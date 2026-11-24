"""Lot 1.5 — règle de variété, vidéos validées, brouillon du pilote, correction A3.

Aucun rendu : uniquement des vérifications de données (les props validées sont lues
sans modification).
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path

import pytest

from lib.studio.storyboard.props_check import (
    ALLOWED_TYPES, MAX_SAME_TYPE_RUN, OVERLAY_ONLY_TYPES, check_props, variety_warnings,
)

REPO = Path(__file__).resolve().parents[2]
FR = REPO / "projects" / "demos" / "fr-series"
VALIDATED = [
    FR / "animated-reel-20s" / "animated-reel-20s-fr.json",
    FR / "code-to-screen" / "code-to-screen-fr.json",
    FR / "focusflow-pitch" / "focusflow-pitch-fr.json",
    FR / "stop-procrastinating-with-this-1-hack" / "stop-procrastinating-with-this-1-hack-fr.json",
    FR / "world-in-numbers" / "world-in-numbers-fr-v2.json",
]

# Brouillon provisoire du pilote (décision du 2026-11-18) — textes provisoires, rien n'est rendu.
PILOT_DRAFT = {
    "theme": "flat-motion-graphics",
    "cuts": [
        {"id": "accroche", "source": "", "type": "stat_card", "stat": "3",
         "subtitle": "problèmes qui vous volent du temps", "in_seconds": 0, "out_seconds": 4},
        {"id": "probleme-1", "source": "", "type": "hero_title", "text": "Les réunions s'enchaînent",
         "in_seconds": 4, "out_seconds": 8},
        {"id": "probleme-2", "source": "", "type": "hero_title", "text": "Les notifications n'arrêtent pas",
         "in_seconds": 8, "out_seconds": 12},
        {"id": "probleme-3", "source": "", "type": "hero_title", "text": "La liste de tâches ne finit jamais",
         "in_seconds": 12, "out_seconds": 16},
        {"id": "solution", "source": "", "type": "comparison", "leftLabel": "Avant", "leftValue": "Journée subie",
         "rightLabel": "Après", "rightValue": "Journée maîtrisée", "in_seconds": 16, "out_seconds": 22},
        {"id": "appel", "source": "", "type": "hero_title", "text": "[Nom de l'application]",
         "heroSubtitle": "[Appel à l'action]", "in_seconds": 22, "out_seconds": 30},
    ],
    "overlays": [
        {"type": "section_title", "text": "Problème 1", "in_seconds": 4.3, "out_seconds": 7.8},
        {"type": "section_title", "text": "Problème 2", "in_seconds": 8.3, "out_seconds": 11.8},
        {"type": "section_title", "text": "Problème 3", "in_seconds": 12.3, "out_seconds": 15.8},
        {"type": "section_title", "text": "La solution", "in_seconds": 16.3, "out_seconds": 21.8},
    ],
    "captions": [],
}


def _draft(path: Path) -> dict:
    p = json.loads(path.read_text(encoding="utf-8"))
    p.pop("audio", None)  # un brouillon de storyboard n'a pas d'audio
    return p


# ---- Règle de variété (conservée) ----

def _hero(i: int, a: float, b: float) -> dict:
    return {"id": f"h{i}", "source": "", "type": "hero_title", "text": f"T{i}", "in_seconds": a, "out_seconds": b}


def test_rule_kept_three_identical_scenes_are_flagged():
    p = {"theme": "flat-motion-graphics", "cuts": [_hero(1, 0, 3), _hero(2, 3, 6), _hero(3, 6, 9)], "overlays": []}
    assert MAX_SAME_TYPE_RUN == 2
    assert variety_warnings(p) and "3 scènes 'hero_title'" in variety_warnings(p)[0]
    assert check_props(p).ok  # avertissement, jamais une erreur


def test_two_identical_scenes_are_fine():
    p = {"theme": "flat-motion-graphics", "cuts": [_hero(1, 0, 3), _hero(2, 3, 6)], "overlays": []}
    assert variety_warnings(p) == []


def test_distinct_overlays_justify_a_run():
    p = {"theme": "flat-motion-graphics", "cuts": [_hero(1, 0, 3), _hero(2, 3, 6), _hero(3, 6, 9)],
         "overlays": [{"type": "section_title", "text": f"Étape {i}", "in_seconds": a + 0.3, "out_seconds": a + 2.8}
                      for i, a in ((1, 0), (2, 3), (3, 6))]}
    assert variety_warnings(p) == []


def test_identical_overlays_do_not_justify_a_run():
    p = {"theme": "flat-motion-graphics", "cuts": [_hero(1, 0, 3), _hero(2, 3, 6), _hero(3, 6, 9)],
         "overlays": [{"type": "section_title", "text": "Idem", "in_seconds": a + 0.3, "out_seconds": a + 2.8}
                      for a in (0, 3, 6)]}
    assert variety_warnings(p)


# ---- Vidéos validées : jamais d'erreur ----

@pytest.mark.parametrize("path", VALIDATED, ids=lambda p: p.parent.name)
def test_validated_videos_pass_the_check(path):
    rep = check_props(_draft(path))
    assert rep.ok, rep.errors


def test_stop_procrastinating_only_gets_a_variety_warning():
    rep = check_props(_draft(VALIDATED[3]))
    assert rep.ok and any(w.startswith("Variété") for w in rep.warnings)


# ---- Brouillon du pilote ----

def test_pilot_draft_is_valid_without_warning():
    rep = check_props(PILOT_DRAFT)
    assert rep.ok, rep.errors
    assert rep.warnings == [], rep.warnings


def test_pilot_uses_only_validated_types():
    used_in_validated = set()
    for path in VALIDATED:
        used_in_validated |= {c["type"] for c in _draft(path)["cuts"]}
    pilot = {c["type"] for c in PILOT_DRAFT["cuts"]}
    assert pilot <= used_in_validated
    assert not pilot & {"text_card", "callout"}
    assert PILOT_DRAFT["cuts"][0]["type"] == "stat_card" and PILOT_DRAFT["cuts"][0]["stat"] == "3"


# ---- Correction A3 dans les fichiers du lot 1.3 ----

def test_router_scene_list_has_no_overlay_only_type():
    text = (REPO / "skills" / "meta" / "studio-creative-router.md").read_text(encoding="utf-8")
    block = text.split("Types de scènes disponibles en phase 1", 1)[1].split("Surimpressions uniquement", 1)[0]
    listed = set(re.findall(r"`([a-z_]+)`", block))
    assert listed and listed <= set(ALLOWED_TYPES)
    assert not listed & set(OVERLAY_ONLY_TYPES)
    assert "Surimpressions uniquement (jamais comme scène) : `section_title`, `stat_reveal`." in text


def test_evaluation_has_no_section_title_scene():
    text = (REPO / "studio" / "docs" / "evaluation-aiguilleur.md").read_text(encoding="utf-8")
    assert not re.search(r"(→|\|)\s*`section_title` «", text)
    assert text.count("Corrigé le 2026-11-18") == 3


# ---- Correction A4 : marge de narration ≠ transition ----

@pytest.mark.parametrize("name", ["scene-director.md", "executive-producer.md"])
def test_skills_distinguish_safety_margin_from_transitions(name):
    text = " ".join((REPO / "skills" / "pipelines" / "studio-fr" / name).read_text(encoding="utf-8").split())
    assert "8 pour une transition" not in text
    assert "Marge de sécurité de narration" in text
    assert "Transitions visuelles réelles" in text
    assert "coupe franche" in text and "fondu de 15 images" in text
    assert not re.search(r"fondu[^.]{0,40}8 images", text)
