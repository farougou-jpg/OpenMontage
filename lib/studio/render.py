"""OpenMontage Studio — rendu vidéo final et contrôle qualité enchaîné (étape G0).

Reprend la méthode utilisée pour le pilote (rendu Remotion local, sans réseau) :
- props = `props_storyboard.json` du storyboard VALIDÉ, plus la piste de la narration
  VALIDÉE (copie Remotion `public/audio/studio/<projet>/vNNN/narration_fr.wav`) ;
- configuration = celle inscrite dans le storyboard validé (v3 ou v4 uniquement) ;
- binaire Remotion du projet, navigateur local, `--bundle-cache=false` ;
- nouveau dossier `renders/vNNN/` à chaque rendu, jamais d'écrasement ; en cas d'échec
  ou d'annulation, le dossier créé par CET appel est retiré.

P0-E (R6) : le rendu lit EXCLUSIVEMENT une copie de la piste propre à ce rendu
(`<racine audio>/<projet>/<narration>/rendus/<rendu>/narration_fr.wav`, en lecture seule), créée
depuis la copie Remotion validée et dont l'empreinte SHA-256 est comparée à celle de la
validation 3 avant ET après le moteur. `rendu.json` inscrit `audio_sha256` et le chemin de cette
copie ; `render_provenance` (donc la validation 4 et l'export) refuse tout rendu sans cette preuve.

L'exécution passe par un `runner` injectable : les tests n'effectuent aucun rendu réel.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
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
AUDIO_NAME = "narration_fr.wav"
RENDER_AUDIO_DIR = "rendus"      # sous-dossier des copies de piste propres à chaque rendu (P0-E, R6)

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


def _require_trusted_checkpoints(p: Path) -> None:
    """P0-D (R1) : aucun composant Studio n'avance sur un checkpoint non vérifié.

    Un checkpoint écrit hors `write_studio_checkpoint`, modifié après écriture ou lié à une
    validation remplacée n'est jamais considéré comme intègre : le rendu et le contrôle sont refusés.
    """
    from lib.studio.checkpoints import verify_studio_checkpoints
    problems = verify_studio_checkpoints(p)
    if problems:
        raise RenderError("Refusé : checkpoints Studio non fiables (" + " ; ".join(problems) + ").")


def render_audio_src(project: str, narration_version: str, render_version: str) -> str:
    """Chemin Remotion (relatif à `public/`) de la copie de piste propre à un rendu (P0-E, R6)."""
    return f"audio/studio/{project}/{narration_version}/{RENDER_AUDIO_DIR}/{render_version}/{AUDIO_NAME}"


def _remove_tree(path: Path) -> None:
    """Retire un dossier créé par cet appel, y compris des fichiers mis en lecture seule."""
    def unlock(func, target, _exc):
        os.chmod(target, stat.S_IWRITE)
        func(target)
    if path.exists():
        shutil.rmtree(path, onexc=unlock)


def render_command(props_path: Path, out_mp4: Path, config: str) -> list[str]:
    return [shutil.which("node") or "node", str(REMOTION_CLI), "render", ENTRY, COMPOSITION, str(out_mp4),
            f"--props={props_path}", f"--config={check_config(config)}", f"--browser-executable={CHROME}",
            "--bundle-cache=false", "--log=info"]


def prepare_render(project_dir: Path, studio_audio_root: Path = PUBLIC_STUDIO_ROOT) -> RenderPlan:
    """Vérifie les validations 2 et 3 (à jour) et prépare les props. N'écrit rien."""
    p = Path(project_dir)
    require_writable(p)
    _require_trusted_checkpoints(p)
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
    _require_trusted_checkpoints(p)
    # P0-E (R6) : empreinte de référence = copie Remotion inscrite dans la validation 3, encore à jour.
    ok, why = is_current(p, "narration")
    narration = validations_by_kind(p).get("narration") or {}
    expected_audio = narration.get("copie_remotion_sha256")
    if not ok or narration.get("version") != plan.narration_version or not isinstance(expected_audio, str):
        raise RenderError(f"Rendu refusé : narration validée absente, périmée ou différente du plan ({why}).")
    renders = check_write_zone(p / "renders", PROJECTS_ROOT)
    cancel = cancel or threading.Event()
    out = next_version_dir(renders)
    audio_dir: Optional[Path] = None
    try:
        # 1-3. Copie immuable propre à ce rendu, depuis les octets VALIDÉS (vérifiés avant la copie).
        source_bytes = plan.public_wav.read_bytes() if plan.public_wav.is_file() else b""
        if hashlib.sha256(source_bytes).hexdigest() != expected_audio:
            raise RenderError("Rendu refusé : la copie Remotion de la narration n'est plus celle de la validation 3.")
        audio_root = plan.public_wav.parents[2]                 # <racine>/<projet>/<narration>/narration_fr.wav
        target_dir = check_write_zone(audio_root / p.name / plan.narration_version / RENDER_AUDIO_DIR / out.name,
                                      PUBLIC_STUDIO_ROOT)
        if target_dir.exists():
            raise RenderError(f"Copie de piste déjà présente pour {out.name} : jamais d'écrasement.")
        target_dir.mkdir(parents=True)
        audio_dir = target_dir
        audio_copy = target_dir / AUDIO_NAME
        audio_copy.write_bytes(source_bytes)
        os.chmod(audio_copy, stat.S_IREAD)                      # lecture seule : copie immuable du rendu
        audio_src = render_audio_src(p.name, plan.narration_version, out.name)
        props = {**plan.props, "audio": {"narration": {"src": audio_src, "volume": 1.0}}}
        props_path = out / "props_rendu.json"
        write_json(props_path, props)
        mp4 = out / OUTPUT_NAME
        # 4. Vérification juste avant le moteur.
        if sha256(audio_copy) != expected_audio:
            raise RenderError("Rendu refusé : copie de piste du rendu différente de la validation 3.")
        code = (runner or _default_runner)(render_command(props_path, mp4, plan.config), COMPOSER, on_line, cancel)
        if cancel.is_set():
            raise RenderError("Rendu annulé.")
        if code != 0 or not mp4.is_file() or mp4.stat().st_size == 0:
            raise RenderError(f"Échec du rendu (code {code}).")
        # 5. Vérification juste après le moteur.
        if not audio_copy.is_file() or sha256(audio_copy) != expected_audio:
            raise RenderError("Rendu refusé : la copie de piste du rendu a changé pendant le rendu.")
        write_json(out / "rendu.json", {"storyboard": plan.storyboard_version, "narration": plan.narration_version,
                                        "configuration_rendu": plan.config, "audio": audio_src,
                                        "audio_sha256": expected_audio, "audio_copie": str(audio_copy),
                                        "mp4": OUTPUT_NAME, "sha256": sha256(mp4), "taille_octets": mp4.stat().st_size})
        return {"version_dir": str(out), "version": out.name, "mp4": str(mp4), "sha256": sha256(mp4),
                "audio_sha256": expected_audio, "audio_copie": str(audio_copy)}
    except BaseException:
        shutil.rmtree(out, ignore_errors=True)
        if audio_dir is not None:
            try:
                _remove_tree(audio_dir)
            except OSError:
                pass
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
    audio_src = render_audio_src(p.name, nar_v, render_version)
    expected = read_json(p / "storyboard" / sb_v / "props_storyboard.json")
    if not isinstance(expected, dict) or info.get("audio") != audio_src:
        raise RenderError("Props du storyboard validé illisibles ou piste audio inattendue.")
    expected = {**expected, "audio": {"narration": {"src": audio_src, "volume": 1.0}}}
    if read_json(r / "props_rendu.json") != expected:
        raise RenderError("props_rendu.json ne correspond pas au storyboard et à la narration validés.")
    # P0-E (R6) : octets audio réellement utilisés = octets de la validation 3.
    audio_sha = info.get("audio_sha256")
    if not isinstance(audio_sha, str) or not audio_sha:
        raise RenderError("Provenance invérifiable : audio_sha256 absent de rendu.json (piste du rendu non prouvée).")
    if audio_sha != vals["narration"].get("copie_remotion_sha256"):
        raise RenderError("Piste audio du rendu différente de la narration validée (validation 3).")
    copy = Path(str(info.get("audio_copie") or ""))
    suffix = (p.name, nar_v, RENDER_AUDIO_DIR, render_version, AUDIO_NAME)
    if copy.parts[-5:] != suffix or not copy.is_file() or sha256(copy) != audio_sha:
        raise RenderError("Copie de piste propre au rendu absente, déplacée ou modifiée.")
    return {"version": render_version, "mp4": str(mp4), "sha256": info["sha256"], "taille_octets": info["taille_octets"],
            "storyboard": sb_v, "narration": nar_v, "audio_sha256": audio_sha}


def check_render(project_dir: Path, render_version: str, tool: Any = None, title: Optional[str] = None) -> Any:
    """Contrôle qualité automatique du rendu (outil du lot 1.6, via le garde-fou). Renvoie le ToolResult."""
    from lib.studio.qc import QualityControlTool
    p = require_writable(Path(project_dir))
    _require_trusted_checkpoints(p)
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


__all__ = ["RenderError", "RenderPlan", "ValidationError", "check_render", "prepare_render", "render_audio_src",
           "render_command", "render_provenance", "run_render"]
