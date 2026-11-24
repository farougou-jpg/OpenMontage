"""Lot 1.2 — test 11 : équivalence avec la méthode V2 (double preuve validée par l'utilisateur).

(a) À audio Piper brut identique, l'ancien ``fr_build.py`` (exécuté tel quel, mais
    redirigé vers un dossier temporaire) et le nouvel outil produisent des fichiers
    identiques octet par octet : segments et narration de première passe.
(b) Même texte lu, mêmes phonèmes, mêmes positions et durées.
(c) Les durées restent dans la variation naturelle de Piper (± 10 %) par rapport
    aux durées enregistrées lors de la validation.

Sécurité : ``fr_build.ROOT`` est redirigé vers tmp_path AVANT l'appel ; sans
``--rebuild``, fr_build refuse de toute façon d'écrire si sa sortie publique existe.
Aucun bytecode n'est écrit dans projects/demos (``sys.dont_write_bytecode``).
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import sys
from pathlib import Path

import pytest

from lib.studio.narration.tool import PiperFrNarration

REPO = Path(__file__).resolve().parents[2]
COMMON = REPO / "projects" / "demos" / "fr-series" / "common"
VIDEOS = ["animated-reel-20s", "code-to-screen", "focusflow-pitch", "stop-procrastinating-with-this-1-hack"]
NATURAL_SPREAD = 0.10


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


@pytest.fixture(scope="module")
def fr_build_module():
    old_flag, old_path = sys.dont_write_bytecode, list(sys.path)
    saved = {k: sys.modules.pop(k) for k in ("fr_text", "fr_build") if k in sys.modules}
    sys.dont_write_bytecode = True
    try:
        spec = importlib.util.spec_from_file_location("fr_build_v2_ref", COMMON / "fr_build.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        yield mod
    finally:
        sys.dont_write_bytecode = old_flag
        sys.path[:] = old_path
        sys.modules.pop("fr_text", None)
        sys.modules.update(saved)


def _run_old(mod, cached_voice, name: str, tmp: Path, monkeypatch) -> Path:
    cfg_src = REPO / "projects" / "demos" / "fr-series" / name / "config.json"
    cfg = json.loads(cfg_src.read_text(encoding="utf-8"))
    fake_root = tmp / "old_root"
    props_dst = fake_root / cfg["source_props"]
    props_dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(REPO / cfg["source_props"], props_dst)
    out_dir = tmp / "old_out" / name
    out_dir.mkdir(parents=True)
    cfg_path = out_dir / "config.json"
    shutil.copyfile(cfg_src, cfg_path)

    class _Factory:
        @staticmethod
        def load(_path):
            return cached_voice

    monkeypatch.setattr(mod, "ROOT", fake_root)
    monkeypatch.setattr(mod, "PiperVoice", _Factory)
    monkeypatch.setattr(sys, "argv", ["fr_build.py", str(cfg_path)])
    assert mod.ROOT == fake_root and str(fake_root).startswith(str(tmp))
    assert mod.main() == 0
    return out_dir


def _script_from_v2(name: str) -> tuple[dict, dict, float]:
    cfg = json.loads((REPO / "projects" / "demos" / "fr-series" / name / "config.json").read_text(encoding="utf-8"))
    props = json.loads((REPO / cfg["source_props"]).read_text(encoding="utf-8"))
    total = max(c["out_seconds"] for c in props["cuts"])
    sections, options = [], {}
    for s in cfg["segments"]:
        sections.append({"id": s["cut"], "text": s["text"], "start_seconds": s["start"],
                         "end_seconds": s["end_max"]})
        options[s["cut"]] = {"fade_out_frames": 0, **({"anchor": s["anchor"]} if "anchor" in s else {})}
    script = {"version": "1.0", "title": name, "total_duration_seconds": total, "sections": sections}
    return script, options, cfg.get("sentence_pause", 0.30)


@pytest.mark.parametrize("name", VIDEOS)
def test_v2_equivalence(name, fr_build_module, cached_voice, tmp_path, monkeypatch):
    old = _run_old(fr_build_module, cached_voice, name, tmp_path, monkeypatch)

    script, options, pause = _script_from_v2(name)
    project = _make_studio_project(tmp_path / "new" / name)
    res = PiperFrNarration(voice=cached_voice).execute({
        "mode": "placement", "script": script, "project_dir": str(project),
        "public_root": str(tmp_path / "pub"), "section_options": options,
        "sentence_pause": pause, "safety_margin_s": 0.0,
    })
    assert res.success, res.error
    new = Path(res.data["version_dir"])

    # (a) identité octet par octet du traitement
    old_rows = json.loads((old / "timing_fr.json").read_text(encoding="utf-8"))
    for r in old_rows:
        assert _sha(old / "segments" / f"{r['cut']}.wav") == _sha(new / "segments" / f"{r['cut']}.wav"), r["cut"]
    assert _sha(old / "narration_fr.wav") == _sha(new / "narration_fr_brut.wav")

    # (b) même texte lu, mêmes phonèmes, mêmes placements
    new_rows = json.loads((new / "timing_fr.json").read_text(encoding="utf-8"))
    keys = ("cut", "texte_ecrit", "texte_lu", "phonemes", "debut", "fin", "fin_max", "duree",
            "syllabes", "syllabes_par_s", "mot_cle_a", "length_scale")
    assert [{k: r[k] for k in keys} for r in old_rows] == [{k: r[k] for k in keys} for r in new_rows]

    # (c) durées dans la variation naturelle de Piper vs la validation enregistrée
    ref = {r["cut"]: r for r in json.loads(
        (REPO / "projects" / "demos" / "fr-series" / name / "timing_fr.json").read_text(encoding="utf-8"))}
    for r in new_rows:
        assert r["texte_lu"] == ref[r["cut"]]["texte_lu"]
        assert r["phonemes"] == ref[r["cut"]]["phonemes"]
        assert abs(r["duree"] - ref[r["cut"]]["duree"]) <= NATURAL_SPREAD * ref[r["cut"]]["duree"], r["cut"]
