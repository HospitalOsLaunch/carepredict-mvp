# HFWM-R0 M3D — Revue hostile unique et résolution ciblée

## Cadre

Une seule revue hostile globale, read-only, a été exécutée après le premier gel. Le
reviewer n'a modifié aucun fichier. Verdict initial : `BLOCKERS_FOUND`. Conformément au
protocole, chaque blocker reproductible a reçu une correction minimale et les tests
ciblés ont été rejoués **une seule fois**. Aucune deuxième revue globale n'a été lancée.

## Blockers et résolution

### M3D-R01_GUARDRAIL_TYPE_I_NOT_CONTROLLED

- Preuve initiale : le quantile normal était anti-conservateur avec peu de sites/blocs ;
  `FAIL_GUARDRAIL` à la vraie frontière +5 % atteignait 10,92 %.
- Correction : valeurs critiques unilatérales calibrées par simulation indépendante sous
  la frontière +5 %, pour chaque design et sémantique Count/Rate. Le plan affiche aussi le
  rejet de l'ancienne règle M2 à vraie régression 0 et +5 %.
- Résultat : sur 1 200 répétitions d'évaluation après 2 000 calibrations, le risque à la
  frontière va de 3,00 % à 5,42 % pour Count et de 4,75 % à 5,33 % pour Rate.
- Test : `test_small_cluster_calibration_controls_error_at_guardrail_boundary` — PASS.
- Statut : `RESOLVED_BY_TARGETED_EVIDENCE`.

### M3D-R02_ELIGIBILITY_MASK_NOT_REPLAYABLE

- Preuve initiale : le seuillage était déterministe, mais les scores 0–100 étaient fournis
  sans transformation preuve→score ; la clé omettait `hospital_group_id`.
- Correction : rubrique par dimension avec checks pondérés, tolérances explicites
  boolean/minimum/maximum et politique `missing evidence = failed check`. Les scores sont
  reconstruits depuis les preuves brutes. La clé globale est désormais
  `(hospital_group_id, hospital_site_id, unit_id, temporal_block_id)`.
- Tests : reconstruction complète, preuve manquante, hard fail, rejouabilité partielle et
  collision inter-groupes — PASS.
- Statut : `RESOLVED_BY_TARGETED_EVIDENCE`.

### M3D-R03_TRANSFER_FALLBACK_CONTRADICTS_CONTRACT

- Preuve initiale : sans `transfer_event_id`, toutes les jambes étaient groupées sous une
  même valeur et `source_record_id` était ignoré.
- Correction : fallback un-à-un exact sur
  `(source_record_id, source_unit_id, destination_unit_id, event_time)`. Toute donnée
  manquante ou incohérente devient un hard fail de couplage.
- Tests : deux paires fallback valides simultanées et deux source records incompatibles —
  PASS.
- Statut : `RESOLVED_BY_TARGETED_EVIDENCE`.

## Relance ciblée unique

```text
pytest tests/hfwm/m3d -q: 19 passed
ruff ciblé: PASS
mypy strict ciblé: PASS
```

Les 22 hashes du premier gel avaient été confirmés par le reviewer, la simulation était
reproductible, le RNG atteignable, et aucun entraînement ou accès partenaire n'avait été
détecté. Le reviewer a également confirmé Count/Rate, la séparation HCL/Nantes/Dijon et
les interdictions M3-L/M3-F.

Finding non bloquant conservé : les rôles réglementaires sont correctement présentés
comme provisoires ; l'ordre exact COMOR/CSE/CIDS doit être confirmé par les HCL et n'est
pas affirmé comme séquence acquise.

## Conclusion

```yaml
global_review_count: 1
second_global_review_executed: false
targeted_correction_cycles: 1
open_reproducible_blockers: 0
review_status: BLOCKERS_RESOLVED_BY_SINGLE_TARGETED_TEST_RUN
```
