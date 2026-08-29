# HFWM-R0 — audit historique du validateur de pré-enregistrement M2

## Périmètre et autorité

Cette passe ne modifie ni les résultats numériques M2, ni A3, B3 ou le tag.
L'autorité examinée est exclusivement le bundle M2A référencé par
`frozen_preregistration_bundle_sha256 =
384c4e5ae707edabcf19523b5fd782f4301ca405722aa71fab31d90e141c37e6`.
Le contrat M3D actuel n'est pas utilisé pour juger l'ancien validateur.

## Axes de classification

```yaml
fit_output_impact: NONE_DEMONSTRATED
preregistration_gate_semantics_impact: MATERIAL
temporal_relation_to_m2_execution: UNRESOLVED
m2_preregistration_contract_conformance: SUPPORTED
m2_execution_time_validator_state: UNRESOLVED
m2_software_gate_enforcement_at_execution: NOT_PROVEN
m2_overall_preregistration_assurance: PARTIAL
m2_code_state_not_fully_recoverable: true
```

`NONE_DEMONSTRATED` signifie que les essais disponibles n'ont montré aucun
changement de fit, prédiction ou rollout ; ce n'est pas une reconstruction des
poids historiques. Le changement de gate est matériel : un bundle M2A accepté
par le validateur A3 est rejeté par le validateur parent.

## Trois erreurs littérales de l'ancien validateur

Exécution sur exactement `/private/tmp/carepredict-m3d1-A3/docs/research/hfwm`
avec le code du parent de `6cd4819` :

```text
error_1: bakeoff and metrics horizons differ
error_2: bakeoff and metrics tasks differ
error_3: generic TSFM must be NOT_EXECUTED before a checkpoint is verified
```

La sortie complète, inchangée, est archivée dans
`artifacts/hfwm-r0/m3d/m2-prereg-old-validator-errors.log` (SHA-256
`ee42d6d330f498a5d4c325d42fd5245894924e7f5acbb8e2e781b9b41d971406`).

### `error_1`

```yaml
error_id: M2A_HORIZON_CROSS_DOCUMENT
literal_old_validator_message: "bakeoff and metrics horizons differ"
manifest_field_or_value:
  bakeoff_field: horizons_hours
  bakeoff_value: [6]
  metrics_value: [6, 24, 72]
frozen_contract_locator:
  - docs/research/hfwm/HFWM_R0_BAKEOFF.yaml:66-68
  - docs/research/hfwm/HFWM_R0_BAKEOFF.yaml:12
  - docs/research/hfwm/HFWM_R0_METRICS.yaml:13-17
frozen_contract_exact_text:
  - '"HFWM_R0_METRICS.yaml": "Historical broad metric catalogue only; its wider target and horizon lists are not authorized for M2A execution."'
  - '"horizons_hours": ['
  - '  6'
  - ']'
old_validator_rule: >-
  _validate_cross_document compare directement bakeoff.horizons_hours et
  metrics.horizons_hours.
new_validator_rule: >-
  Lorsque protocol_id == hfwm-r0-m2a-bounded-v1, la comparaison tasks/horizons
  est conditionnellement omise ; _validate_bounded_m2a impose [6].
semantic_change: >-
  Le catalogue historique large n'est plus traité comme la liste d'exécution
  de M2A ; le manifeste borné fait foi pour l'horizon.
verdict: VALIDATOR_BUG
justification: >-
  Le bundle M2A déclare explicitement le catalogue METRICS historique et sa
  propre autorité numérique. L'ancien contrôle applique une égalité qui est
  incompatible avec ce contrat M2A précis.
```

### `error_2`

