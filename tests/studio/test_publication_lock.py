"""Lot 1.6 — verrou de publication : volet A (garde-fou), volet B (export du studio),
option C (export_bundle refuse les projets Studio non contrôlés).

Tout se passe dans le dossier temporaire : projets Studio factices contenant une COPIE
d'un MP4 validé (copie, aucune génération). Les originaux et tout `projects/` sont
inventoriés avant et après : aucune écriture dans les dossiers de production.
"""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
from pathlib import Path

import pytest

from lib.studio.budget_guard import PublicationRefusedError, StudioBudgetGuard
from lib.studio.narration.tool import REPO_ROOT
from lib.studio.publish import exporter_video
from lib.studio.qc import QualityControlTool, publication_allowed
from tests.studio.qc_data import load, paths, script_from_timing
from tests.studio.test_qc_publication_refusals import _storyboard_from_mp4
from tools.base_tool import ToolResult
from tools.publishers.export_bundle import ExportBundle

PROJECTS = REPO_ROOT / "projects"


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _inventory() -> dict[str, str]:
    return {str(p.relative_to(PROJECTS)): _sha(p) for p in sorted(PROJECTS.rglob("*")) if p.is_file()}


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    inv_before = _inventory()
    original_sha = _sha(paths("code-to-screen")["mp4"])
    root = tmp_path_factory.mktemp("publication")
    code = load("code-to-screen")
    project = root / "projet-studio"
    project.mkdir(parents=True)
    (project / "studio_project.json").write_text(json.dumps({
        "studio": "OpenMontage Studio", "version": 1, "projet": project.name,
        "pipeline": "studio-fr"
    }), encoding="utf-8")
    render_dir = project / "renders" / "v001"
    render_dir.mkdir(parents=True)
    mp4 = render_dir / "final.mp4"
    shutil.copy2(code["mp4"], mp4)
    sb = _storyboard_from_mp4({**code, "mp4": mp4}, root / "sb")
    base = {"mp4": str(mp4), "props": code["props"], "timing": code["timing"], "project_dir": str(project),
            "storyboard_dir": str(sb), "script": script_from_timing(code["timing"], 30)}
    (render_dir / "rendu.json").write_text(json.dumps({
        "mp4": mp4.name, "sha256": _sha(mp4), "taille_octets": mp4.stat().st_size
    }), encoding="utf-8")
    qc_ok = QualityControlTool().execute(base)
    assert publication_allowed(qc_ok), qc_ok.data.get("bloquants")
    shifted = copy.deepcopy(code["timing"])
    for r in shifted:
        r["fin"] += 0.5
    qc_ko = QualityControlTool().execute({**base, "timing": shifted})
    assert qc_ko.success and qc_ko.data["conforme"] is False
    other = root / "autre.mp4"
    shutil.copy2(load("focusflow-pitch")["mp4"], other)
    yield {"root": root, "project": project, "mp4": mp4, "qc_ok": qc_ok, "qc_ko": qc_ko, "other": other,
           "sha": _sha(mp4)}
    assert _inventory() == inv_before, "un fichier de projects/ a été créé, modifié ou supprimé"
    assert _sha(paths("code-to-screen")["mp4"]) == original_sha


