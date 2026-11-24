# Évaluation de l'aiguilleur créatif — lot 1.3 (2026-11-17)

Aiguilleur : `skills/meta/studio-creative-router.md`. Vérifications déterministes :
`lib/studio/capabilities.py`. Devis : `capabilities.quote()` via `StudioBudgetGuard.check()`
(aucune exécution). **Aucune génération audio ou vidéo, aucun accès réseau.**

Résultats mesurés pour les 5 idées :
- `check_request` : idées 1 à 4 acceptées sans valeur par défaut ; idée 5 refusée
  (« Format 9:16 pas encore disponible (lot 1.4) », alternative 16:9).
- Moteurs installés (`video_compose.get_info()`) : ffmpeg, remotion, hyperframes.
- Modes : économique disponible (0 €, par défaut) ; hybride indisponible (non engageable).
- Devis du plan local (narration Piper, video_compose, audio_mixer, subtitle_gen,
  visual_qa, composition_validator, export_bundle) : **0,00 $**, aucun outil refusé.

Valable pour les 5 idées :
- **Moteur** : Remotion recommandé (variantes françaises validées) ; HyperFrames présenté
  comme alternative (HTML/GSAP, pas encore de variantes FR validées).
- **Composition** : gabarits recommandés ; atelier disponible sur demande.
- **Refus communs en phase 1** : mode hybride (séquences IA : phase 3, aucune clé, carte
  graphique de 2 Go) ; musique (phase 2) ; images/vidéos d'archive (phase 2) ;
  `anime_scene` et `screenshot_scene` (exigent des images) ; recherche web (désactivée
  par défaut, activable sur demande).

---

## 1. Pilote — publicité 30 s, application de gestion du temps (16:9)

