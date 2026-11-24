"""Lot 1.6 — refus de publication : 10 cas réels vérifiés individuellement + fail closed.

Storyboard de référence = images EXTRAITES du MP4 validé de code-to-screen (aucun rendu,
aucune génération). Les sources sont lues sans modification (empreintes vérifiées).
"""

from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from lib.studio.narration.tool import REPO_ROOT
from lib.studio.qc import QualityControlTool, publication_allowed
from lib.studio.qc.visual import extract_frame
from lib.studio.storyboard.stills import choose_frame
from lib.studio.storyboard.tool import _screen_text
from tests.studio.qc_data import load, paths, script_from_timing, sha
from tools.base_tool import ToolResult


def _storyboard_from_mp4(d: dict, out: Path) -> Path:
    scenes = []
    for i, c in enumerate(sorted(d["props"]["cuts"], key=lambda c: c["in_seconds"]), start=1):
        f = choose_frame(c)
        rel = f"scenes/scene_{i:02d}.png"
        extract_frame(d["mp4"], f, out / rel)
        scenes.append({"number": i, "id": c["id"], "frame": f, "image": rel, "screen_text": _screen_text(c)})
    (out / "storyboard.json").write_text(json.dumps({"scenes": scenes}, ensure_ascii=False), encoding="utf-8")
    return out


@pytest.fixture(scope="module")
def refs(tmp_path_factory):
    root = tmp_path_factory.mktemp("refus")
    before = {n: {k: sha(v) for k, v in paths(n).items()} for n in ("code-to-screen", "animated-reel-20s")}
    code = load("code-to-screen")
    sb = _storyboard_from_mp4(code, root / "sb_code")
    altered = root / "sb_altere"
    shutil.copytree(sb, altered)
    img = np.asarray(Image.open(altered / "scenes" / "scene_01.png").convert("RGB")).copy()
    img[565:590, 1531:1548] = img[540:545, 1531:1548].mean(axis=(0, 1))   # une lettre du sous-titre
    Image.fromarray(img).save(altered / "scenes" / "scene_01.png")
    ar = load("animated-reel-20s")
    sb_ar = _storyboard_from_mp4(ar, root / "sb_ar")
    yield {"root": root, "code": code, "sb": sb, "altered": altered, "ar": ar, "sb_ar": sb_ar}
    assert {n: {k: sha(v) for k, v in paths(n).items()} for n in before} == before


def _case(refs, name):
    d = refs["code"]
    props, timing = copy.deepcopy(d["props"]), copy.deepcopy(d["timing"])
    script = script_from_timing(d["timing"], 30)
    sb, mp4, project = refs["sb"], d["mp4"], refs["root"] / name
    if name == "1_format_faux":
        props["tailPaddingSeconds"] = 3
    elif name == "2_decalage_audio":
        for r in timing:
            r["debut"] += 0.5
            r["fin"] += 0.5
    elif name == "3_texte_ecran_different":
        props["cuts"][0]["text"] = "Autre titre"
    elif name == "4_narration_differente":
        script["sections"][0]["text"] = "Autre phrase."
    elif name == "5_lettre_differente_image":
        sb = refs["altered"]
    elif name == "6_storyboard_absent":
        sb = None
    elif name == "7_scenario_absent":
        script = None
    elif name == "8_animated_reel_marges":
        ar = refs["ar"]
        props, timing, mp4, sb = ar["props"], ar["timing"], ar["mp4"], refs["sb_ar"]
        script = script_from_timing(ar["timing"], 30)
    elif name == "9_zone_protegee":
        project = REPO_ROOT / "projects" / "demos" / "fr-series" / "code-to-screen"
    if name != "9_zone_protegee":
        project.mkdir(parents=True, exist_ok=True)
        (project / "studio_project.json").write_text(json.dumps({
            "studio": "OpenMontage Studio", "version": 1, "projet": project.name,
            "pipeline": "studio-fr"
        }), encoding="utf-8")
    return QualityControlTool().execute({
        "mp4": str(mp4), "props": props, "timing": timing, "project_dir": str(project),
        "storyboard_dir": str(sb) if sb else None, "script": script})


def test_case_0_witness_is_allowed(refs):
    res = _case(refs, "0_temoin")
    assert res.success and res.data["conforme"] is True
    assert publication_allowed(res) is True


@pytest.mark.parametrize("name,cause", [
    ("1_format_faux", "Format"),
    ("2_decalage_audio", "Décalage audio"),
    ("3_texte_ecran_different", "Conformité des textes"),
    ("4_narration_differente", "Conformité des textes"),
    ("5_lettre_differente_image", "Conformité visuelle"),
    ("6_storyboard_absent", "Conformité visuelle"),
    ("7_scenario_absent", "Conformité des textes"),
    ("8_animated_reel_marges", "Marge de parole"),
])
def test_failing_qc_refuses_publication(refs, name, cause):
    res = _case(refs, name)
    assert res.success is True and res.data["conforme"] is False
    assert any(b.startswith(cause) for b in res.data["bloquants"]), res.data["bloquants"]
    assert publication_allowed(res) is False


def test_case_9_protected_zone_tool_failure_refuses_publication(refs):
    res = _case(refs, "9_zone_protegee")
    assert res.success is False and "protégée" in res.error
    assert publication_allowed(res) is False


# ---- Fail closed ----

def _good(refs):
    res = _case(refs, "0_temoin_bis")
    assert publication_allowed(res) is True
    return res


@pytest.mark.parametrize("value", ["True", "False", "non", 1, [0], None])
def test_non_boolean_conforme_is_refused(refs, value):
    res = _good(refs)
    res.data["conforme"] = value
    assert publication_allowed(res) is False


@pytest.mark.parametrize("bad", [
    None, "conforme", {"conforme": True}, ToolResult(success=False, error="x"),
    ToolResult(success=True, data={}), ToolResult(success=True, data={"conforme": True}),
    ToolResult(success="yes", data={"conforme": True}),
])
def test_absent_or_forged_results_are_refused(bad):
    assert publication_allowed(bad) is False


def test_missing_or_unreadable_report_is_refused(refs, tmp_path):
    res = _good(refs)
    rapport = Path(res.data["rapport_json"])
    saved = rapport.read_bytes()
    rapport.write_text("{ pas du json", encoding="utf-8")
    assert publication_allowed(res) is False
    rapport.unlink()
    assert publication_allowed(res) is False
    rapport.write_bytes(saved)
    assert publication_allowed(res) is True


def test_report_contradicting_result_is_refused(refs):
    res = _good(refs)
    rapport = Path(res.data["rapport_json"])
    data = json.loads(rapport.read_text(encoding="utf-8"))
    data["conforme"] = False
    rapport.write_text(json.dumps(data), encoding="utf-8")
    assert publication_allowed(res) is False


def test_blocking_list_overrides_conforme_flag(refs):
    res = _good(refs)
    res.data["bloquants"] = ["Format — injecté"]
    assert publication_allowed(res) is False


def test_unexpected_exception_becomes_refusal(refs, monkeypatch):
    def boom(*a, **k):
        raise OSError("disque indisponible (simulé)")
    monkeypatch.setattr("lib.studio.qc.tool.next_version_dir", boom)
    res = _case(refs, "10_exception")
    assert res.success is False and "OSError" in res.error
    assert publication_allowed(res) is False
