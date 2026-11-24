# Proposal Director — OpenMontage Studio (studio-fr)

## Quand l'utiliser

Étape `proposal` : transformer le `brief` en 2 ou 3 concepts, avec les choix de
production, et obtenir l'accord de l'utilisateur. Appliquer
`skills/meta/studio-creative-router.md`.

## Procédure

1. **Capacités réelles** :

   ```python
   from lib.studio.capabilities import modes_status, composition_methods, render_runtimes, quote
   from tools.tool_registry import registry
   registry.discover()
   engines = registry.get("video_compose").get_info()["render_engines"]
   ```

   Si un moteur n'est pas installé, le dire explicitement.
2. **2 ou 3 concepts réellement différents** (accroche, structure, ton), chacun avec :
   titre, accroche, déroulé en scènes, style, durée.
3. **Modes** — toujours les deux :
   - Mode économique — **sélectionné par défaut**, 0 € ;
   - Mode hybride — présenté avec son statut (indisponible en phase 1) et ses prérequis.
4. **Méthode de composition** — toujours les deux, sans en imposer une :
   - Gabarits — recommandés (francisés, validés sur les cinq vidéos françaises) ;
   - Atelier — sur demande (composition sur mesure, plus de temps).
5. **Moteur de rendu — Present both** : Remotion (recommandé pour les variantes FR
   validées) et HyperFrames (alternative HTML/GSAP). Pour chacun : une phrase sur ce
   qu'il apporte à CE projet, une phrase sur sa limite, puis ta recommandation. Le
   champ `render_runtime` du `proposal_packet` (`remotion` ou `hyperframes`) n'est
   rempli qu'après accord ; la décision `render_runtime_selection` liste les deux.
6. **Musique** : aucune en phase 1 (Pixabay arrive en phase 2). Le dire et consigner
   `music_source`.
7. **Devis** — calculé par le garde-fou, sans rien exécuter :

   ```python
   from lib.studio.budget_guard import StudioBudgetGuard
   from lib.studio.narration import PiperFrNarration
   guard = StudioBudgetGuard(project_dir)
   devis = quote([PiperFrNarration(), registry.get("video_compose"), registry.get("audio_mixer")], guard)
   ```

   Présenter le total (0 € attendu). Un outil refusé par le garde-fou n'entre pas dans le
   plan.
8. **decision_log** : `pipeline_selection` (mode), `composition_mode`,
   `render_runtime_selection` (Remotion ET HyperFrames dans `options_considered`),
   `playbook_selection`, `music_source`, `budget_tradeoff`.

## Présentation à l'utilisateur (modèle)

```
Concept A — … (recommandé)    Concept B — …    Concept C — …

Mode : ● Économique (0 €, par défaut)   ○ Hybride (indisponible en phase 1 : …)
Composition : ● Gabarits (recommandé)   ○ Atelier (sur demande)
Moteur : Remotion (recommandé, …) | HyperFrames (…)
Style : …   Durée : … s   Format : 16:9 1920×1080   Musique : aucune (phase 2)
Devis : 0 € — aucun service payant
```

Attendre le choix explicite de l'utilisateur (concept, et toute modification de mode,
de méthode ou de moteur) avant de passer au scénario.
