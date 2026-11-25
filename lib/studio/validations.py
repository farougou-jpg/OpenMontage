"""OpenMontage Studio — validations de l'utilisateur (étape G0).

Quatre validations, dans cet ordre : 1 scénario → 2 storyboard → 3 narration → 4 rendu.
Chaque validation inscrit dans `validations.json` les empreintes SHA-256 des fichiers
validés ; `is_current` vérifie ensuite qu'ils n'ont pas changé.

Règle centrale (P0-B) : une validation porte sur l'artefact EXACT présenté à l'utilisateur.
1. `presentation(projet, type, …)` calcule, en lecture seule, l'empreinte SHA-256 de ce qui va
   être présenté (mêmes contrôles techniques que la validation) ;
2. l'agent présente exactement ces fichiers et recueille l'accord explicite de l'utilisateur ;
3. `validate_<type>(…, empreinte_presentee=…, accord_utilisateur="<citation exacte>")` recalcule
   l'empreinte : toute différence (ancien artefact, version régénérée, réécriture entre
   l'accord et la validation) est refusée ; un accord absent ou vide est refusé.
L'empreinte et la citation sont inscrites dans `validations.json` ; `is_current` exige qu'elles
soient cohérentes. Le code ne peut pas juger qu'un humain a réellement parlé : c'est la règle
des skills ; il garantit en revanche que l'accord enregistré porte sur ce contenu précis.

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


def fingerprint(prints: dict[str, str]) -> str:
    """Empreinte SHA-256 unique d'un artefact (ensemble chemin relatif → SHA-256 de chaque fichier)."""
    canon = json.dumps(dict(sorted(prints.items())), ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


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
    if not isinstance(e.get("accord_utilisateur"), str) or not e["accord_utilisateur"].strip():
        return False, f"validation {e.get('numero')} sans accord explicite enregistré"
    if e.get("empreinte_presentation") != fingerprint(prints):
        return False, f"validation {e.get('numero')} sans empreinte de présentation cohérente"
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


# ---- artefacts à présenter (contrôles techniques, lecture seule) ----

def _collect_script(p: Path) -> tuple[dict, list[Path]]:
    script = p / "script.json"
    if not script.is_file():
        raise ValidationError("Scénario absent (script.json).")
    try:
        data = load_script(script)
    except Exception as exc:  # noqa: BLE001 — scénario invalide
        raise ValidationError(f"Scénario invalide : {exc}") from exc
    return {"sections": len(data.get("sections", []))}, [script]


def _collect_storyboard(p: Path, version: str) -> tuple[dict, list[Path]]:
    d = _version_dir(p / "storyboard", version)
    sb = read_json(d / "storyboard.json", {}) or {}
    config = sb.get("configuration_rendu")
    if config not in ALLOWED_CONFIGS:
        raise ValidationError(f"Configuration de rendu inconnue dans le storyboard : {config!r}.")
    for name in ("storyboard.json", "props_storyboard.json"):
        if not (d / name).is_file():
            raise ValidationError(f"Storyboard incomplet : {name} absent.")
    return {"version": version, "configuration_rendu": config}, [f for f in d.rglob("*") if f.is_file()]


def _collect_narration(p: Path, version: str, studio_audio_root: Path) -> tuple[dict, list[Path]]:
    d = _version_dir(p / "assets" / "narration", version)
    report = read_json(d / "controle" / "rapport_narration.json", {}) or {}
    wav = d / "narration_fr.wav"
    if report.get("conforme") is not True or not wav.is_file():
        raise ValidationError("Narration non conforme ou piste finale absente : validation refusée.")
    public = Path(studio_audio_root) / p.name / version / "narration_fr.wav"
    if not public.is_file() or sha256(public) != sha256(wav):
        raise ValidationError("Copie pour Remotion absente ou différente de la piste finale.")
    return ({"version": version, "profil": report.get("profil", "V2"), "copie_remotion_sha256": sha256(public)},
            [wav, d / "timing_fr.json", d / "controle" / "rapport_narration.json"])


def _collect_render(p: Path, render_version: str, qc_version: str) -> tuple[dict, list[Path]]:
    r = _version_dir(p / "renders", render_version)
    q = _version_dir(p / "controle", qc_version)
    # P0-C : le MP4 doit provenir de render.py, sur les validations 2 et 3 actuelles (import local : cycle).
    from lib.studio.render import RenderError, render_provenance
    try:
        render_provenance(p, render_version)
    except RenderError as exc:
        raise ValidationError(f"Rendu non validable : {exc}") from exc
    mp4s = sorted(r.glob("*.mp4"))
    if len(mp4s) != 1:
        raise ValidationError(f"Rendu {render_version} : un seul MP4 attendu ({len(mp4s)} trouvé(s)).")
    ok, why = verify_report_for_publication(q / "rapport_qc.json", mp4s[0], p)
    if not ok:
        raise ValidationError(f"Rendu non validable : {why}.")
    report = read_json(q / "rapport_qc.json", {})
    files = [mp4s[0], r / "props_rendu.json", q / "rapport_qc.json"]
    return ({"version_rendu": render_version, "version_controle": qc_version,
             "fichier": mp4s[0].relative_to(p).as_posix(), "sha256": sha256(mp4s[0]),
             "taille_octets": mp4s[0].stat().st_size,
             "controle": {"conforme": True, "bloquants": 0,
                          "avertissements": len(report.get("avertissements") or [])}},
            [f for f in files if f.is_file()])


def _collect(p: Path, kind: str, version: Optional[str], render_version: Optional[str],
             qc_version: Optional[str], studio_audio_root: Path) -> tuple[dict, list[Path]]:
    if kind == "scenario":
        return _collect_script(p)
    if kind == "storyboard":
        return _collect_storyboard(p, str(version))
    if kind == "narration":
        return _collect_narration(p, str(version), studio_audio_root)
    if kind == "rendu":
        return _collect_render(p, str(render_version), str(qc_version))
    raise ValidationError(f"Type de validation inconnu : {kind!r}.")


def presentation(project_dir: Path, kind: str, version: Optional[str] = None,
                 render_version: Optional[str] = None, qc_version: Optional[str] = None,
                 studio_audio_root: Path = PUBLIC_STUDIO_ROOT) -> dict:
    """Artefact à présenter AVANT de demander l'accord : fichiers et empreinte. Lecture seule.

    Mêmes contrôles techniques que la validation correspondante. L'empreinte renvoyée est celle
    que `validate_<type>` exigera (`empreinte_presentee`).
    """
    p = Path(project_dir)
    payload, files = _collect(p, kind, version, render_version, qc_version, studio_audio_root)
    prints = _hashes(p, files)
    return {"type": kind, "objet": OBJECTS[kind], "empreinte": fingerprint(prints), "fichiers": prints,
            **{k: v for k, v in payload.items() if k in ("version", "version_rendu", "version_controle")}}


def _validated_append(p: Path, kind: str, payload: dict, files: list[Path],
                      empreinte_presentee: Any, accord_utilisateur: Any) -> dict:
    if not isinstance(accord_utilisateur, str) or not accord_utilisateur.strip():
        raise ValidationError(f"Validation {OBJECTS[kind]} refusée : accord explicite de l'utilisateur absent "
                              "(citer ses mots exacts).")
    prints = _hashes(p, files)             # une seule lecture : ce qui est vérifié est ce qui est inscrit
    current = fingerprint(prints)
    if not isinstance(empreinte_presentee, str) or empreinte_presentee != current:
        raise ValidationError(f"Validation {OBJECTS[kind]} refusée : l'artefact n'est pas exactement celui "
                              "présenté à l'utilisateur (empreinte différente). Le présenter de nouveau.")
    return _append(p, kind, {**payload, "empreintes": prints, "empreinte_presentation": current,
                             "accord_utilisateur": accord_utilisateur.strip()})


def validate_script(project_dir: Path, *, empreinte_presentee: Optional[str] = None,
                    accord_utilisateur: Optional[str] = None) -> dict:
    p = Path(project_dir)
    payload, files = _collect_script(p)
    return _validated_append(p, "scenario", payload, files, empreinte_presentee, accord_utilisateur)


def validate_storyboard(project_dir: Path, version: str, *, empreinte_presentee: Optional[str] = None,
                        accord_utilisateur: Optional[str] = None) -> dict:
    p = Path(project_dir)
    payload, files = _collect_storyboard(p, version)
    return _validated_append(p, "storyboard", payload, files, empreinte_presentee, accord_utilisateur)


def validate_narration(project_dir: Path, version: str, studio_audio_root: Path = PUBLIC_STUDIO_ROOT, *,
                       empreinte_presentee: Optional[str] = None,
                       accord_utilisateur: Optional[str] = None) -> dict:
    p = Path(project_dir)
    payload, files = _collect_narration(p, version, studio_audio_root)
    return _validated_append(p, "narration", payload, files, empreinte_presentee, accord_utilisateur)


def validate_render(project_dir: Path, render_version: str, qc_version: str, *,
                    empreinte_presentee: Optional[str] = None, accord_utilisateur: Optional[str] = None) -> dict:
    p = Path(project_dir)
    payload, files = _collect_render(p, render_version, qc_version)
    return _validated_append(p, "rendu", payload, files, empreinte_presentee, accord_utilisateur)
