# Script Director — OpenMontage Studio (studio-fr)

## Quand l'utiliser

Étape `script` : écrire la narration française et tous les textes à l'écran du concept
validé, vérifier que chaque phrase tient, puis obtenir la **validation 1**.
Pour le métier d'écriture (accroche, arc, rythme), s'appuyer aussi sur
`skills/pipelines/explainer/script-director.md` ; en cas de conflit, cette skill prime.

## Règles d'écriture (méthode V2 validée)

- Voix unique : Piper `fr_FR-siwis-medium`, `length_scale` 1.0. **Jamais d'accélération** :
  si une phrase ne tient pas, on la raccourcit.
- Phrases courtes, une idée par scène ; la parole occupe au plus ~75 % de la scène.
- Écrire les nombres naturellement (« 30 min », « 1 heure », « 29,99 € ») : la
  normalisation du studio les lit correctement. Un accord incertain est signalé, pas
  corrigé : reformuler si le rapport le demande.
- Éviter : « prompt » (dire « consigne »), « dix-huit » en milieu de groupe (le t final
  tombe : le placer en fin de proposition), les mots anglais non listés dans le LEXICON,
  les emoji dans les titres.
- Pauses explicites possibles : `[pause 0.4]` (0 < durée ≤ 3 s). Aucun autre `[...]`.
- Débit `fast` interdit dans `delivery_cues.pace`.

## Vérification des durées (sans fichier audio)

```python
from lib.studio.budget_guard import StudioBudgetGuard
from lib.studio.narration import PiperFrNarration
res = StudioBudgetGuard(project_dir).run(PiperFrNarration(), {
    "mode": "mesure", "script": script, "project_dir": str(project_dir),
    "section_options": {"<id>": {"fade_out_frames": 15}},   # 15 pour un graphique, 8 sinon
})
```

Chaque section doit avoir `tient: true`. Sinon : reformuler, puis mesurer à nouveau.
Le mode `mesure` n'écrit qu'un rapport JSON de durées.

## Validation 1 — ce que tu présentes

1. Tableau de **tous les textes à l'écran**, scène par scène.
2. **Narration complète**, telle qu'écrite et telle qu'elle sera lue (texte normalisé).
3. Durées mesurées, débit (syllabes/s), marge avant chaque fondu.
4. Avertissements du rapport (accord incertain, mot étranger…).

Attendre l'accord explicite de l'utilisateur. Aucune narration définitive avant.
L'artefact produit est conforme à `schemas/artifacts/script.schema.json`.