def _modified_copy(src: Path, dst: Path, how: str) -> Path:
    shutil.copy2(src, dst)
    data = bytearray(dst.read_bytes())
    if how == "ajout":
        data += b"\0"
    else:  # même taille, contenu différent
        data[len(data) // 2] ^= 0xFF
    dst.write_bytes(bytes(data))
    return dst


def _export_inputs(video: Path, export_dir: Path, **extra) -> dict:
    return {"video_path": str(video), "title": "Pilote", "export_dir": str(export_dir), **extra}


# ======================= Volet A : garde-fou =======================

def test_A_guard_refuses_publish_without_qc(env, tmp_path):
    out = tmp_path / "exp"
    with pytest.raises(PublicationRefusedError, match="absent, échoué ou invalide"):
        StudioBudgetGuard(env["project"]).run(ExportBundle(), _export_inputs(env["mp4"], out))
    assert not out.exists()


def test_A_guard_refuses_failed_qc(env, tmp_path):
    with pytest.raises(PublicationRefusedError):
        StudioBudgetGuard(env["project"]).run(ExportBundle(), _export_inputs(env["mp4"], tmp_path / "e"),
                                              qc_result=env["qc_ko"])
    assert not (tmp_path / "e").exists()


@pytest.mark.parametrize("how", ["ajout", "meme_taille"])
def test_A_guard_refuses_mp4_modified_after_qc(env, tmp_path, how):
    changed = _modified_copy(env["mp4"], tmp_path / "modifie.mp4", how)
    with pytest.raises(PublicationRefusedError, match="empreinte SHA-256"):
        StudioBudgetGuard(env["project"]).run(ExportBundle(), _export_inputs(changed, tmp_path / "e"),
                                              qc_result=env["qc_ok"])
    assert not (tmp_path / "e").exists()


def test_A_guard_refuses_qc_of_another_video(env, tmp_path):
    with pytest.raises(PublicationRefusedError):
        StudioBudgetGuard(env["project"]).run(ExportBundle(), _export_inputs(env["other"], tmp_path / "e"),
                                              qc_result=env["qc_ok"])


@pytest.mark.parametrize("forged", [
    None, ToolResult(success=True, data={"conforme": True}),
    ToolResult(success=True, data={"conforme": True, "rapport_json": "inexistant.json"}),
])
def test_A_guard_refuses_forged_or_missing_results(env, tmp_path, forged):
    with pytest.raises(PublicationRefusedError):
        StudioBudgetGuard(env["project"]).run(ExportBundle(), _export_inputs(env["mp4"], tmp_path / "e"),
                                              qc_result=forged)


def test_A_studio_publication_uses_guard_and_accepts_exact_mp4(env):
    res = exporter_video(env["qc_ok"], env["mp4"], "Pilote", env["project"])
    assert res.success, res.error
    out = Path(res.data["version_dir"])
    assert _sha(out / "video" / "output.mp4") == env["sha"]


def test_A_non_publish_tools_unaffected(env):
    d = StudioBudgetGuard(env["project"]).check(QualityControlTool(), {})
    assert d.allowed  # l'exigence de contrôle ne concerne que les outils de publication


# ============ Option C : appel DIRECT à export_bundle (contournement) ============

def test_C_direct_export_without_report_is_refused(env):
    out = env["project"] / "exports" / "v010"
    res = ExportBundle().execute(_export_inputs(env["mp4"], out))
    assert not res.success and "exporter_video" in res.error
    assert not out.exists()


def test_C_direct_export_with_failed_report_is_refused(env):
    res = ExportBundle().execute(_export_inputs(env["mp4"], env["project"] / "exports" / "v011",
                                                studio_qc_report=env["qc_ko"].data["rapport_json"]))
    assert not res.success and "exporter_video" in res.error


@pytest.mark.parametrize("how", ["ajout", "meme_taille"])
def test_C_direct_export_of_modified_mp4_is_refused(env, how):
    changed = _modified_copy(env["mp4"], env["project"] / "renders" / "v001" / f"modifie_{how}.mp4", how)
    try:
        res = ExportBundle().execute(_export_inputs(changed, env["project"] / "exports" / ("v012" if how == "ajout" else "v013"),
                                                    studio_qc_report=env["qc_ok"].data["rapport_json"]))
        assert not res.success and "exporter_video" in res.error
    finally:
        changed.unlink()


def test_C_report_outside_project_controle_is_refused(env, tmp_path):
    copied = tmp_path / "rapport_qc.json"
    shutil.copy2(env["qc_ok"].data["rapport_json"], copied)
    res = ExportBundle().execute(_export_inputs(env["mp4"], env["project"] / "exports" / "v014",
                                                studio_qc_report=str(copied)))
    assert not res.success and "exporter_video" in res.error


def test_C_mp4_copied_out_but_export_into_studio_project_is_refused(env, tmp_path):
    outside = tmp_path / "copie_hors_projet.mp4"
    shutil.copy2(env["mp4"], outside)
    res = ExportBundle().execute(_export_inputs(outside, env["project"] / "exports" / "v016"))
    assert not res.success and "exporter_video" in res.error


def test_C_studio_project_detected_without_marker(env, tmp_path):
    proj = tmp_path / "projet-sans-marqueur"
    (proj / "storyboard" / "v001").mkdir(parents=True)
    (proj / "storyboard" / "v001" / "storyboard.json").write_text("{}", encoding="utf-8")
    (proj / "renders").mkdir()
    shutil.copy2(env["mp4"], proj / "renders" / "final.mp4")
    res = ExportBundle().execute(_export_inputs(proj / "renders" / "final.mp4", proj / "exports" / "x"))
    assert not res.success and "exporter_video" in res.error


def test_C_direct_export_is_refused_even_with_a_valid_report(env):
    out = env["project"] / "exports" / "v015"
    res = ExportBundle().execute(_export_inputs(env["mp4"], out,
                                                studio_qc_report=env["qc_ok"].data["rapport_json"]))
    assert not res.success and "exporter_video" in res.error
    assert not out.exists()


# ============ Projets hors Studio : comportement inchangé ============

def test_non_studio_project_export_unchanged(tmp_path):
    video = tmp_path / "projects" / "demo" / "renders" / "final.mp4"
    video.parent.mkdir(parents=True)
    video.write_bytes(b"fake-mp4-bytes")
    res = ExportBundle().execute({"video_path": str(video), "title": "T", "export_dir": str(tmp_path / "out")})
    assert res.success and (tmp_path / "out" / "video" / "output.mp4").read_bytes() == b"fake-mp4-bytes"


def test_fr_series_like_layout_is_not_treated_as_studio(tmp_path):
    """Structure des vidéos validées (controle/ non versionné, timing_fr.json à la racine)."""
    proj = tmp_path / "fr-series" / "video"
    (proj / "controle").mkdir(parents=True)
    (proj / "controle" / "rapport_qc.json").write_text("{}", encoding="utf-8")
    (proj / "timing_fr.json").write_text("[]", encoding="utf-8")
    (proj / "video-fr.mp4").write_bytes(b"x")
    res = ExportBundle().execute({"video_path": str(proj / "video-fr.mp4"), "title": "T",
                                  "export_dir": str(tmp_path / "out")})
    assert res.success


# ======================= Volet B : export du studio =======================

def _b_versions(project: Path) -> set[str]:
    return {p.name for p in (project / "exports").glob("v[0-9][0-9][0-9]")}


@pytest.mark.parametrize("qc_key", [None, "qc_ko"])
def test_B_refused_without_or_with_failed_qc(env, qc_key):
    before = _b_versions(env["project"])
    res = exporter_video(env[qc_key] if qc_key else None, env["mp4"], "Pilote", env["project"])
    assert not res.success and res.error.startswith("Publication refusée")
    assert _b_versions(env["project"]) == before


def test_B_refused_if_mp4_changed_after_qc(env, tmp_path):
    changed = _modified_copy(env["mp4"], tmp_path / "m.mp4", "meme_taille")
    before = _b_versions(env["project"])
    res = exporter_video(env["qc_ok"], changed, "Pilote", env["project"])
    assert not res.success and "rendu versionné et immuable" in res.error
    assert _b_versions(env["project"]) == before


def test_B_report_outside_project_controle_is_refused(env, tmp_path):
    copied = tmp_path / "rapport_qc_copie.json"
    shutil.copy2(env["qc_ok"].data["rapport_json"], copied)
    forged = ToolResult(success=True, data={**env["qc_ok"].data, "rapport_json": str(copied)},
                        artifacts=list(env["qc_ok"].artifacts), cost_usd=0.0)
    before = _b_versions(env["project"])
    res = exporter_video(forged, env["mp4"], "Pilote", env["project"])
    assert not res.success and "hors du dossier controle" in res.error
    assert _b_versions(env["project"]) == before


def test_B_modified_render_cannot_be_republished(env):
    mp4 = env["mp4"]
    original = mp4.read_bytes()
    before = _b_versions(env["project"])
    try:
        mp4.write_bytes(original + b"\x00")
        res = exporter_video(env["qc_ok"], mp4, "Pilote", env["project"])
        assert not res.success and "rendu versionné et immuable" in res.error
        assert _b_versions(env["project"]) == before
    finally:
        mp4.write_bytes(original)


def test_B_tampering_during_export_is_detected_and_only_this_export_removed(env, monkeypatch):
    real = ExportBundle.execute

    def tampering(self, inputs):
        res = real(self, inputs)
        if res.success:
            (Path(res.data["export_path"]) / "video" / "output.mp4").write_bytes(b"remplace")
        return res
    monkeypatch.setattr(ExportBundle, "execute", tampering)
    before = _b_versions(env["project"])
    res = exporter_video(env["qc_ok"], env["mp4"], "Pilote", env["project"])
    assert not res.success and "ne correspond pas" in res.error
    assert _b_versions(env["project"]) == before
    assert _sha(env["mp4"]) == env["sha"]


def test_B_protected_zone_refused():
    target = PROJECTS / "demos" / "fr-series" / "code-to-screen"
    res = exporter_video(None, target / "code-to-screen-fr.mp4", "X", target)
    assert not res.success
    assert not (target / "exports").exists() and not (target / "studio_project.json").exists()


def test_B_unexpected_exception_is_a_refusal(env, monkeypatch):
    def boom(*a, **k):
        raise OSError("disque indisponible (simulé)")
    monkeypatch.setattr("lib.studio.publish.next_version_dir", boom)
    res = exporter_video(env["qc_ok"], env["mp4"], "Pilote", env["project"])
    assert not res.success and "OSError" in res.error


def test_B_nominal_publication_and_versions(env):
    r1 = exporter_video(env["qc_ok"], env["mp4"], "Pilote", env["project"], description="Test")
    r2 = exporter_video(env["qc_ok"], env["mp4"], "Pilote", env["project"])
    assert r1.success and r2.success, (r1.error, r2.error)
    v1, v2 = Path(r1.data["version_dir"]), Path(r2.data["version_dir"])
    assert v1.parent == v2.parent == env["project"] / "exports" and v1.name < v2.name
    for v in (v1, v2):
        assert _sha(v / "video" / "output.mp4") == env["sha"]
        trace = json.loads((v / "publication_qc.json").read_text(encoding="utf-8"))
        assert trace["mp4_sha256"] == env["sha"] and trace["rapport_qc"] == env["qc_ok"].data["rapport_json"]
    assert (env["project"] / "studio_project.json").is_file()


# ======================= Consignes du pipeline =======================

def test_pipeline_publish_stage_uses_studio_export_only():
    import yaml
    m = yaml.safe_load((REPO_ROOT / "pipeline_defs" / "studio-fr.yaml").read_text(encoding="utf-8"))
    publish = next(s for s in m["stages"] if s["name"] == "publish")
    assert publish["skill"] == "pipelines/studio-fr/publish-director"
    assert "export_bundle" not in (publish.get("tools_available") or [])
    assert "pipelines/explainer/publish-director" not in m["required_skills"]
    assert "studio_export" in m["metadata"]["studio_tools"]
    skill = (REPO_ROOT / "skills" / "pipelines" / "studio-fr" / "publish-director.md").read_text(encoding="utf-8")
    assert "exclusivement par `exporter_video`" in skill and "Ne jamais appeler" in skill



def test_B_republication_after_lock_uses_only_the_immutable_render(env):
    # Un premier export verrouille le projet.
    first = exporter_video(env["qc_ok"], env["mp4"], "Pilote", env["project"])
    assert first.success, first.error
    from lib.studio.project import is_locked
    assert is_locked(env["project"])

    render_dir = env["project"] / "renders" / "v001"
    # Le rapport QC de référence est lié au même contenu ; la republication
    # crée une nouvelle version sans toucher aux sources ni au rendu.
    second = exporter_video(env["qc_ok"], render_dir / "final.mp4", "Pilote", env["project"])
    assert second.success, second.error
    assert Path(second.data["version_dir"]).name > Path(first.data["version_dir"]).name
    assert _sha(render_dir / "final.mp4") == env["sha"]


def test_B_locked_project_refuses_republication_from_unmanaged_mp4(env, tmp_path):
    first = exporter_video(env["qc_ok"], env["mp4"], "Pilote", env["project"])
    assert first.success, first.error
    before = _b_versions(env["project"])
    res = exporter_video(env["qc_ok"], env["other"], "Pilote", env["project"])
    assert not res.success and "rendu versionné et immuable" in res.error
    assert _b_versions(env["project"]) == before
