"""Étape G0 — socle de l'interface : projets, validations, rendu, file de tâches, export.

Aucun rendu, aucune synthèse ni aucun accès réseau : les projets sont créés dans le dossier
temporaire de pytest, le rendu passe par un `runner` simulé, le contrôle qualité par un outil
simulé. Le pilote et les vidéos françaises ne sont lus qu'en lecture seule.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from pathlib import Path

import pytest

from tools.base_tool import ToolResult

from lib.studio import export_package as exp
from lib.studio import project as prj
from lib.studio import render as ren
from lib.studio import validations as val
from lib.studio.jobs import CANCELLED, DONE, FAILED, JobBusyError, JobQueue
from lib.studio.narration.tool import PROJECTS_ROOT, PathPolicyError
from lib.studio.storyboard.stills import FR_CONFIG_V3, FR_CONFIG_V4

PILOT = PROJECTS_ROOT / "pilote-gestion-temps"
SCRIPT = {
    "version": "1.0", "title": "Projet test G0", "total_duration_seconds": 15,
    "sections": [
        {"id": "un", "text": "Trop de réunions.", "start_seconds": 0, "end_seconds": 7},
        {"id": "deux", "text": "Inscrivez-vous dès maintenant.", "start_seconds": 7, "end_seconds": 15},
    ],
}
FAKE_MP4 = b"\x00\x00\x00\x18ftypmp42" + b"G0-video-simulee" * 64


def sha(p: Path) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def tree(root: Path) -> dict[str, str]:
    return {f.relative_to(root).as_posix(): sha(f) for f in sorted(root.rglob("*")) if f.is_file()}


@pytest.fixture(autouse=True)
def no_real_process(monkeypatch):
    """Aucun processus réel (Remotion, ffmpeg) ne peut être lancé par le socle pendant ces tests."""
    def refuse(*_a, **_k):
        raise AssertionError("processus réel interdit dans les tests G0")
    monkeypatch.setattr(ren.subprocess, "Popen", refuse)
    monkeypatch.setattr(ren.subprocess, "run", refuse)


# ---- projet de test complet (dans tmp_path) ----

def new_project(tmp_path: Path, slug: str = "projet-test") -> Path:
    return prj.create_project(slug, "Projet test", "Une idée de test.", 15, root=tmp_path / "projects")


def add_script(p: Path) -> None:
    (p / "script.json").write_bytes(json.dumps(SCRIPT, ensure_ascii=False, indent=2).encode("utf-8"))


def add_storyboard(p: Path, version: str = "v001", config: str = FR_CONFIG_V4) -> None:
    d = p / "storyboard" / version
    (d / "scenes").mkdir(parents=True)
    prj.write_json(d / "storyboard.json", {"configuration_rendu": config, "scenes": 2})
    prj.write_json(d / "props_storyboard.json", {"theme": "clean-professional", "cuts": [
        {"id": "un", "type": "hero_title", "text": "Trop de réunions", "in_seconds": 0, "out_seconds": 7},
        {"id": "deux", "type": "hero_title", "text": "Inscrivez-vous", "in_seconds": 7, "out_seconds": 15}],
        "overlays": []})
    (d / "scenes" / "scene_01.png").write_bytes(b"png-1")
    (d / "scenes" / "scene_02.png").write_bytes(b"png-2")


def add_narration(p: Path, audio_root: Path, version: str = "v001", conforme: bool = True) -> None:
    d = p / "assets" / "narration" / version
    (d / "controle").mkdir(parents=True)
    (d / "narration_fr.wav").write_bytes(b"RIFF-narration-" + version.encode())
    prj.write_json(d / "timing_fr.json", [{"cut": "un", "debut": 0.4, "fin": 2.0}])
    prj.write_json(d / "controle" / "rapport_narration.json", {"conforme": conforme, "profil": "B"})
    pub = audio_root / p.name / version
    pub.mkdir(parents=True)
    (pub / "narration_fr.wav").write_bytes((d / "narration_fr.wav").read_bytes())


def fake_runner(content: bytes = FAKE_MP4, code: int = 0):
    calls = []

    def run(cmd, cwd, on_line, cancel):
        calls.append(cmd)
        out = Path(cmd[5])
        on_line("Rendered 930/930")
        if content:
            out.write_bytes(content)
        return code
    run.calls = calls
    return run


def add_qc_report(p: Path, render_version: str, qc_version: str = "v001", conforme: bool = True) -> Path:
    mp4 = p / "renders" / render_version / ren.OUTPUT_NAME
    d = p / "controle" / qc_version
    d.mkdir(parents=True)
    prj.write_json(d / "rapport_qc.json", {"conforme": conforme, "bloquants": [] if conforme else ["x"],
                                           "avertissements": [],
                                           "mp4": {"sha256": sha(mp4), "taille": mp4.stat().st_size}})
    (d / "rapport_qc.md").write_bytes("# Rapport simulé\n".encode("utf-8"))
    return d


def validated_until_narration(tmp_path: Path) -> tuple[Path, Path]:
    p, audio = new_project(tmp_path), tmp_path / "audio_studio"
    add_script(p); val.validate_script(p)
    add_storyboard(p); val.validate_storyboard(p, "v001")
    add_narration(p, audio); val.validate_narration(p, "v001", studio_audio_root=audio)
    return p, audio


def rendered_and_validated(tmp_path: Path) -> tuple[Path, Path]:
    p, audio = validated_until_narration(tmp_path)
    plan = ren.prepare_render(p, studio_audio_root=audio)
    ren.run_render(plan, runner=fake_runner())
    add_qc_report(p, "v001")
    val.validate_render(p, "v001", "v001")
    return p, audio


# ---- projets ----



def test_write_requires_a_valid_studio_identity(tmp_path):
    project = tmp_path / "projects" / "projet-test"
    project.mkdir(parents=True)
    # Un marqueur présent mais non lié au dossier ne constitue pas une identité.
    prj.write_json(project / "studio_project.json", {
        "studio": "OpenMontage Studio", "version": 1,
        "projet": "autre-projet", "pipeline": "studio-fr"
    })
    with pytest.raises(prj.ProjectLockedError, match="Identité Studio invalide"):
        prj.require_writable(project)

    prj.write_json(project / "studio_project.json", {
        "studio": "OpenMontage Studio", "version": 1,
        "projet": project.name, "pipeline": "studio-fr"
    })
    assert prj.require_writable(project) == project.resolve()


def test_create_project_defaults(tmp_path):
    p = new_project(tmp_path)
    meta = json.loads((p / "studio_project.json").read_text(encoding="utf-8"))
    assert meta["studio"] == "OpenMontage Studio" and meta["duree_s"] == 15 and meta["pipeline"] == "studio-fr"
    assert prj.project_settings(p)["profil_narration"] == "B"                      # D5
    assert prj.project_settings(p)["configuration_rendu"] == FR_CONFIG_V4
    assert prj.narration_request(p)["profil"] == "B"
    assert json.loads((p / "validations.json").read_text(encoding="utf-8"))["validations"] == []
    assert b"\r\n" not in (p / "studio_project.json").read_bytes()
    st = prj.project_state(p)
    assert st["prochaine_etape"] == "scenario" and not st["verrouille"]
    assert prj.resume_point(p)["action"] == "scenario"


@pytest.mark.parametrize("slug", ["", "AB", "a", "x" * 70, "-abc", "abc-", "a--b", "a/b", "../x", "pilote-gestion-temps",
                                  "demos", "été-1"])
def test_bad_or_reserved_slugs(tmp_path, slug):
    with pytest.raises(prj.ProjectError):
        prj.create_project(slug, "T", "I", 30, root=tmp_path)


def test_create_refusals(tmp_path):
    new_project(tmp_path)
    with pytest.raises(prj.ProjectError, match="existe déjà"):
        new_project(tmp_path)
    for kwargs in ({"duration_s": 45}, {"title": " "}, {"idea": ""}):
        args = {"slug": "autre-projet", "title": "T", "idea": "I", "duration_s": 30, **kwargs}
        with pytest.raises(prj.ProjectError):
            prj.create_project(root=tmp_path, **args)
    with pytest.raises(PathPolicyError):
        prj.create_project("nouveau", "T", "I", 30, root=PROJECTS_ROOT / "demos")
    assert not (PROJECTS_ROOT / "demos" / "nouveau").exists()


def test_pilot_and_french_videos_locked_and_read_only():
    before = tree(PILOT)
    assert prj.lock_reason(PILOT) and prj.is_locked(PROJECTS_ROOT / "demos" / "fr-series")
    for target in (PILOT, PROJECTS_ROOT / "demos" / "fr-series" / "code-to-screen"):
        with pytest.raises(prj.ProjectLockedError):
            prj.require_writable(target)
    st = prj.project_state(PILOT)
    assert st["verrouille"] and st["termine"] and st["etapes"]["export"]["statut"] == "fait"
    assert prj.resume_point(PILOT)["action"] == "consultation"
    assert "pilote-gestion-temps" in [s["projet"] for s in prj.list_projects()]
    assert not [s for s in prj.list_projects() if s["projet"] == "demos"]
    with pytest.raises(prj.ProjectLockedError):
        val.validate_script(PILOT)
    with pytest.raises(prj.ProjectLockedError):
        exp.export_package(PILOT, "x.mp4", "T")
    assert tree(PILOT) == before


# ---- état d'avancement : validité actuelle, ancien format, date d'activité ----

def test_state_distinguishes_historical_validation_from_current_validity(tmp_path):
    p, _ = validated_until_narration(tmp_path)
    steps = prj.project_state(p)["etapes"]
    for name in ("scenario", "storyboard", "narration"):
        assert steps[name]["statut"] == "fait"
        assert steps[name]["a_jour"] is True and steps[name]["verification"] == "à jour"
    for name in ("projet", "rendu", "controle", "validation_rendu", "export"):
        assert steps[name]["a_jour"] is None and steps[name]["verification"] is None
    assert "origine" not in steps["narration"]

    (p / "script.json").write_bytes((p / "script.json").read_bytes() + b" ")
    steps = prj.project_state(p)["etapes"]
    # La validation reste inscrite (historique) mais n'est plus valide aujourd'hui.
    assert steps["scenario"]["statut"] == "fait" and steps["scenario"]["a_jour"] is False
    assert "modifié depuis la validation 1" in steps["scenario"]["verification"]
    assert steps["storyboard"]["a_jour"] is True


def test_pilot_legacy_sound_reference_shown_as_narration_without_changing_rules():
    before = tree(PILOT)
    steps = prj.project_state(PILOT)["etapes"]
    assert steps["narration"]["statut"] == "fait" and "ancien format" in steps["narration"]["origine"]
    # Validations historiques sans empreintes : jamais présentées comme vérifiées.
    for name in ("scenario", "storyboard", "narration", "validation_rendu"):
        assert steps[name]["a_jour"] is False and "sans empreintes" in steps[name]["verification"]
    # Règles inchangées : aucune validation « narration » n'est créée ni reconnue.
    assert "narration" not in val.validations_by_kind(PILOT)
    assert val.is_current(PILOT, "narration") == (False, "narration française non validé")
    assert tree(PILOT) == before


def test_last_modified_includes_latest_versioned_folders_only(tmp_path):
    p = new_project(tmp_path)
    for f in (p / "studio_project.json", p / "validations.json"):
        os.utime(f, (1_000_000, 1_000_000))
    (p / "storyboard" / "v001").mkdir(parents=True)
    (p / "storyboard" / "v002").mkdir()
    (p / "storyboard" / "brouillon").mkdir()                 # non versionné : ignoré
    os.utime(p / "storyboard" / "v001", (3_000_000, 3_000_000))
    os.utime(p / "storyboard" / "v002", (2_000_000, 2_000_000))
    os.utime(p / "storyboard" / "brouillon", (4_000_000, 4_000_000))
    os.utime(p / "storyboard", (4_000_000, 4_000_000))
    from datetime import datetime, timezone
    expected = datetime.fromtimestamp(2_000_000, timezone.utc).isoformat()   # dernière version = v002
    assert prj.project_state(p)["modifie_le"] == expected


# ---- utilitaires du socle ----

def test_check_slug_accepts_valid_identifiers():
    for slug in ("abc", "pub-30s", "a1-b2-c3", "x" * 61):
        assert prj.check_slug(slug) == slug


def test_versions_and_latest_version_keep_only_vnnn_folders(tmp_path):
    root = tmp_path / "renders"
    assert prj.versions(root) == [] and prj.latest_version(root) is None
    for name in ("v002", "v010", "v001", "v1", "v0001", "essais"):
        (root / name).mkdir(parents=True)
    (root / "v003").write_bytes(b"fichier, pas un dossier")
    assert prj.versions(root) == ["v001", "v002", "v010"]
    assert prj.latest_version(root) == "v010"


def test_is_studio_project_identity_and_legacy_fallback(tmp_path):
    assert prj.is_studio_project(new_project(tmp_path, "projet-neuf"))
    legacy = tmp_path / "ancien"
    legacy.mkdir()
    prj.write_json(legacy / "validations.json", {"projet": "ancien", "pipeline": "studio-fr", "validations": []})
    assert prj.is_studio_project(legacy)                      # ancien format, sans marqueur
    other = tmp_path / "autre"
    other.mkdir()
    prj.write_json(other / "validations.json", {"projet": "ancien", "pipeline": "studio-fr", "validations": []})
    assert not prj.is_studio_project(other)                   # nom de dossier différent
    prj.write_json(other / "validations.json", {"projet": "autre", "pipeline": "explainer", "validations": []})
    assert not prj.is_studio_project(other)                   # autre pipeline
    assert not prj.is_studio_project(tmp_path / "absent")


def test_mark_studio_project_never_creates_identity(tmp_path):
    from lib.studio.qc.tool import mark_studio_project
    p = new_project(tmp_path)
    assert mark_studio_project(p) == p.resolve() / "studio_project.json"
    bare = tmp_path / "sans-identite"
    bare.mkdir()
    with pytest.raises(prj.ProjectLockedError, match="Identité Studio absente"):
        mark_studio_project(bare)
    assert list(bare.iterdir()) == []


# ---- P0-A : enregistrement Backlot ----

def studio_files(p: Path) -> dict[str, bytes]:
    return {n: (p / n).read_bytes() for n in ("studio_project.json", "validations.json")}


def dirs_of(root: Path) -> set[str]:
    return {d.relative_to(root).as_posix() for d in root.rglob("*") if d.is_dir()}


def backlot_layout(tmp_path: Path) -> set[str]:
    """Arborescence de référence : ce que lib.checkpoint.init_project crée réellement (jamais recopiée)."""
    from lib.checkpoint import init_project
    return dirs_of(init_project("reference", title="R", pipeline_type="studio-fr",
                                pipeline_dir=tmp_path / "reference"))


def test_register_with_backlot_aligns_identities(tmp_path):
    p = new_project(tmp_path)
    before = studio_files(p)
    assert prj.register_with_backlot(p) == p.resolve()
    marker = json.loads((p / "project.json").read_text(encoding="utf-8"))
    meta = json.loads((p / "studio_project.json").read_text(encoding="utf-8"))
    assert marker["project_id"] == p.name and marker["pipeline_type"] == "studio-fr"
    assert marker["title"] == meta["titre"] and marker["created_at"] == meta["cree_le"]
    assert dirs_of(p) == backlot_layout(tmp_path)           # arborescence = celle d'init_project
    assert studio_files(p) == before                      # identité Studio intacte
    assert prj.require_writable(p) == p.resolve()
    assert not list(p.glob("checkpoint_*.json"))          # aucun checkpoint créé


def test_register_with_backlot_is_idempotent(tmp_path):
    p = new_project(tmp_path)
    prj.register_with_backlot(p)
    first = (p / "project.json").read_bytes()
    created = json.loads(first)["created_at"]
    prj.register_with_backlot(p)
    assert (p / "project.json").read_bytes() == first
    assert json.loads((p / "project.json").read_bytes())["created_at"] == created


def test_register_refused_on_locked_or_unidentified_projects_without_writing(tmp_path):
    for target in (PILOT, PROJECTS_ROOT / "demos" / "fr-series"):
        before = tree(target)
        with pytest.raises(prj.ProjectLockedError):
            prj.register_with_backlot(target)
        assert tree(target) == before
        assert not (target / "project.json").exists()
    exported, _ = rendered_and_validated(tmp_path)
    exp.export_package(exported, "film.mp4", "Projet test")
    before = tree(exported)
    with pytest.raises(prj.ProjectLockedError, match="exporté"):
        prj.register_with_backlot(exported)
    assert tree(exported) == before and not (exported / "project.json").exists()
    bare = tmp_path / "projects" / "sans-identite"
    bare.mkdir(parents=True)
    with pytest.raises(prj.ProjectLockedError):
        prj.register_with_backlot(bare)
    assert list(bare.iterdir()) == []


@pytest.mark.parametrize("field,value", [("created_at", "2000-01-01T00:00:00+00:00"),
                                         ("project_id", "autre-projet"), ("pipeline_type", "explainer"),
                                         ("title", "Autre titre")])
def test_register_never_overwrites_contradictory_project_json(tmp_path, field, value):
    p = new_project(tmp_path)
    meta = json.loads((p / "studio_project.json").read_text(encoding="utf-8"))
    marker = {"version": "1.0", "project_id": p.name, "title": meta["titre"], "pipeline_type": "studio-fr",
              "created_at": meta["cree_le"], field: value}
    (p / "project.json").write_bytes(json.dumps(marker).encode("utf-8"))
    before = tree(p)
    with pytest.raises(prj.ProjectError, match=f"contradictoire \\({field}\\)"):
        prj.register_with_backlot(p)
    assert tree(p) == before and not (p / "artifacts").exists()


@pytest.mark.parametrize("raw", [b"{bad", b"[]", b"\xff\xfe"])
def test_register_refuses_unreadable_project_json(tmp_path, raw):
    p = new_project(tmp_path)
    (p / "project.json").write_bytes(raw)
    with pytest.raises(prj.ProjectError, match="jamais réinitialisé"):
        prj.register_with_backlot(p)
    assert (p / "project.json").read_bytes() == raw and not (p / "artifacts").exists()


def test_register_refuses_inconsistent_studio_identity(tmp_path):
    p = new_project(tmp_path)
    meta = json.loads((p / "studio_project.json").read_text(encoding="utf-8"))
    prj.write_json(p / "studio_project.json", {k: v for k, v in meta.items() if k != "cree_le"})
    with pytest.raises(prj.ProjectError, match="cree_le"):
        prj.register_with_backlot(p)
    prj.write_json(p / "studio_project.json", meta)
    vals = json.loads((p / "validations.json").read_text(encoding="utf-8"))
    prj.write_json(p / "validations.json", {**vals, "titre": "Titre divergent"})
    with pytest.raises(prj.ProjectError, match="validations.json"):
        prj.register_with_backlot(p)
    assert not (p / "project.json").exists()


def _failing_init(real, *, corrupt_marker: bool):
    """init_project qui crée réellement le dossier, puis échoue (après avoir abîmé le marqueur)."""
    def fail(project_id, *, title, pipeline_type, pipeline_dir=None, style_playbook=None, series=None):
        real(project_id, title=title, pipeline_type=pipeline_type, pipeline_dir=pipeline_dir)
        if corrupt_marker:
            (Path(pipeline_dir) / project_id / "project.json").write_bytes(b"{tronque")
        raise RuntimeError("échec simulé d'init_project")
    return fail


def test_register_rollback_when_init_project_fails_on_new_project(tmp_path, monkeypatch):
    import lib.checkpoint as ckpt
    p = new_project(tmp_path)
    before = tree(p)
    dirs_before = sorted(x.relative_to(p).as_posix() for x in p.rglob("*") if x.is_dir())
    monkeypatch.setattr(ckpt, "init_project", _failing_init(ckpt.init_project, corrupt_marker=True))
    with pytest.raises(RuntimeError, match="échec simulé"):
        prj.register_with_backlot(p)
    assert tree(p) == before                               # aucun project.json partiel
    assert sorted(x.relative_to(p).as_posix() for x in p.rglob("*") if x.is_dir()) == dirs_before
    assert prj.require_writable(p) == p.resolve()          # projet Studio intact, réessayable
    monkeypatch.undo()
    prj.register_with_backlot(p)
    assert json.loads((p / "project.json").read_bytes())["project_id"] == p.name


def test_register_rollback_restores_previous_marker_and_keeps_existing_files(tmp_path, monkeypatch):
    import lib.checkpoint as ckpt
    layout = backlot_layout(tmp_path)                      # référence calculée avant la simulation
    p = new_project(tmp_path)
    prj.register_with_backlot(p)
    (p / "renders" / "note.txt").write_bytes(b"fichier existant")
    before = tree(p)
    monkeypatch.setattr(ckpt, "init_project", _failing_init(ckpt.init_project, corrupt_marker=True))
    with pytest.raises(RuntimeError):
        prj.register_with_backlot(p)
    assert tree(p) == before                               # marqueur restauré octet pour octet
    assert layout <= dirs_of(p)                            # dossiers préexistants conservés


def test_register_rollback_when_marker_inconsistent_after_init(tmp_path, monkeypatch):
    import lib.checkpoint as ckpt
    real = ckpt.init_project
    p = new_project(tmp_path)
    before = tree(p)

    def drifting(project_id, *, title, pipeline_type, pipeline_dir=None, style_playbook=None, series=None):
        out = real(project_id, title=title, pipeline_type=pipeline_type, pipeline_dir=pipeline_dir)
        m = Path(pipeline_dir) / project_id / "project.json"
        m.write_text(json.dumps({**json.loads(m.read_text(encoding="utf-8")), "created_at": "autre"}),
                     encoding="utf-8")
        return out
    monkeypatch.setattr(ckpt, "init_project", drifting)
    with pytest.raises(prj.ProjectError, match="incohérent"):
        prj.register_with_backlot(p)
    assert tree(p) == before and not (p / "artifacts").exists()


def test_rollback_removes_what_init_created_without_hardcoded_layout(tmp_path, monkeypatch):
    """D3 : le retour arrière constate les dossiers créés (même inconnus), sans liste recopiée."""
    import lib.checkpoint as ckpt
    real = ckpt.init_project
    p = new_project(tmp_path)
    (p / "assets" / "narration").mkdir(parents=True)          # préexistant : doit rester
    (p / "assets" / "narration" / "garder.txt").write_bytes(b"x")
    before, dirs_before = tree(p), dirs_of(p)

    def init_with_new_layout(project_id, *, title, pipeline_type, pipeline_dir=None, style_playbook=None,
                             series=None):
        real(project_id, title=title, pipeline_type=pipeline_type, pipeline_dir=pipeline_dir)
        (Path(pipeline_dir) / project_id / "futur" / "dossier").mkdir(parents=True)   # évolution simulée
        raise RuntimeError("échec simulé")
    monkeypatch.setattr(ckpt, "init_project", init_with_new_layout)
    with pytest.raises(RuntimeError, match="échec simulé"):
        prj.register_with_backlot(p)
    assert dirs_of(p) == dirs_before and tree(p) == before
    assert not hasattr(prj, "BACKLOT_LAYOUT_DIRS")


def test_rollback_failure_on_new_marker_is_reported_and_original_kept(tmp_path, monkeypatch):
    """D1 : project.json créé par l'appel mais impossible à retirer → erreur explicite, origine identifiable."""
    import lib.checkpoint as ckpt
    p = new_project(tmp_path)
    monkeypatch.setattr(ckpt, "init_project", _failing_init(ckpt.init_project, corrupt_marker=False))
    real_unlink = Path.unlink

    def locked_unlink(self, *a, **k):
        if self.name == "project.json":
            raise PermissionError("fichier verrouillé (simulé)")
        return real_unlink(self, *a, **k)
    monkeypatch.setattr(Path, "unlink", locked_unlink)
    with pytest.raises(prj.RegistrationRollbackError, match="retour arrière incomplet") as info:
        prj.register_with_backlot(p)
    err = info.value
    assert isinstance(err.original, RuntimeError) and "échec simulé" in str(err.original)
    assert err.__cause__ is err.original and "RuntimeError" in str(err)
    assert any("n'a pas pu être retiré" in pb for pb in err.problems)
    assert isinstance(err, prj.ProjectError)                  # jamais un succès
    monkeypatch.undo()
    # Reprise : un nouvel appel refait la vérification complète avant d'accepter.
    prj.register_with_backlot(p)
    assert dirs_of(p) == backlot_layout(tmp_path)


