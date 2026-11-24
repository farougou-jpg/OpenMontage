"""Lot 1.3 — vérifications déterministes du studio (lib/studio/capabilities.py)."""

from __future__ import annotations

import pytest

from lib.studio import capabilities as cap
from lib.studio.budget_guard import StudioBudgetGuard
from lib.studio.capabilities import StudioRequest, check_request
from lib.studio.narration import PiperFrNarration
from tools.base_tool import BaseTool, ToolResult, ToolRuntime


def test_valid_pilot_request():
    chk = check_request(StudioRequest(idea="Pub app gestion du temps", video_type="Publicité",
                                      duration_s=30, format="16:9", language="Français"))
    assert chk.ok and not chk.errors and not chk.ask_for
    assert chk.request.video_type == "publicite" and chk.request.language == "fr"


def test_empty_form_asks_for_idea_only():
    chk = check_request(StudioRequest())
    assert not chk.ok and chk.ask_for == ["idee"] and not chk.errors


def test_defaults_are_announced():
    chk = check_request(StudioRequest(idea="x", video_type="formation"))
    assert chk.ok
    assert chk.request.duration_s == 90 and chk.request.format == "16:9"
    assert any("durée 90" in d for d in chk.defaults_applied)
    assert any("16:9" in d for d in chk.defaults_applied)


@pytest.mark.parametrize("fmt", ["9:16", "1:1"])
def test_pending_formats_refused_with_alternative(fmt):
    chk = check_request(StudioRequest(idea="x", format=fmt))
    assert not chk.ok and "lot 1.4" in chk.errors[0]
    assert any("16:9" in a for a in chk.alternatives)


def test_unknown_format_refused():
    assert not check_request(StudioRequest(idea="x", format="4:3")).ok


@pytest.mark.parametrize("d,nearest", [(45, 30), (20, 15), (120, 90)])
def test_invalid_duration_refused_with_nearest(d, nearest):
    chk = check_request(StudioRequest(idea="x", duration_s=d))
    assert not chk.ok and f"{nearest} s" in chk.alternatives[0]


def test_non_french_refused():
    assert not check_request(StudioRequest(idea="x", language="en")).ok


def test_unknown_type_refused():
    assert not check_request(StudioRequest(idea="x", video_type="clip musical")).ok


def test_both_modes_presented_economique_default():
    modes = {m.id: m for m in cap.modes_status()}
    assert set(modes) == {"economique", "hybride"}
    assert modes["economique"].available and modes["economique"].default and modes["economique"].cost == "0 €"
    assert not modes["hybride"].available and not modes["hybride"].default
    assert modes["hybride"].requirements and "autorisation explicite" in " ".join(modes["hybride"].requirements)
    assert cap.DEFAULT_MODE == "economique"


def test_hybrid_never_allowed_in_phase_1(monkeypatch):
    for key in ("FAL_KEY", "KLING_API_KEY", "RUNWAY_API_KEY"):
        monkeypatch.setenv(key, "fausse-cle")
    assert cap.is_mode_allowed("economique")
    assert not cap.is_mode_allowed("hybride")


def test_both_composition_methods_presented_gabarits_recommended():
    methods = {m["id"]: m for m in cap.composition_methods()}
    assert set(methods) == {"gabarits", "atelier"}
    assert methods["gabarits"]["recommande"] and not methods["atelier"]["recommande"]
    assert methods["atelier"]["sur_demande"]
    assert cap.DEFAULT_COMPOSITION == "gabarits"


def test_both_runtimes_presented():
    assert [r["id"] for r in cap.render_runtimes()] == ["remotion", "hyperframes"]


def test_web_research_disabled_by_default():
    assert cap.WEB_RESEARCH_DEFAULT is False


class _FakePaid(BaseTool):
    name = "fake_paid_video"
    runtime = ToolRuntime.API

    def estimate_cost(self, inputs):
        return 0.40

    def execute(self, inputs):
        raise AssertionError("ne doit jamais être exécuté")


def test_quote_is_zero_for_local_plan_and_never_executes(tmp_path):
    from tools.tool_registry import registry
    registry.discover()
    guard = StudioBudgetGuard(tmp_path / "p")
    devis = cap.quote([PiperFrNarration(), registry.get("video_compose"), registry.get("audio_mixer")], guard)
    assert devis["total_usd"] == 0.0 and not devis["refuses"]
    devis = cap.quote([PiperFrNarration(), _FakePaid()], guard)
    assert devis["refuses"] == ["fake_paid_video"] and devis["total_usd"] == 0.0
    assert not guard.cost_log_path.exists()
