"""OpenMontage Studio — projets : création, liste, état d'avancement, reprise (étape G0).

Socle sans interface de la future application graphique. Aucune génération ici : ce
module lit les fichiers d'un projet pour en déduire l'état, et n'écrit que dans un
projet du studio non verrouillé.

Verrouillage (lecture seule, refus de toute écriture) :
- tout ce qui est sous `projects/demos/` (les cinq vidéos françaises et le reste) ;
- le pilote « Studio d'impact » (`projects/pilote-gestion-temps`) ;
- tout projet déjà exporté (`exports/vNNN/publication_qc.json`).
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from lib.paths import PROJECTS_DIR
from lib.studio.narration.tool import PROTECTED, check_write_zone
from lib.studio.qc.tool import STUDIO_MARKER
from lib.studio.storyboard.stills import FR_CONFIG_V4

PIPELINE = "studio-fr"
DURATIONS = (15, 30, 60, 90)
LOCKED_PROJECTS = ("pilote-gestion-temps",)
PROJECTS_ROOT = PROJECTS_DIR
SLUG_RE = re.compile(r"[a-z0-9][a-z0-9-]{2,60}")
VERSION_RE = re.compile(r"v(\d{3})")

# Décisions validées (D5 : profil B par défaut ; storyboard et rendu en FR v4).
DEFAULTS = {
    "profil_narration": "B",
    "configuration_rendu": FR_CONFIG_V4,
    "format": "16:9",
    "resolution": "1920x1080",
    "langue": "fr",
    "mode": "economique",
    "composition": "gabarits",
    "moteur_rendu": "remotion",
}

STEPS = ("projet", "scenario", "storyboard", "narration", "rendu", "controle", "validation_rendu", "export")
# Étapes rattachées à une validation de l'utilisateur (type inscrit dans validations.json).
VALIDATED_STEPS = {"scenario": "scenario", "storyboard": "storyboard", "narration": "narration",
                   "validation_rendu": "rendu"}
# Projets antérieurs au module (pilote) : leur validation 3 porte sur la référence sonore,
# affichée comme narration faite. Lecture seule : aucune règle de validation n'en dépend.
LEGACY_NARRATION_KIND = "reference_sonore"
# Dossiers versionnés (vNNN) dont la dernière version date l'activité du projet.
VERSIONED_DIRS = ("storyboard", "assets/narration", "renders", "controle", "exports")


class ProjectError(ValueError):
    """Demande de projet invalide."""


class ProjectLockedError(PermissionError):
    """Projet verrouillé : lecture seule."""


# ---- utilitaires ----

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: Path, data: Any) -> None:
    """JSON UTF-8, fins de ligne LF (octets écrits tels quels, pas de conversion Windows)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def versions(root: Path) -> list[str]:
    """Sous-dossiers vNNN triés."""
    if not root.is_dir():
        return []
    return sorted(d.name for d in root.iterdir() if d.is_dir() and VERSION_RE.fullmatch(d.name))


def latest_version(root: Path) -> Optional[str]:
    v = versions(root)
    return v[-1] if v else None


def _inside(p: Path, root: Path) -> bool:
    try:
        p.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


# ---- verrouillage ----

def lock_reason(project_dir: Path) -> Optional[str]:
    p = Path(project_dir)
    for prot in PROTECTED:
        if _inside(p, prot):
            return "zone protégée (vidéos françaises validées)"
    if p.resolve().parent == PROJECTS_ROOT.resolve() and p.name in LOCKED_PROJECTS:
        return "pilote « Studio d'impact » validé et exporté"
    for v in versions(p / "exports"):
        if (p / "exports" / v / "publication_qc.json").is_file():
            return f"projet exporté ({v})"
    return None


def is_locked(project_dir: Path) -> bool:
    return lock_reason(project_dir) is not None


def require_studio_identity(project_dir: Path) -> Path:
    """Vérifie l'identité Studio avant toute écriture dans un projet.

    Le marqueur doit être un JSON valide et lier explicitement le dossier à son
    slug et au pipeline Studio. Un simple fichier portant le bon nom ne suffit pas.
    """
    p = Path(project_dir).resolve()
    if not p.is_dir():
        raise ProjectLockedError(f"Projet Studio introuvable : {p}.")
    marker = p / STUDIO_MARKER
    meta = read_json(marker)
    if not isinstance(meta, dict):
        raise ProjectLockedError("Identité Studio absente ou illisible : studio_project.json.")
    if (marker.is_symlink()
            or meta.get("studio") != "OpenMontage Studio"
            or type(meta.get("version")) is not int
            or meta.get("version") != 1
            or meta.get("projet") != p.name
            or meta.get("pipeline") != PIPELINE):
        raise ProjectLockedError(
            "Identité Studio invalide : studio, version, projet et pipeline doivent "
            "correspondre exactement au dossier."
        )
    return p


