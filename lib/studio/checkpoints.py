"""OpenMontage Studio — checkpoints du pipeline `studio-fr` liés aux validations (lot P0-C).

`write_studio_checkpoint` est le SEUL chemin d'écriture des checkpoints Studio. Il encapsule
`lib.checkpoint.write_checkpoint` (inchangé) et ajoute :

- verrous et identité du projet vérifiés avant toute écriture ;
- gel de l'étape `publish` (refus de tout checkpoint `publish` jusqu'au lot P0-D) ;
- liaison de l'artefact à ce qui a été validé ou produit :
  `script` = `script.json` (validation 1) ; `scene_plan` et `edit` = scènes / coupes du storyboard
  (validation 2) ; `assets` = narration (validation 3, accord exigé au niveau du checkpoint) ;
  `compose` = MP4 issu de `render.py` (provenance vérifiée) et contrôlé conforme ;
- intégrité des checkpoints précédents (trace présente, artefact inchangé, validation à jour) ;
- trace `metadata.studio_integrity` (empreinte SHA-256 de l'artefact, référence de validation) ;
- relecture après écriture : en cas d'écart, le checkpoint et le journal des décisions retrouvent
  leurs octets antérieurs, et l'échec est signalé (jamais en silence).

Un checkpoint écrit directement par `write_checkpoint` n'a pas de trace : `verify_studio_checkpoints`
le signale et `write_studio_checkpoint` refuse toute étape suivante tant qu'il subsiste.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any, Optional

from lib.studio.project import (PIPELINE, ProjectError, _atomic_write_bytes, latest_version, read_json,
                                require_writable, versions)
from lib.studio.validations import OBJECTS, is_current, load, validations_by_kind

INTEGRITY_KEY = "studio_integrity"
WRITER = "lib.studio.checkpoints.write_studio_checkpoint"
# Étape du pipeline → validation humaine qui la conditionne (statut `completed`).
STAGE_VALIDATION = {"script": "scenario", "scene_plan": "storyboard", "assets": "narration"}
# Étapes gelées : aucun checkpoint, quel que soit le statut, jusqu'à autorisation explicite.
FROZEN_STAGES = {"publish": "publication gelée pour studio-fr jusqu'au lot P0-D et à l'autorisation "
                            "explicite de l'utilisateur"}
LIFECYCLE = ("awaiting_human", "completed")


class CheckpointIntegrityError(ProjectError):
    """Checkpoint Studio refusé, ou incohérent après écriture (`problems` détaille)."""

    def __init__(self, message: str, problems: Optional[list[str]] = None,
                 original: Optional[BaseException] = None) -> None:
        self.problems, self.original = list(problems or []), original
        super().__init__(message + (" : " + " ; ".join(self.problems) if self.problems else ""))


# ---- empreinte d'un jeu d'artefacts ----

def _normalized(artifacts: Any) -> Any:
    """Copie sans les références que `write_checkpoint` ajoute lui-même (`decision_log_ref`)."""
    data = copy.deepcopy(artifacts)
    if isinstance(data, dict):
        plan = (data.get("proposal_packet") or {}).get("production_plan") if isinstance(
            data.get("proposal_packet"), dict) else None
        if isinstance(plan, dict):
            plan.pop("decision_log_ref", None)
        if isinstance(data.get("render_report"), dict):
            data["render_report"].pop("decision_log_ref", None)
    return data


def artifacts_sha256(artifacts: Any) -> str:
    canon = json.dumps(_normalized(artifacts), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


# ---- liaison artefact ↔ validation / production ----

def _rel(p: Path, raw: Any) -> Optional[str]:
    if not isinstance(raw, str) or not raw:
        return None
    path = Path(raw)
    path = path if path.is_absolute() else p / path
    try:
        return path.resolve().relative_to(p.resolve()).as_posix()
    except (ValueError, OSError):
        return None


def _signature(items: Any, id_key: str, start: str, end: str) -> list[tuple]:
    if not isinstance(items, list) or not items:
        raise CheckpointIntegrityError("Artefact sans scènes ni coupes comparables")
    try:
        return sorted((str(i[id_key]), round(float(i[start]), 3), round(float(i[end]), 3)) for i in items)
    except (KeyError, TypeError, ValueError) as exc:
        raise CheckpointIntegrityError(f"Scène ou coupe incomplète ({type(exc).__name__}: {exc})") from None


def _current(p: Path, kind: str) -> dict:
    ok, why = is_current(p, kind)
    if not ok:
        raise CheckpointIntegrityError(f"Validation « {OBJECTS[kind]} » absente ou périmée ({why})")
    return validations_by_kind(p)[kind]


def _storyboard_cuts(p: Path, version: Optional[str]) -> list[tuple]:
    props = read_json(p / "storyboard" / str(version) / "props_storyboard.json") if version else None
    if not isinstance(props, dict):
        raise CheckpointIntegrityError(f"props_storyboard.json illisible (storyboard {version})")
    return _signature(props.get("cuts"), "id", "in_seconds", "out_seconds")


def _declared_storyboard_version(p: Path, artifacts: Any) -> Optional[str]:
    """`scene_plan.metadata.storyboard_version` (P0-D, R5) : None si absent, refus si inconnu."""
    sp = artifacts.get("scene_plan") if isinstance(artifacts, dict) else None
    meta = sp.get("metadata") if isinstance(sp, dict) else None
    declared = meta.get("storyboard_version") if isinstance(meta, dict) else None
    if declared is not None and (not isinstance(declared, str) or declared not in versions(p / "storyboard")):
        raise CheckpointIntegrityError(f"scene_plan.metadata.storyboard_version inconnue : {declared!r}")
    return declared


def _bind(p: Path, stage: str, status: str, artifacts: dict, human_approved: bool) -> Optional[dict]:
    """Vérifie que l'artefact est exactement ce qui a été validé / produit. Renvoie la référence de validation."""
    completed = status == "completed"
    entry: Optional[dict] = None
    if completed and stage in STAGE_VALIDATION:
        if human_approved is not True:
            raise CheckpointIntegrityError(f"Étape « {stage} » : accord humain requis (human_approved=True) "
                                           "après une validation réussie")
        entry = _current(p, STAGE_VALIDATION[stage])

    if stage == "script":
        on_disk = read_json(p / "script.json")
        if artifacts.get("script") != on_disk or on_disk is None:
            raise CheckpointIntegrityError("Artefact `script` différent de script.json (contenu validé/présenté)")
    elif stage in ("scene_plan", "edit"):
        # P0-D (R5) : la version du storyboard présentée est déclarée dans le scene_plan et doit être
        # celle utilisée ici ; en `completed`, elle doit être la version validée (validation 2).
        declared = _declared_storyboard_version(p, artifacts) if stage == "scene_plan" else None
        if stage == "edit" or completed:
            version = _current(p, "storyboard").get("version")
            if declared is not None and declared != version:
                raise CheckpointIntegrityError(f"scene_plan présenté sur le storyboard {declared}, "
                                               f"version validée : {version}")
        else:
            if declared is None:
                raise CheckpointIntegrityError("scene_plan en attente d'accord : "
                                               "metadata.storyboard_version (version présentée) obligatoire")
            version = declared
        cuts = _storyboard_cuts(p, version)
        if stage == "scene_plan":
            got = _signature((artifacts.get("scene_plan") or {}).get("scenes"), "id", "start_seconds", "end_seconds")
        else:
            ed = artifacts.get("edit_decisions") or {}
            if ed.get("render_runtime") != "remotion":
                raise CheckpointIntegrityError("edit_decisions : render_runtime « remotion » obligatoire en phase 1")
            got = _signature(ed.get("cuts"), "id", "in_seconds", "out_seconds")
        if got != cuts:
            raise CheckpointIntegrityError(f"Scènes / coupes différentes du storyboard {version}")
    elif stage == "assets":
        version = entry.get("version") if entry else latest_version(p / "assets" / "narration")
        wanted = f"assets/narration/{version}/narration_fr.wav"
        paths = {_rel(p, a.get("path")) for a in (artifacts.get("asset_manifest") or {}).get("assets") or []
                 if isinstance(a, dict)}
        if not version or wanted not in paths:
            raise CheckpointIntegrityError(f"asset_manifest ne cite pas la narration {wanted}")
    elif stage == "compose":
        _bind_render(p, artifacts.get("render_report") or {})

    if entry is None:
        return None
    return {"type": STAGE_VALIDATION[stage], "numero": entry.get("numero"),
            "empreinte_presentation": entry.get("empreinte_presentation")}


