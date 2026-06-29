# Gate 1-B hard-case population audit

## Threshold sweep

| min/class | N after | Positives | Negatives | Positive loss | Prevalence | Strata |
|---:|---:|---:|---:|---:|---:|---:|
| 5 | 69571 | 12535 | 57036 | 6.46% | 18.02% | 332 |
| 10 | 62346 | 11737 | 50609 | 12.42% | 18.83% | 209 |
| 20 | 44987 | 10590 | 34397 | 20.98% | 23.54% | 127 |

Selected `min_per_class=5`.

## Stratified primary lift view

- N: 100000 -> 69571
- Classes before: {'aval_institu': 13401, 'non_aval': 86599}
- Classes after: {'aval_institu': 12535, 'non_aval': 57036}
- Loss total: 30.43%
- Loss positive: 6.46%
- Loss negative: 34.14%
- Positive prevalence: 13.40% -> 18.02%
- Strata: 1676 -> 332

## Matched confound-control view

- N: 100000 -> 40567
- Classes before: {'aval_institu': 13401, 'non_aval': 86599}
- Classes after: {'aval_institu': 12535, 'non_aval': 28032}
- Loss total: 59.43%
- Loss positive: 6.46%
- Loss negative: 67.63%
- Positive prevalence: 13.40% -> 30.90%
- Strata: 1676 -> 332

## Top retained strata by positive volume

| Age | Diagnosis family | Total | Positive | Negative |
|---|---|---:|---:|---:|
| 70 OR OLDER | SEPTICEMIA | 3122 | 1085 | 2037 |
| 70 OR OLDER | FRACTURE OF THE NECK OF THE FEMUR (HIP), INITIAL ENCOUNTER | 634 | 496 | 138 |
| 50-69 | SEPTICEMIA | 2078 | 482 | 1596 |
| 70 OR OLDER | HEART FAILURE | 1735 | 406 | 1329 |
| 70 OR OLDER | CEREBRAL INFARCTION | 826 | 360 | 466 |
| 70 OR OLDER | URINARY TRACT INFECTIONS | 938 | 336 | 602 |
| 70 OR OLDER | ACUTE AND UNSPECIFIED RENAL FAILURE | 777 | 228 | 549 |
| 70 OR OLDER | PNEUMONIA (EXCEPT THAT CAUSED BY TUBERCULOSIS) | 796 | 206 | 590 |
| 70 OR OLDER | OSTEOARTHRITIS | 681 | 192 | 489 |
| 70 OR OLDER | FRACTURE OF THE LOWER LIMB (EXCEPT HIP), INITIAL ENCOUNTER | 249 | 191 | 58 |
| 70 OR OLDER | NEUROCOGNITIVE DISORDERS | 313 | 186 | 127 |
| 50-69 | CEREBRAL INFARCTION | 562 | 171 | 391 |
| 70 OR OLDER | COMPLICATION OF GENITOURINARY DEVICE, IMPLANT OR GRAFT, INITIAL ENCOUNTER | 409 | 161 | 248 |
| 70 OR OLDER | TRAUMATIC BRAIN INJURY (TBI); CONCUSSION, INITIAL ENCOUNTER | 326 | 160 | 166 |
| 70 OR OLDER | CORONAVIRUS DISEASE 2019 (COVID-19) | 535 | 153 | 382 |
| 70 OR OLDER | DIABETES MELLITUS WITH COMPLICATION | 596 | 148 | 448 |
| 70 OR OLDER | FRACTURE OF TORSO, INITIAL ENCOUNTER | 264 | 147 | 117 |
| 70 OR OLDER | FLUID AND ELECTROLYTE DISORDERS | 539 | 144 | 395 |
| 70 OR OLDER | OTHER NERVOUS SYSTEM DISORDERS (NEITHER HEREDITARY NOR DEGENERATIVE) | 331 | 139 | 192 |
| 70 OR OLDER | RESPIRATORY FAILURE; INSUFFICIENCY; ARREST | 503 | 133 | 370 |

## Top dropped positive strata

| Age | Diagnosis family | Total | Positive | Negative |
|---|---|---:|---:|---:|
| 70 OR OLDER | GASTROINTESTINAL CANCERS - SMALL INTESTINE | 10 | 7 | 3 |
| 70 OR OLDER | SPINAL CORD INJURY (SCI), INITIAL ENCOUNTER | 9 | 6 | 3 |
| 70 OR OLDER | HIV INFECTION | 8 | 6 | 2 |
| 70 OR OLDER | SCOLIOSIS AND OTHER POSTURAL DORSOPATHIC DEFORMITIES | 8 | 6 | 2 |
| 70 OR OLDER | VARICOSE VEINS OF LOWER EXTREMITY | 9 | 5 | 4 |
| 18-29 | EPILEPSY; CONVULSIONS | 165 | 4 | 161 |
| 50-69 | NONRHEUMATIC AND UNSPECIFIED VALVE DISORDERS | 138 | 4 | 134 |
| 30-49 | INTESTINAL OBSTRUCTION AND ILEUS | 111 | 4 | 107 |
| 0-17 | SEPTICEMIA | 101 | 4 | 97 |
| 50-69 | TRANSIENT CEREBRAL ISCHEMIA | 101 | 4 | 97 |
| 50-69 | COMPLICATION OF TRANSPLANTED ORGANS OR TISSUE, INITIAL ENCOUNTER | 93 | 4 | 89 |
| 30-49 | NONSPECIFIC CHEST PAIN | 64 | 4 | 60 |
| 30-49 | OTHER SPECIFIED AND UNSPECIFIED NUTRITIONAL AND METABOLIC DISORDERS | 59 | 4 | 55 |
| 30-49 | OSTEOARTHRITIS | 55 | 4 | 51 |
| 50-69 | OTHER SPECIFIED AND UNSPECIFIED LOWER RESPIRATORY DISEASE | 52 | 4 | 48 |
| 50-69 | ABNORMAL FINDINGS WITHOUT DIAGNOSIS | 49 | 4 | 45 |
| 30-49 | MUSCLE DISORDERS | 48 | 4 | 44 |
| 50-69 | POSTPROCEDURAL OR POSTOPERATIVE RESPIRATORY SYSTEM COMPLICATION | 45 | 4 | 41 |
| 50-69 | CIRCULATORY SIGNS AND SYMPTOMS | 44 | 4 | 40 |
| 50-69 | NEOPLASMS OF UNSPECIFIED NATURE OR UNCERTAIN BEHAVIOR | 44 | 4 | 40 |

## Age distribution after stratification

- 70 OR OLDER: 30021
- 50-69: 22627
- 0-17: 8235
- 30-49: 7019
- 18-29: 1669

## Psych / self-harm check

Detected admissions: 2104; aval rate: 12.50%; share of retained positives: 2.10%.

## Interpretation guardrail

- `loss_rate_positive <= 0.50`: view usable for Step 3.
- If every threshold has `loss_rate_positive > 0.50`, do not encode before human review of a coarser diagnosis family.
- If the retained population is mostly 70+, interpret the result as institutional downstream care among older patients with comparable diagnoses, not general downstream disposition.

## AUPRC comparability

The stratified view retains all rows in eligible strata and is the primary lift reading without within-stratum downsampling. Eligibility filtering changed prevalence by +4.62%; Step 3 must therefore report a floor recomputed on this view alongside the preregistered natural-population floor. The matched view changes prevalence by design: Step 3 must recompute every trivial baseline and the DRG floor on that matched population. Its verdict is a same-prevalence delta, never an absolute AUPRC comparison with the natural-population floor.
