"""Planche de storyboard (PNG), page HTML hors ligne, Markdown et JSON."""

from __future__ import annotations

import html
import json
import textwrap
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

FONT_CANDIDATES = (Path(r"C:\Windows\Fonts\segoeui.ttf"), Path(r"C:\Windows\Fonts\arial.ttf"))
FONT_BOLD_CANDIDATES = (Path(r"C:\Windows\Fonts\segoeuib.ttf"), Path(r"C:\Windows\Fonts\arialbd.ttf"))
THUMB_W, THUMB_H = 640, 360
CAPTION_H = 190
GAP = 24
COLUMNS = 3
BG, FG, MUTED, ACCENT = (250, 250, 250), (26, 26, 46), (96, 104, 120), (124, 58, 237)


@dataclass
class SceneEntry:
    number: int
    id: str
    start: float
    end: float
    type: str
    screen_text: str
    narration: str
    transition: str
    frame: int
    image: str  # chemin relatif au dossier de version


def fr_seconds(x: float) -> str:
    return f"{x:.1f}".replace(".", ",") + " s"


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    for p in (FONT_BOLD_CANDIDATES if bold else FONT_CANDIDATES) + FONT_CANDIDATES:
        if p.is_file():
            return ImageFont.truetype(str(p), size)
    raise FileNotFoundError("Aucune police système avec accents trouvée (segoeui.ttf / arial.ttf).")


def build_sheet(entries: list[SceneEntry], version_dir: Path, title: str) -> Path:
    rows = (len(entries) + COLUMNS - 1) // COLUMNS
    head = 90
    w = COLUMNS * THUMB_W + (COLUMNS + 1) * GAP
    h = head + rows * (THUMB_H + CAPTION_H + GAP) + GAP
    sheet = Image.new("RGB", (w, h), BG)
    d = ImageDraw.Draw(sheet)
    d.text((GAP, 28), title, font=_font(34, bold=True), fill=FG)
    f_head, f_body, f_small = _font(22, bold=True), _font(19), _font(17)
    for i, e in enumerate(entries):
        x = GAP + (i % COLUMNS) * (THUMB_W + GAP)
        y = head + (i // COLUMNS) * (THUMB_H + CAPTION_H + GAP)
        with Image.open(version_dir / e.image) as im:
            sheet.paste(im.convert("RGB").resize((THUMB_W, THUMB_H), Image.LANCZOS), (x, y))
        d.rectangle([x, y, x + THUMB_W - 1, y + THUMB_H - 1], outline=(210, 210, 220))
        cy = y + THUMB_H + 8
        d.text((x, cy), f"Scène {e.number} · {fr_seconds(e.start)} – {fr_seconds(e.end)} · {e.type}",
               font=f_head, fill=ACCENT)
        cy += 32
        for line in textwrap.wrap(f"Écran : {e.screen_text}", 58)[:3]:
            d.text((x, cy), line, font=f_body, fill=FG)
            cy += 25
        if e.narration:
            for line in textwrap.wrap(f"Narration : {e.narration}", 64)[:2]:
                d.text((x, cy), line, font=f_small, fill=MUTED)
                cy += 22
        d.text((x, y + THUMB_H + CAPTION_H - 26), f"Sortie : {e.transition}", font=f_small, fill=MUTED)
    out = version_dir / "planche.png"
    sheet.save(out)
    return out


def write_documents(entries: list[SceneEntry], version_dir: Path, title: str,
                    meta: Optional[dict] = None) -> dict[str, Path]:
    meta = meta or {}
    js = version_dir / "storyboard.json"
    js.write_text(json.dumps({"titre": title, **meta, "scenes": [asdict(e) for e in entries]},
                             ensure_ascii=False, indent=2), encoding="utf-8")

    md_lines = [f"# Storyboard — {title}", "",
                *[f"- {k} : {v}" for k, v in meta.items()], "",
                "| # | Temps | Type | Texte à l'écran | Narration | Sortie | Image |",
                "|---|---|---|---|---|---|---|",
                *[f"| {e.number} | {fr_seconds(e.start)} – {fr_seconds(e.end)} | `{e.type}` | {e.screen_text} | "
                  f"{e.narration or '—'} | {e.transition} | ![]({e.image}) |" for e in entries]]
    md = version_dir / "storyboard.md"
    md.write_text("\n".join(md_lines) + "\n", encoding="utf-8")

    esc = html.escape
    cards = "\n".join(
        f"<figure><img src=\"{esc(e.image)}\" alt=\"Scène {e.number}\">"
        f"<figcaption><b>Scène {e.number}</b> · {esc(fr_seconds(e.start))} – {esc(fr_seconds(e.end))} · "
        f"<code>{esc(e.type)}</code><br>Écran : {esc(e.screen_text)}<br>"
        f"<i>Narration : {esc(e.narration or '—')}</i><br>Sortie : {esc(e.transition)}</figcaption></figure>"
        for e in entries)
    meta_html = "".join(f"<li>{esc(str(k))} : {esc(str(v))}</li>" for k, v in meta.items())
    page = (
        "<!doctype html><html lang=\"fr\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        f"<title>Storyboard</title><style>"
        "body{margin:0;padding:16px;font-family:system-ui,'Segoe UI',sans-serif;background:#fafafa;color:#1a1a2e}"
        "h1{font-size:1.5rem}main{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:20px}"
        "figure{margin:0;background:#fff;border:1px solid #ddd;border-radius:8px;overflow:hidden}"
        "img{width:100%;height:auto;display:block}figcaption{padding:10px 12px;font-size:.9rem;line-height:1.45}"
        "code{background:#eee;padding:0 4px;border-radius:3px}"
        f"</style></head><body><h1>Storyboard — {esc(title)}</h1><ul>{meta_html}</ul><main>{cards}</main>"
        "</body></html>")
    page_path = version_dir / "storyboard.html"
    page_path.write_text(page, encoding="utf-8")
    return {"json": js, "md": md, "html": page_path}
