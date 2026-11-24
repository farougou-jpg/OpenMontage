"""Lot 1.2 — test 12 : les fichiers des vidéos françaises restent intacts.

Compare l'état actuel aux empreintes SHA-256 enregistrées le 2026-11-17 avant le
lot 1.2 (studio/backups/fr_protected.2026-11-17.sha256). Le préfixe « zz » fait
passer ce test après les autres tests du dossier studio.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
MANIFEST = REPO / "studio" / "backups" / "fr_protected.2026-11-17.sha256"
PROTECTED_DIRS = [
    "projects/demos/fr-series",
    "projects/demos/fr-pilot",
    "remotion-composer/public/audio/fr-series",
    "remotion-composer/public/audio/fr-pilot",
]


def _manifest() -> dict[str, str]:
    out = {}
    for line in MANIFEST.read_text(encoding="utf-8").splitlines():
        digest, path = line.split(None, 1)
        out[path.strip()] = digest
    return out


def _current() -> dict[str, str]:
    out = {}
    for d in PROTECTED_DIRS:
        for f in sorted((REPO / d).rglob("*")):
            if f.is_file() and "__pycache__" not in f.parts:
                out[f.relative_to(REPO).as_posix()] = hashlib.sha256(f.read_bytes()).hexdigest()
    return out


def test_protected_french_files_unchanged():
    expected, current = _manifest(), _current()
    assert len(expected) == 151
    missing = sorted(set(expected) - set(current))
    added = sorted(set(current) - set(expected))
    changed = sorted(p for p in expected if p in current and current[p] != expected[p])
    assert not missing, f"fichiers disparus : {missing}"
    assert not added, f"fichiers ajoutés dans une zone protégée : {added}"
    assert not changed, f"fichiers modifiés : {changed}"
