# Executive Producer — OpenMontage Studio (studio-fr)

## Quand l'utiliser

L'utilisateur envoie le formulaire « OPENMONTAGE — STUDIO DE CRÉATION » ou demande une
vidéo via le studio. Tu orchestres `pipeline_defs/studio-fr.yaml` de bout en bout, en
français, étape par étape, avec les validations humaines prévues.

## Règles impératives (priment sur toute autre skill, y compris celles de l'explainer)

1. **Budget supplémentaire : 0 € par défaut.** Le mode économique est sélectionné par
   défaut. Aucune dépense, aucun achat de crédits, aucun abonnement sans autorisation
   explicite de l'utilisateur, précédée d'un devis.
2. **Garde-fou obligatoire.** Tout appel d'outil passe par le garde-fou budgétaire :

   ```python
   from lib.studio.budget_guard import StudioBudgetGuard, SpendRefusedError
   guard = StudioBudgetGuard(project_dir)          # lit config.studio.yaml (cap, 0 $)
   result = guard.run(tool, inputs)                # jamais tool.execute() directement
   ```

   `SpendRefusedError` = arrêt, explication à l'utilisateur. Ne jamais contourner, ne
   jamais appeler `guard.approve()` sans un « oui » explicite de l'utilisateur pour un
   outil et un plafond précis.
3. **Recherche web désactivée par défaut** (`WEB_RESEARCH_DEFAULT = False`). Elle n'est
   faite que si l'utilisateur la demande explicitement.
4. **Aucune génération avant les deux validations** : scénario (validation 1) puis
   storyboard (validation 2). Le mode `mesure` de la narration ne crée aucun fichier
   audio et sert seulement à vérifier les durées.
5. **Phase 1** : français, 16:9 en 1920×1080, durées 15/30/60/90 s. Mode hybride présenté
   mais jamais engageable. Pas de musique, pas de banque d'images (phase 2).
6. **Toujours présenter les choix** : modes économique et hybride ; méthodes gabarits
   (recommandée) et atelier (sur demande, jamais imposée) ; moteurs Remotion
   (recommandé) et HyperFrames.
7. **Fichiers protégés** : ne jamais écrire dans `projects/demos/`,
   `remotion-composer/public/audio/fr-series/` ni `fr-pilot/`. Les sorties vont dans
   `projects/<projet>/` et `remotion-composer/public/audio/studio/<projet>/`.
8. **Échec = arrêt.** Un contrôle bloquant qui échoue arrête l'étape ; on explique, on
   propose une correction (ex. reformuler une phrase), on ne force jamais.
9. **Validation = artefact exact.** Une validation humaine porte sur le contenu exact
   présenté à l'utilisateur, prouvé par son empreinte SHA-256 et par la citation de son
   accord (voir « Validations humaines » ci-dessous). Ne jamais valider à sa place.

## Initialisation du projet Studio (fin de l'étape `idea`)

Ordre imposé, une seule fois, AVANT le premier checkpoint :

```python
from lib.studio import project as prj
project_dir = prj.create_project(slug, titre, idee, duree_s)   # dossier neuf, identité Studio
prj.register_with_backlot(project_dir)                         # project.json aligné (Backlot)
```

puis `python -m backlot open <slug>` (non bloquant). Seulement ensuite :
`write_checkpoint(..., pipeline_type="studio-fr")`. Pour ce pipeline,
`register_with_backlot` remplace l'appel direct à `init_project` (elle l'appelle elle-même,
avec les identités alignées) : ne jamais appeler `init_project` ni `write_checkpoint` avant
`create_project`, ni sur `projects/demos/` ou `projects/pilote-gestion-temps/`.
Lot P0-C : tout checkpoint `studio-fr` s'écrit exclusivement via
`ckp.write_studio_checkpoint(project_dir, étape, statut, artefacts, ...)`
(`from lib.studio import checkpoints as ckp`), qui vérifie puis appelle `write_checkpoint` ;
jamais d'appel direct (un tel checkpoint n'a pas de trace d'intégrité et bloque la suite).

## Validations humaines : l'artefact exact (règle absolue)

| Étape | Validation | Présentation | Enregistrement |
|---|---|---|---|
| `script` | Validation 1 | `val.presentation(project_dir, "scenario")` | `val.validate_script(...)` |
| `scene_plan` | Validation 2 | `val.presentation(project_dir, "storyboard", version="vNNN")` | `val.validate_storyboard(..., "vNNN", ...)` |
| `assets` | Validation 3 | `val.presentation(project_dir, "narration", version="vNNN")` | `val.validate_narration(..., "vNNN", ...)` |

(`from lib.studio import validations as val`.) Pour chaque validation :

1. Produire l'artefact final, puis calculer son empreinte (lecture seule) :
   `shown = val.presentation(...)`.
2. Présenter exactement ces fichiers (`shown["fichiers"]`) et indiquer l'empreinte
   `shown["empreinte"]`. Fin du tour : attendre la réponse de l'utilisateur.
3. Seul un accord explicite compte. Silence, réponse ambiguë, accord donné sur une autre
   question ou « continue » sans objet : ce n'est pas un accord.
4. Accord explicite reçu → valider aussitôt, sans aucune écriture intermédiaire :
   `empreinte_presentee=shown["empreinte"]`,
   `accord_utilisateur="<mots exacts de l'utilisateur, sans reformulation>"`.
5. Refus « pas exactement celui présenté » : ne jamais recalculer l'empreinte pour forcer ;
   présenter de nouveau l'artefact actuel et redemander l'accord.
6. Écrire le checkpoint `completed` avec `human_approved=True` seulement après une
   validation réussie ; l'artefact du checkpoint est celui qui a été validé.

