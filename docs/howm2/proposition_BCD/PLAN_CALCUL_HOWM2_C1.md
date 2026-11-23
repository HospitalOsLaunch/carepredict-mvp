# Plan de calcul HOWM2-C1 (proposé)

## Conditions générales

- CPU seulement, 0 €.
- Registre neuf `BUDGET_LEDGER_HOWM2_C1`, chaîné et ancré comme en A.
- Plafond par commande : 7 000 s (exécution en arrière-plan) ; checkpoints toutes les 400 s au plus.
- Environnement approuvé : Python 3.11.18 et venv_howm (gel e93a3617…1218), inchangés.
- Aucun GPU. 100 000 établissements sont exclus.

## Repères mesurés

| Repère | Source | Valeur |
|---|---|---|
| Génération | HOWM-1 R0.GEN | 48 établissements TRAIN en 16,5 s, soit ≈ 0,34 s par établissement |
| Pas H1 | R1 | 0,43 s pour 32 origines |
| Échelle L0–L5 | A | 360 établissements en 1 094 s, 4 processus |
| Taille du corpus | HOWM-1 | ≈ 0,5 Mo par établissement |

À cette taille, 10 000 établissements stockés feraient 5 Go. Le flux est donc généré en **tessons
de 500**, un tesson d'avance, et chaque tesson est supprimé après consommation (T-C16).

## Lots

| Lot | Contenu | Estimation | Plafond (s) |
|---|---|---|---:|
| C.SETUP | Consignation, code, tests | — | 900 |
| C.GEN | Flux de 10 000 (en tessons), CVAL 48, CEVAL 200 | ≈ 3 600 s | 4 200 |
| C.REF | L0, L1, L2 et L4 sur CEVAL | ≈ 600 s | 900 |
| C.PILOT | 50 pas de C.1 et de C.2 : facteur de coût k de H1-long | — | 300 |
| C.TRAIN.100 | 2 systèmes × 3 graines × 150 pas | ≈ 400 s × k | 900 |
| C.TRAIN.1000 | 2 systèmes × 3 graines × 1 500 pas | ≈ 3 × 650 × (1 + k) s | 9 000 |
| C.TRAIN.10000 | 1 graine par système (15 000 pas), puis 2 graines du meilleur selon CVAL | ≈ 6 450 × (1 + k) + 2 × 6 450 × k* s | 28 800 |
| C.EVAL | Gel F-C1, CEVAL, DIAG, sondes, calibration | — | 1 800 |
| C.REST | Rapport, paquet P2, reçu de restauration | — | 600 |
| **Total** | | | **47 400** (≈ 13,2 h) |

k* vaut 1 si le meilleur système est C.1, et k si c'est C.2.

## Échelle de réduction déclarée

Seule adaptation permise sans question, appliquée dans cet ordre si le pilote projette un
dépassement :

1. À 10 000, une seule graine par système ; le point retenu devient 1 000, avec 3 graines.
2. Si k > 3, C.2 n'est pas entraîné à 10 000 (il reste à 100 et à 1 000).
3. Au-delà : arrêt, et question avec options.

## Variante courte (au choix de l'utilisateur)

Sans le point 10 000 (génération réduite à 1 248 établissements, plafond C.GEN 900 s) : plafond total de **15 300 s** (≈ 4,3 h), point retenu 1 000. La loi d'échelle
n'a alors que deux points ; elle est déclarée comme telle.
