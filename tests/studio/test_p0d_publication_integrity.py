"""Lot P0-D — R2 (publication liée à la validation 4 du MP4 exact), R1 (aucun checkpoint non vérifié
accepté comme intègre par le Studio), R5 (version du storyboard présentée = version du checkpoint).

Dossier temporaire de pytest uniquement ; rendu et contrôle qualité simulés ; gel de `publish` intact.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lib.checkpoint import write_checkpoint
from lib.studio import checkpoints as ckp
from lib.studio import export_package as exp
from lib.studio import project as prj
from lib.studio import render as ren
from lib.studio import validations as val
from lib.studio.budget_guard import PublicationRefusedError, StudioBudgetGuard
from lib.studio.publish import exporter_video
from tests.studio import test_g0_socle as g0
from tests.studio import test_p0c_checkpoint_integrity as c0
from tools.base_tool import ToolResult
from tools.publishers.export_bundle import ExportBundle


@pytest.fixture(autouse=True)
def no_real_process(monkeypatch):
    def refuse(*_a, **_k):
        raise AssertionError("processus réel interdit dans les tests P0-D")
    monkeypatch.setattr(ren.subprocess, "Popen", refuse)
    monkeypatch.setattr(ren.subprocess, "run", refuse)


def qc_result(p: Path, qc_version: str = "v001") -> ToolResult:
    report = p / "controle" / qc_version / "rapport_qc.json"
    return ToolResult(success=True, data={"conforme": True, "bloquants": [], "avertissements": [],
                                          "rapport_json": str(report)})


def rendered_with_qc(tmp_path: Path) -> tuple[Path, Path]:
    p, audio = g0.validated_until_narration(tmp_path)
    ren.run_render(ren.prepare_render(p, studio_audio_root=audio), runner=g0.fake_runner())
    g0.add_qc_report(p, "v001")
    return p, audio


def exports(p: Path) -> list[str]:
    return prj.versions(p / "exports")


# ======================= R2 : publication = validation 4 du MP4 exact =======================

def test_R2_direct_exporter_video_without_validation_4_is_refused(tmp_path):
    p, _ = rendered_with_qc(tmp_path)                                   # reproduction de P0-B
    res = exporter_video(qc_result(p), p / "renders/v001/video.mp4", "T", p)
    assert not res.success and "validation 4 (rendu vidéo) absente ou périmée" in res.error
    assert exports(p) == [] and not prj.is_locked(p)


def test_R2_nominal_export_binds_the_validated_mp4(tmp_path):
    p, _ = rendered_with_qc(tmp_path)
    e = g0.approve(p, "rendu", render_version="v001", qc_version="v001")
    res = exp.export_package(p, "film.mp4", "Titre")
    assert res["sha256"] == e["sha256"] and exports(p) == ["v001"] and prj.is_locked(p)


def test_R2_resume_after_refusal_once_validation_4_is_given(tmp_path):
    p, _ = rendered_with_qc(tmp_path)
    assert not exporter_video(qc_result(p), p / "renders/v001/video.mp4", "T", p).success
    g0.approve(p, "rendu", render_version="v001", qc_version="v001")    # reprise : accord explicite
    res = exporter_video(qc_result(p), p / "renders/v001/video.mp4", "T", p)
    assert res.success, res.error


def test_R2_other_mp4_than_validation_4_refused(tmp_path):
    p, audio = rendered_with_qc(tmp_path)
    g0.approve(p, "rendu", render_version="v001", qc_version="v001")
    ren.run_render(ren.prepare_render(p, studio_audio_root=audio),
                   runner=g0.fake_runner(content=g0.FAKE_MP4 + b"autre-rendu"))   # v002, contenu différent
    g0.add_qc_report(p, "v002", "v002")                                 # contrôle conforme de v002
    res = exporter_video(qc_result(p, "v002"), p / "renders/v002/video.mp4", "T", p)
    assert not res.success and "n'est pas celui de la validation 4" in res.error
    assert exports(p) == []


def test_R2_qc_report_other_than_validation_4_refused(tmp_path):
    p, _ = rendered_with_qc(tmp_path)
    g0.approve(p, "rendu", render_version="v001", qc_version="v001")
    g0.add_qc_report(p, "v001", "v002")                                 # second rapport conforme, même MP4
    res = exporter_video(qc_result(p, "v002"), p / "renders/v001/video.mp4", "T", p)
    assert not res.success and "n'est pas celui de la validation 4" in res.error


def test_R2_modification_after_validation_4_refused(tmp_path):
    p, _ = rendered_with_qc(tmp_path)
    g0.approve(p, "rendu", render_version="v001", qc_version="v001")
    props = p / "renders/v001/props_rendu.json"
    props.write_bytes(props.read_bytes() + b" ")
    res = exporter_video(qc_result(p), p / "renders/v001/video.mp4", "T", p)
    assert not res.success and "absente ou périmée" in res.error
    with pytest.raises(exp.ExportError, match="modifié depuis la validation"):
        exp.export_package(p, "film.mp4", "T")
    assert exports(p) == []


def test_R2_direct_export_bundle_and_guard_paths_stay_refused(tmp_path):
    p, _ = rendered_with_qc(tmp_path)
    g0.approve(p, "rendu", render_version="v001", qc_version="v001")
    mp4 = p / "renders/v001/video.mp4"
    out = p / "exports" / "v001"
    res = ExportBundle().execute({"video_path": str(mp4), "title": "T", "export_dir": str(out),
                                  "studio_qc_report": str(p / "controle/v001/rapport_qc.json")})
    assert not res.success and "exporter_video" in res.error
    with pytest.raises(PublicationRefusedError):
        StudioBudgetGuard(p).run(ExportBundle(), {"video_path": str(mp4), "title": "T",
                                                  "export_dir": str(out)}, qc_result=None)
    assert exports(p) == []


def test_R2_interrupted_export_leaves_no_export_and_keeps_validation(tmp_path, monkeypatch):
    p, _ = rendered_with_qc(tmp_path)
    g0.approve(p, "rendu", render_version="v001", qc_version="v001")

    def crash(self, inputs):
        Path(inputs["export_dir"], "video").mkdir(parents=True, exist_ok=True)
        raise OSError("coupure simulée pendant l'export")
    monkeypatch.setattr(ExportBundle, "execute", crash)
    res = exporter_video(qc_result(p), p / "renders/v001/video.mp4", "T", p)
    assert not res.success and "OSError" in res.error
    assert exports(p) == [] and not prj.is_locked(p)
    assert val.is_current(p, "rendu")[0] is True
    monkeypatch.undo()
    assert exporter_video(qc_result(p), p / "renders/v001/video.mp4", "T", p).success   # reprise


# ======================= R1 : aucun checkpoint non vérifié accepté =======================

@pytest.fixture
def composed(tmp_path):
    p, audio, _ = c0.run_until(tmp_path, "compose")
    g0.approve(p, "rendu", render_version="v001", qc_version="v001")
    return p, audio


def _blocked_everywhere(p: Path, audio: Path) -> None:
    with pytest.raises(ren.RenderError, match="checkpoints Studio non fiables"):
        ren.prepare_render(p, studio_audio_root=audio)
    with pytest.raises(ren.RenderError, match="checkpoints Studio non fiables"):
        ren.check_render(p, "v001")
    with pytest.raises(exp.ExportError, match="checkpoints Studio non fiables"):
        exp.export_package(p, "film.mp4", "T")
    res = exporter_video(qc_result(p), p / "renders/v001/video.mp4", "T", p)
    assert not res.success and "checkpoints Studio non fiables" in res.error
    assert exports(p) == []


def test_R1_direct_write_checkpoint_is_never_accepted_downstream(composed):
    p, audio = composed
    edit = json.loads((p / "checkpoint_edit.json").read_text(encoding="utf-8"))["artifacts"]
    write_checkpoint(p.parent, p.name, "edit", "completed", edit, pipeline_type="studio-fr")   # hors wrapper
    assert any("hors write_studio_checkpoint" in pb for pb in ckp.verify_studio_checkpoints(p))
    _blocked_everywhere(p, audio)
    ckp.write_studio_checkpoint(p, "edit", "completed", edit)            # reprise : réécriture vérifiée
    assert ckp.verify_studio_checkpoints(p) == []
    assert exp.export_package(p, "film.mp4", "T")["version"] == "v001"


def test_R1_tampered_checkpoint_blocks_render_and_publication(composed):
    p, audio = composed
    f = p / "checkpoint_assets.json"
    data = json.loads(f.read_text(encoding="utf-8"))
    data["artifacts"]["asset_manifest"]["assets"][0]["path"] = "assets/narration/v009/narration_fr.wav"
    f.write_text(json.dumps(data), encoding="utf-8")
    _blocked_everywhere(p, audio)


def test_R1_projects_without_checkpoints_are_unaffected(tmp_path):
    p, _ = rendered_with_qc(tmp_path)
    g0.approve(p, "rendu", render_version="v001", qc_version="v001")
    assert ckp.verify_studio_checkpoints(p) == []
    assert exp.export_package(p, "film.mp4", "T")["version"] == "v001"


# ======================= R5 : storyboard présenté = storyboard du checkpoint =======================

def _second_storyboard(p: Path) -> None:
    """storyboard/v002 aux coupes DIFFÉRENTES de v001 (dernière version, non présentée)."""
    d = p / "storyboard" / "v002"
    (d / "scenes").mkdir(parents=True)
    prj.write_json(d / "storyboard.json", {"configuration_rendu": g0.FR_CONFIG_V4, "scenes": 2})
    prj.write_json(d / "props_storyboard.json", {"theme": "clean-professional", "overlays": [], "cuts": [
        {"id": "un", "type": "hero_title", "text": "A", "in_seconds": 0, "out_seconds": 5},
        {"id": "deux", "type": "hero_title", "text": "B", "in_seconds": 5, "out_seconds": 15}]})


def _scene_plan(version, cuts=c0.CUTS):
    sp = c0.scene_plan(cuts)
    if version is not None:
        sp["metadata"] = {"storyboard_version": version}
    return sp


def test_R5_awaiting_scene_plan_is_checked_against_the_presented_version(tmp_path):
    p, _, _ = c0.run_until(tmp_path, "script")
    g0.add_storyboard(p)                                     # v001 présentée
    _second_storyboard(p)                                    # v002 = dernière version, autres coupes
    with pytest.raises(ckp.CheckpointIntegrityError, match="storyboard_version .*obligatoire"):
        ckp.write_studio_checkpoint(p, "scene_plan", "awaiting_human", {"scene_plan": _scene_plan(None)})
    ckp.write_studio_checkpoint(p, "scene_plan", "awaiting_human", {"scene_plan": _scene_plan("v001")})
    with pytest.raises(ckp.CheckpointIntegrityError, match="différentes du storyboard v002"):
        ckp.write_studio_checkpoint(p, "scene_plan", "awaiting_human", {"scene_plan": _scene_plan("v002")})
    with pytest.raises(ckp.CheckpointIntegrityError, match="inconnue"):
        ckp.write_studio_checkpoint(p, "scene_plan", "awaiting_human", {"scene_plan": _scene_plan("v009")})


def test_R5_completed_scene_plan_must_declare_the_validated_version(tmp_path):
    p, _, _ = c0.run_until(tmp_path, "script")
    g0.add_storyboard(p)
    _second_storyboard(p)
    g0.approve(p, "storyboard", version="v001")              # validation 2 sur v001
    with pytest.raises(ckp.CheckpointIntegrityError, match="présenté sur le storyboard v002, version validée : v001"):
        ckp.write_studio_checkpoint(p, "scene_plan", "completed",
                                    {"scene_plan": _scene_plan("v002", [("un", 0, 5), ("deux", 5, 15)])},
                                    human_approved=True)
    ckp.write_studio_checkpoint(p, "scene_plan", "completed", {"scene_plan": _scene_plan("v001")},
                                human_approved=True)
    assert ckp.verify_studio_checkpoints(p) == []


def test_R5_forged_checkpoint_with_recomputed_trace_is_still_detected(tmp_path):
    p, _, _ = c0.run_until(tmp_path, "script")
    g0.add_storyboard(p)
    _second_storyboard(p)
    g0.approve(p, "storyboard", version="v001")
    ckp.write_studio_checkpoint(p, "scene_plan", "completed", {"scene_plan": _scene_plan("v001")},
                                human_approved=True)
    f = p / "checkpoint_scene_plan.json"
    data = json.loads(f.read_text(encoding="utf-8"))
    data["artifacts"]["scene_plan"]["metadata"]["storyboard_version"] = "v002"
    data["metadata"]["studio_integrity"]["artefacts_sha256"] = ckp.artifacts_sha256(data["artifacts"])
    f.write_text(json.dumps(data), encoding="utf-8")         # falsification avec empreinte recalculée
    assert any("storyboard présenté différent de la version validée" in pb
               for pb in ckp.verify_studio_checkpoints(p))


def test_R5_superseded_storyboard_validation_makes_scene_plan_stale(tmp_path):
    p, _, _ = c0.run_until(tmp_path, "scene_plan")
    _second_storyboard(p)
    g0.approve(p, "storyboard", version="v002")              # nouvelle validation 2, sur v002
    assert any("remplacée ou périmée" in pb for pb in ckp.verify_studio_checkpoints(p))


# ======================= gel de publish (inchangé) =======================

def test_publish_checkpoint_still_frozen_after_p0d(composed):
    p, _ = composed
    with pytest.raises(ckp.CheckpointIntegrityError, match="publication gelée"):
        ckp.write_studio_checkpoint(p, "publish", "completed", {"publish_log": {}}, human_approved=True)
    skill = (g0.Path(__file__).resolve().parents[2] / "skills/pipelines/studio-fr/publish-director.md"
             ).read_text(encoding="utf-8")
    assert "Étape gelée" in skill and "ne lancer aucun export" in skill
