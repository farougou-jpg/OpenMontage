"""Profil sonore B (référence validée du pilote) — length_scale 1,10, chaîne « chaleur », 48 kHz.

Le profil V2 reste le comportement par défaut, inchangé (les tests d'équivalence V2 existants
le vérifient). Synthèse Piper locale dans le dossier temporaire de pytest uniquement.
"""

from __future__ import annotations

import json
import wave
from pathlib import Path

import pytest

from lib.studio.narration.mastering import PROFILE_B_FILTERS, PROFILE_B_RATE, lufs
from lib.studio.narration.synth import PROFILE_LENGTH_SCALES, Synth
from lib.studio.narration.tool import PiperFrNarration

REPO = Path(__file__).resolve().parents[2]


def _make_studio_project(path: Path) -> Path:
    import json
    path.mkdir(parents=True, exist_ok=True)
    (path / "studio_project.json").write_text(json.dumps({
        "studio": "OpenMontage Studio", "version": 1, "projet": path.name,
        "pipeline": "studio-fr"
    }), encoding="utf-8")
    return path
VALIDATED_B = ("aresample=48000,highpass=f=80,equalizer=f=200:t=q:w=1.0:g=2,equalizer=f=450:t=q:w=1.2:g=-1.5,"
               "equalizer=f=3200:t=q:w=1.0:g=2,deesser=i=0.4,acompressor=threshold=-20dB:ratio=2:attack=8:release=120:makeup=1,"
               "aexciter=amount=1:drive=4:blend=0:freq=5000:ceil=11000")

SCRIPT = {
    "version": "1.0", "title": "Profil B test", "total_duration_seconds": 9,
    "sections": [
        {"id": "un", "text": "Trop de réunions, pas assez de temps.", "start_seconds": 0.3, "end_seconds": 4},
        {"id": "deux", "text": "Studio d'impact. Inscrivez-vous dès maintenant.", "start_seconds": 4,
         "end_seconds": 9, "delivery_cues": {"pause_before_seconds": 0.4}},
    ],
}


# ---- Paramètres ----

def test_profiles_and_length_scales():
    assert PROFILE_LENGTH_SCALES == {"V2": 1.0, "B": 1.10}


def test_profile_b_filters_identical_to_validated_reference():
    assert PROFILE_B_FILTERS == VALIDATED_B
    assert PROFILE_B_RATE == 48000
    ref = REPO / "projects" / "pilote-gestion-temps" / "assets" / "narration" / "essais" / "essai-01" / "parametres.json"
    if ref.is_file():  # lecture seule de la référence validée, si elle existe sur cette machine
        assert json.loads(ref.read_text(encoding="utf-8"))["B"]["filtres_ffmpeg"] == PROFILE_B_FILTERS


def test_length_scale_rules(piper_voice):
    with pytest.raises(ValueError, match="length_scale = 1.0 obligatoire"):
        Synth(length_scale=1.10, voice=piper_voice)                  # 1,10 refusé sans le profil B
    with pytest.raises(ValueError, match="Profil B"):
        Synth(length_scale=1.0, voice=piper_voice, profile="B")      # le profil B impose 1,10
    with pytest.raises(ValueError, match="inconnu"):
        Synth(length_scale=1.10, voice=piper_voice, profile="C")
    assert Synth(length_scale=1.10, voice=piper_voice, profile="B").length_scale == 1.10
    assert Synth(voice=piper_voice).profile == "V2"                 # défaut inchangé


def test_unknown_profile_refused_by_tool(tmp_path):
    project = _make_studio_project(tmp_path / "p")
    res = PiperFrNarration().execute({"mode": "mesure", "script": SCRIPT, "project_dir": str(project),
                                      "profil": "Z"})
    assert not res.success and "inconnu" in res.error


# ---- Chaîne complète profil B (synthèse locale, dossier temporaire) ----

def test_profile_b_end_to_end(piper_voice, tmp_path):
    project = _make_studio_project(tmp_path / "pilote-b")
    res = PiperFrNarration(voice=piper_voice).execute({
        "mode": "placement", "script": SCRIPT, "project_dir": str(project),
        "public_root": str(tmp_path / "public"), "profil": "B"})
    assert res.success, res.error
    qc = res.data["qc"]
    assert qc["conforme"] and not qc["blocking"], qc["blocking"]
    assert abs(qc["measures"]["lufs"] + 16) <= 0.5 and qc["measures"]["true_peak_dbfs"] <= -1.5
    assert qc["measures"]["echantillons_ecretes"] == 0
    v = Path(res.data["version_dir"])
    with wave.open(str(v / "narration_fr.wav")) as w:
        assert (w.getframerate(), w.getsampwidth(), w.getnchannels()) == (48000, 3, 1)
        assert abs(w.getnframes() / w.getframerate() - 9.0) < 0.01
    with wave.open(str(v / "narration_fr_brut.wav")) as w:
        assert (w.getframerate(), w.getsampwidth()) == (22050, 2)
    rows = json.loads((v / "timing_fr.json").read_text(encoding="utf-8"))
    assert all(r["length_scale"] == 1.10 and r["profil"] == "B" for r in rows)
    assert rows[1]["debut"] == 4.4 and all(r["fin"] <= r["fin_max"] for r in rows)
    report = json.loads((v / "controle" / "rapport_narration.json").read_text(encoding="utf-8"))
    assert report["profil"] == "B" and report["length_scale"] == 1.10
    assert not list(v.glob("_*.wav"))                                # fichiers intermédiaires retirés
    assert Path(res.data["public_wav"]).read_bytes() == (v / "narration_fr.wav").read_bytes()


def test_profile_b_is_slower_than_v2(piper_voice, tmp_path):
    """À texte égal, le profil B (1,10) parle plus lentement que la V2 (1,0)."""
    durations = {}
    for profile in ("V2", "B"):
        project = _make_studio_project(tmp_path / profile)
        res = PiperFrNarration(voice=piper_voice).execute({
            "mode": "mesure", "script": SCRIPT, "project_dir": str(project), "profil": profile})
        assert res.success, res.error
        durations[profile] = sum(s["duree_parole"] for s in res.data["sections"])
    assert durations["B"] > durations["V2"] * 1.03