def test_rollback_failure_on_existing_marker_never_presented_as_valid(tmp_path, monkeypatch):
    """D1 : marqueur préexistant abîmé et non restaurable → erreur explicite ; ensuite refus « illisible »."""
    import lib.checkpoint as ckpt
    p = new_project(tmp_path)
    prj.register_with_backlot(p)
    monkeypatch.setattr(ckpt, "init_project", _failing_init(ckpt.init_project, corrupt_marker=True))

    def no_write(*_a, **_k):
        raise OSError("disque en lecture seule (simulé)")
    monkeypatch.setattr(prj, "_atomic_write_bytes", no_write)
    with pytest.raises(prj.RegistrationRollbackError) as info:
        prj.register_with_backlot(p)
    assert isinstance(info.value.original, RuntimeError)
    assert any("restauration de project.json impossible" in pb for pb in info.value.problems)
    monkeypatch.undo()
    with pytest.raises(prj.ProjectError, match="illisible"):  # état abîmé : jamais accepté
        prj.register_with_backlot(p)


def test_leftover_dirs_are_noted_without_changing_the_original_error(tmp_path, monkeypatch):
    import lib.checkpoint as ckpt
    p = new_project(tmp_path)
    monkeypatch.setattr(ckpt, "init_project", _failing_init(ckpt.init_project, corrupt_marker=False))
    real_rmdir = Path.rmdir

    def busy_rmdir(self):
        if self.name == "renders":
            raise PermissionError("dossier occupé (simulé)")
        return real_rmdir(self)
    monkeypatch.setattr(Path, "rmdir", busy_rmdir)
    with pytest.raises(RuntimeError, match="échec simulé") as info:   # type d'origine conservé
        prj.register_with_backlot(p)
    assert any("renders" in n for n in getattr(info.value, "__notes__", []))
    assert not (p / "project.json").exists()                 # marqueur bien retiré


