"""Synchronisation parole / scènes, mesurée dans le MP4.

Fin utile d'une scène (30 i/s) :
- graphique (`bar_chart`, `line_chart`, `pie_chart`, `kpi_grid`) : fin − 15 images
  (durée réelle de son fondu de sortie) ;
- autre scène : fin − 8 images de marge de sécurité de narration (aucun effet visuel).

Marge = fin utile − fin de la parole de la scène (seuils validés le 2026-11-18) :
< 0,25 s bloquant ; 0,25 à 0,5 s avertissement ; > 0,5 s conforme.
Décalage : fin de parole mesurée vs `fin` de timing_fr.json : ± 0,10 s (bloquant) ;
début mesuré − `debut` attendu entre 0 et +0,25 s (rembourrage 0,08 s + fondu d'entrée).
"""

from __future__ import annotations

from lib.studio.storyboard.props_check import CHART_TYPES

FPS = 30
MARGIN_BLOCK_S, MARGIN_WARN_S = 0.25, 0.5
END_TOL_S = 0.10
START_LAG_MIN_S, START_LAG_MAX_S = 0.0, 0.25


def useful_end(cut: dict, fps: int = FPS) -> tuple[float, str]:
    if cut.get("type") in CHART_TYPES:
        return cut["out_seconds"] - 15 / fps, "fondu du graphique (15 images)"
    return cut["out_seconds"] - 8 / fps, "marge de sécurité (8 images)"


def per_scene_speech(cuts: list[dict], speech: list[tuple[float, float]]) -> tuple[dict, list]:
    """Rattache chaque intervalle de parole à la scène qui contient son milieu."""
    scenes, orphans = {}, []
    for s, e in speech:
        mid = (s + e) / 2
        cut = next((c for c in cuts if c["in_seconds"] <= mid < c["out_seconds"]), None)
        if cut is None:
            orphans.append((s, e))
            continue
        d = scenes.setdefault(cut["id"], {"start": s, "end": e, "chunks": []})
        d["start"], d["end"] = min(d["start"], s), max(d["end"], e)
        d["chunks"].append((s, e))
    return scenes, orphans


def check_sync(props: dict, timing: list[dict], speech: list[tuple[float, float]], duration: float, qc) -> list[dict]:
    cuts = sorted(props["cuts"], key=lambda c: c["in_seconds"])
    scenes, orphans = per_scene_speech(cuts, speech)
    expected = {r["cut"]: r for r in timing}
    rows = []
    for cut in cuts:
        cid = cut["id"]
        sp, exp = scenes.get(cid), expected.get(cid)
        limit, nature = useful_end(cut)
        row = {"scene": cid, "type": cut.get("type"), "limite_s": round(limit, 3), "nature_limite": nature}
        if exp and not sp:
            qc.block("Synchronisation", f"{cid} : parole attendue mais non détectée dans le MP4")
            row["statut"] = "❌"
            rows.append(row)
            continue
        if not sp:
            row["statut"] = "—"
            rows.append(row)
            continue
        margin = limit - sp["end"]
        row.update({"voix_debut_s": sp["start"], "voix_fin_s": sp["end"], "marge_s": round(margin, 3)})
        status = "✅"
        if sp["start"] < cut["in_seconds"] - 1e-6:
            qc.block("Synchronisation", f"{cid} : la parole commence avant la scène ({sp['start']:.2f} s)")
            status = "❌"
        if margin < MARGIN_BLOCK_S:
            qc.block("Marge de parole", f"{cid} : {margin:.2f} s (< {MARGIN_BLOCK_S} s)")
            status = "❌"
        elif margin < MARGIN_WARN_S:
            qc.warn("Marge de parole", f"{cid} : {margin:.2f} s (entre {MARGIN_BLOCK_S} et {MARGIN_WARN_S} s)")
            status = "⚠️" if status == "✅" else status
        if exp:
            d_end = sp["end"] - exp["fin"]
            lag = sp["start"] - exp["debut"]
            row.update({"attendu_debut_s": exp["debut"], "attendu_fin_s": exp["fin"],
                        "ecart_fin_s": round(d_end, 3), "retard_debut_s": round(lag, 3)})
            if abs(d_end) > END_TOL_S:
                qc.block("Décalage audio", f"{cid} : fin de parole décalée de {d_end:+.2f} s (± {END_TOL_S} s)")
                status = "❌"
            if not START_LAG_MIN_S <= lag <= START_LAG_MAX_S:
                qc.warn("Décalage audio", f"{cid} : début de parole à {lag:+.2f} s de l'attendu "
                                         f"(plage normale 0 à +{START_LAG_MAX_S} s)")
                status = "⚠️" if status == "✅" else status
        else:
            qc.warn("Synchronisation", f"{cid} : parole détectée sans entrée dans timing_fr.json")
            status = "⚠️" if status == "✅" else status
        row["statut"] = status
        rows.append(row)
    for s, e in orphans:
        qc.warn("Synchronisation", f"parole hors scène de {s:.2f} à {e:.2f} s")
    last_end = max((sp["end"] for sp in scenes.values()), default=0.0)
    if last_end > duration - 0.25:
        qc.block("Dernière seconde", f"parole jusqu'à {last_end:.2f} s pour une vidéo de {duration:.2f} s")
    else:
        qc.ok("Dernière seconde", f"voix finie à {last_end:.2f} s ; fin de vidéo {duration:.2f} s")
    if not any(r.get("statut") == "❌" for r in rows):
        qc.ok("Synchronisation", f"{sum(1 for r in rows if 'marge_s' in r)} scène(s) parlée(s) contrôlée(s)")
    qc.measures["synchronisation"] = rows
    return rows
