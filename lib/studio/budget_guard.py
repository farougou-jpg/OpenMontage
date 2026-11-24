"""OpenMontage Studio — budget guard (lot 1.1).

Deny-by-default spending gate for every tool call made by the studio.

Policy (from ``config.studio.yaml``):

* ``local`` and ``local_gpu`` tools run freely (no money involved).
* ``api`` / ``hybrid`` / unknown-runtime tools are **refused**, unless:
    - the tool is on ``studio.free_external_allowlist`` AND its estimated
      cost is exactly 0, or
    - the user explicitly granted a per-project, per-tool approval with a
      cumulative USD ceiling (``approve``), and the call fits under it.
* A cost the tool cannot quote (``PriceQuoteRequired``) is always refused.
* The guard refuses to start if the studio profile is missing, invalid, not
  in ``cap`` mode, or has a non-zero default budget — it never falls back to
  the permissive core defaults (``warn`` / 10 USD).

The core ``config.yaml`` is never read or written here. Spend is logged through
the existing ``CostTracker`` into ``<project>/cost_log.json``; approvals live in
``<project>/studio_approvals.json`` and never apply to another project.

Limitation: only calls routed through ``StudioBudgetGuard.run`` are gated. A
direct ``tool.execute()`` bypasses it; the studio pipeline must use the guard.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import yaml

from lib.config_model import BudgetMode, OpenMontageConfig
from tools.base_tool import BaseTool, ToolResult, ToolRuntime, ToolTier
from tools.cost_tracker import CostTracker, EntryStatus
from tools.provider_pricing import PriceQuoteRequired

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
STUDIO_CONFIG_PATH = REPO_ROOT / "config.studio.yaml"
APPROVALS_FILENAME = "studio_approvals.json"
COST_LOG_FILENAME = "cost_log.json"

_FREE_RUNTIMES = {ToolRuntime.LOCAL, ToolRuntime.LOCAL_GPU}


class StudioConfigError(RuntimeError):
    """The studio profile is missing or does not enforce the 0 € policy."""


class PublicationRefusedError(RuntimeError):
    """Publication refusée : contrôle qualité absent, échoué, invalide ou MP4 différent (rien exécuté)."""


class SpendRefusedError(RuntimeError):
    """A tool call was refused by the studio budget guard (nothing executed)."""

    def __init__(self, decision: "GuardDecision") -> None:
        super().__init__(decision.reason)
        self.decision = decision


@dataclass(frozen=True)
class GuardDecision:
    allowed: bool
    tool: str
    runtime: str
    estimated_usd: Optional[float]
    reason: str
    requires_approval: bool = False


@dataclass(frozen=True)
class StudioSettings:
    config: OpenMontageConfig
    free_external_allowlist: frozenset[str]
    source: Path


def load_studio_settings(path: Optional[Path] = None) -> StudioSettings:
    """Load and validate the studio profile. Fails closed on any problem."""
    path = Path(path) if path is not None else STUDIO_CONFIG_PATH
    if not path.is_file():
        raise StudioConfigError(
            f"Profil studio introuvable : {path}. Le garde-fou refuse de démarrer "
            "(aucun repli sur config.yaml)."
        )
    try:
        with open(path, encoding="utf-8") as f:
            raw = yaml.safe_load(f)
        if not isinstance(raw, dict):
            raise ValueError("le fichier ne contient pas de dictionnaire YAML")
        config = OpenMontageConfig.model_validate(raw)
    except Exception as exc:  # yaml or pydantic error
        raise StudioConfigError(f"Profil studio invalide ({path}) : {exc}") from exc

    budget = config.budget
    if budget.mode != BudgetMode.CAP:
        raise StudioConfigError(
            f"Le profil studio doit être en mode 'cap' (trouvé : {budget.mode.value})."
        )
    if budget.total_usd != 0.0:
        raise StudioConfigError(
            "Le profil studio impose un budget par défaut de 0 $ "
            f"(trouvé : {budget.total_usd}). Toute dépense passe par une autorisation."
        )
    if not budget.require_approval_for_new_paid_tool:
        raise StudioConfigError(
            "Le profil studio doit exiger une approbation pour tout outil payant."
        )

    studio = raw.get("studio") or {}
    if not isinstance(studio, dict):
        raise StudioConfigError("La section 'studio' du profil doit être un dictionnaire.")
    allowlist = studio.get("free_external_allowlist") or []
    if not isinstance(allowlist, list) or not all(isinstance(x, str) for x in allowlist):
        raise StudioConfigError("'studio.free_external_allowlist' doit être une liste de noms.")

    return StudioSettings(
        config=config,
        free_external_allowlist=frozenset(allowlist),
        source=path,
    )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class StudioBudgetGuard:
    """Per-project spending gate. One instance per project directory."""

    def __init__(self, project_dir: Path, settings: Optional[StudioSettings] = None) -> None:
        self.settings = settings if settings is not None else load_studio_settings()
        self.project_dir = Path(project_dir).resolve()
        self.approvals_path = self.project_dir / APPROVALS_FILENAME
        self.cost_log_path = self.project_dir / COST_LOG_FILENAME

    # ---- Approvals (granted only after an explicit user "yes") ----

    def _load_approvals(self) -> dict[str, Any]:
        if not self.approvals_path.is_file():
            return {"version": "1.0", "project_dir": str(self.project_dir), "approvals": {}}
        with open(self.approvals_path, encoding="utf-8") as f:
            data = json.load(f)
        if data.get("project_dir") != str(self.project_dir):
            # A file copied from another project must never carry its approvals over.
            raise StudioConfigError(
                f"{self.approvals_path} appartient à un autre projet "
                f"({data.get('project_dir')!r}) : autorisations ignorées par sécurité."
            )
        return data

    def _ensure_studio_write_allowed(self) -> None:
        from lib.studio.project import STUDIO_MARKER, PROJECTS_ROOT, require_writable
        try:
            self.project_dir.relative_to(Path(PROJECTS_ROOT).resolve())
            is_canonical_project = True
        except ValueError:
            is_canonical_project = False
        if is_canonical_project or (self.project_dir / STUDIO_MARKER).exists():
            require_writable(self.project_dir)

    def _save_approvals(self, data: dict[str, Any]) -> None:
        self._ensure_studio_write_allowed()
        self.project_dir.mkdir(parents=True, exist_ok=True)
        with open(self.approvals_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def approve(self, tool_name: str, max_usd: float, note: str) -> None:
        """Record the user's explicit approval: cumulative ceiling for one tool here."""
        if not isinstance(max_usd, (int, float)) or not math.isfinite(max_usd) or max_usd <= 0:
            raise ValueError("Le plafond autorisé doit être un montant positif.")
        if not note or not note.strip():
            raise ValueError("Une autorisation doit citer l'accord explicite de l'utilisateur.")
        data = self._load_approvals()
        data["approvals"][tool_name] = {
            "max_usd": round(float(max_usd), 4),
            "note": note.strip(),
            "granted_at": _now(),
        }
        self._save_approvals(data)

    def revoke(self, tool_name: str) -> None:
        data = self._load_approvals()
        data["approvals"].pop(tool_name, None)
        self._save_approvals(data)

    def approval_for(self, tool_name: str) -> Optional[dict[str, Any]]:
        return self._load_approvals()["approvals"].get(tool_name)

    def committed_usd(self, tool_name: str) -> float:
        """Spent + reserved so far on this tool in this project."""
        if not self.cost_log_path.is_file():
            return 0.0
        tracker = CostTracker(cost_log_path=self.cost_log_path, mode=BudgetMode.OBSERVE)
        total = 0.0
        for e in tracker.entries:
            if e.get("tool") != tool_name:
                continue
            if e["status"] == EntryStatus.RESERVED.value:
                total += e.get("reserved_usd", 0.0)
            elif e["status"] in (EntryStatus.COMPLETED.value, EntryStatus.FAILED.value):
                total += e.get("actual_usd", 0.0)
        return round(total, 4)

    # ---- Decision ----

    def check(self, tool: BaseTool, inputs: dict[str, Any]) -> GuardDecision:
        name = getattr(tool, "name", "") or type(tool).__name__
        runtime = getattr(tool, "runtime", None)
        runtime_label = getattr(runtime, "value", str(runtime))

        try:
            estimated: Optional[float] = float(tool.estimate_cost(inputs))
        except PriceQuoteRequired as exc:
            return GuardDecision(False, name, runtime_label, None,
                                 f"Coût inconnu pour {name!r} (devis requis : {exc}) : refusé.",
                                 requires_approval=True)
        except Exception as exc:
            return GuardDecision(False, name, runtime_label, None,
                                 f"Estimation du coût impossible pour {name!r} ({exc}) : refusé.",
                                 requires_approval=True)
        if not math.isfinite(estimated) or estimated < 0:
            return GuardDecision(False, name, runtime_label, None,
                                 f"Estimation de coût invalide pour {name!r} : refusé.",
                                 requires_approval=True)

        if runtime in _FREE_RUNTIMES:
            return GuardDecision(True, name, runtime_label, 0.0,
                                 f"Outil local {name!r} : autorisé (0 $).")

        if name in self.settings.free_external_allowlist and estimated == 0.0:
            return GuardDecision(True, name, runtime_label, 0.0,
                                 f"Service externe gratuit autorisé {name!r} : autorisé (0 $).")

        approval = self.approval_for(name)
        if approval is None:
            return GuardDecision(False, name, runtime_label, estimated,
                                 f"Outil externe {name!r} ({runtime_label}) sans autorisation "
                                 f"explicite (estimation : {estimated:.4f} $) : refusé.",
                                 requires_approval=True)

        committed = self.committed_usd(name)
        ceiling = approval["max_usd"]
        if committed + estimated > ceiling + 1e-9:
            return GuardDecision(False, name, runtime_label, estimated,
                                 f"{name!r} : {estimated:.4f} $ demandés, {committed:.4f} $ déjà "
                                 f"engagés, plafond autorisé {ceiling:.4f} $ : refusé.",
                                 requires_approval=True)

        return GuardDecision(True, name, runtime_label, estimated,
                             f"{name!r} : {estimated:.4f} $ dans le plafond autorisé "
                             f"({committed:.4f} / {ceiling:.4f} $) : autorisé.")

    # ---- Guarded execution ----

    def run(self, tool: BaseTool, inputs: dict[str, Any], qc_result: Any = None) -> ToolResult:
        """Check, then execute only if allowed. Raises SpendRefusedError otherwise.

        Publication (lot 1.6) : un outil de type PUBLISH (ex. export_bundle) n'est exécuté
        que si `qc_result` est un contrôle qualité conforme dont l'empreinte SHA-256 du MP4
        correspond exactement à `inputs["video_path"]`. Sinon PublicationRefusedError :
        rien n'est exécuté. Le chemin du rapport est transmis à l'outil (`studio_qc_report`)
        pour que export_bundle refasse la même vérification de son côté.
        """
        is_publish = getattr(tool, "tier", None) == ToolTier.PUBLISH
        if not is_publish:
            # Pour un vrai projet Studio, le garde-fou ne contourne jamais le verrou.
            # Les usages génériques isolés hors du dépôt restent compatibles.
            self._ensure_studio_write_allowed()

        if is_publish:
            try:
                from lib.studio.qc.tool import verify_publication
                ok, reason = verify_publication(qc_result, (inputs or {}).get("video_path"))
            except Exception as exc:  # noqa: BLE001 — fail closed
                ok, reason = False, f"vérification impossible ({type(exc).__name__}: {exc})"
            if not ok:
                raise PublicationRefusedError(f"Publication refusée par le garde-fou : {reason}")
            inputs = {**inputs, "studio_qc_report": qc_result.data["rapport_json"]}
        decision = self.check(tool, inputs)
        if not decision.allowed:
            raise SpendRefusedError(decision)

        estimated = decision.estimated_usd or 0.0
        if estimated == 0.0:
            return tool.execute(inputs)

        # Paid and approved: account through the existing CostTracker.
        approval = self.approval_for(decision.tool)
        tracker = CostTracker(
            budget_total_usd=approval["max_usd"],
            reserve_pct=0.0,
            single_action_approval_usd=approval["max_usd"],
            require_approval_for_new_paid_tool=True,
            mode=BudgetMode.CAP,
            cost_log_path=self.cost_log_path,
        )
        # _load() restores the file's total; the approval ceiling for this tool wins.
        tracker.budget_total_usd = approval["max_usd"] + self._other_tools_spent(tracker, decision.tool)
        tracker.approve_tool(decision.tool)
        entry_id = tracker.estimate(decision.tool, "studio_run", estimated)
        tracker.reserve(entry_id)
        try:
            result = tool.execute(inputs)
        except Exception:
            tracker.refund(entry_id)
            raise
        actual = result.cost_usd if isinstance(result.cost_usd, (int, float)) else estimated
        tracker.reconcile(entry_id, float(actual), success=bool(result.success))
        return result

    @staticmethod
    def _other_tools_spent(tracker: CostTracker, tool_name: str) -> float:
        total = 0.0
        for e in tracker.entries:
            if e.get("tool") == tool_name:
                continue
            total += e.get("reserved_usd", 0.0) + e.get("actual_usd", 0.0)
        return total


def executer_outil(tool: BaseTool, inputs: dict[str, Any], project_dir: Path) -> ToolResult:
    """Raccourci : exécute un outil à travers le garde-fou du projet."""
    return StudioBudgetGuard(project_dir).run(tool, inputs)