def _bind_render(p: Path, report: dict) -> None:
    from lib.studio.qc.tool import verify_report_for_publication
    from lib.studio.render import RenderError, render_provenance
    outputs = report.get("outputs") if isinstance(report, dict) else None
    rels = [_rel(p, o.get("path")) for o in outputs or [] if isinstance(o, dict)]
    renders = [r for r in rels if r and len(r.split("/")) == 3 and r.startswith("renders/") and r.endswith(".mp4")]
    if len(renders) != 1:
        raise CheckpointIntegrityError("render_report doit citer exactement un MP4 renders/vNNN/ produit par render.py")
    version = renders[0].split("/")[1]
    try:
        prov = render_provenance(p, version)
    except RenderError as exc:
        raise CheckpointIntegrityError(f"Rendu {version} refusé : {exc}") from None
    mp4 = Path(prov["mp4"])
    for qc in sorted((p / "controle").glob("v[0-9][0-9][0-9]/rapport_qc.json"), reverse=True):
        if verify_report_for_publication(qc, mp4, p)[0]:
            return
    raise CheckpointIntegrityError(f"Aucun contrôle qualité conforme pour le MP4 exact de {version}")


# ---- vérification (lecture seule) ----

def _check_one(p: Path, stage: str, cp: Any, chained: bool) -> list[str]:
    if not isinstance(cp, dict):
        return [f"checkpoint {stage} illisible"]
    trace = (cp.get("metadata") or {}).get(INTEGRITY_KEY) if isinstance(cp.get("metadata"), dict) else None
    if not isinstance(trace, dict) or trace.get("ecrit_par") != WRITER:
        return [f"checkpoint {stage} écrit hors write_studio_checkpoint (trace d'intégrité absente)"]
    problems = []
    if (trace.get("etape") != stage or cp.get("stage") != stage or cp.get("pipeline_type") != PIPELINE
            or cp.get("project_id") != p.name or trace.get("statut") != cp.get("status")):
        problems.append(f"checkpoint {stage} : identité incohérente avec sa trace")
    if artifacts_sha256(cp.get("artifacts")) != trace.get("artefacts_sha256"):
        problems.append(f"checkpoint {stage} : artefact modifié après écriture (empreinte SHA-256 différente)")
    ref, kind = trace.get("validation"), STAGE_VALIDATION.get(stage)
    if kind and cp.get("status") == "completed":
        entries = [e for e in load(p)["validations"] if isinstance(e, dict)]
        match = [e for e in entries if isinstance(ref, dict) and e.get("numero") == ref.get("numero")]
        if not isinstance(ref, dict) or not match:
            problems.append(f"checkpoint {stage} : validation de référence introuvable")
        elif (match[0].get("type") != kind
              or match[0].get("empreinte_presentation") != ref.get("empreinte_presentation")):
            problems.append(f"checkpoint {stage} : validation de référence différente")
        elif stage == "scene_plan" and _declared_version_mismatch(p, cp, match[0]):
            problems.append(f"checkpoint {stage} : storyboard présenté différent de la version validée")
        elif chained:
            latest = validations_by_kind(p).get(kind) or {}
            ok, why = is_current(p, kind)
            if latest.get("numero") != ref.get("numero") or not ok:
                problems.append(f"checkpoint {stage} : validation remplacée ou périmée ({why})")
    return problems


