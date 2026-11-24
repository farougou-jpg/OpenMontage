# Contrôle qualité FR (lot 1.6)

Outil : `lib/studio/qc` → `QualityControlTool` (`studio_quality_control`). Local, gratuit,
hors registre automatique, appelé via le garde-fou budgétaire. **Obligatoire avant toute
publication** : `publication_allowed(res)` doit être vrai.

Lecture seule : le MP4, les props, le timing, le storyboard et le scénario ne sont jamais
modifiés (empreintes SHA-256 relevées avant et après, écart = bloquant). Sorties :
`projects/<projet>/controle/vNNN/` (`rapport_qc.md`, `rapport_qc.json`,
`mesures_brutes.txt`, `cmp_<scène>.png`, `planche_mp4.png`, `images/`).

## Contrôles et seuils (validés le 2026-11-18)

| Contrôle | Bloquant | Avertissement |
|---|---|---|
| Format | ≠ 1920×1080, 30 i/s, H.264 + AAC, nombre d'images ± 1 | — |
| Volume MP4 | hors −16 LUFS ± 1 | — |
| True peak MP4 | > −1,0 dBFS | — |
| Écrêtage | ≥ 1 échantillon saturé | — |
| Marge de parole (fin utile − fin de parole) | < 0,25 s | 0,25 à 0,5 s |
| Décalage audio (fin de phrase vs `timing_fr.json`) | > ± 0,10 s | début hors 0 à +0,25 s |
| Parole sans entrée dans `timing_fr.json` | — | oui |
| Parole avant le début de sa scène, dans la dernière seconde, attendue mais absente | oui | — |
| Noir réel (`pix_th` 0,02) | ≥ 0,5 s | — |
| Image figée | — | ≥ 90 % d'une scène |
| Storyboard validé | écart moyen ≥ 2 % **ou** tuile 20×20 px avec ≥ 3 pixels forts | — |
| Textes | différence avec storyboard ou scénario validés ; référence absente | — |

**Fin utile** : graphique = fin − 15 images (son fondu réel) ; autre scène = fin − 8 images
de marge de sécurité (aucun effet visuel). Règle conservée sans assouplissement (option A).

**Pixel fort** : écart > 60/255 sur un canal après un flou de 1 px (le flou efface le bruit
de compression). Calibration : 21 scènes conformes des 5 vidéos françaises → 0 ou 1 pixel
fort par tuile ; défauts simulés (accent effacé, lettre du sous-titre, décalage de 1 px,
couleur, valeur KPI) → 7 à 379. La moyenne seule (< 2 %) ne détectait aucun de ces défauts.