```yaml
error_id: M2A_TASK_CROSS_DOCUMENT
literal_old_validator_message: "bakeoff and metrics tasks differ"
manifest_field_or_value:
  bakeoff_field: tasks
  bakeoff_value: [occupancy, inflow]
  metrics_value: [occupancy, inflow, discharges, staffing, pressure]
frozen_contract_locator:
  - docs/research/hfwm/HFWM_R0_BAKEOFF.yaml:62-65
  - docs/research/hfwm/HFWM_R0_BAKEOFF.yaml:12
  - docs/research/hfwm/HFWM_R0_METRICS.yaml:6-12
frozen_contract_exact_text:
  - '"HFWM_R0_METRICS.yaml": "Historical broad metric catalogue only; its wider target and horizon lists are not authorized for M2A execution."'
  - '"tasks": ['
  - '  "occupancy",'
  - '  "inflow"'
  - ']'
old_validator_rule: >-
  _validate_cross_document compare directement bakeoff.tasks et metrics.tasks.
new_validator_rule: >-
  Pour le protocole borné, _validate_bounded_m2a exige exactement occupancy et
  inflow et le contrôle cross-document est conditionnellement omis.
semantic_change: >-
  La sélection M2A de deux targets est reconnue comme un sous-contrat borné,
  au lieu d'être comparée au catalogue non exécutif.
verdict: VALIDATOR_BUG
justification: >-
  Le bundle historique identifie M2A comme l'autorité numérique et interdit les
  targets plus larges du catalogue. L'erreur provient de l'ancien validateur,
  pas d'une violation du bundle M2A.
```

### `error_3`

```yaml
error_id: M2A_GENERIC_TSFM_LOCATION
literal_old_validator_message: "generic TSFM must be NOT_EXECUTED before a checkpoint is verified"
manifest_field_or_value:
  final_gate_comparators: [hgbr_cqr]
  excluded_comparators.generic_tsfm.decision: EXCLUDED_NOT_EXECUTABLE_WITHOUT_SEPARATE_WORK
  excluded_comparators.generic_tsfm.checkpoint_verified: false
frozen_contract_locator:
  - docs/research/hfwm/HFWM_R0_BAKEOFF.yaml:232-238
  - docs/research/hfwm/HFWM_R0_BAKEOFF.yaml:10-14
frozen_contract_exact_text:
  - '"excluded_comparators": ['
  - '  {"id": "generic_tsfm",'
  - '   "decision": "EXCLUDED_NOT_EXECUTABLE_WITHOUT_SEPARATE_WORK",'
  - '   "checkpoint_verified": false,'
  - '   "reason": "No local checkpoint has verified identity, licence, provenance and offline compatibility."}'
  - '"numeric_authority": "THIS_MANIFEST_IS_THE_ONLY_EXECUTION_AUTHORITY_FOR_M2A"'
old_validator_rule: >-
  _validate_bakeoff exigeait un item generic_tsfm dans final_gate_comparators,
  avec status NOT_EXECUTED et checkpoint_verified false.
new_validator_rule: >-
  Le contrôle TSFM est conditionnel à sa présence dans final_gate_comparators ;
  l'entrée exclue de M2A est vérifiée dans excluded_comparators.
semantic_change: >-
  Un comparateur explicitement exclu et non exécutable n'est plus traité comme
  un comparateur final obligatoire.
verdict: VALIDATOR_BUG
justification: >-
  Le bundle M2A documente l'exclusion du TSFM et l'absence de checkpoint. Le
  validateur parent cherchait l'objet au mauvais emplacement contractuel.
```

## Inventaire de chaque modification

| Modification dans `preregistration.py` | Catégorie | Effet de gate |
|---|---|---|
| `cpu_seconds_max_per_seed` (arm/comparateur) | nouvelle validation | budget borné et parité vérifiables |
| `runs_per_seed == 1` | nouvelle validation | interdit les réplications implicites |
| `budget_scope` | nouvelle validation | impose le périmètre total du bras |
| budgets HGBR/CQR et `capacity_accounting` | validation renforcée | comparateur final explicitement borné |
| TSFM seulement s'il est présent | validation assouplie | l'exclusion M2A devient représentable |
| `_validate_bounded_m2a` | nouvelle validation | vérifie le sous-contrat borné M2A |
| bypass conditionnel tasks/horizons | validation assouplie | changement matériel ; accepte le sous-contrat M2A |
| schéma de données | aucune modification | aucun changement de schéma |
| autorisation | changement indirect | `require_valid_preregistration` peut autoriser le bundle borné |

L'« assouplissement conditionnel de la cohérence tasks/horizons » est donc un
changement de sémantique d'autorisation, pas un simple changement de schéma.

## Provenance temporelle

- `adc8d8ba59fe...` est le parent Git où le fichier existait déjà (blob
  `e0552567...` pour `preregistration.py`).
- `6cd4819ef342...` est le premier commit qui enregistre les modifications
  jusque-là présentes dans le working tree (blob `780b76d3...`).
