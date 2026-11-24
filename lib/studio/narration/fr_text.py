"""Normalisation française du studio : méthode V2 + règles complémentaires prudentes.

``fr_text_v2`` est une copie octet pour octet de
``projects/demos/fr-series/common/fr_text.py`` (méthode V2 validée). Ce module
n'en change rien : il applique d'abord quelques règles *supplémentaires*, ciblées
sur des écritures que la V2 ne sait pas lire (milliers groupés, euros, heures,
ordinaux, signes, ×), puis délègue tout le reste à ``normalize_v2``.

Accord au féminin : seulement quand le nom qui suit immédiatement le nombre est
dans une liste de noms féminins connus. Si le mot suivant n'est pas reconnu
(adjectif, nom inconnu…), la formulation n'est PAS modifiée : le cas est
signalé dans ``NormalizationResult.notes`` pour relecture humaine.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from lib.studio.narration.fr_text_v2 import (
    LEXICON,
    int_to_words,
    normalize as normalize_v2,
)

__all__ = ["LEXICON", "NormalizationResult", "analyze", "int_to_words",
           "normalize_studio", "normalize_v2", "ordinal_words"]

# Noms féminins courants (singulier et pluriel). Liste volontairement fermée.
FEMININE_NOUNS = {
    "heure", "minute", "seconde", "semaine", "journée", "année", "fois", "tâche",
    "personne", "idée", "étape", "application", "appli", "notification", "réunion",
    "page", "vidéo", "solution", "raison", "question", "erreur", "astuce", "méthode",
    "équipe", "entreprise", "place", "chose", "nuit", "liste", "habitude", "priorité",
    "alerte", "pause", "règle", "minute", "matinée", "soirée", "journée", "version",
    "fonction", "fonctionnalité", "option", "offre", "étoile", "victoire", "demande",
}
FEMININE_NOUNS |= {n + ("" if n.endswith(("s", "x")) else "s") for n in set(FEMININE_NOUNS)}

# Noms masculins courants : évitent un signalement inutile.
MASCULINE_NOUNS = {
    "jour", "mois", "an", "client", "utilisateur", "rendez-vous", "projet", "outil",
    "euro", "problème", "objectif", "clic", "e-mail", "mail", "message", "écran",
    "point", "pas", "mot", "conseil", "rappel", "agenda", "calendrier", "membre",
    "minuteur", "moment", "instant", "résultat", "fichier", "plan", "seul", "sur",
}
MASCULINE_NOUNS |= {n + ("" if n.endswith(("s", "x")) else "s") for n in set(MASCULINE_NOUNS)}

_SPACES = re.compile(r"[    ]")
_WORD_AFTER = r"\s+([A-Za-zÀ-ÖØ-öø-ÿ'’-]+)"


@dataclass
class NormalizationResult:
    written: str
    spoken: str
    rules: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _ends_with_un(n: int) -> bool:
    return int_to_words(n).endswith("un")


def _feminine(words: str) -> str:
    return words[:-2] + "une" if words.endswith("un") else words


def ordinal_words(n: int) -> str:
    if n == 1:
        return "premier"
    w = int_to_words(n)
    if w.endswith("cinq"):
        return w + "uième"
    if w.endswith("neuf"):
        return w[:-1] + "vième"
    if w.endswith("quatre-vingts"):
        w = w[:-1]
    if w.endswith("e"):
        w = w[:-1]
    return w + "ième"


def _num(s: str) -> int:
    return int(re.sub(r"\D", "", s))


def analyze(text: str) -> NormalizationResult:
    res = NormalizationResult(written=text, spoken=text)
    t = text

    def rule(name: str, pattern: str, repl, flags=0) -> None:
        nonlocal t
        new = re.sub(pattern, repl, t, flags=flags)
        if new != t:
            res.rules.append(name)
            t = new

    # 1. Typographie : espaces insécables, guillemets, tirets longs.
    rule("espaces_insecables", _SPACES.pattern, " ")
    rule("guillemets", r"«\s*|\s*»|[“”]", "")
    rule("tirets", r"\s+[—–]\s+", ", ")

    # 2. Milliers groupés : « 1 000 », « 10 000 », « 1 250 000 ».
    rule("milliers", r"\b\d{1,3}(?: \d{3})+\b(?!,\d)", lambda m: m.group(0).replace(" ", ""))

    # 3. Rythmes « 24h/24 », « 7j/7 ».
    rule("rythme", r"\b(\d+)\s*h\s*/\s*(\d+)\b",
         lambda m: f"{_feminine(int_to_words(int(m.group(1))))} heures sur "
                   f"{_feminine(int_to_words(int(m.group(2))))}")
    rule("rythme", r"\b(\d+)\s*j\s*/\s*(\d+)\b",
         lambda m: f"{int_to_words(int(m.group(1)))} jours sur {int_to_words(int(m.group(2)))}")

    # 4. Heures et durées (genre connu : heure/minute/seconde féminins).
    def hours(m: re.Match) -> str:
        h = int(m.group(1))
        out = _feminine(int_to_words(h)) + (" heure" if h == 1 else " heures")
        if m.group(2):
            out += " " + _feminine(int_to_words(int(m.group(2))))
        return out
    rule("heures", r"\b(\d{1,2})\s*h(?:\s*(\d{2}))?\b(?![\w/])", hours)
    rule("minutes", r"\b(\d+)\s*min\b\.?",
         lambda m: _feminine(int_to_words(int(m.group(1)))) + (" minute" if int(m.group(1)) == 1 else " minutes"))
    rule("secondes", r"\b(\d+)\s*(?:s|sec)\b(?!['’])",
         lambda m: _feminine(int_to_words(int(m.group(1)))) + (" seconde" if int(m.group(1)) == 1 else " secondes"))

    # 5. Euros : « 29,99 € », « 5 € », « 0,50 € ».
    def euros(m: re.Match) -> str:
        e, c = int(m.group(1)), int((m.group(2) or "0").ljust(2, "0"))
        parts = []
        if e:
            parts.append(int_to_words(e) + (" euro" if e == 1 else " euros"))
        if c:
            parts.append(int_to_words(c) if e else int_to_words(c) + (" centime" if c == 1 else " centimes"))
        return " ".join(parts) or "zéro euro"
    rule("euros", r"\b(\d+)(?:,(\d{1,2}))?\s*€", euros)

    # 6. Pourcentages signés : « +18 % », « -30 % », « −30 % ».
    rule("signe", r"(?<![\w\d])\+\s?(?=\d+(?:,\d+)?\s*%)", "plus ")
    rule("signe", r"(?<![\w\d])[-−]\s?(?=\d+(?:,\d+)?\s*%)", "moins ")

    # 7. Ordinaux : « 2e », « 3ème », « 10e » (« 1er » reste géré par la V2).
    rule("ordinaux", r"\b(\d+)(?:e|ème|eme)\b", lambda m: ordinal_words(int(m.group(1))))

    # 8. Multiplication : « ×2 », « x2 ».
    rule("multiplication", r"(?<![\w])(?:×\s?|x)(\d+)\b", lambda m: "fois " + int_to_words(int(m.group(1))))

    # 9. Accord au féminin (prudent) pour les nombres qui se terminent par « un ».
    def agree(m: re.Match) -> str:
        n, word = _num(m.group(1)), m.group(2)
        if not _ends_with_un(n):
            return m.group(0)
        low = word.lower()
        if low in FEMININE_NOUNS:
            res.rules.append("accord_feminin")
            return f"{_feminine(int_to_words(n))} {word}"
        if low not in MASCULINE_NOUNS:
            res.notes.append(
                f"Accord incertain : « {m.group(1)} {word} » — laissé au masculin, à relire.")
        return m.group(0)
    t = re.sub(r"(?<![\d,])\b(\d+)\b(?!,\d)" + _WORD_AFTER, agree, t)

    # 10. Tout le reste : méthode V2 inchangée.
    t = normalize_v2(t)
    if re.search(r"\d", t):
        res.notes.append(f"Chiffre non converti dans : « {t} »")
    res.spoken = t
    return res


def normalize_studio(text: str) -> str:
    return analyze(text).spoken
