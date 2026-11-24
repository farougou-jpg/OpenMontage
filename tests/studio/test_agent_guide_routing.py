"""Lot 1.3 — AGENT_GUIDE.md : seule la ligne de routage studio-fr a été ajoutée."""

from __future__ import annotations

import difflib
import hashlib
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
GUIDE = REPO / "AGENT_GUIDE.md"
BACKUP = REPO / "studio" / "backups" / "AGENT_GUIDE.md.2026-11-17.bak"
BACKUP_SHA = REPO / "studio" / "backups" / "AGENT_GUIDE.md.2026-11-17.bak.sha256"
ORIGINAL_SHA = "a060300bca8786755b7b04fb4df618348b38c9806c67a910ecf3bb5a44560799"
ROUTING_PREFIX = "**OpenMontage Studio (français) :**"


def test_backup_matches_original_hash():
    assert hashlib.sha256(BACKUP.read_bytes()).hexdigest() == ORIGINAL_SHA
    assert BACKUP_SHA.read_text(encoding="utf-8").split()[0] == ORIGINAL_SHA


def test_only_the_routing_line_was_added():
    old = BACKUP.read_text(encoding="utf-8").splitlines()
    new = GUIDE.read_text(encoding="utf-8").splitlines()
    diff = [d for d in difflib.ndiff(old, new) if d[:2] in ("- ", "+ ")]
    assert not [d for d in diff if d.startswith("- ")], "une ligne existante a été supprimée ou modifiée"
    added = [d[2:] for d in diff if d.startswith("+ ")]
    assert len(added) == 2 and added.count("") == 1  # une ligne de routage + une ligne vide
    routing = next(a for a in added if a)
    assert routing.startswith(ROUTING_PREFIX)
    for token in ("studio-fr", "studio/README.md", "skills/pipelines/studio-fr/executive-producer.md"):
        assert token in routing
    assert len(new) == len(old) + 2


def test_routing_line_sits_in_onboarding_section():
    text = GUIDE.read_text(encoding="utf-8")
    onboarding = text.index("## First Interaction — Onboarding")
    reference = text.index("## Reference Video Entry Point")
    assert onboarding < text.index(ROUTING_PREFIX) < reference


def test_available_pipelines_table_unchanged():
    def table(t: str) -> str:
        start = t.index("## Available Pipelines")
        return t[start:t.index("## Mandatory Preflight")]
    assert table(GUIDE.read_text(encoding="utf-8")) == table(BACKUP.read_text(encoding="utf-8"))
    assert "studio-fr" not in table(GUIDE.read_text(encoding="utf-8"))


def test_routing_targets_exist():
    for p in ("studio/README.md", "skills/pipelines/studio-fr/executive-producer.md",
              "pipeline_defs/studio-fr.yaml"):
        assert (REPO / p).is_file(), p