def test_interruption_is_never_converted_even_if_rollback_fails(tmp_path, monkeypatch):
    import lib.checkpoint as ckpt
    real = ckpt.init_project
    p = new_project(tmp_path)

    def interrupted(project_id, *, title, pipeline_type, pipeline_dir=None, style_playbook=None, series=None):
        real(project_id, title=title, pipeline_type=pipeline_type, pipeline_dir=pipeline_dir)
        raise KeyboardInterrupt("arrêt demandé")
    monkeypatch.setattr(ckpt, "init_project", interrupted)
    monkeypatch.setattr(prj, "_rollback_registration", lambda *a, **k: (["project.json non retiré"], []))
    with pytest.raises(KeyboardInterrupt) as info:
        prj.register_with_backlot(p)
    assert any("Retour arrière incomplet" in n for n in info.value.__notes__)


def test_create_project_refuses_folder_initialised_by_backlot_first(tmp_path):
    from lib.checkpoint import init_project
    init_project("ordre-inverse", title="T", pipeline_type="studio-fr", pipeline_dir=tmp_path / "projects")
    with pytest.raises(prj.ProjectError, match="existe déjà"):
        prj.create_project("ordre-inverse", "T", "I", 15, root=tmp_path / "projects")


# ---- P0-A : écriture du scénario ----

