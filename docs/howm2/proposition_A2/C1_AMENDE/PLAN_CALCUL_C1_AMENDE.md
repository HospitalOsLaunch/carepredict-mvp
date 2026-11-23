# Plan de calcul C1 amendé (proposé)

## Conditions et repères

- CPU, 0 €, registre `BUDGET_LEDGER_HOWM2_C1`, 7 000 s au plus par commande, reprise exacte.
- Pas H1 : 0,43 s pour 32 origines (R1).
- Génération : environ 0,34 s par établissement.
- Facteur k de C.2a : mesuré au pilote. Il est attendu entre 2 et 4, puisque la séquence passe
  en moyenne de 24 à environ 80 heures.
- Coût de C.2b : celui de C.1.

## Palier 1 (100 et 1 000)

| Lot | Contenu | Plafond (s) |
|---|---|---:|
| C.SETUP | Consignation, code, tests | 900 |
| C.GEN1 | Flux 0–999 en tessons, CVAL 48, CEVAL 200 | 900 |
| C.REF | L0, L1, L2, L2c et L4 sur CEVAL (code de A et A′) | 900 |
| C.PILOT | 50 pas de chaque système : facteur k | 300 |
| C.TRAIN.100 | 3 systèmes × 3 graines × 150 pas | 1 200 |
| C.TRAIN.1000 | 3 systèmes × 3 graines × 1 500 pas : environ 650 × (6 + 3k) s | 10 800 |
| C.EVAL1 | Gel F-C1 (palier 1), CEVAL, DIAG, sondes, calibration | 1 800 |
| C.REST1 | Rapport, paquet, reçu | 600 |
| **Total du palier 1** | | **17 400** (≈ 4,8 h) |

## Palier 2 (10 000), conditionnel (N9′)

| Lot | Contenu | Plafond (s) |
|---|---|---:|
| C.GEN2 | Flux 1 000–9 999 en tessons | 3 300 |
| C.TRAIN.10000 | 1 graine par système (15 000 pas), puis 2 graines du meilleur | 6 450 × (2 + k + 2k*) |
| C.EVAL2 et C.REST2 | Évaluation, rapport, paquet, reçu | 2 400 |
| **Total du palier 2** | | ≈ 30 000 à 45 000, selon k |

k* vaut 1 si le meilleur système est C.1 ou C.2b, et k si c'est C.2a.

**Échelle de réduction du palier 2.** Si k > 3, C.2a n'est pas entraîné à 10 000. Au-delà : arrêt
et question.
