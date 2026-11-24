"""Lot 1.3 — règles de l'aiguilleur ajoutées à la demande de l'utilisateur (2026-11-17)."""

from __future__ import annotations

from pathlib import Path

ROUTER = Path(__file__).resolve().parents[2] / "skills" / "meta" / "studio-creative-router.md"


def _flat() -> str:
    return " ".join(ROUTER.read_text(encoding="utf-8").split())


def test_fictional_story_never_presented_as_real_testimonial():
    text = _flat()
    assert "Une histoire fictive ne doit jamais être présentée comme un témoignage réel." in text
    assert ("Toute présentation sous forme de témoignage nécessite des faits réels "
            "et l'accord de la personne concernée.") in text


def test_storytelling_future_phases_offer_illustrations_and_characters():
    text = _flat()
    assert ("Pour les projets de storytelling, prévoir dans les phases ultérieures la possibilité "
            "d'utiliser des illustrations vectorielles, des personnages animés et des décors "
            "illustrés.") in text
    assert "sans l'activer avant que ces outils existent" in text
