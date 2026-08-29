# HFWM-R0 M1 — targeted hostile review

Reviewer : `HFWM M1 Hostile Reviewer`
Mode : lecture seule sur le candidat gelé ; seul ce rapport a été écrit.
Périmètre : les neuf risques définis par `HFWM-R0-M1R`.

## Intégrité du gel

Les SHA-256 des quatre fichiers de code, de la configuration, du dataset, des
deux manifests de données, du checkpoint, des métriques et du manifest
d'entraînement correspondent tous à `CURRENT_MILESTONE.yaml`. Les hashes
logiques ont également été recalculés : dataset
`64e831ec1a3fbf6fdad2bd0ac716b675619216d3b4c180895ac6acdba2bbb965`,
checkpoint `372198d6a3470f97786471655e6d73233312705869bea1b0340fac28359f4b33`,
métriques `3b9c0e6414a22cc18794246934fff20de684f165b755383719881c85b125c18f`
et manifest `6945dbd2fcd341562337ed2e5d07ef7bb482ebed5901d1202da5edf26aa39520`.

## Recalculs exécutés

- Reconstruction en mémoire de `build_temporal_corpus()` puis
  `build_point_in_time_data_slice()` : dataset identique au fichier gelé, 240
  lignes et 60 épisodes. Zéro événement feature avec `event_time` ou
  `available_at` postérieur à `as_of`; zéro target hors horizon; zéro correction
  future dans les targets. Les 240 snapshots contiennent chacun la correction
  historique déjà disponible attendue.
- Audit indépendant des partitions : zéro épisode traversant un split, zéro
  affectation de ligne incohérente, zéro épisode chevauchant, zéro identifiant
  dupliqué et gap inter-split minimum observé de 240 heures.
- Deux appels en mémoire à `train_minimal_candidate`, sans export : même hash de
  modèle, checkpoint identique et métriques identiques hors durée CPU. Le run
  reconstruit est identique aux checkpoint et métriques persistés.
- Recalcul Numpy indépendant depuis le checkpoint et les lignes test : MAE/RMSE,
  couverture, écart-type moyen, non-finis et MAE par pas sont exactement égaux
  au JSON gelé. Taux non fini : `0.0`.
- Test de non-réinjection : après mutation extrême de toutes les observations
  futures d'un épisode test, le rollout reste octet-identique
  (`61679ebd...f458f`). La boucle utilise bien `current = predicted` pendant
  quatre pas et ne reçoit aucune observation après `t0`.
- Contrôle de dynamique jointe : les coefficients croisés sont non nuls
  (`inflow→occupancy=0.095572`, `occupancy→inflow=-0.471511`). Le candidat n'est
  donc pas deux heads indépendantes simplement renommées. Aucun claim de modèle
  démontré, Foundation, causal, Nantes ou exécution autonome n'a été trouvé dans
  les preuves du candidat.

## BLOCKERS

Aucun blocker reproductible dans le périmètre M1R.

## NON_BLOCKING_FINDINGS

### M1R-F01 — processus d'enregistrement non appris

Les coefficients associés à la fiabilité et au processus d'enregistrement sont
nuls à la précision numérique (`≈1e-14` ou `0`). La représentation les contient,
mais `fit()` reçoit seulement `train_values`; la preuve M1B ne doit donc pas
suggérer que leur influence est démontrée. Cela n'invalide pas M1, qui exige ici
un état causal issu des observations, mais cette propriété devra être testée
avant tout claim de robustesse aux retards ou à la missingness.

### M1R-F02 — incertitude de rollout heuristique

Sous l'interprétation `residual_gaussian`, la propagation implémentée
`variance * step + (1 - reliability)` n'est pas la covariance récursive de la
dynamique linéaire jointe. Au pas 4, les variances implémentées sont
`[17.0516, 28.8057]`, contre `[4.9954, 8.1218]` pour la récursion linéaire
gaussienne correspondante. Les couvertures persistées sont arithmétiquement
correctes pour les intervalles effectivement produits, mais ceux-ci doivent être
qualifiés d'incertitude heuristique ou corrigés/calibrés avant comparaison. M1
reste satisfait car une incertitude résiduelle mesurée est bien exposée et aucun
claim de calibration n'est formulé.

### M1R-F03 — contraintes incomplètement exercées

Le rollout applique la non-négativité, mais l'évaluation passe un contexte vide :
la capacité disponible dans la source et la conservation incluant les sorties ne
sont pas évaluées. Aucun dépassement évident n'est observé sur le test
(`occupancy` prédite entre `22.1773` et `22.7755`, capacité synthétique 24), mais
une métrique de cohérence contrainte sera nécessaire au-delà de M1.

### M1R-F04 — portée des poids à clarifier

Le registre autorise explicitement l'entraînement local et la rétention locale,
mais porte aussi `weights_allowed: false`. Le checkpoint demeure local et non
publié, conformément à la mission courante ; il ne doit pas être distribué ou
présenté comme réutilisable avant clarification explicite de ce champ.

NO_BLOCKER_FOUND
