"""Contrôles automatiques de la narration studio (bloquants / avertissements) et rapport."""

from __future__ import annotations

import json
import re
import subprocess
import wave
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

from lib.studio.narration.mastering import PEAK_CEIL_DB, TARGET_LUFS

LUFS_TOLERANCE = 0.5
MAX_SYLLABLES_PER_S = 6.5
LONG_SILENCE_S = 1.0
SUSPECT_PHONEMES = ("əʊ", "eɪ", "aɪ", "oʊ", "ɹ", "θ", "ð")


@dataclass
class QCReport:
    blocking: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    measures: dict = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return not self.blocking

    def to_dict(self) -> dict:
        return {"conforme": self.passed, **asdict(self)}


def check_timing(rows: list[dict], total: float, qc: QCReport) -> None:
    prev_end, prev_id = 0.0, None
    for r in rows:
        if r["fin"] > r["fin_max"] + 1e-6:
            qc.blocking.append(f"{r['cut']} : fin {r['fin']:.2f} s > fin max {r['fin_max']:.2f} s (reformuler).")
        if r["debut"] < prev_end - 1e-6:
            qc.blocking.append(f"{r['cut']} : chevauche {prev_id} ({r['debut']:.2f} s < {prev_end:.2f} s).")
        if r["syllabes_par_s"] > MAX_SYLLABLES_PER_S:
            qc.warnings.append(f"{r['cut']} : débit élevé ({r['syllabes_par_s']} syll/s > {MAX_SYLLABLES_PER_S}).")
        low = r["phonemes"]
        hits = [p.strip() for p in SUSPECT_PHONEMES if p in low]
        if hits:
            qc.warnings.append(f"{r['cut']} : phonèmes non français suspects {hits} — vérifier le LEXICON.")
        if re.search(r"\d", r["texte_lu"]):
            qc.warnings.append(f"{r['cut']} : chiffre non converti dans le texte lu.")
        for note in r.get("notes", []):
            qc.warnings.append(f"{r['cut']} : {note}")
        prev_end, prev_id = r["fin"], r["cut"]
    if rows and prev_end > total + 1e-6:
        qc.blocking.append(f"La parole finit à {prev_end:.2f} s, après la fin de la vidéo ({total:.2f} s).")


def check_loudness(lufs_i: float, tp: float, qc: QCReport) -> None:
    qc.measures.update({"lufs": lufs_i, "true_peak_dbfs": tp,
                        "cible_lufs": TARGET_LUFS, "plafond_true_peak_dbfs": PEAK_CEIL_DB})
    if abs(lufs_i - TARGET_LUFS) > LUFS_TOLERANCE:
        qc.blocking.append(f"Volume {lufs_i:.1f} LUFS hors de {TARGET_LUFS} ± {LUFS_TOLERANCE}.")
    if tp > PEAK_CEIL_DB:
        qc.blocking.append(f"True peak {tp:.1f} dBFS > {PEAK_CEIL_DB} dBFS.")


def check_audio(final: Path, segment_files: list[Path], qc: QCReport) -> None:
    with wave.open(str(final), "rb") as w:
        x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
        qc.measures["duree_fichier_s"] = round(w.getnframes() / w.getframerate(), 3)
        qc.measures["frequence_hz"] = w.getframerate()
        qc.measures["canaux"] = w.getnchannels()
    clipped = int(np.count_nonzero(np.abs(x.astype(np.int32)) >= 32767))
    qc.measures["echantillons_ecretes"] = clipped
    if clipped:
        qc.warnings.append(f"{clipped} échantillon(s) à pleine échelle (écrêtage possible).")
    for seg in segment_files:
        log = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(seg), "-af",
                              f"silencedetect=noise=-45dB:d={LONG_SILENCE_S}", "-f", "null", "-"],
                             capture_output=True, text=True).stderr
        n = len(re.findall(r"silence_end", log))
        if n:
            qc.warnings.append(f"{seg.stem} : {n} silence(s) de plus de {LONG_SILENCE_S} s dans la phrase.")


def write_report(qc: QCReport, rows: list[dict], out_dir: Path, header: dict) -> tuple[Path, Path]:
    ctrl = out_dir / "controle"
    ctrl.mkdir(parents=True, exist_ok=True)
    js = ctrl / "rapport_narration.json"
    js.write_text(json.dumps({**header, **qc.to_dict(), "segments": rows}, ensure_ascii=False, indent=2),
                  encoding="utf-8")
    lines = [f"# Rapport narration — {header.get('projet', '')} {header.get('version', '')}", "",
             f"**Verdict : {'CONFORME' if qc.passed else 'NON CONFORME'}**", "",
             f"- Voix : {header.get('voix')} (length_scale {header.get('length_scale')})",
             *[f"- {k} : {v}" for k, v in qc.measures.items()], "",
             "## Bloquants", *([f"- {b}" for b in qc.blocking] or ["- aucun"]), "",
             "## Avertissements (à relire)", *([f"- {w}" for w in qc.warnings] or ["- aucun"]), "",
             "## Segments", "", "| Section | Début | Fin | Fin max | Syll/s | Texte lu |", "|---|---|---|---|---|---|",
             *[f"| {r['cut']} | {r['debut']:.2f} | {r['fin']:.2f} | {r['fin_max']:.2f} | "
               f"{r['syllabes_par_s']} | {r['texte_lu']} |" for r in rows]]
    md = ctrl / "rapport_narration.md"
    md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return js, md