def test_write_script_persists_lf_and_returns_exact_artifact(tmp_path):
    p = new_project(tmp_path)
    res = prj.write_script(p, SCRIPT)
    raw = (p / "script.json").read_bytes()
    assert b"\r\n" not in raw and json.loads(raw.decode("utf-8")) == res["artefact"] == SCRIPT
    assert res["sha256"] == sha(p / "script.json") and res["sections"] == 2
    assert res["modifie"] is True and res["validation_scenario_perimee"] is False
    res["artefact"]["title"] = "modifié"                      # copie : le fichier ne bouge pas
    assert json.loads((p / "script.json").read_bytes())["title"] == SCRIPT["title"]
    assert not list(p.glob("checkpoint_*.json")) and not (p / "project.json").exists()
    assert "scenario" not in val.validations_by_kind(p)       # aucune validation simulée


def test_write_script_rejects_invalid_content_without_writing(tmp_path):
    p = new_project(tmp_path)
    with pytest.raises(prj.ProjectError, match="schéma"):
        prj.write_script(p, {k: v for k, v in SCRIPT.items() if k != "sections"})
    with pytest.raises(prj.ProjectError, match="Durée du scénario"):
        prj.write_script(p, {**SCRIPT, "total_duration_seconds": 30})
    (tmp_path / "illisible.json").write_bytes(b"{bad")
    with pytest.raises(prj.ProjectError, match="illisible"):
        prj.write_script(p, tmp_path / "illisible.json")
    assert not (p / "script.json").exists()


