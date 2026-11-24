"""Contrôles visuels du MP4 : conformité au storyboard validé, noirs réels, images figées, planche.

Lecture seule du MP4 ; les images extraites vont dans le dossier de contrôle versionné.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

from lib.studio.storyboard.sheet import _font

MAX_MEAN_DIFF_PCT = 2.0          # écart moyen global (critère conservé)
# Anomalie localisée (décision du 2026-11-18) : après un flou de 1 px (efface le bruit de
# compression), un pixel est « fort » si son écart dépasse 60/255 sur un canal ; une tuile
# de 20×20 px contenant 3 pixels forts ou plus rend la scène non conforme, quelle que soit
# la moyenne globale. Calibré sur les 22 scènes des 5 vidéos françaises (0 ou 1 pixel fort).
TILE_PX, STRONG_DIFF, TILE_MIN_STRONG = 20, 60, 3
BLACK_PIX_TH, BLACK_MIN_S = 0.02, 0.5   # « vrai noir » : les fonds du thème (~9 %) ne comptent pas
FREEZE_NOISE_DB, FREEZE_MIN_S, FREEZE_SCENE_RATIO = -60, 2.0, 0.9


def extract_frame(mp4: Path, frame: int, out: Path) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(mp4),
                    "-vf", f"select=eq(n\\,{frame})", "-vframes", "1", str(out)], check=True)
    return out


def _blur(a: np.ndarray) -> np.ndarray:
    from PIL import ImageFilter
    return np.asarray(Image.fromarray(np.clip(a, 0, 255).astype(np.uint8)).filter(ImageFilter.BoxBlur(1)),
                      dtype=np.float32)


def compare_arrays(a: np.ndarray, b: np.ndarray) -> dict:
    """Écart moyen global (%) et pire tuile (nombre de pixels forts). Deux critères indépendants."""
    if a.shape != b.shape:
        return {"ecart_pct": 100.0, "max_pixels_forts_tuile": 10**6, "tuiles_anormales": 10**6}
    mean = float(np.abs(a - b).mean() / 255 * 100)
    h, w = a.shape[0] // TILE_PX * TILE_PX, a.shape[1] // TILE_PX * TILE_PX
    strong = (np.abs(_blur(a) - _blur(b)).max(axis=2) > STRONG_DIFF)[:h, :w]
    tiles = strong.reshape(h // TILE_PX, TILE_PX, w // TILE_PX, TILE_PX).sum(axis=(1, 3))
    return {"ecart_pct": mean, "max_pixels_forts_tuile": int(tiles.max()),
            "tuiles_anormales": int((tiles >= TILE_MIN_STRONG).sum())}


def is_conform(m: dict) -> bool:
    """Non conforme si la moyenne OU une tuile dépasse son seuil : la moyenne ne masque jamais une tuile."""
    return m["ecart_pct"] < MAX_MEAN_DIFF_PCT and m["max_pixels_forts_tuile"] < TILE_MIN_STRONG


def compare_files(a_path: Path, b_path: Path) -> dict:
    a = np.asarray(Image.open(a_path).convert("RGB"), dtype=np.float32)
    b = np.asarray(Image.open(b_path).convert("RGB"), dtype=np.float32)
    return compare_arrays(a, b)


def side_by_side(left: Path, right: Path, out: Path, caption: str) -> Path:
    w, h, pad, cap = 960, 540, 16, 44
    canvas = Image.new("RGB", (2 * w + 3 * pad, h + 2 * pad + cap), (250, 250, 250))
    for i, p in enumerate((left, right)):
        with Image.open(p) as im:
            canvas.paste(im.convert("RGB").resize((w, h), Image.LANCZOS), (pad + i * (w + pad), pad + cap))
    from PIL import ImageDraw
    ImageDraw.Draw(canvas).text((pad, 10), caption, font=_font(22), fill=(26, 26, 46))
    canvas.save(out)
    return out


def check_storyboard(mp4: Path, storyboard: dict, storyboard_dir: Path, out_dir: Path, qc) -> list[dict]:
    """Compare l'image du MP4 à l'image validée du storyboard, au même instant, pour chaque scène."""
    rows = []
    for s in storyboard["scenes"]:
        ref = storyboard_dir / s["image"]
        got = extract_frame(mp4, s["frame"], out_dir / "images" / f"mp4_{s['id']}.png")
        m = compare_files(ref, got)
        cmp = side_by_side(ref, got, out_dir / f"cmp_{s['id']}.png",
                           f"{s['id']} — image {s['frame']} — storyboard validé (gauche) / MP4 (droite) — "
                           f"écart moyen {m['ecart_pct']:.2f} % — pire tuile {m['max_pixels_forts_tuile']} px forts")
        ok = is_conform(m)
        rows.append({"scene": s["id"], "image": s["frame"], "ecart_pct": round(m["ecart_pct"], 3),
                     "max_pixels_forts_tuile": m["max_pixels_forts_tuile"],
                     "tuiles_anormales": m["tuiles_anormales"], "comparaison": cmp.name,
                     "statut": "✅" if ok else "❌"})
        if m["ecart_pct"] >= MAX_MEAN_DIFF_PCT:
            qc.block("Conformité visuelle", f"{s['id']} : écart moyen {m['ecart_pct']:.2f} % "
                                            f"(seuil {MAX_MEAN_DIFF_PCT} %)")
        if m["max_pixels_forts_tuile"] >= TILE_MIN_STRONG:
            qc.block("Conformité visuelle", f"{s['id']} : anomalie localisée — {m['tuiles_anormales']} tuile(s) "
                                            f"20×20 px avec ≥ {TILE_MIN_STRONG} pixels fortement différents "
                                            f"(pire : {m['max_pixels_forts_tuile']}), écart moyen "
                                            f"{m['ecart_pct']:.2f} %")
    if rows and all(r["statut"] == "✅" for r in rows):
        qc.ok("Conformité visuelle", f"{len(rows)} scène(s) identiques au storyboard validé "
                                    f"(écart moyen max {max(r['ecart_pct'] for r in rows):.2f} %, "
                                    f"pire tuile {max(r['max_pixels_forts_tuile'] for r in rows)} px forts)")
    qc.measures["conformite_visuelle"] = rows
    return rows


def check_black_freeze(mp4: Path, cuts: list[dict], qc) -> str:
    log = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(mp4), "-map", "0:v", "-vf",
                          f"blackdetect=d={BLACK_MIN_S}:pix_th={BLACK_PIX_TH},"
                          f"freezedetect=n={FREEZE_NOISE_DB}dB:d={FREEZE_MIN_S}", "-an", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    blacks = [(float(a), float(b)) for a, b in re.findall(r"black_start:([\d.]+) black_end:([\d.]+)", log)]
    fstarts = [float(x) for x in re.findall(r"freeze_start: ([\d.]+)", log)]
    fdurs = [float(x) for x in re.findall(r"freeze_duration: ([\d.]+)", log)]
    qc.measures["noirs"] = blacks
    qc.measures["images_figees"] = list(zip(fstarts, fdurs))
    if blacks:
        qc.block("Images noires", " ; ".join(f"{a:.2f}–{b:.2f} s" for a, b in blacks))
    else:
        qc.ok("Images noires", "aucun noir réel ≥ 0,5 s")
    flagged = []
    for start, dur in zip(fstarts, fdurs):
        for c in cuts:
            length = c["out_seconds"] - c["in_seconds"]
            overlap = max(0.0, min(start + dur, c["out_seconds"]) - max(start, c["in_seconds"]))
            if length > 0 and overlap / length >= FREEZE_SCENE_RATIO:
                flagged.append(f"{c['id']} figée {overlap:.1f} s sur {length:.1f} s")
    if flagged:
        qc.warn("Images figées", " ; ".join(flagged) + " (scène sans animation visible ?)")
    else:
        qc.ok("Images figées", "plans fixes normaux uniquement (< 90 % d'une scène)")
    return "\n".join(l for l in log.splitlines() if "black_" in l or "freeze_" in l)


def contact_sheet(mp4: Path, out: Path, fps: float = 2.0, cols: int = 8) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="qc_planche_"))
    try:
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(mp4), "-vf",
                        f"fps={fps},scale=320:180", str(tmp / "f_%04d.png")], check=True)
        frames = sorted(tmp.glob("f_*.png"))
        rows = (len(frames) + cols - 1) // cols
        sheet = Image.new("RGB", (cols * 324 + 4, rows * 184 + 4), (240, 240, 240))
        for i, f in enumerate(frames):
            with Image.open(f) as im:
                sheet.paste(im.convert("RGB"), (4 + (i % cols) * 324, 4 + (i // cols) * 184))
        sheet.save(out)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return out
