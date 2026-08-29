# HFWM-R0 M3D.1 — Audit des diffs M2 sensibles

## Référence Git observée

Les deux fichiers ont été introduits dans `adc8d8ba59fe464692581141c901ed5813cbb5a3`
(`feat(hfwm): freeze R0 synthetic data foundation and bakeoff`, 28 août 2026). Aucun
commit ultérieur ne porte les diffs actuellement présents ; ils étaient dans le working
tree après la production des artefacts M2.

## `src/hfwm/evaluation/preregistration.py`

Diff exact : ajout des contrôles de budgets `cpu_seconds_max_per_seed`, `runs_per_seed`,
`budget_scope` et de la parité HGBR/CQR ; validation optionnelle du comparateur TSFM ;
ajout de `_validate_bounded_m2a` pour vérifier la cohorte synthétique, le split avant
windowing, la calibration et les seuils M2A ; assouplissement conditionnel de la cohérence
tasks/horizons pour le protocole borné.

Classification : `POST_M2_NO_EFFECT_ON_REPRODUCIBILITY`.

Preuve : ce module ne forme pas de modèle et n'est pas importé par le runner M2B ; ses
changements portent uniquement sur la validation préalable du manifeste. Les résultats
M2 conservés ne sont pas recalculés.

## `src/hfwm/models/local/model.py`

Diff exact : ajout de `fitted_state()` (copie canonique des paramètres) et
`restore_fitted_state()` (validation de formes, finitude, variance positive et identité
de site avant restauration).

Classification : `POST_M2_NO_EFFECT_ON_REPRODUCIBILITY`.

Preuve : les chemins `fit`, `predict_next`, `rollout` et `sample_rollout` utilisés par M2
ne sont pas modifiés ; les deux méthodes ajoutées sont des helpers d'I/O explicite et ne
sont appelées par aucun runner historique. Aucun checkpoint M2 n'a toutefois été persisté.

## Limite de reconstruction

`M2_CODE_STATE_NOT_FULLY_RECOVERABLE` est enregistré : le manifeste M2 pointe vers
`adc8d8b`, mais ne contient pas les hashes des sources exécutées et les weights n'ont pas
été persistés. Les résultats M2 restent historiques et documentaires uniquement.

Narratif autorisé : M2 a déclenché le kill requis par sa règle procédurale pré-enregistrée,
mais le banc ne disposait pas d'une précision décisionnelle suffisante pour établir la
direction ni l'amplitude réelle de l'effet occupation. Le point estimate reste environ
`+17,31 %` et l'application rétrospective de M3 reste `INCONCLUSIVE_GUARDRAIL`.
