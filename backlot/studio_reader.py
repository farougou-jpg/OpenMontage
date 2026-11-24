"""Read-only reader for OpenMontage Studio project artifacts."""
from __future__ import annotations
import json
import re
from pathlib import Path
from typing import Any

# Studio versions are exactly "vNNN" (same rule as lib/studio/project.py VERSION_RE).
_VERSION_RE = re.compile(r"v\d{3}")
_AUDIO_EXT = {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg"}
_VIDEO_EXT = {".mp4", ".webm", ".mov", ".mkv"}
_IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp"}


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except FileNotFoundError:
        return None, "missing"
    except (OSError, UnicodeError) as exc:
        return None, f"read_error: {exc}"
    except json.JSONDecodeError as exc:
        return None, f"invalid_json: {exc}"


def _json_file(path: Path, root: Path):
    data, error = _read_json(path)
    return {
        "path": path.relative_to(root).as_posix(),
        "exists": path.is_file(),
        "valid": error is None and data is not None,
        "data": data,
        "error": error,
    }


def _version_dirs(parent: Path):
    if not parent.is_dir():
        return []
    return sorted((p for p in parent.iterdir()
                   if p.is_dir() and _VERSION_RE.fullmatch(p.name)),
                  key=lambda p: p.name)


def _files(folder: Path, root: Path, extensions: set[str]) -> list[str]:
    """Direct files of `folder` with one of `extensions`, as project-relative paths."""
    if not folder.is_dir():
        return []
    return [
        p.relative_to(root).as_posix()
        for p in sorted(folder.iterdir())
        if p.is_file() and p.suffix.lower() in extensions
    ]


def _optional_file(path: Path, root: Path):
    return path.relative_to(root).as_posix() if path.is_file() else None


def _read_storyboard_version(folder: Path, root: Path):
    scenes = folder / "scenes"
    return {
        "version": folder.name,
        "storyboard": _json_file(folder / "storyboard.json", root),
        "props": _json_file(folder / "props_storyboard.json", root),
        "scene_images": [
            p.relative_to(root).as_posix()
            for p in sorted(scenes.iterdir())
            if p.is_file() and p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}
        ] if scenes.is_dir() else [],
        "board_image": (
            (folder / "planche.png").relative_to(root).as_posix()
            if (folder / "planche.png").is_file() else None
        ),
        "html": (
            (folder / "storyboard.html").relative_to(root).as_posix()
            if (folder / "storyboard.html").is_file() else None
        ),
        "markdown": (
            (folder / "storyboard.md").relative_to(root).as_posix()
            if (folder / "storyboard.md").is_file() else None
        ),
    }


def _read_render_version(folder: Path, root: Path):
    return {
        "version": folder.name,
        "videos": [
            p.relative_to(root).as_posix()
            for p in sorted(folder.iterdir())
            if p.is_file() and p.suffix.lower() in {".mp4", ".webm", ".mov", ".mkv"}
        ],
        "props": _json_file(folder / "props_rendu.json", root),
    }


def _read_narration_version(folder: Path, root: Path):
    """Narration files of assets/narration/vNNN, reported as stored (no verdict derived)."""
    return {
        "version": folder.name,
        "audio": _files(folder, root, _AUDIO_EXT),
        "segments": _files(folder / "segments", root, _AUDIO_EXT),
        "timing": _json_file(folder / "timing_fr.json", root),
        "report": _json_file(folder / "controle" / "rapport_narration.json", root),
        "report_markdown": _optional_file(folder / "controle" / "rapport_narration.md", root),
    }


def _read_export_version(folder: Path, root: Path):
    """Export package of exports/vNNN, reported as stored (no verdict derived)."""
    control = folder / "controle"
    return {
        "version": folder.name,
        "videos": _files(folder / "video", root, _VIDEO_EXT),
        "thumbnails": _files(folder / "thumbnails", root, _IMAGE_EXT),
        "metadata": _json_file(folder / "metadata" / "metadata.json", root),
        "description": _optional_file(folder / "metadata" / "description.txt", root),
        "publication_qc": _json_file(folder / "publication_qc.json", root),
        "qc_reports": [
            _json_file(p, root) for p in sorted(control.glob("*.json")) if p.is_file()
        ] if control.is_dir() else [],
    }


def read_studio_project(project_dir: Path) -> dict[str, Any]:
    """Read Studio JSON and artifact indexes; never write or derive progress."""
    root = Path(project_dir).resolve()
    script = _json_file(root / "script.json", root)
    validations = _json_file(root / "validations.json", root)

    storyboards = [
        _read_storyboard_version(p, root)
        for p in _version_dirs(root / "storyboard")
    ]
    renders = [
        _read_render_version(p, root)
        for p in _version_dirs(root / "renders")
    ]
    narrations = [
        _read_narration_version(p, root)
        for p in _version_dirs(root / "assets" / "narration")
    ]
    exports = [
        _read_export_version(p, root)
        for p in _version_dirs(root / "exports")
    ]

    qc_reports = []
    control = root / "controle"
    if control.is_dir():
        qc_reports = [
            _json_file(p, root)
            for p in sorted(control.rglob("rapport_qc.json"))
        ]

    script_data = script["data"] if script["valid"] else None
    validation_data = validations["data"] if validations["valid"] else None
    sections = script_data.get("sections") if isinstance(script_data, dict) else None
    validation_items = (
        validation_data.get("validations")
        if isinstance(validation_data, dict) else None
    )
    sections = sections if isinstance(sections, list) else []
    validation_items = validation_items if isinstance(validation_items, list) else []

    return {
        "project_dir": str(root),
        "script": script,
        "script_sections": sections,
        "validations": validations,
        "validation_items": validation_items,
        "storyboard_versions": storyboards,
        "render_versions": renders,
        "narration_versions": narrations,
        "export_versions": exports,
        "qc_reports": qc_reports,
        "summary": {
            "storyboard_version_count": len(storyboards),
            "render_version_count": len(renders),
            "narration_version_count": len(narrations),
            "export_version_count": len(exports),
            "video_count": sum(len(v["videos"]) for v in renders),
            "qc_report_count": len(qc_reports),
            "script_section_count": len(sections),
            "studio_validation_count": len(validation_items),
        },
    }
