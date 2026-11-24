"""Mixage et mastering de la narration (V2) + seconde passe true peak automatique.

Première passe : identique à fr_build.py (égalisation des phrases sur la médiane
RMS, gain vers -16 LUFS, alimiter à -1,5 dBFS). Le limiteur V2 agit sur les
échantillons : le true peak peut dépasser -1,5 dBFS (cas world-in-numbers :
-1,3). Si c'est le cas, une seconde passe suréchantillonnée est appliquée
(aresample 88200 -> alimiter -> retour à la fréquence d'origine), la version de
première passe étant conservée sous ``narration_fr_brut.wav``.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import numpy as np

TARGET_LUFS, PEAK_CEIL_DB = -16.0, -1.5
OVERSAMPLE_RATE = 88200


def lufs(path: Path) -> tuple[float, float]:
    """(LUFS intégré, true peak dBFS) via ffmpeg ebur128 — identique à fr_build.lufs."""
    log = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-af", "ebur128=peak=true",
                          "-f", "null", "-"], capture_output=True, text=True).stderr
    return (float(re.findall(r"I:\s+(-?[\d.]+) LUFS", log)[-1]),
            float(re.findall(r"Peak:\s+(-?[\d.]+) dBFS", log)[-1]))


@dataclass
class MasterResult:
    final: Path
    brut: Path
    lufs: float
    true_peak: float
    lufs_brut: float
    true_peak_brut: float
    second_pass: bool
    level_spread_db: float


def mix_track(synth, rendered: list[tuple[float, np.ndarray]], total: float):
    """Égalisation des phrases + placement sur la piste (copie de fr_build.main)."""
    levels = [synth.rms_db(a) for _, a in rendered]
    ref = float(np.median(levels))
    track = np.zeros(int(round(total * synth.sr)), dtype=np.float32)
    for (start, audio), lvl in zip(rendered, levels):
        i0 = int(round(start * synth.sr))
        track[i0:i0 + len(audio)] += audio * 10 ** ((ref - lvl) / 20)
    return track, levels


def master(synth, rendered: list[tuple[float, np.ndarray]], total: float, out_dir: Path) -> MasterResult:
    track, levels = mix_track(synth, rendered, total)
    raw = out_dir / "_raw.wav"
    brut = out_dir / "narration_fr_brut.wav"
    final = out_dir / "narration_fr.wav"
    synth.write_wav(raw, track)
    gain = TARGET_LUFS - lufs(raw)[0]
    limit = 10 ** (PEAK_CEIL_DB / 20)
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(raw), "-af",
                    f"volume={gain:.2f}dB,alimiter=limit={limit:.3f}:attack=3:release=60:level=disabled",
                    "-ar", str(synth.sr), "-ac", "1", "-c:a", "pcm_s16le", str(brut)], check=True)
    raw.unlink()
    i_brut, pk_brut = lufs(brut)

    second = pk_brut > PEAK_CEIL_DB
    if second:
        # Plafond légèrement sous -1,5 pour absorber l'arrondi de la mesure.
        limit2 = 10 ** ((PEAK_CEIL_DB - 0.2) / 20)
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(brut), "-af",
                        f"aresample={OVERSAMPLE_RATE},alimiter=limit={limit2:.3f}:attack=3:release=60:level=disabled,"
                        f"aresample={synth.sr}",
                        "-ar", str(synth.sr), "-ac", "1", "-c:a", "pcm_s16le", str(final)], check=True)
    else:
        shutil.copyfile(brut, final)
    i, pk = lufs(final)
    return MasterResult(final=final, brut=brut, lufs=i, true_peak=pk, lufs_brut=i_brut,
                        true_peak_brut=pk_brut, second_pass=second,
                        level_spread_db=float(max(levels) - min(levels)) if levels else 0.0)


# ---- Profil B : référence sonore validée du pilote (essai-01, version B, 2026-11-18) ----
# Synthèse à length_scale 1,10 (voir synth.PROFILE_LENGTH_SCALES), puis chaîne « chaleur et
# présence » en 48 kHz / 24 bits. Chaîne de filtres identique, caractère pour caractère, à
# projects/pilote-gestion-temps/assets/narration/essais/essai-01/parametres.json (version B).
PROFILE_B_FILTERS = (
    "aresample=48000,highpass=f=80,equalizer=f=200:t=q:w=1.0:g=2,equalizer=f=450:t=q:w=1.2:g=-1.5,"
    "equalizer=f=3200:t=q:w=1.0:g=2,deesser=i=0.4,acompressor=threshold=-20dB:ratio=2:attack=8:release=120:makeup=1,"
    "aexciter=amount=1:drive=4:blend=0:freq=5000:ceil=11000"
)
PROFILE_B_RATE = 48000
PROFILE_B_LIMITER_RATE = 192000
PROFILE_B_INTERNAL_CEIL_DB = PEAK_CEIL_DB - 0.2   # -1,7 dBFS, comme la version B validée


def _ffmpeg(args: list[str]) -> None:
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args], check=True)


def master_profile_b(synth, rendered: list[tuple[float, np.ndarray]], total: float, out_dir: Path) -> MasterResult:
    """Même égalisation des phrases que la V2, puis la chaîne B, -16 LUFS, limiteur suréchantillonné.

    narration_fr_brut.wav : piste égalisée, sans chaîne B ni normalisation (22 050 Hz, 16 bits).
    narration_fr.wav      : version finale profil B (48 000 Hz, 24 bits, mono).
    """
    track, levels = mix_track(synth, rendered, total)
    brut = out_dir / "narration_fr_brut.wav"
    final = out_dir / "narration_fr.wav"
    tmp = out_dir / "_chaine_b.wav"
    synth.write_wav(brut, track)
    i_brut, pk_brut = lufs(brut)
    _ffmpeg(["-i", str(brut), "-af", PROFILE_B_FILTERS, "-ar", str(PROFILE_B_RATE), "-ac", "1",
             "-c:a", "pcm_s24le", str(tmp)])
    gain = TARGET_LUFS - lufs(tmp)[0]
    limit = 10 ** (PROFILE_B_INTERNAL_CEIL_DB / 20)
    _ffmpeg(["-i", str(tmp), "-af",
             f"volume={gain:.2f}dB,aresample={PROFILE_B_LIMITER_RATE},"
             f"alimiter=limit={limit:.3f}:attack=3:release=60:level=disabled,aresample={PROFILE_B_RATE}",
             "-ar", str(PROFILE_B_RATE), "-ac", "1", "-c:a", "pcm_s24le", str(final)])
    tmp.unlink()
    i, pk = lufs(final)
    return MasterResult(final=final, brut=brut, lufs=i, true_peak=pk, lufs_brut=i_brut,
                        true_peak_brut=pk_brut, second_pass=True,
                        level_spread_db=float(max(levels) - min(levels)) if levels else 0.0)
