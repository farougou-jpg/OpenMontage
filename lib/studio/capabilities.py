"""OpenMontage Studio — vérifications déterministes (lot 1.3).

Ce module ne prend AUCUNE décision créative (règle du projet : les choix créatifs
appartiennent aux skills). Il dit seulement ce qui est possible, maintenant :
formats, durées, langue, modes disponibles selon la phase, méthodes de
composition proposées, devis via le garde-fou budgétaire.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

PHASE = 1

VIDEO_TYPES = (
    "publicite", "explicative", "reseaux_sociaux", "entreprise",
    "formation", "storytelling", "promotionnelle",
)
VALID_DURATIONS = (15, 30, 60, 90)
DEFAULT_DURATION_BY_TYPE = {
    "publicite": 30, "explicative": 60, "reseaux_sociaux": 30, "entreprise": 60,
    "formation": 90, "storytelling": 60, "promotionnelle": 30,
}
SUPPORTED_FORMATS = {"16:9": (1920, 1080)}
PENDING_FORMATS = {"9:16": "lot 1.4", "1:1": "lot 1.4"}
DEFAULT_FORMAT = "16:9"
LANGUAGE = "fr"

DEFAULT_MODE = "economique"
DEFAULT_COMPOSITION = "gabarits"
DEFAULT_RUNTIME = "remotion"
WEB_RESEARCH_DEFAULT = False  # activée uniquement sur demande explicite de l'utilisateur


@dataclass
class StudioRequest:
    idea: str = ""
    video_type: Optional[str] = None
    duration_s: Optional[int] = None
    format: Optional[str] = None
    language: str = LANGUAGE


@dataclass
class RequestCheck:
    ok: bool
    request: StudioRequest
    errors: list[str] = field(default_factory=list)
    ask_for: list[str] = field(default_factory=list)
    alternatives: list[str] = field(default_factory=list)
    defaults_applied: list[str] = field(default_factory=list)


def _norm_type(t: Optional[str]) -> Optional[str]:
    if t is None:
        return None
    s = t.strip().lower()
    for a, b in (("é", "e"), ("è", "e"), ("ê", "e"), (" ", "_"), ("-", "_"), ("'", "_"), ("’", "_")):
        s = s.replace(a, b)
    aliases = {
        "video_explicative": "explicative", "reseaux": "reseaux_sociaux",
        "presentation_d_entreprise": "entreprise", "presentation_entreprise": "entreprise",
        "video_promotionnelle": "promotionnelle", "pub": "publicite",
    }
    return aliases.get(s, s)


def check_request(req: StudioRequest) -> RequestCheck:
    """Valide le formulaire et complète les valeurs absentes par des défauts annoncés."""
    out = RequestCheck(ok=True, request=StudioRequest(**vars(req)))
    r = out.request

    if not (r.idea or "").strip():
        out.ask_for.append("idee")

    if r.video_type is not None:
        r.video_type = _norm_type(r.video_type)
        if r.video_type not in VIDEO_TYPES:
            out.errors.append(f"Type de vidéo inconnu : {req.video_type!r}.")
            out.alternatives.append("Types possibles : " + ", ".join(VIDEO_TYPES))

    if r.duration_s is None:
        r.duration_s = DEFAULT_DURATION_BY_TYPE.get(r.video_type or "", 30)
        out.defaults_applied.append(f"durée {r.duration_s} s")
    elif r.duration_s not in VALID_DURATIONS:
        nearest = min(VALID_DURATIONS, key=lambda d: abs(d - r.duration_s))  # type: ignore[operator]
        out.errors.append(f"Durée {r.duration_s} s non prise en charge ({', '.join(map(str, VALID_DURATIONS))} s).")
        out.alternatives.append(f"Durée la plus proche : {nearest} s")

    if r.format is None:
        r.format = DEFAULT_FORMAT
        out.defaults_applied.append("format 16:9 (1920×1080)")
    elif r.format in PENDING_FORMATS:
        out.errors.append(f"Format {r.format} pas encore disponible ({PENDING_FORMATS[r.format]}).")
        out.alternatives.append("Format 16:9 (1920×1080) disponible dès maintenant")
    elif r.format not in SUPPORTED_FORMATS:
        out.errors.append(f"Format {r.format!r} inconnu.")
        out.alternatives.append("Format 16:9 (1920×1080)")

    if (r.language or "").lower() not in (LANGUAGE, "français", "francais"):
        out.errors.append(f"Langue {r.language!r} non prise en charge : le studio produit en français.")
    r.language = LANGUAGE

    out.ok = not out.errors and not out.ask_for
    return out


@dataclass(frozen=True)
class ModeStatus:
    id: str
    label: str
    available: bool
    default: bool
    cost: str
    reason: str
    requirements: tuple[str, ...] = ()


def modes_status(phase: int = PHASE) -> list[ModeStatus]:
    """Les deux modes, toujours présentés. L'hybride n'est jamais activable en phase 1."""
    hybrid_ok = phase >= 3
    return [
        ModeStatus("economique", "Mode économique", True, True, "0 €",
                   "Motion design, narration Piper locale (illustrations vectorielles en phase 2)."),
        ModeStatus("hybride", "Mode hybride", hybrid_ok, False,
                   "devis préalable + autorisation explicite" if hybrid_ok else "non engageable",
                   "Motion design + séquences vidéo générées par IA."
                   + ("" if hybrid_ok else " Indisponible en phase 1 : moteurs vidéo IA prévus en phase 3, "
                                           "aucune clé configurée, carte graphique de 2 Go."),
                   () if hybrid_ok else ("phase 3 du studio", "clé d'un service vidéo (ex. fal.ai)",
                                         "devis préalable", "autorisation explicite de l'utilisateur")),
    ]


def is_mode_allowed(mode: str, phase: int = PHASE) -> bool:
    return any(m.id == mode and m.available for m in modes_status(phase))


def composition_methods() -> list[dict[str, Any]]:
    """Les deux méthodes, toujours présentées ; aucune n'est imposée."""
    return [
        {"id": "gabarits", "recommande": True, "sur_demande": False,
         "description": "Scènes Remotion existantes, francisées (configuration FR v3) et validées sur les "
                        "cinq vidéos françaises. Rapide et fiable."},
        {"id": "atelier", "recommande": False, "sur_demande": True,
         "description": "Composition créée sur mesure pour ce projet (skills/meta/bespoke-composition.md). "
                        "Plus distinctive, plus longue à produire."},
    ]


def render_runtimes() -> list[dict[str, Any]]:
    """Les deux moteurs, toujours présentés (règle « Present both » d'AGENT_GUIDE.md)."""
    return [
        {"id": "remotion", "recommande": True,
         "raison": "Composants FR validés (titres, KPI, graphiques), configuration remotion.fr-locale-v4."},
        {"id": "hyperframes", "recommande": False,
         "raison": "HTML/GSAP, typographie cinétique ; pas encore de variantes françaises validées."},
    ]


def quote(tools: Iterable[Any], guard) -> dict[str, Any]:
    """Devis sans exécution : ``guard.check()`` pour chaque outil prévu."""
    lines, total, refused = [], 0.0, []
    for tool in tools:
        d = guard.check(tool, {})
        lines.append({"outil": d.tool, "type": d.runtime, "autorise": d.allowed,
                      "estimation_usd": d.estimated_usd, "motif": d.reason})
        if d.allowed:
            total += d.estimated_usd or 0.0
        else:
            refused.append(d.tool)
    return {"lignes": lines, "total_usd": round(total, 4), "refuses": refused}
