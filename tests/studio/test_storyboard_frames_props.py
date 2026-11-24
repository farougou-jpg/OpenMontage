"""Lot 1.5 — tests 1 et 2 : choix des instants, vérification du brouillon (sans rendu)."""

from __future__ import annotations

import copy

import pytest

from lib.studio.storyboard.props_check import check_props, fade_frames, transition_label
from lib.studio.storyboard.stills import MIN_AFTER_START_S, SAFETY_FRAMES, choose_frame

BASE = {
    "theme": "flat-motion-graphics",
    "cuts": [
        {"id": "a", "source": "", "type": "hero_title", "text": "Titre", "in_seconds": 0, "out_seconds": 4},
        {"id": "b", "source": "", "type": "bar_chart", "title": "Graphique", "in_seconds": 4, "out_seconds": 10,
         "chartData": [{"label": "A", "value": 1}]},
        {"id": "c", "source": "", "type": "callout", "text": "Encadré", "in_seconds": 10, "out_seconds": 13},
    ],
    "overlays": [], "captions": [],
}


# ---- Test 1 : instants ----

@pytest.mark.parametrize("cut", BASE["cuts"], ids=lambda c: c["type"])
def test_frame_never_inside_fade_out(cut):
    f = choose_frame(cut)
    end = round(cut["out_seconds"] * 30)
    assert f <= end - fade_frames(cut) - SAFETY_FRAMES
    assert f > round(cut["in_seconds"] * 30)


def test_text_scene_waits_for_entrance():
    cut = BASE["cuts"][0]
    assert choose_frame(cut) >= round(MIN_AFTER_START_S * 30)


def test_chart_shows_final_state():
    cut = BASE["cuts"][1]
    assert fade_frames(cut) == 15
    assert choose_frame(cut) == round(10 * 30) - 15 - SAFETY_FRAMES


def test_override_is_clamped_out_of_fade():
    cut = BASE["cuts"][2]
    assert choose_frame(cut, override_s=12.99) == round(13 * 30) - 8 - SAFETY_FRAMES
    assert choose_frame(cut, override_s=11.0) == 330


def test_very_short_scene_stays_inside_scene():
    cut = {"id": "x", "type": "text_card", "in_seconds": 2.0, "out_seconds": 2.3}
    f = choose_frame(cut)
    assert 60 <= f < 69


def test_transition_labels_describe_real_engine_behaviour():
    assert transition_label(BASE["cuts"][0]) == "coupe franche + animation d'entrée suivante"
    assert transition_label(BASE["cuts"][1]) == "fondu 15 images (graphique)"
    assert transition_label({**BASE["cuts"][2], "transition_out": "fade"}) == \
        "coupe franche + animation d'entrée suivante"


def test_component_transition_props_warned_as_ignored():
    p = copy.deepcopy(BASE)
    p["cuts"][0]["transition_out"] = "cut"
    rep = check_props(p)
    assert rep.ok and any("ignorés par le moteur" in w for w in rep.warnings)


def test_engine_fade_facts():
    """Les libellés reposent sur le code : fondu 15 images dans les graphiques, aucun dans
    HeroTitle / StatCard / ComparisonCard, transitions appliquées aux seules scènes vidéo."""
    from pathlib import Path
    comp = Path(__file__).resolve().parents[2] / "remotion-composer" / "src"
    for chart in ("BarChart", "PieChart", "KPIGrid", "LineChart"):
        assert "durationInFrames - 15" in (comp / "components" / "charts" / f"{chart}.tsx").read_text(encoding="utf-8")
    for name in ("HeroTitle.fr.tsx", "StatCard.tsx", "ComparisonCard.tsx"):
        assert "durationInFrames" not in (comp / "components" / name).read_text(encoding="utf-8")
    explainer = (comp / "Explainer.tsx").read_text(encoding="utf-8")
    assert explainer.count("transitionOut={cut.transition_out}") == 1


# ---- Test 2 : vérification du brouillon ----

def test_valid_props_pass():
    rep = check_props(BASE)
    assert rep.ok, rep.errors


def test_section_title_accepted_as_overlay():
    p = copy.deepcopy(BASE)
    p["overlays"] = [{"type": "section_title", "text": "Problème 1", "in_seconds": 4.3, "out_seconds": 7.5}]
    assert check_props(p).ok


def test_cut_types_match_what_explainer_renders():
    """Chaque type de scène autorisé doit avoir une branche de rendu dans Explainer.tsx."""
    import re
    from pathlib import Path
    from lib.studio.storyboard.props_check import ALLOWED_TYPES, OVERLAY_ONLY_TYPES
    src = (Path(__file__).resolve().parents[2] / "remotion-composer" / "src" / "Explainer.tsx").read_text(
        encoding="utf-8")
    rendered = set(re.findall(r'cut\.type === "([a-z_]+)"', src))
    assert set(ALLOWED_TYPES) <= rendered
    assert not set(OVERLAY_ONLY_TYPES) & rendered


def _bad(mutate):
    p = copy.deepcopy(BASE)
    mutate(p)
    return check_props(p)


@pytest.mark.parametrize("mutate,needle", [
    (lambda p: p["cuts"][0].update(type="anime_scene"), "non autorisé"),
    (lambda p: p["cuts"][0].update(type="screenshot_scene"), "non autorisé"),
    (lambda p: p["cuts"][1].update(in_seconds=5), "trou"),
    (lambda p: p["cuts"][1].update(in_seconds=3), "chevauchement"),
    (lambda p: p["cuts"][2].update(backgroundImage="photo.jpg"), "backgroundImage"),
    (lambda p: p["cuts"][2].update(backgroundVideo="clip.mp4"), "backgroundVideo"),
    (lambda p: p.update(theme="anime-ghibli"), "Style"),
    (lambda p: p.update(themeConfig={"primaryColor": "#000"}), "themeConfig"),
    (lambda p: p.update(audio={"narration": {"src": "x.wav"}}), "audio"),
    (lambda p: p["cuts"][1].update(id="a"), "double"),
    (lambda p: p["overlays"].append({"type": "provider_chip"}), "Surimpression"),
    (lambda p: p.update(cuts=[]), "Aucune scène"),
    (lambda p: p["cuts"][0].update(type="section_title"), "surimpression uniquement"),
    (lambda p: p["cuts"][0].update(type="stat_reveal"), "surimpression uniquement"),
])
def test_invalid_props_refused(mutate, needle):
    rep = _bad(mutate)
    assert not rep.ok and any(needle in e for e in rep.errors), rep.errors
