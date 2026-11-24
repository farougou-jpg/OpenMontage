import json
from pathlib import Path
from backlot.studio_reader import read_studio_project


def put_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_reads_script_and_validations_as_source_data(tmp_path):
    put_json(tmp_path / "script.json", {"sections": [{"id": "s1"}]})
    put_json(tmp_path / "validations.json", {
        "pipeline": "studio-fr",
        "validations": [{"objet": "scénario", "statut": "validé"}]
    })
    result = read_studio_project(tmp_path)
    assert result["script_sections"] == [{"id": "s1"}]
    assert result["validation_items"][0]["statut"] == "validé"
    assert "checkpoints" not in result and "stages" not in result


def test_reads_storyboard_versions_and_images(tmp_path):
    for version in ("v001", "v002"):
        folder = tmp_path / "storyboard" / version
        put_json(folder / "storyboard.json", {"scenes": [{"numero": 1}]})
        put_json(folder / "props_storyboard.json", {"assets": []})
        (folder / "scenes").mkdir()
        (folder / "scenes" / "scene_01.png").write_bytes(b"image")
        (folder / "planche.png").write_bytes(b"board")
    result = read_studio_project(tmp_path)
    assert [v["version"] for v in result["storyboard_versions"]] == ["v001", "v002"]
    assert len(result["storyboard_versions"][1]["scene_images"]) == 1
    assert result["storyboard_versions"][1]["board_image"].endswith("planche.png")


def test_reads_render_video_and_props(tmp_path):
    folder = tmp_path / "renders" / "v001"
    folder.mkdir(parents=True)
    (folder / "clip.mp4").write_bytes(b"video")
    put_json(folder / "props_rendu.json", {"theme": "flat-motion-graphics"})
    result = read_studio_project(tmp_path)
    assert result["render_versions"][0]["videos"] == ["renders/v001/clip.mp4"]
    assert result["summary"]["video_count"] == 1


def test_reads_qc_reports(tmp_path):
    put_json(tmp_path / "controle" / "v001" / "rapport_qc.json", {"conforme": True})
    result = read_studio_project(tmp_path)
    assert result["qc_reports"][0]["data"]["conforme"] is True


def test_missing_and_invalid_files_are_reported(tmp_path):
    result = read_studio_project(tmp_path)
    assert result["script"]["error"] == "missing"
    (tmp_path / "script.json").write_text("{bad", encoding="utf-8")
    result = read_studio_project(tmp_path)
    assert result["script"]["error"].startswith("invalid_json:")


def test_reader_does_not_modify_files(tmp_path):
    path = tmp_path / "validations.json"
    original = '{"validations":[{"statut":"validé"}]}'
    path.write_text(original, encoding="utf-8")
    before = path.read_bytes()
    read_studio_project(tmp_path)
    assert path.read_bytes() == before
