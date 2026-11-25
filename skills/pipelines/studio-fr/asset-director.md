# Asset Director — OpenMontage Studio (studio-fr)

## Quand l'utiliser

Étape `assets`, après les validations 1 (scénario) et 2 (storyboard) : produire la
narration définitive. En phase 1, c'est la seule ressource générée.

## Narration

Voix imposée, sans sélection automatique : `PiperFrNarration` (Piper
`fr_FR-siwis-medium`, méthode V2), via le garde-fou budgétaire :

```python
from lib.studio.budget_guard import StudioBudgetGuard
from lib.studio.narration import PiperFrNarration
res = StudioBudgetGuard(project_dir).run(PiperFrNarration(), {
    "mode": "placement", "script": script_valide, "project_dir": str(project_dir),
    "section_options": {"<id>": {"fade_out_frames": 15}},
})
```

- `res.success` faux → lire `res.error` (souvent « reformuler ») : revenir au scénario
  avec l'utilisateur, ne jamais accélérer ni forcer.
- Lire `controle/rapport_narration.md` : bloquants à zéro ; avertissements présentés à
  l'utilisateur.
- Le fichier pour Remotion est dans
  `remotion-composer/public/audio/studio/<projet>/vNNN/narration_fr.wav` ; chaque
  exécution crée une nouvelle version, rien n'est écrasé.

## Validation 3 — narration (accord explicite, artefact exact)

Après une narration conforme (bloquants à zéro), calculer l'empreinte de ce qui est présenté,
présenter, puis valider dès l'accord explicite, sans régénérer ni modifier entre-temps
(règle « Validations humaines » de `executive-producer`) :

```python
from lib.studio import validations as val
shown = val.presentation(project_dir, "narration", version="vNNN")   # piste, timing, rapport
# … présentation : rapport_narration.md, piste narration_fr.wav, durées et marges, empreinte …
# … fin du tour, accord explicite de l'utilisateur …
val.validate_narration(project_dir, "vNNN", empreinte_presentee=shown["empreinte"],
                       accord_utilisateur="<mots exacts de l'utilisateur>")
```

Une nouvelle exécution crée une nouvelle version `vNNN` : la présenter et obtenir un nouvel
accord. Sans validation 3 à jour, le checkpoint `assets` et le rendu sont refusés.

## Interdits en phase 1

Aucun sélecteur (`tts_selector`, `image_selector`, `video_selector`), aucune musique,
aucune banque d'images, aucun service payant. Le garde-fou refuserait ; ne pas essayer.

## Sortie

`asset_manifest` conforme au schéma : narration, rapport de contrôle, coût total 0. Il cite
la piste validée `assets/narration/vNNN/narration_fr.wav`. Checkpoint, uniquement après la
validation 3 :

```python
from lib.studio import checkpoints as ckp
ckp.write_studio_checkpoint(project_dir, "assets", "completed",
                            {"asset_manifest": asset_manifest}, human_approved=True)
```
