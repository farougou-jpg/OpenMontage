"""Lot P0-E — R4 : intégrité du journal des décisions dans les checkpoints Studio (trace v2).

`decision_log_ref` figé et couvert par l'empreinte ; référence structurellement liée au projet ;
empreinte de chaque décision, vérifiée à chaque relecture ; ajouts ultérieurs permis ; traces v1
vérifiées selon leurs règles. Dossier temporaire de pytest uniquement.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from lib.studio import checkpoints as ckp
from lib.studio import project as prj
from lib.studio import render as ren
from tests.contracts.test_phase0_contracts import sample_artifact
from tests.studio import test_p0c_checkpoint_integrity as c0


@pytest.fixture(autouse=True)
def no_real_process(monkeypatch):
    def refuse(*_a, **_k):
        raise AssertionError("processus réel interdit dans les tests P0-E")
    monkeypatch.setattr(ren.subprocess, "Popen", refuse)
    monkeypatch.setattr(ren.subprocess, "run", refuse)


def decision(decision_id: str, selected: str = "remotion", stage: str = "proposal") -> dict:
    return {"decision_id": decision_id, "stage": stage, "category": "render_runtime_selection", "subject": "Moteur",
            "options_considered": [{"option_id": selected, "label": selected, "score": 1, "reason": "phase 1"}],
            "selected": selected, "reason": "phase 1"}


def log(p: Path, *decisions: dict) -> dict:
    return {"version": "1.0", "project_id": p.name, "decisions": list(decisions)}


@pytest.fixture
def proposed(tmp_path):
    root = tmp_path / "projects"
    p = prj.create_project("journal-p0e", "T", "I", 15, root=root)
    prj.register_with_backlot(p)
    ckp.write_studio_checkpoint(p, "idea", "completed", {"brief": sample_artifact("brief")})
    pp = sample_artifact("proposal_packet")
    pp.setdefault("approval", {})["status"] = "approved"
    ckp.write_studio_checkpoint(p, "proposal", "completed", {"proposal_packet": pp, "decision_log": log(p, decision("d1"))},
                                human_approved=True)
    return p


def cp(p: Path, stage: str = "proposal") -> dict:
    return json.loads((p / f"checkpoint_{stage}.json").read_text(encoding="utf-8"))


def save(p: Path, data: dict, stage: str = "proposal", recompute: bool = False) -> None:
    if recompute:                                            # falsification avec empreinte recalculée
        t = data["metadata"]["studio_integrity"]
        t["artefacts_sha256"] = ckp.artifacts_sha256(data["artifacts"], t.get("version", 1))
    (p / f"checkpoint_{stage}.json").write_text(json.dumps(data), encoding="utf-8")


# ---- trace v2 ----

def test_v2_trace_freezes_the_reference_and_records_each_decision(proposed):
    p = proposed
    data = cp(p)
    trace = data["metadata"]["studio_integrity"]
    assert trace["version"] == 2
    assert data["artifacts"]["proposal_packet"]["production_plan"]["decision_log_ref"] == str(p / "decision_log.json")
    assert [d[0] for d in trace["decisions"]] == ["d1"] and len(trace["decisions"][0][1]) == 64
    assert trace["artefacts_sha256"] == ckp.artifacts_sha256(data["artifacts"], 2)
    assert ckp.verify_studio_checkpoints(p) == []


def test_falsified_reference_is_detected(proposed):
    p = proposed
    data = cp(p)
    data["artifacts"]["proposal_packet"]["production_plan"]["decision_log_ref"] = "C:/ailleurs/falsifie.json"
    save(p, data)
    assert any("artefact modifié après écriture" in pb for pb in ckp.verify_studio_checkpoints(p))
    save(p, data, recompute=True)                            # même avec l'empreinte recalculée
    assert any("ne désigne pas le decision_log.json du projet" in pb for pb in ckp.verify_studio_checkpoints(p))


def test_removed_reference_is_detected(proposed):
    p = proposed
    data = cp(p)
    data["artifacts"]["proposal_packet"]["production_plan"].pop("decision_log_ref")
    save(p, data, recompute=True)
    assert any("decision_log_ref absent" in pb for pb in ckp.verify_studio_checkpoints(p))


def test_modified_decision_is_detected_and_blocks_the_next_stage(proposed):
    p = proposed
    j = json.loads((p / "decision_log.json").read_text(encoding="utf-8"))
    j["decisions"][0]["selected"] = "hyperframes"
    (p / "decision_log.json").write_text(json.dumps(j), encoding="utf-8")
    assert any("décision d1 modifiée ou supprimée" in pb for pb in ckp.verify_studio_checkpoints(p))
    art = prj.write_script(p, c0.g0.SCRIPT)["artefact"]
    c0.g0.approve(p, "scenario")
    with pytest.raises(ckp.CheckpointIntegrityError, match="précédents non fiables"):
        ckp.write_studio_checkpoint(p, "script", "completed", {"script": art}, human_approved=True)


def test_deleted_decision_and_deleted_log_are_detected(proposed):
    p = proposed
    j = json.loads((p / "decision_log.json").read_text(encoding="utf-8"))
    (p / "decision_log.json").write_text(json.dumps({**j, "decisions": []}), encoding="utf-8")
    assert any("décision d1 modifiée ou supprimée" in pb for pb in ckp.verify_studio_checkpoints(p))
    (p / "decision_log.json").unlink()
    assert any("decision_log.json absent ou illisible" in pb for pb in ckp.verify_studio_checkpoints(p))


def test_new_decisions_added_later_are_allowed(proposed):
    p = proposed
    art = prj.write_script(p, c0.g0.SCRIPT)["artefact"]
    c0.g0.approve(p, "scenario")
    ckp.write_studio_checkpoint(p, "script", "completed",
                                {"script": art, "decision_log": log(p, decision("d2", stage="script"))},
                                human_approved=True)
    ids = [d["decision_id"] for d in json.loads((p / "decision_log.json").read_text(encoding="utf-8"))["decisions"]]
    assert ids == ["d1", "d2"]
    assert [d[0] for d in cp(p, "script")["metadata"]["studio_integrity"]["decisions"]] == ["d1", "d2"]
    assert ckp.verify_studio_checkpoints(p) == []


def test_render_report_reference_is_also_frozen(tmp_path):
    p, _, _ = c0.run_until(tmp_path, "compose")
    ckp.write_studio_checkpoint(p, "compose", "completed",
                                {"render_report": c0.render_report(), "decision_log": log(p, decision("d9", stage="compose"))})
    data = cp(p, "compose")
    assert data["artifacts"]["render_report"]["decision_log_ref"] == str(p / "decision_log.json")
    assert ckp.verify_studio_checkpoints(p) == []
    data["artifacts"]["render_report"]["decision_log_ref"] = "autre/decision_log.json"
    save(p, data, stage="compose", recompute=True)
    assert any("ne désigne pas le decision_log.json du projet" in pb for pb in ckp.verify_studio_checkpoints(p))


def test_moved_project_raises_no_false_alarm(proposed, tmp_path):
    p = proposed
    moved = tmp_path / "ailleurs" / "projects" / p.name
    shutil.copytree(p, moved)
    assert ckp.verify_studio_checkpoints(moved) == []        # référence absolue ancienne, mais même projet


# ---- compatibilité v1 et robustesse ----

def _as_v1(data: dict) -> dict:
    t = data["metadata"]["studio_integrity"]
    t["version"] = 1
    t.pop("decisions", None)
    t["artefacts_sha256"] = ckp.artifacts_sha256(data["artifacts"], 1)
    return data


def test_v1_traces_are_still_verified_with_v1_rules(proposed):
    p = proposed
    save(p, _as_v1(cp(p)))
    assert ckp.verify_studio_checkpoints(p) == []            # pas rejetée faute de champs v2
    data = cp(p)
    data["artifacts"]["proposal_packet"]["title"] = "modifié"
    save(p, data)
    assert any("artefact modifié après écriture" in pb for pb in ckp.verify_studio_checkpoints(p))


def test_v1_rule_ignores_reference_as_before(proposed):
    p = proposed
    data = _as_v1(cp(p))
    data["artifacts"]["proposal_packet"]["production_plan"]["decision_log_ref"] = "C:/ailleurs/x.json"
    save(p, data)
    assert ckp.verify_studio_checkpoints(p) == []            # limite connue des traces v1, documentée


def test_v2_trace_without_decisions_or_unknown_version_is_refused(proposed):
    p = proposed
    data = cp(p)
    data["metadata"]["studio_integrity"].pop("decisions")
    save(p, data)
    assert any("empreintes des décisions absentes" in pb for pb in ckp.verify_studio_checkpoints(p))
    data["metadata"]["studio_integrity"]["version"] = 9
    save(p, data)
    assert any("version de trace inconnue" in pb for pb in ckp.verify_studio_checkpoints(p))


def test_unreadable_decision_log_refuses_the_write(proposed):
    p = proposed
    (p / "decision_log.json").write_text("{bad", encoding="utf-8")
    art = prj.write_script(p, c0.g0.SCRIPT)["artefact"]
    c0.g0.approve(p, "scenario")
    before = (p / "decision_log.json").read_bytes()
    with pytest.raises(ckp.CheckpointIntegrityError):
        ckp.write_studio_checkpoint(p, "script", "completed", {"script": art}, human_approved=True)
    assert (p / "decision_log.json").read_bytes() == before and not (p / "checkpoint_script.json").exists()
