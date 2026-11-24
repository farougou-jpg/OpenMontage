# Narration française du studio (lot 1.2)

Outil : `lib/studio/narration` → `PiperFrNarration` (`studio_piper_fr_narration`).
Voix imposée : Piper `fr_FR-siwis-medium`, `length_scale` 1.0 (méthode V2). Local, 0 $.
Hors registre automatique : `tts_selector` ne le choisit jamais ; le studio l'appelle
explicitement, via le garde-fou budgétaire (`lib/studio/budget_guard.py`).

## Entrée

Un scénario conforme à `schemas/artifacts/script.schema.json` :
- `sections[].text` : texte écrit, validé par l'utilisateur ;
- `start_seconds` / `end_seconds` : la scène ;
- `delivery_cues.pause_before_seconds` / `pause_after_seconds` : pauses ;
- `delivery_cues.pace: fast` est refusé (on raccourcit le texte, on n'accélère jamais).

Options par section (`section_options`) : `fade_out_frames` (8 par défaut, 15 pour un
graphique) et `anchor: [mot, min, max]` (ancrage d'un mot-clé, comme en V2).

Fenêtre de parole = `[début + pause avant, fin − pause après − fondu − 0,5 s]`.

Pause explicite dans le texte : `[pause 0.4]` (0 < durée ≤ 3 s). Tout autre `[...]`
est refusé, sauf les phonèmes bruts `[[ ... ]]` du LEXICON.

## Modes

- `mesure` : durée réelle de chaque phrase, débit, durée de scène suggérée
  → `projects/<projet>/assets/narration/mesures/vNNN/mesure.json`. Aucun audio.
- `placement` : narration complète →
  `projects/<projet>/assets/narration/vNNN/` (`segments/`, `narration_fr.wav`,
  `narration_fr_brut.wav`, `timing_fr.json`, `controle/rapport_narration.md|json`)
  et, si conforme, copie dans `remotion-composer/public/audio/studio/<projet>/vNNN/`.

Jamais d'écrasement : chaque exécution crée une nouvelle version. Écriture refusée dans
`projects/demos/`, `public/audio/fr-series/`, `public/audio/fr-pilot/`.

## Normalisation

`fr_text_v2.py` est la copie exacte de la V2 validée. `fr_text.py` ajoute : milliers
groupés, euros, heures/min/s, `24h/24`, `7j/7`, ordinaux, `+`/`−` devant un pourcentage,
`×2`, guillemets, tirets longs, espaces insécables, accord au féminin (« 1 heure » →
« une heure ») **uniquement** si le nom suivant est dans la liste des noms féminins.
Un cas incertain (« 1 seule tâche ») n'est pas modifié : il est signalé dans le rapport.

## Contrôles

Bloquants : -16 LUFS ± 0,5 ; true peak ≤ -1,5 dBFS (seconde passe suréchantillonnée
automatique, version brute conservée) ; fin ≤ fin max ; pas de chevauchement ; parole
finie avant la fin de la vidéo. Si un bloquant échoue, pas de `narration_fr.wav`.

Avertissements : débit > 6,5 syll/s, phonèmes non français, chiffre non converti,
accord incertain, silence > 1 s dans une phrase, échantillons à pleine échelle.

## Piper n'est pas déterministe

Deux synthèses du même texte diffèrent légèrement (jusqu'à ~180 ms mesurés). L'équivalence
avec la V2 est donc prouvée ainsi (`tests/studio/test_narration_v2_equivalence.py`) :
même audio brut → fichiers identiques octet par octet ; même texte lu et mêmes
phonèmes ; durées à ± 10 % des durées validées.

## Profil sonore B (référence validée du pilote, 2026-11-18)

Option `"profil": "B"` de `PiperFrNarration` ; le profil `"V2"` reste le défaut, inchangé.

- Synthèse : même voix, `length_scale` **1,10** (débit environ 7 à 10 % plus lent), autorisé
  uniquement avec ce profil (`synth.PROFILE_LENGTH_SCALES`). Toute autre valeur reste refusée.
- Mastering (`mastering.master_profile_b`) : même égalisation des phrases que la V2, puis la
  chaîne de la version B validée (`PROFILE_B_FILTERS`) : 48 kHz, passe-haut 80 Hz, +2 dB à
  200 Hz, -1,5 dB à 450 Hz, +2 dB à 3,2 kHz, dé-esseur, compression 2:1, `aexciter` ; puis
  -16 LUFS et limiteur suréchantillonné à 192 kHz (plafond interne -1,7 dBFS).
- Sorties : `narration_fr.wav` en **48 kHz / 24 bits / mono** ; `narration_fr_brut.wav` = piste
  égalisée sans chaîne B (22 050 Hz, 16 bits) ; segments en 22 050 Hz.
- Contrôles identiques (-16 LUFS ± 0,5, true peak <= -1,5 dBFS, fenêtres…). L'écrêtage est
  vérifié sur une copie 16 bits temporaire du fichier final 24 bits.
- Référence : `projects/pilote-gestion-temps/assets/narration/essais/essai-01/` (version B)
  et `projects/pilote-gestion-temps/validations.json` (validation 3).
