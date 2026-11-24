"""Conformité des textes : props du rendu vs storyboard validé, narration vs scénario validé."""

from __future__ import annotations

from lib.studio.storyboard.tool import _screen_text


def check_texts(props: dict, storyboard: dict | None, timing: list[dict], script: dict | None, qc) -> dict:
    diffs = []
    if storyboard is not None:
        validated = {s["id"]: s["screen_text"] for s in storyboard["scenes"]}
        for cut in props["cuts"]:
            want = validated.get(cut["id"])
            got = _screen_text(cut)
            if want is None:
                diffs.append(f"{cut['id']} : scène absente du storyboard validé")
            elif got != want:
                diffs.append(f"{cut['id']} : texte à l'écran « {got} » ≠ storyboard « {want} »")
        for sid in set(validated) - {c["id"] for c in props["cuts"]}:
            diffs.append(f"{sid} : scène du storyboard absente du rendu")
    if script is not None:
        sections = {s["id"]: s["text"].strip() for s in script["sections"]}
        for row in timing:
            want = sections.get(row["cut"])
            if want is None:
                diffs.append(f"{row['cut']} : narration absente du scénario validé")
            elif row["texte_ecrit"].strip() != want:
                diffs.append(f"{row['cut']} : narration « {row['texte_ecrit']} » ≠ scénario « {want} »")
    checked = (storyboard is not None) + (script is not None)
    qc.measures["conformite_textes"] = {"ecarts": diffs, "references": checked}
    if diffs:
        qc.block("Conformité des textes", " | ".join(diffs))
    elif checked:
        qc.ok("Conformité des textes", "textes identiques aux versions validées")
    return {"ecarts": diffs}
