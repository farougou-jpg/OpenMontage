"""Regression tests for an external OPENMONTAGE_PROJECTS_DIR.

The variable is read at import time by lib.paths, so each scenario runs in a
fresh Python subprocess. The tests only evaluate the write policy; they do not
create, modify, or delete project files.
"""

import os
import subprocess
import sys
from pathlib import Path


def _run_policy_check(projects_root: Path, target: Path, expected: str) -> None:
    code = r"""
import sys
from pathlib import Path
from lib.paths import PROJECTS_DIR
from lib.studio.narration.tool import PathPolicyError, check_write_zone

projects_root = Path(sys.argv[1]).resolve()
target = Path(sys.argv[2]).resolve()
expected = sys.argv[3]

assert PROJECTS_DIR.resolve() == projects_root, (
    f"PROJECTS_DIR={PROJECTS_DIR!s}, expected={projects_root!s}"
)

try:
    result = check_write_zone(target, PROJECTS_DIR)
except PathPolicyError:
    actual = "denied"
else:
    actual = "allowed"
    assert result == target

assert actual == expected, (
    f"target={target!s}: expected {expected}, got {actual}"
)
"""
    env = os.environ.copy()
    env["OPENMONTAGE_PROJECTS_DIR"] = str(projects_root)
    repo_root = Path(__file__).resolve().parents[1]
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(repo_root) + (os.pathsep + existing if existing else "")
    completed = subprocess.run(
        [sys.executable, "-c", code, str(projects_root), str(target), expected],
        cwd=repo_root,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, (
        f"Policy subprocess failed ({completed.returncode}).\n"
        f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
    )


def test_external_projects_root_allows_a_project_directory(tmp_path):
    projects_root = tmp_path / "external-projects"
    target = projects_root / "nouveau-projet" / "assets" / "narration"
    _run_policy_check(projects_root, target, "allowed")


def test_external_projects_root_still_protects_its_demos_directory(tmp_path):
    projects_root = tmp_path / "external-projects"
    target = projects_root / "demos" / "video-validee"
    _run_policy_check(projects_root, target, "denied")


def test_external_projects_root_rejects_historical_repo_pilot(tmp_path):
    projects_root = tmp_path / "external-projects"
    repo_root = Path(__file__).resolve().parents[1]
    target = repo_root / "projects" / "pilote-gestion-temps" / "assets"
    _run_policy_check(projects_root, target, "denied")


def test_external_projects_root_rejects_protected_historical_audio(tmp_path):
    projects_root = tmp_path / "external-projects"
    repo_root = Path(__file__).resolve().parents[1]
    target = (
        repo_root / "remotion-composer" / "public" / "audio"
        / "fr-series" / "video-validee"
    )
    _run_policy_check(projects_root, target, "denied")
