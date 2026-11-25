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


def render_provenance(project_dir: Path, render_version: str) -> dict:
    """Prouve qu'un rendu `renders/vNNN` vient de `run_render`, sur les validations 2 et 3 actuelles (P0-C).

    Exige, sinon `RenderError` : manifeste `rendu.json` ; un seul MP4, celui du manifeste, avec la même
    empreinte SHA-256 et la même taille ; versions du storyboard et de la narration égales aux validations
    2 et 3, toutes deux à jour ; configuration de rendu du storyboard validé ; `props_rendu.json` égal aux
    props du storyboard validé augmentées de la piste de la narration validée. Lecture seule.
    """
    p = Path(project_dir)
    from lib.studio.project import versions
    if render_version not in versions(p / "renders"):
        raise RenderError(f"Rendu introuvable : renders/{render_version}.")
    r = p / "renders" / render_version
    info = read_json(r / "rendu.json")
    if not isinstance(info, dict):
        raise RenderError("Provenance invérifiable : rendu.json absent (MP4 non produit par render.py).")
    mp4s = sorted(f.name for f in r.glob("*.mp4"))
    if info.get("mp4") != OUTPUT_NAME or mp4s != [OUTPUT_NAME]:
        raise RenderError(f"Provenance invérifiable : un seul MP4 attendu ({OUTPUT_NAME}), trouvé(s) : {mp4s}.")
    mp4 = r / OUTPUT_NAME
    if info.get("sha256") != sha256(mp4) or info.get("taille_octets") != mp4.stat().st_size:
        raise RenderError("Provenance invérifiable : le MP4 ne correspond plus au manifeste rendu.json.")
    for kind in ("storyboard", "narration"):
        ok, why = is_current(p, kind)
        if not ok:
            raise RenderError(f"Provenance invérifiable : {why}.")
    vals = validations_by_kind(p)
    sb_v, nar_v = vals["storyboard"].get("version"), vals["narration"].get("version")
    if info.get("storyboard") != sb_v or info.get("narration") != nar_v:
        raise RenderError(f"Rendu produit sur storyboard {info.get('storyboard')} / narration {info.get('narration')}, "
                          f"validés : {sb_v} / {nar_v}.")
    if info.get("configuration_rendu") != vals["storyboard"].get("configuration_rendu"):
        raise RenderError("Configuration de rendu différente de celle du storyboard validé.")
    audio_src = f"audio/studio/{p.name}/{nar_v}/narration_fr.wav"
    expected = read_json(p / "storyboard" / sb_v / "props_storyboard.json")
    if not isinstance(expected, dict) or info.get("audio") != audio_src:
        raise RenderError("Props du storyboard validé illisibles ou piste audio inattendue.")
    expected = {**expected, "audio": {"narration": {"src": audio_src, "volume": 1.0}}}
    if read_json(r / "props_rendu.json") != expected:
        raise RenderError("props_rendu.json ne correspond pas au storyboard et à la narration validés.")
    return {"version": render_version, "mp4": str(mp4), "sha256": info["sha256"], "taille_octets": info["taille_octets"],
            "storyboard": sb_v, "narration": nar_v}


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
           "render_provenance", "run_render"]
