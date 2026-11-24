"""Résultat et rapport du contrôle qualité (modèle : world-in-numbers/controle/rapport_qc.md)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class QCResult:
    criteria: list[dict] = field(default_factory=list)
    blocking: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    measures: dict = field(default_factory=dict)

    def ok(self, name: str, detail: str) -> None:
        self.criteria.append({"critere": name, "resultat": detail, "statut": "✅"})

    def warn(self, name: str, detail: str) -> None:
        self.warnings.append(f"{name} — {detail}")
        self.criteria.append({"critere": name, "resultat": detail, "statut": "⚠️"})

    def block(self, name: str, detail: str) -> None:
        self.blocking.append(f"{name} — {detail}")
        self.criteria.append({"critere": name, "resultat": detail, "statut": "❌"})

    @property
    def conforme(self) -> bool:
        return not self.blocking


def fr(x) -> str:
    return f"{x:.2f}".replace(".", ",") if isinstance(x, (int, float)) else str(x)


def write_reports(qc: QCResult, out_dir: Path, header: dict, raw_log: str) -> dict[str, Path]:
    js = out_dir / "rapport_qc.json"
    js.write_text(json.dumps({**header, "conforme": qc.conforme, "criteres": qc.criteria,
                              "bloquants": qc.blocking, "avertissements": qc.warnings,
                              "mesures": qc.measures}, ensure_ascii=False, indent=2, default=str),
                  encoding="utf-8")
    sync = qc.measures.get("synchronisation", [])
    vis = qc.measures.get("conformite_visuelle", [])
    lines = [
        f"# {header.get('projet', '')} — rapport de contrôle qualité ({header.get('version', '')})", "",
        f"**Verdict : {'CONFORME' if qc.conforme else 'NON CONFORME — publication refusée'}**"
        + (f" ({len(qc.warnings)} avertissement(s) à relire)" if qc.warnings else ""), "",
        "Contrôle en lecture seule : aucun fichier source n'est modifié. Mesures brutes : `mesures_brutes.txt`.", "",
        "## Fichiers contrôlés", "", "| Fichier | SHA-256 |", "|---|---|",
        *[f"| `{k}` | `{v[:16]}…` |" for k, v in header.get("empreintes", {}).items()], "",
        "## Résultats", "", "| Critère | Résultat | Statut |", "|---|---|---|",
        *[f"| {c['critere']} | {c['resultat']} | {c['statut']} |" for c in qc.criteria], "",
        "## Synchronisation (mesurée dans le MP4)", "",
        "| Scène | Voix | Limite de sortie | Marge | Écart fin vs timing | Statut |", "|---|---|---|---|---|---|",
        *[f"| {r['scene']} | {fr(r.get('voix_debut_s', '—'))} → {fr(r.get('voix_fin_s', '—'))} s | "
          f"{r['nature_limite']} {fr(r['limite_s'])} s | {fr(r.get('marge_s', '—'))} s | "
          f"{fr(r.get('ecart_fin_s', '—'))} s | {r['statut']} |" for r in sync], "",
    ]
    if vis:
        lines += ["## Conformité au storyboard validé", "",
                  "Critères indépendants : écart moyen < 2 % ET aucune tuile 20×20 px avec ≥ 3 pixels "
                  "fortement différents (> 60/255 après flou de 1 px).", "",
                  "| Scène | Image | Écart moyen | Pire tuile (px forts) | Comparaison | Statut |",
                  "|---|---|---|---|---|---|",
                  *[f"| {r['scene']} | {r['image']} | {fr(r['ecart_pct'])} % | {r['max_pixels_forts_tuile']} | "
                    f"`{r['comparaison']}` | {r['statut']} |" for r in vis], ""]
    lines += ["## Bloquants", *([f"- {b}" for b in qc.blocking] or ["- aucun"]), "",
              "## Avertissements", *([f"- {w}" for w in qc.warnings] or ["- aucun"]), ""]
    md = out_dir / "rapport_qc.md"
    md.write_text("\n".join(lines), encoding="utf-8")
    raw = out_dir / "mesures_brutes.txt"
    raw.write_text(f"Contrôle qualité — {header.get('projet', '')} {header.get('version', '')}\n\n"
                   f"== Mesures\n{json.dumps(qc.measures, ensure_ascii=False, indent=2, default=str)}\n\n"
                   f"== Journaux FFmpeg (silencedetect, blackdetect, freezedetect)\n{raw_log}\n",
                   encoding="utf-8")
    return {"json": js, "md": md, "brut": raw}
