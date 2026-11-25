"""Lot P0-C — rendu obligatoire par `render.py` : provenance vérifiée, validation 4 sur le MP4 exact (D2).

Aucun rendu réel : `run_render` reçoit un runner simulé. Dossier temporaire de pytest uniquement.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from lib.studio import export_package as exp
from lib.studio import project as prj
from lib.studio import render as ren
from lib.studio import validations as val
from tests.studio import test_g0_socle as g0


@pytest.fixture(autouse=True)
def no_real_process(monkeypatch):
    def refuse(*_a, **_k):
        raise AssertionError("processus réel interdit dans les tests P0-C")
    monkeypatch.setattr(ren.subprocess, "Popen", refuse)
    monkeypatch.setattr(ren.subprocess, "run", refuse)


def rendered(tmp_path: Path) -> tuple[Path, Path]:
    p, audio = g0.validated_until_narration(tmp_path)
    ren.run_render(ren.prepare_render(p, studio_audio_root=audio), runner=g0.fake_runner())
    return p, audio


def validate_4(p: Path, render_version: str = "v001", qc_version: str = "v001") -> dict:
    return g0.approve(p, "rendu", render_version=render_version, qc_version=qc_version)


def test_provenance_of_a_render_py_output(tmp_path):
    p, _ = rendered(tmp_path)
    prov = ren.render_provenance(p, "v001")
    mp4 = p / "renders" / "v001" / "video.mp4"
    assert prov["sha256"] == hashlib.sha256(mp4.read_bytes()).hexdigest()
    assert (prov["storyboard"], prov["narration"]) == ("v001", "v001")


def test_D2_mp4_outside_render_py_refused_even_with_conform_qc(tmp_path):
    p, _ = g0.validated_until_narration(tmp_path)
    d = p / "renders" / "v001"
    d.mkdir(parents=True)
    (d / "video.mp4").write_bytes(g0.FAKE_MP4)
    g0.add_qc_report(p, "v001")                                   # contrôle conforme sur ce MP4 exact
    with pytest.raises(ren.RenderError, match="rendu.json absent"):
        ren.render_provenance(p, "v001")
    before = (p / "validations.json").read_bytes()
    with pytest.raises(val.ValidationError, match="rendu.json absent"):
        validate_4(p)
    assert (p / "validations.json").read_bytes() == before
    with pytest.raises(exp.ExportError, match="rendu vidéo non validé"):
        exp.export_package(p, "film.mp4", "T")


@pytest.mark.parametrize("tamper,why", [
    ("mp4", "ne correspond plus au manifeste"),
    ("second_mp4", "un seul MP4"),
    ("manifest_storyboard", "Rendu produit sur storyboard"),
    ("manifest_config", "Configuration de rendu"),
    ("manifest_audio", "piste audio inattendue"),
    ("props", "props_rendu.json ne correspond pas"),
    ("props_missing", "props_rendu.json ne correspond pas"),
])
def test_tampered_render_has_no_provenance(tmp_path, tamper, why):
    p, _ = rendered(tmp_path)
    r = p / "renders" / "v001"
    info = json.loads((r / "rendu.json").read_text(encoding="utf-8"))
    if tamper == "mp4":
        (r / "video.mp4").write_bytes(g0.FAKE_MP4 + b"!")
    elif tamper == "second_mp4":
        (r / "autre.mp4").write_bytes(b"x")
    elif tamper.startswith("manifest_"):
        key = {"manifest_storyboard": "storyboard", "manifest_config": "configuration_rendu",
               "manifest_audio": "audio"}[tamper]
        prj.write_json(r / "rendu.json", {**info, key: "falsifie"})
    elif tamper == "props":
        props = json.loads((r / "props_rendu.json").read_text(encoding="utf-8"))
        props["cuts"][0]["text"] = "Texte jamais validé"
        prj.write_json(r / "props_rendu.json", props)
    else:
        (r / "props_rendu.json").unlink()
    with pytest.raises(ren.RenderError, match=why):
        ren.render_provenance(p, "v001")


def test_render_made_on_superseded_narration_is_refused(tmp_path):
    p, audio = rendered(tmp_path)
    g0.add_narration(p, audio, "v002")
    g0.approve(p, "narration", version="v002", studio_audio_root=audio)   # narration revalidée après le rendu
    with pytest.raises(ren.RenderError, match="Rendu produit sur storyboard v001 / narration v001"):
        ren.render_provenance(p, "v001")


def test_render_refused_when_validations_are_no_longer_current(tmp_path):
    p, _ = rendered(tmp_path)
    (p / "storyboard" / "v001" / "scenes" / "scene_01.png").write_bytes(b"retouche")
    with pytest.raises(ren.RenderError, match="modifié depuis la validation 2"):
        ren.render_provenance(p, "v001")


def test_validation_4_binds_the_exact_render_py_mp4(tmp_path):
    p, _ = rendered(tmp_path)
    g0.add_qc_report(p, "v001")
    e = validate_4(p)
    info = json.loads((p / "renders" / "v001" / "rendu.json").read_text(encoding="utf-8"))
    mp4 = p / "renders" / "v001" / "video.mp4"
    assert e["sha256"] == info["sha256"] == hashlib.sha256(mp4.read_bytes()).hexdigest()
    assert e["taille_octets"] == info["taille_octets"] == mp4.stat().st_size
    assert e["fichier"] == "renders/v001/video.mp4"
    assert set(e["empreintes"]) == {"renders/v001/video.mp4", "renders/v001/props_rendu.json",
                                    "controle/v001/rapport_qc.json"}


def test_qc_report_alone_never_substitutes_for_provenance(tmp_path):
    p, _ = rendered(tmp_path)
    g0.add_qc_report(p, "v001")
    (p / "renders" / "v001" / "rendu.json").unlink()            # rapport conforme, provenance perdue
    with pytest.raises(val.ValidationError, match="rendu.json absent"):
        validate_4(p)


def test_publish_code_untouched_and_export_still_requires_validation_4(tmp_path):
    p, _ = rendered(tmp_path)
    g0.add_qc_report(p, "v001")
    with pytest.raises(exp.ExportError, match="rendu vidéo non validé"):
        exp.export_package(p, "film.mp4", "T")
    assert prj.versions(p / "exports") == []