def require_writable(project_dir: Path) -> Path:
    """Vérifie l'identité, puis refuse toute écriture dans un projet verrouillé."""
    p = Path(project_dir)
    reason = lock_reason(p)
    if reason:
        raise ProjectLockedError(f"Projet en lecture seule : {reason}.")
    p = require_studio_identity(p)
    check_write_zone(p / STUDIO_MARKER, PROJECTS_ROOT)
    return p


# ---- création ----

def check_slug(slug: str) -> str:
    if not isinstance(slug, str) or not SLUG_RE.fullmatch(slug) or "--" in slug or slug.endswith("-"):
        raise ProjectError("Identifiant de projet invalide : minuscules, chiffres et tirets (3 à 61 caractères).")
    if slug in LOCKED_PROJECTS or slug == "demos":
        raise ProjectError(f"Identifiant réservé : {slug}.")
    return slug


def create_project(slug: str, title: str, idea: str, duration_s: int,
                   root: Path = PROJECTS_ROOT, **details: Any) -> Path:
    """Crée `<root>/<slug>/` avec `studio_project.json` et `validations.json` vides. Jamais d'écrasement."""
    check_slug(slug)
    if not isinstance(title, str) or not title.strip():
        raise ProjectError("Titre obligatoire.")
    if not isinstance(idea, str) or not idea.strip():
        raise ProjectError("Idée obligatoire.")
    if duration_s not in DURATIONS:
        raise ProjectError(f"Durée non disponible en phase 1 : {duration_s} s (choix : {DURATIONS}).")
    project = Path(root) / slug
    if project.exists():
        raise ProjectError(f"Le projet existe déjà : {slug}.")
    check_write_zone(project / STUDIO_MARKER, PROJECTS_ROOT)
    project.mkdir(parents=True)
    write_json(project / STUDIO_MARKER, {
        "studio": "OpenMontage Studio", "version": 1,
        "regle": "publication uniquement avec contrôle qualité conforme",
        "projet": slug, "titre": title.strip(), "idee": idea.strip(), "duree_s": duration_s,
        "pipeline": PIPELINE, "cree_le": now_iso(), "reglages": dict(DEFAULTS),
        "details": {k: v for k, v in details.items() if isinstance(v, (str, int, float, bool))},
    })
    write_json(project / "validations.json", {"projet": slug, "titre": title.strip(), "pipeline": PIPELINE,
                                              "validations": []})
    return project


def project_settings(project_dir: Path) -> dict:
    """Réglages du projet ; valeurs par défaut validées (profil B, FR v4) si absentes."""
    meta = read_json(Path(project_dir) / STUDIO_MARKER, {}) or {}
    return {**DEFAULTS, **(meta.get("reglages") or {})}


def narration_request(project_dir: Path, **overrides: Any) -> dict:
    """Entrées de `PiperFrNarration` pour ce projet (profil B par défaut). Ne lance rien."""
    p = Path(project_dir)
    req = {"mode": "placement", "script": str(p / "script.json"), "project_dir": str(p),
           "sentence_pause": 0.30, "profil": project_settings(p)["profil_narration"]}
    req.update(overrides)
    return req


# ---- liste et état ----

def is_studio_project(project_dir: Path) -> bool:
    p = Path(project_dir).resolve()
    try:
        require_studio_identity(p)
        return True
    except (ProjectLockedError, OSError, RuntimeError):
        vals = read_json(p / "validations.json", {}) or {}
        return (isinstance(vals, dict) and vals.get("pipeline") == PIPELINE
                and vals.get("projet") == p.name)


def list_projects(root: Path = PROJECTS_ROOT) -> list[dict]:
    """Projets du studio (dossiers directs de `root`), du plus récent au plus ancien."""
    root = Path(root)
    if not root.is_dir():
        return []
    out = [project_state(d) for d in root.iterdir() if d.is_dir() and d.name != "demos" and is_studio_project(d)]
    return sorted(out, key=lambda s: s["modifie_le"] or "", reverse=True)


def _validation_kinds(project_dir: Path) -> dict[str, dict]:
    from lib.studio.validations import validations_by_kind
    return validations_by_kind(project_dir)


