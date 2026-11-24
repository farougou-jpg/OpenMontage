"""OpenMontage Studio — export de publication (lot 1.6, volet B).

`exporter_video` est le SEUL chemin de publication du studio. Il ne lève jamais
d'exception : tout doute renvoie un refus (`ToolResult(success=False)`).

Étapes :
1. contrôle qualité conforme ET empreinte SHA-256 du MP4 identique (volet A) ;
2. vérification du manifeste du rendu versionné et de son empreinte ;
3. export versionné `projects/<projet>/exports/vNNN/` via le garde-fou (volet A),
   `export_bundle` refaisant lui-même la vérification (option C) ;
4. empreinte du fichier exporté revérifiée ; en cas d'écart, le sous-dossier `vNNN`
   créé par CET appel est retiré (aucun fichier préexistant n'est touché) ;
5. trace `publication_qc.json`.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tools.base_tool import ToolResult

from lib.studio.budget_guard import StudioBudgetGuard
from lib.studio.narration.tool import PROJECTS_ROOT, check_write_zone, next_version_dir
from lib.studio.project import ProjectLockedError, lock_reason, require_studio_identity, require_writable
from lib.studio.qc.tool import verify_publication


def _sha(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _refus(reason: str) -> ToolResult:
    return ToolResult(success=False, error=f"Publication refusée : {reason}", cost_usd=0.0)


def exporter_video(qc_result: Any, video_path: Any, title: str, project_dir: Any,
                   **export_options: Any) -> ToolResult:
    try:
        return _exporter(qc_result, Path(video_path), title, Path(project_dir), export_options)
    except Exception as exc:  # noqa: BLE001 — fail closed
        return _refus(f"erreur inattendue ({type(exc).__name__}: {exc})")


def _is_immutable_render(project_dir: Path, video: Path) -> bool:
    """Le MP4 doit être un rendu vNNN enregistré, avec son manifeste d'empreinte."""
    try:
        resolved = video.resolve()
        renders = (project_dir / "renders").resolve()
        resolved.relative_to(renders)
        render_dir = resolved.parent
        if not re.fullmatch(r"v\d{3}", render_dir.name):
            return False
        info = json.loads((render_dir / "rendu.json").read_text(encoding="utf-8"))
        return (isinstance(info, dict)
                and info.get("mp4") == resolved.name
                and info.get("sha256") == _sha(resolved)
                and info.get("taille_octets") == resolved.stat().st_size)
    except (OSError, ValueError, KeyError, TypeError, RuntimeError):
        return False


def _exporter(qc_result, video: Path, title: str, project_dir: Path, options: dict) -> ToolResult:
    from tools.publishers.export_bundle import ExportBundle

    # Le projet doit avoir une identité Studio explicite, même pour une republication.
    try:
        project_dir = require_studio_identity(project_dir)
    except ProjectLockedError as exc:
        return _refus(str(exc))

    reason_locked = lock_reason(project_dir)
    if reason_locked:
        # Seul le verrou posé par une publication antérieure est réversible pour
        # republier un rendu déjà figé. Le pilote et les zones protégées restent interdits.
        if not reason_locked.startswith("projet exporté ("):
            return _refus(f"projet verrouillé : {reason_locked}")
        if not _is_immutable_render(project_dir, video):
            return _refus("republication refusée : seul un rendu versionné et immuable est autorisé")
    else:
        try:
            project_dir = require_writable(project_dir)
        except ProjectLockedError as exc:
            return _refus(str(exc))

    ok, reason = verify_publication(qc_result, video, studio_root=project_dir)
    if not ok:
        return _refus(reason)
    expected = json.loads(Path(qc_result.data["rapport_json"]).read_text(encoding="utf-8"))["mp4"]["sha256"]

    exports_root = check_write_zone(project_dir / "exports", PROJECTS_ROOT)
    for forbidden in ("video_path", "export_dir", "studio_qc_report"):
        options.pop(forbidden, None)

    out = None
    try:
        out = next_version_dir(exports_root)
        guard = StudioBudgetGuard(project_dir)
        export_tool = ExportBundle()
        # Marqueur interne à l'instance : un appel direct à ExportBundle ne peut
        # pas contourner le verrou et la politique de republication du Studio.
        export_tool._studio_export_authorized = True
        res = guard.run(export_tool, {"video_path": str(video), "title": title,
                                     "export_dir": str(out), **options}, qc_result=qc_result)
        if not res.success:
            shutil.rmtree(out, ignore_errors=True)
            return _refus(res.error or "export en échec")
        exported = Path(res.data["export_path"]) / "video" / f"output{video.suffix or '.mp4'}"
        if not exported.is_file() or _sha(exported) != expected:
            shutil.rmtree(out, ignore_errors=True)
            return _refus("le fichier exporté ne correspond pas au MP4 contrôlé ; export retiré")
        trace = out / "publication_qc.json"
        trace.write_text(json.dumps({
            "rapport_qc": qc_result.data["rapport_json"], "mp4_sha256": expected,
            "fichier_publie": str(exported), "date": datetime.now(timezone.utc).isoformat(),
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        return ToolResult(success=True, data={**res.data, "version_dir": str(out),
                                              "publication_qc": str(trace), "mp4_sha256": expected},
                          artifacts=[*res.artifacts, str(trace)], cost_usd=0.0)
    except Exception:
        if out is not None:
            shutil.rmtree(out, ignore_errors=True)
        raise
