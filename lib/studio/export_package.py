"""OpenMontage Studio — export du paquet complet en une action (étape G0).

Méthode retenue pour le pilote, décision D2 (« rapport et empreinte ») :
1. la validation 4 (rendu) doit exister et ses fichiers être inchangés ;
2. l'empreinte SHA-256 du MP4 est revérifiée juste avant l'export ;
3. le résultat du contrôle est reconstitué depuis le rapport `controle/vNNN/rapport_qc.json`
   inscrit dans la validation 4 ; le verrou (`exporter_video`, puis `export_bundle`)
   relit ce rapport et recalcule l'empreinte ;
4. dans le paquet uniquement : la vidéo `output.mp4` reçoit le nom choisi, le rapport de
   contrôle (json + md) est joint, la trace `publication_qc.json` est complétée ;
5. tout écart après l'export retire le dossier `exports/vNNN` créé par CET appel.

Aucune publication, mise en ligne ni diffusion : export local uniquement.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Callable, Optional

from tools.base_tool import ToolResult

from lib.studio.project import read_json, require_writable, write_json
from lib.studio.publish import exporter_video
from lib.studio.validations import is_current, sha256, validations_by_kind

FILE_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,80}\.mp4")


class ExportError(RuntimeError):
    """Export refusé ou en échec."""


def check_file_name(name: str) -> str:
    if not isinstance(name, str) or not FILE_NAME_RE.fullmatch(name) or ".." in name:
        raise ExportError("Nom de fichier invalide : lettres, chiffres, « . », « _ », « - », extension .mp4.")
    return name


def export_package(project_dir: Path, file_name: str, title: str, description: str = "",
                   exporter: Optional[Callable[..., ToolResult]] = None) -> dict:
    p = require_writable(Path(project_dir))
    check_file_name(file_name)
    ok, why = is_current(p, "rendu")
    if not ok:
        raise ExportError(f"Export refusé : {why}.")
    v4 = validations_by_kind(p)["rendu"]
    mp4 = p / v4["fichier"]
    expected = v4["sha256"]
    if sha256(mp4) != expected:
        raise ExportError("Export refusé : l'empreinte du MP4 ne correspond plus à la validation du rendu.")
    report_json = p / "controle" / v4["version_controle"] / "rapport_qc.json"
    report_md = report_json.with_suffix(".md")
    report = read_json(report_json)
    if not isinstance(report, dict) or report.get("conforme") is not True or report.get("bloquants") \
            or (report.get("mp4") or {}).get("sha256") != expected:
        raise ExportError("Export refusé : rapport de contrôle absent, non conforme ou d'un autre MP4.")
    qc = ToolResult(success=True, data={"conforme": True, "bloquants": [],
                                        "avertissements": report.get("avertissements") or [],
                                        "rapport_json": str(report_json)})

    res = (exporter or exporter_video)(qc, mp4, title, p, description=description,
                                       platform="local", visibility="private")
    if not res.success:
        raise ExportError(res.error or "Export en échec.")
    out = Path(res.data["version_dir"])
    try:
        exported = out / "video" / "output.mp4"
        final = out / "video" / file_name
        if final.exists() and final != exported:
            raise ExportError("Nom de fichier déjà présent dans le paquet.")
        exported.rename(final)
        if sha256(final) != expected:
            raise ExportError("Empreinte du fichier exporté différente du MP4 validé.")
        (out / "controle").mkdir()
        joined = []
        for src in (report_json, report_md):
            if src.is_file():
                shutil.copy2(src, out / "controle" / src.name)
                if sha256(out / "controle" / src.name) != sha256(src):
                    raise ExportError(f"Copie du rapport altérée : {src.name}.")
                joined.append(f"controle/{src.name}")
        trace = out / "publication_qc.json"
        t = read_json(trace, {}) or {}
        t.update({"fichier_publie": str(final), "nom_initial_export_bundle": "video/output.mp4",
                  "rapport_qc_joint": joined,
                  "resultat_controle": f"reconstitué depuis controle/{v4['version_controle']}/rapport_qc.json "
                                       "(méthode « rapport et empreinte »)",
                  "validation": f"validations.json, validation {v4['numero']}",
                  "publication": "aucune (export local uniquement)"})
        write_json(trace, t)
    except BaseException:
        shutil.rmtree(out, ignore_errors=True)
        raise
    files = sorted(f for f in out.rglob("*") if f.is_file())
    return {"export_dir": str(out), "version": out.name, "video": str(final), "sha256": expected,
            "fichiers": {f.relative_to(out).as_posix(): {"sha256": sha256(f), "taille_octets": f.stat().st_size}
                         for f in files}}
