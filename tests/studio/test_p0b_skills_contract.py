"""Lot P0-B — contrat des skills studio-fr : initialisation et validations sur l'artefact exact.

Vérifie le texte réellement lu par l'agent : ordre des appels, règle de l'accord explicite,
et existence réelle (avec la bonne signature) de chaque fonction Studio citée.
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path

import pytest

from lib.studio import project as prj
from lib.studio import validations as val

REPO = Path(__file__).resolve().parents[2]
SKILLS = REPO / "skills" / "pipelines" / "studio-fr"


def _text(name: str) -> str:
    return (SKILLS / name).read_text(encoding="utf-8")


def _in_order(text: str, *tokens: str) -> bool:
    positions = [text.find(t) for t in tokens]
    return all(p >= 0 for p in positions) and positions == sorted(positions)


def test_initialisation_order_in_executive_producer_and_idea_director():
    ep = _text("executive-producer.md")
    section = ep[ep.index("## Initialisation du projet Studio"):ep.index("## Validations humaines")]
    assert _in_order(section, "prj.create_project(", "prj.register_with_backlot(", "python -m backlot open",
                     "write_checkpoint(")
    idea = _text("idea-director.md")
    assert _in_order(idea, "prj.create_project(", "prj.register_with_backlot(", "python -m backlot open",
                     "checkpoint `idea`")


def test_init_project_never_instructed_directly():
    for path in sorted(SKILLS.glob("*.md")):
        for para in re.split(r"\n\s*\n", path.read_text(encoding="utf-8")):
            if "init_project" in para:
                assert re.search(r"ne jamais appeler `init_project`|remplace l'appel direct", para), \
                    f"{path.name}: {para[:160]}"


def test_executive_producer_states_exact_artifact_rule():
    ep = " ".join(_text("executive-producer.md").split())
    for token in ("Validation = artefact exact", "empreinte SHA-256", "Seul un accord explicite compte",
                  "sans aucune écriture intermédiaire", "empreinte_presentee=shown[\"empreinte\"]",
                  "accord_utilisateur=\"<mots exacts de l'utilisateur, sans reformulation>\"",
                  "ne jamais recalculer l'empreinte pour forcer", "human_approved=True",
                  "Ne jamais valider à sa place"):
        assert token in ep, token


@pytest.mark.parametrize("name,steps", [
    ("script-director.md", ("prj.write_script(", 'val.presentation(project_dir, "scenario")',
                            "Attendre l'accord explicite", "val.validate_script(", "human_approved=True")),
    ("scene-director.md", ("StoryboardTool", 'val.presentation(project_dir, "storyboard"',
                           "# … présentation, accord explicite", "val.validate_storyboard(")),
])
def test_stage_skills_present_then_validate_exact_artifact(name, steps):
    text = _text(name)
    assert _in_order(text, *steps), name
    assert "empreinte_presentee=shown[\"empreinte\"]" in text
    assert "<mots exacts de l'utilisateur>" in text


def test_every_studio_function_cited_by_skills_exists_with_expected_parameters():
    cited = {"prj": set(), "val": set()}
    for path in sorted(SKILLS.glob("*.md")):
        for mod, fn in re.findall(r"\b(prj|val)\.([a-z_]+)\(", path.read_text(encoding="utf-8")):
            cited[mod].add(fn)
    assert {"create_project", "register_with_backlot", "write_script"} <= cited["prj"]
    assert {"presentation", "validate_script", "validate_storyboard"} <= cited["val"]
    for fn in cited["prj"]:
        assert callable(getattr(prj, fn, None)), f"prj.{fn} absent"
    for fn in cited["val"]:
        assert callable(getattr(val, fn, None)), f"val.{fn} absent"
    for fn in (val.validate_script, val.validate_storyboard, val.validate_narration, val.validate_render):
        params = inspect.signature(fn).parameters
        for p in ("empreinte_presentee", "accord_utilisateur"):
            assert params[p].kind is inspect.Parameter.KEYWORD_ONLY, (fn.__name__, p)


def test_skill_example_sequence_really_works(tmp_path):
    """La séquence décrite par les skills, exécutée telle quelle, valide le scénario présenté."""
    project_dir = prj.create_project("contrat-skills", "Contrat", "Une idée.", 15, root=tmp_path / "projects")
    prj.register_with_backlot(project_dir)
    script = {"version": "1.0", "title": "Contrat", "total_duration_seconds": 15, "sections": [
        {"id": "un", "text": "Trop de réunions.", "start_seconds": 0, "end_seconds": 15}]}
    res = prj.write_script(project_dir, script)
    shown = val.presentation(project_dir, "scenario")
    e = val.validate_script(project_dir, empreinte_presentee=shown["empreinte"],
                            accord_utilisateur="Oui, c'est parfait, je valide le scénario.")
    assert e["empreintes"] == shown["fichiers"] and res["artefact"] == script
    assert val.is_current(project_dir, "scenario")[0] is True
