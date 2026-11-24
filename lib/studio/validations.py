"""OpenMontage Studio — validations de l'utilisateur (étape G0).

Quatre validations, dans cet ordre : 1 scénario → 2 storyboard → 3 narration → 4 rendu.
Chaque validation inscrit dans `validations.json` les empreintes SHA-256 des fichiers
validés ; `is_current` vérifie ensuite qu'ils n'ont pas changé.

Règles :
- une validation exige la précédente, encore à jour ;
- une étape déjà validée peut être revalidée (nouvelle version) tant que l'étape suivante
  ne l'est pas ; l'ancienne entrée est conservée (`remplace`) ;
- jamais dans un projet verrouillé (pilote, vidéos françaises, projet exporté) ;
- les fins de ligne existantes du fichier sont conservées (CRLF ou LF).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Optional

from lib.studio.narration.script_input import load_script
from lib.studio.narration.tool import PUBLIC_STUDIO_ROOT
from lib.studio.project import PIPELINE, now_iso, read_json, require_writable, versions
from lib.studio.qc.tool import verify_report_for_publication
from lib.studio.storyboard.stills import ALLOWED_CONFIGS

KINDS = ("scenario", "storyboard", "narration", "rendu")
OBJECTS = {"scenario": "scénario", "storyboard": "storyboard", "narration": "narration française",
           "rendu": "rendu vidéo"}
# Projets antérieurs au module (pilote) : type déduit du numéro.
LEGACY_KINDS = {1: "scenario", 2: "storyboard", 3: "reference_sonore", 4: "rendu"}


class ValidationError(ValueError):
    """Validation refusée (étape précédente manquante, fichier absent ou non conforme)."""


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _hashes(root: Path, files: list[Path]) -> dict[str, str]:
    return {f.relative_to(root).as_posix(): sha256(f) for f in sorted(files)}


# ---- lecture ----

def load(project_dir: Path) -> dict:
    data = read_json(Path(project_dir) / "validations.json")
    if data is None:
        return {"projet": Path(project_dir).name, "pipeline": PIPELINE, "validations": []}
    if not isinstance(data, dict) or not isinstance(data.get("validations"), list):
        raise ValidationError("validations.json illisible ou mal formé.")
    return data


def kind_of(entry: dict) -> Optional[str]:
    return entry.get("type") or LEGACY_KINDS.get(entry.get("numero"))


def validations_by_kind(project_dir: Path) -> dict[str, dict]:
    """Dernière validation de chaque type."""
    try:
        entries = load(project_dir)["validations"]
    except ValidationError:
        return {}
    out: dict[str, dict] = {}
    for e in entries:
        if isinstance(e, dict) and e.get("statut") == "validé" and kind_of(e):
            out[kind_of(e)] = e
    return out


def is_current(project_dir: Path, kind: str) -> tuple[bool, str]:
    """La validation `kind` existe-t-elle, et ses fichiers sont-ils inchangés ?"""
    e = validations_by_kind(project_dir).get(kind)
    if e is None:
        return False, f"{OBJECTS.get(kind, kind)} non validé"
    prints = e.get("empreintes")
    if not isinstance(prints, dict) or not prints:
        return False, f"validation {e.get('numero')} sans empreintes vérifiables"
    p = Path(project_dir)
    for rel, expected in prints.items():
        f = p / rel
        if not f.is_file():
            return False, f"fichier validé absent : {rel}"
        if sha256(f) != expected:
            return False, f"fichier modifié depuis la validation {e['numero']} : {rel}"
    return True, "à jour"


# ---- écriture ----

def _write(project_dir: Path, data: dict) -> None:
    path = Path(project_dir) / "validations.json"
    crlf = path.is_file() and b"\r\n" in path.read_bytes()
    text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    path.write_bytes((text.replace("\n", "\r\n") if crlf else text).encode("utf-8"))


def _append(project_dir: Path, kind: str, payload: dict[str, Any]) -> dict:
    p = require_writable(Path(project_dir))
    data = load(p)
    current = validations_by_kind(p)
    idx = KINDS.index(kind)
    if idx > 0:
        ok, why = is_current(p, KINDS[idx - 1])
        if not ok:
            raise ValidationError(f"Validation {OBJECTS[kind]} refusée : {why}.")
    later = [k for k in KINDS[idx + 1:] if k in current]
    if later:
        raise ValidationError(f"Validation {OBJECTS[kind]} refusée : l'étape « {OBJECTS[later[0]]} » est déjà "
                              "validée ; créer un nouveau projet pour repartir de cette étape.")
    numero = max([e.get("numero", 0) for e in data["validations"] if isinstance(e, dict)] + [0]) + 1
    entry = {"numero": numero, "type": kind, "objet": OBJECTS[kind], "statut": "validé",
             "enregistre_le": now_iso(), **payload}
    if kind in current:
        entry["remplace"] = current[kind]["numero"]
    data["validations"].append(entry)
    _write(p, data)
    return entry


def _version_dir(root: Path, version: str) -> Path:
    if version not in versions(root):
        raise ValidationError(f"Version introuvable : {root.name}/{version}.")
    return root / version


def validate_script(project_dir: Path) -> dict:
    p = Path(project_dir)
    script = p / "script.json"
    if not script.is_file():
        raise ValidationError("Scénario absent (script.json).")
    try:
        data = load_script(script)
    except Exception as exc:  # noqa: BLE001 — scénario invalide
        raise ValidationError(f"Scénario invalide : {exc}") from exc
    return _append(p, "scenario", {"sections": len(data.get("sections", [])),
                                   "empreintes": _hashes(p, [script])})


def validate_storyboard(project_dir: Path, version: str) -> dict:
    p = Path(project_dir)
    d = _version_dir(p / "storyboard", version)
    sb = read_json(d / "storyboard.json", {}) or {}
    config = sb.get("configuration_rendu")
    if config not in ALLOWED_CONFIGS:
        raise ValidationError(f"Configuration de rendu inconnue dans le storyboard : {config!r}.")
    for name in ("storyboard.json", "props_storyboard.json"):
        if not (d / name).is_file():
            raise ValidationError(f"Storyboard incomplet : {name} absent.")
    files = [f for f in d.rglob("*") if f.is_file()]
    return _append(p, "storyboard", {"version": version, "configuration_rendu": config,
                                     "empreintes": _hashes(p, files)})


def validate_narration(project_dir: Path, version: str, studio_audio_root: Path = PUBLIC_STUDIO_ROOT) -> dict:
    p = Path(project_dir)
    d = _version_dir(p / "assets" / "narration", version)
    report = read_json(d / "controle" / "rapport_narration.json", {}) or {}
    wav = d / "narration_fr.wav"
    if report.get("conforme") is not True or not wav.is_file():
        raise ValidationError("Narration non conforme ou piste finale absente : validation refusée.")
    public = Path(studio_audio_root) / p.name / version / "narration_fr.wav"
    if not public.is_file() or sha256(public) != sha256(wav):
        raise ValidationError("Copie pour Remotion absente ou différente de la piste finale.")
    files = [wav, d / "timing_fr.json", d / "controle" / "rapport_narration.json"]
    return _append(p, "narration", {"version": version, "profil": report.get("profil", "V2"),
                                    "copie_remotion_sha256": sha256(public),
                                    "empreintes": _hashes(p, files)})


def validate_render(project_dir: Path, render_version: str, qc_version: str) -> dict:
    p = Path(project_dir)
    r = _version_dir(p / "renders", render_version)
    q = _version_dir(p / "controle", qc_version)
    mp4s = sorted(r.glob("*.mp4"))
    if len(mp4s) != 1:
        raise ValidationError(f"Rendu {render_version} : un seul MP4 attendu ({len(mp4s)} trouvé(s)).")
    ok, why = verify_report_for_publication(q / "rapport_qc.json", mp4s[0], p)
    if not ok:
        raise ValidationError(f"Rendu non validable : {why}.")
    report = read_json(q / "rapport_qc.json", {})
    files = [mp4s[0], r / "props_rendu.json", q / "rapport_qc.json"]
    return _append(p, "rendu", {"version_rendu": render_version, "version_controle": qc_version,
                                "fichier": mp4s[0].relative_to(p).as_posix(), "sha256": sha256(mp4s[0]),
                                "taille_octets": mp4s[0].stat().st_size,
                                "controle": {"conforme": True, "bloquants": 0,
                                             "avertissements": len(report.get("avertissements") or [])},
                                "empreintes": _hashes(p, [f for f in files if f.is_file()])})
