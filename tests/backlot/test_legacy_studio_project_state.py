"""Read-only Backlot projection tests for historical Studio project layouts."""
from pathlib import Path

from backlot.state import load_board_state
from backlot.project_metadata import read_project_metadata

REPO = Path(__file__).resolve().parents[2]
PILOT = REPO / "projects" / "pilote-gestion-temps"


def test_historical_studio_metadata_is_recognized_without_progress_inference():
    metadata = read_project_metadata(PILOT)
    assert metadata["source_format"] == "studio"
    assert metadata["project_id"] == "pilote-gestion-temps"
    assert metadata["pipeline_type"] == "studio-fr"
    assert "Studio d'impact" in metadata["title"]


def test_historical_storyboard_is_projected_into_six_readable_scene_cards():
    state = load_board_state(PILOT)
    board = state["storyboard"]
    assert board is not None
    assert len(board["scenes"]) == 6
    assert board["total_duration_seconds"] == 30
    first = board["scenes"][0]
    assert first["id"] == "accroche"
    assert first["start_seconds"] == 0
    assert first["end_seconds"] == 4
    assert first["narration"] == "Trois problèmes vous volent du temps."
    assert first["visual"]["exists"] is True
    assert first["visual"]["path"].endswith("storyboard/v002/scenes/scene_01.png")


def test_versioned_render_and_export_media_are_discovered():
    state = load_board_state(PILOT)
    paths = {item["path"] for item in state["media"]["renders"]}
    assert "renders/v001/pilote-studio-impact-v002.mp4" in paths
    assert "exports/v001/video/studio-impact-fr-v002.mp4" in paths
    assert any(item["path"].endswith("storyboard/v002/scenes/scene_01.png")
               for item in state["media"]["snapshots"])
    assert any(item["path"] == "assets/narration/v002/narration_fr.wav"
               and item["type"] == "narration" for item in state["media"]["audio"])


def test_reading_historical_pilot_does_not_create_backlot_progress():
    before = {p.name for p in PILOT.glob("checkpoint_*.json")}
    state = load_board_state(PILOT)
    after = {p.name for p in PILOT.glob("checkpoint_*.json")}
    assert before == after == set()
    assert state["has_pipeline_state"] is False
    assert all(stage["status"] == "pending" for stage in state["stages"])
