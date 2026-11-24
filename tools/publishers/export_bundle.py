"""Local export bundler — the first PUBLISH-tier tool.

Every pipeline ends in a `publish` stage that produces a `publish_log` artifact,
but `tools/publishers/` shipped empty, so the mechanical packaging (copying the
render, writing metadata files, laying out the export directory, and emitting a
schema-valid `publish_log`) had to be hand-rolled by the agent each time.

This tool does that packaging deterministically and locally — no external
account, no upload, no cost. It takes the final render path plus the SEO
metadata the publish-director skill prepares and writes a self-contained export
bundle a creator can hand to any platform, returning a validated `publish_log`
entry with `status: "exported"`.

A networked publisher (e.g. a YouTube uploader) can be added later as a separate
`provider` under the same `publish` capability.
"""

from __future__ import annotations

import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from tools.base_tool import (
    BaseTool,
    Determinism,
    ExecutionMode,
    ResourceProfile,
    ToolResult,
    ToolRuntime,
    ToolStability,
    ToolStatus,
    ToolTier,
)


class ExportBundle(BaseTool):
    name = "export_bundle"
    version = "0.1.0"
    tier = ToolTier.PUBLISH
    capability = "publish"
    provider = "local"
    stability = ToolStability.BETA
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.DETERMINISTIC
    runtime = ToolRuntime.LOCAL

    dependencies = []  # pure filesystem packaging
    install_instructions = "No setup required — runs locally with the Python standard library."

    agent_skills = []

    capabilities = ["package_export", "write_publish_log"]
    supports = {
        "local_offline": True,
        "free": True,
        "uploads": False,
    }
    best_for = [
        "packaging a finished render for hand-off to any platform",
        "producing a schema-valid publish_log without an external account",
        "offline / no-API-key publishing",
    ]
    not_good_for = [
        "uploading directly to YouTube/TikTok/etc. (no network publish)",
        "generating SEO metadata or thumbnails (the publish-director prepares those)",
    ]

    input_schema = {
        "type": "object",
        "required": ["video_path", "title"],
        "properties": {
            "video_path": {
                "type": "string",
                "description": "Path to the final rendered video (from render_report.outputs[].path).",
            },
            "title": {"type": "string", "description": "Video title / SEO title."},
            "project_name": {
                "type": "string",
                "description": "Project name; used for the export folder. Defaults to the video's parent-of-parent dir name.",
            },
            "export_dir": {
                "type": "string",
                "description": "Override the export root. Defaults to 'exports/<project_name>'.",
            },
            "description": {"type": "string"},
            "tags": {"type": "array", "items": {"type": "string"}},
            "hashtags": {"type": "array", "items": {"type": "string"}},
            "chapters": {
                "type": "array",
                "items": {
                    "type": "object",
                    "description": "Either {start_seconds, title} or {time, label}.",
                },
            },
            "subtitles_path": {"type": "string"},
            "thumbnail_path": {"type": "string"},
            "thumbnail_concept": {
                "type": "object",
                "description": "Thumbnail concept JSON when no rendered thumbnail exists.",
            },
            "platform": {
                "type": "string",
                "description": "Target platform label for the publish_log entry. Defaults to 'local'.",
            },
            "visibility": {"type": "string", "enum": ["public", "private", "unlisted"]},
            "timestamp": {
                "type": "string",
                "description": "Override the ISO-8601 timestamp (mainly for deterministic tests).",
            },
            "studio_qc_report": {
                "type": "string",
                "description": "OpenMontage Studio only: path to the conformant rapport_qc.json of this exact MP4. "
                               "Required (and verified by SHA-256) when the video or export_dir is inside a "
                               "Studio project; ignored otherwise.",
            },
        },
    }
    output_schema = {
        "type": "object",
        "properties": {
            "publish_log": {"type": "object"},
            "export_path": {"type": "string"},
            "files_written": {"type": "array", "items": {"type": "string"}},
        },
    }

    resource_profile = ResourceProfile(
        cpu_cores=1, ram_mb=128, vram_mb=0, disk_mb=0, network_required=False
    )
    side_effects = ["writes an export bundle directory to disk"]
    user_visible_verification = [
        "Open the export folder and confirm the video, metadata, and chapters are present and correct",
    ]

    # ---- Helpers ----

    @staticmethod
    def _format_chapter_time(seconds: float) -> str:
        seconds = int(round(seconds))
        h, rem = divmod(seconds, 3600)
        m, s = divmod(rem, 60)
        if h:
            return f"{h}:{m:02d}:{s:02d}"
        return f"{m}:{s:02d}"

    def _chapter_lines(self, chapters: list[dict[str, Any]]) -> list[str]:
        lines: list[str] = []
        for ch in chapters:
            label = ch.get("title") or ch.get("label") or ""
            if "start_seconds" in ch or "time_seconds" in ch:
                ts = self._format_chapter_time(ch.get("start_seconds", ch.get("time_seconds", 0)))
            elif "time" in ch:
                ts = str(ch["time"])
            else:
                ts = "0:00"
            lines.append(f"{ts} - {label}".rstrip(" -"))
        return lines

    # ---- Execution ----

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        video_path = Path(inputs["video_path"]).expanduser()
        if not video_path.is_file():
            return ToolResult(success=False, error=f"video_path not found: {video_path}")

        # OpenMontage Studio (lot 1.6) : seulement pour les projets du studio, publication
        # refusée sans contrôle qualité conforme portant sur ce MP4 exact. Les autres projets
        # ne passent par aucune vérification supplémentaire (comportement inchangé).
        studio_refusal = self._studio_publication_refusal(video_path, inputs)
        if studio_refusal:
            return ToolResult(success=False, error=studio_refusal)

        title = inputs["title"]
        project_name = inputs.get("project_name") or self._infer_project_name(video_path)

        # Explicitly-provided optional assets must exist — silently dropping them
        # would ship a publish package missing part of an approved deliverable.
        for key in ("subtitles_path", "thumbnail_path"):
            val = inputs.get(key)
            if val and not Path(val).expanduser().is_file():
                return ToolResult(success=False, error=f"{key} provided but not found: {val}")

        export_root = (
            Path(inputs["export_dir"]).expanduser()
            if inputs.get("export_dir")
            else self._default_export_dir(video_path, project_name)
        )

        video_dir = export_root / "video"
        meta_dir = export_root / "metadata"
        thumb_dir = export_root / "thumbnails"
        for d in (video_dir, meta_dir, thumb_dir):
            d.mkdir(parents=True, exist_ok=True)

        files_written: list[str] = []

        # Video
        out_video = video_dir / f"output{video_path.suffix or '.mp4'}"
        shutil.copy2(video_path, out_video)
        files_written.append(str(out_video))

        # Subtitles (optional)
        subs_in = inputs.get("subtitles_path")
        if subs_in:
            subs_in = Path(subs_in).expanduser()
            if subs_in.is_file():
                out_subs = video_dir / f"subtitles{subs_in.suffix or '.srt'}"
                shutil.copy2(subs_in, out_subs)
                files_written.append(str(out_subs))

        description = inputs.get("description", "")
        tags = inputs.get("tags", []) or []
        hashtags = inputs.get("hashtags", []) or []
        chapters = inputs.get("chapters", []) or []
        chapter_lines = self._chapter_lines(chapters)

        # metadata.json
        metadata = {
            "title": title,
            "description": description,
            "tags": tags,
            "hashtags": hashtags,
            "chapters": chapters,
        }
        meta_json = meta_dir / "metadata.json"
        meta_json.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        files_written.append(str(meta_json))

        # description.txt (description + chapters appended, ready to paste)
        desc_parts = [description] if description else []
        if chapter_lines:
            desc_parts.append("\n".join(chapter_lines))
        desc_txt = meta_dir / "description.txt"
        desc_txt.write_text("\n\n".join(desc_parts) + ("\n" if desc_parts else ""), encoding="utf-8")
        files_written.append(str(desc_txt))

        # tags.txt (one per line)
        if tags:
            tags_txt = meta_dir / "tags.txt"
            tags_txt.write_text("\n".join(tags) + "\n", encoding="utf-8")
            files_written.append(str(tags_txt))

        # chapters.txt
        if chapter_lines:
            chapters_txt = meta_dir / "chapters.txt"
            chapters_txt.write_text("\n".join(chapter_lines) + "\n", encoding="utf-8")
            files_written.append(str(chapters_txt))

        # Thumbnail: real image if given, else concept JSON
        thumb_in = inputs.get("thumbnail_path")
        if thumb_in and Path(thumb_in).expanduser().is_file():
            thumb_in = Path(thumb_in).expanduser()
            out_thumb = thumb_dir / f"thumbnail{thumb_in.suffix or '.png'}"
            shutil.copy2(thumb_in, out_thumb)
            files_written.append(str(out_thumb))
        elif inputs.get("thumbnail_concept"):
            concept = thumb_dir / "concept.json"
            concept.write_text(json.dumps(inputs["thumbnail_concept"], indent=2), encoding="utf-8")
            files_written.append(str(concept))

        timestamp = inputs.get("timestamp") or datetime.now(timezone.utc).isoformat()
        entry: dict[str, Any] = {
            "platform": inputs.get("platform", "local"),
            "status": "exported",
            "export_path": str(export_root),
            "timestamp": timestamp,
            "metadata_used": {
                "title": title,
                "description": description,
                "hashtags": hashtags,
                "chapters": chapters,
            },
        }
        if inputs.get("visibility"):
            entry["visibility"] = inputs["visibility"]

        publish_log = {"version": "1.0", "entries": [entry]}

        # Validate against the canonical schema so a bad entry fails here, not at checkpoint.
        try:
            from schemas.artifacts import validate_artifact

            validate_artifact("publish_log", publish_log)
        except Exception as exc:  # pragma: no cover - defensive
            return ToolResult(success=False, error=f"publish_log failed schema validation: {exc}")

        return ToolResult(
            success=True,
            data={
                "publish_log": publish_log,
                "export_path": str(export_root),
                "files_written": files_written,
            },
            artifacts=[str(out_video)],
        )

    # ---- OpenMontage Studio : verrou de publication (projets du studio uniquement) ----

    _STUDIO_MARKER = "studio_project.json"
    _STUDIO_ARTIFACT_GLOBS = (
        "assets/narration/v[0-9][0-9][0-9]/timing_fr.json",
        "storyboard/v[0-9][0-9][0-9]/storyboard.json",
        "controle/v[0-9][0-9][0-9]/rapport_qc.json",
    )

    @classmethod
    def _is_studio_project(cls, directory: Path) -> bool:
        if (directory / cls._STUDIO_MARKER).is_file():
            return True
        return any(next(directory.glob(g), None) is not None for g in cls._STUDIO_ARTIFACT_GLOBS)

    @classmethod
    def _studio_project_root(cls, *paths: Any) -> Optional[Path]:
        """Racine du projet Studio contenant la vidéo ou le dossier d'export, sinon None."""
        for p in paths:
            if not p:
                continue
            try:
                current = Path(p).expanduser().resolve()
            except (OSError, RuntimeError):
                continue
            for directory in (current, *current.parents):
                try:
                    if directory.is_dir() and cls._is_studio_project(directory):
                        return directory
                except OSError:
                    continue
        return None

    def _studio_publication_refusal(self, video_path: Path, inputs: dict[str, Any]) -> Optional[str]:
        root = self._studio_project_root(video_path, inputs.get("export_dir"))
        if root is None:
            return None  # projet hors studio : aucun changement de comportement
        if getattr(self, "_studio_export_authorized", False) is not True:
            return ("Publication Studio refusée : utiliser exclusivement "
                    "`lib.studio.publish.exporter_video`.")
        try:
            from lib.studio.project import lock_reason, require_studio_identity, require_writable
            root = require_studio_identity(root)
            locked = lock_reason(root)
            if locked:
                if not locked.startswith("projet exporté ("):
                    return f"Publication Studio refusée : projet verrouillé ({locked})."
            else:
                require_writable(root)

            video = video_path.resolve()
            video.relative_to((root / "renders").resolve())
            render_dir = video.parent
            if not re.fullmatch(r"v\d{3}", render_dir.name):
                return "Publication Studio refusée : le MP4 doit provenir d'un rendu versionné vNNN."
            manifest = json.loads((render_dir / "rendu.json").read_text(encoding="utf-8"))
            if (not isinstance(manifest, dict) or manifest.get("mp4") != video.name
                    or manifest.get("sha256") != self._sha256_file(video)
                    or manifest.get("taille_octets") != video.stat().st_size):
                return "Publication Studio refusée : manifeste du rendu absent ou empreinte différente."

            export_dir = Path(inputs.get("export_dir") or "").expanduser().resolve()
            export_dir.relative_to((root / "exports").resolve())
            if not re.fullmatch(r"v\d{3}", export_dir.name):
                return "Publication Studio refusée : utiliser une nouvelle version d'export vNNN."
            if export_dir.exists() and any(export_dir.iterdir()):
                return "Publication Studio refusée : le dossier d'export doit être neuf."
            from lib.studio.qc.tool import verify_report_for_publication
            ok, reason = verify_report_for_publication(inputs.get("studio_qc_report"), video_path, root)
            return None if ok else f"Publication Studio refusée : {reason}"
        except Exception as exc:  # fail closed
            return f"Publication Studio refusée : validation impossible ({type(exc).__name__}: {exc})"

    @staticmethod
    def _sha256_file(path: Path) -> str:
        import hashlib
        digest = hashlib.sha256()
        with open(path, "rb") as stream:
            for chunk in iter(lambda: stream.read(1 << 20), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _default_export_dir(video_path: Path, project_name: str) -> Path:
        """Keep run output inside the project workspace.

        When the render lives at ``projects/<name>/renders/...`` (the OpenMontage
        convention), default the bundle to ``projects/<name>/exports/`` alongside
        ``artifacts/``, ``assets/`` and ``renders/``. Otherwise fall back to a
        top-level ``exports/<project_name>/``.
        """
        resolved = video_path.resolve()
        if resolved.parent.name == "renders":
            return resolved.parent.parent / "exports"
        return Path("exports") / project_name

    @staticmethod
    def _infer_project_name(video_path: Path) -> str:
        # projects/<name>/renders/final.mp4 -> <name>; fall back to the file stem.
        parents = video_path.resolve().parents
        if len(parents) >= 2:
            return parents[1].name
        return video_path.stem