def test_write_script_identical_content_is_not_rewritten(tmp_path):
    p = new_project(tmp_path)
    prj.write_script(p, SCRIPT)
    os.utime(p / "script.json", (1_000_000, 1_000_000))
    raw = (p / "script.json").read_bytes()
    res = prj.write_script(p, json.loads(json.dumps(SCRIPT)))
    assert res["modifie"] is False and res["validation_scenario_perimee"] is False
    assert (p / "script.json").read_bytes() == raw and (p / "script.json").stat().st_mtime == 1_000_000


def test_write_script_failure_never_destroys_previous_script(tmp_path, monkeypatch):
    p = new_project(tmp_path)
    prj.write_script(p, SCRIPT)
    before = (p / "script.json").read_bytes()

    def broken_replace(*_a, **_k):
        raise OSError("disque plein (simulé)")
    monkeypatch.setattr(prj.os, "replace", broken_replace)
    changed = {**SCRIPT, "title": "Version 2"}
    with pytest.raises(OSError, match="disque plein"):
        prj.write_script(p, changed)
    assert (p / "script.json").read_bytes() == before
    assert not list(p.glob(".script.json.*.tmp"))            # aucun fichier temporaire laissé


def test_script_change_after_validation_1_invalidates_it(tmp_path):
    p = new_project(tmp_path)
    prj.write_script(p, SCRIPT)
    val.validate_script(p)
    add_storyboard(p)
    changed = json.loads(json.dumps(SCRIPT))
    changed["sections"][0]["text"] = "Beaucoup trop de réunions."
    res = prj.write_script(p, changed)
    assert res["modifie"] is True and res["validation_scenario_perimee"] is True
    assert val.is_current(p, "scenario")[0] is False
    assert prj.project_state(p)["etapes"]["scenario"]["a_jour"] is False
    with pytest.raises(val.ValidationError, match="modifié depuis la validation 1"):
        val.validate_storyboard(p, "v001")
    e = val.validate_script(p)                                # nouvelle validation explicite
    assert e["remplace"] == 1 and val.is_current(p, "scenario")[0] is True
    assert val.validate_storyboard(p, "v001")["numero"] == 3


