"""Lot v4 — StatCard.fr.tsx (Space Grotesk, graisse 700) et configuration FR v4.

Garanties : la v3 et StatCard.tsx restent intacts ; la v4 = v3 + StatCard ; le rendu
v4 ne change que le texte des scènes `stat_card` (fond identique), et rien d'autre.
Rendus locaux uniquement, dans le dossier temporaire de pytest.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import re
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from lib.studio.qc.visual import compare_arrays
from lib.studio.storyboard import StoryboardTool
from lib.studio.storyboard.stills import (
    FR_CONFIG, FR_CONFIG_V3, FR_CONFIG_V4, render_still, renderer_available,
)

REPO = Path(__file__).resolve().parents[2]
COMPOSER = REPO / "remotion-composer"
COMPONENTS = COMPOSER / "src" / "components"
BACKUPS = REPO / "studio" / "backups"
needs_renderer = pytest.mark.skipif(not renderer_available(), reason="rendu Remotion local indisponible")


def _make_studio_project(path: Path) -> Path:
    import json
    path.mkdir(parents=True, exist_ok=True)
    (path / "studio_project.json").write_text(json.dumps({
        "studio": "OpenMontage Studio", "version": 1, "projet": path.name,
        "pipeline": "studio-fr"
    }), encoding="utf-8")
    return path


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _recorded(name: str) -> str:
    return (BACKUPS / f"{name}.2026-11-18-lot-v4.bak.sha256").read_text(encoding="utf-8").split()[0]


# ---- Intégrité des originaux ----

def test_v3_config_and_original_statcard_unchanged():
    assert _sha(COMPOSER / "remotion.fr-locale-v3.config.ts") == _recorded("remotion.fr-locale-v3.config.ts")
    assert _sha(COMPONENTS / "StatCard.tsx") == _recorded("StatCard.tsx")
    assert _sha(COMPOSER / "remotion.fr-locale-v3.config.ts").startswith("7318bd0d")
    assert _sha(COMPONENTS / "StatCard.tsx").startswith("e23f4515")


# ---- StatCard.fr.tsx : seulement la police (et la graisse 700 du chiffre) ----

def test_statcard_fr_differs_only_by_font_and_weight():
    orig = (COMPONENTS / "StatCard.tsx").read_text(encoding="utf-8").splitlines()
    fr = (COMPONENTS / "StatCard.fr.tsx").read_text(encoding="utf-8").splitlines()
    diff = [d for d in difflib.ndiff(orig, fr) if d[:2] in ("- ", "+ ")]
    removed = sorted(d[2:].strip() for d in diff if d.startswith("- "))
    added = sorted(d[2:].strip() for d in diff if d.startswith("+ "))
    assert removed == sorted(['fontFamily: "Inter, system-ui, sans-serif",',
                              'fontFamily: "Inter, system-ui, sans-serif",', "fontWeight: 800,"])
    assert [a for a in added if not a.startswith("//")] == sorted(
        ['fontFamily: "Space Grotesk, Inter, system-ui, sans-serif",',
         'fontFamily: "Space Grotesk, Inter, system-ui, sans-serif",', "fontWeight: 700,"])
    assert len([a for a in added if a.startswith("//")]) == 1  # commentaire d'en-tête
    assert len(fr) == len(orig) + 1


def test_space_grotesk_weights_are_loaded_by_explainer():
    src = (COMPOSER / "src" / "Explainer.tsx").read_text(encoding="utf-8")
    assert 'loadSpaceGrotesk(["400", "700"])' in src  # 700 = chiffre, 400 = sous-titre


# ---- Configuration v4 = v3 + StatCard ----

def _variants(path: Path) -> set[str]:
    regex = re.search(r"const FR_VARIANTS = /(.+)/;", path.read_text(encoding="utf-8")).group(1)
    names = set(re.findall(r"[A-Z][A-Za-z]+", regex))
    return names


def test_v4_is_v3_plus_statcard():
    v3, v4 = COMPOSER / FR_CONFIG_V3, COMPOSER / FR_CONFIG_V4
    assert _variants(v4) == _variants(v3) | {"StatCard"}
    assert "StatCard" not in _variants(v3)
    # Hors en-tête et ligne FR_VARIANTS, le code de la v4 est identique à la v3.
    def code(p):
        lines = p.read_text(encoding="utf-8").splitlines()
        return [l for l in lines if not l.lstrip().startswith(("/**", "*", "*/")) and "FR_VARIANTS = " not in l]
    assert code(v3) == code(v4)


def test_default_config_is_v4_and_v3_allowed():
    assert FR_CONFIG == FR_CONFIG_V4
    res = StoryboardTool().execute({"props": {"theme": "flat-motion-graphics", "cuts": [
        {"id": "a", "source": "", "type": "hero_title", "text": "x", "in_seconds": 0, "out_seconds": 2}]},
        "project_dir": str(REPO / "ne-pas-ecrire"), "remotion_config": "autre.config.ts"})
    assert not res.success and "non autorisée" in res.error
    assert not (REPO / "ne-pas-ecrire").exists()


# ---- Rendus v3 / v4 ----

def _render(tmp: Path, props: dict, frame: int, config: str, name: str) -> np.ndarray:
    pp = tmp / f"{name}.json"
    pp.write_text(json.dumps(props, ensure_ascii=False), encoding="utf-8")
    out = render_still(pp, frame, tmp / f"{name}.png", config=config)
    return np.asarray(Image.open(out).convert("RGB")).astype(int)


STAT = {"theme": "flat-motion-graphics", "overlays": [], "captions": [], "cuts": [
    {"id": "s", "source": "", "type": "stat_card", "stat": "3", "subtitle": "problèmes qui vous volent du temps",
     "in_seconds": 0, "out_seconds": 4}]}
OTHERS = {"theme": "flat-motion-graphics", "captions": [], "cuts": [
    {"id": "h", "source": "", "type": "hero_title", "text": "Les réunions s'enchaînent", "in_seconds": 0, "out_seconds": 4},
    {"id": "c", "source": "", "type": "comparison", "leftLabel": "Avant", "leftValue": "Journée subie",
     "rightLabel": "Après", "rightValue": "Journée maîtrisée", "in_seconds": 4, "out_seconds": 10}],
    "overlays": [{"type": "section_title", "text": "Problème 1", "in_seconds": 0.3, "out_seconds": 3.8}]}


@needs_renderer
def test_v4_changes_only_the_statcard_text(tmp_path):
    a = _render(tmp_path, STAT, 109, FR_CONFIG_V3, "v3")
    b = _render(tmp_path, STAT, 109, FR_CONFIG_V4, "v4")
    diff = np.abs(a - b).max(axis=2) > 0
    assert diff.any(), "la v4 doit changer la police du stat_card"
    ys, xs = np.where(diff)
    assert 400 < ys.min() and ys.max() < 700, (ys.min(), ys.max())  # uniquement la bande du texte
    outside = diff.copy()
    outside[ys.min():ys.max() + 1, xs.min():xs.max() + 1] = False
    assert not outside.any()
    bg = np.array([30, 41, 59])                                       # fond #1E293B inchangé
    assert (a[:300, :300] == bg).all() and (b[:300, :300] == bg).all()
    # Lisibilité du « 3 » (graisse 700, moins massif mais même hauteur à ±3 px)
    def digit_height(img):
        t = np.abs(img - bg).max(axis=2) > 40
        rows = np.where(t.any(axis=1))[0]
        split = rows[np.where(np.diff(rows) > 5)[0][0]]
        return split - rows.min() + 1
    assert abs(digit_height(a) - digit_height(b)) <= 3


@needs_renderer
@pytest.mark.parametrize("frame", [72, 228])   # hero_title + surimpression, puis comparison
def test_v4_leaves_other_components_identical(tmp_path, frame):
    a = _render(tmp_path, OTHERS, frame, FR_CONFIG_V3, "v3")
    b = _render(tmp_path, OTHERS, frame, FR_CONFIG_V4, "v4")
    m = compare_arrays(a.astype(np.float32), b.astype(np.float32))
    assert m["max_pixels_forts_tuile"] == 0 and m["ecart_pct"] < 0.05, m


@needs_renderer
def test_storyboard_records_render_config(tmp_path):
    project = _make_studio_project(tmp_path / "p")
    res = StoryboardTool().execute({"props": STAT, "project_dir": str(project)})
    assert res.success and res.data["configuration_rendu"] == FR_CONFIG_V4
    sb = json.loads((Path(res.data["version_dir"]) / "storyboard.json").read_text(encoding="utf-8"))
    assert sb["configuration_rendu"] == FR_CONFIG_V4
