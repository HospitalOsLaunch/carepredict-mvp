# Gate 1-B proxy audit

## Question preregistree

Gate 1-B ne demande plus seulement si `aval_institu` est previsible. Il demande si l'embedding apporte un lift au-dela des proxies evidents age + DRG.

Extract reel: **100000** admissions; prevalence aval: **13.40%**.

## Proxy age

| Age bucket | Admissions | aval_institu | Taux aval |
|---|---:|---:|---:|
| 70 or Older | 31499 | 8832 | 28.04% |
| 50-69 | 27213 | 3453 | 12.69% |
| 30-49 | 20139 | 761 | 3.78% |
| 0-17 | 12318 | 140 | 1.14% |
| 18-29 | 8831 | 215 | 2.43% |

Les 70+ ont un taux aval de **28.04%** contre **6.67%** pour les autres ages (ecart +21.37%). L'age cree donc une separation forte qui devra figurer dans les baselines triviales.

## Proxy APR-DRG

APR-DRG quasi-deterministes observes (taux aval > 50%; aucun seuil de support n'est applique dans cette statistique descriptive):

- EXTENSIVE THIRD DEGREE BURNS WITH SKIN GRAFT: 100.0% aval (1/1)
- FRACTURE OF PELVIS OR DISLOCATION OF HIP: 71.7% aval (91/127)
- HIP AND FEMUR FRACTURE REPAIR: 69.0% aval (410/594)
- RADIOTHERAPY: 66.7% aval (4/6)
- FRACTURE OF FEMUR: 63.5% aval (61/96)
- NON-ELECTIVE OR COMPLEX HIP JOINT REPLACEMENT: 62.8% aval (246/392)
- TRACHEOSTOMY WITH MV >96 HOURS WITHOUT EXTENSIVE PROCEDURE: 60.8% aval (79/130)
- TRACHEOSTOMY WITH MV >96 HOURS WITH EXTENSIVE PROCEDURE: 58.4% aval (73/125)
- INTENTIONAL SELF-HARM AND ATTEMPTED SUICIDE: 54.5% aval (133/244)
- DEGENERATIVE NERVOUS SYSTEM DISORDERS EXCEPT MULTIPLE SCLEROSIS: 52.6% aval (299/568)
- MUSCULOSKELETAL AND OTHER PROCEDURES FOR MULTIPLE SIGNIFICANT TRAUMA: 51.7% aval (78/151)

Les 10 APR-DRG au plus fort volume positif expliquent **33.37%** de la classe aval.

Top 20 APR-DRG par volume aval:

| APR-DRG | Admissions | aval_institu | Taux aval |
|---|---:|---:|---:|
| SEPTICEMIA AND DISSEMINATED INFECTIONS | 5410 | 1349 | 24.94% |
| HEART FAILURE | 2705 | 480 | 17.74% |
| CVA AND PRECEREBRAL OCCLUSION WITH INFARCTION | 1305 | 451 | 34.56% |
| HIP AND FEMUR FRACTURE REPAIR | 594 | 410 | 69.02% |
| KIDNEY AND URINARY TRACT INFECTIONS | 1478 | 378 | 25.58% |
| MAJOR RESPIRATORY INFECTIONS AND INFLAMMATIONS | 1363 | 340 | 24.94% |
| DEGENERATIVE NERVOUS SYSTEM DISORDERS EXCEPT MULTIPLE SCLEROSIS | 568 | 299 | 52.64% |
| ACUTE KIDNEY INJURY | 1260 | 286 | 22.70% |
| NON-ELECTIVE OR COMPLEX HIP JOINT REPLACEMENT | 392 | 246 | 62.76% |
| MALFUNCTION, REACTION, COMPLICATION OF GENITOURINARY DEVICE OR PROCEDURE | 820 | 233 | 28.41% |
| INFECTIOUS AND PARASITIC DISEASES INCLUDING HIV WITH O.R. PROCEDURE | 753 | 228 | 30.28% |
| OTHER DISORDERS OF NERVOUS SYSTEM | 927 | 227 | 24.49% |
| OTHER PNEUMONIA | 1403 | 221 | 15.75% |
| OTHER MUSCULOSKELETAL SYSTEM AND CONNECTIVE TISSUE DIAGNOSES | 686 | 201 | 29.30% |
| OTHER BACK AND NECK DISORDERS, FRACTURES AND INJURIES | 657 | 193 | 29.38% |
| ELECTIVE KNEE JOINT REPLACEMENT | 782 | 172 | 21.99% |
| RESPIRATORY FAILURE | 1025 | 161 | 15.71% |
| CELLULITIS AND OTHER SKIN INFECTIONS | 1272 | 155 | 12.19% |
| ALTERATION IN CONSCIOUSNESS | 437 | 154 | 35.24% |
| FRACTURES AND DISLOCATIONS EXCEPT FEMUR, PELVIS AND BACK | 305 | 152 | 49.84% |

## Plancher AUPRC de la regle DRG

La regle binaire sans modele (predire aval lorsque le taux empirique du DRG depasse 50%) atteint une AUPRC de **0.1860**, contre une prevalence de **0.1340**. Cette AUPRC est la barre proxy, pas la seule prevalence.

## Portee

Ce signal n'est **pas une fuite technique**: age et diagnostic sont des champs sources admissibles et distincts de la disposition. Il est toutefois quasi-deterministe pour certains profils. Un GO sur la vue complete serait donc ininterpretable: l'embedding pourrait seulement relire le DRG. Une evaluation hard-case, preregistree avant tout encodage, est necessaire pour mesurer un lift au-dela d'age + famille diagnostique.
