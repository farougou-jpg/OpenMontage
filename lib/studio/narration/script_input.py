"""Scénario (artefact ``script``, schemas/artifacts/script.schema.json) -> segments de narration."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import jsonschema

from lib.studio.narration.synth import split_pauses

SCHEMA_PATH = Path(__file__).resolve().parents[3] / "schemas" / "artifacts" / "script.schema.json"
REFUSED_PACES = {"fast"}  # Piper V2 : jamais d'accélération, il faut reformuler.


class ScriptError(ValueError):
    """Scénario invalide pour la narration studio."""


@dataclass
class Segment:
    id: str
    text: str                    # texte écrit (tel que validé par l'utilisateur)
    start: float                 # début de la parole (s)
    end_max: float               # fin de parole au plus tard (s)
    section_end: float           # fin de la scène (s)
    pause_before: float = 0.0
    pause_after: float = 0.0
    anchor: Optional[tuple[str, float, float]] = None
    fade_out_frames: int = 8
    safety_margin_s: float = 0.5
    fps: int = 30


def load_script(script: dict | str | Path) -> dict:
    if isinstance(script, (str, Path)):
        script = json.loads(Path(script).read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(script, schema)
    except jsonschema.ValidationError as exc:
        raise ScriptError(f"Scénario non conforme au schéma : {exc.message}") from exc
    return script


def to_segments(script: dict, section_options: Optional[dict[str, dict]] = None,
                safety_margin_s: float = 0.5, fps: int = 30) -> list[Segment]:
    """Fenêtre de parole = [start + pause_before, end - pause_after - fondu - marge]."""
    section_options = section_options or {}
    segs: list[Segment] = []
    prev_end = 0.0
    seen: set[str] = set()
    for sec in script["sections"]:
        sid = sec["id"]
        if sid in seen:
            raise ScriptError(f"Section en double : {sid!r}")
        seen.add(sid)
        text = sec["text"].strip()
        if not text:
            raise ScriptError(f"{sid} : texte vide")
        split_pauses(text)  # rejette tout marqueur inconnu dès la lecture
        start, end = float(sec["start_seconds"]), float(sec["end_seconds"])
        if end <= start:
            raise ScriptError(f"{sid} : fin ({end}) avant ou égale au début ({start})")
        if start < prev_end - 1e-9:
            raise ScriptError(f"{sid} : chevauche la section précédente (début {start} < {prev_end})")
        if end > script["total_duration_seconds"] + 1e-9:
            raise ScriptError(f"{sid} : finit après la durée totale ({end} > {script['total_duration_seconds']})")
        prev_end = end

        cues = sec.get("delivery_cues") or {}
        pace = cues.get("pace")
        if pace in REFUSED_PACES:
            raise ScriptError(f"{sid} : débit « {pace} » refusé — la méthode V2 n'accélère jamais, "
                              "il faut raccourcir le texte.")
        before = float(cues.get("pause_before_seconds", 0.0))
        after = float(cues.get("pause_after_seconds", 0.0))
        opts = section_options.get(sid, {})
        fade = int(opts.get("fade_out_frames", 8))
        end_max = end - after - fade / fps - safety_margin_s
        if end_max <= start + before:
            raise ScriptError(f"{sid} : aucune place pour la parole après pauses, fondu et marge.")
        anchor = opts.get("anchor")
        segs.append(Segment(
            id=sid, text=text, start=round(start + before, 3), end_max=round(end_max, 3),
            section_end=end, pause_before=before, pause_after=after, fade_out_frames=fade,
            safety_margin_s=safety_margin_s, fps=fps,
            anchor=tuple(anchor) if anchor else None,  # type: ignore[arg-type]
        ))
    return segs
