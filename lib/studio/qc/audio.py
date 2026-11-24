"""Audio du MP4 : volume, true peak, écrêtage, intervalles de parole — lecture seule."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import numpy as np

from lib.studio.narration.mastering import lufs

TARGET_LUFS, LUFS_TOL = -16.0, 1.0
TRUE_PEAK_MAX = -1.0
SILENCE_NOISE_DB, SILENCE_MIN_S = -45, 0.25   # calibré sur le contrôle manuel de world-in-numbers


def check_loudness(mp4: Path, qc) -> tuple[float, float]:
    i, tp = lufs(mp4)
    qc.measures["audio"] = {"lufs": i, "true_peak_dbfs": tp, "cible_lufs": TARGET_LUFS,
                            "tolerance_lu": LUFS_TOL, "true_peak_max_dbfs": TRUE_PEAK_MAX}
    if abs(i - TARGET_LUFS) > LUFS_TOL:
        qc.block("Volume", f"{i:.1f} LUFS hors de {TARGET_LUFS:.0f} ± {LUFS_TOL:.0f}")
    else:
        qc.ok("Volume", f"{i:.1f} LUFS")
    if tp > TRUE_PEAK_MAX:
        qc.block("True peak", f"{tp:.1f} dBFS > {TRUE_PEAK_MAX:.1f} dBFS")
    else:
        qc.ok("True peak", f"{tp:.1f} dBFS")
    return i, tp


def check_clipping(mp4: Path, qc) -> int:
    """Décodage en mémoire (aucun fichier écrit) et comptage des échantillons saturés."""
    raw = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(mp4), "-map", "0:a",
                          "-f", "f32le", "-acodec", "pcm_f32le", "-"], capture_output=True, check=True).stdout
    x = np.frombuffer(raw, dtype=np.float32)
    clipped = int(np.count_nonzero(np.abs(x) >= 0.999))
    qc.measures.setdefault("audio", {})["echantillons_satures"] = clipped
    if clipped:
        qc.block("Écrêtage", f"{clipped} échantillon(s) saturé(s)")
    else:
        qc.ok("Écrêtage", "aucun échantillon saturé")
    return clipped


def speech_intervals(mp4: Path, dur: float) -> tuple[list[tuple[float, float]], str]:
    """Intervalles de parole = complément des silences (silencedetect -45 dB, 0,25 s)."""
    log = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(mp4), "-map", "0:a", "-af",
                          f"silencedetect=noise={SILENCE_NOISE_DB}dB:d={SILENCE_MIN_S}", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    starts = [float(x) for x in re.findall(r"silence_start: (-?[\d.]+)", log)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", log)]
    silences = list(zip(starts, ends + [dur] * (len(starts) - len(ends))))
    speech, cursor = [], 0.0
    for s, e in silences:
        if s > cursor + 1e-6:
            speech.append((round(cursor, 3), round(s, 3)))
        cursor = e
    if cursor < dur - 1e-6:
        speech.append((round(cursor, 3), round(dur, 3)))
    raw = "\n".join(l for l in log.splitlines() if "silence_" in l)
    return speech, raw
