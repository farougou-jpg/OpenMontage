"""Lot P0-C — contrat des skills et du manifeste : validation 3, rendu par render.py, checkpoints Studio.

Vérifie le texte réellement lu par l'agent et le manifeste réellement chargé.
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path

import pytest

from lib.checkpoint import _stage_requires_approval
from lib.pipeline_loader import load_pipeline
from lib.studio import checkpoints as ckp
from lib.studio import project as prj
from lib.studio import render as ren
from lib.studio import validations as val

REPO = Path(__file__).resolve().parents[2]
SKILLS = REPO / "skills" / "pipelines" / "studio-fr"


def _text(name: str) -> str:
    return (SKILLS / name).read_text(encoding="utf-8")


def _in_order(text: str, *tokens: str) -> bool:
    positions = [text.find(t) for t in tokens]
    return all(p >= 0 for p in positions) and positions == sorted(positions)


def test_asset_director_wires_validation_3_before_checkpoint():
    text = _text("asset-director.md")
    assert _in_order(text, "PiperFrNarration", 'val.presentation(project_dir, "narration"', "accord explicite de l'utilisateur",
                     "val.validate_narration(", 'ckp.write_studio_checkpoint(project_dir, "assets"')
    assert 'empreinte_presentee=shown["empreinte"]' in text and "<mots exacts de l'utilisateur>" in text
    assert "human_approved=True" in text


def test_compose_director_forces_render_py_and_forbids_other_engines():
    text = _text("compose-director.md")
    assert _in_order(text, "render_runtime", "ren.prepare_render(", "ren.run_render(", "ren.check_render(",
                     'ckp.write_studio_checkpoint(project_dir, "compose"')
    para = next(x for x in re.split(r"\n\s*\n", text) if "`video_compose`" in x)
    assert "Interdits en phase 1" in para and "`hyperframes_compose`" in para
    assert "même avec un rapport de contrôle conforme" in " ".join(text.split())
    assert "gelée" in text


def test_edit_director_reuses_validated_storyboard_cuts():
    text = " ".join(_text("edit-director.md").split())
    for token in ("aucune nouvelle coupe", "props_storyboard.json", '"render_runtime": "remotion"',
                  'ckp.write_studio_checkpoint(project_dir, "edit"'):
        assert token in text, token


def test_manifest_routes_edit_and_compose_to_studio_skills_without_render_tools():
    m = load_pipeline("studio-fr")
    stages = {s["name"]: s for s in m["stages"]}
    assert stages["edit"]["skill"] == "pipelines/studio-fr/edit-director"
    assert stages["compose"]["skill"] == "pipelines/studio-fr/compose-director"
    assert not {"video_compose", "hyperframes_compose", "remotion_caption_burn"} & set(stages["compose"]["tools_available"])
    assert "pipelines/explainer/compose-director" not in m["required_skills"]
    gates = {n for n in stages if _stage_requires_approval("studio-fr", n)}
    assert gates == {"proposal", "script", "scene_plan", "publish"}          # manifeste : 4 accords, inchangé


def test_no_studio_skill_instructs_a_direct_checkpoint_write():
    for path in sorted(SKILLS.glob("*.md")):
        for para in re.split(r"\n\s*\n", path.read_text(encoding="utf-8")):
            if re.search(r"(?<!studio_)write_checkpoint\(", para):
                assert "write_studio_checkpoint" in para, f"{path.name}: {para[:160]}"


def test_executive_producer_states_p0c_rules_and_publish_freeze():
    ep = " ".join(_text("executive-producer.md").split())
    for token in ("`assets` | Validation 3", "val.validate_narration(", "ckp.write_studio_checkpoint(",
                  "jamais d'appel direct", "pipelines/studio-fr/compose-director",
                  "rendu exclusivement par `lib/studio/render.py`", "gelée pour le studio jusqu'au lot P0-D"):
        assert token in ep, token
    prop = " ".join(_text("proposal-director.md").split())
    assert "indisponible au rendu en phase 1" in prop and "Present both" in prop


def test_every_function_cited_by_studio_skills_exists():
    mods = {"prj": prj, "val": val, "ren": ren, "ckp": ckp}
    cited: dict[str, set] = {k: set() for k in mods}
    for path in sorted(SKILLS.glob("*.md")):
        for mod, fn in re.findall(r"\b(prj|val|ren|ckp)\.([a-z_]+)\(", path.read_text(encoding="utf-8")):
            cited[mod].add(fn)
    assert {"prepare_render", "run_render", "check_render"} <= cited["ren"]
    assert {"write_studio_checkpoint"} <= cited["ckp"] and "validate_narration" in cited["val"]
    for mod, fns in cited.items():
        for fn in fns:
            assert callable(getattr(mods[mod], fn, None)), f"{mod}.{fn} absent"
    params = inspect.signature(ckp.write_studio_checkpoint).parameters
    assert params["human_approved"].kind is inspect.Parameter.KEYWORD_ONLY


@pytest.mark.parametrize("name", ["edit-director.md", "compose-director.md", "asset-director.md"])
def test_new_studio_skills_name_no_paid_tool_and_no_selector_outside_prohibition(name):
    from tools.base_tool import ToolRuntime
    from tools.tool_registry import registry
    registry.discover()
    paid = {n for n in registry.list_all() if registry.get(n).runtime == ToolRuntime.API}
    text = _text(name)
    assert not set(re.findall(r"`([a-z0-9_]+)`", text)) & paid
