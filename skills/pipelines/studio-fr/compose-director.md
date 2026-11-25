# Compose Director — OpenMontage Studio (studio-fr)

## Quand l'utiliser

Étape `compose`, après le checkpoint `edit`. Remplace, pour le studio, le compose-director
de l'explainer.

## Moteur de rendu : lire `render_runtime` d'abord

Lire `edit_decisions.render_runtime`, verrouillé à la proposition. En phase 1 du studio, il
vaut `remotion` : HyperFrames (et la méthode atelier) ont été présentés à la proposition
comme « indisponibles au rendu en phase 1 » et ne peuvent pas avoir été choisis. Toute autre
valeur est un blocage : l'expliquer à l'utilisateur (AGENT_GUIDE, « Escalate Blockers
Explicitly ») ; jamais de bascule silencieuse vers un autre moteur.

## Règle unique : le rendu passe par `lib/studio/render.py`

Phase 1 : rendu Remotion local, méthode gabarits, 1920×1080, configuration inscrite dans le
storyboard validé (`remotion.fr-locale-v4.config.ts`). Le rendu part du storyboard validé
(validation 2) et de la narration validée (validation 3), rien d'autre :

```python
from lib.studio import render as ren
plan = ren.prepare_render(project_dir)          # refuse si la validation 2 ou 3 n'est pas à jour
res = ren.run_render(plan)                      # nouveau renders/vNNN/ + rendu.json ; long : en arrière-plan
qc = ren.check_render(project_dir, res["version"])   # contrôle qualité du MP4 exact (lot 1.6)
```

Interdits en phase 1 pour le studio : `video_compose`, `hyperframes_compose`, la méthode
atelier et tout autre moteur de rendu. Un MP4 qui ne vient pas de `run_render` n'a pas de
provenance vérifiable (`rendu.json`, versions validées, props) : le checkpoint `compose` et la
validation 4 le refusent, même avec un rapport de contrôle conforme. Ne jamais copier, renommer
ni retoucher un MP4 dans `renders/`.

## Contrôle qualité

`qc.data["conforme"]` faux : présenter `controle/vNNN/rapport_qc.md`, les bloquants et une
correction proposée ; ne pas avancer. Aucune vidéo n'est présentée comme finale sans rapport de
contrôle conforme.

## Sortie

`render_report` conforme au schéma, citant le seul MP4 `renders/vNNN/video.mp4` :

```python
from lib.studio import checkpoints as ckp
render_report = {"version": "1.0", "outputs": [{"path": f"renders/{res['version']}/video.mp4",
                 "format": "mp4", "resolution": "1920x1080", "duration_seconds": duree}]}
ckp.write_studio_checkpoint(project_dir, "compose", "completed", {"render_report": render_report})
```

L'étape `publish` est gelée pour le studio jusqu'au lot P0-D : ne lancer aucun export.
