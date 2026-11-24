"""Lot 1.1 — tests du garde-fou budgétaire du studio.

Aucun test n'appelle un vrai service : les outils « payants » sont des faux
(FakePaidTool) dont execute() n'ouvre aucune connexion et renvoie un coût
fictif. Le blocage réseau de tests/conftest.py reste actif en plus.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from lib.config_model import OpenMontageConfig
from lib.studio.budget_guard import (
    STUDIO_CONFIG_PATH,
    SpendRefusedError,
    StudioBudgetGuard,
    StudioConfigError,
    load_studio_settings,
)
from tools.base_tool import BaseTool, ToolResult, ToolRuntime
from tools.graphics.atlas_image import AtlasImage
from tools.provider_pricing import PriceQuoteRequired

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
BACKUP_DIR = REPO_ROOT / "studio" / "backups"


# ---- Fake tools (no network, no money) ----

class _Recorder(BaseTool):
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []


class FakeLocalTool(_Recorder):
    name = "fake_local"
    runtime = ToolRuntime.LOCAL

    def execute(self, inputs):
        self.calls.append(inputs)
        return ToolResult(success=True, cost_usd=0.0)


class FakePaidTool(_Recorder):
    """Simulated API tool: cost comes from inputs['fake_cost']."""

    name = "fake_paid_api"
    runtime = ToolRuntime.API

    def estimate_cost(self, inputs):
        return float(inputs.get("fake_cost", 0.0))

    def execute(self, inputs):
        self.calls.append(inputs)
        if inputs.get("fake_fail"):
            raise RuntimeError("panne simulée")
        return ToolResult(success=True, cost_usd=float(inputs.get("fake_cost", 0.0)))


class FakeOtherPaidTool(FakePaidTool):
    name = "fake_other_api"


class FakeHybridTool(_Recorder):
    name = "fake_hybrid"
    runtime = ToolRuntime.HYBRID

    def execute(self, inputs):
        self.calls.append(inputs)
        return ToolResult(success=True)


class FakeQuoteTool(_Recorder):
    name = "fake_quote_api"
    runtime = ToolRuntime.API

    def estimate_cost(self, inputs):
        raise PriceQuoteRequired("tarif non publié")

    def execute(self, inputs):
        self.calls.append(inputs)
        return ToolResult(success=True)


@pytest.fixture
def guard(tmp_path):
    return StudioBudgetGuard(tmp_path / "projet_a")


# ---- 1. Profil studio ----

def test_studio_profile_enforces_zero_budget():
    settings = load_studio_settings()
    assert settings.source == STUDIO_CONFIG_PATH
    assert settings.config.budget.mode.value == "cap"
    assert settings.config.budget.total_usd == 0.0
    assert settings.config.budget.single_action_approval_usd == 0.0
    assert settings.config.budget.require_approval_for_new_paid_tool is True
    assert settings.config.output.default_resolution == "1920x1080"
    assert settings.free_external_allowlist == frozenset()


def test_core_config_still_loads_unchanged():
    core = OpenMontageConfig.load()
    assert core.budget.mode.value == "warn"
    assert core.budget.total_usd == 10.0


# ---- 2. Démarrage refusé si le profil est absent ou permissif ----

def test_missing_profile_fails_closed(tmp_path):
    with pytest.raises(StudioConfigError):
        load_studio_settings(tmp_path / "absent.yaml")
    with pytest.raises(StudioConfigError):
        StudioBudgetGuard(tmp_path / "p", settings=load_studio_settings(tmp_path / "absent.yaml"))


@pytest.mark.parametrize("patch", [
    {"mode": "warn"},
    {"mode": "observe"},
    {"total_usd": 5.0},
    {"require_approval_for_new_paid_tool": False},
])
def test_permissive_profile_is_rejected(tmp_path, patch):
    import yaml
    raw = yaml.safe_load(STUDIO_CONFIG_PATH.read_text(encoding="utf-8"))
    raw["budget"].update(patch)
    bad = tmp_path / "bad.yaml"
    bad.write_text(yaml.safe_dump(raw), encoding="utf-8")
    with pytest.raises(StudioConfigError):
        load_studio_settings(bad)


def test_invalid_yaml_is_rejected(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("budget: [pas, un, dict", encoding="utf-8")
    with pytest.raises(StudioConfigError):
        load_studio_settings(bad)


# ---- 3. Outils locaux ----

def test_local_tool_runs(guard):
    tool = FakeLocalTool()
    result = guard.run(tool, {"x": 1})
    assert result.success and tool.calls == [{"x": 1}]
    assert not guard.cost_log_path.exists()


# ---- 4. Outils externes refusés avant exécution ----

def test_unapproved_paid_tool_refused_before_execute(guard):
    tool = FakePaidTool()
    with pytest.raises(SpendRefusedError) as exc:
        guard.run(tool, {"fake_cost": 0.05})
    assert exc.value.decision.requires_approval
    assert tool.calls == []


def test_unapproved_api_tool_with_zero_estimate_still_refused(guard):
    """Un outil d'API qui annonce 0 $ n'est pas présumé gratuit."""
    tool = FakePaidTool()
    with pytest.raises(SpendRefusedError):
        guard.run(tool, {"fake_cost": 0.0})
    assert tool.calls == []


def test_real_paid_tool_refused_without_touching_execute(guard, monkeypatch):
    monkeypatch.setenv("ATLASCLOUD_API_KEY", "sk-fausse-cle-jamais-utilisee")
    tool = AtlasImage()

    def _must_not_run(inputs):
        raise AssertionError("execute() ne doit jamais être appelé")

    tool.execute = _must_not_run  # type: ignore[method-assign]
    with pytest.raises(SpendRefusedError):
        guard.run(tool, {"prompt": "test", "output_path": "nope.png"})


def test_quote_required_refused_even_if_approved(guard):
    tool = FakeQuoteTool()
    guard.approve(tool.name, 1.0, "test : autorisation fictive")
    with pytest.raises(SpendRefusedError):
        guard.run(tool, {})
    assert tool.calls == []


def test_hybrid_tool_refused_by_default(guard):
    tool = FakeHybridTool()
    with pytest.raises(SpendRefusedError):
        guard.run(tool, {})
    assert tool.calls == []


# ---- 5. Autorisation à 0,10 $ (simulée) ----

def test_approval_ceiling_accepts_005_refuses_020(guard):
    tool = FakePaidTool()
    guard.approve(tool.name, 0.10, "test : « oui pour 0,10 $ »")

    with pytest.raises(SpendRefusedError):
        guard.run(tool, {"fake_cost": 0.20})
    assert tool.calls == []

    result = guard.run(tool, {"fake_cost": 0.05})
    assert result.success and len(tool.calls) == 1
    log = json.loads(guard.cost_log_path.read_text())
    assert [e["status"] for e in log["entries"]] == ["completed"]
    assert log["entries"][0]["actual_usd"] == 0.05


def test_approval_ceiling_is_cumulative(guard):
    tool = FakePaidTool()
    guard.approve(tool.name, 0.10, "test")
    guard.run(tool, {"fake_cost": 0.05})
    guard.run(tool, {"fake_cost": 0.05})
    with pytest.raises(SpendRefusedError):
        guard.run(tool, {"fake_cost": 0.01})
    assert len(tool.calls) == 2
    assert guard.committed_usd(tool.name) == pytest.approx(0.10)


def test_approval_does_not_cover_another_tool(guard):
    guard.approve(FakePaidTool.name, 0.10, "test")
    other = FakeOtherPaidTool()
    with pytest.raises(SpendRefusedError):
        guard.run(other, {"fake_cost": 0.05})
    assert other.calls == []


def test_failed_execution_releases_reservation(guard):
    tool = FakePaidTool()
    guard.approve(tool.name, 0.10, "test")
    with pytest.raises(RuntimeError):
        guard.run(tool, {"fake_cost": 0.05, "fake_fail": True})
    assert guard.committed_usd(tool.name) == 0.0


def test_approve_requires_positive_amount_and_note(guard):
    for bad in (0, -1, float("nan"), float("inf")):
        with pytest.raises(ValueError):
            guard.approve("x", bad, "note")
    with pytest.raises(ValueError):
        guard.approve("x", 0.1, "  ")


def test_revoke(guard):
    tool = FakePaidTool()
    guard.approve(tool.name, 0.10, "test")
    guard.revoke(tool.name)
    with pytest.raises(SpendRefusedError):
        guard.run(tool, {"fake_cost": 0.05})


# ---- 6. Isolation entre projets ----

def test_approval_is_isolated_per_project(tmp_path):
    a = StudioBudgetGuard(tmp_path / "projet_a")
    b = StudioBudgetGuard(tmp_path / "projet_b")
    a.approve(FakePaidTool.name, 0.10, "test projet A")

    tool = FakePaidTool()
    assert a.run(tool, {"fake_cost": 0.05}).success
    with pytest.raises(SpendRefusedError):
        b.run(tool, {"fake_cost": 0.05})
    assert len(tool.calls) == 1


def test_copied_approvals_file_is_not_trusted(tmp_path):
    a = StudioBudgetGuard(tmp_path / "projet_a")
    a.approve(FakePaidTool.name, 0.10, "test projet A")
    (tmp_path / "projet_b").mkdir()
    shutil.copy(a.approvals_path, tmp_path / "projet_b" / a.approvals_path.name)
    b = StudioBudgetGuard(tmp_path / "projet_b")
    with pytest.raises(StudioConfigError):
        b.run(FakePaidTool(), {"fake_cost": 0.05})


# ---- 7. config.yaml intact ----

def test_core_config_matches_backup_hash():
    expected = (BACKUP_DIR / "config.yaml.2026-11-17.bak.sha256").read_text().split()[0]
    actual = hashlib.sha256((REPO_ROOT / "config.yaml").read_bytes()).hexdigest()
    backup = hashlib.sha256((BACKUP_DIR / "config.yaml.2026-11-17.bak").read_bytes()).hexdigest()
    assert actual == expected == backup
