# Scene Director — OpenMontage Studio (studio-fr)

## Quand l'utiliser

Étape `scene_plan` : construire le storyboard à partir du scénario validé et obtenir la
**validation 2**. Pour le métier (variété, rythme visuel), s'appuyer aussi sur
`skills/pipelines/explainer/scene-director.md` ; en cas de conflit, cette skill prime.

## Procédure

1. Une scène par section du scénario (mêmes identifiants, mêmes bornes de temps).
2. **Méthode gabarits** (recommandée) : choisir un type de scène existant
   (`skills/meta/studio-creative-router.md` §1), le style (playbook) validé et la
   transition. Préférer les variantes françaises validées (`hero_title`, `kpi_grid`,
   `bar_chart`, `pie_chart`, `progress_bar`). Pour les autres types, prévoir une
   vérification visuelle du texte français.
3. **Méthode atelier** (si l'utilisateur l'a choisie) : suivre
   `skills/meta/bespoke-composition.md` ; écrire l'art direction avant les scènes.
4. Pas deux fois de suite le même type sur trois scènes ; au moins 3 types différents
   dès 30 s.
5. Transitions visuelles réelles (méthode gabarits, 30 i/s) : un graphique sort par un
   fondu de 15 images ; les autres scènes se terminent par une coupe franche suivie de
   l'animation d'entrée de la scène suivante (`transition_in` / `transition_out` sont
   ignorés pour ces scènes) ; les surimpressions `section_title` sortent en fondu de
   15 images. Ne pas promettre d'autres fondus ou coupes paramétrées (voir A4,
   `studio/docs/ameliorations.md`).
   Marge de sécurité de narration, distincte de toute transition : la parole finit au
   moins 0,5 s avant la fin utile de la scène. Pour une scène qui n'est pas un graphique,
   la fin utile retire 8 images de marge (aucun effet visuel). Pour un graphique, elle
   retire 15 images, la durée de son fondu de sortie.
6. Phase 1 : aucun visuel externe (ni image, ni vidéo, ni musique).

## Storyboard en images (méthode gabarits)

Écrire le brouillon de props Remotion (scènes `cuts`, style `theme`, sans audio ni image
de fond), puis rendre une image fixe par scène, en local et gratuitement :

```python
from lib.studio.budget_guard import StudioBudgetGuard
from lib.studio.storyboard import StoryboardTool
res = StudioBudgetGuard(project_dir).run(StoryboardTool(), {
    "props": brouillon_props, "project_dir": str(project_dir), "title": "…",
    "narration": {"<id_scene>": "extrait de narration"},
})
```

- Brouillon refusé (`res.success` faux) → corriger le type de scène, les temps ou le style.
- Sorties : `projects/<projet>/storyboard/vNNN/` (`planche.png`, `storyboard.html`,
  `storyboard.md`, `scenes/`). Rien n'est écrasé.
- Regarder chaque image : texte coupé, trop petit, police inattendue → le signaler.
- Méthode atelier : le storyboard en images viendra avec la composition sur mesure.

## Validation 2 — ce que tu présentes

La planche (`planche.png`) et la page `storyboard.html`, plus ce tableau :

| Scène | Début–fin | Type | Texte à l'écran | Narration | Transition |
|---|---|---|---|---|---|

Avec le style, le format 1920×1080, la méthode de composition et le moteur. Attendre
l'accord explicite de l'utilisateur avant toute génération audio ou vidéo. L'artefact produit est
conforme à `schemas/artifacts/scene_plan.schema.json`.

Empreinte du storyboard présenté (tous les fichiers de `storyboard/vNNN/`), calculée avant
la présentation, puis validation 2 dès l'accord explicite, sans rien régénérer entre-temps :

```python
from lib.studio import validations as val
shown = val.presentation(project_dir, "storyboard", version="vNNN")
# … présentation, accord explicite de l'utilisateur …
val.validate_storyboard(project_dir, "vNNN", empreinte_presentee=shown["empreinte"],
                        accord_utilisateur="<mots exacts de l'utilisateur>")
```

Un nouveau rendu du storyboard crée une nouvelle version `vNNN` : la présenter et obtenir
un nouvel accord ; l'empreinte d'une autre version est refusée.
