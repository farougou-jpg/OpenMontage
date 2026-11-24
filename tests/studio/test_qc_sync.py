"""Lot 1.6 — tests 3 et 4 : synchronisation parole / scènes, seuils de marge, décalage."""

from __future__ import annotations

import copy
from functools import lru_cache

import pytest

from lib.studio.qc import audio, probe, sync
from lib.studio.qc.report import QCResult
from tests.studio.qc_data import load


@lru_cache(maxsize=None)
def measured(name: str):
    d = load(name)
    dur = probe.check_format(probe.ffprobe(d["mp4"]), d["props"], QCResult())["duree_s"]
    speech, _ = audio.speech_intervals(d["mp4"], dur)
    return d, tuple(speech), dur


def run(name, timing=None):
    d, speech, dur = measured(name)
    qc = QCResult()
    rows = sync.check_sync(d["props"], timing if timing is not None else d["timing"], list(speech), dur, qc)
    return qc, {r["scene"]: r for r in rows}


# ---- Test 3 : world-in-numbers = rapport manuel validé ----

MANUAL = {  # rapport_qc.md de world-in-numbers (voix début, voix fin, marge)
    "world-hook": (0.53, 2.14, 1.1), "world-population": (3.88, 6.69, 0.5),
    "world-cities": (7.93, 11.28, 1.2), "world-energy": (13.48, 16.97, 0.5),
    "world-close": (18.43, 21.36, 0.37),
}


def test_world_in_numbers_matches_manual_report():
    qc, rows = run("world-in-numbers")
    for sid, (start, end, margin) in MANUAL.items():
        r = rows[sid]
        assert abs(r["voix_debut_s"] - start) <= 0.1 and abs(r["voix_fin_s"] - end) <= 0.1
        assert abs(r["marge_s"] - margin) <= 0.1
    assert rows["world-cities"]["nature_limite"].startswith("fondu du graphique")
    assert rows["world-hook"]["nature_limite"].startswith("marge de sécurité")
    assert qc.conforme
    assert [w for w in qc.warnings if "Marge" in w] == ["Marge de parole — world-close : 0.38 s (entre 0.25 et 0.5 s)"]


@pytest.mark.parametrize("name", ["code-to-screen", "focusflow-pitch", "stop-procrastinating-with-this-1-hack"])
def test_other_validated_videos_are_in_sync(name):
    qc, rows = run(name)
    assert qc.conforme and not qc.warnings, (qc.blocking, qc.warnings)
    assert all(abs(r["ecart_fin_s"]) <= 0.10 for r in rows.values() if "ecart_fin_s" in r)


def test_animated_reel_is_flagged_by_the_validated_thresholds():
    """Constat du lot 1.6 : marges de 0,18 et 0,21 s (< 0,25 s) sur hook et story."""
    qc, rows = run("animated-reel-20s")
    assert not qc.conforme
    assert rows["hook"]["statut"] == "❌" and rows["story"]["statut"] == "❌"
    assert 0.15 < rows["hook"]["marge_s"] < 0.25 and 0.15 < rows["story"]["marge_s"] < 0.25
    assert rows["momentum"]["statut"] == "✅" and rows["final"]["statut"] == "✅"


# ---- Seuils de marge (données synthétiques, aucun média) ----

PROPS = {"cuts": [{"id": "a", "type": "hero_title", "in_seconds": 0, "out_seconds": 4},
                  {"id": "b", "type": "bar_chart", "in_seconds": 4, "out_seconds": 10}]}


@pytest.mark.parametrize("end,status", [(3.2, "✅"), (3.40, "⚠️"), (3.55, "❌")])
def test_margin_thresholds_text_scene(end, status):
    # fin utile = 4 − 8/30 = 3,733 s → marges 0,53 / 0,33 / 0,18 s.
    # Timing cohérent fourni : seul le seuil de marge détermine le statut.
    timing = [{"cut": "a", "debut": 0.4, "fin": end, "texte_ecrit": "x"}]
    qc = QCResult()
    rows = sync.check_sync(PROPS, timing, [(0.5, end)], 12.0, qc)
    assert rows[0]["statut"] == status
    assert not any("timing_fr.json" in w for w in qc.warnings)


def test_missing_timing_is_a_warning_and_short_margin_a_block():
    """Deux anomalies distinctes, jamais confondues :
    timing absent → avertissement seul ; marge < 0,25 s → blocage (même avec un timing)."""
    qc = QCResult()
    rows = sync.check_sync(PROPS, [], [(0.5, 3.2)], 12.0, qc)          # marge 0,53 s, timing absent
    assert rows[0]["statut"] == "⚠️" and qc.conforme
    assert qc.warnings == ["Synchronisation — a : parole détectée sans entrée dans timing_fr.json"]

    qc = QCResult()
    timing = [{"cut": "a", "debut": 0.4, "fin": 3.55, "texte_ecrit": "x"}]
    rows = sync.check_sync(PROPS, timing, [(0.5, 3.55)], 12.0, qc)     # marge 0,18 s, timing présent
    assert rows[0]["statut"] == "❌" and not qc.conforme
    assert any(b.startswith("Marge de parole — a : 0.18 s") for b in qc.blocking)
    assert not qc.warnings


def test_margin_uses_chart_fade_for_charts():
    qc = QCResult()
    timing = [{"cut": "b", "debut": 4.4, "fin": 9.2, "texte_ecrit": "x"}]
    rows = sync.check_sync(PROPS, timing, [(4.5, 9.2)], 12.0, qc)   # fin utile 9,5 → marge 0,30
    assert rows[1]["limite_s"] == 9.5 and rows[1]["statut"] == "⚠️"
    assert qc.warnings == ["Marge de parole — b : 0.30 s (entre 0.25 et 0.5 s)"]


def test_speech_crossing_scene_start_is_blocked():
    qc = QCResult()
    sync.check_sync(PROPS, [], [(3.9, 4.6)], 12.0, qc)   # milieu dans b, début dans a
    assert not qc.conforme and any("commence avant la scène" in b for b in qc.blocking)


def test_last_second_rule():
    qc = QCResult()
    sync.check_sync({"cuts": [{"id": "a", "type": "hero_title", "in_seconds": 0, "out_seconds": 10}]},
                    [], [(1, 9.9)], 10.0, qc)
    assert any("Dernière seconde" in b for b in qc.blocking)


# ---- Test 4 : décalage simulé en mémoire ----

def test_shifted_timing_is_detected():
    d, _, _ = measured("code-to-screen")
    shifted = copy.deepcopy(d["timing"])
    for r in shifted:
        r["debut"] += 0.5
        r["fin"] += 0.5
    qc, _ = run("code-to-screen", shifted)
    assert not qc.conforme and any("Décalage audio" in b for b in qc.blocking)


def test_missing_speech_is_blocked():
    d, _, _ = measured("code-to-screen")
    extra = copy.deepcopy(d["timing"]) + [{"cut": "fantome", "debut": 1, "fin": 2, "texte_ecrit": "x"}]
    props = copy.deepcopy(d["props"])
    props["cuts"].append({"id": "fantome", "type": "hero_title", "in_seconds": 24, "out_seconds": 24.9})
    qc = QCResult()
    _, speech, dur = measured("code-to-screen")
    sync.check_sync(props, extra, list(speech), dur, qc)
    assert any("non détectée" in b for b in qc.blocking)
