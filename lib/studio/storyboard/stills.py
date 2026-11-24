"""Images fixes du storyboard : choix de l'instant et rendu local via Remotion `still`.

Rendu 100 % local : binaire Remotion du projet (pas `npx`), navigateur
chrome-headless-shell déjà installé passé explicitement (aucun téléchargement
possible), configuration FR v3, cache webpack désactivé (rien n'est écrit dans
node_modules).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Optional

from lib.studio.storyboard.props_check import FINAL_STATE_TYPES, FPS, fade_frames

REPO_ROOT = Path(__file__).resolve().parents[3]
COMPOSER = REPO_ROOT / "remotion-composer"
REMOTION_CLI = COMPOSER / "node_modules" / "@remotion" / "cli" / "remotion-cli.js"
CHROME = (COMPOSER / "node_modules" / ".remotion" / "chrome-headless-shell" / "win64"
          / "chrome-headless-shell-win64" / "chrome-headless-shell.exe")
# v4 = v3 + StatCard en Space Grotesk : configuration des nouvelles productions du studio.
# v3 reste disponible pour comparer avec les vidéos françaises validées (rendues avant la v4).
FR_CONFIG_V3 = "remotion.fr-locale-v3.config.ts"
FR_CONFIG_V4 = "remotion.fr-locale-v4.config.ts"
FR_CONFIG = FR_CONFIG_V4
ALLOWED_CONFIGS = (FR_CONFIG_V3, FR_CONFIG_V4)
ENTRY = "src/index.tsx"
MIN_AFTER_START_S = 1.5
SAFETY_FRAMES = 3


class StillRenderError(RuntimeError):
    """Le rendu d'une image fixe a échoué."""


def choose_frame(cut: dict, fps: int = FPS, override_s: Optional[float] = None) -> int:
    """Instant lisible : après l'animation d'entrée, jamais pendant le fondu de sortie."""
    first = round(cut["in_seconds"] * fps)
    end = round(cut["out_seconds"] * fps)          # première image de la scène suivante
    latest = end - fade_frames(cut, fps) - SAFETY_FRAMES
    if latest <= first:
        latest = max(first, end - 1)
    if override_s is not None:
        frame = round(override_s * fps)
    elif cut.get("type") in FINAL_STATE_TYPES:
        frame = latest
    else:
        dur = end - first
        frame = first + max(round(MIN_AFTER_START_S * fps), round(0.6 * dur))
    return int(min(max(frame, first + 1 if latest > first else first), latest))


def renderer_available() -> bool:
    return REMOTION_CLI.is_file() and CHROME.is_file() and shutil.which("node") is not None


def check_config(config: str) -> str:
    if config not in ALLOWED_CONFIGS:
        raise ValueError(f"Configuration de rendu non autorisée : {config!r} (autorisées : {ALLOWED_CONFIGS})")
    return config


def still_command(props_path: Path, frame: int, out_png: Path, composition: str = "Explainer",
                  config: str = FR_CONFIG) -> list[str]:
    return [
        shutil.which("node") or "node", str(REMOTION_CLI), "still", ENTRY, composition, str(out_png),
        f"--props={props_path}", f"--frame={frame}", f"--config={check_config(config)}",
        f"--browser-executable={CHROME}", "--bundle-cache=false", "--log=error",
    ]


def render_still(props_path: Path, frame: int, out_png: Path, composition: str = "Explainer",
                 timeout: int = 300, config: str = FR_CONFIG) -> Path:
    if not renderer_available():
        raise StillRenderError("Rendu local indisponible (Remotion, navigateur local ou Node absent).")
    cmd = still_command(props_path, frame, out_png, composition, config)
    out_png.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(cmd, cwd=str(COMPOSER),
                          capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    if proc.returncode != 0 or not out_png.is_file():
        raise StillRenderError(f"Échec du rendu (image {frame}) : {(proc.stderr or proc.stdout)[-800:]}")
    return out_png
