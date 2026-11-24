# Publish Director — OpenMontage Studio (studio-fr)

## Quand l'utiliser

Étape `publish`, après le rendu : contrôler la vidéo puis l'exporter. Remplace, pour le
studio, le publish-director de l'explainer.

## Règle unique

**La publication passe exclusivement par `exporter_video`.** Ne jamais appeler
`export_bundle` directement dans le studio : il refuse de toute façon une vidéo d'un projet
Studio sans rapport de contrôle conforme portant sur ce MP4 exact.

```python
from lib.studio.budget_guard import StudioBudgetGuard
from lib.studio.qc import QualityControlTool, publication_allowed
from lib.studio.publish import exporter_video

qc = StudioBudgetGuard(project_dir).run(QualityControlTool(), {...})   # voir executive-producer
if not publication_allowed(qc):
    ...  # présenter controle/vNNN/rapport_qc.md, les bloquants, une correction ; NE PAS publier
res = exporter_video(qc, video_path=mp4, title=titre, project_dir=project_dir,
                     description=..., tags=[...])
```

`exporter_video` refuse (sans exception, `res.success` faux) si :
- le contrôle qualité est absent, échoué, incomplet ou invalide ;
- le MP4 n'est plus exactement celui qui a été contrôlé (empreinte SHA-256 et taille) ;
- le fichier exporté ne correspond pas au MP4 contrôlé (l'export de cet appel est retiré) ;
- le dossier d'export est une zone protégée, ou toute autre erreur survient.

En cas de refus : ne pas réessayer autrement, ne pas copier le fichier à la main ;
expliquer le motif à l'utilisateur.

## Sortie

`projects/<projet>/exports/vNNN/` (vidéo, métadonnées, `publish_log`) et
`publication_qc.json` (rapport utilisé, empreinte du MP4 publié). Présenter la vidéo
finale, le rapport de contrôle et le chemin d'export. Validation finale de l'utilisateur.
