import json
from pathlib import Path

from backlot.project_metadata import read_project_metadata
from lib.paths import PROJECTS_DIR
from lib.pipeline_loader import load_pipeline_readonly


def _write_json(path: Path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_studio_created_at_is_read_from_studio_project_marker(tmp_path):
    _write_json(tmp_path / "studio_project.json", {
        "studio": "OpenMontage Studio",
        "cree_le": "2026-11-22T10:00:00+00:00",
    })
    _write_json(tmp_path / "validations.json", {
        "projet": "projet-test",
        "titre": "Projet test",
        "pipeline": "studio-fr",
        "validations": [],
    })
    result = read_project_metadata(tmp_path)
    assert result["created_at"] == "2026-11-22T10:00:00+00:00"
    assert result["source_format"] == "studio"


def test_backlot_created_at_keeps_priority_over_studio_created_at(tmp_path):
    _write_json(tmp_path / "project.json", {
        "project_id": "p1",
        "created_at": "2026-01-01T00:00:00Z",
    })
    _write_json(tmp_path / "studio_project.json", {
        "cree_le": "2026-02-01T00:00:00Z",
    })
    result = read_project_metadata(tmp_path)
    assert result["created_at"] == "2026-01-01T00:00:00Z"
    assert result["conflicts"]["created_at"] is True


def test_legacy_studio_created_at_in_validations_remains_supported(tmp_path):
    _write_json(tmp_path / "validations.json", {
        "projet": "p1",
        "cree_le": "2026-03-01T00:00:00Z",
    })
    result = read_project_metadata(tmp_path)
    assert result["created_at"] == "2026-03-01T00:00:00Z"


def test_pipeline_cached_manifest_isolated_between_callers():
    first = load_pipeline_readonly("studio-fr")
    original = first["stages"][0]["name"]
    first["stages"][0]["name"] = "caller-corruption"
    second = load_pipeline_readonly("studio-fr")
    assert second["stages"][0]["name"] == original


def test_projects_dir_is_canonical_path_object():
    assert isinstance(PROJECTS_DIR, Path)
