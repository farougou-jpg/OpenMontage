"""Étape G0 — socle de l'interface : projets, validations, rendu, file de tâches, export.

Aucun rendu, aucune synthèse ni aucun accès réseau : les projets sont créés dans le dossier
temporaire de pytest, le rendu passe par un `runner` simulé, le contrôle qualité par un outil
simulé. Le pilote et les vidéos françaises ne sont lus qu'en lecture seule.
"""

from __future__ import annotations

import hashlib
import json
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
