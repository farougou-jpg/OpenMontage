"""Lot 1.6 — aucun événement de test écrit dans les vrais projets.

Le préfixe « zz » fait passer ce test après les autres tests du dossier studio,
dont ceux qui vérifient le refus des zones protégées de `projects/demos/`.
"""

from __future__ import annotations

from pathlib import Path

from lib.studio.narration.tool import PiperFrNarration
from lib.studio.qc import QualityControlTool
from lib.studio.storyboard import StoryboardTool

REPO = Path(__file__).resolve().parents[2]
DEMOS = REPO / "projects" / "demos"


def test_protected_zone_refusals_do_not_write_project_events(isolated_project_events):
    target = DEMOS / "fr-series" / "code-to-screen"
    PiperFrNarration().execute({"mode": "mesure", "script": {}, "project_dir": str(target)})
    StoryboardTool().execute({"props": {"theme": "x", "cuts": []}, "project_dir": str(target)})
    QualityControlTool().execute({"mp4": str(target / "code-to-screen-fr.mp4"), "props": {}, "timing": [],
                                  "project_dir": str(target)})
    assert not (DEMOS / "events.jsonl").exists()
    assert not str(isolated_project_events).startswith(str(REPO))  # journal isolé, hors dépôt


def test_no_events_file_in_demos_after_studio_tests():
    assert not (DEMOS / "events.jsonl").exists(), "un test a écrit dans projects/demos/events.jsonl"


STUDIO_OUTPUT_PATTERNS = ("events.jsonl", "studio_project.json", "publication_qc.json",
                          "exports/v[0-9][0-9][0-9]", "controle/v[0-9][0-9][0-9]",
                          "storyboard/v[0-9][0-9][0-9]", "assets/narration/v[0-9][0-9][0-9]")


def test_no_studio_output_in_protected_demos():
    """Zone protégée : jamais d'events.jsonl ni de sortie du studio dans projects/demos/."""
    traces = [p for pattern in STUDIO_OUTPUT_PATTERNS for p in DEMOS.rglob(pattern)]
    assert not traces, f"sorties du studio dans projects/demos/ : {traces}"


def test_studio_tests_did_not_touch_projects(projects_snapshot_before_studio_tests):
    """Aucun test du studio n'a créé, modifié ou supprimé un fichier de projects/.

    Comparaison chemins + SHA-256 entre le début de la session de tests du studio et
    maintenant. Les vrais projets (ex. pilote) existants avant les tests sont admis ;
    toute écriture faite PENDANT les tests est détectée.
    """
    from tests.studio.conftest import snapshot_projects
    before, after = projects_snapshot_before_studio_tests, snapshot_projects()
    created = sorted(set(after) - set(before))
    deleted = sorted(set(before) - set(after))
    modified = sorted(p for p in before.keys() & after.keys() if before[p] != after[p])
    assert not created, f"fichiers créés dans projects/ pendant les tests : {created}"
    assert not deleted, f"fichiers supprimés de projects/ pendant les tests : {deleted}"
    assert not modified, f"fichiers modifiés dans projects/ pendant les tests : {modified}"
    assert before, "instantané vide : projects/ introuvable"
