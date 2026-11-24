"""Lot 1.2 — tests 6 à 10 : chemins, garde-fou budgétaire, synthèse, chaîne complète, échec propre.

Synthèse Piper locale uniquement (aucun réseau, 0 $). Toutes les écritures vont
dans le dossier temporaire de pytest.
"""

from __future__ import annotations

import hashlib
import json
import wave
from pathlib import Path

import pytest

from lib.studio.budget_guard import StudioBudgetGuard
from lib.studio.narration.synth import Synth
from lib.studio.narration.tool import (
    PROJECTS_ROOT,
    PUBLIC_STUDIO_ROOT,
    REPO_ROOT,
    PathPolicyError,
    PiperFrNarration,
    check_write_zone,
    next_version_dir,
)

SCRIPT = {
    "version": "1.0",
    "title": "Pub test",
    "total_duration_seconds": 9,
    "sections": [
        {"id": "probleme", "text": "Trop de réunions, pas assez de temps.", "start_seconds": 0.3,
         "end_seconds": 4},
        {"id": "solution", "text": "Une seule appli. [pause 0.3] 1 heure gagnée.", "start_seconds": 4,
         "end_seconds": 9, "delivery_cues": {"pause_before_seconds": 0.2}},
    ],
}


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _make_studio_project(path: Path) -> Path:
    import json
    path.mkdir(parents=True, exist_ok=True)
    (path / "studio_project.json").write_text(json.dumps({
        "studio": "OpenMontage Studio", "version": 1, "projet": path.name,
        "pipeline": "studio-fr"
    }), encoding="utf-8")
    return path


# ---- Test 6 : zones d'écriture et versions ----

@pytest.mark.parametrize("target", [
    REPO_ROOT / "projects" / "demos" / "nouveau",
    REPO_ROOT / "projects" / "demos" / "fr-series" / "code-to-screen" / "x.wav",
    REPO_ROOT / "remotion-composer" / "public" / "audio" / "fr-series" / "x",
    REPO_ROOT / "remotion-composer" / "public" / "audio" / "fr-pilot" / "x",
    REPO_ROOT / "remotion-composer" / "public" / "audio" / "studio" / "pilote-gestion-temps" / "v001" / "narration_fr.wav",
])
def test_protected_zones_refused(target):
    with pytest.raises(PathPolicyError):
        check_write_zone(target, PROJECTS_ROOT)
    with pytest.raises(PathPolicyError):
        check_write_zone(target, PUBLIC_STUDIO_ROOT)


def test_repo_outside_studio_zones_refused():
    for target in (REPO_ROOT / "lib" / "x", REPO_ROOT / "config.yaml", PROJECTS_ROOT):
        with pytest.raises(PathPolicyError):
            check_write_zone(target, PROJECTS_ROOT)
    with pytest.raises(PathPolicyError):
        check_write_zone(REPO_ROOT / "remotion-composer" / "public" / "audio" / "autre", PUBLIC_STUDIO_ROOT)


def test_allowed_zones():
    assert check_write_zone(PROJECTS_ROOT / "pub-test", PROJECTS_ROOT)
    assert check_write_zone(PUBLIC_STUDIO_ROOT / "pub-test", PUBLIC_STUDIO_ROOT)


def test_outside_repo_only_temp_allowed(tmp_path):
    assert check_write_zone(tmp_path / "p", PROJECTS_ROOT)
    with pytest.raises(PathPolicyError):
        check_write_zone(Path.home() / "Documents" / "pub-test", PROJECTS_ROOT)


def test_versions_never_overwrite(tmp_path):
    a = next_version_dir(tmp_path / "n")
    (a / "f.txt").write_text("v1")
    b = next_version_dir(tmp_path / "n")
    assert (a.name, b.name) == ("v001", "v002")
    assert (a / "f.txt").read_text() == "v1"


def test_tool_refuses_demo_project_without_writing():
    target = REPO_ROOT / "projects" / "demos" / "studio-test-interdit"
    res = PiperFrNarration().execute({"mode": "mesure", "script": SCRIPT, "project_dir": str(target)})
    assert not res.success and "protégée" in res.error
    assert not target.exists()


# ---- Test 7 : intégration au garde-fou budgétaire ----

def test_budget_guard_allows_local_narration_at_zero_cost(tmp_path):
    decision = StudioBudgetGuard(tmp_path / "p").check(PiperFrNarration(), {})
    assert decision.allowed and decision.estimated_usd == 0.0 and decision.runtime == "local"


