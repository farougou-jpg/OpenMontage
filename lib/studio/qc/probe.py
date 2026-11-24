"""Format du MP4 (ffprobe) — lecture seule."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

FPS = 30
WIDTH, HEIGHT = 1920, 1080


def ffprobe(path: Path) -> dict:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
                         capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def expected_frames(props: dict, fps: int = FPS) -> int:
    """Durée de la composition Explainer : fin de la dernière scène + tailPaddingSeconds (1 s par défaut)."""
    last = max(c["out_seconds"] for c in props["cuts"])
    tail = props.get("tailPaddingSeconds")
    tail = tail if isinstance(tail, (int, float)) else 1
    return int(-(-((last + tail) * fps) // 1))  # plafond, comme Math.ceil


def check_format(info: dict, props: dict, qc) -> dict:
    v = next((s for s in info["streams"] if s.get("codec_type") == "video"), None)
    a = next((s for s in info["streams"] if s.get("codec_type") == "audio"), None)
    m = {
        "video_codec": v and v.get("codec_name"), "largeur": v and v.get("width"), "hauteur": v and v.get("height"),
        "images_par_seconde": v and v.get("r_frame_rate"), "nb_images": int(v.get("nb_frames", 0)) if v else 0,
        "audio_codec": a and a.get("codec_name"), "audio_hz": a and a.get("sample_rate"),
        "duree_s": round(float(info["format"]["duration"]), 3),
        "nb_images_attendu": expected_frames(props),
    }
    qc.measures["format"] = m
    if not v:
        qc.block("Format", "aucune piste vidéo")
        return m
    problems = []
    if m["video_codec"] != "h264":
        problems.append(f"codec vidéo {m['video_codec']} (attendu h264)")
    if (m["largeur"], m["hauteur"]) != (WIDTH, HEIGHT):
        problems.append(f"{m['largeur']}×{m['hauteur']} (attendu 1920×1080)")
    if m["images_par_seconde"] != f"{FPS}/1":
        problems.append(f"{m['images_par_seconde']} i/s (attendu 30)")
    if abs(m["nb_images"] - m["nb_images_attendu"]) > 1:
        problems.append(f"{m['nb_images']} images (attendu {m['nb_images_attendu']} ± 1)")
    if m["audio_codec"] != "aac":
        problems.append(f"audio {m['audio_codec']} (attendu aac)")
    if problems:
        qc.block("Format", " ; ".join(problems))
    else:
        qc.ok("Format", f"1920×1080, 30 i/s, {m['nb_images']} images, {m['duree_s']} s, H.264 + AAC {m['audio_hz']} Hz")
    return m
