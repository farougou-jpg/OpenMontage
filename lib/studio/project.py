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

import copy
import json
import os
import re
import uuid
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

# Enregistrement Backlot (lot P0-A).
BACKLOT_MARKER = "project.json"          # = lib.checkpoint.PROJECT_MARKER_FILENAME
SCRIPT_FILE = "script.json"
# L'arborescence Backlot n'est PAS recopiée ici : elle reste définie par
# lib.checkpoint.init_project ; le retour arrière constate ce que l'appel a réellement créé.
# Validations après lesquelles le scénario ne peut plus être réécrit dans le même projet.
SCRIPT_FROZEN_BY = ("storyboard", "narration", "rendu")


class ProjectError(ValueError):
    """Demande de projet invalide."""


class ProjectLockedError(PermissionError):
    """Projet verrouillé : lecture seule."""


class RegistrationRollbackError(ProjectError):
    """Enregistrement Backlot en échec ET retour arrière incomplet : `project.json` n'est pas fiable.

    L'exception initiale reste identifiable : attribut `original` et cause chaînée (`__cause__`).
    `problems` décrit ce qui n'a pas pu être restauré.
    """

    def __init__(self, original: BaseException, problems: list[str]) -> None:
        self.original, self.problems = original, list(problems)
        super().__init__(
            f"Enregistrement Backlot en échec ({type(original).__name__}: {original}) ET retour arrière "
            f"incomplet : {' ; '.join(self.problems)}. project.json n'est pas fiable : relancer "
            "register_with_backlot (vérification complète) ou le retirer avant tout usage.")


# ---- utilitaires ----

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: Path, data: Any) -> None:
    """JSON UTF-8, fins de ligne LF (octets écrits tels quels, pas de conversion Windows)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def _json_bytes(data: Any) -> bytes:
    return (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    """Écrit `path` d'un seul coup : fichier temporaire voisin, puis remplacement.

    En cas d'échec, le fichier précédent reste intact et le temporaire est retiré.
    """
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex[:12]}.tmp")
    try:
        tmp.write_bytes(data)
        os.replace(tmp, path)
    except BaseException:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise


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


# ---- enregistrement Backlot (P0-A) ----

def _studio_identity_for_backlot(p: Path) -> dict[str, str]:
    """Les quatre champs que Backlot compare, tirés de l'identité Studio (jamais inventés)."""
    meta = read_json(p / STUDIO_MARKER, {}) or {}
    vals = read_json(p / "validations.json")
    created, title = meta.get("cree_le"), meta.get("titre")
    if not isinstance(created, str) or not created.strip():
        raise ProjectError("Date de création Studio absente (cree_le) : enregistrement Backlot refusé.")
    if not isinstance(title, str) or not title.strip():
        raise ProjectError("Titre Studio absent : enregistrement Backlot refusé.")
    if (not isinstance(vals, dict) or vals.get("titre") != title or vals.get("projet") != p.name
            or vals.get("pipeline") != PIPELINE):
        raise ProjectError("validations.json ne correspond pas à l'identité Studio (projet, titre, pipeline) : "
                           "enregistrement Backlot refusé.")
    return {"project_id": p.name, "title": title, "pipeline_type": PIPELINE, "created_at": created}


def _dir_set(p: Path) -> set[str]:
    """Dossiers réels sous `p` (liens symboliques non suivis), en chemins relatifs."""
    return {d.relative_to(p).as_posix() for d in p.rglob("*") if d.is_dir() and not d.is_symlink()}


