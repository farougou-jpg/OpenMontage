import json
from pathlib import Path

from backlot.project_metadata import read_project_metadata


def write_json(folder: Path, name: str, value):
    (folder / name).write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def test_backlot_only(tmp_path):
    write_json(tmp_path, "project.json", {
        "project_id": "p1", "title": "Backlot title",
        "pipeline_type": "video", "created_at": "2026-01-01"
    })
    result = read_project_metadata(tmp_path)
    assert result["source_format"] == "backlot"
    assert result["title"] == "Backlot title"
    assert result["pipeline_type"] == "video"
    assert result["has_marker"] is True


def test_studio_uses_validations_root_metadata_and_script_title_fallback(tmp_path):
    write_json(tmp_path, "studio_project.json", {
        "studio": "OpenMontage Studio", "version": 1,
        "regle": "publication uniquement avec contrôle qualité conforme"
    })
    write_json(tmp_path, "script.json", {
        "version": "1.0", "title": "Titre du script", "sections": []
    })
    write_json(tmp_path, "validations.json", {
        "projet": "pilote-gestion-temps",
        "titre": "Titre complet Studio",
        "pipeline": "studio-fr",
        "validations": [{"statut": "validé"}],
        "etapes_suivantes_non_autorisees": ["publication"]
    })
    result = read_project_metadata(tmp_path)
    assert result["project_id"] == "pilote-gestion-temps"
    assert result["title"] == "Titre complet Studio"
    assert result["pipeline_type"] == "studio-fr"
    assert result["source_format"] == "studio"
    assert result["has_marker"] is True


def test_studio_title_falls_back_to_script_title(tmp_path):
    write_json(tmp_path, "script.json", {"title": "Titre du script"})
    result = read_project_metadata(tmp_path)
    assert result["title"] == "Titre du script"
    assert result["pipeline_type"] == "unknown"
    assert result["source_format"] == "studio"


def test_hybrid_backlot_values_have_priority(tmp_path):
    write_json(tmp_path, "project.json", {
        "project_id": "p1", "title": "Backlot", "pipeline_type": "backlot-pipe"
    })
    write_json(tmp_path, "validations.json", {
        "projet": "p1", "titre": "Studio", "pipeline": "studio-fr"
    })
    result = read_project_metadata(tmp_path)
    assert result["source_format"] == "hybrid"
    assert result["title"] == "Backlot"
    assert result["pipeline_type"] == "backlot-pipe"
    assert result["metadata_conflict"] is True
    assert result["conflicts"]["title"] is True
    assert result["conflicts"]["pipeline_type"] is True


def test_hybrid_studio_fills_missing_backlot_values(tmp_path):
    write_json(tmp_path, "project.json", {"project_id": "p1"})
    write_json(tmp_path, "validations.json", {
        "projet": "p1", "titre": "Studio title", "pipeline": "studio-fr"
    })
    result = read_project_metadata(tmp_path)
    assert result["title"] == "Studio title"
    assert result["pipeline_type"] == "studio-fr"
    assert result["metadata_conflict"] is False


def test_studio_validations_array_is_not_progress(tmp_path):
    write_json(tmp_path, "validations.json", {
        "projet": "p1", "titre": "Studio title", "pipeline": "studio-fr",
        "validations": [
            {"numero": 1, "objet": "scénario", "statut": "validé"},
            {"numero": 2, "objet": "rendu", "statut": "validé"}
        ]
    })
    result = read_project_metadata(tmp_path)
    assert result["pipeline_type"] == "studio-fr"
    assert "stages" not in result
    assert "checkpoints" not in result
    assert "validations" not in result


def test_folder_name_fallback_without_metadata(tmp_path):
    result = read_project_metadata(tmp_path)
    assert result["project_id"] == tmp_path.name
    assert result["title"] == tmp_path.name.replace("-", " ").title()
    assert result["pipeline_type"] == "unknown"
    assert result["source_format"] == "unknown"
    assert result["has_marker"] is False


def test_invalid_json_is_ignored(tmp_path):
    (tmp_path / "validations.json").write_text("{bad json", encoding="utf-8")
    result = read_project_metadata(tmp_path)
    assert result["pipeline_type"] == "unknown"
    assert result["has_marker"] is False


def test_non_object_json_is_ignored(tmp_path):
    (tmp_path / "validations.json").write_text("[]", encoding="utf-8")
    result = read_project_metadata(tmp_path)
    assert result["source_format"] == "unknown"
    assert result["has_marker"] is False


def test_missing_directory_is_safe(tmp_path):
    result = read_project_metadata(tmp_path / "missing")
    assert result["pipeline_type"] == "unknown"
    assert result["has_marker"] is False


def test_reader_does_not_modify_files(tmp_path):
    original = '{"projet":"p1","titre":"Studio","pipeline":"studio-fr"}'
    path = tmp_path / "validations.json"
    path.write_text(original, encoding="utf-8")
    before = path.read_bytes()
    read_project_metadata(tmp_path)
    assert path.read_bytes() == before


def test_created_at_remains_none_when_not_explicitly_present(tmp_path):
    write_json(tmp_path, "validations.json", {
        "projet": "p1", "titre": "Studio", "pipeline": "studio-fr"
    })
    result = read_project_metadata(tmp_path)
    assert result["created_at"] is None
