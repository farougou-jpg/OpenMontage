# Edit Director — OpenMontage Studio (studio-fr)

## Quand l'utiliser

Étape `edit`, après les validations 2 (storyboard) et 3 (narration). Remplace, pour le
studio, l'edit-director de l'explainer (décision D4).

## Règle unique : aucune nouvelle coupe

Le montage du studio est celui du storyboard validé. `edit_decisions` reprend exactement les
coupes de `storyboard/vNNN/props_storyboard.json` (version de la validation 2) : mêmes
identifiants, mêmes bornes `in_seconds` / `out_seconds`, rien d'ajouté ni de retiré.
`render_runtime` vaut `"remotion"` (phase 1 : seul moteur de rendu du studio).

Les règles de marge de narration et de transitions de `executive-producer` s'appliquent ;
elles sont déjà portées par le storyboard validé. Aucune musique en phase 1.

```python
from lib.studio import checkpoints as ckp
edit_decisions = {"version": "1.0", "render_runtime": "remotion", "cuts": [
    {"id": c["id"], "source": "storyboard/vNNN/props_storyboard.json",
     "in_seconds": c["in_seconds"], "out_seconds": c["out_seconds"]} for c in props["cuts"]]}
ckp.write_studio_checkpoint(project_dir, "edit", "completed", {"edit_decisions": edit_decisions})
```

Coupe différente du storyboard validé, ou autre moteur : checkpoint refusé. Pour changer le
montage, revenir au storyboard (nouvelle version, nouvelle validation 2).