def _declared_version_mismatch(p: Path, cp: dict, entry: dict) -> bool:
    """P0-D (R5) : la version déclarée par le scene_plan diffère de celle de la validation 2."""
    try:
        declared = _declared_storyboard_version(p, cp.get("artifacts"))
    except CheckpointIntegrityError:
        return True
    return declared is not None and declared != entry.get("version")


def verify_studio_checkpoints(project_dir: Path, before_stage: Optional[str] = None) -> list[str]:
    """Écarts d'intégrité des checkpoints Studio existants (avant `before_stage` si donné). Lecture seule."""
    from lib.checkpoint import get_pipeline_stages
    p = Path(project_dir)
    stages = get_pipeline_stages(PIPELINE)
    limit = stages.index(before_stage) if before_stage in stages else len(stages)
    problems: list[str] = []
    for stage in stages[:limit]:
        f = p / f"checkpoint_{stage}.json"
        if f.exists() or f.is_symlink():
            problems += _check_one(p, stage, read_json(f), chained=True)
    return problems


# ---- écriture ----

def _snapshot(path: Path) -> Optional[bytes]:
    return path.read_bytes() if path.is_file() else None


def _restore(path: Path, previous: Optional[bytes]) -> Optional[str]:
    try:
        if previous is None:
            if path.is_file():
                path.unlink()
        elif not path.is_file() or path.read_bytes() != previous:
            _atomic_write_bytes(path, previous)
        if (previous is None and path.exists()) or (previous is not None and path.read_bytes() != previous):
            return f"{path.name} non restauré"
    except Exception as exc:  # noqa: BLE001 — signalé, jamais ignoré
        return f"{path.name} non restauré ({type(exc).__name__}: {exc})"
    return None


