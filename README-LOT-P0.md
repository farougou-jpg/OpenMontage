# Lot P0 — sécurisation Backlot / Studio

## Contenu
- `lib/studio/narration/tool.py` : `PROJECTS_ROOT` devient un alias de compatibilité
  de `lib.paths.PROJECTS_DIR`; le contrôle de zone accepte une racine projets externe
  au dépôt, utile pour staging et tests isolés.
- `lib/studio/project.py` : rattachement explicite à la racine canonique.
- `backlot/project_metadata.py` : lecture de `cree_le` dans `studio_project.json`,
  avec compatibilité des anciens `validations.json`.
- `lib/pipeline_loader.py` : copie défensive du manifeste mis en cache.
- `tools/tool_registry.py` : suppression du caractère parasite initial `•`.
- `config.studio.yaml` : profil Studio dédié, budget par défaut nul et allowlist vide.
- `tests/test_studio_patch_regressions.py` : tests ciblés.

## Précautions
- Le `config.yaml` global n'est pas modifié.
- Aucun dossier `projects/`, rendu, MP4, storyboard, scénario, validation ou export
  n'est inclus dans ce lot.
- `PROJECTS_ROOT` est conservé comme alias pour préserver les imports existants.
- Vérifier la protection des dossiers protégés sur l'installation réelle avant mise
  en production, notamment si `OPENMONTAGE_PROJECTS_DIR` est défini.

## Application
1. Sauvegarder le dépôt.
2. Extraire le ZIP dans un dossier temporaire et comparer les fichiers.
3. Appliquer les fichiers source et `config.studio.yaml` après validation.
4. Ne jamais remplacer `config.yaml` par le profil Studio.

## Tests
Depuis la racine du dépôt :

    python -m pytest tests/test_studio_patch_regressions.py -q
    python -m pytest tests/test_project_metadata.py tests/test_studio_reader.py -q

Exécuter ensuite les suites Studio existantes avec leurs médias de test requis.
Ce lot ne prétend pas que toute la suite du dépôt a été exécutée.
