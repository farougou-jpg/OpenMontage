# Publish Director — OpenMontage Studio (studio-fr)

## Quand l'utiliser

Étape `publish`, après le rendu : contrôler la vidéo puis l'exporter. Remplace, pour le
studio, le publish-director de l'explainer.

## Étape gelée (lot P0-D)

La publication du studio est **gelée** jusqu'à l'autorisation explicite de l'utilisateur :
ne lancer aucun export, même si toutes les conditions ci-dessous sont réunies, et ne jamais
écrire de checkpoint `publish` (`write_studio_checkpoint` le refuse). Le contenu qui suit
décrit le chemin qui s'appliquera après la levée du gel.

## Règle unique

**La publication passe exclusivement par `exporter_video`**, appelé uniquement à travers
`export_package`, et seulement APRÈS la validation 4 (rendu vidéo) du MP4 exact.
Ne jamais appeler `export_bundle` directement dans le studio : il refuse de toute façon une
vidéo d'un projet Studio sans rapport de contrôle conforme portant sur ce MP4 exact.

```python
from lib.studio import validations as val
from lib.studio.export_package import export_package

# 1. rendu et contrôle conformes (compose-director : ren.check_render) ;
# 2. présentation du MP4 exact et du rapport de contrôle, puis accord explicite (validation 4) :
shown = val.presentation(project_dir, "rendu", render_version="vNNN", qc_version="vNNN")
# … fin du tour, accord explicite de l'utilisateur …
val.validate_render(project_dir, "vNNN", "vNNN", empreinte_presentee=shown["empreinte"],
                    accord_utilisateur="<mots exacts de l'utilisateur>")
# 3. export local du MP4 validé (jamais avant la validation 4) :
res = export_package(project_dir, "nom-du-fichier.mp4", titre, description)
```

`exporter_video` (appelé par `export_package`, ou directement) refuse aussi, sans exception, si
la validation 4 est absente ou périmée, si le MP4 n'est pas exactement celui qu'elle cite
(chemin, SHA-256, taille), si sa provenance `render.py` n'est plus vérifiable, si le rapport
de contrôle n'est pas celui de la validation 4, ou si un checkpoint Studio n'est pas intègre.

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
finale, le rapport de contrôle et le chemin d'export. La validation finale de l'utilisateur
(validation 4) a eu lieu AVANT l'export, sur ce MP4 exact ; elle n'est jamais demandée après.
