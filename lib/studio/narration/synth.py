"""Synthèse Piper FR — logique reprise à l'identique de fr-series/common/fr_build.py (V2).

Seules additions : la voix peut être injectée (tests) et les marqueurs de pause
explicites ``[pause 0.4]`` sont découpés AVANT la synthèse (hors V2, optionnels).
"""

from __future__ import annotations

import re
import wave
from pathlib import Path
from typing import Any, Optional

import numpy as np

MODEL = Path.home() / ".piper" / "models" / "fr_FR-siwis-medium.onnx"
VOICE_NAME = "fr_FR-siwis-medium"
FADE_IN, FADE_OUT = 0.012, 0.060
VOWELS = set("aeiouyɑɛɔøœəɪʊʏɐæɜɤɯ")
PAUSE_MARK = re.compile(r"\[\s*pause\s+(\d+(?:[.,]\d+)?)\s*\]", re.IGNORECASE)
ANY_BRACKET_WORD = re.compile(r"\[(?!\[)[^\]]*\](?!\])")  # [xxx] mais pas [[ phonèmes ]]


class PauseMarkupError(ValueError):
    """Marqueur entre crochets non reconnu (il serait lu à voix haute)."""


def split_pauses(text: str) -> list[tuple[str, float]]:
    """« A [pause 0.4] B » -> [("A", 0.4), ("B", 0.0)]. Rejette tout autre [..]."""
    parts: list[tuple[str, float]] = []
    pos = 0
    for m in PAUSE_MARK.finditer(text):
        parts.append((text[pos:m.start()].strip(), float(m.group(1).replace(",", "."))))
        pos = m.end()
    parts.append((text[pos:].strip(), 0.0))
    for chunk, _ in parts:
        bad = [b for b in ANY_BRACKET_WORD.findall(chunk) if not b.startswith("[[")]
        if bad:
            raise PauseMarkupError(f"Marqueur inconnu {bad[0]!r} : seul [pause X] est accepté.")
    for chunk, pause in parts[:-1]:
        if pause <= 0 or pause > 3.0:
            raise PauseMarkupError(f"Pause {pause} s hors limites (0 < pause ≤ 3 s).")
    if any(not chunk for chunk, _ in parts):
        raise PauseMarkupError("Un marqueur [pause X] ne peut pas commencer ou finir une phrase.")
    return parts


def load_voice(model: Path = MODEL):
    from piper import PiperVoice
    if not model.is_file():
        raise FileNotFoundError(f"Voix Piper introuvable : {model}")
    return PiperVoice.load(str(model))


PROFILE_LENGTH_SCALES = {"V2": 1.0, "B": 1.10}


class Synth:
    """Équivalent du ``Builder`` de fr_build.py (méthodes audio identiques)."""

    def __init__(self, length_scale: float = 1.0, sentence_pause: float = 0.30,
                 voice: Optional[Any] = None, profile: str = "V2") -> None:
        from piper import SynthesisConfig
        # Profils validés : V2 (défaut, 1,0) ; B (référence sonore du pilote, 1,10). Aucune autre valeur.
        expected = PROFILE_LENGTH_SCALES.get(profile)
        if expected is None:
            raise ValueError(f"Profil de narration inconnu : {profile!r} (profils : {sorted(PROFILE_LENGTH_SCALES)}).")
        if length_scale != expected:
            if profile == "V2":
                raise ValueError("Méthode V2 : length_scale = 1.0 obligatoire (reformuler, ne pas accélérer).")
            raise ValueError(f"Profil {profile} : length_scale = {expected} obligatoire (valeur reçue : {length_scale}).")
        self.profile = profile
        self.length_scale = length_scale
        self.voice = voice if voice is not None else load_voice()
        self.sr = self.voice.config.sample_rate
        self.syn = SynthesisConfig(length_scale=length_scale)
        self.pause = sentence_pause

    # --- audio (copie de fr_build.Builder) ---
    def trim(self, x, thresh=0.004, pad=0.08):
        idx = np.flatnonzero(np.abs(x) > thresh)
        if idx.size == 0:
            return x
        p = int(pad * self.sr)
        return x[max(0, idx[0] - p): idx[-1] + p]

    def fade(self, x):
        x = x.copy()
        fi, fo = int(FADE_IN * self.sr), int(FADE_OUT * self.sr)
        x[:fi] *= np.linspace(0, 1, fi)
        x[-fo:] *= np.linspace(1, 0, fo) ** 2
        return x

    def speak(self, text: str) -> np.ndarray:
        parts = [self.fade(self.trim(c.audio_int16_array.astype(np.float32) / 32768))
                 for c in self.voice.synthesize(text, syn_config=self.syn)]
        gap = np.zeros(int(self.pause * self.sr), dtype=np.float32)
        out = parts[0]
        for p in parts[1:]:
            out = np.concatenate([out, gap, p])
        return out

    def syllables(self, text: str) -> int:
        return sum(1 for c in "".join("".join(s) for s in self.voice.phonemize(text)) if c in VOWELS)

    def phonemes(self, text: str) -> str:
        return " | ".join("".join(s) for s in self.voice.phonemize(text))

    def rms_db(self, x):
        f = int(0.02 * self.sr)
        rms = np.sqrt((x[: len(x) // f * f].reshape(-1, f) ** 2).mean(axis=1))
        v = rms[rms > rms.max() * 0.1]
        return 20 * np.log10(np.sqrt((v ** 2).mean()) + 1e-9)

    def write_wav(self, path: Path, x):
        path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(path), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(self.sr)
            w.writeframes((np.clip(x, -1, 1) * 32767).astype(np.int16).tobytes())

    # --- ajout studio : pauses explicites ---
    def speak_with_pauses(self, spoken_parts: list[tuple[str, float]]) -> np.ndarray:
        """Chaque morceau est dit par ``speak`` (V2) ; les pauses sont des silences exacts."""
        if len(spoken_parts) == 1:
            return self.speak(spoken_parts[0][0])
        out = []
        for text, pause in spoken_parts:
            out.append(self.speak(text))
            if pause:
                out.append(np.zeros(int(round(pause * self.sr)), dtype=np.float32))
        return np.concatenate(out)
