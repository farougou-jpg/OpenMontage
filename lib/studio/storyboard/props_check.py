"""Vérification du brouillon de props Remotion (méthode gabarits) avant le storyboard."""

from __future__ import annotations

from dataclasses import dataclass, field

FPS = 30
STUDIO_THEMES = ("flat-motion-graphics", "clean-professional", "minimalist-diagram", "premium-minimalist")
# Types de SCÈNE rendus par Explainer.tsx. `section_title` et `stat_reveal` n'en font pas
# partie : ce sont uniquement des surimpressions (overlays).
ALLOWED_TYPES = (
    "hero_title", "text_card", "stat_card", "kpi_grid",
    "bar_chart", "line_chart", "pie_chart", "progress_bar", "comparison", "callout", "terminal_scene",
)
OVERLAY_ONLY_TYPES = ("section_title", "stat_reveal")
# Composants dont le fondu de sortie dure 15 images (graphiques) ; 8 images pour les autres.
CHART_TYPES = ("bar_chart", "line_chart", "pie_chart", "kpi_grid")
# Composants qui se « remplissent » : l'image fixe montre leur état final.
FINAL_STATE_TYPES = CHART_TYPES + ("progress_bar", "stat_card")
FORBIDDEN_CUT_KEYS = ("backgroundImage", "backgroundVideo")
ALLOWED_OVERLAY_TYPES = ("section_title", "stat_reveal", "hero_title")


@dataclass
class PropsReport:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def check_props(props: dict) -> PropsReport:
    rep = PropsReport()
    theme = props.get("theme") or props.get("playbook")
    if theme not in STUDIO_THEMES:
        rep.errors.append(f"Style {theme!r} inconnu (autorisés : {', '.join(STUDIO_THEMES)}).")
    if props.get("themeConfig"):
        rep.errors.append("themeConfig personnalisé interdit en méthode gabarits (utiliser un style existant).")
    audio = props.get("audio") or {}
    if any(audio.values()) if isinstance(audio, dict) else audio:
        rep.errors.append("Le brouillon de storyboard ne doit contenir aucun audio.")

    cuts = props.get("cuts") or []
    if not cuts:
        rep.errors.append("Aucune scène (cuts vide).")
        return rep
    ids = [c.get("id") for c in cuts]
    if len(set(ids)) != len(ids) or not all(ids):
        rep.errors.append("Identifiants de scène manquants ou en double.")
    prev_out = 0.0
    for c in sorted(cuts, key=lambda c: c.get("in_seconds", 0)):
        cid, t = c.get("id"), c.get("type")
        if t in OVERLAY_ONLY_TYPES:
            rep.errors.append(f"{cid} : {t!r} n'est pas un type de scène (surimpression uniquement, "
                              "à placer dans overlays).")
        elif t not in ALLOWED_TYPES:
            rep.errors.append(f"{cid} : type {t!r} non autorisé en phase 1.")
        for k in FORBIDDEN_CUT_KEYS:
            if c.get(k):
                rep.errors.append(f"{cid} : {k} interdit (aucune image ni vidéo externe en phase 1).")
        a, b = float(c.get("in_seconds", -1)), float(c.get("out_seconds", -1))
        if b <= a:
            rep.errors.append(f"{cid} : fin ({b}) avant ou égale au début ({a}).")
        if abs(a - prev_out) > 1e-6:
            kind = "trou" if a > prev_out else "chevauchement"
            rep.errors.append(f"{cid} : {kind} entre {prev_out} s et {a} s.")
        prev_out = b
        if c.get("transition_in") or c.get("transition_out"):
            rep.warnings.append(f"{cid} : transition_in/transition_out ignorés par le moteur pour une "
                                "scène de composant (effet réel : coupe franche, ou fondu pour un graphique).")
        if t not in ("hero_title", "section_title") and not any(
                c.get(k) for k in ("text", "title", "chartData", "progressLabel", "leftLabel", "stat")):
            rep.warnings.append(f"{cid} : aucun texte détecté.")
    rep.warnings.extend(variety_warnings(props))
    for o in props.get("overlays") or []:
        if o.get("type") not in ALLOWED_OVERLAY_TYPES:
            rep.errors.append(f"Surimpression {o.get('type')!r} non autorisée.")
        for k in FORBIDDEN_CUT_KEYS + ("image", "src"):
            if o.get(k):
                rep.errors.append(f"Surimpression : {k} interdit en phase 1.")
    return rep


MAX_SAME_TYPE_RUN = 2  # règle de variété : pas 3 scènes de même type d'affilée


def _overlay_label(props: dict, cut: dict) -> str | None:
    """Texte de la surimpression section_title affichée pendant la scène, s'il y en a une."""
    for o in props.get("overlays") or []:
        if o.get("type") == "section_title" and cut["in_seconds"] <= o.get("in_seconds", -1) < cut["out_seconds"]:
            return (o.get("text") or "").strip() or None
    return None


def variety_warnings(props: dict) -> list[str]:
    """Règle de variété (avertissement, non bloquant).

    Une suite de plus de MAX_SAME_TYPE_RUN scènes du même type est signalée, sauf si
    chacune porte une surimpression `section_title` distincte (ex. « Problème 1/2/3 »),
    qui différencie visuellement les scènes. Les vidéos validées restent conformes :
    elles ne produisent au pire qu'un avertissement, jamais une erreur.
    """
    cuts = sorted(props.get("cuts") or [], key=lambda c: c.get("in_seconds", 0))
    out, i = [], 0
    while i < len(cuts):
        j = i
        while j + 1 < len(cuts) and cuts[j + 1].get("type") == cuts[i].get("type"):
            j += 1
        run = cuts[i:j + 1]
        if len(run) > MAX_SAME_TYPE_RUN:
            labels = [_overlay_label(props, c) for c in run]
            if not (all(labels) and len(set(labels)) == len(labels)):
                out.append(f"Variété : {len(run)} scènes {run[0].get('type')!r} d'affilée "
                           f"({', '.join(c['id'] for c in run)}) sans surimpressions distinctes — à justifier.")
        i = j + 1
    return out


def fade_frames(cut: dict, fps: int = FPS) -> int:
    if cut.get("type") in CHART_TYPES:
        return 15
    dur = cut.get("transition_duration")
    return max(1, round(dur * fps)) if isinstance(dur, (int, float)) and dur > 0 else 8


def transition_label(cut: dict, fps: int = FPS) -> str:
    """Comportement RÉEL du moteur (Explainer.tsx) : seuls les graphiques ont un fondu de
    sortie (15 images). Les autres scènes de composants se terminent par une coupe franche,
    suivie de l'animation d'entrée de la scène suivante ; transition_out n'y est pas appliqué."""
    if cut.get("type") in CHART_TYPES:
        return "fondu 15 images (graphique)"
    return "coupe franche + animation d'entrée suivante"
