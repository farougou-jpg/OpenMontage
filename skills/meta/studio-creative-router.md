# Aiguilleur créatif — OpenMontage Studio

## Quand l'utiliser

À l'étape `proposal` du pipeline `studio-fr` (et plus tard dans les phases 2 à 4) :
choisir les techniques visuelles adaptées à l'idée de l'utilisateur. Le choix créatif
t'appartient ; ce qui est *possible* est dit par `lib/studio/capabilities.py`.

## 1. Lire le besoin

Dans le `brief`, repérer :

| Signal dans l'idée | Ce qu'il appelle |
|---|---|
| Chiffres, pourcentages, comparaisons | `kpi_grid`, `stat_card`, `bar_chart`, `pie_chart`, `line_chart`, `comparison` (+ surimpression `stat_reveal`) |
| Étapes, méthode, liste de conseils | `hero_title` + surimpression `section_title` (« Étape n »), `progress_bar`, `callout`, `text_card` |
| Message de marque, accroche, appel à l'action | `hero_title`, `text_card`, `callout` |
| Problème → solution | `hero_title` + surimpression `section_title`, puis `comparison` (avant/après) |
| Technique, code, outil logiciel | `terminal_scene` |
| Personnages, lieux, émotion, récit | Illustrations ou séquences IA → **phase 2/3** (voir §4) |

Types de scènes disponibles en phase 1 (gabarits Remotion) : `hero_title`,
`text_card`, `stat_card`, `kpi_grid`, `bar_chart`, `line_chart`, `pie_chart`,
`progress_bar`, `comparison`, `callout`, `terminal_scene`.
Surimpressions uniquement (jamais comme scène) : `section_title`, `stat_reveal`.
Variantes françaises validées : `hero_title`, `kpi_grid`, `bar_chart`, `pie_chart`,
`progress_bar`. Les autres affichent du texte français mais n'ont pas encore été audités
visuellement en FR : le signaler et les vérifier au storyboard.
Exclus en phase 1 : `screenshot_scene` (exige une capture fournie), `anime_scene`
(exige des images générées).

## 2. Choisir le style et le rythme

| Style (playbook existant) | Pour |
|---|---|
| `flat-motion-graphics` | Publicité, réseaux sociaux, promotionnel : énergique, coloré |
| `clean-professional` | Entreprise, explicatif sérieux, finance |
| `minimalist-diagram` | Formation, procédures, schémas |
| `premium-minimalist` | Marque haut de gamme, storytelling sobre |

Rythme (scènes de gabarit) : 15 s → 3-4 scènes ; 30 s → 5-7 ; 60 s → 8-12 ; 90 s → 12-16.
Narration Piper : environ 2,3 mots/s en moyenne, à confirmer par le mode `mesure`.
Garder de l'air : la parole occupe au plus ~75 % de chaque scène.

## 3. Présenter systématiquement les deux modes

```python
from lib.studio.capabilities import modes_status, composition_methods, render_runtimes
```

- **Mode économique — sélectionné par défaut, 0 €** : motion design + narration Piper
  locale (illustrations vectorielles en phase 2).
- **Mode hybride** : motion design + séquences vidéo générées par IA. En phase 1 :
  « indisponible » avec les prérequis (`ModeStatus.requirements`). Plus tard : seulement
  avec devis préalable et autorisation explicite. Ne jamais l'activer seul, ne jamais
  appeler un service payant pour « tester ».

## 4. Être honnête sans basculer

Si l'idée gagnerait clairement à avoir des personnages, des décors ou des séquences
filmées (storytelling, témoignage, produit physique) :

1. le dire en une phrase (« cette histoire serait plus forte avec des illustrations de
   Léa ; c'est prévu en phase 2/3 ») ;
2. proposer la **meilleure version économique** : typographie narrative, citations en
   `text_card`, chiffres clés, icônes de texte, rythme ;
3. ne jamais changer de mode, de fournisseur ou de budget sans l'accord de l'utilisateur.

**Règle — témoignages.** Une histoire fictive ne doit jamais être présentée comme un
témoignage réel. Toute présentation sous forme de témoignage nécessite des faits réels
et l'accord de la personne concernée. Sinon, annoncer clairement une histoire
illustrative (ex. « histoire inspirée de situations courantes »).

**Règle — storytelling dans les phases ultérieures.** Pour les projets de storytelling,
prévoir dans les phases ultérieures la possibilité d'utiliser des illustrations
vectorielles, des personnages animés et des décors illustrés. Le signaler à
l'utilisateur dans la proposition, sans l'activer avant que ces outils existent.

## 5. Méthode de composition et moteur de rendu

- **Gabarits** — recommandés par défaut : scènes Remotion existantes, déjà francisées et
  validées sur les cinq vidéos françaises.
- **Atelier** — disponible à la demande : composition sur mesure
  (`skills/meta/bespoke-composition.md`), plus distinctive, plus longue. Ne jamais forcer
  les gabarits si l'utilisateur choisit l'atelier.
- **Moteur** : Present both — Remotion (recommandé : composants FR validés) et
  HyperFrames (HTML/GSAP, pas encore de variantes françaises validées). Le champ
  `render_runtime` n'est fixé qu'après accord de l'utilisateur.

## 6. Fiche d'aiguillage (format de sortie)

Pour chaque idée, produire :

| Rubrique | Contenu |
|---|---|
| Vérifications | Résultat de `check_request` (défauts appliqués, refus) |
| Mode retenu | Économique (défaut) ou autre si l'utilisateur l'a demandé + justification |
| Style visuel | Playbook + justification |
| Types de scènes | Séquence proposée, durées approximatives |
| Moteur de rendu | Remotion recommandé, HyperFrames présenté |
| Méthode de composition | Gabarits recommandés, atelier possible |
| Refusé et pourquoi | Mode hybride, formats, scènes exclues, recherche web… |
| Devis | `capabilities.quote(outils, guard)` : 0 € attendu |

Puis consigner dans `decision_log` : `pipeline_selection` (mode),
`composition_mode`, `render_runtime_selection`, `playbook_selection`, `budget_tradeoff`,
avec les options écartées et leur motif.
