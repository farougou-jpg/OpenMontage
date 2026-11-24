# Améliorations à traiter dans un lot ultérieur dédié

Registre ouvert au lot 1.5 (2026-11-18). Aucun de ces points n'est corrigé : chaque
correction fera l'objet d'un plan soumis à validation.

## A1 — `text_card` : police hors thème

- **Constat** (storyboard de test, lot 1.5, style `flat-motion-graphics`) : le texte
  s'affiche dans une police système au lieu de Space Grotesk (police du thème), et la
  scène n'a pas le fond dégradé des autres composants.
- **Impact** : incohérence graphique avec `hero_title`, `comparison`, graphiques.
- **Piste** : variante `TextCard.fr.tsx` (modèle validé : `HeroTitle.fr.tsx`), sans
  modifier l'original ; ajout à la configuration FR.
- **En attendant** : ne pas utiliser `text_card` dans le pilote (décision du 2026-11-18).

## A2 — `callout` : police hors thème et texte trop petit

- **Constat** : même police système ; texte d'environ 1 % de la hauteur d'image en
  1920×1080, difficile à lire en vidéo.
- **Piste** : variante `CalloutBox.fr.tsx` (taille de texte, police du thème).
- **En attendant** : ne pas utiliser `callout` dans le pilote.

## A4 — Pas de fondu ni de coupe paramétrable entre scènes de composants

- **Constat** (lecture d'`Explainer.tsx`, 2026-11-18) : `transition_in` / `transition_out`
  ne sont appliqués qu'aux scènes vidéo. `hero_title`, `stat_card`, `comparison`,
  `text_card`, `callout` n'ont aucun fondu de sortie : le passage est toujours une coupe
  franche suivie de l'animation d'entrée. Seuls les graphiques ont un fondu (15 images).
- **Impact** : l'alternance « fondus / coupes sèches » demandée pour le pilote n'est pas
  réalisable en méthode gabarits sans modifier le moteur ou les composants.
- **Pistes** : (a) lot dédié : enveloppe de transition pour les scènes de composants
  (variante `.fr` ou paramètre), sans modifier les originaux ; (b) méthode atelier.
- **Corrigé le 2026-11-18** dans `skills/pipelines/studio-fr/scene-director.md` et
  `executive-producer.md` : la marge de 8 images est présentée comme marge de sécurité de
  narration, distincte des transitions réelles (test
  `test_skills_distinguish_safety_margin_from_transitions`).
- **Reste à harmoniser (autorisation requise)** : `skills/pipelines/studio-fr/script-director.md`
  (commentaire « 15 pour un graphique, 8 sinon » et « marge avant chaque fondu »).

## A3 — `section_title` présenté à tort comme type de scène

- **Constat** : dans `Explainer.tsx`, `section_title` et `stat_reveal` sont uniquement des
  surimpressions (`overlays`), pas des scènes (`cuts`).
- **Corrigé au lot 1.5** : `lib/studio/storyboard/props_check.py` les refuse comme scènes
  (test `test_cut_types_match_what_explainer_renders`).
- **Reste à corriger (fichiers du lot 1.3, autorisation requise)** :
  `skills/meta/studio-creative-router.md` (liste des types de scènes) et
  `studio/docs/evaluation-aiguilleur.md` (scènes `section_title` des idées 2, 3 et 4).

## A5 — `stat_card` : police hors thème

- **Constat** (storyboard du pilote, 2026-11-18) : `StatCard.tsx` demande la police « Inter »,
  non chargée dans le projet ; repli sur une police système (fond uni conservé).
- **Décision** : option C1 — police Space Grotesk seule, graisse 700 pour le chiffre, fond inchangé.
- **Corrigé en v4** : `remotion-composer/src/components/StatCard.fr.tsx` (3 lignes : police et graisse)
  activé par `remotion.fr-locale-v4.config.ts` ; `StatCard.tsx` et la v3 inchangés
  (tests `tests/studio/test_fr_v4.py`). Les vidéos validées gardent leur rendu d'origine (v1 à v3).