@pytest.mark.parametrize("stage", ["storyboard", "narration", "rendu"])
def test_validations_2_3_4_forbid_script_rewrite(tmp_path, stage):
    if stage == "rendu":
        p, _ = rendered_and_validated(tmp_path)
    elif stage == "narration":
        p, _ = validated_until_narration(tmp_path)
    else:
        p = new_project(tmp_path)
        add_script(p); val.validate_script(p); add_storyboard(p); val.validate_storyboard(p, "v001")
    assert stage in val.validations_by_kind(p)
    before = tree(p)
    with pytest.raises(prj.ProjectError, match="déjà validée"):
        prj.write_script(p, {**SCRIPT, "title": "Réécriture interdite"})
    assert tree(p) == before


def test_write_script_refused_on_locked_or_unidentified_projects(tmp_path):
    for target in (PILOT, PROJECTS_ROOT / "demos" / "fr-series"):
        before = tree(target)
        with pytest.raises(prj.ProjectLockedError):
            prj.write_script(target, SCRIPT)
        assert tree(target) == before
    bare = tmp_path / "projects" / "sans-identite"
    bare.mkdir(parents=True)
    with pytest.raises(prj.ProjectLockedError):
        prj.write_script(bare, SCRIPT)
    assert list(bare.iterdir()) == []


# ---- validations ----

def test_validation_order_enforced(tmp_path):
    p, audio = new_project(tmp_path), tmp_path / "a"
    add_script(p); add_storyboard(p); add_narration(p, audio)
    with pytest.raises(val.ValidationError, match="scénario non validé"):
        val.validate_storyboard(p, "v001")
    val.validate_script(p)
    with pytest.raises(val.ValidationError, match="storyboard non validé"):
        val.validate_narration(p, "v001", studio_audio_root=audio)
    with pytest.raises(val.ValidationError, match="introuvable"):
        val.validate_storyboard(p, "v009")
    e = val.validate_storyboard(p, "v001")
    assert e["numero"] == 2 and e["type"] == "storyboard" and e["configuration_rendu"] == FR_CONFIG_V4
    assert "storyboard/v001/scenes/scene_01.png" in e["empreintes"]


