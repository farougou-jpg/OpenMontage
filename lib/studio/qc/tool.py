"""Outil de contrôle qualité FR du studio (lot 1.6) — obligatoire avant toute publication.

Lecture seule des sources (MP4, props, timing, storyboard, scénario) : leurs empreintes
SHA-256 sont relevées avant et après le contrôle. Local, gratuit, hors registre
automatique, appelé via le garde-fou budgétaire. Sorties versionnées dans
``projects/<projet>/controle/vNNN/`` (ou le dossier temporaire du système pour les tests).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from tools.base_tool import BaseTool, ToolResult, ToolRuntime, ToolStability, ToolTier

from lib.studio.narration.tool import PROJECTS_ROOT, PathPolicyError, check_write_zone, next_version_dir
from lib.studio.qc import audio, probe, sync, visual
from lib.studio.qc.conformity import check_texts
from lib.studio.qc.report import QCResult, write_reports


def _load(value):
    if value is None or isinstance(value, (dict, list)):
        return value
    return json.loads(Path(value).read_text(encoding="utf-8"))


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


class QualityControlTool(BaseTool):
    name = "studio_quality_control"
    version = "1.0.0"
    tier = ToolTier.CORE
    capability = "qc_fr"
    provider = "ffmpeg"
    runtime = ToolRuntime.LOCAL
    stability = ToolStability.EXPERIMENTAL
    dependencies = ["cmd:ffmpeg", "cmd:ffprobe"]
    input_schema = {
        "type": "object",
        "required": ["mp4", "props", "timing", "project_dir"],
        "properties": {
            "mp4": {"type": "string"},
            "props": {"description": "props du rendu (dict ou chemin)"},
            "timing": {"description": "timing_fr.json de la narration (liste ou chemin)"},
            "storyboard_dir": {"type": "string", "description": "dossier vNNN du storyboard validé"},
            "script": {"description": "scénario validé (dict ou chemin)"},
            "project_dir": {"type": "string"},
            "title": {"type": "string"},
        },
    }

    def estimate_cost(self, inputs: dict[str, Any]) -> float:
        return 0.0

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        """Fail closed : toute erreur (y compris OSError, KeyError, erreur FFmpeg) devient un
        résultat d'échec, donc un refus de publication."""
        try:
            return self._run(inputs)
        except (PathPolicyError, FileNotFoundError, ValueError) as exc:
            return ToolResult(success=False, error=str(exc), cost_usd=0.0)
        except Exception as exc:  # noqa: BLE001 — refus explicite plutôt qu'exception non formatée
            return ToolResult(success=False, error=f"Contrôle qualité interrompu ({type(exc).__name__}) : {exc}",
                              cost_usd=0.0)

    def _run(self, inputs: dict[str, Any]) -> ToolResult:
        mp4 = Path(inputs["mp4"])
        if not mp4.is_file():
            raise FileNotFoundError(f"MP4 introuvable : {mp4}")
        project_dir = Path(inputs["project_dir"])
        # Aucun rapport QC ne doit être créé avant validation de l'identité du projet.
        from lib.studio.project import require_writable
        project_dir = require_writable(project_dir)
        out = next_version_dir(check_write_zone(project_dir / "controle", PROJECTS_ROOT))

        sources = {"mp4": mp4}
        for key in ("props", "timing", "script"):
            if isinstance(inputs.get(key), (str, Path)):
                sources[key] = Path(inputs[key])
        sb_dir = Path(inputs["storyboard_dir"]) if inputs.get("storyboard_dir") else None
        if sb_dir:
            sources["storyboard"] = sb_dir / "storyboard.json"
        before = {k: _sha(p) for k, p in sources.items()}

        props, timing, script = _load(inputs["props"]), _load(inputs["timing"]), _load(inputs.get("script"))
        storyboard = _load(sb_dir / "storyboard.json") if sb_dir else None
        qc = QCResult()

        info = probe.ffprobe(mp4)
        fmt = probe.check_format(info, props, qc)
        audio.check_loudness(mp4, qc)
        audio.check_clipping(mp4, qc)
        speech, log_sil = audio.speech_intervals(mp4, fmt["duree_s"])
        qc.measures["parole"] = speech
        sync.check_sync(props, timing, speech, fmt["duree_s"], qc)
        log_vis = visual.check_black_freeze(mp4, props["cuts"], qc)
        if storyboard is None:
            qc.block("Conformité visuelle", "storyboard validé absent : comparaison impossible")
        else:
            visual.check_storyboard(mp4, storyboard, sb_dir, out, qc)
        if script is None:
            qc.block("Conformité des textes", "scénario validé absent : comparaison de la narration impossible")
        check_texts(props, storyboard, timing, script, qc)
        visual.contact_sheet(mp4, out / "planche_mp4.png")

        after = {k: _sha(p) for k, p in sources.items()}
        if after != before:
            qc.block("Intégrité des sources", "un fichier source a changé pendant le contrôle")
        header = {"projet": inputs.get("title") or project_dir.name, "version": out.name,
                  "empreintes": {str(p.name): before[k] for k, p in sources.items()},
                  # Identité exacte du MP4 contrôlé : la publication exigera le même contenu.
                  "mp4": {"chemin": str(mp4.resolve()), "sha256": before["mp4"],
                          "taille": mp4.stat().st_size}}
        mark_studio_project(project_dir)
        docs = write_reports(qc, out, header, f"{log_sil}\n{log_vis}")
        return ToolResult(
            success=True,  # l'outil a fonctionné ; le verdict est dans data["conforme"]
            data={"conforme": qc.conforme, "bloquants": qc.blocking, "avertissements": qc.warnings,
                  "version_dir": str(out), "rapport": str(docs["md"]), "rapport_json": str(docs["json"]),
                  "mesures": qc.measures,
                  "criteres": qc.criteria},
            artifacts=[str(p) for p in docs.values()] + [str(out / "planche_mp4.png")],
            cost_usd=0.0)


