"""Outil storyboard du studio : une image fixe par scène + planche, HTML, Markdown.

Local, gratuit, hors registre automatique, appelé via le garde-fou budgétaire.
Écritures : ``projects/<projet>/storyboard/vNNN/`` (ou le dossier temporaire du
système pour les tests) ; zones protégées refusées ; jamais d'écrasement.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from tools.base_tool import BaseTool, ToolResult, ToolRuntime, ToolStability, ToolTier

from lib.studio.narration.tool import PROJECTS_ROOT, PathPolicyError, check_write_zone, next_version_dir
from lib.studio.storyboard.props_check import FPS, check_props, transition_label
from lib.studio.storyboard.sheet import SceneEntry, build_sheet, write_documents
from lib.studio.storyboard.stills import FR_CONFIG, StillRenderError, check_config, choose_frame, render_still


def _screen_text(cut: dict) -> str:
    if cut.get("type") == "comparison":
        return f"{cut.get('leftLabel', '')} : {cut.get('leftValue', '')} / {cut.get('rightLabel', '')} : {cut.get('rightValue', '')}"
    parts = [cut.get(k) for k in ("title", "text", "stat", "subtitle", "heroSubtitle", "progressLabel")]
    if cut.get("chartData"):
        parts.append(", ".join(str(d.get("label", "")) for d in cut["chartData"][:6]))
    return " — ".join(str(p) for p in parts if p) or "—"


class StoryboardTool(BaseTool):
    name = "studio_storyboard"
    version = "1.0.0"
    tier = ToolTier.CORE
    capability = "storyboard_fr"
    provider = "remotion"
    runtime = ToolRuntime.LOCAL
    stability = ToolStability.EXPERIMENTAL
    dependencies = ["cmd:node"]
    input_schema = {
        "type": "object",
        "required": ["props", "project_dir"],
        "properties": {
            "props": {"description": "props Explainer (dict) ou chemin JSON — brouillon gabarits"},
            "project_dir": {"type": "string"},
            "title": {"type": "string"},
            "narration": {"type": "object", "description": "{id_scene: extrait de narration}"},
            "still_at_seconds": {"type": "object", "description": "{id_scene: instant forcé (s)}"},
            "meta": {"type": "object"},
            "remotion_config": {"type": "string", "description": "configuration de rendu FR : v4 (défaut) ou v3"},
        },
    }

    def estimate_cost(self, inputs: dict[str, Any]) -> float:
        return 0.0

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        try:
            return self._run(inputs)
        except (PathPolicyError, PermissionError, StillRenderError, ValueError, FileNotFoundError) as exc:
            return ToolResult(success=False, error=str(exc), cost_usd=0.0)

    def _run(self, inputs: dict[str, Any]) -> ToolResult:
        props = inputs["props"]
        if not isinstance(props, dict):
            props = json.loads(Path(props).read_text(encoding="utf-8"))
        props = copy.deepcopy(props)
        if not props.get("audio"):
            props.pop("audio", None)  # audio vide : retiré ; audio présent : refusé par check_props
        config = check_config(inputs.get("remotion_config") or FR_CONFIG)
        report = check_props(props)
        if not report.ok:
            return ToolResult(success=False, error="Brouillon refusé : " + " | ".join(report.errors),
                              data={"errors": report.errors, "warnings": report.warnings}, cost_usd=0.0)

        project_dir = Path(inputs["project_dir"])
        # Vérifier l'identité Studio et le verrou avant la première écriture.
        from lib.studio.project import require_writable
        project_dir = require_writable(project_dir)
        out = next_version_dir(check_write_zone(project_dir / "storyboard", PROJECTS_ROOT))
        props_path = out / "props_storyboard.json"
        props_path.write_text(json.dumps(props, ensure_ascii=False, indent=2), encoding="utf-8")

        narration = inputs.get("narration") or {}
        overrides = inputs.get("still_at_seconds") or {}
        entries = []
        cuts = sorted(props["cuts"], key=lambda c: c["in_seconds"])
        for n, cut in enumerate(cuts, start=1):
            frame = choose_frame(cut, FPS, overrides.get(cut["id"]))
            rel = f"scenes/scene_{n:02d}.png"
            render_still(props_path, frame, out / rel, config=config)
            entries.append(SceneEntry(
                number=n, id=cut["id"], start=cut["in_seconds"], end=cut["out_seconds"],
                type=cut["type"], screen_text=_screen_text(cut), narration=narration.get(cut["id"], ""),
                transition=transition_label(cut), frame=frame, image=rel))
        title = inputs.get("title") or project_dir.name
        meta = {"style": props.get("theme"), "format": "16:9 · 1920×1080", "configuration_rendu": config,
                **(inputs.get("meta") or {})}
        sheet = build_sheet(entries, out, title)
        docs = write_documents(entries, out, title, meta)
        return ToolResult(
            success=True,
            data={"version_dir": str(out), "planche": str(sheet), "html": str(docs["html"]),
                  "scenes": [e.__dict__ for e in entries], "warnings": report.warnings,
                  "configuration_rendu": config},
            artifacts=[str(sheet), *map(str, docs.values()), *(str(out / e.image) for e in entries)],
            cost_usd=0.0)