def _rollback_registration(p: Path, marker: Path, previous: Optional[bytes],
                           dirs_before: set[str]) -> tuple[list[str], list[str]]:
    """Annule un enregistrement inachevé sans jamais toucher à un fichier préexistant.

    Renvoie (`problemes`, `dossiers_restants`) : `problemes` liste ce qui empêche de considérer
    `project.json` comme restauré (rien n'est ignoré en silence) ; `dossiers_restants` liste les
    dossiers créés par l'appel qui n'ont pas pu être retirés (sans effet sur l'identité).
    """
    problems: list[str] = []
    try:
        if previous is None:
            try:
                if marker.is_file() and not marker.is_symlink():
                    marker.unlink()
            except OSError as exc:
                problems.append(f"project.json créé par cet appel n'a pas pu être retiré "
                                f"({type(exc).__name__}: {exc})")
            else:
                if marker.exists() or marker.is_symlink():
                    problems.append("project.json créé par cet appel n'a pas pu être retiré")
        else:
            if not marker.is_file() or marker.read_bytes() != previous:
                _atomic_write_bytes(marker, previous)
            if not marker.is_file() or marker.read_bytes() != previous:
                problems.append("project.json préexistant n'a pas pu être restauré à l'identique")
    except Exception as exc:  # noqa: BLE001 — signalé, jamais ignoré
        problems.append(f"restauration de project.json impossible ({type(exc).__name__}: {exc})")
    # Seuls les dossiers créés pendant CET appel (constatés, pas supposés), s'ils sont restés vides.
    leftovers: list[str] = []
    try:
        created = _dir_set(p) - dirs_before
    except Exception as exc:  # noqa: BLE001
        return problems, [f"inventaire des dossiers impossible ({type(exc).__name__}: {exc})"]
    for d in sorted(created, key=lambda s: s.count("/"), reverse=True):
        try:
            (p / d).rmdir()
        except OSError:
            leftovers.append(d)
    return problems, leftovers


