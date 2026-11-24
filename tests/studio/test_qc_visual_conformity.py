"""Lot 1.6 — tests 5, 6, 7 : conformité au storyboard validé, textes, noirs et images figées.

Les images fixes du storyboard sont rendues en local (Remotion, comme au lot 1.5) dans
le dossier temporaire ; les MP4 validés sont seulement lus.
"""

from __future__ import annotations

import copy
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from lib.studio.qc import visual
from lib.studio.qc.conformity import check_texts
from lib.studio.qc.report import QCResult
from lib.studio.storyboard import StoryboardTool
from lib.studio.storyboard.stills import FR_CONFIG_V3, render_still, renderer_available
from tests.studio.qc_data import VIDEOS, load, paths, script_from_timing, sha

needs_renderer = pytest.mark.skipif(not renderer_available(), reason="rendu Remotion local indisponible")


def _make_studio_project(path: Path) -> Path:
    import json
    path.mkdir(parents=True, exist_ok=True)
    (path / "studio_project.json").write_text(json.dumps({
        "studio": "OpenMontage Studio", "version": 1, "projet": path.name,
        "pipeline": "studio-fr"
    }), encoding="utf-8")
    return path


@pytest.fixture(scope="module")
def code_storyboard(tmp_path_factory):
    """Storyboard « validé » de code-to-screen : rendu local, sans audio, dans le dossier temporaire."""
    if not renderer_available():
        pytest.skip("rendu Remotion local indisponible")
    d = load("code-to-screen")
    props = copy.deepcopy(d["props"])
    props.pop("audio")
    root = tmp_path_factory.mktemp("sb")
    project = _make_studio_project(root / "code")
    # Comparaison avec un MP4 validé (rendu avant la v4) : storyboard explicitement en v3.
    res = StoryboardTool().execute({"props": props, "project_dir": str(project),
                                    "remotion_config": FR_CONFIG_V3})
    assert res.success, res.error
    return Path(res.data["version_dir"])


# ---- Test 5 : conformité visuelle ----

@needs_renderer
def test_mp4_matches_validated_storyboard(code_storyboard, tmp_path):
    mp4 = paths("code-to-screen")["mp4"]
    before = sha(mp4)
    sb = json.loads((code_storyboard / "storyboard.json").read_text(encoding="utf-8"))
    qc = QCResult()
    rows = visual.check_storyboard(mp4, sb, code_storyboard, tmp_path, qc)
    assert qc.conforme, qc.blocking
    assert len(rows) == 5 and all(r["ecart_pct"] < 2.0 for r in rows)
    assert all((tmp_path / r["comparaison"]).is_file() for r in rows)
    assert sha(mp4) == before


@needs_renderer
def test_changed_text_is_detected(code_storyboard, tmp_path):
    """Storyboard validé avec un texte différent pour une scène → écart > 2 % → bloquant."""
    altered_dir = tmp_path / "sb_modifie"
    shutil.copytree(code_storyboard, altered_dir)
    props = json.loads((altered_dir / "props_storyboard.json").read_text(encoding="utf-8"))
    hook = next(c for c in props["cuts"] if c["id"] == "code-hook")
    hook["text"] = "Un tout autre titre affiché"
    alt_props = altered_dir / "props_modifiees.json"
    alt_props.write_text(json.dumps(props, ensure_ascii=False), encoding="utf-8")
    sb = json.loads((altered_dir / "storyboard.json").read_text(encoding="utf-8"))
    scene = next(s for s in sb["scenes"] if s["id"] == "code-hook")
    render_still(alt_props, scene["frame"], altered_dir / scene["image"], config=FR_CONFIG_V3)
    qc = QCResult()
    rows = {r["scene"]: r for r in visual.check_storyboard(paths("code-to-screen")["mp4"], sb, altered_dir,
                                                           tmp_path / "out", qc)}
    hook_row = rows["code-hook"]
    assert hook_row["statut"] == "❌"
    assert hook_row["max_pixels_forts_tuile"] >= 3          # détecté par les tuiles…
    assert hook_row["ecart_pct"] < 2.0                       # …alors que la moyenne seule l'aurait manqué
    assert any("anomalie localisée" in b and "code-hook" in b for b in qc.blocking)
    assert all(r["statut"] == "✅" for k, r in rows.items() if k != "code-hook")
    assert not qc.conforme


# ---- Test 6 : conformité des textes (données en mémoire) ----

def _storyboard_from_props(props):
    from lib.studio.storyboard.tool import _screen_text
    return {"scenes": [{"id": c["id"], "screen_text": _screen_text(c)} for c in props["cuts"]]}


def test_texts_identical_are_conform():
    d = load("code-to-screen")
    qc = QCResult()
    check_texts(d["props"], _storyboard_from_props(d["props"]), d["timing"],
                script_from_timing(d["timing"], 24), qc)
    assert qc.conforme


@pytest.mark.parametrize("where", ["ecran", "narration", "scene_en_trop"])
def test_texts_changed_are_blocked(where):
    d = load("code-to-screen")
    props, timing = copy.deepcopy(d["props"]), copy.deepcopy(d["timing"])
    sb = _storyboard_from_props(d["props"])
    script = script_from_timing(d["timing"], 24)
    if where == "ecran":
        props["cuts"][1]["text"] = props["cuts"][1].get("text", "") + " (modifié)"
    elif where == "narration":
        timing[0]["texte_ecrit"] = "Une autre phrase."
    else:
        props["cuts"].append({"id": "inconnue", "type": "hero_title", "text": "x",
                              "in_seconds": 24, "out_seconds": 25})
    qc = QCResult()
    check_texts(props, sb, timing, script, qc)
    assert not qc.conforme