# ---- Test 8 : synthèse d'une phrase ----

def test_short_sentence_synthesis(piper_voice, tmp_path):
    s = Synth(voice=piper_voice)
    audio = s.speak("Bonjour à tous.")
    assert s.sr == 22050 and len(audio) > 0.3 * s.sr
    out = tmp_path / "a.wav"
    s.write_wav(out, audio)
    with wave.open(str(out)) as w:
        assert (w.getnchannels(), w.getframerate(), w.getsampwidth()) == (1, 22050, 2)


def test_length_scale_other_than_one_refused(piper_voice):
    with pytest.raises(ValueError, match="length_scale"):
        Synth(length_scale=0.9, voice=piper_voice)


# ---- Test 9 : chaîne complète ----

def test_end_to_end_placement(piper_voice, tmp_path):
    project = _make_studio_project(tmp_path / "pub-test")
    public = tmp_path / "public_studio"
    guard = StudioBudgetGuard(project)
    tool = PiperFrNarration(voice=piper_voice)
    inputs = {"mode": "placement", "script": SCRIPT, "project_dir": str(project),
              "public_root": str(public), "section_options": {"solution": {"fade_out_frames": 15}}}
    res = guard.run(tool, inputs)
    assert res.success, res.error
    qc = res.data["qc"]
    assert qc["conforme"] and not qc["blocking"]
    assert abs(qc["measures"]["lufs"] + 16) <= 0.5
    assert qc["measures"]["true_peak_dbfs"] <= -1.5
    assert qc["measures"]["frequence_hz"] == 22050 and qc["measures"]["canaux"] == 1
    rows = res.data["segments"]
    assert rows[1]["texte_lu"] == "Une seule appli. une heure gagnée."
    assert "accord_feminin" in rows[1]["regles"]
    for r in rows:
        assert r["fin"] <= r["fin_max"]
    assert rows[0]["fin_max"] == round(4 - 8 / 30 - 0.5, 3)
    assert rows[1]["fin_max"] == round(9 - 15 / 30 - 0.5, 3)

    vdir = Path(res.data["version_dir"])
    assert vdir.name == "v001"
    for f in ("narration_fr.wav", "narration_fr_brut.wav", "timing_fr.json",
              "controle/rapport_narration.md", "controle/rapport_narration.json",
              "segments/probleme.wav", "segments/solution.wav"):
        assert (vdir / f).is_file(), f
    pub = public / "pub-test" / "v001" / "narration_fr.wav"
    assert pub.is_file() and _sha(pub) == _sha(vdir / "narration_fr.wav")
    report = json.loads((vdir / "controle" / "rapport_narration.json").read_text(encoding="utf-8"))
    assert report["voix"] == "fr_FR-siwis-medium" and report["length_scale"] == 1.0

    before = _sha(vdir / "narration_fr.wav")
    res2 = guard.run(tool, inputs)
    assert res2.success and Path(res2.data["version_dir"]).name == "v002"
    assert _sha(vdir / "narration_fr.wav") == before  # v001 intact
    assert not guard.cost_log_path.exists()  # rien de payant enregistré


def test_measure_mode(piper_voice, tmp_path):
    project = _make_studio_project(tmp_path / "p")
    res = PiperFrNarration(voice=piper_voice).execute(
        {"mode": "mesure", "script": SCRIPT, "project_dir": str(project)})
    assert res.success
    sec = res.data["sections"]
    assert [s["section"] for s in sec] == ["probleme", "solution"]
    for s in sec:
        assert s["duree_parole"] > 0.5 and s["tient"] is True
        assert s["duree_scene_suggeree"] > s["duree_parole"]
    assert not list((tmp_path / "p").rglob("*.wav"))
    assert Path(res.data["rapport"]).is_file()


# ---- Test 10 : phrase trop longue -> échec propre ----

def test_too_long_sentence_fails_without_final_file(piper_voice, tmp_path):
    script = {**SCRIPT, "sections": [
        {"id": "trop_long", "start_seconds": 0, "end_seconds": 2.5,
         "text": "Cette phrase est beaucoup trop longue pour tenir dans une scène de deux secondes et demie."},
    ]}
    project = _make_studio_project(tmp_path / "p")
    res = PiperFrNarration(voice=piper_voice).execute(
        {"mode": "placement", "script": script, "project_dir": str(project),
         "public_root": str(tmp_path / "pub")})
    assert not res.success and "reformuler" in res.error
    assert not list(project.rglob("*.wav"))
    assert not (tmp_path / "pub").exists()