- Le timestamp Git de `6cd4819` est `2026-08-29T15:10:49+02:00` ; il date
  l'enregistrement, pas nécessairement l'édition.
- Les mtimes A3 (`2026-08-29T15:26:14+02:00`) correspondent à la matérialisation
  du checkout et sont `WEAK` pour dater l'édition.
- Les mtimes des logs temporaires sont `WEAK` : ils datent les comparaisons
  rejouées, pas M2.
- Aucun snapshot Time Machine local n'a été listé ; l'énumération APFS a échoué
  au niveau du framework système : `NON_PROBATIVE`.
- Aucune sauvegarde IDE/recovery pertinente ni entrée d'historique shell utile
  n'a été trouvée : absence non probante (`NON_PROBATIVE`).
- Les journaux Codex contiennent des métadonnées de sessions/inter-agents, mais
  aucun transcript d'exécution liant M2 à un hash de `preregistration.py` :
  `WEAK`, non probant pour la chronologie.

Conclusion figée :

```text
PREREGISTRATION_VALIDATOR_CHANGE_TIME_RELATIVE_TO_M2_EXECUTION = UNRESOLVED
```

Le manifeste M2 enregistre `git_head=adc8d8ba...`, le bundle SHA et
`weights_persisted=false`, mais aucun hash de `preregistration.py`, transcript
de commande ou capture d'environnement. Aucune preuve ne lie l'exécution M2 à
un SHA précis du validateur. `M2_CODE_STATE_NOT_FULLY_RECOVERABLE` est donc
étendu explicitement au validateur de pré-enregistrement.

## Archives de preuves post-tag

Les cinq logs ont été copiés octet pour octet dans `artifacts/hfwm-r0/m3d/`.
`post_tag_evidence: true` est attaché à chacun ; aucune sortie n'a été rejouée
pour remplacer un original.

| Fichier | Source | Taille | SHA-256 | Commande connue | Archivage |
|---|---|---:|---|---|---|
| `m2-prereg-parent.log` | `/private/tmp/m2_prereg_parent.log` | 152 | `bf5556fb12ea384e81eacc2406bf3aef6c729e72eed5e7ebb2ce898a1b3e9345` | comparaison inline des validateurs parent/A3 | 2026-08-29 16:01:52+0200 |
| `m2-prereg-a3.log` | `/private/tmp/m2_prereg_a3.log` | 151 | `f1377806d26a6dc5d81e4dedf5aecfc96c3b0dd9f175b1fa2e89f311514b46a5` | comparaison inline des validateurs parent/A3 | 2026-08-29 16:01:52+0200 |
| `m2-local-parent.log` | `/private/tmp/m2_local_parent.log` | 376 | `a6d45cd475348db3739ce1bdda8331fa6715be8fd1cec2a01cb055d214d1a895` | comparaison inline parent/A3 du modèle local | 2026-08-29 16:01:52+0200 |
| `m2-local-a3.log` | `/private/tmp/m2_local_a3.log` | 375 | `5ff459b371d750f603a007e3e7a302a2f5b51318fc736dc6ea77c252be7c31be` | comparaison inline parent/A3 du modèle local | 2026-08-29 16:01:52+0200 |
| `a3-local-roundtrip.log` | `/private/tmp/a3_local_roundtrip.log` | 416 | `edbedf7f75a79a446989fa0db47ed112158c3c3c10ef1a3c0da37740926ee4a5` | round-trip inline `fitted_state`/`restore_fitted_state` | 2026-08-29 16:01:52+0200 |

## Finding de gouvernance Git

```yaml
gate_semantics_change_committed_under_chore_label: true
future_policy:
  validator_or_gate_semantics_change_requires_explicit_fix_or_protocol_commit: true
```

Le commit `6cd4819` est intitulé `chore(hfwm): freeze M3D.1 release content`
alors qu'il contient une modification matérielle de sémantique de validation.
L'historique n'est pas réécrit ; ce finding est seulement enregistré.

## Narratif fail-closed

M2 dispose d'un bundle de pré-enregistrement historique gelé, mais l'état exact
du validateur et la conformité du bundle au gate logiciel au moment de
l'exécution ne sont pas encore établis avec une provenance suffisante. Les
résultats numériques M2 restent historiques et inchangés.

## Conclusion

`M2_PREREGISTRATION_CONFORMANCE_SUPPORTED`
