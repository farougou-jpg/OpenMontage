"""Lot P0-C — checkpoints Studio liés aux validations (A2), validation 3 (V3), gel de `publish`.

Enchaînement réel dans le dossier temporaire de pytest : `write_studio_checkpoint` au-dessus du
vrai `lib.checkpoint.write_checkpoint` (inchangé). Rendu et contrôle qualité simulés.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import lib.checkpoint as ckpt_lib
from lib.checkpoint import write_checkpoint
from lib.studio import checkpoints as ckp
from lib.studio import project as prj
from lib.studio import render as ren
from lib.studio import validations as val
from tests.contracts.test_phase0_contracts import sample_artifact
from tests.studio import test_g0_socle as g0

STAGES = ["idea", "proposal", "script", "scene_plan", "assets", "edit", "compose"]
CUTS = [("un", 0, 7), ("deux", 7, 15)]          # coupes de g0.add_storyboard


@pytest.fixture(autouse=True)
def no_real_process(monkeypatch):
    def refuse(*_a, **_k):
        raise AssertionError("processus réel interdit dans les tests P0-C")
    monkeypatch.setattr(ren.subprocess, "Popen", refuse)
    monkeypatch.setattr(ren.subprocess, "run", refuse)


def scene_plan(cuts=CUTS):
    return {"version": "1.0", "scenes": [{"id": i, "type": "text_card", "description": i, "start_seconds": a,
                                          "end_seconds": b} for i, a, b in cuts]}


def asset_manifest(version="v001"):
    return {"version": "1.0", "assets": [{"id": "narration", "type": "narration", "scene_id": "global",
                                          "path": f"assets/narration/{version}/narration_fr.wav",
                                          "source_tool": "studio_piper_fr_narration"}]}


def edit_decisions(cuts=CUTS, runtime="remotion"):
    return {"version": "1.0", "render_runtime": runtime, "cuts": [
        {"id": i, "source": "storyboard/v001/props_storyboard.json", "in_seconds": a, "out_seconds": b}
        for i, a, b in cuts]}


def render_report(path="renders/v001/video.mp4"):
    return {"version": "1.0", "outputs": [{"path": path, "format": "mp4", "resolution": "1920x1080",
                                           "duration_seconds": 15}]}


def run_until(tmp_path: Path, last: str) -> tuple[Path, Path, dict]:
    """Projet réel conduit selon les skills jusqu'à l'étape `last` incluse (checkpoints via le wrapper)."""
    root, audio = tmp_path / "projects", tmp_path / "audio_studio"
    p = prj.create_project("p0c-run", "Pub P0-C", "Une idée.", 15, root=root)
    prj.register_with_backlot(p)
    ctx: dict = {}
    for stage in STAGES[:STAGES.index(last) + 1]:
        if stage == "idea":
            ckp.write_studio_checkpoint(p, "idea", "completed", {"brief": sample_artifact("brief")})
        elif stage == "proposal":
            pp = sample_artifact("proposal_packet")
            pp.setdefault("approval", {})["status"] = "approved"
            ckp.write_studio_checkpoint(p, "proposal", "completed", {"proposal_packet": pp}, human_approved=True)
        elif stage == "script":
            ctx["script"] = prj.write_script(p, g0.SCRIPT)["artefact"]
            g0.approve(p, "scenario")
            ckp.write_studio_checkpoint(p, "script", "completed", {"script": ctx["script"]}, human_approved=True)
        elif stage == "scene_plan":
            g0.add_storyboard(p)
            g0.approve(p, "storyboard", version="v001")
            ckp.write_studio_checkpoint(p, "scene_plan", "completed", {"scene_plan": scene_plan()},
                                        human_approved=True)
        elif stage == "assets":
            g0.add_narration(p, audio)
            g0.approve(p, "narration", version="v001", studio_audio_root=audio)
            ckp.write_studio_checkpoint(p, "assets", "completed", {"asset_manifest": asset_manifest()},
                                        human_approved=True)
        elif stage == "edit":
            ckp.write_studio_checkpoint(p, "edit", "completed", {"edit_decisions": edit_decisions()})
        elif stage == "compose":
            ren.run_render(ren.prepare_render(p, studio_audio_root=audio), runner=g0.fake_runner())
            g0.add_qc_report(p, "v001")
            ckp.write_studio_checkpoint(p, "compose", "completed", {"render_report": render_report()})
    return p, audio, ctx


def trace(p: Path, stage: str) -> dict:
    return json.loads((p / f"checkpoint_{stage}.json").read_text(encoding="utf-8"))["metadata"]["studio_integrity"]


# ---- positifs ----

def test_full_sequence_writes_traced_checkpoints_bound_to_validations(tmp_path):
    p, _, _ = run_until(tmp_path, "compose")
    assert ckp.verify_studio_checkpoints(p) == []
    refs = {s: trace(p, s)["validation"] for s in ("script", "scene_plan", "assets")}
    assert [refs[s]["numero"] for s in ("script", "scene_plan", "assets")] == [1, 2, 3]
    for s, kind in (("script", "scenario"), ("scene_plan", "storyboard"), ("assets", "narration")):
        assert refs[s]["empreinte_presentation"] == val.validations_by_kind(p)[kind]["empreinte_presentation"]
    for s in STAGES:
        t = trace(p, s)
        assert t["ecrit_par"] == ckp.WRITER and t["etape"] == s and len(t["artefacts_sha256"]) == 64


def test_awaiting_human_binds_to_presented_files_before_validation(tmp_path):
    p, _, _ = run_until(tmp_path, "proposal")
    res = prj.write_script(p, g0.SCRIPT)
    ckp.write_studio_checkpoint(p, "script", "awaiting_human", {"script": res["artefact"]})
    with pytest.raises(ckp.CheckpointIntegrityError, match="différent de script.json"):
        ckp.write_studio_checkpoint(p, "script", "awaiting_human", {"script": {**g0.SCRIPT, "title": "Autre"}})


# ---- négatifs : A2, V3, liaisons ----

def test_A2_script_checkpoint_must_equal_validated_script(tmp_path):
    p, _, _ = run_until(tmp_path, "proposal")
    prj.write_script(p, g0.SCRIPT)
    g0.approve(p, "scenario")
    with pytest.raises(ckp.CheckpointIntegrityError, match="différent de script.json"):
        ckp.write_studio_checkpoint(p, "script", "completed", {"script": {**g0.SCRIPT, "title": "Jamais validé"}},
                                    human_approved=True)
    assert not (p / "checkpoint_script.json").exists()


def test_script_completed_requires_current_validation_and_approval(tmp_path):
    p, _, _ = run_until(tmp_path, "proposal")
    art = prj.write_script(p, g0.SCRIPT)["artefact"]
    with pytest.raises(ckp.CheckpointIntegrityError, match="absente ou périmée"):
        ckp.write_studio_checkpoint(p, "script", "completed", {"script": art}, human_approved=True)
    g0.approve(p, "scenario")
    with pytest.raises(ckp.CheckpointIntegrityError, match="accord humain requis"):
        ckp.write_studio_checkpoint(p, "script", "completed", {"script": art}, human_approved=False)
    assert not (p / "checkpoint_script.json").exists()


def test_scene_plan_must_match_validated_storyboard(tmp_path):
    p, _, _ = run_until(tmp_path, "script")
    g0.add_storyboard(p)
    g0.approve(p, "storyboard", version="v001")
    for bad in ([("un", 0, 6), ("deux", 6, 15)], [("un", 0, 7)], [("un", 0, 7), ("deux", 7, 15), ("trois", 15, 16)]):
        with pytest.raises(ckp.CheckpointIntegrityError, match="différentes du storyboard"):
            ckp.write_studio_checkpoint(p, "scene_plan", "completed", {"scene_plan": scene_plan(bad)},
                                        human_approved=True)
    assert not (p / "checkpoint_scene_plan.json").exists()


def test_V3_assets_checkpoint_requires_validation_3(tmp_path):
    p, audio, _ = run_until(tmp_path, "scene_plan")
    g0.add_narration(p, audio)
    with pytest.raises(ckp.CheckpointIntegrityError, match="narration française.*absente ou périmée"):
        ckp.write_studio_checkpoint(p, "assets", "completed", {"asset_manifest": asset_manifest()},
                                    human_approved=True)
    g0.approve(p, "narration", version="v001", studio_audio_root=audio)
    with pytest.raises(ckp.CheckpointIntegrityError, match="accord humain requis"):
        ckp.write_studio_checkpoint(p, "assets", "completed", {"asset_manifest": asset_manifest()})
    with pytest.raises(ckp.CheckpointIntegrityError, match="ne cite pas la narration"):
        ckp.write_studio_checkpoint(p, "assets", "completed", {"asset_manifest": asset_manifest("v002")},
                                    human_approved=True)
    assert not (p / "checkpoint_assets.json").exists()
    ckp.write_studio_checkpoint(p, "assets", "completed", {"asset_manifest": asset_manifest()}, human_approved=True)
    assert trace(p, "assets")["validation"]["numero"] == 3


def test_edit_must_reuse_storyboard_cuts_with_remotion(tmp_path):
    p, _, _ = run_until(tmp_path, "assets")
    with pytest.raises(ckp.CheckpointIntegrityError, match="remotion"):
        ckp.write_studio_checkpoint(p, "edit", "completed", {"edit_decisions": edit_decisions(runtime="hyperframes")})
    with pytest.raises(ckp.CheckpointIntegrityError, match="différentes du storyboard"):
        ckp.write_studio_checkpoint(p, "edit", "completed",
                                    {"edit_decisions": edit_decisions(CUTS + [("trois", 15, 16)])})


def test_compose_requires_render_py_provenance_and_conform_qc(tmp_path):
    p, audio, _ = run_until(tmp_path, "edit")
    d = p / "renders" / "v001"
    d.mkdir(parents=True)
    (d / "video.mp4").write_bytes(g0.FAKE_MP4 + b"hors-render")   # MP4 hors render.py (autre contenu)
    g0.add_qc_report(p, "v001")                                    # rapport conforme sur ce MP4
    with pytest.raises(ckp.CheckpointIntegrityError, match="rendu.json absent"):
        ckp.write_studio_checkpoint(p, "compose", "completed", {"render_report": render_report()})
    ren.run_render(ren.prepare_render(p, studio_audio_root=audio), runner=g0.fake_runner())   # → v002
    with pytest.raises(ckp.CheckpointIntegrityError, match="Aucun contrôle qualité conforme"):
        ckp.write_studio_checkpoint(p, "compose", "completed", {"render_report": render_report("renders/v002/video.mp4")})
    g0.add_qc_report(p, "v002", "v002")
    ckp.write_studio_checkpoint(p, "compose", "completed", {"render_report": render_report("renders/v002/video.mp4")})
    assert ckp.verify_studio_checkpoints(p) == []


@pytest.mark.parametrize("status", ["in_progress", "awaiting_human", "completed", "failed"])
def test_publish_is_frozen_whatever_the_status(tmp_path, status):
    p, _, _ = run_until(tmp_path, "compose")
    with pytest.raises(ckp.CheckpointIntegrityError, match="publication gelée"):
        ckp.write_studio_checkpoint(p, "publish", status, {"publish_log": {}}, human_approved=True)
    assert not (p / "checkpoint_publish.json").exists()


# ---- non-contournement ----

def test_direct_write_checkpoint_never_yields_an_accepted_studio_checkpoint(tmp_path):
    p, _, _ = run_until(tmp_path, "proposal")
    art = prj.write_script(p, g0.SCRIPT)["artefact"]
    g0.approve(p, "scenario")
    write_checkpoint(p.parent, p.name, "script", "completed", {"script": art}, pipeline_type="studio-fr",
                     human_approved=True)                              # appel direct : accepté par lib.checkpoint…
    problems = ckp.verify_studio_checkpoints(p)
    assert any("hors write_studio_checkpoint" in pb for pb in problems)  # … mais jamais reconnu par Studio
    g0.add_storyboard(p)
    g0.approve(p, "storyboard", version="v001")
    with pytest.raises(ckp.CheckpointIntegrityError, match="précédents non fiables"):
        ckp.write_studio_checkpoint(p, "scene_plan", "completed", {"scene_plan": scene_plan()}, human_approved=True)
    ckp.write_studio_checkpoint(p, "script", "completed", {"script": art}, human_approved=True)   # réécrit proprement
    ckp.write_studio_checkpoint(p, "scene_plan", "completed", {"scene_plan": scene_plan()}, human_approved=True)
    assert ckp.verify_studio_checkpoints(p) == []


def test_tampered_checkpoint_is_detected_and_blocks_next_stage(tmp_path):
    p, _, _ = run_until(tmp_path, "script")
    f = p / "checkpoint_script.json"
    data = json.loads(f.read_text(encoding="utf-8"))
    data["artifacts"]["script"]["title"] = "Modifié à la main"
    f.write_text(json.dumps(data), encoding="utf-8")
    assert any("artefact modifié après écriture" in pb for pb in ckp.verify_studio_checkpoints(p))
    g0.add_storyboard(p)
    g0.approve(p, "storyboard", version="v001")
    with pytest.raises(ckp.CheckpointIntegrityError, match="précédents non fiables"):
        ckp.write_studio_checkpoint(p, "scene_plan", "completed", {"scene_plan": scene_plan()}, human_approved=True)


def test_revalidated_script_makes_old_checkpoint_stale(tmp_path):
    p, _, _ = run_until(tmp_path, "script")
    changed = json.loads(json.dumps(g0.SCRIPT))
    changed["sections"][0]["text"] = "Beaucoup trop de réunions."
    prj.write_script(p, changed)
    g0.approve(p, "scenario")                                          # nouvelle validation 1 (n° 2)
    assert any("remplacée ou périmée" in pb for pb in ckp.verify_studio_checkpoints(p))


def test_reserved_integrity_metadata_cannot_be_forged(tmp_path):
    p, _, _ = run_until(tmp_path, "idea")
    with pytest.raises(ckp.CheckpointIntegrityError, match="réservé"):
        ckp.write_studio_checkpoint(p, "proposal", "in_progress", {}, metadata={"studio_integrity": {"x": 1}})


# ---- restauration après écriture ----

def _tampering_writer(real):
    def write(pipeline_dir, project_id, stage, *a, **k):
        path = real(pipeline_dir, project_id, stage, *a, **k)
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        data["artifacts"]["corruption"] = True
        Path(path).write_text(json.dumps(data), encoding="utf-8")
        return path
    return write


def test_post_write_mismatch_restores_previous_checkpoint_and_decision_log(tmp_path, monkeypatch):
    p, _, _ = run_until(tmp_path, "script")
    target, decisions = p / "checkpoint_script.json", p / "decision_log.json"
    before = (target.read_bytes(), decisions.read_bytes() if decisions.exists() else None)
    monkeypatch.setattr(ckpt_lib, "write_checkpoint", _tampering_writer(ckpt_lib.write_checkpoint))
    art = json.loads((p / "script.json").read_text(encoding="utf-8"))
    with pytest.raises(ckp.CheckpointIntegrityError, match="incohérent après écriture"):
        ckp.write_studio_checkpoint(p, "script", "completed", {"script": art}, human_approved=True)
    assert target.read_bytes() == before[0]
    assert (decisions.read_bytes() if decisions.exists() else None) == before[1]


def test_post_write_mismatch_on_new_checkpoint_removes_it(tmp_path, monkeypatch):
    p, _, _ = run_until(tmp_path, "idea")
    pp = sample_artifact("proposal_packet")
    pp.setdefault("approval", {})["status"] = "approved"
    monkeypatch.setattr(ckpt_lib, "write_checkpoint", _tampering_writer(ckpt_lib.write_checkpoint))
    with pytest.raises(ckp.CheckpointIntegrityError, match="incohérent après écriture"):
        ckp.write_studio_checkpoint(p, "proposal", "completed", {"proposal_packet": pp}, human_approved=True)
    assert not (p / "checkpoint_proposal.json").exists()


def test_failed_restoration_is_reported_with_the_original_error(tmp_path, monkeypatch):
    p, _, _ = run_until(tmp_path, "script")
    monkeypatch.setattr(ckpt_lib, "write_checkpoint", _tampering_writer(ckpt_lib.write_checkpoint))

    def no_write(*_a, **_k):
        raise OSError("disque en lecture seule (simulé)")
    monkeypatch.setattr(ckp, "_atomic_write_bytes", no_write)
    art = json.loads((p / "script.json").read_text(encoding="utf-8"))
    with pytest.raises(ckp.CheckpointIntegrityError, match="restauration incomplète") as info:
        ckp.write_studio_checkpoint(p, "script", "completed", {"script": art}, human_approved=True)
    assert isinstance(info.value.original, ckp.CheckpointIntegrityError)
    assert "incohérent après écriture" in str(info.value.original)
    assert any("checkpoint_script.json" in pb for pb in info.value.problems)


# ---- non-régression ----

def test_pilot_and_demos_refused_without_writing():
    for target in (g0.PILOT, g0.PROJECTS_ROOT / "demos" / "fr-series"):
        before = g0.tree(target)
        with pytest.raises(prj.ProjectLockedError):
            ckp.write_studio_checkpoint(target, "idea", "completed", {"brief": sample_artifact("brief")})
        assert g0.tree(target) == before


def test_identities_and_board_preserved_after_full_sequence(tmp_path):
    p, _, _ = run_until(tmp_path, "compose")
    from backlot.project_metadata import read_project_metadata
    from backlot.state import load_board_state
    md = read_project_metadata(p)
    assert md["metadata_conflict"] is False and md["source_format"] == "hybrid"
    board = load_board_state(p)
    assert board["has_pipeline_state"] is True and board["title"] == "Pub P0-C"
    assert prj.require_writable(p) == p.resolve()
