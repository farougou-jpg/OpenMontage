"""Lot 1.6 — tests 8 et 10 : outil complet, zones protégées, versions, rapport, obligation avant publication."""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from lib.studio.budget_guard import StudioBudgetGuard
from lib.studio.narration.tool import REPO_ROOT
from lib.studio.qc import QualityControlTool, publication_allowed
from lib.studio.storyboard import StoryboardTool
from lib.studio.storyboard.stills import renderer_available
from tests.studio.qc_data import load, paths, script_from_timing, sha

needs_renderer = pytest.mark.skipif(not renderer_available(), reason="rendu Remotion local indisponible")




def _make_studio_project(path: Path) -> Path:
    import json
    path.mkdir(parents=True, exist_ok=True)
    (path / "studio_project.json").write_text(json.dumps({
        "studio": "OpenMontage Studio", "version": 1, "projet": path.name,
        "pipeline": "studio-fr"
    }), encoding="utf-8")
    return path


def _inputs(name, project_dir, storyboard_dir=None, with_script=True):
    d = load(name)
    return {"mp4": str(d["mp4"]), "props": d["props"], "timing": d["timing"], "project_dir": str(project_dir),
            "storyboard_dir": str(storyboard_dir) if storyboard_dir else None,
            "script": script_from_timing(d["timing"], 30) if with_script else None, "title": name}


# ---- Test 8 : zones protégées, versions, garde-fou ----

def test_protected_zone_refused_without_writing():
    target = REPO_ROOT / "projects" / "demos" / "fr-series" / "code-to-screen"
    before = sorted(p.name for p in target.iterdir())
    res = QualityControlTool().execute(_inputs("code-to-screen", target))
    assert not res.success and "protégée" in res.error
    assert sorted(p.name for p in target.iterdir()) == before


def test_budget_guard_and_registry(tmp_path):
    d = StudioBudgetGuard(tmp_path / "p").check(QualityControlTool(), {})
    assert d.allowed and d.estimated_usd == 0.0 and d.runtime == "local"
    from tools.tool_registry import registry
    registry.discover()
    assert registry.get("studio_quality_control") is None


def test_missing_storyboard_and_script_block_publication(tmp_path):
    project = _make_studio_project(tmp_path / "p")
    res = QualityControlTool().execute(_inputs("world-in-numbers", project, with_script=False))
    assert res.success and not res.data["conforme"]
    assert any("storyboard validé absent" in b for b in res.data["bloquants"])
    assert any("scénario validé absent" in b for b in res.data["bloquants"])
    assert not publication_allowed(res)


# ---- Test 10 : chaîne complète et rapport ----

@needs_renderer
def test_full_qc_on_code_to_screen(tmp_path):
    d = load("code-to-screen")
    props = copy.deepcopy(d["props"])
    props.pop("audio")
    sb_project = _make_studio_project(tmp_path / "sb")
    sb = StoryboardTool().execute({"props": props, "project_dir": str(sb_project)})
    assert sb.success, sb.error
    sources = {k: sha(v) for k, v in paths("code-to-screen").items()}

    project = _make_studio_project(tmp_path / "projet")
    guard = StudioBudgetGuard(project)
    r1 = guard.run(QualityControlTool(), _inputs("code-to-screen", project, sb.data["version_dir"]))
    r2 = guard.run(QualityControlTool(), _inputs("code-to-screen", project, sb.data["version_dir"]))
    assert r1.success and r1.data["conforme"], r1.data["bloquants"]
    assert publication_allowed(r1)
    assert Path(r1.data["version_dir"]).name == "v001" and Path(r2.data["version_dir"]).name == "v002"

    v = Path(r1.data["version_dir"])
    for f in ("rapport_qc.md", "rapport_qc.json", "mesures_brutes.txt", "planche_mp4.png"):
        assert (v / f).is_file(), f
    assert len(list(v.glob("cmp_*.png"))) == 5
    md = (v / "rapport_qc.md").read_text(encoding="utf-8")
    for section in ("**Verdict : CONFORME**", "## Résultats", "## Synchronisation (mesurée dans le MP4)",
                    "## Conformité au storyboard validé", "marge de sécurité (8 images)"):
        assert section in md, section
    assert "Volume | -16.1 LUFS" in md
    assert {k: sha(v) for k, v in paths("code-to-screen").items()} == sources
    assert not guard.cost_log_path.exists()


# ---- Obligation avant publication (skill) ----

def test_executive_producer_requires_qc_before_publish():
    text = " ".join((REPO_ROOT / "skills" / "pipelines" / "studio-fr" / "executive-producer.md")
                    .read_text(encoding="utf-8").split())
    assert "QualityControlTool" in text and "publication_allowed" in text
    assert "Contrôle qualité obligatoire" in text
    assert "jamais présentée comme vidéo finale sans rapport de contrôle conforme" in text
