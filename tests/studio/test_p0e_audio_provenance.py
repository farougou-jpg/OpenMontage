"""Lot P0-E — R6 : les octets audio réellement utilisés par un rendu sont ceux de la validation 3.

Le rendu lit une copie de piste propre à lui (lecture seule), vérifiée avant et après le moteur ;
`rendu.json` inscrit `audio_sha256` ; `render_provenance` (validation 4, export) l'exige.
Dossier temporaire de pytest uniquement ; aucun rendu réel (runner simulé).
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
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
        raise AssertionError("processus réel interdit dans les tests P0-E")
    monkeypatch.setattr(ren.subprocess, "Popen", refuse)
    monkeypatch.setattr(ren.subprocess, "run", refuse)


def sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def shared_copy(p: Path, audio: Path) -> Path:
    return audio / p.name / "v001" / "narration_fr.wav"


def render_copy(audio: Path, p: Path, render_version: str = "v001") -> Path:
    return audio / p.name / "v001" / "rendus" / render_version / "narration_fr.wav"


def validated_audio(p: Path) -> str:
    return val.validations_by_kind(p)["narration"]["copie_remotion_sha256"]


def force_write(path: Path, data: bytes) -> None:
    os.chmod(path, stat.S_IWRITE)
    path.write_bytes(data)


# ---- rendu normal ----

def test_nominal_render_uses_an_immutable_copy_of_the_validated_audio(tmp_path):
    p, audio = g0.validated_until_narration(tmp_path)
    res = ren.run_render(ren.prepare_render(p, studio_audio_root=audio), runner=g0.fake_runner())
    copy = render_copy(audio, p)
    info = json.loads((p / "renders/v001/rendu.json").read_text(encoding="utf-8"))
    assert info["audio_sha256"] == validated_audio(p) == sha(copy) == res["audio_sha256"]
    assert Path(info["audio_copie"]) == copy and copy.read_bytes() == shared_copy(p, audio).read_bytes()
    assert not os.access(copy, os.W_OK)                                  # copie en lecture seule
    props = json.loads((p / "renders/v001/props_rendu.json").read_text(encoding="utf-8"))
    assert props["audio"]["narration"]["src"] == ren.render_audio_src(p.name, "v001", "v001") == info["audio"]
    assert ren.render_provenance(p, "v001")["audio_sha256"] == validated_audio(p)
    g0.add_qc_report(p, "v001")
    assert g0.approve(p, "rendu", render_version="v001", qc_version="v001")["numero"] == 4


def test_each_render_gets_its_own_copy(tmp_path):
    p, audio = g0.validated_until_narration(tmp_path)
    for _ in range(2):
        ren.run_render(ren.prepare_render(p, studio_audio_root=audio), runner=g0.fake_runner())
    assert render_copy(audio, p, "v001").is_file() and render_copy(audio, p, "v002").is_file()
    assert ren.render_provenance(p, "v002")["audio_sha256"] == validated_audio(p)


# ---- remplacements et modifications ----

def test_replacement_after_prepare_render_is_refused_and_leaves_nothing(tmp_path):
    p, audio = g0.validated_until_narration(tmp_path)
    plan = ren.prepare_render(p, studio_audio_root=audio)
    shared_copy(p, audio).write_bytes(b"RIFF-AUTRE-PISTE")
    with pytest.raises(ren.RenderError, match="n'est plus celle de la validation 3"):
        ren.run_render(plan, runner=g0.fake_runner())
    assert prj.versions(p / "renders") == [] and not render_copy(audio, p).exists()


def test_shared_copy_replaced_during_render_cannot_reach_the_render(tmp_path):
    p, audio = g0.validated_until_narration(tmp_path)
    fake = g0.fake_runner()

    def swapping(cmd, cwd, on_line, cancel):
        shared_copy(p, audio).write_bytes(b"RIFF-AUTRE-PISTE-PENDANT")    # la copie partagée change…
        return fake(cmd, cwd, on_line, cancel)
    ren.run_render(ren.prepare_render(p, studio_audio_root=audio), runner=swapping)
    props = json.loads((p / "renders/v001/props_rendu.json").read_text(encoding="utf-8"))
    assert "rendus/v001" in props["audio"]["narration"]["src"]          # … mais le rendu lit sa propre copie
    assert sha(render_copy(audio, p)) == validated_audio(p)
    assert ren.render_provenance(p, "v001")["audio_sha256"] == validated_audio(p)
    with pytest.raises(ren.RenderError, match="Copie Remotion"):         # un rendu suivant serait refusé
        ren.prepare_render(p, studio_audio_root=audio)


def test_render_copy_modified_during_render_is_refused_and_cleaned(tmp_path):
    p, audio = g0.validated_until_narration(tmp_path)
    fake = g0.fake_runner()

    def tampering(cmd, cwd, on_line, cancel):
        force_write(render_copy(audio, p), b"RIFF-PISTE-REMPLACEE-DANS-LE-RENDU")
        return fake(cmd, cwd, on_line, cancel)
    with pytest.raises(ren.RenderError, match="a changé pendant le rendu"):
        ren.run_render(ren.prepare_render(p, studio_audio_root=audio), runner=tampering)
    assert prj.versions(p / "renders") == [] and not render_copy(audio, p).exists()


def test_modification_at_identical_path_after_render(tmp_path):
    p, audio = g0.validated_until_narration(tmp_path)
    ren.run_render(ren.prepare_render(p, studio_audio_root=audio), runner=g0.fake_runner())
    shared_copy(p, audio).write_bytes(b"RIFF-AUTRE")          # copie partagée modifiée APRÈS le rendu :
    assert ren.render_provenance(p, "v001")                   # le MP4 a été rendu avec les octets validés
    force_write(render_copy(audio, p), b"RIFF-AUTRE")         # copie propre au rendu modifiée : preuve perdue
    with pytest.raises(ren.RenderError, match="Copie de piste propre au rendu absente, déplacée ou modifiée"):
        ren.render_provenance(p, "v001")
    g0.add_qc_report(p, "v001")
    with pytest.raises(val.ValidationError, match="Copie de piste propre au rendu"):
        g0.approve(p, "rendu", render_version="v001", qc_version="v001")


def test_deleted_render_copy_is_refused(tmp_path):
    p, audio = g0.validated_until_narration(tmp_path)
    ren.run_render(ren.prepare_render(p, studio_audio_root=audio), runner=g0.fake_runner())
    os.chmod(render_copy(audio, p), stat.S_IWRITE)
    render_copy(audio, p).unlink()
    with pytest.raises(ren.RenderError, match="absente, déplacée ou modifiée"):
        ren.render_provenance(p, "v001")


# ---- preuve absente ou falsifiée dans rendu.json ----

@pytest.mark.parametrize("change,why", [
    ({"audio_sha256": None}, "audio_sha256 absent"),
    ({"audio_sha256": ""}, "audio_sha256 absent"),
    ({"audio_sha256": "0" * 64}, "différente de la narration validée"),
    ({"audio_copie": None}, "absente, déplacée ou modifiée"),
])
def test_missing_or_forged_audio_proof_is_refused(tmp_path, change, why):
    p, audio = g0.validated_until_narration(tmp_path)
    ren.run_render(ren.prepare_render(p, studio_audio_root=audio), runner=g0.fake_runner())
    f = p / "renders/v001/rendu.json"
    info = json.loads(f.read_text(encoding="utf-8"))
    for k, v in change.items():
        if v is None:
            info.pop(k)
        else:
            info[k] = v
    prj.write_json(f, info)
    with pytest.raises(ren.RenderError, match=why):
        ren.render_provenance(p, "v001")


def test_audio_copy_pointing_to_another_file_is_refused(tmp_path):
    p, audio = g0.validated_until_narration(tmp_path)
    ren.run_render(ren.prepare_render(p, studio_audio_root=audio), runner=g0.fake_runner())
    f = p / "renders/v001/rendu.json"
    info = json.loads(f.read_text(encoding="utf-8"))
    info["audio_copie"] = str(shared_copy(p, audio))            # mêmes octets, mais pas la copie du rendu
    prj.write_json(f, info)
    with pytest.raises(ren.RenderError, match="absente, déplacée ou modifiée"):
        ren.render_provenance(p, "v001")


def test_validation_4_and_export_require_the_audio_proof(tmp_path):
    p, audio = g0.validated_until_narration(tmp_path)
    ren.run_render(ren.prepare_render(p, studio_audio_root=audio), runner=g0.fake_runner())
    g0.add_qc_report(p, "v001")
    g0.approve(p, "rendu", render_version="v001", qc_version="v001")
    f = p / "renders/v001/rendu.json"
    info = json.loads(f.read_text(encoding="utf-8"))
    info.pop("audio_sha256")
    prj.write_json(f, info)                                      # rendu.json n'est pas dans les empreintes v4
    with pytest.raises(exp.ExportError, match="audio_sha256 absent"):
        exp.export_package(p, "film.mp4", "T")
    assert prj.versions(p / "exports") == []


# ---- plan et nettoyage ----

def test_plan_from_a_superseded_narration_is_refused(tmp_path):
    p, audio = g0.validated_until_narration(tmp_path)
    plan = ren.prepare_render(p, studio_audio_root=audio)
    g0.add_narration(p, audio, "v002")
    g0.approve(p, "narration", version="v002", studio_audio_root=audio)
    with pytest.raises(ren.RenderError, match="différente du plan"):
        ren.run_render(plan, runner=g0.fake_runner())
    assert prj.versions(p / "renders") == []


@pytest.mark.parametrize("kind", ["code", "vide", "annule"])
def test_failed_or_cancelled_render_removes_its_audio_copy(tmp_path, kind):
    import threading
    p, audio = g0.validated_until_narration(tmp_path)
    plan = ren.prepare_render(p, studio_audio_root=audio)
    cancel = threading.Event()
    if kind == "annule":
        cancel.set()
    runner = g0.fake_runner(code=1) if kind == "code" else g0.fake_runner(content=b"" if kind == "vide" else g0.FAKE_MP4)
    with pytest.raises(ren.RenderError):
        ren.run_render(plan, runner=runner, cancel=cancel)
    assert prj.versions(p / "renders") == [] and not render_copy(audio, p).exists()
    assert shared_copy(p, audio).is_file()                       # la copie validée n'est jamais touchée
