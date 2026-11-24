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


def test_only_vnnn_folders_are_versions(tmp_path):
    for name in ("v001", "v1", "v0002", "vieux", "video"):
        put_json(tmp_path / "storyboard" / name / "storyboard.json", {"scenes": []})
        (tmp_path / "renders" / name).mkdir(parents=True)
        (tmp_path / "assets" / "narration" / name).mkdir(parents=True)
        (tmp_path / "exports" / name).mkdir(parents=True)
    result = read_studio_project(tmp_path)
    for key in ("storyboard_versions", "render_versions", "narration_versions", "export_versions"):
        assert [v["version"] for v in result[key]] == ["v001"], key


def test_reads_narration_versions(tmp_path):
    folder = tmp_path / "assets" / "narration" / "v001"
    (folder / "segments").mkdir(parents=True)
    (folder / "narration_fr.wav").write_bytes(b"wav")
    (folder / "narration_fr_brut.wav").write_bytes(b"wav")
    (folder / "segments" / "accroche.wav").write_bytes(b"wav")
    put_json(folder / "timing_fr.json", [{"cut": "accroche", "debut": 0.3}])
    put_json(folder / "controle" / "rapport_narration.json", {"conforme": True, "profil": "B"})
    (folder / "controle" / "rapport_narration.md").write_text("# rapport", encoding="utf-8")
    (tmp_path / "assets" / "narration" / "essais").mkdir()   # essais non versionnés : ignorés
    result = read_studio_project(tmp_path)
    nar = result["narration_versions"]
    assert [v["version"] for v in nar] == ["v001"]
    assert nar[0]["audio"] == ["assets/narration/v001/narration_fr.wav",
                               "assets/narration/v001/narration_fr_brut.wav"]
    assert nar[0]["segments"] == ["assets/narration/v001/segments/accroche.wav"]
    assert nar[0]["timing"]["data"][0]["cut"] == "accroche"
    assert nar[0]["report"]["data"]["conforme"] is True
    assert nar[0]["report_markdown"] == "assets/narration/v001/controle/rapport_narration.md"
    assert result["summary"]["narration_version_count"] == 1


def test_reads_export_versions(tmp_path):
    folder = tmp_path / "exports" / "v001"
    (folder / "video").mkdir(parents=True)
    (folder / "video" / "film-fr-v001.mp4").write_bytes(b"video")
    put_json(folder / "metadata" / "metadata.json", {"title": "Film"})
    (folder / "metadata" / "description.txt").write_text("Description", encoding="utf-8")
    put_json(folder / "publication_qc.json", {"mp4_sha256": "abc"})
    put_json(folder / "controle" / "rapport_qc.json", {"conforme": True})
    result = read_studio_project(tmp_path)
    exp = result["export_versions"][0]
    assert exp["version"] == "v001"
    assert exp["videos"] == ["exports/v001/video/film-fr-v001.mp4"]
    assert exp["metadata"]["data"]["title"] == "Film"
    assert exp["description"] == "exports/v001/metadata/description.txt"
    assert exp["publication_qc"]["data"]["mp4_sha256"] == "abc"
    assert [r["path"] for r in exp["qc_reports"]] == ["exports/v001/controle/rapport_qc.json"]
    assert result["summary"]["export_version_count"] == 1


def test_missing_narration_and_export_files_are_reported(tmp_path):
    (tmp_path / "assets" / "narration" / "v001").mkdir(parents=True)
    (tmp_path / "exports" / "v001").mkdir(parents=True)
    (tmp_path / "exports" / "v001" / "publication_qc.json").write_text("{bad", encoding="utf-8")
    result = read_studio_project(tmp_path)
    nar, exp = result["narration_versions"][0], result["export_versions"][0]
    assert nar["audio"] == [] and nar["report"]["error"] == "missing" and nar["report_markdown"] is None
    assert exp["videos"] == [] and exp["metadata"]["error"] == "missing" and exp["qc_reports"] == []
    assert exp["publication_qc"]["error"].startswith("invalid_json:")


def test_reader_exposes_no_progress_derivation(tmp_path):
    put_json(tmp_path / "exports" / "v001" / "publication_qc.json", {"mp4_sha256": "abc"})
    result = read_studio_project(tmp_path)
    for key in ("etat_studio", "etapes", "prochaine_etape", "termine", "stages", "checkpoints", "progress"):
        assert key not in result
    for version in result["export_versions"] + result["narration_versions"]:
        assert not {"statut", "a_jour", "termine", "done"} & set(version)


def test_reader_does_not_modify_new_studio_folders(tmp_path):
    put_json(tmp_path / "assets" / "narration" / "v001" / "timing_fr.json", [])
    put_json(tmp_path / "exports" / "v001" / "publication_qc.json", {})
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    dirs_before = sorted(p for p in tmp_path.rglob("*"))
    read_studio_project(tmp_path)
    assert {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()} == before
    assert sorted(p for p in tmp_path.rglob("*")) == dirs_before


def test_reader_does_not_modify_files(tmp_path):
    path = tmp_path / "validations.json"
    original = '{"validations":[{"statut":"validé"}]}'
    path.write_text(original, encoding="utf-8")
    before = path.read_bytes()
    read_studio_project(tmp_path)
    assert path.read_bytes() == before