**Parole** : `silencedetect` −45 dB, 0,25 s (calibré : retrouve le rapport manuel de
world-in-numbers à ± 0,1 s). Les débuts mesurés sont ~0,13 s après `debut` (rembourrage
0,08 s + fondu d'entrée) : le décalage est donc contrôlé sur les fins de phrase.

## Constats sur les vidéos validées (lecture seule, aucune modification)

| Vidéo | Verdict selon ces règles | Détail |
|---|---|---|
| animated-reel-20s | **non conforme** | marges 0,18 s (hook) et 0,21 s (story) < 0,25 s ; titre final : surlignage coupant « po\|ur » (défaut corrigé ensuite par la configuration FR v2) |
| code-to-screen | conforme | — |
| focusflow-pitch | conforme | — |
| stop-procrastinating | conforme | — |
| world-in-numbers | conforme, 1 avertissement | marge finale 0,38 s (identique au rapport manuel) |

Ces règles s'appliquent aux productions du studio ; les vidéos validées restent intactes.

## Règle de publication (fail closed)

`publication_allowed(res)` n'autorise la publication que si `res` est un résultat de
`QualityControlTool` avec `success is True`, `conforme is True` (booléen strict), aucun
bloquant, et si le rapport `rapport_qc.json` écrit sur disque est lisible et dit lui aussi
conforme sans bloquant. Toute autre situation — erreur, exception (convertie en échec par
l'outil), résultat absent ou fabriqué, valeur non booléenne, rapport manquant, illisible ou
contradictoire — entraîne un refus. Vérifié par `tests/studio/test_qc_publication_refusals.py`
(10 cas réels individuels + cas fail closed).

## Verrou de publication (lot 1.6)

Trois protections techniques, vérifiées par `tests/studio/test_publication_lock.py` :

- **Garde-fou** (`StudioBudgetGuard.run`) : tout outil de publication (`ToolTier.PUBLISH`,
  dont `export_bundle`) est refusé sans contrôle conforme dont l'empreinte SHA-256 et la
  taille du MP4 correspondent exactement au fichier à publier.
- **Export du studio** (`lib/studio/publish.exporter_video`, seul chemin de publication du
  pipeline `studio-fr`) : même vérification, copie de transit revérifiée, empreinte du
  fichier exporté revérifiée (l'export de l'appel est retiré en cas d'écart).
- **`export_bundle` lui-même** : pour une vidéo ou un dossier d'export situé dans un projet
  Studio (marqueur `studio_project.json` ou sorties versionnées `assets/narration/vNNN`,
  `storyboard/vNNN`, `controle/vNNN`), un appel direct est refusé sans `studio_qc_report`
  conforme, situé dans `controle/` du projet, portant sur ce MP4 exact. Les projets hors
  Studio ne sont pas concernés (comportement inchangé).

**Ces protections ne sont pas absolues.** Elles bloquent les erreurs et les contournements
qui passent par les outils d'OpenMontage ; elles ne peuvent pas empêcher des manipulations
manuelles faites directement sur les fichiers, hors de tout outil.

## Limites connues

**Protections techniques du Studio — ce qu'elles ne couvrent pas :**

- **MP4 copié hors des projets Studio** : un MP4 issu du studio, copié dans un dossier qui
  n'est pas un projet Studio puis exporté vers un dossier qui n'en est pas un non plus,
  est indiscernable d'une vidéo ordinaire : `export_bundle` l'exporte sans contrôle.
- **Rapport falsifié manuellement** : un `rapport_qc.json` modifié ou fabriqué à la main
  et déposé dans `controle/` du projet par une personne ayant accès aux fichiers n'est pas
  détecté (aucune signature cryptographique). Le verrou vérifie la cohérence du rapport,
  pas son authenticité.

**Manipulations manuelles externes — hors de portée de tout outil :**

- **Copie manuelle d'un MP4** (explorateur de fichiers, commande de copie, envoi direct
  sur une plateforme) : aucun logiciel du projet ne peut l'empêcher.
- **Modification du code** du studio ou d'`export_bundle` : elle supprimerait les
  vérifications.

La règle « publication uniquement avec un contrôle qualité conforme » reste donc aussi une
consigne (`skills/pipelines/studio-fr/executive-producer.md`,
`skills/pipelines/studio-fr/publish-director.md`) que l'agent doit respecter.

**Autres limites du contrôle :**
- **VFR** : extraction d'image par numéro d'image (`select=eq(n,…)`), valable pour un MP4 à
  30 i/s constant ; un MP4 à fréquence d'images variable n'a pas été testé.
- **Pas d'OCR** (Tesseract non installé) : les textes sont contrôlés au niveau des données
  (props, storyboard, scénario) et par comparaison de pixels avec le storyboard validé.
- **Noirs et images figées** : seuils vérifiés sur les 5 vidéos françaises (aucun défaut,
  aucune fausse alerte) ; la détection d'un vrai défaut n'est testée que sur des journaux
  FFmpeg simulés, aucune vraie vidéo défectueuse n'a été produite.
- **Une image par scène** : la comparaison au storyboard porte sur l'instant du storyboard ;
  une anomalie visible seulement à un autre moment de la scène (animation, surimpression)
  n'est pas détectée.
- **Calibration visuelle** : 22 scènes, toutes dans le style sombre `flat-motion-graphics` ;
  les styles clairs (`minimalist-diagram`, `clean-professional`) ne sont pas calibrés.
- **Musique** : la détection de parole (`silencedetect` −45 dB) est calibrée sans musique ;
  avec une musique de fond (phase 2), il faudra une autre méthode (par exemple analyser le
  WAV de narration seul).
- **Configuration de rendu** : le storyboard et le MP4 doivent être rendus avec la même
  configuration (FR v3) ; un MP4 rendu avec une autre version est signalé (cas
  d'animated-reel, surlignage « po|ur »).
- **Non testé** : méthode atelier, rendu HyperFrames, formats 9:16 et 1:1, vidéo avec
  musique, production réelle du studio de bout en bout (le pilote sera le premier cas).
- **Durée** : la suite complète dure environ 13 à 16 minutes (rendus locaux de calibration).
- **Journal d'événements des tests** : le socle (`lib/events.py`) écrit `events.jsonl` dans
  tout projet situé sous `projects/`. Les tests du studio redirigent ce journal vers un
  dossier temporaire isolé (`tests/studio/conftest.py`) ; un test vérifie qu'aucun
  `projects/demos/events.jsonl` n'est recréé.
