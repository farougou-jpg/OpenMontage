"""Read-only normalization of Backlot and OpenMontage Studio project metadata.

This module reads descriptive metadata only. In particular, it never interprets
Studio validations as Backlot checkpoints or derives production progress.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _read_object(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _text(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _conflict(left: str | None, right: str | None) -> bool:
    return left is not None and right is not None and left != right


def read_project_metadata(project_dir: Path) -> dict[str, Any]:
    """Return normalized descriptive metadata without changing project files.

    Backlot project.json has priority when it provides a value. Studio metadata
    is read from validations.json (top-level descriptive keys only), then
    script.json for a title fallback. studio_project.json is treated as an
    application marker/configuration file, not as the project's descriptive
    metadata.
    """
    project_dir = Path(project_dir)
    folder_id = project_dir.name

    backlot = _read_object(project_dir / "project.json")
    studio_marker = _read_object(project_dir / "studio_project.json")
    validations = _read_object(project_dir / "validations.json")
    script = _read_object(project_dir / "script.json")

    # Studio's validations.json contains descriptive metadata at the root and
    # a separate "validations" list. Only the root keys are used here.
    studio_project_id = _text((validations or {}).get("projet"))
    studio_title = _text((validations or {}).get("titre"))
    if studio_title is None:
        studio_title = _text((script or {}).get("title"))
    studio_pipeline = _text((validations or {}).get("pipeline"))
    # New Studio projects store their creation timestamp in studio_project.json.
    # Keep the legacy validations.json fallback for older projects.
    studio_created = (
        _text((studio_marker or {}).get("cree_le"))
        or _text((validations or {}).get("cree_le"))
    )

    backlot_project_id = _text((backlot or {}).get("project_id"))
    backlot_title = _text((backlot or {}).get("title"))
    backlot_pipeline = _text((backlot or {}).get("pipeline_type"))
    backlot_created = _text((backlot or {}).get("created_at"))

    project_id = backlot_project_id or studio_project_id or folder_id
    title = backlot_title or studio_title or folder_id.replace("-", " ").title()
    pipeline_type = backlot_pipeline or studio_pipeline or "unknown"
    created_at = backlot_created or studio_created

    has_backlot_marker = backlot is not None
    has_studio_marker = (
        studio_marker is not None
        or validations is not None
        or script is not None
    )
    if has_backlot_marker and has_studio_marker:
        source_format = "hybrid"
    elif has_backlot_marker:
        source_format = "backlot"
    elif has_studio_marker:
        source_format = "studio"
    else:
        source_format = "unknown"

    conflicts = {
        "project_id": _conflict(backlot_project_id, studio_project_id),
        "title": _conflict(backlot_title, studio_title),
        "pipeline_type": _conflict(backlot_pipeline, studio_pipeline),
        "created_at": _conflict(backlot_created, studio_created),
    }

    return {
        "project_id": project_id,
        "title": title,
        "pipeline_type": pipeline_type,
        "created_at": created_at,
        "source_format": source_format,
        "has_marker": has_backlot_marker or has_studio_marker,
        "metadata_conflict": any(conflicts.values()),
        "conflicts": conflicts,
    }