def test_modified_file_invalidates_next_steps(tmp_path):
    p, audio = new_project(tmp_path), tmp_path / "a"
    add_script(p); val.validate_script(p); add_storyboard(p)
    (p / "script.json").write_bytes((p / "script.json").read_bytes() + b" ")
    assert val.is_current(p, "scenario")[0] is False
    with pytest.raises(val.ValidationError, match="modifié depuis la validation 1"):
        val.validate_storyboard(p, "v001")


def test_revalidation_rules(tmp_path):
    p, audio = validated_until_narration(tmp_path)
    with pytest.raises(val.ValidationError, match="déjà validée"):
        val.validate_storyboard(p, "v001")                       # narration déjà validée après lui
    add_narration(p, audio, "v002")
    e = val.validate_narration(p, "v002", studio_audio_root=audio)
    assert e["remplace"] == 3 and val.validations_by_kind(p)["narration"]["version"] == "v002"
    assert len(val.load(p)["validations"]) == 4                  # l'ancienne entrée est conservée


def test_narration_refusals(tmp_path):
    p, audio = new_project(tmp_path), tmp_path / "a"
    add_script(p); val.validate_script(p); add_storyboard(p); val.validate_storyboard(p, "v001")
    add_narration(p, audio, conforme=False)
    with pytest.raises(val.ValidationError, match="non conforme"):
        val.validate_narration(p, "v001", studio_audio_root=audio)
    add_narration(p, audio, "v002")
    (audio / p.name / "v002" / "narration_fr.wav").write_bytes(b"autre")
    with pytest.raises(val.ValidationError, match="Copie pour Remotion"):
        val.validate_narration(p, "v002", studio_audio_root=audio)


def test_storyboard_unknown_config_refused(tmp_path):
    p = new_project(tmp_path)
    add_script(p); val.validate_script(p); add_storyboard(p, config="remotion.config.ts")
    with pytest.raises(val.ValidationError, match="Configuration de rendu inconnue"):
        val.validate_storyboard(p, "v001")


def test_crlf_preserved(tmp_path):
    p = new_project(tmp_path)
    f = p / "validations.json"
    f.write_bytes(f.read_bytes().replace(b"\n", b"\r\n"))
    add_script(p); val.validate_script(p)
    raw = f.read_bytes()
    assert raw.count(b"\r\n") == raw.count(b"\n") > 0


def test_legacy_pilot_kinds_read_only():
    kinds = val.validations_by_kind(PILOT)
    assert {"scenario", "storyboard", "reference_sonore", "rendu"} <= set(kinds)
    assert kinds["rendu"]["sha256"] == "00d118cd24867b93b2739a0e1c726143dfe607acfc1e82e736ba659e982c03e1"


# ---- rendu ----

def test_prepare_render_requires_validations(tmp_path):
    p = new_project(tmp_path)
    with pytest.raises(ren.RenderError, match="storyboard non validé"):
        ren.prepare_render(p)
    with pytest.raises(prj.ProjectLockedError):
        ren.prepare_render(PILOT)


def test_prepare_and_run_render(tmp_path):
    p, audio = validated_until_narration(tmp_path)
    plan = ren.prepare_render(p, studio_audio_root=audio)
    assert plan.config == FR_CONFIG_V4 and plan.storyboard_version == "v001" and plan.narration_version == "v001"
    assert plan.props["audio"]["narration"]["src"] == f"audio/studio/{p.name}/v001/narration_fr.wav"
    sb = json.loads((p / "storyboard/v001/props_storyboard.json").read_text(encoding="utf-8"))
    assert {k: v for k, v in plan.props.items() if k != "audio"} == sb
    runner = fake_runner()
    lines = []
    res = ren.run_render(plan, runner=runner, on_line=lines.append)
    cmd = runner.calls[0]
    assert cmd[2] == "render" and f"--config={FR_CONFIG_V4}" in cmd and "--bundle-cache=false" in cmd
    assert not any("npx" in c for c in cmd) and any(c.startswith("--browser-executable=") for c in cmd)
    assert res["version"] == "v001" and res["sha256"] == hashlib.sha256(FAKE_MP4).hexdigest()
    info = json.loads((p / "renders/v001/rendu.json").read_text(encoding="utf-8"))
    assert info["configuration_rendu"] == FR_CONFIG_V4 and lines == ["Rendered 930/930"]
    assert ren.run_render(plan, runner=fake_runner())["version"] == "v002"   # jamais d'écrasement


def test_render_failure_and_cancel_leave_nothing(tmp_path):
    p, audio = validated_until_narration(tmp_path)
    plan = ren.prepare_render(p, studio_audio_root=audio)
    with pytest.raises(ren.RenderError, match="Échec"):
        ren.run_render(plan, runner=fake_runner(code=1))
    with pytest.raises(ren.RenderError, match="Échec"):
        ren.run_render(plan, runner=fake_runner(content=b""))
    cancel = threading.Event(); cancel.set()
    with pytest.raises(ren.RenderError, match="annulé"):
        ren.run_render(plan, runner=fake_runner(), cancel=cancel)
    assert prj.versions(p / "renders") == []


def test_render_refused_if_narration_copy_changed(tmp_path):
    p, audio = validated_until_narration(tmp_path)
    (audio / p.name / "v001" / "narration_fr.wav").write_bytes(b"modifie")
    with pytest.raises(ren.RenderError, match="modifiée"):
        ren.prepare_render(p, studio_audio_root=audio)