STUDIO_MARKER = "studio_project.json"


def mark_studio_project(project_dir: Path) -> Path:
    """Vérifie le marqueur Studio existant ; ne crée jamais une identité implicite."""
    from lib.studio.project import require_studio_identity
    project = require_studio_identity(Path(project_dir))
    return project / STUDIO_MARKER


def verify_report_for_publication(report_path: Any, video_path: Any,
                                  studio_root: Path | None = None) -> tuple[bool, str]:
    """Vérifie un rapport de contrôle pour publier `video_path` — fail closed.

    Exige : rapport lisible, conforme (booléen strict) sans bloquant, situé dans
    `<studio_root>/controle/` si la racine du projet est connue, et dont l'identité MP4
    (SHA-256 ET taille) correspond EXACTEMENT au fichier à publier, recalculée maintenant.
    """
    try:
        if not isinstance(report_path, (str, Path)) or not str(report_path):
            return False, "contrôle qualité absent (aucun rapport fourni)"
        rp = Path(report_path).resolve()
        if studio_root is not None:
            try:
                rp.relative_to((Path(studio_root) / "controle").resolve())
            except ValueError:
                return False, "rapport de contrôle hors du dossier controle/ du projet"
        report = json.loads(rp.read_text(encoding="utf-8"))
        if not isinstance(report, dict) or report.get("conforme") is not True or report.get("bloquants"):
            return False, "contrôle qualité non conforme ou incomplet"
        ident = report.get("mp4")
        if not isinstance(ident, dict) or not ident.get("sha256") or ident.get("taille") is None:
            return False, "rapport sans identité du MP4 contrôlé (contrôle incomplet)"
        video = Path(video_path)
        if not video.is_file():
            return False, f"fichier à publier introuvable : {video}"
        if video.stat().st_size != ident["taille"] or _sha(video) != ident["sha256"]:
            return False, "le fichier à publier n'est pas exactement le MP4 contrôlé (empreinte SHA-256 différente)"
        return True, "contrôle conforme et empreinte identique"
    except Exception as exc:  # noqa: BLE001 — toute erreur vaut refus
        return False, f"vérification impossible ({type(exc).__name__}: {exc})"


def verify_publication(qc_result: Any, video_path: Any,
                       studio_root: Path | None = None) -> tuple[bool, str]:
    """QC conforme, rapport rattaché au projet et empreinte exacte du MP4."""
    try:
        if not publication_allowed(qc_result):
            return False, "contrôle qualité absent, échoué ou invalide"
        return verify_report_for_publication(qc_result.data["rapport_json"], video_path, studio_root)
    except Exception as exc:  # noqa: BLE001
        return False, f"vérification impossible ({type(exc).__name__}: {exc})"


def publication_allowed(result: Any) -> bool:
    """Règle du studio : publication uniquement avec un contrôle qualité conforme — fail closed.

    Autorise seulement si TOUT est vrai : résultat `ToolResult`, `success is True`,
    `conforme is True` (booléen strict), aucun bloquant, et le rapport `rapport_qc.json`
    écrit sur disque est lisible et dit lui aussi conforme sans bloquant. Toute autre
    situation (erreur, exception, résultat absent ou fabriqué, valeur non booléenne,
    rapport manquant, illisible ou contradictoire) entraîne un refus.
    """
    try:
        if not isinstance(result, ToolResult) or result.success is not True:
            return False
        data = result.data
        if not isinstance(data, dict) or data.get("conforme") is not True or data.get("bloquants"):
            return False
        report = json.loads(Path(data["rapport_json"]).read_text(encoding="utf-8"))
        return (isinstance(report, dict) and report.get("conforme") is True
                and not report.get("bloquants"))
    except Exception:  # noqa: BLE001 — toute erreur de lecture vaut refus
        return False