Toute modification après validation la rend caduque (`is_current` la refuse ; l'étape
suivante aussi) : il faut présenter le nouvel artefact et obtenir un nouvel accord.

## Déroulé

| Étape | Skill | Ce que tu présentes | Validation |
|---|---|---|---|
| `idea` | `pipelines/studio-fr/idea-director` | Idée reformulée, valeurs par défaut annoncées | — |
| `proposal` | `pipelines/studio-fr/proposal-director` (+ `meta/studio-creative-router`) | 2 ou 3 concepts, modes, méthodes, moteurs, devis 0 € | ✅ |
| `script` | `pipelines/studio-fr/script-director` | Narration complète + tous les textes à l'écran + mesures | ✅ Validation 1 |
| `scene_plan` | `pipelines/studio-fr/scene-director` | Storyboard en images (`StoryboardTool`, local, 0 €) + tableau | ✅ Validation 2 |
| `assets` | `pipelines/studio-fr/asset-director` | Rapport de narration | — |
| `edit` | `pipelines/explainer/edit-director` + règles ci-dessous | — | — |
| `compose` | `pipelines/explainer/compose-director` + règles ci-dessous | Rapport de rendu | — |
| `publish` | `pipelines/studio-fr/publish-director` | MP4 + rapport de contrôle qualité (`QualityControlTool` obligatoire ; publication refusée si non conforme) ; export uniquement via `exporter_video` | ✅ Validation finale |

Lot P0-C (prime sur les lignes `assets`, `edit`, `compose` et `publish` ci-dessus) :
`assets` porte la validation 3 (accord explicite exigé au checkpoint) ; `edit` suit
`pipelines/studio-fr/edit-director` (coupes du storyboard validé, aucune nouvelle coupe) ;
`compose` suit `pipelines/studio-fr/compose-director` (rendu exclusivement par
`lib/studio/render.py`) ; `publish` est gelée pour le studio jusqu'au lot P0-D : aucun export,
et `write_studio_checkpoint` refuse tout checkpoint `publish`.

Lis chaque skill d'étape AVANT de travailler dans l'étape (Rule Zero d'AGENT_GUIDE.md) et
écris un checkpoint à la fin de chaque étape (`skills/meta/checkpoint-protocol.md`).

## Règles studio pour les étapes réutilisées de l'explainer

- **edit** : distinguer deux notions (à 30 i/s).
  - **Marge de sécurité de narration** : la parole finit au moins 0,5 s avant la fin
    utile de la scène, et la fin utile retire en plus 8 images de marge pour toute scène
    qui n'est pas un graphique. Ces 8 images ne sont **pas** une transition : elles
    préservent le temps nécessaire à la narration.
  - **Transitions visuelles réelles** (méthode gabarits) : un graphique sort par un fondu
    de 15 images ; les autres scènes (`hero_title`, `stat_card`, `comparison`…) se
    terminent par une coupe franche suivie de l'animation d'entrée de la scène suivante.
    Les surimpressions `section_title` sortent en fondu (15 images).

  Ne jamais accélérer la voix.
- **compose** : le `render_runtime` validé à la proposition s'applique. Avec Remotion et
  la méthode gabarits, rendre en 1920×1080 avec
  `--config=remotion.fr-locale-v4.config.ts` (variantes françaises des titres, KPI, chiffres clés,
  graphiques, barres de progression). Narration :
  `remotion-composer/public/audio/studio/<projet>/vNNN/narration_fr.wav`. Pas d'emoji
  dans les titres (HeroTitle découpe en UTF-16).
- **publish** : **Contrôle qualité obligatoire** avant toute publication, en lecture seule :

  ```python
  from lib.studio.qc import QualityControlTool, publication_allowed
  res = StudioBudgetGuard(project_dir).run(QualityControlTool(), {
      "mp4": mp4, "props": props_rendu, "timing": timing_fr, "project_dir": str(project_dir),
      "storyboard_dir": dossier_storyboard_valide, "script": scenario_valide,
  })
  ```

  Bloquants : format (1920×1080, 30 i/s, H.264 + AAC, durée), volume -16 LUFS ± 1,
  true peak du MP4 ≤ -1,0 dBFS, écrêtage, marge de parole < 0,25 s, décalage de fin de
  phrase > 0,10 s, parole hors scène ou dans la dernière seconde, noir réel ≥ 0,5 s,
  différence avec le storyboard validé (écart moyen ≥ 2 % OU une tuile 20×20 px avec
  ≥ 3 pixels fortement différents : la moyenne ne masque jamais une anomalie localisée),
  texte différent du storyboard ou du scénario validés. Avertissements (montrés à l'utilisateur) : marge de 0,25 à 0,5 s, scène
  entièrement figée, début de phrase hors de la plage normale. Le WAV de narration reste
  contrôlé à true peak ≤ -1,5 dBFS (lot 1.2).
  Si `publication_allowed(res)` est faux, la vidéo n'est jamais présentée comme vidéo
  finale sans rapport de contrôle conforme : présenter `controle/vNNN/rapport_qc.md`,
  les bloquants et une correction proposée.
- Si une skill de l'explainer suggère un sélecteur (`tts_selector`, `image_selector`,
  `video_selector`), une musique ou un fournisseur payant : **ignorer** cette suggestion
  en phase 1 et appliquer les règles ci-dessus.

## Journal des décisions

Chaque choix est consigné dans `decision_log` (catégories existantes :
`pipeline_selection`, `composition_mode`, `render_runtime_selection`, `budget_tradeoff`,
`voice_selection`, `music_source`) avec les options écartées. Si un choix change en
cours de route, ajouter une nouvelle entrée avec la même `category` et le même `subject`.
