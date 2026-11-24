"""Normalisation de texte français pour la synthèse vocale (Piper / espeak-ng).

- nombres entiers, décimales, pourcentages, années et dates -> toutes lettres ;
- « 8,1 milliards » -> « huit milliards cent millions » (forme orale naturelle) ;
- lexique de prononciation (mots étrangers / techniques).
"""

from __future__ import annotations

import re

UNITS = ["zéro", "un", "deux", "trois", "quatre", "cinq", "six", "sept", "huit", "neuf",
         "dix", "onze", "douze", "treize", "quatorze", "quinze", "seize"]
TENS = {2: "vingt", 3: "trente", 4: "quarante", 5: "cinquante", 6: "soixante"}
MONTHS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
          "septembre", "octobre", "novembre", "décembre"]

# Prononciations corrigées (vérifiées via voice.phonemize). Les [[ ]] sont des phonèmes bruts
# espeak-ng : à placer en fin de proposition, la ponctuation qui suit est sinon absorbée.
LEXICON = {
    r"\bShanghai\b": "Changhaï",           # ʃɑ̃ɡˈe (faux) -> ʃɑ̃ɡˈaj
    r"\bSão Paulo\b": "[[ saw pawlˈo ]]",  # saˈo polˈo -> saw pawlˈo
    r"\bRemotion\b": "Rimôcheune",
    r"\bAPI\b": "A P I",
    r"\bOpenMontage\b": "Opène Montage",   # ˈəʊpən (phonèmes anglais) -> opˈɛn mɔ̃tˈaʒ
    r"\bFocusFlow\b": "Fôcus Flô",         # fokˈys flˈəʊ (diphtongue anglaise) -> fokˈys flˈoː
    r"\bIA\b": "I A",                      # jˈa (« ya ») -> ˈiʲ ˈa
    r"\be-mail\b": "imèle",                # ˈəmˈeɪl (anglais) -> imˈɛl
}
# NB : « dix-huit » perd son t final devant consonne (dˈizyˈi paʁ…) -> le placer en fin de groupe.
# NB : éviter « prompt » à l'oral (lu pʁˈɔ̃) -> préférer « consigne ».


def _below_100(n: int) -> str:
    if n <= 16:
        return UNITS[n]
    if n < 20:
        return "dix-" + UNITS[n - 10]
    t, u = divmod(n, 10)
    if t in (7, 9):  # soixante-dix…, quatre-vingt-dix…
        base = "soixante" if t == 7 else "quatre-vingt"
        rest = n - (60 if t == 7 else 80)
        sep = " et " if (t == 7 and rest == 11) else "-"
        return base + sep + _below_100(rest)
    if t == 8:
        return "quatre-vingts" if u == 0 else "quatre-vingt-" + UNITS[u]
    if u == 0:
        return TENS[t]
    if u == 1:
        return TENS[t] + " et un"
    return TENS[t] + "-" + UNITS[u]


def _below_1000(n: int) -> str:
    h, r = divmod(n, 100)
    if h == 0:
        return _below_100(r)
    head = "cent" if h == 1 else UNITS[h] + " cent"
    if r == 0:
        return head + ("s" if h > 1 else "")
    return head + " " + _below_100(r)


def int_to_words(n: int) -> str:
    if n < 0:
        return "moins " + int_to_words(-n)
    if n < 1000:
        return _below_1000(n)
    parts = []
    for value, sing, plur in ((10**9, "milliard", "milliards"), (10**6, "million", "millions")):
        q, n = divmod(n, value)
        if q:
            parts.append(f"{int_to_words(q)} {sing if q == 1 else plur}")
    q, n = divmod(n, 1000)
    if q:
        parts.append("mille" if q == 1 else _below_1000(q) + " mille")
    if n:
        parts.append(_below_1000(n))
    return " ".join(parts)


def decimal_to_words(int_part: str, dec_part: str) -> str:
    dec = dec_part.lstrip("0")
    zeros = "zéro " * (len(dec_part) - len(dec)) if dec else ""
    return f"{int_to_words(int(int_part))} virgule {zeros}{int_to_words(int(dec or '0'))}".strip()


def _scaled(m: re.Match) -> str:
    """« 8,1 milliards » -> « huit milliards cent millions »."""
    whole, frac, unit = int(m.group(1)), m.group(2), m.group(3)
    sub_unit = {"milliards": ("million", "millions", 10**3), "millions": ("mille", "mille", 10**3)}[unit]
    sub = int(round(float("0." + frac) * sub_unit[2]))
    out = f"{int_to_words(whole)} {unit if whole > 1 else unit[:-1]}"
    if sub:
        out += f" {int_to_words(sub)} {sub_unit[0] if sub == 1 else sub_unit[1]}"
    return out


def normalize(text: str) -> str:
    for pattern, repl in LEXICON.items():
        text = re.sub(pattern, repl, text)
    # Dates : « 1er janvier 2026 », « 17 novembre 2026 »
    text = re.sub(r"\b1er\b", "premier", text)
    text = re.sub(
        rf"\b(\d{{1,2}}) ({'|'.join(MONTHS)}) (\d{{4}})\b",
        lambda m: f"{int_to_words(int(m.group(1)))} {m.group(2)} {int_to_words(int(m.group(3)))}",
        text,
    )
    text = re.sub(r"\b(\d+),(\d+)\s*(milliards|millions)\b", _scaled, text)
    text = re.sub(r"\b(\d+),(\d+)\s*%", lambda m: decimal_to_words(m.group(1), m.group(2)) + " pour cent", text)
    text = re.sub(r"\b(\d+)\s*%", lambda m: int_to_words(int(m.group(1))) + " pour cent", text)
    text = re.sub(r"\b(\d+),(\d+)\b", lambda m: decimal_to_words(m.group(1), m.group(2)), text)
    text = re.sub(r"\b\d+\b", lambda m: int_to_words(int(m.group(0))), text)
    return re.sub(r"\s+", " ", text).strip()


if __name__ == "__main__":
    tests = {
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
    bad = 0
    for src, exp in tests.items():
        got = normalize(src)
        ok = got == exp
        bad += not ok
        print(f"{'OK ' if ok else 'ERR'} {src!r:22} -> {got!r}")
    raise SystemExit(bad)
