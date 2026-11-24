"""Lot 1.3 — pipeline studio-fr et skills du studio."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from lib.checkpoint import _stage_requires_approval, get_pipeline_stages
from lib.pipeline_loader import load_pipeline
from tools.base_tool import ToolRuntime
from tools.tool_registry import registry

REPO = Path(__file__).resolve().parents[2]
MANIFEST = REPO / "pipeline_defs" / "studio-fr.yaml"
STUDIO_SKILLS = sorted((REPO / "skills" / "pipelines" / "studio-fr").glob("*.md")) + [
    REPO / "skills" / "meta" / "studio-creative-router.md"]
SELECTORS = ("tts_selector", "image_selector", "video_selector")
STAGES = ["idea", "proposal", "script", "scene_plan", "assets", "edit", "compose", "publish"]


@pytest.fixture(scope="module")
def manifest():
    return load_pipeline("studio-fr")


def _text(p: Path) -> str:
    return p.read_text(encoding="utf-8")


# ---- 1. Manifeste et validations ----

def test_manifest_loads_with_declared_order(manifest):
    assert [s["name"] for s in manifest["stages"]] == STAGES
    assert get_pipeline_stages("studio-fr") == STAGES


def test_four_human_gates_enforced(manifest):
    gates = {s["name"]: _stage_requires_approval("studio-fr", s["name"]) for s in manifest["stages"]}
    assert {k for k, v in gates.items() if v} == {"proposal", "script", "scene_plan", "publish"}
    assert all(v is not None for v in gates.values())


# ---- 2. Budget et skills ----

def test_budget_default_zero_and_studio_defaults(manifest):
    assert manifest["orchestration"]["budget_default_usd"] == 0.0
    meta = manifest["metadata"]
    assert meta["default_mode"] == "economique"
    assert meta["default_composition_mode"] == "gabarits"
    assert meta["web_research_default"] is False
    assert meta["formats"] == ["16:9"] and meta["resolution"] == "1920x1080"


def test_all_referenced_skills_exist(manifest):
    refs = set(manifest["required_skills"]) | {s["skill"] for s in manifest["stages"]}
    refs.add(manifest["orchestration"]["skill"])
    for ref in refs:
        assert (REPO / "skills" / f"{ref}.md").is_file(), ref
    for p in (manifest["metadata"]["budget_guard"], manifest["metadata"]["remotion_config"]):
        assert (REPO / p).is_file(), p


def test_playbooks_exist(manifest):
    from styles.playbook_loader import list_playbooks
    offered = manifest["compatible_playbooks"]["recommended"] + manifest["compatible_playbooks"]["also_works"]
    assert set(offered) <= set(list_playbooks())


# ---- 3. Outils : tous locaux, aucun sélecteur ----

def test_every_listed_tool_is_local(manifest):
    registry.discover()
    listed = {t for s in manifest["stages"] for t in s.get("tools_available", [])}
    assert listed
    for name in listed:
        tool = registry.get(name)
        assert tool is not None, f"outil inconnu : {name}"
        assert tool.runtime in (ToolRuntime.LOCAL, ToolRuntime.LOCAL_GPU), f"{name} n'est pas local"
    assert not listed & set(SELECTORS)


def test_studio_narration_tool_is_local_and_outside_registry():
    from lib.studio.narration import PiperFrNarration
    registry.discover()
    assert PiperFrNarration().runtime == ToolRuntime.LOCAL
    assert registry.get("studio_piper_fr_narration") is None
    assert all(t.name != "studio_piper_fr_narration" for t in registry.get_by_capability("tts"))


# ---- 4. Contenu des skills ----

def test_studio_skills_carry_mandatory_rules():
    ep = _text(REPO / "skills/pipelines/studio-fr/executive-producer.md")
    for token in ("StudioBudgetGuard", "guard.run", "0 €", "Recherche web désactivée par défaut",
                  "remotion.fr-locale-v4.config.ts", "1920×1080", "Validation 1", "Validation 2",
                  "gabarits", "atelier", "économique"):
        assert token in ep, token
    assert "PiperFrNarration" in _text(REPO / "skills/pipelines/studio-fr/asset-director.md")
    idea = _text(REPO / "skills/pipelines/studio-fr/idea-director.md")
    assert "Recherche web : désactivée par défaut" in idea and "check_request" in idea


def test_proposal_presents_modes_methods_and_runtimes():
    body = _text(REPO / "skills/pipelines/studio-fr/proposal-director.md")
    for token in ("Mode économique — **sélectionné par défaut**", "Mode hybride",
                  "Gabarits — recommandés", "Atelier — sur demande", "sans en imposer une",
                  "render_runtime", "hyperframes", "Present both", "render_runtime_selection", "quote("):
        assert token in body, token
    router = _text(REPO / "skills/meta/studio-creative-router.md")
    for token in ("sélectionné par défaut, 0 €", "Ne jamais l'activer seul", "Ne jamais forcer",
                  "ne jamais changer de mode"):
        assert token in router, token


def test_selectors_only_mentioned_as_forbidden():
    for path in STUDIO_SKILLS:
        for para in re.split(r"\n\s*\n", _text(path)):
            if any(s in para for s in SELECTORS):
                assert re.search(r"[Aa]ucun|ignorer|[Ii]nterdit", para), f"{path.name}: {para[:120]}"


def test_no_paid_tool_named_in_studio_skills():
    registry.discover()
    paid = {n for n in registry.list_all() if registry.get(n).runtime == ToolRuntime.API}
    assert paid
    for path in STUDIO_SKILLS + [MANIFEST, REPO / "studio" / "README.md"]:
        words = set(re.findall(r"`([a-z0-9_]+)`", _text(path)))
        assert not words & paid, f"{path.name} cite un outil payant : {words & paid}"


def test_manifest_yaml_has_no_paid_tool_anywhere():
    raw = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    registry.discover()
    paid = {n for n in registry.list_all() if registry.get(n).runtime == ToolRuntime.API}
    dump = yaml.safe_dump(raw)
    assert not [p for p in paid if re.search(rf"\b{re.escape(p)}\b", dump)]
