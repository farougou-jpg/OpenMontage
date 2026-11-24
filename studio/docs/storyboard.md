# Storyboard en images (lot 1.5)

Outil : `lib/studio/storyboard` → `StoryboardTool` (`studio_storyboard`). Local, gratuit,
hors registre automatique, appelé via le garde-fou budgétaire.

## Principe

Une image fixe par scène, rendue avec les vrais composants Remotion francisés
(`remotion.fr-locale-v4.config.ts` par défaut ; `v3` sur demande via `remotion_config`, pour
comparer avec les vidéos validées rendues avant la v4), puis une planche. Aucune IA : ce sont des captures
de la future vidéo. Aucun audio, aucune vidéo produits.

## Entrée

Brouillon de props `Explainer` (méthode gabarits) : `theme` parmi les 4 styles du studio,
`cuts` contiguës, types autorisés en phase 1, sans audio, sans image ni vidéo de fond.

## Instant de chaque image

- Texte : ~60 % de la scène, au moins 1,5 s après son début.
- Graphiques, KPI, barres de progression, chiffres : état final.
- Toujours avant la fin de scène : 15 images avant pour un graphique (fondu réel), 8 images
  de marge pour les autres, plus 3 images de sécurité.

## Transitions réelles (moteur Explainer)

- Graphiques (`bar_chart`, `line_chart`, `pie_chart`, `kpi_grid`) : fondu de sortie de 15 images.
- `hero_title`, `stat_card`, `comparison`, `text_card`, `callout` : coupe franche, puis
  animation d'entrée de la scène suivante. `transition_in` / `transition_out` ne sont
  appliqués qu'aux scènes vidéo : sur une scène de composant, ils sont ignorés (avertissement).
- Surimpressions : `section_title` sort en 15 images, `stat_reveal` en 12.

## Règle de variété

Avertissement (non bloquant) au-delà de 2 scènes du même type d'affilée, sauf si chacune
porte une surimpression `section_title` distincte. Les cinq vidéos validées passent sans
erreur (stop-procrastinating : avertissement seulement).
- Ajustable par scène (`still_at_seconds`).

## Rendu 100 % local

Binaire Remotion du projet (pas `npx`), navigateur `chrome-headless-shell` déjà installé
passé explicitement (`--browser-executable`), cache webpack désactivé
(`--bundle-cache=false`) : rien n'est écrit dans `node_modules`. Environ 10 s par image.

## Sorties

`projects/<projet>/storyboard/vNNN/` : `scenes/scene_NN.png` (1920×1080), `planche.png`,
`storyboard.html` (hors ligne, sans ressource externe), `storyboard.md`,
`storyboard.json`, `props_storyboard.json`. Zones protégées refusées, jamais d'écrasement.

## Fidélité vérifiée

Sur code-to-screen FR (props et MP4 validés, lus sans modification) : écart moyen entre
l'image fixe et l'image du MP4 au même instant < 2 % (0,48 % mesuré sur le titre).

## Configuration v4 (lot v4)

v4 = v3 + `StatCard.fr.tsx` (police Space Grotesk, graisse 700 pour le chiffre ; fond, tailles,
couleurs et animations identiques). La configuration utilisée est inscrite dans
`storyboard.json` (`configuration_rendu`) : le rendu final doit utiliser la même. La v3 reste
intacte et sert à reproduire / comparer les vidéos françaises validées.
