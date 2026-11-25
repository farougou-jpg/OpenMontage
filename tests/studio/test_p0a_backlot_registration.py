"""Lot P0-A — intégration Studio / Backlot : enregistrement et scénario.

Enchaînement réel dans le dossier temporaire de pytest : `create_project` →
`register_with_backlot` → `write_script` → vrai `write_checkpoint`, puis lecture par
Backlot (`read_project_metadata`, `load_board_state`, `read_studio_project`) et par le
socle Studio. Aucun réseau, aucune génération ; le pilote et `demos/` ne sont que lus.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from backlot.project_metadata import read_project_metadata
from backlot.state import load_board_state
from backlot.studio_reader import read_studio_project
from lib.checkpoint import CheckpointValidationError, write_checkpoint
from lib.studio import project as prj
from lib.studio import validations as val
from lib.studio.narration.tool import PROJECTS_ROOT

SLUG = "pub-p0a"
TITLE = "Pub P0-A"
SCRIPT = {
    "version": "1.0", "title": TITLE, "total_duration_seconds": 15,
    "sections": [
        {"id": "un", "text": "Trop de réunions.", "start_seconds": 0, "end_seconds": 7},
        {"id": "deux", "text": "Inscrivez-vous dès maintenant.", "start_seconds": 7, "end_seconds": 15},
    ],
}
BRIEF = {
    "version": "1.0", "title": TITLE, "hook": "Trois problèmes du quotidien, une solution.",
    "key_points": ["problème", "solution", "appel à l'action"], "tone": "dynamique",
    "style": "clean-professional", "target_platform": "generic", "target_duration_seconds": 15,
}


def _tree(root: Path) -> dict[str, str]:
    return {f.relative_to(root).as_posix(): hashlib.sha256(f.read_bytes()).hexdigest()
            for f in sorted(root.rglob("*")) if f.is_file()}


@pytest.fixture
def registered(tmp_path):
    root = tmp_path / "projects"
    p = prj.create_project(SLUG, TITLE, "Une publicité de test.", 15, root=root)
    prj.register_with_backlot(p)
    res = prj.write_script(p, SCRIPT)
    return root, p, res


def test_full_sequence_is_coherent_for_backlot_and_studio(registered):
    root, p, res = registered
    meta = json.loads((p / "studio_project.json").read_text(encoding="utf-8"))
    write_checkpoint(root, SLUG, "idea", "completed", {"brief": BRIEF}, pipeline_type="studio-fr")

    md = read_project_metadata(p)
    assert md["source_format"] == "hybrid" and md["metadata_conflict"] is False
    assert not any(md["conflicts"].values())
    assert (md["project_id"], md["title"], md["pipeline_type"]) == (SLUG, TITLE, "studio-fr")
    assert md["created_at"] == meta["cree_le"]

    board = load_board_state(p)
    assert board["title"] == TITLE and board["created_at"] == meta["cree_le"]
    assert board["has_marker"] is True and board["has_pipeline_state"] is True

    studio = read_studio_project(p)
    assert studio["script"]["valid"] and studio["script"]["data"] == res["artefact"] == SCRIPT
    assert studio["summary"]["script_section_count"] == 2

    st = prj.project_state(p)
    assert not st["verrouille"] and st["prochaine_etape"] == "scenario"
    assert st["etapes"]["scenario"]["statut"] == "en_cours"      # écrit, pas encore validé
    assert prj.require_writable(p) == p.resolve()


def test_script_artifact_and_file_are_identical(registered):
    _, p, res = registered
    assert json.loads((p / "script.json").read_bytes().decode("utf-8")) == res["artefact"]
    assert res["sha256"] == hashlib.sha256((p / "script.json").read_bytes()).hexdigest()


def test_human_gates_still_enforced_on_registered_project(registered):
    root, p, res = registered
    write_checkpoint(root, SLUG, "idea", "completed", {"brief": BRIEF}, pipeline_type="studio-fr")
    with pytest.raises(CheckpointValidationError, match="GATE VIOLATION"):
        write_checkpoint(root, SLUG, "script", "completed", {"script": res["artefact"]},
                         pipeline_type="studio-fr")
    assert not (p / "checkpoint_script.json").exists()
    assert "scenario" not in val.validations_by_kind(p)           # aucune validation simulée


def test_registration_and_script_never_write_checkpoints_or_validations(tmp_path):
    p = prj.create_project("sans-checkpoint", "T", "I", 15, root=tmp_path / "projects")
    vals_before = (p / "validations.json").read_bytes()
    prj.register_with_backlot(p)
    prj.write_script(p, SCRIPT)
    assert not list(p.glob("checkpoint_*.json")) and not (p / "decision_log.json").exists()
    assert (p / "validations.json").read_bytes() == vals_before


def test_protected_projects_untouched_by_p0a_entry_points(tmp_path):
    targets = [PROJECTS_ROOT / "pilote-gestion-temps", PROJECTS_ROOT / "demos" / "fr-series"]
    before = {t: _tree(t) for t in targets}
    for t in targets:
        for call in (lambda: prj.register_with_backlot(t), lambda: prj.write_script(t, SCRIPT)):
            with pytest.raises(prj.ProjectLockedError):
                call()
    assert {t: _tree(t) for t in targets} == before
    assert not any((t / "project.json").exists() for t in targets)
