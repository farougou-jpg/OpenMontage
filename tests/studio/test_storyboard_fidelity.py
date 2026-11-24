"""Lot 1.5 — test 6 : fidélité des images fixes au rendu vidéo validé.

Les props et le MP4 de code-to-screen FR sont LUS sans modification ; les images
(rendu Remotion et extraction FFmpeg) vont uniquement dans tmp_path.
"""

from __future__ import annotations

import copy
import hashlib
import json
import subprocess
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from lib.studio.storyboard import StoryboardTool
from lib.studio.storyboard.stills import renderer_available

REPO = Path(__file__).resolve().parents[2]
VIDEO_DIR = REPO / "projects" / "demos" / "fr-series" / "code-to-screen"
PROPS = VIDEO_DIR / "code-to-screen-fr.json"
MP4 = VIDEO_DIR / "code-to-screen-fr.mp4"
SCENES = ("code-hook", "code-compare", "code-kpis")  # hero_title, comparison, kpi_grid
MAX_MEAN_DIFF_PCT = 2.0


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _make_studio_project(path: Path) -> Path:
    import json
    path.mkdir(parents=True, exist_ok=True)
    (path / "studio_project.json").write_text(json.dumps({
        "studio": "OpenMontage Studio", "version": 1, "projet": path.name,
        "pipeline": "studio-fr"
    }), encoding="utf-8")
    return path


def _frame_from_mp4(frame: int, out: Path) -> Path:
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(MP4),
                    "-vf", f"select=eq(n\\,{frame})", "-vframes", "1", str(out)], check=True)
    return out


@pytest.mark.skipif(not renderer_available(), reason="rendu Remotion local indisponible")
def test_stills_match_validated_video(tmp_path):
    sha_before = (_sha(PROPS), _sha(MP4))
    props = json.loads(PROPS.read_text(encoding="utf-8"))
    # Composition complète, mêmes instants que la vidéo ; l'audio ne change pas l'image
    # et un brouillon de storyboard n'en contient pas.
    full = copy.deepcopy(props)
    full.pop("audio")

    project = _make_studio_project(tmp_path / "fidelite")
    res = StoryboardTool().execute({"props": full, "project_dir": str(project)})
    assert res.success, res.error
    vdir = Path(res.data["version_dir"])
    scenes = {s["id"]: s for s in res.data["scenes"]}
    diffs = {}
    for sid in SCENES:
        s = scenes[sid]
        ref = _frame_from_mp4(s["frame"], tmp_path / f"mp4_{sid}.png")
        a = np.asarray(Image.open(vdir / s["image"]).convert("RGB"), dtype=np.float32)
        b = np.asarray(Image.open(ref).convert("RGB"), dtype=np.float32)
        assert a.shape == b.shape == (1080, 1920, 3)
        diffs[sid] = float(np.abs(a - b).mean() / 255 * 100)
    assert all(d < MAX_MEAN_DIFF_PCT for d in diffs.values()), diffs
    assert (_sha(PROPS), _sha(MP4)) == sha_before