def _current_check(project_dir: Path, kind: Optional[str]) -> tuple[Optional[bool], Optional[str]]:
    """Validité ACTUELLE d'une validation (fichiers inchangés), distincte de son existence.

    `None` si l'étape n'a pas de validation enregistrée ; sinon le verdict de `is_current`.
    Lecture seule ; une erreur de lecture vaut « pas à jour ».
    """
    if kind is None:
        return None, None
    from lib.studio.validations import is_current
    try:
        return is_current(project_dir, kind)
    except OSError as exc:
        return False, f"vérification impossible : {exc}"


def _last_modified(p: Path) -> Optional[str]:
    """Dernière activité : fichiers du projet et dernière version de chaque dossier versionné."""
    files = [p / STUDIO_MARKER, p / "validations.json", p / "script.json", p / "events.jsonl"]
    latest = [p / d / v for d in VERSIONED_DIRS if (v := latest_version(p / d))]
    mtimes = []
    for f in files + latest:
        try:
            if f.exists():
                mtimes.append(f.stat().st_mtime)
        except OSError:
            continue
    return datetime.fromtimestamp(max(mtimes), timezone.utc).isoformat() if mtimes else None


def project_state(project_dir: Path) -> dict:
    """État d'avancement déduit des fichiers (lecture seule).

    Pour chaque étape validée, `a_jour` dit si les fichiers validés sont INCHANGÉS
    aujourd'hui (`is_current`) : une validation historique n'est pas une validité actuelle.
    """
    p = Path(project_dir)
    meta = read_json(p / STUDIO_MARKER, {}) or {}
    vals = read_json(p / "validations.json", {}) or {}
    kinds = _validation_kinds(p)
    sb, nar = latest_version(p / "storyboard"), latest_version(p / "assets" / "narration")
    ren, qc, exp = latest_version(p / "renders"), latest_version(p / "controle"), latest_version(p / "exports")
    qc_report = read_json(p / "controle" / qc / "rapport_qc.json", {}) if qc else {}
    narration_kind = ("narration" if "narration" in kinds
                      else LEGACY_NARRATION_KIND if LEGACY_NARRATION_KIND in kinds else None)

    def step(done: bool, started: bool, detail: str) -> dict:
        return {"statut": "fait" if done else ("en_cours" if started else "a_faire"), "detail": detail}

    steps = {
        "projet": step(True, True, meta.get("titre") or vals.get("titre") or p.name),
        "scenario": step("scenario" in kinds, (p / "script.json").is_file(),
                         "validé" if "scenario" in kinds else ("brouillon" if (p / "script.json").is_file() else "")),
        "storyboard": step("storyboard" in kinds, bool(sb), sb or ""),
        "narration": step(narration_kind is not None, bool(nar), nar or ""),
        "rendu": step(bool(ren), bool(ren), ren or ""),
        "controle": step(bool(qc_report.get("conforme") is True), bool(qc),
                         ("conforme" if qc_report.get("conforme") is True else "non conforme") if qc else ""),
        "validation_rendu": step("rendu" in kinds, False, "validé" if "rendu" in kinds else ""),
        "export": step(bool(exp and (p / "exports" / exp / "publication_qc.json").is_file()), bool(exp), exp or ""),
    }
    for name, s in steps.items():
        kind = narration_kind if name == "narration" else VALIDATED_STEPS.get(name)
        kind = kind if kind in kinds else None
        s["a_jour"], s["verification"] = _current_check(p, kind)
    if narration_kind == LEGACY_NARRATION_KIND:
        steps["narration"]["origine"] = "référence sonore (ancien format, affichée comme narration)"
    # Une production exportée est terminée (le pilote, antérieur au module, n'a pas toutes les
    # validations au nouveau format : il reste affiché tel quel, en lecture seule).
    exported = steps["export"]["statut"] == "fait"
    next_step = None if exported else next((s for s in STEPS if steps[s]["statut"] != "fait"), None)
    return {
        "projet": p.name, "chemin": str(p), "titre": steps["projet"]["detail"],
        "verrouille": is_locked(p), "raison_verrou": lock_reason(p),
        "etapes": steps, "prochaine_etape": next_step, "termine": next_step is None,
        "validations": sorted(kinds), "reglages": project_settings(p),
        "modifie_le": _last_modified(p),
    }


def resume_point(project_dir: Path) -> dict:
    """Où reprendre une production interrompue."""
    s = project_state(project_dir)
    if s["verrouille"]:
        return {"projet": s["projet"], "action": "consultation", "raison": s["raison_verrou"]}
    return {"projet": s["projet"], "action": s["prochaine_etape"] or "termine",
            "detail": s["etapes"].get(s["prochaine_etape"], {}).get("detail", "") if s["prochaine_etape"] else ""}
