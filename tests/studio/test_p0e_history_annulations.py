"""Lot P0-E — R3 : une tentative de checkpoint annulée ne laisse aucune fausse version dans history/.

Les copies créées par la tentative sont déplacées (jamais supprimées) vers history/annulations/,
avec un journal ; les fichiers d'historique préexistants ne bougent pas ; le board Backlot ne compte
que les versions réelles. Dossier temporaire de pytest uniquement.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import lib.checkpoint as ckpt_lib
from backlot.state import load_board_state
from lib.studio import checkpoints as ckp
from lib.studio import render as ren
from tests.contracts.test_phase0_contracts import sample_artifact
from tests.studio import test_p0c_checkpoint_integrity as c0


@pytest.fixture(autouse=True)
def no_real_process(monkeypatch):
    def refuse(*_a, **_k):
        raise AssertionError("processus réel interdit dans les tests P0-E")
    monkeypatch.setattr(ren.subprocess, "Popen", refuse)
    monkeypatch.setattr(ren.subprocess, "run", refuse)


def history(p: Path) -> dict[str, bytes]:
    h = p / "history"
    return {f.name: f.read_bytes() for f in sorted(h.glob("checkpoint_script_*.json"))} if h.is_dir() else {}


def cancelled(p: Path) -> dict[str, bytes]:
    a = p / "history" / "annulations"
    return {f.name: f.read_bytes() for f in sorted(a.glob("checkpoint_*.json"))} if a.is_dir() else {}


def journal(p: Path) -> list[dict]:
    j = p / "history" / "annulations" / "annulations.jsonl"
    return [json.loads(line) for line in j.read_text(encoding="utf-8").splitlines()] if j.is_file() else []


def versions(p: Path, stage: str = "script") -> int:
    return next(s for s in load_board_state(p)["stages"] if s.get("name") == stage)["versions"]


def script_artifact(p: Path) -> dict:
    return json.loads((p / "script.json").read_text(encoding="utf-8"))


def cancel_once(p: Path, monkeypatch) -> ckp.CheckpointIntegrityError:
    monkeypatch.setattr(ckpt_lib, "write_checkpoint", c0._tampering_writer(ckpt_lib.write_checkpoint))
    with pytest.raises(ckp.CheckpointIntegrityError) as info:
        ckp.write_studio_checkpoint(p, "script", "completed", {"script": script_artifact(p)}, human_approved=True)
    monkeypatch.undo()
    return info.value


def test_cancelled_attempt_leaves_no_false_version(tmp_path, monkeypatch):
    p, _, _ = c0.run_until(tmp_path, "script")
    current = (p / "checkpoint_script.json").read_bytes()
    assert history(p) == {} and versions(p) == 1
    err = cancel_once(p, monkeypatch)
    assert "incohérent après écriture" in str(err)
    assert (p / "checkpoint_script.json").read_bytes() == current
    assert history(p) == {} and versions(p) == 1                       # aucune fausse version
    kept = cancelled(p)
    assert len(kept) == 1 and list(kept.values()) == [current]          # copie conservée, jamais supprimée
    entry = journal(p)[-1]
    assert entry["etape"] == "script" and entry["copies"] == list(kept) and entry["non_deplacees"] == []
    assert "CheckpointIntegrityError" in entry["motif"]
    assert ckp.verify_studio_checkpoints(p) == []


def test_successful_rewrite_after_cancellation_counts_real_versions_only(tmp_path, monkeypatch):
    p, _, _ = c0.run_until(tmp_path, "script")
    cancel_once(p, monkeypatch)
    ckp.write_studio_checkpoint(p, "script", "completed", {"script": script_artifact(p)}, human_approved=True)
    assert len(history(p)) == 1 and versions(p) == 2                   # 1 version archivée + courante
    assert len(cancelled(p)) == 1


def test_preexisting_history_files_are_untouched(tmp_path, monkeypatch):
    p, _, _ = c0.run_until(tmp_path, "script")
    for _ in range(2):                                                  # deux versions réelles archivées
        ckp.write_studio_checkpoint(p, "script", "completed", {"script": script_artifact(p)}, human_approved=True)
    before = history(p)
    assert len(before) == 2 and versions(p) == 3
    cancel_once(p, monkeypatch)
    assert history(p) == before                                         # mêmes noms, mêmes octets, même ordre
    assert versions(p) == 3 and len(cancelled(p)) == 1


def test_repeated_cancellations_accumulate_traces_without_overwriting(tmp_path, monkeypatch):
    p, _, _ = c0.run_until(tmp_path, "script")
    cancel_once(p, monkeypatch)
    cancel_once(p, monkeypatch)
    assert len(cancelled(p)) == 2 and len(journal(p)) == 2              # deux traces distinctes
    assert history(p) == {} and versions(p) == 1


def test_first_write_cancelled_leaves_nothing(tmp_path, monkeypatch):
    p, _, _ = c0.run_until(tmp_path, "idea")
    pp = sample_artifact("proposal_packet")
    pp.setdefault("approval", {})["status"] = "approved"
    monkeypatch.setattr(ckpt_lib, "write_checkpoint", c0._tampering_writer(ckpt_lib.write_checkpoint))
    with pytest.raises(ckp.CheckpointIntegrityError):
        ckp.write_studio_checkpoint(p, "proposal", "completed", {"proposal_packet": pp}, human_approved=True)
    assert not (p / "checkpoint_proposal.json").exists()
    assert not (p / "history" / "annulations").exists()


def test_failed_move_is_reported_and_nothing_is_deleted(tmp_path, monkeypatch):
    p, _, _ = c0.run_until(tmp_path, "script")
    real_rename = Path.rename

    def locked_rename(self, target):
        if self.parent.name == "history":
            raise PermissionError("fichier ouvert par l'observateur (simulé)")
        return real_rename(self, target)
    monkeypatch.setattr(Path, "rename", locked_rename)
    monkeypatch.setattr(ckpt_lib, "write_checkpoint", c0._tampering_writer(ckpt_lib.write_checkpoint))
    with pytest.raises(ckp.CheckpointIntegrityError, match="restauration incomplète") as info:
        ckp.write_studio_checkpoint(p, "script", "completed", {"script": script_artifact(p)}, human_approved=True)
    monkeypatch.undo()
    assert any("non déplacée vers annulations" in pb for pb in info.value.problems)
    assert len(history(p)) == 1                                         # copie laissée en place, pas supprimée
    assert journal(p)[-1]["non_deplacees"] == list(history(p))


def test_successful_writes_still_archive_normally(tmp_path):
    p, _, _ = c0.run_until(tmp_path, "script")
    ckp.write_studio_checkpoint(p, "script", "completed", {"script": script_artifact(p)}, human_approved=True)
    assert len(history(p)) == 1 and versions(p) == 2
    assert not (p / "history" / "annulations").exists()