def write_studio_checkpoint(project_dir: Path, stage: str, status: str, artifacts: dict, *,
                            human_approved: bool = False, review: Optional[dict] = None,
                            cost_snapshot: Optional[dict] = None, error: Optional[str] = None,
                            metadata: Optional[dict] = None, style_playbook: Optional[str] = None) -> Path:
    """Seul chemin d'écriture d'un checkpoint `studio-fr` (voir le module)."""
    import lib.checkpoint as ckpt
    p = require_writable(Path(project_dir))
    if stage in FROZEN_STAGES:
        raise CheckpointIntegrityError(f"Checkpoint « {stage} » refusé : {FROZEN_STAGES[stage]}")
    if stage not in ckpt.get_pipeline_stages(PIPELINE):
        raise CheckpointIntegrityError(f"Étape inconnue du pipeline {PIPELINE} : {stage!r}")
    if not isinstance(artifacts, dict):
        raise CheckpointIntegrityError("Artefacts du checkpoint : dictionnaire attendu")
    metadata = dict(metadata or {})
    if INTEGRITY_KEY in metadata:
        raise CheckpointIntegrityError(f"metadata.{INTEGRITY_KEY} est réservé à {WRITER}")
    artifacts = copy.deepcopy(artifacts)
    reference = None
    if status in LIFECYCLE:
        problems = verify_studio_checkpoints(p, before_stage=stage)
        if problems:
            raise CheckpointIntegrityError(f"Checkpoint « {stage} » refusé : checkpoints précédents non fiables",
                                           problems)
        reference = _bind(p, stage, status, artifacts, human_approved)
    metadata[INTEGRITY_KEY] = {"version": 1, "ecrit_par": WRITER, "etape": stage, "statut": status,
                               "artefacts_sha256": artifacts_sha256(artifacts), "validation": reference}

    target, decisions = p / f"checkpoint_{stage}.json", p / "decision_log.json"
    before = {target: _snapshot(target), decisions: _snapshot(decisions)}
    try:
        path = ckpt.write_checkpoint(p.parent, p.name, stage, status, artifacts, pipeline_type=PIPELINE,
                                     style_playbook=style_playbook, human_approved=human_approved,
                                     human_approval_required=stage in STAGE_VALIDATION, review=review,
                                     cost_snapshot=cost_snapshot, error=error, metadata=metadata)
        problems = _check_one(p, stage, read_json(target), chained=False)
        if problems:
            raise CheckpointIntegrityError(f"Checkpoint « {stage} » incohérent après écriture : annulé", problems)
    except BaseException as exc:
        failed = [m for m in (_restore(f, b) for f, b in before.items()) if m]
        if failed:
            if not isinstance(exc, Exception):
                exc.add_note("Restauration incomplète : " + " ; ".join(failed))
                raise
            raise CheckpointIntegrityError(f"Checkpoint « {stage} » en échec ET restauration incomplète "
                                           "(ne pas utiliser ce checkpoint)", failed, original=exc) from exc
        raise
    return Path(path)
