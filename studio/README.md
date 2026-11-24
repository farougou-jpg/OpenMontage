# OpenMontage Studio (français)

Point d'entrée du studio. Une idée (formulaire « OPENMONTAGE — STUDIO DE CRÉATION » ou
simple phrase) devient une vidéo, avec validation du scénario puis du storyboard avant
toute génération.

## Pour l'agent

1. Lire `skills/pipelines/studio-fr/executive-producer.md` (règles impératives).
2. Suivre `pipeline_defs/studio-fr.yaml`, étape par étape, en lisant chaque skill d'étape.
3. Formulaire vide → demander l'idée, rien d'autre.

## Règles en bref (phase 1)

| Règle | Valeur |
|---|---|
| Budget supplémentaire | **0 € par défaut** ; toute dépense = devis + autorisation explicite |
| Garde-fou | `lib/studio/budget_guard.py` + `config.studio.yaml` (mode cap, 0 $) |
| Modes présentés | Économique (par défaut, 0 €) et hybride (indisponible en phase 1) |
| Composition | Gabarits (recommandés) et atelier (sur demande) |
| Moteur | Remotion (recommandé) et HyperFrames, toujours présentés |
| Recherche web | Désactivée par défaut, sur demande explicite seulement |
| Narration | Piper `fr_FR-siwis-medium`, méthode V2 (`lib/studio/narration`, `studio/docs/narration-fr.md`) |
| Format / durées | 16:9 1920×1080 ; 15, 30, 60 ou 90 s (9:16 et 1:1 au lot 1.4) |
| Fichiers protégés | `projects/demos/`, `public/audio/fr-series/`, `public/audio/fr-pilot/` |

## Feuille de route

Phase 1 (motion design local) : lots 1.1 garde-fou ✅, 1.2 narration ✅, 1.3 aiguilleur et
pipeline, 1.5 storyboard en images, 1.6 contrôle qualité FR, 1.7 pilote, 1.4 formats.
Phase 2 : ressources visuelles et musique (Pexels, Pixabay, illustrations).
Phase 3 : moteurs de génération vidéo IA (mode hybride). Phase 4 : automatisation.
