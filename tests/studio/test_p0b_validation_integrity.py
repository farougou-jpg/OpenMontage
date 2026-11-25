"""Lot P0-B — une validation humaine porte sur l'artefact EXACT présenté à l'utilisateur.

A. accord humain (absent, implicite, explicite, ancien artefact) ;
B. intégrité SHA-256 (empreinte identique / différente, modification après présentation,
   réécriture entre l'accord et la validation) ;
C. chaîne (ordre, validation obligatoire absente, checkpoint absent, publication sans
   validation finale) ;
D. non-régression (validations antérieures, identités Studio/Backlot, pilote).

Tout se passe dans le dossier temporaire de pytest ; rendu et contrôle qualité simulés.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lib.checkpoint import CheckpointValidationError, write_checkpoint
from lib.studio import export_package as exp
from lib.studio import project as prj
from lib.studio import render as ren
from lib.studio import validations as val
from tests.studio import test_g0_socle as g0

ACCORD = g0.ACCORD


@pytest.fixture(autouse=True)
def no_real_process(monkeypatch):
    def refuse(*_a, **_k):
        raise AssertionError("processus réel interdit dans les tests P0-B")
    monkeypatch.setattr(ren.subprocess, "Popen", refuse)
    monkeypatch.setattr(ren.subprocess, "run", refuse)


def entries(p: Path) -> list[dict]:
    return json.loads((p / "validations.json").read_text(encoding="utf-8"))["validations"]


def scripted(tmp_path: Path) -> Path:
    p = g0.new_project(tmp_path)
    prj.write_script(p, g0.SCRIPT)
    return p


# ---- A. accord humain ----

@pytest.mark.parametrize("accord", [None, "", "   \n", True, 1, ["oui"]])
def test_A_missing_or_implicit_approval_is_refused(tmp_path, accord):
    p = scripted(tmp_path)
    before = (p / "validations.json").read_bytes()
    shown = val.presentation(p, "scenario")
    with pytest.raises(val.ValidationError, match="accord explicite de l'utilisateur absent"):
        val.validate_script(p, empreinte_presentee=shown["empreinte"], accord_utilisateur=accord)
    assert (p / "validations.json").read_bytes() == before


def test_A_call_without_any_proof_is_refused_for_every_validation(tmp_path):
    p, audio = g0.validated_until_narration(tmp_path)
    ren.run_render(ren.prepare_render(p, studio_audio_root=audio), runner=g0.fake_runner())
    g0.add_qc_report(p, "v001")
    before = (p / "validations.json").read_bytes()
    for call in (lambda: val.validate_script(p),
                 lambda: val.validate_storyboard(p, "v001"),
                 lambda: val.validate_narration(p, "v001", audio),
                 lambda: val.validate_render(p, "v001", "v001")):
        with pytest.raises(val.ValidationError, match="accord explicite"):
            call()
    assert (p / "validations.json").read_bytes() == before


def test_A_explicit_approval_on_presented_artifact_is_recorded(tmp_path):
    p = scripted(tmp_path)
    shown = val.presentation(p, "scenario")
    e = val.validate_script(p, empreinte_presentee=shown["empreinte"], accord_utilisateur="  Oui, je valide.  ")
    assert e["accord_utilisateur"] == "Oui, je valide."
    assert e["empreinte_presentation"] == shown["empreinte"] and e["empreintes"] == shown["fichiers"]
    assert val.is_current(p, "scenario") == (True, "à jour")
    assert entries(p)[-1] == e


def test_A_old_artifact_cannot_be_validated(tmp_path):
    p = scripted(tmp_path)
    old = val.presentation(p, "scenario")["empreinte"]
    prj.write_script(p, {**g0.SCRIPT, "title": "Version 2"})
    with pytest.raises(val.ValidationError, match="pas exactement celui présenté"):
        val.validate_script(p, empreinte_presentee=old, accord_utilisateur=ACCORD)
    assert entries(p) == []
    # Storyboard : l'empreinte de v001 ne valide pas v002.
    g0.approve(p, "scenario")
    g0.add_storyboard(p, "v001")
    g0.add_storyboard(p, "v002")
    fp_v001 = val.presentation(p, "storyboard", version="v001")["empreinte"]
    with pytest.raises(val.ValidationError, match="pas exactement celui présenté"):
        val.validate_storyboard(p, "v002", empreinte_presentee=fp_v001, accord_utilisateur=ACCORD)


# ---- B. intégrité SHA-256 ----

def test_B_identical_fingerprint_accepted_different_refused(tmp_path):
    p = scripted(tmp_path)
    shown = val.presentation(p, "scenario")
    assert shown["empreinte"] == val.presentation(p, "scenario")["empreinte"]   # déterministe
    forged = ("0" if shown["empreinte"][0] != "0" else "1") + shown["empreinte"][1:]
    for bad in (forged, shown["empreinte"].upper(), "", None):
        with pytest.raises(val.ValidationError):
            val.validate_script(p, empreinte_presentee=bad, accord_utilisateur=ACCORD)
    assert entries(p) == []
    assert val.validate_script(p, empreinte_presentee=shown["empreinte"], accord_utilisateur=ACCORD)["numero"] == 1


def test_B_rewrite_between_approval_and_validation_is_detected(tmp_path):
    p = scripted(tmp_path)
    shown = val.presentation(p, "scenario")                   # présenté, puis accord de l'utilisateur
    changed = json.loads(json.dumps(g0.SCRIPT))
    changed["sections"][1]["text"] = "Inscrivez-vous aujourd'hui."
    prj.write_script(p, changed)                              # réécriture silencieuse avant validation
    with pytest.raises(val.ValidationError, match="pas exactement celui présenté"):
        val.validate_script(p, empreinte_presentee=shown["empreinte"], accord_utilisateur=ACCORD)
    assert entries(p) == []


def test_B_file_added_to_storyboard_after_presentation_is_detected(tmp_path):
    p = scripted(tmp_path)
    g0.approve(p, "scenario")
    g0.add_storyboard(p)
    shown = val.presentation(p, "storyboard", version="v001")
    (p / "storyboard" / "v001" / "scenes" / "scene_03.png").write_bytes(b"ajout")
    with pytest.raises(val.ValidationError, match="pas exactement celui présenté"):
        val.validate_storyboard(p, "v001", empreinte_presentee=shown["empreinte"], accord_utilisateur=ACCORD)


def test_B_modification_after_validation_invalidates_it(tmp_path):
    p = scripted(tmp_path)
    g0.approve(p, "scenario")
    g0.add_storyboard(p)
    (p / "script.json").write_bytes((p / "script.json").read_bytes() + b" ")
    assert val.is_current(p, "scenario")[0] is False
    assert prj.project_state(p)["etapes"]["scenario"]["a_jour"] is False
    with pytest.raises(val.ValidationError, match="modifié depuis la validation 1"):
        g0.approve(p, "storyboard", version="v001")


def test_B_tampered_validation_record_is_not_current(tmp_path):
    p = scripted(tmp_path)
    g0.approve(p, "scenario")
    data = json.loads((p / "validations.json").read_text(encoding="utf-8"))
    for field, value, why in (("accord_utilisateur", "", "sans accord explicite"),
                              ("empreinte_presentation", "0" * 64, "empreinte de présentation cohérente")):
        tampered = json.loads(json.dumps(data))
        tampered["validations"][-1][field] = value
        prj.write_json(p / "validations.json", tampered)
        ok, reason = val.is_current(p, "scenario")
        assert ok is False and why in reason
    legacy = json.loads(json.dumps(data))                     # format antérieur : ni accord ni empreinte
    for k in ("accord_utilisateur", "empreinte_presentation"):
        legacy["validations"][-1].pop(k)
    prj.write_json(p / "validations.json", legacy)
    assert val.is_current(p, "scenario")[0] is False
    g0.add_storyboard(p)
    with pytest.raises(val.ValidationError, match="sans accord explicite"):
        g0.approve(p, "storyboard", version="v001")


# ---- C. chaîne ----

def test_C_wrong_order_refused(tmp_path):
    p = scripted(tmp_path)
    g0.add_storyboard(p)
    with pytest.raises(val.ValidationError, match="scénario non validé"):
        g0.approve(p, "storyboard", version="v001")
    assert entries(p) == []


def test_C_missing_mandatory_validation_blocks_render_and_export(tmp_path):
    p = scripted(tmp_path)
    g0.approve(p, "scenario")
    g0.add_storyboard(p)
    g0.approve(p, "storyboard", version="v001")
    with pytest.raises(ren.RenderError, match="narration française non validé"):
        ren.prepare_render(p)
    p2, audio = g0.validated_until_narration(tmp_path / "deux")
    ren.run_render(ren.prepare_render(p2, studio_audio_root=audio), runner=g0.fake_runner())
    g0.add_qc_report(p2, "v001")
    with pytest.raises(exp.ExportError, match="rendu vidéo non validé"):
        exp.export_package(p2, "film.mp4", "T")
    assert prj.versions(p2 / "exports") == []


def test_C_missing_checkpoint_and_final_gate_refused(tmp_path):
    root = tmp_path / "projects"
    p = prj.create_project("chaine-p0b", "T", "I", 15, root=root)
    prj.register_with_backlot(p)
    with pytest.raises(CheckpointValidationError, match="PREREQUISITE VIOLATION"):
        write_checkpoint(root, p.name, "compose", "completed", {"render_report": {}}, pipeline_type="studio-fr")
    with pytest.raises(CheckpointValidationError, match="GATE VIOLATION"):
        write_checkpoint(root, p.name, "publish", "completed", {"publish_log": {}}, pipeline_type="studio-fr")
    assert not list(p.glob("checkpoint_*.json"))


def test_C_publication_requires_final_human_validation(tmp_path):
    p, audio = g0.validated_until_narration(tmp_path)
    ren.run_render(ren.prepare_render(p, studio_audio_root=audio), runner=g0.fake_runner())
    g0.add_qc_report(p, "v001")
    shown = val.presentation(p, "rendu", render_version="v001", qc_version="v001")
    with pytest.raises(val.ValidationError, match="accord explicite"):
        val.validate_render(p, "v001", "v001", empreinte_presentee=shown["empreinte"], accord_utilisateur=" ")
    with pytest.raises(exp.ExportError, match="rendu vidéo non validé"):
        exp.export_package(p, "film.mp4", "T")
    val.validate_render(p, "v001", "v001", empreinte_presentee=shown["empreinte"], accord_utilisateur=ACCORD)
    res = exp.export_package(p, "film.mp4", "T")
    assert Path(res["export_dir"]).name == "v001" and prj.is_locked(p)


# ---- D. non-régression ----

def test_D_validations_keep_studio_and_backlot_identities(tmp_path):
    p = prj.create_project("identites-p0b", "T", "I", 15, root=tmp_path / "projects")
    prj.register_with_backlot(p)
    prj.write_script(p, g0.SCRIPT)
    marker, backlot = (p / "studio_project.json").read_bytes(), (p / "project.json").read_bytes()
    g0.approve(p, "scenario")
    g0.add_storyboard(p)
    g0.approve(p, "storyboard", version="v001")
    assert (p / "studio_project.json").read_bytes() == marker and (p / "project.json").read_bytes() == backlot
    assert prj.require_writable(p) == p.resolve()
    from backlot.project_metadata import read_project_metadata
    assert read_project_metadata(p)["metadata_conflict"] is False


def test_D_pilot_validations_unchanged_and_still_locked():
    before = g0.tree(g0.PILOT)
    kinds = val.validations_by_kind(g0.PILOT)
    assert {"scenario", "storyboard", "reference_sonore", "rendu"} <= set(kinds)
    assert kinds["rendu"]["sha256"] == "00d118cd24867b93b2739a0e1c726143dfe607acfc1e82e736ba659e982c03e1"
    with pytest.raises(prj.ProjectLockedError):
        g0.approve(g0.PILOT, "scenario")
    assert g0.tree(g0.PILOT) == before
