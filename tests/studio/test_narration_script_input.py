"""Lot 1.2 — tests 4 et 5 : scénario -> segments, marqueurs de pause."""

from __future__ import annotations

import copy

import pytest

from lib.studio.narration.script_input import ScriptError, load_script, to_segments
from lib.studio.narration.synth import PauseMarkupError, split_pauses

BASE = {
    "version": "1.0",
    "title": "Test",
    "total_duration_seconds": 12,
    "sections": [
        {"id": "s1", "text": "Trop de réunions.", "start_seconds": 0, "end_seconds": 4},
        {"id": "s2", "text": "Une seule appli.", "start_seconds": 4, "end_seconds": 8,
         "delivery_cues": {"pace": "conversational", "pause_before_seconds": 0.3,
                           "pause_after_seconds": 0.2}},
        {"id": "s3", "text": "Essayez-la.", "start_seconds": 8, "end_seconds": 12},
    ],
}


def _script(patch):
    s = copy.deepcopy(BASE)
    for (i, key), val in patch.items():
        s["sections"][i][key] = val
    return s


# ---- Test 4 : conversion du scénario ----

def test_valid_script_windows():
    segs = to_segments(load_script(BASE), {"s3": {"fade_out_frames": 15}})
    s1, s2, s3 = segs
    assert (s1.start, s1.end_max) == (0.0, round(4 - 8 / 30 - 0.5, 3))
    assert s2.start == 4.3 and s2.end_max == round(8 - 0.2 - 8 / 30 - 0.5, 3)
    assert s3.end_max == round(12 - 15 / 30 - 0.5, 3)


def test_schema_violation_rejected():
    bad = copy.deepcopy(BASE)
    del bad["sections"][0]["text"]
    with pytest.raises(ScriptError):
        load_script(bad)


@pytest.mark.parametrize("patch,msg", [
    ({(0, "end_seconds"): 0}, "avant"),
    ({(1, "start_seconds"): 3}, "chevauche"),
    ({(0, "text"): "   "}, "vide"),
    ({(2, "end_seconds"): 20}, "durée totale"),
])
def test_invalid_scripts_rejected(patch, msg):
    with pytest.raises(ScriptError, match=msg):
        to_segments(load_script(_script(patch)))


def test_fast_pace_refused_never_accelerated():
    s = copy.deepcopy(BASE)
    s["sections"][1]["delivery_cues"]["pace"] = "fast"
    with pytest.raises(ScriptError, match="raccourcir"):
        to_segments(load_script(s))


def test_no_room_for_speech_rejected():
    s = _script({(0, "end_seconds"): 0.7})
    s["sections"][1]["start_seconds"] = 0.7
    with pytest.raises(ScriptError, match="aucune place"):
        to_segments(load_script(s))


def test_duplicate_section_rejected():
    s = copy.deepcopy(BASE)
    s["sections"][2]["id"] = "s1"
    with pytest.raises(ScriptError, match="double"):
        to_segments(load_script(s))


# ---- Test 5 : marqueurs de pause ----

def test_pause_marker_parsed():
    assert split_pauses("Trois problèmes. [pause 0.4] Une solution.") == [
        ("Trois problèmes.", 0.4), ("Une solution.", 0.0)]
    assert split_pauses("A [pause 0,25] B") == [("A", 0.25), ("B", 0.0)]


@pytest.mark.parametrize("text", [
    "Bonjour [respire] à tous.",
    "Bonjour [pause] à tous.",
    "[pause 0.4] Bonjour.",
    "Bonjour. [pause 0.4]",
    "Bonjour [pause 5] toi.",
])
def test_unknown_or_bad_markers_rejected(text):
    with pytest.raises(PauseMarkupError):
        split_pauses(text)


def test_raw_phonemes_are_not_markers():
    assert split_pauses("de Tokyo à [[ saw pawlˈo ]].") == [("de Tokyo à [[ saw pawlˈo ]].", 0.0)]


def test_bad_marker_rejected_at_script_load():
    with pytest.raises(PauseMarkupError):
        to_segments(load_script(_script({(0, "text"): "Trop [bip] de réunions."})))
