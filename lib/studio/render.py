"""OpenMontage Studio — rendu vidéo final et contrôle qualité enchaîné (étape G0).

Reprend la méthode utilisée pour le pilote (rendu Remotion local, sans réseau) :
- props = `props_storyboard.json` du storyboard VALIDÉ, plus la piste de la narration
  VALIDÉE (copie Remotion `public/audio/studio/<projet>/vNNN/narration_fr.wav`) ;
- configuration = celle inscrite dans le storyboard validé (v3 ou v4 uniquement) ;
- binaire Remotion du projet, navigateur local, `--bundle-cache=false` ;
- nouveau dossier `renders/vNNN/` à chaque rendu, jamais d'écrasement ; en cas d'échec
  ou d'annulation, le dossier créé par CET appel est retiré.

L'exécution passe par un `runner` injectable : les tests n'effectuent aucun rendu réel.
"""

from __future__ import annotations

import shutil
import subprocess
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from lib.studio.budget_guard import StudioBudgetGuard
from lib.studio.narration.tool import PROJECTS_ROOT, PUBLIC_STUDIO_ROOT, check_write_zone, next_version_dir
from lib.studio.project import read_json, require_writable, write_json
from lib.studio.storyboard.stills import CHROME, COMPOSER, ENTRY, REMOTION_CLI, check_config, renderer_available
from lib.studio.validations import ValidationError, is_current, sha256, validations_by_kind

COMPOSITION = "Explainer"
OUTPUT_NAME = "video.mp4"

Runner = Callable[[list[str], Path, Callable[[str], None], threading.Event], int]


class RenderError(RuntimeError):
    """Rendu refusé ou en échec."""


@dataclass
class RenderPlan:
    project_dir: Path
    storyboard_version: str
    narration_version: str
    config: str
    props: dict
    audio_src: str
    public_wav: Path
    notes: list[str] = field(default_factory=list)


def render_command(props_path: Path, out_mp4: Path, config: str) -> list[str]:
    return [shutil.which("node") or "node", str(REMOTION_CLI), "render", ENTRY, COMPOSITION, str(out_mp4),
            f"--props={props_path}", f"--config={check_config(config)}", f"--browser-executable={CHROME}",
            "--bundle-cache=false", "--log=info"]


def prepare_render(project_dir: Path, studio_audio_root: Path = PUBLIC_STUDIO_ROOT) -> RenderPlan:
    """Vérifie les validations 2 et 3 (à jour) et prépare les props. N'écrit rien."""
    p = Path(project_dir)
    require_writable(p)
    for kind in ("storyboard", "narration"):
        ok, why = is_current(p, kind)
        if not ok:
            raise RenderError(f"Rendu refusé : {why}.")
    vals = validations_by_kind(p)
    sb_v, nar_v = vals["storyboard"]["version"], vals["narration"]["version"]
    config = check_config(vals["storyboard"]["configuration_rendu"])
    props = read_json(p / "storyboard" / sb_v / "props_storyboard.json")
    if not isinstance(props, dict) or not props.get("cuts"):
        raise RenderError("props_storyboard.json du storyboard validé illisible.")
    public = Path(studio_audio_root) / p.name / nar_v / "narration_fr.wav"
    if not public.is_file() or sha256(public) != vals["narration"].get("copie_remotion_sha256"):
        raise RenderError("Copie Remotion de la narration validée absente ou modifiée.")
    audio_src = f"audio/studio/{p.name}/{nar_v}/narration_fr.wav"
    props = {**props, "audio": {"narration": {"src": audio_src, "volume": 1.0}}}
    return RenderPlan(p, sb_v, nar_v, config, props, audio_src, public)


def _default_runner(cmd: list[str], cwd: Path, on_line: Callable[[str], None], cancel: threading.Event) -> int:
    proc = subprocess.Popen(cmd, cwd=str(cwd), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace")
    done = threading.Event()

    def watch() -> None:
        while not done.wait(0.2):
            if cancel.is_set() and proc.poll() is None:
                proc.kill()

    threading.Thread(target=watch, daemon=True).start()
    try:
        for line in proc.stdout:  # type: ignore[union-attr]
            on_line(line.rstrip())
        return proc.wait()
    finally:
        done.set()


def run_render(plan: RenderPlan, runner: Optional[Runner] = None, on_line: Callable[[str], None] = lambda _l: None,
               cancel: Optional[threading.Event] = None) -> dict:
    """Rend la vidéo dans un nouveau `renders/vNNN/`. Retire ce dossier en cas d'échec ou d'annulation."""
    if runner is None and not renderer_available():
        raise RenderError("Rendu local indisponible (Remotion, navigateur local ou Node absent).")
    p = require_writable(plan.project_dir)
    renders = check_write_zone(p / "renders", PROJECTS_ROOT)
    cancel = cancel or threading.Event()
    out = next_version_dir(renders)
    try:
        props_path = out / "props_rendu.json"
        write_json(props_path, plan.props)
        mp4 = out / OUTPUT_NAME
        code = (runner or _default_runner)(render_command(props_path, mp4, plan.config), COMPOSER, on_line, cancel)
        if cancel.is_set():
            raise RenderError("Rendu annulé.")
        if code != 0 or not mp4.is_file() or mp4.stat().st_size == 0:
            raise RenderError(f"Échec du rendu (code {code}).")
        write_json(out / "rendu.json", {"storyboard": plan.storyboard_version, "narration": plan.narration_version,
                                        "configuration_rendu": plan.config, "audio": plan.audio_src,
                                        "mp4": OUTPUT_NAME, "sha256": sha256(mp4), "taille_octets": mp4.stat().st_size})
        return {"version_dir": str(out), "version": out.name, "mp4": str(mp4), "sha256": sha256(mp4)}
    except BaseException:
        shutil.rmtree(out, ignore_errors=True)
        raise


def check_render(project_dir: Path, render_version: str, tool: Any = None, title: Optional[str] = None) -> Any:
    """Contrôle qualité automatique du rendu (outil du lot 1.6, via le garde-fou). Renvoie le ToolResult."""
    from lib.studio.qc import QualityControlTool
    p = require_writable(Path(project_dir))
    r = p / "renders" / render_version
    info = read_json(r / "rendu.json")
    if not isinstance(info, dict):
        raise RenderError(f"Rendu {render_version} introuvable ou incomplet.")
    if sha256(r / info["mp4"]) != info["sha256"]:
        raise RenderError("Le MP4 a changé depuis le rendu : contrôle refusé.")
    inputs = {"mp4": str(r / info["mp4"]), "props": str(r / "props_rendu.json"),
              "timing": str(p / "assets" / "narration" / info["narration"] / "timing_fr.json"),
              "storyboard_dir": str(p / "storyboard" / info["storyboard"]), "script": str(p / "script.json"),
              "project_dir": str(p), "title": title or p.name}
    return StudioBudgetGuard(p).run(tool or QualityControlTool(), inputs)


__all__ = ["RenderError", "RenderPlan", "ValidationError", "check_render", "prepare_render", "render_command",
           "run_render"]