def test_render_config_whitelist():
    assert ren.render_command(Path("p.json"), Path("o.mp4"), FR_CONFIG_V3)
    with pytest.raises(ValueError):
        ren.render_command(Path("p.json"), Path("o.mp4"), "remotion.config.ts")


def test_check_render_uses_render_sources(tmp_path, monkeypatch):
    from lib.studio.qc import QualityControlTool
    p, audio = validated_until_narration(tmp_path)
    ren.run_render(ren.prepare_render(p, studio_audio_root=audio), runner=fake_runner())
    seen = {}

    def fake_execute(self, inputs):          # contrôle simulé : aucun ffmpeg
        seen.update(inputs)
        return ToolResult(success=True, data={"conforme": True})
    monkeypatch.setattr(QualityControlTool, "execute", fake_execute)
    res = ren.check_render(p, "v001")
    assert res.success
    norm = {k: str(v).replace("\\", "/") for k, v in seen.items()}
    assert norm["mp4"].endswith("renders/v001/video.mp4") and norm["props"].endswith("renders/v001/props_rendu.json")
    assert norm["storyboard_dir"].endswith("storyboard/v001")
    assert norm["timing"].endswith("assets/narration/v001/timing_fr.json")
    (p / "renders/v001/video.mp4").write_bytes(b"altere")
    with pytest.raises(ren.RenderError, match="changé"):
        ren.check_render(p, "v001")


# ---- file de tâches ----

def test_jobs_single_task_result_and_busy():
    q, gate = JobQueue(), threading.Event()

    def slow(ctx):
        ctx.log("début"); ctx.progress(0.5)
        gate.wait(5)
        return {"ok": True}
    job = q.submit("rendu", slow, project="p")
    time.sleep(0.05)
    with pytest.raises(JobBusyError):
        q.submit("autre", lambda ctx: None)
    assert q.current() is job and job.as_dict()["progression"] == 0.5
    gate.set(); q.wait(job.id, 5)
    assert job.status == DONE and job.result == {"ok": True} and job.progress == 1.0 and q.current() is None
    assert q.wait(q.submit("suivante", lambda ctx: 1).id, 5).status == DONE


def test_jobs_failure_and_cancel():
    q = JobQueue()
    failed = q.wait(q.submit("échec", lambda ctx: 1 / 0).id, 5)
    assert failed.status == FAILED and "ZeroDivisionError" in failed.error

    def loop(ctx):
        while not ctx.cancelled:
            time.sleep(0.01)
    job = q.submit("longue", loop)
    time.sleep(0.05)
    assert q.cancel(job.id) and q.wait(job.id, 5).status == CANCELLED
    assert not q.cancel(job.id)


# ---- export ----

def test_export_package_full(tmp_path):
    p, _ = rendered_and_validated(tmp_path)
    mp4_sha = hashlib.sha256(FAKE_MP4).hexdigest()
    res = exp.export_package(p, "projet-test-fr-v001.mp4", "Projet test", "Description.")
    out = Path(res["export_dir"])
    assert out == p / "exports" / "v001" and res["sha256"] == mp4_sha
    assert set(res["fichiers"]) >= {"video/projet-test-fr-v001.mp4", "metadata/metadata.json",
                                    "metadata/description.txt", "controle/rapport_qc.json",
                                    "controle/rapport_qc.md", "publication_qc.json"}
    assert not (out / "video" / "output.mp4").exists()
    assert sha(out / "video/projet-test-fr-v001.mp4") == mp4_sha == sha(p / "renders/v001/video.mp4")
    assert sha(out / "controle/rapport_qc.json") == sha(p / "controle/v001/rapport_qc.json")
    trace = json.loads((out / "publication_qc.json").read_text(encoding="utf-8"))
    assert trace["publication"].startswith("aucune") and trace["mp4_sha256"] == mp4_sha
    meta = json.loads((out / "metadata/metadata.json").read_text(encoding="utf-8"))
    assert meta["title"] == "Projet test"
    assert prj.is_locked(p) and prj.project_state(p)["termine"]               # projet exporté → verrouillé
    with pytest.raises(prj.ProjectLockedError):
        exp.export_package(p, "autre.mp4", "T")


def test_export_refusals_leave_nothing(tmp_path):
    p, _ = rendered_and_validated(tmp_path)
    for bad in ("../x.mp4", "a b.mp4", "x.mov", ".mp4", "x" * 90 + ".mp4"):
        with pytest.raises(exp.ExportError, match="Nom de fichier"):
            exp.export_package(p, bad, "T")
    refusing = lambda *a, **k: ToolResult(success=False, error="refus simulé")  # noqa: E731
    with pytest.raises(exp.ExportError, match="refus simulé"):
        exp.export_package(p, "ok.mp4", "T", exporter=refusing)
    (p / "renders/v001/video.mp4").write_bytes(FAKE_MP4 + b"!")
    with pytest.raises(exp.ExportError, match="modifié depuis la validation"):
        exp.export_package(p, "ok.mp4", "T")
    assert prj.versions(p / "exports") == [] and not prj.is_locked(p)


def test_export_requires_render_validation(tmp_path):
    p, audio = validated_until_narration(tmp_path)
    ren.run_render(ren.prepare_render(p, studio_audio_root=audio), runner=fake_runner())
    add_qc_report(p, "v001", conforme=False)
    with pytest.raises(val.ValidationError, match="non conforme"):
        val.validate_render(p, "v001", "v001")
    with pytest.raises(exp.ExportError, match="rendu vidéo non validé"):
        exp.export_package(p, "ok.mp4", "T")
