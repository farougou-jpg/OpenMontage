"""Lot 1.2 — tests 1 à 3 : normalisation française (V2 conservée + règles studio)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from lib.studio.narration import fr_text_v2
from lib.studio.narration.fr_text import analyze, normalize_studio, ordinal_words

REPO = Path(__file__).resolve().parents[2]
FR_SERIES = REPO / "projects" / "demos" / "fr-series"
REFERENCE_TIMINGS = [
    FR_SERIES / "animated-reel-20s" / "timing_fr.json",
    FR_SERIES / "code-to-screen" / "timing_fr.json",
    FR_SERIES / "focusflow-pitch" / "timing_fr.json",
    FR_SERIES / "stop-procrastinating-with-this-1-hack" / "timing_fr.json",
    FR_SERIES / "world-in-numbers" / "timing_fr_v2.json",
]


def _golden() -> list[tuple[str, str, str]]:
    rows = []
    for f in REFERENCE_TIMINGS:
        for r in json.loads(f.read_text(encoding="utf-8")):
            rows.append((f"{f.parent.name}/{r['cut']}", r["texte_ecrit"], r["texte_lu"]))
    return rows


def test_v2_copy_is_byte_identical_to_validated_source():
    src = FR_SERIES / "common" / "fr_text.py"
    copy = REPO / "lib" / "studio" / "narration" / "fr_text_v2.py"
    assert hashlib.sha256(src.read_bytes()).digest() == hashlib.sha256(copy.read_bytes()).digest()


# ---- Test 1 : correspondance exacte avec les 5 vidéos validées ----

def test_golden_has_all_validated_sentences():
    assert len(_golden()) == 22


@pytest.mark.parametrize("ref,written,spoken", _golden(), ids=[g[0] for g in _golden()])
def test_studio_normalization_matches_validated_v2(ref, written, spoken):
    assert normalize_studio(written) == spoken
    assert not analyze(written).notes


# ---- Test 2 : autotests d'origine de fr_text.py ----

V2_SELF_TESTS = {
    "8,1 milliards": "huit milliards cent millions",
    "34 %": "trente-quatre pour cent",
    "34,5 %": "trente-quatre virgule cinq pour cent",
    "29,6": "vingt-neuf virgule six",
    "71": "soixante et onze",
    "80": "quatre-vingts",
    "91": "quatre-vingt-onze",
    "200": "deux cents",
    "1er janvier 2026": "premier janvier deux mille vingt-six",
    "17 novembre 2026": "dix-sept novembre deux mille vingt-six",
    "Shanghai": "Changhaï",
}


@pytest.mark.parametrize("src,expected", V2_SELF_TESTS.items())
def test_v2_self_tests(src, expected):
    assert fr_text_v2.normalize(src) == expected
    assert normalize_studio(src) == expected


def test_v2_numbers_unchanged_up_to_100000():
    for n in range(0, 100_001, 7):
        assert normalize_studio(str(n)) == fr_text_v2.normalize(str(n))


# ---- Test 3 : nouvelles règles ----

NEW_RULES = {
    "1 000 utilisateurs": "mille utilisateurs",
    "10 000 tâches": "dix mille tâches",
    "1 250 000 euros": "un million deux cent cinquante mille euros",
    "+18 %": "plus dix-huit pour cent",
    "-30 % de stress": "moins trente pour cent de stress",
    "le 2e jour": "le deuxième jour",
    "9e": "neuvième", "5e": "cinquième", "80e": "quatre-vingtième", "21e": "vingt et unième",
    "29,99 €": "vingt-neuf euros quatre-vingt-dix-neuf",
    "5 €": "cinq euros", "1 €": "un euro", "0,50 €": "cinquante centimes",
    "8 h 30": "huit heures trente", "à 1 h": "à une heure", "21 h": "vingt et une heures",
    "30 min": "trente minutes", "45 s": "quarante-cinq secondes",
    "×2 plus vite": "fois deux plus vite", "x3": "fois trois",
    "24h/24 et 7j/7": "vingt-quatre heures sur vingt-quatre et sept jours sur sept",
    "1 heure": "une heure", "21 tâches": "vingt et une tâches", "81 minutes": "quatre-vingt-une minutes",
    "1 rappel": "un rappel", "31 jours": "trente et un jours",
    "« Gagnez du temps »": "Gagnez du temps",
    "Trois problèmes — une solution.": "Trois problèmes, une solution.",
    "34 %": "trente-quatre pour cent",
    "La règle des deux minutes : répondez": "La règle des deux minutes : répondez",
}


@pytest.mark.parametrize("src,expected", NEW_RULES.items())
def test_new_rules(src, expected):
    assert normalize_studio(src) == expected


def test_uncertain_agreement_is_flagged_never_changed():
    res = analyze("1 seule tâche")
    assert res.spoken == "un seule tâche"  # laissé tel quel (masculin V2)
    assert any("Accord incertain" in n for n in res.notes)
    res = analyze("21 grandes idées")
    assert res.spoken.startswith("vingt et un grandes")
    assert res.notes


def test_ordinal_words():
    assert ordinal_words(1) == "premier"
    assert ordinal_words(4) == "quatrième"
    assert ordinal_words(11) == "onzième"
    assert ordinal_words(100) == "centième"
