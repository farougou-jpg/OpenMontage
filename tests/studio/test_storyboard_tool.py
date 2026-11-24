"""Lot 1.5 — tests 3, 4, 5 (sans rendu) puis 7 et 8 (rendu local Remotion, dossier temporaire)."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from lib.studio.budget_guard import StudioBudgetGuard
from lib.studio.narration.tool import REPO_ROOT, PathPolicyError
from lib.studio.storyboard import StoryboardTool
from lib.studio.storyboard.sheet import SceneEntry, build_sheet, write_documents
from lib.studio.storyboard.stills import CHROME, COMPOSER, renderer_available, still_command

MINI = {
    "theme": "flat-motion-graphics",
    "cuts": [
        {"id": "accroche", "source": "", "type": "hero_title", "text": "Vos journées vous échappent ?",
         "in_seconds": 0, "out_seconds": 3},
        {"id": "probleme", "source": "", "type": "text_card", "text": "Les réunions s'enchaînent",
         "in_seconds": 3, "out_seconds": 6},
        {"id": "alerte", "source": "", "type": "callout", "callout_type": "warning",
         "text": "La liste de tâches ne finit jamais", "in_seconds": 6, "out_seconds": 9},
    ],
    "overlays": [], "captions": [],
}
needs_renderer = pytest.mark.skipif(not renderer_available(), reason="rendu Remotion local indisponible")


def _make_studio_project(path: Path) -> Path:
    import json
    path.mkdir(parents=True, exist_ok=True)
    (path / "studio_project.json").write_text(json.dumps({
        "studio": "OpenMontage Studio", "version": 1, "projet": path.name,
        "pipeline": "studio-fr"
    }), encoding="utf-8")
    return path


# ---- Test 3 : zones protégées, versions ----

@pytest.mark.parametrize("target", [
    REPO_ROOT / "projects" / "demos" / "fr-series" / "code-to-screen",
    REPO_ROOT / "projects" / "demos" / "nouveau",
])
def test_protected_zones_refused_without_rendering(target, monkeypatch):
    calls = []
    monkeypatch.setattr("lib.studio.storyboard.tool.render_still", lambda *a, **k: calls.append(a))
    res = StoryboardTool().execute({"props": MINI, "project_dir": str(target)})
    assert not res.success and "protégée" in res.error
    assert calls == [] and not (target / "storyboard").exists()


def test_invalid_props_refused_before_any_write(tmp_path):
    bad = {**MINI, "theme": "inconnu"}
    res = StoryboardTool().execute({"props": bad, "project_dir": str(tmp_path / "p")})
    assert not res.success and "Brouillon refusé" in res.error
    assert not (tmp_path / "p").exists()


def test_versions_never_overwritten(tmp_path, monkeypatch):
    def fake_render(props_path, frame, out_png, *a, **k):
        out_png.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (1920, 1080), (15, 23, 42)).save(out_png)
        return out_png
    monkeypatch.setattr("lib.studio.storyboard.tool.render_still", fake_render)
    _make_studio_project(tmp_path / "p")
    r1 = StoryboardTool().execute({"props": MINI, "project_dir": str(tmp_path / "p")})
    r2 = StoryboardTool().execute({"props": MINI, "project_dir": str(tmp_path / "p")})
    assert r1.success and r2.success
    assert Path(r1.data["version_dir"]).name == "v001" and Path(r2.data["version_dir"]).name == "v002"


# ---- Test 4 : garde-fou ----

def test_budget_guard_allows_storyboard_at_zero_cost(tmp_path):
    d = StudioBudgetGuard(tmp_path / "p").check(StoryboardTool(), {})
    assert d.allowed and d.estimated_usd == 0.0 and d.runtime == "local"


def test_storyboard_tool_outside_registry():
    from tools.tool_registry import registry
    registry.discover()
    assert registry.get("studio_storyboard") is None


# ---- Test 5 : planche et documents (images synthétiques, aucun rendu) ----

def test_sheet_and_offline_html(tmp_path):
    entries = []
    for n, (cid, txt) in enumerate([("a", "Vos journées vous échappent ?"), ("b", "Réunions à rallonge"),
                                    ("c", "Tâches • priorités • « focus »"), ("d", "Fin")], start=1):
        rel = f"scenes/scene_{n:02d}.png"
        (tmp_path / "scenes").mkdir(exist_ok=True)
        Image.new("RGB", (1920, 1080), (40 * n, 30, 60)).save(tmp_path / rel)
        entries.append(SceneEntry(n, cid, n * 3.0 - 3, n * 3.0, "text_card", txt, "Narration accentuée é à ç",
                                  "fondu 8 images", 60, rel))
    sheet = build_sheet(entries, tmp_path, "Pub test — planche")
    with Image.open(sheet) as im:
        assert im.size == (3 * 640 + 4 * 24, 90 + 2 * (360 + 190 + 24) + 24)
    docs = write_documents(entries, tmp_path, "Pub test", {"style": "flat-motion-graphics"})
    page = docs["html"].read_text(encoding="utf-8")
    assert "http://" not in page and "https://" not in page and "<script" not in page
    assert 'src="scenes/scene_01.png"' in page and "Vos journées vous échappent ?" in page
    assert "« focus »" in docs["md"].read_text(encoding="utf-8")
    assert "Narration accentuée é à ç" in docs["json"].read_text(encoding="utf-8")


# ---- Test 8 (partie statique) : commande 100 % locale ----

def test_still_command_is_local_only(tmp_path):
    cmd = still_command(tmp_path / "p.json", 10, tmp_path / "o.png")
    joined = " ".join(cmd)
    assert "npx" not in joined
    assert f"--browser-executable={CHROME}" in cmd and CHROME.is_file()
    assert "--bundle-cache=false" in cmd and "--config=remotion.fr-locale-v4.config.ts" in cmd
    cmd3 = still_command(tmp_path / "p.json", 10, tmp_path / "o.png", config="remotion.fr-locale-v3.config.ts")
    assert "--config=remotion.fr-locale-v3.config.ts" in cmd3
    with pytest.raises(ValueError):
        still_command(tmp_path / "p.json", 10, tmp_path / "o.png", config="autre.config.ts")


# Journal interne du navigateur local : il y ajoute parfois des messages GPU. Ce n'est
# ni un téléchargement ni un accès réseau ; il est exclu de l'instantané mais son
# contenu ajouté est contrôlé (aucune entrée réseau).
BROWSER_LOG = CHROME.parent / "debug.log"
NETWORK_MARKERS = ("http", "dns", "network", "net::", "socket", "connect", "download")


def _snapshot(paths):
    snap = {}
    for root in paths:
        if root.exists():
            for dirpath, _, files in os.walk(root):
                for f in files:
                    p = Path(dirpath) / f
                    if p == BROWSER_LOG:
                        continue
                    snap[str(p)] = p.stat().st_mtime_ns
    return snap


def _log_bytes() -> bytes:
    return BROWSER_LOG.read_bytes() if BROWSER_LOG.exists() else b""


def _git_status(path: Path) -> str:
    return subprocess.run(["git", "status", "--porcelain", "--", str(path)], cwd=str(REPO_ROOT),
                          capture_output=True, text=True).stdout


# ---- Tests 7 et 8 : chaîne complète avec rendu local ----

@needs_renderer
def test_end_to_end_storyboard_render(tmp_path):
    watched = [COMPOSER / "node_modules" / ".cache", COMPOSER / "node_modules" / ".remotion"]
    before, git_before, log_before = _snapshot(watched), _git_status(COMPOSER), _log_bytes()
    exe_sha = __import__("hashlib").sha256(CHROME.read_bytes()).hexdigest()

    _make_studio_project(tmp_path / "pub-test")
    guard = StudioBudgetGuard(tmp_path / "pub-test")
    res = guard.run(StoryboardTool(), {
        "props": MINI, "project_dir": str(tmp_path / "pub-test"), "title": "Pub test",
        "narration": {"accroche": "Vos journées vous échappent ?"},
    })
    assert res.success, res.error
    vdir = Path(res.data["version_dir"])
    assert vdir.name == "v001" and str(vdir).startswith(str(tmp_path))
    for n in (1, 2, 3):
        with Image.open(vdir / "scenes" / f"scene_{n:02d}.png") as im:
            assert im.size == (1920, 1080)
            import numpy as np
            assert len(np.unique(np.asarray(im.convert("L").resize((64, 36))))) > 3  # pas une image vide
    for f in ("planche.png", "storyboard.html", "storyboard.md", "storyboard.json", "props_storyboard.json"):
        assert (vdir / f).is_file(), f
    assert [s["frame"] for s in res.data["scenes"]] == [54, 144, 234]
    assert not guard.cost_log_path.exists()

    # Test 8 : aucun téléchargement de navigateur, aucun cache écrit, dépôt inchangé
    assert _snapshot(watched) == before
    assert __import__("hashlib").sha256(CHROME.read_bytes()).hexdigest() == exe_sha
    assert _git_status(COMPOSER) == git_before
    log_after = _log_bytes()
    assert log_after.startswith(log_before)  # journal seulement complété, jamais réécrit
    added = log_after[len(log_before):].decode("utf-8", "replace").lower()
    assert not [m for m in NETWORK_MARKERS if m in added], added[-500:]