def register_with_backlot(project_dir: Path, style_playbook: Optional[str] = None) -> Path:
    """Enregistre un projet Studio auprès de Backlot (`project.json`), identités alignées.

    Responsabilité unique : enregistrement et cohérence des identités. N'écrit aucun
    checkpoint, n'ouvre pas le board, ne valide rien. Ordre imposé : `create_project`
    puis `register_with_backlot` (puis `python -m backlot open`).

    - verrous et identité Studio vérifiés AVANT toute écriture ;
    - `project.json` préexistant : accepté s'il est cohérent (idempotence), refusé s'il est
      illisible ou contradictoire — jamais écrasé ;
    - `created_at` = `cree_le` exactement (pré-rempli, conservé par `init_project`) ;
    - tout échec (y compris d'`init_project`) annule ce que CET appel a écrit : le marqueur
      retrouve son état antérieur, les dossiers créés et restés vides sont retirés ;
    - si ce retour arrière est lui-même incomplet pour `project.json`, `RegistrationRollbackError`
      est levée (exception initiale dans `original` et `__cause__`) : le projet n'est jamais
      présenté comme initialisé. Une interruption (`KeyboardInterrupt`…) est relancée telle
      quelle, avec une note. Des dossiers vides non retirés sont signalés par une note.
    """
    p = require_writable(Path(project_dir))
    identity = _studio_identity_for_backlot(p)
    marker = p / BACKLOT_MARKER
    if marker.is_symlink():
        raise ProjectError("project.json est un lien symbolique : enregistrement Backlot refusé.")
    check_write_zone(marker, PROJECTS_ROOT)
    previous: Optional[bytes] = None
    if marker.exists():
        if not marker.is_file():
            raise ProjectError("project.json n'est pas un fichier : enregistrement Backlot refusé.")
        previous = marker.read_bytes()
        try:
            current = json.loads(previous.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            raise ProjectError("project.json illisible : jamais réinitialisé, enregistrement Backlot refusé.") from None
        if not isinstance(current, dict):
            raise ProjectError("project.json mal formé : jamais réinitialisé, enregistrement Backlot refusé.")
        diff = [k for k, v in identity.items() if current.get(k) != v]
        if diff:
            raise ProjectError(f"project.json contradictoire ({', '.join(diff)}) : jamais écrasé, "
                               "enregistrement Backlot refusé.")
    dirs_before = _dir_set(p)
    try:
        if previous is None:
            _atomic_write_bytes(marker, _json_bytes({"version": "1.0", **identity}))
        import lib.checkpoint as checkpoint
        checkpoint.init_project(p.name, title=identity["title"], pipeline_type=PIPELINE,
                                pipeline_dir=p.parent, style_playbook=style_playbook)
        written = read_json(marker)
        if not isinstance(written, dict) or any(written.get(k) != v for k, v in identity.items()):
            raise ProjectError("Enregistrement Backlot incohérent après initialisation : annulé.")
    except BaseException as exc:
        problems, leftovers = _rollback_registration(p, marker, previous, dirs_before)
        if leftovers:
            exc.add_note(f"Retour arrière : dossiers non retirés (non vides ou inaccessibles) : "
                         f"{', '.join(leftovers)}")
        if problems:
            if not isinstance(exc, Exception):       # interruption : jamais convertie
                exc.add_note("Retour arrière incomplet : " + " ; ".join(problems)
                             + ". project.json n'est pas fiable.")
                raise
            raise RegistrationRollbackError(exc, problems) from exc
        raise
    return p


# ---- scénario (P0-A, décision D3) ----

def write_script(project_dir: Path, script: Any) -> dict:
    """Valide techniquement et enregistre `script.json` (seule voie d'écriture du scénario).

    Responsabilité unique : validation technique (schéma, durée du projet) et persistance
    atomique. Ne crée aucun checkpoint et n'enregistre aucune validation : la validation 1
    reste une décision de l'utilisateur, enregistrée ensuite par `validate_script`.

    - refus si le storyboard, la narration ou le rendu est déjà validé (même règle que
      `validations._append` : créer un nouveau projet pour repartir de cette étape) ;
    - contenu identique : aucune réécriture ; contenu différent après la validation 1 :
      écriture, et `validation_scenario_perimee` est vrai (`is_current` la refusera) ;
    - `artefact` est exactement le contenu enregistré, à reprendre tel quel dans le checkpoint.
    """
    from lib.studio.narration.script_input import ScriptError, load_script
    from lib.studio.validations import ValidationError, load, sha256, validations_by_kind

    p = require_writable(Path(project_dir))
    try:
        data = copy.deepcopy(load_script(script))
    except ScriptError as exc:
        raise ProjectError(str(exc)) from exc
    except (OSError, ValueError) as exc:
        raise ProjectError(f"Scénario illisible : {exc}") from exc
    meta = read_json(p / STUDIO_MARKER, {}) or {}
    total = data.get("total_duration_seconds")
    if isinstance(total, bool) or not isinstance(total, (int, float)) or total != meta.get("duree_s"):
        raise ProjectError(f"Durée du scénario ({total} s) différente de la durée du projet "
                           f"({meta.get('duree_s')} s).")
    try:
        load(p)  # validations.json mal formé : refus plutôt qu'une lecture permissive
    except ValidationError as exc:
        raise ProjectError(str(exc)) from exc
    kinds = validations_by_kind(p)
    frozen = [k for k in SCRIPT_FROZEN_BY if k in kinds]
    if frozen:
        raise ProjectError(f"Scénario non modifiable : l'étape « {frozen[0]} » est déjà validée ; "
                           "créer un nouveau projet pour repartir de cette étape.")
    target = p / SCRIPT_FILE
    if target.is_symlink():
        raise ProjectError("script.json est un lien symbolique : écriture refusée.")
    check_write_zone(target, PROJECTS_ROOT)
    existing = read_json(target) if target.is_file() else None
    changed = existing != data
    if changed:
        _atomic_write_bytes(target, _json_bytes(data))
    return {"chemin": str(target), "sha256": sha256(target), "sections": len(data["sections"]),
            "modifie": changed, "validation_scenario_perimee": changed and "scenario" in kinds,
            "artefact": copy.deepcopy(data)}


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
