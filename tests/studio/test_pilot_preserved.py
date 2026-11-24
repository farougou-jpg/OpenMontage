"""Le pilote « Studio d'impact » (validé et exporté) reste strictement intact.

Manifeste : `studio/backups/pilote_protege.2026-11-18.sha256` — tous les fichiers du projet
(narrations v001/v002, storyboards, rendu, contrôle, export v001, validations…) et ses copies
audio pour Remotion. Aucun fichier modifié, ajouté ou supprimé.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
MANIFEST = REPO / "studio" / "backups" / "pilote_protege.2026-11-18.sha256"
ROOTS = ("projects/pilote-gestion-temps", "remotion-composer/public/audio/studio/pilote-gestion-temps")
VALIDATED_MP4 = "00d118cd24867b93b2739a0e1c726143dfe607acfc1e82e736ba659e982c03e1"


def _manifest() -> dict[str, str]:
    out = {}
    for line in MANIFEST.read_text(encoding="utf-8").splitlines():
        digest, path = line.split(maxsplit=1)
        out[path.lstrip("*")] = digest
    return out


def test_pilot_files_identical_to_manifest():
    expected = _manifest()
    actual = {f.relative_to(REPO).as_posix(): hashlib.sha256(f.read_bytes()).hexdigest()
              for root in ROOTS for f in sorted((REPO / root).rglob("*")) if f.is_file()}
    assert sorted(actual) == sorted(expected), "fichier ajouté ou supprimé dans le pilote"
    changed = [p for p in expected if actual[p] != expected[p]]
    assert not changed, f"fichiers du pilote modifiés : {changed}"


def test_pilot_export_is_the_validated_render():
    m = _manifest()
    assert m["projects/pilote-gestion-temps/renders/v001/pilote-studio-impact-v002.mp4"] == VALIDATED_MP4
    assert m["projects/pilote-gestion-temps/exports/v001/video/studio-impact-fr-v002.mp4"] == VALIDATED_MP4


def test_pilot_public_audio_copy_is_protected():
    from lib.studio.narration.tool import PROJECTS_ROOT, PathPolicyError, check_write_zone

    audio = REPO / "remotion-composer" / "public" / "audio" / "studio" / "pilote-gestion-temps"
    assert audio.is_dir()
    assert any(p.is_file() for p in audio.rglob("*"))
    with pytest.raises(PathPolicyError, match="Zone protégée"):
        check_write_zone(audio / "v001" / "narration_fr.wav", PROJECTS_ROOT)
