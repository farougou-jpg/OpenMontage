"""Données partagées des tests du contrôle qualité (lecture seule des vidéos françaises)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
FR = REPO / "projects" / "demos" / "fr-series"
VIDEOS = {
    "animated-reel-20s": ("animated-reel-20s-fr", "timing_fr.json"),
    "code-to-screen": ("code-to-screen-fr", "timing_fr.json"),
    "focusflow-pitch": ("focusflow-pitch-fr", "timing_fr.json"),
    "stop-procrastinating-with-this-1-hack": ("stop-procrastinating-with-this-1-hack-fr", "timing_fr.json"),
    "world-in-numbers": ("world-in-numbers-fr-v2", "timing_fr_v2.json"),
}


def paths(name: str) -> dict[str, Path]:
    stem, timing = VIDEOS[name]
    d = FR / name
    return {"mp4": d / f"{stem}.mp4", "props": d / f"{stem}.json", "timing": d / timing}


def load(name: str) -> dict:
    p = paths(name)
    return {"mp4": p["mp4"], "props": json.loads(p["props"].read_text(encoding="utf-8")),
            "timing": json.loads(p["timing"].read_text(encoding="utf-8"))}


def script_from_timing(timing: list[dict], total: float) -> dict:
    """Scénario équivalent à la narration validée (mêmes textes écrits)."""
    return {"version": "1.0", "title": "validé", "total_duration_seconds": total,
            "sections": [{"id": r["cut"], "text": r["texte_ecrit"], "start_seconds": 0, "end_seconds": 1}
                         for r in timing]}


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()
