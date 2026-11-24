"""Lot 1.6 — tests 1, 2, 9 : format, volume, true peak, écrêtage (vidéos françaises lues sans modification)."""

from __future__ import annotations

import pytest

from lib.studio.qc import audio, probe
from lib.studio.qc.report import QCResult
from tests.studio.qc_data import VIDEOS, load, paths, sha

# Mesures relevées sur les MP4 validés (ebur128, true peak) le 2026-11-18 ;
# world-in-numbers : identiques au rapport manuel (−16,2 LUFS, −4,4 dBFS).
EXPECTED_LOUDNESS = {
    "animated-reel-20s": (-16.1, -4.4),
    "code-to-screen": (-16.1, -4.8),
    "focusflow-pitch": (-16.3, -4.8),
    "stop-procrastinating-with-this-1-hack": (-16.1, -4.8),
    "world-in-numbers": (-16.2, -4.4),
}


@pytest.mark.parametrize("name", list(VIDEOS))
def test_format_of_validated_videos(name):
    d = load(name)
    qc = QCResult()
    m = probe.check_format(probe.ffprobe(d["mp4"]), d["props"], qc)
    assert qc.conforme, qc.blocking
    assert (m["largeur"], m["hauteur"], m["images_par_seconde"]) == (1920, 1080, "30/1")
    assert m["video_codec"] == "h264" and m["audio_codec"] == "aac"
    assert abs(m["nb_images"] - m["nb_images_attendu"]) <= 1


def test_format_detects_wrong_frame_count():
    d = load("code-to-screen")
    props = {**d["props"], "tailPaddingSeconds": 3}
    qc = QCResult()
    probe.check_format(probe.ffprobe(d["mp4"]), props, qc)
    assert not qc.conforme and "images" in qc.blocking[0]


@pytest.mark.parametrize("name", list(VIDEOS))
def test_loudness_and_clipping_of_validated_videos(name):
    mp4 = paths(name)["mp4"]
    before = sha(mp4)
    qc = QCResult()
    i, tp = audio.check_loudness(mp4, qc)
    assert (i, tp) == EXPECTED_LOUDNESS[name]
    assert audio.check_clipping(mp4, qc) == 0
    assert qc.conforme, qc.blocking
    assert sha(mp4) == before


@pytest.mark.parametrize("measure,blocked", [
    ((-16.9, -1.0), False), ((-15.0, -2.0), False),
    ((-17.2, -3.0), True), ((-14.8, -3.0), True), ((-16.0, -0.9), True),
])
def test_audio_thresholds(monkeypatch, measure, blocked):
    monkeypatch.setattr(audio, "lufs", lambda _p: measure)
    qc = QCResult()
    audio.check_loudness(paths("code-to-screen")["mp4"], qc)
    assert (not qc.conforme) == blocked
