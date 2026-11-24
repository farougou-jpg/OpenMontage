"""Outil de narration FR du studio : Piper fr_FR-siwis-medium, méthode V2.

Hors registre automatique (pas dans ``tools/``) : ``tts_selector`` ne peut pas le
choisir. Le studio l'appelle explicitement, à travers le garde-fou budgétaire.

Modes :
* ``mesure``    : durée réelle de chaque section, débit, durée de scène suggérée.
                  Aucun fichier audio ; un rapport JSON versionné.
* ``placement`` : méthode V2 (fenêtres, ancrage de mot-clé, égalisation, -16 LUFS,
                  limiteur) + seconde passe true peak + contrôles automatiques.

Écritures autorisées : ``projects/<projet>/`` (hors ``projects/demos``) et
``remotion-composer/public/audio/studio/<projet>/``, ou le dossier temporaire du
système (tests). Jamais d'écrasement : chaque exécution crée ``vNNN``.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Optional

from tools.base_tool import BaseTool, ToolResult, ToolRuntime, ToolStability, ToolTier

from lib.paths import PROJECTS_DIR

from lib.studio.narration import qc as qcm
from lib.studio.narration.fr_text import analyze
from lib.studio.narration.mastering import master, master_profile_b
from lib.studio.narration.script_input import ScriptError, Segment, load_script, to_segments
from lib.studio.narration.synth import PROFILE_LENGTH_SCALES, VOICE_NAME, PauseMarkupError, Synth, split_pauses

REPO_ROOT = Path(__file__).resolve().parents[3]
# Compatibility alias: all project paths originate in lib.paths.
PROJECTS_ROOT = PROJECTS_DIR
PUBLIC_STUDIO_ROOT = REPO_ROOT / "remotion-composer" / "public" / "audio" / "studio"
PROTECTED = (
    PROJECTS_DIR / "demos",
    REPO_ROOT / "remotion-composer" / "public" / "audio" / "fr-series",
    REPO_ROOT / "remotion-composer" / "public" / "audio" / "fr-pilot",
    # Copie audio immuable du pilote : elle est couverte par le manifeste de préservation.
    REPO_ROOT / "remotion-composer" / "public" / "audio" / "studio" / "pilote-gestion-temps",
)


class PathPolicyError(PermissionError):
    """Écriture refusée : zone protégée ou hors des zones du studio."""


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def check_write_zone(path: Path, allowed_repo_root: Path) -> Path:
    p = Path(path).resolve()
    for prot in PROTECTED:
        if _inside(p, prot.resolve()):
            raise PathPolicyError(f"Zone protégée, écriture refusée : {p}")
    root = Path(allowed_repo_root).resolve()
    # The canonical projects root may intentionally live outside the repository
    # (for isolated tests or staging via OPENMONTAGE_PROJECTS_DIR).
    if _inside(p, root):
        if p == root:
            raise PathPolicyError(f"Hors de la zone studio autorisée ({root}) : {p}")
        return p
    if _inside(p, REPO_ROOT.resolve()):
        raise PathPolicyError(f"Hors de la zone studio autorisée ({root}) : {p}")
    if _inside(p, Path(tempfile.gettempdir()).resolve()):
        return p
    raise PathPolicyError(f"Emplacement non autorisé (ni projet studio, ni dossier temporaire) : {p}")


def next_version_dir(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    nums = [int(m.group(1)) for d in root.iterdir() if (m := re.fullmatch(r"v(\d{3})", d.name))]
    out = root / f"v{(max(nums) + 1) if nums else 1:03d}"
    out.mkdir(exist_ok=False)
    return out


def _spoken_parts(text: str) -> tuple[list[tuple[str, float]], list[str], list[str]]:
    parts, rules, notes = [], [], []
    for chunk, pause in split_pauses(text):
        res = analyze(chunk)
        parts.append((res.spoken, pause))
        rules += res.rules
        notes += res.notes
    return parts, sorted(set(rules)), notes


def place_segments(synth: Synth, segments: list[Segment]) -> tuple[list[tuple[float, Any]], list[dict], list[str]]:
    """Boucle de placement de fr_build.main, sur des segments issus du scénario."""
    rendered, report, errors = [], [], []
    for seg in segments:
        parts, rules, notes = _spoken_parts(seg.text)
        spoken = " ".join(p for p, _ in parts) if len(parts) > 1 else parts[0][0]
        audio = synth.speak_with_pauses(parts)
        dur = len(audio) / synth.sr
        start, kw_time = seg.start, None
        if seg.anchor:
            if len(parts) > 1:
                errors.append(f"{seg.id}: ancrage et [pause] ne peuvent pas être combinés")
            kw, lo, hi = seg.anchor
            prefix = analyze(seg.text.split(kw)[0]).spoken.rstrip(" ,")
            kw_time = start + (len(synth.speak(prefix)) / synth.sr + 0.12 if prefix else 0.0)
            if kw_time < lo:
                start, kw_time = start + lo - kw_time, lo
            if not lo <= kw_time <= hi:
                errors.append(f"{seg.id}: mot-clé à {kw_time:.2f}s hors fenêtre [{lo}, {hi}]")
        end = start + dur
        if end > seg.end_max:
            errors.append(f"{seg.id}: fin {end:.2f}s > {seg.end_max}s (reformuler, pas accélérer)")
        syl = synth.syllables(spoken)
        rendered.append((start, audio))
        report.append({
            "cut": seg.id, "texte_ecrit": seg.text, "texte_lu": spoken,
            "phonemes": synth.phonemes(spoken),
            "debut": round(start, 3), "fin": round(end, 3), "fin_max": seg.end_max,
            "duree": round(dur, 3), "syllabes": syl, "syllabes_par_s": round(syl / dur, 2),
            "mot_cle_a": round(kw_time, 2) if kw_time else None,
            "length_scale": synth.length_scale, "profil": synth.profile,
            "regles": rules, "notes": notes,
        })
    return rendered, report, errors


class PiperFrNarration(BaseTool):
    name = "studio_piper_fr_narration"
    version = "1.0.0"
    tier = ToolTier.VOICE
    capability = "narration_fr"          # volontairement ≠ "tts" : invisible pour tts_selector
    provider = "piper"
    runtime = ToolRuntime.LOCAL
    stability = ToolStability.EXPERIMENTAL
    dependencies = ["python:piper", "cmd:ffmpeg"]
    install_instructions = "Voix déjà installée : ~/.piper/models/fr_FR-siwis-medium.onnx"
    input_schema = {
        "type": "object",
        "required": ["mode", "script", "project_dir"],
        "properties": {
            "mode": {"enum": ["mesure", "placement"]},
            "script": {"description": "artefact script (dict) ou chemin JSON"},
            "project_dir": {"type": "string"},
            "public_root": {"type": "string"},
            "section_options": {"type": "object"},
            "sentence_pause": {"type": "number", "default": 0.30},
            "safety_margin_s": {"type": "number", "default": 0.5},
            "fps": {"type": "integer", "default": 30},
            "profil": {"enum": ["V2", "B"], "default": "V2",
                       "description": "V2 (défaut, length_scale 1,0, 22 kHz) ou B (référence sonore validée : 1,10, chaleur, 48 kHz)"},
        },
    }

    def __init__(self, voice: Optional[Any] = None) -> None:
        self._voice = voice  # injection pour les tests

    def estimate_cost(self, inputs: dict[str, Any]) -> float:
        return 0.0

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        try:
            return self._run(inputs)
        except (ScriptError, PauseMarkupError, PathPolicyError, PermissionError, FileNotFoundError, ValueError) as exc:
            return ToolResult(success=False, error=str(exc), cost_usd=0.0)

    # ---- implémentation ----

    def _run(self, inputs: dict[str, Any]) -> ToolResult:
        mode = inputs["mode"]
        project_dir = Path(inputs["project_dir"])
        # Identité + verrou avant toute création de dossier ou de fichier.
        from lib.studio.project import require_writable
        project_dir = require_writable(project_dir)
        check_write_zone(project_dir, PROJECTS_ROOT)
        project = project_dir.name
        script = load_script(inputs["script"])
        segments = to_segments(script, inputs.get("section_options"),
                               float(inputs.get("safety_margin_s", 0.5)), int(inputs.get("fps", 30)))
        profile = inputs.get("profil") or "V2"
        synth = Synth(length_scale=PROFILE_LENGTH_SCALES.get(profile, -1.0),
                      sentence_pause=float(inputs.get("sentence_pause", 0.30)), voice=self._voice, profile=profile)
        if mode == "mesure":
            return self._measure(synth, segments, project_dir)
        if mode != "placement":
            raise ValueError(f"Mode inconnu : {mode!r}")
        public_root = Path(inputs.get("public_root") or PUBLIC_STUDIO_ROOT)
        check_write_zone(public_root / project, PUBLIC_STUDIO_ROOT)
        return self._place(synth, segments, script, project_dir, project, public_root)

    def _measure(self, synth: Synth, segments: list[Segment], project_dir: Path) -> ToolResult:
        rows = []
        for seg in segments:
            parts, rules, notes = _spoken_parts(seg.text)
            dur = len(synth.speak_with_pauses(parts)) / synth.sr
            spoken = " ".join(p for p, _ in parts)
            syl = synth.syllables(spoken)
            fade_s = seg.fade_out_frames / seg.fps
            rows.append({
                "section": seg.id, "texte_lu": spoken, "duree_parole": round(dur, 3),
                "syllabes_par_s": round(syl / dur, 2),
                "fenetre_disponible": round(seg.end_max - seg.start, 3),
                "tient": seg.start + dur <= seg.end_max,
                # pause avant + parole + pause après + fondu sortant + marge de sécurité
                "duree_scene_suggeree": round(seg.pause_before + dur + seg.pause_after + fade_s
                                              + seg.safety_margin_s, 3),
                "regles": rules, "notes": notes,
            })
        out_root = check_write_zone(project_dir / "assets" / "narration" / "mesures", PROJECTS_ROOT)
        out = next_version_dir(out_root)
        path = out / "mesure.json"
        path.write_text(json.dumps({"voix": VOICE_NAME, "profil": synth.profile, "length_scale": synth.length_scale,
                                    "sections": rows}, ensure_ascii=False, indent=2),
                        encoding="utf-8")
        return ToolResult(success=True, data={"mode": "mesure", "sections": rows, "rapport": str(path)},
                          artifacts=[str(path)], cost_usd=0.0)

    def _place(self, synth: Synth, segments: list[Segment], script: dict, project_dir: Path,
               project: str, public_root: Path) -> ToolResult:
        total = float(script["total_duration_seconds"])
        rendered, rows, errors = place_segments(synth, segments)
        if errors:
            return ToolResult(success=False, error="ÉCHEC placement :\n  " + "\n  ".join(errors),
                              data={"segments": rows}, cost_usd=0.0)

        out_root = check_write_zone(project_dir / "assets" / "narration", PROJECTS_ROOT)
        out = next_version_dir(out_root)
        seg_files = []
        for (start, audio), row in zip(rendered, rows):
            f = out / "segments" / f"{row['cut']}.wav"
            synth.write_wav(f, audio)
            seg_files.append(f)
        m = (master_profile_b if synth.profile == "B" else master)(synth, rendered, total, out)
        (out / "timing_fr.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")

        qc = qcm.QCReport()
        qcm.check_timing(rows, total, qc)
        qcm.check_loudness(m.lufs, m.true_peak, qc)
        if synth.profile == "B":
            # Fichier final en 24 bits : contrôle d'écrêtage et de format sur une copie 16 bits temporaire.
            check_copy = out / "_controle_16bits.wav"
            subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(m.final),
                            "-c:a", "pcm_s16le", str(check_copy)], check=True)
            try:
                qcm.check_audio(check_copy, seg_files, qc)
            finally:
                check_copy.unlink(missing_ok=True)
            qc.measures["format_fichier_final"] = "48 000 Hz, 24 bits, mono"
        else:
            qcm.check_audio(m.final, seg_files, qc)
        qc.measures.update({"lufs_brut": m.lufs_brut, "true_peak_brut_dbfs": m.true_peak_brut,
                            "seconde_passe_true_peak": m.second_pass,
                            "ecart_niveau_phrases_db": round(m.level_spread_db, 2)})
        header = {"projet": project, "version": out.name, "voix": VOICE_NAME, "length_scale": synth.length_scale,
                  "profil": synth.profile,
                  "duree_video_s": total}
        js, md = qcm.write_report(qc, rows, out, header)

        artifacts = [str(m.final), str(m.brut), str(out / "timing_fr.json"), str(js), str(md)]
        public_wav = None
        if qc.passed:
            dest_dir = check_write_zone(public_root / project / out.name, PUBLIC_STUDIO_ROOT)
            dest_dir.mkdir(parents=True, exist_ok=False)
            public_wav = dest_dir / "narration_fr.wav"
            shutil.copyfile(m.final, public_wav)
            artifacts.append(str(public_wav))
        else:
            # Narration non conforme : on retire le fichier final, on garde brut + rapport.
            m.final.unlink()
            artifacts.remove(str(m.final))
        return ToolResult(
            success=qc.passed,
            error=None if qc.passed else "Contrôle qualité non conforme : " + " | ".join(qc.blocking),
            data={"mode": "placement", "version_dir": str(out), "narration": str(m.final) if qc.passed else None,
                  "public_wav": str(public_wav) if public_wav else None, "qc": qc.to_dict(), "segments": rows},
            artifacts=artifacts, cost_usd=0.0,
        )
