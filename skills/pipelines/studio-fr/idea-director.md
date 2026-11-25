# Idea Director — OpenMontage Studio (studio-fr)

## Quand l'utiliser

Première étape du pipeline `studio-fr` : transformer le formulaire du studio (ou une
simple phrase) en `brief` (`schemas/artifacts/brief.schema.json`).

## Procédure

1. **Lire le formulaire** : idée, type de vidéo, durée, format, langue.
2. **Vérifier** avec le module déterministe :

   ```python
   from lib.studio.capabilities import StudioRequest, check_request
   chk = check_request(StudioRequest(idea=..., video_type=..., duration_s=..., format=...))
   ```

   - `chk.ask_for == ["idee"]` (formulaire vide) → demander l'idée, rien d'autre.
   - `chk.errors` → expliquer en une phrase et proposer `chk.alternatives`
     (ex. 9:16 demandé → « disponible au lot 1.4 ; 16:9 possible dès maintenant »).
   - `chk.defaults_applied` → annoncer les valeurs choisies (« durée 30 s, format 16:9 »).
3. **Ne poser une question que si l'essentiel manque.** L'utilisateur veut décrire son
   idée et laisser Claude concevoir : déduire public, ton et objectif de l'idée et du
   type ; les signaler comme « déduits » dans le brief.
4. **Recherche web : désactivée par défaut.** Ne faire aucune recherche web sauf demande
   explicite de l'utilisateur (« fais une recherche », « vérifie les chiffres en ligne »).
   Sans recherche, ne jamais inventer de statistique présentée comme réelle : utiliser
   des formulations qualitatives ou des chiffres explicitement illustratifs.
5. **Produire le `brief`** en français : idée reformulée, objectif, public, ton, type,
   durée, format 16:9, contraintes (0 €, phase 1, local), éléments imposés par
   l'utilisateur (citations exactes de ses mots).
6. **Créer le projet Studio**, dans cet ordre et avant tout checkpoint (voir
   `executive-producer`, « Initialisation du projet Studio ») :

   ```python
   from lib.studio import project as prj
   project_dir = prj.create_project(slug, titre, idee, duree_s)
   prj.register_with_backlot(project_dir)
   ```

   puis `python -m backlot open <slug>` (non bloquant), puis le checkpoint `idea`.
   Identifiant : minuscules, chiffres et tirets, 3 à 61 caractères, dérivé du titre.
   Si le projet existe déjà, ne rien écraser : demander à l'utilisateur s'il faut le
   reprendre ou en créer un autre.

## Ce que tu présentes

Deux à quatre lignes : ce que tu as compris, les valeurs par défaut appliquées, et la
suite (« je prépare 2 ou 3 concepts »). Pas de validation demandée à cette étape.
