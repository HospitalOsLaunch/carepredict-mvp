# HFWM-R0 M3D.1 — preuve exécutable des diffs M2 sensibles

Cette attestation est post-tag et ne modifie pas A3, B3 ni le tag.

## `preregistration.py`

- Commit d'introduction observé : `6cd4819ef342a2382213b5f51b0f4dde634fe7fa`.
- Auteur/message/date : `belaguy007`, `chore(hfwm): freeze M3D.1 release content`,
  `2026-08-29T15:10:49+02:00`.
- Diff exact : `git diff --unified=3 6cd4819^ 6cd4819 --
  src/hfwm/evaluation/preregistration.py` (94 lignes ajoutées, 10 supprimées).
- Nature observée : budgets CPU, `runs_per_seed`, périmètre de budget, validation
  M2A bornée, cohérence TSFM et cross-document. Aucun import de modèle et aucune
  écriture de poids/predictions/rollout.
- Comparaison exécutable : l'ancien validateur retourne `valid=false` avec 3 erreurs
  sur le contrat M2A ; le validateur A3 retourne `valid=true`, avec le même
  `manifest_sha256=384c4e5ae707edabcf19523b5fd782f4301ca405722aa71fab31d90e141c37e6`.
- Classification : `POST_M2_NO_EFFECT_ON_REPRODUCIBILITY` pour les fits approuvés ;
  la modification change uniquement l'autorisation/pré-enregistrement et peut
  changer l'acceptation d'un manifeste invalide.

## `local/model.py`

- Même commit d'introduction et même auteur/message/date.
- Diff exact : `git diff --unified=3 6cd4819^ 6cd4819 --
  src/hfwm/models/local/model.py` (52 lignes ajoutées, aucune suppression).
- Nature observée : ajout de `fitted_state()` et `restore_fitted_state()` uniquement.
  Les corps de `fit`, `predict_next`, `rollout` et `sample_futures` sont inchangés.
- Comparaison parent/A3 sur les mêmes données synthétiques, configuration et état :
  `backbone_hash=846c5b192abf1e9d426ca72a68a01f0064c1395112b7ce99c42c78ea3bf5322c`,
  `predict_hash=8760b67673de9948717eb28df936b04a3f7be1969b639f25a28c7fda7078c010`,
  `rollout_hash=f054657dc1cf65d07baab151d5ab7131b1b16a6f0489e809f5189aafe614751f`,
  `uncertainty_hash=a17f8f07b5106de29d08437699d531cb5d08adeba66a5bbe00fa84cb44bed6a6`.
- Test A3 de round-trip `fitted_state()`/`restore_fitted_state()` : `PASS` ; les
  tableaux `predict_next`, `rollout` et incertitude sont identiques.
- Classification : `POST_M2_NO_EFFECT_ON_REPRODUCIBILITY` pour les chemins
  historiques ; aucun poids M2 historique n'est reconstitué.

## Limite obligatoire

`M2_CODE_STATE_NOT_FULLY_RECOVERABLE` reste inchangé : les poids exécutés par M2 ne
  sont pas persistés. Les résultats M2 sont historiques. Le narratif autorisé est
  celui du manifeste B3 ; aucun claim robuste d'échec ou de succès d'un world model
  n'est ajouté.

Commandes et sorties détaillées sont conservées dans `/private/tmp` :
`/private/tmp/m2_prereg_parent.log`, `/private/tmp/m2_prereg_a3.log`,
`/private/tmp/m2_local_parent.log`, `/private/tmp/m2_local_a3.log` et
`/private/tmp/a3_local_roundtrip.log`.