| Rubrique | Décision |
|---|---|
| Mode | **Économique** (0 €). Un message publicitaire court (problèmes → solution → appel à l'action) se porte très bien en typographie animée ; aucun personnage indispensable. |
| Style | `flat-motion-graphics` : énergique, coloré, adapté à la publicité. |
| Scènes (≈ 6) | `hero_title` accroche (0–4 s) → `text_card` problème 1 « réunions qui débordent » (4–8) → `text_card` problème 2 « notifications en rafale » (8–12) → `callout` problème 3 « liste qui ne finit jamais » (12–16) → `comparison` avant / après (16–22) → `hero_title` appel à l'action (22–30). 4 types différents. |
| Moteur | Remotion (recommandé) ; HyperFrames présenté. |
| Composition | Gabarits (recommandés) ; atelier possible pour une pub plus singulière. |
| Refusé | Hybride (plans filmés d'une personne débordée) ; musique (phase 2) ; chiffres « réels » de productivité (pas de recherche web) → formulations qualitatives. |
| À demander au scénario | Nom de l'application et formule d'appel à l'action (pas inventés). |
| Devis | **0 €** |

## 2. Explicative 60 s — « Comment fonctionne l'épargne retraite en 3 étapes »

| Rubrique | Décision |
|---|---|
| Mode | **Économique** (0 €). Contenu pédagogique, étapes et chiffres : cœur de métier des gabarits. |
| Style | `clean-professional` : sérieux, lisible, adapté à la finance. |
| Scènes (≈ 6) | `hero_title` (0–5) → `text_card` versements + surimpression `section_title` « 1. Épargner » (5–16) → `bar_chart` exemple illustratif + surimpression « 2. Faire fructifier » (16–30) → `comparison` capital / rente + surimpression « 3. Récupérer » (30–44) → `callout` points à vérifier (44–52) → `hero_title` conclusion (52–60). *(Corrigé le 2026-11-18, A3 : `section_title` est une surimpression, pas une scène.)* |
| Moteur | Remotion (recommandé) ; HyperFrames présenté. |
| Composition | Gabarits (recommandés) ; atelier sur demande. |
| Refusé | Recherche web par défaut → **aucune règle fiscale ni chiffre présenté comme réel** : graphique étiqueté « exemple illustratif », ou chiffres fournis par l'utilisateur, ou recherche activée à sa demande. `line_chart` évité (pas de variante française validée : format des nombres) au profit de `bar_chart` (validé). Hybride, musique. |
| Point de vigilance | Sujet financier : mention « information générale, pas un conseil » proposée. |
| Devis | **0 €** |

## 3. Formation 90 s — « 5 gestes pour sécuriser ses mots de passe au bureau »

| Rubrique | Décision |
|---|---|
| Mode | **Économique** (0 €). Une procédure en étapes est idéale pour le motion design. |
| Style | `minimalist-diagram` : clair, pédagogique, peu de distraction. |
| Scènes (≈ 9) | `hero_title` (0–6) → pour chacun des 5 gestes : `callout` consigne (≈ 13 s) avec surimpression `section_title` « Geste n » → `progress_bar` « 5 gestes sur 5 » (71–78) → `text_card` récapitulatif (78–85) → `hero_title` clôture (85–90). *(Corrigé le 2026-11-18, A3.)* |
| Moteur | Remotion (recommandé) ; HyperFrames présenté. |
| Composition | Gabarits (recommandés) ; atelier sur demande. |
| Refusé | `screenshot_scene` (exigerait de vraies captures d'écran : possible si l'utilisateur les fournit) ; chiffres d'incidents ou recommandations officielles citées (pas de recherche web) ; hybride ; musique. |
| Point de vigilance | `callout` sans variante française auditée → vérification visuelle au storyboard (voir A2 dans `studio/docs/ameliorations.md`). |
| Devis | **0 €** |

## 4. Storytelling 60 s — « Léa, boulangère, raconte comment elle a digitalisé sa boutique »

| Rubrique | Décision |
|---|---|
| Mode | **Économique** (0 €), **avec avertissement honnête** : cette histoire serait nettement plus forte avec des illustrations de Léa et de sa boutique (phase 2) ou des séquences générées (mode hybride, phase 3). Aucune bascule automatique. |
| Meilleure version économique | Récit typographique à la première personne : la voix Piper (féminine) incarne Léa ; citations courtes à l'écran ; trois chapitres. |
| Style | `premium-minimalist` : sobre et chaleureux, laisse la place aux mots. |
| Scènes (≈ 5) | `hero_title` « Léa, boulangère » (0–5) → `text_card` citation + surimpression `section_title` « Avant » (5–18) → `text_card` citation + surimpression « Le déclic » (18–32) → `comparison` avant / après + surimpression « Aujourd'hui » (32–48) → `hero_title` message final (48–60). *(Corrigé le 2026-11-18, A3.)* |
| Moteur | Remotion (recommandé) ; HyperFrames présenté (sa typographie cinétique pourrait servir ce récit ; à proposer comme alternative). |
| Composition | Gabarits (recommandés) ; **l'atelier est ici une vraie option** pour un récit plus singulier, à proposer explicitement. |
| Refusé | Personnages et décors (illustrations : phase 2 ; séquences IA : phase 3, hybride) ; `anime_scene` (exige des images générées) ; musique ; chiffres de ventes inventés (seulement si l'utilisateur les fournit). |
| Point de vigilance | Demander si Léa est réelle : si oui, utiliser ses vraies paroles avec son accord ; si non, présenter le récit comme une histoire illustrative, jamais comme un témoignage authentique. |
| Devis | **0 €** |

## 5. Présentation d'entreprise 30 s pour les réseaux sociaux, demandée en 9:16

| Rubrique | Décision |
|---|---|
| Vérification | **Refusée telle quelle** : « Format 9:16 pas encore disponible (lot 1.4) ». |
| Alternatives proposées | (a) produire dès maintenant en 16:9 (1920×1080) ; (b) attendre le lot 1.4 pour le 9:16 natif. L'utilisateur choisit. |
| Mode (si 16:9 accepté) | **Économique** (0 €). |
| Style | `clean-professional` (ou `flat-motion-graphics` si le ton est plus jeune). |
| Scènes (≈ 5) | `hero_title` nom et promesse (0–5) → `text_card` mission (5–11) → `kpi_grid` chiffres clés fournis par l'entreprise (11–19) → `callout` services (19–25) → `hero_title` appel à l'action (25–30). |
| Moteur | Remotion (recommandé) ; HyperFrames présenté. |
| Composition | Gabarits (recommandés) ; atelier sur demande. |
| Refusé | 9:16 (lot 1.4) ; chiffres non fournis (jamais inventés) ; hybride ; musique. |
| À demander | Nom de l'entreprise, mission, 3 à 4 chiffres réels, appel à l'action. |
| Devis | **0 €** |