# ---- Test 7 : noirs et images figées ----

@pytest.mark.parametrize("name", list(VIDEOS))
def test_no_real_black_and_no_frozen_scene_in_validated_videos(name):
    d = load(name)
    qc = QCResult()
    visual.check_black_freeze(d["mp4"], d["props"]["cuts"], qc)
    assert qc.conforme and not qc.warnings, (qc.blocking, qc.warnings)


def _fake_ffmpeg(stderr):
    return lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout="", stderr=stderr)


def test_black_frames_are_blocked(monkeypatch):
    monkeypatch.setattr(visual.subprocess, "run", _fake_ffmpeg("black_start:2.0 black_end:3.1 black_duration:1.1"))
    qc = QCResult()
    visual.check_black_freeze(Path("x.mp4"), [{"id": "a", "in_seconds": 0, "out_seconds": 5}], qc)
    assert not qc.conforme


def test_frozen_whole_scene_is_a_warning_only(monkeypatch):
    log = "freeze_start: 0.2\nfreeze_duration: 4.7\nfreeze_end: 4.9"
    monkeypatch.setattr(visual.subprocess, "run", _fake_ffmpeg(log))
    qc = QCResult()
    visual.check_black_freeze(Path("x.mp4"), [{"id": "a", "in_seconds": 0, "out_seconds": 5}], qc)
    assert qc.conforme and any("figée" in w for w in qc.warnings)


# ---- Anomalie localisée : jamais masquée par la moyenne globale ----

def _erase(img, y0, y1, x0, x1):
    import numpy as np
    out = img.copy()
    out[y0:y1, x0:x1] = np.median(img[max(0, y0 - 30):y0 - 5, x0:x1].reshape(-1, 3), axis=0)
    return out


@needs_renderer
def test_localized_anomaly_never_masked_by_mean(code_storyboard, tmp_path):
    import numpy as np
    from PIL import Image
    sb = json.loads((code_storyboard / "storyboard.json").read_text(encoding="utf-8"))
    hook = next(s for s in sb["scenes"] if s["id"] == "code-hook")
    ref = np.asarray(Image.open(code_storyboard / hook["image"]).convert("RGB"), dtype=np.float32)
    mp4 = np.asarray(Image.open(visual.extract_frame(paths("code-to-screen")["mp4"], hook["frame"],
                                                     tmp_path / "f.png")).convert("RGB"), dtype=np.float32)
    good = visual.compare_arrays(ref, mp4)
    assert visual.is_conform(good) and good["max_pixels_forts_tuile"] < visual.TILE_MIN_STRONG

    lum = mp4.mean(axis=2)
    ys, xs = np.where(lum[565:569, 370:1550] > 120)          # accents du sous-titre (È, À)
    x = int(xs.min()) + 370
    for name, defect in {
        "accent effacé": _erase(mp4, 563, 570, x - 1, x + 4),
        "lettre du sous-titre effacée": _erase(mp4, 565, 590, 1531, 1548),
        "mise en page décalée de 1 px": np.roll(mp4, 1, axis=1),
    }.items():
        m = visual.compare_arrays(ref, defect)
        assert m["ecart_pct"] < visual.MAX_MEAN_DIFF_PCT, name       # la moyenne seule ne verrait rien
        assert m["max_pixels_forts_tuile"] >= visual.TILE_MIN_STRONG, (name, m)
        assert not visual.is_conform(m), name


def test_decision_rule_is_an_or():
    assert not visual.is_conform({"ecart_pct": 0.5, "max_pixels_forts_tuile": 3})
    assert not visual.is_conform({"ecart_pct": 2.0, "max_pixels_forts_tuile": 0})
    assert visual.is_conform({"ecart_pct": 1.99, "max_pixels_forts_tuile": 2})


# ---- Calibration sur les 5 vidéos validées (images de storyboard rendues en local, temporaire) ----

@needs_renderer
def test_calibration_on_all_validated_videos(tmp_path):
    """21 scènes sur 22 conformes ; animated-reel « final » détectée : dans le MP4 validé, le
    surlignage du titre coupe le mot « pour » (« Conçu po|ur »), défaut corrigé ensuite par la
    configuration FR v2 utilisée par le storyboard. Écart moyen < 2 % : seule la tuile le voit."""
    found = {}
    for name in VIDEOS:
        p = paths(name)
        before = {k: sha(v) for k, v in p.items()}
        d = load(name)
        props = copy.deepcopy(d["props"])
        props.pop("audio", None)
        # Vidéos validées rendues avant la v4 : calibration explicitement en v3.
        project = _make_studio_project(tmp_path / name)
        res = StoryboardTool().execute({"props": props, "project_dir": str(project),
                                        "remotion_config": FR_CONFIG_V3})
        assert res.success, res.error
        vdir = Path(res.data["version_dir"])
        sb = json.loads((vdir / "storyboard.json").read_text(encoding="utf-8"))
        qc = QCResult()
        for r in visual.check_storyboard(p["mp4"], sb, vdir, tmp_path / f"qc_{name}", qc):
            found[(name, r["scene"])] = r
        assert {k: sha(v) for k, v in p.items()} == before
    flagged = {k for k, r in found.items() if r["statut"] == "❌"}
    assert len(found) == 22
    assert flagged == {("animated-reel-20s", "final")}
    final = found[("animated-reel-20s", "final")]
    assert final["ecart_pct"] < 2.0 and final["max_pixels_forts_tuile"] >= 3
    assert max(r["max_pixels_forts_tuile"] for k, r in found.items() if k not in flagged) <= 1
