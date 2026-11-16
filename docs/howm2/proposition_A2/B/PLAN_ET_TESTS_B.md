# Tranche B — Note normative, matrice de tests et plan de calcul (proposés)

## Note normative B (consignée avant toute mesure, si adoptée)

- Code nouveau dans `src/hospitalos/howm_v2/`. HOWM-1 (G0 et F1) et les résultats R1, A et A′ ne
  sont pas modifiés.
- Partitions v2 sous un nouvel espace de clés `key("HOWM2v2", part, i)`, disjoint de toutes les
  partitions existantes (testé) :
  - `REF2_TUNE`, 60 : réglage ;
  - `REF2_GATE`, 200 : porte ;
  - `REF2_DEC`, 24 × 4 instants ;
  - réserve v2 scellée, créée au gel.
- Chaque itération i (au plus 3) consigne :
  - le changement de conception ;
  - la validation du filtre L4-v2 (identité, exactitude par énumération, calibration de
    l'addendum 2) ;
  - les mesures de la porte G_ID ;
  - le verdict d'itération.
- Le réglage n'utilise que `REF2_TUNE`. La porte est mesurée une seule fois par itération sur
  `REF2_GATE` et `REF2_DEC`.
- Aucun entraînement, aucune descente de gradient.

## Matrice de tests B

| ID | Objet | Condition de réussite |
|---|---|---|
| T-B01 | Espace de clés v2 | Disjoint de G0, de HOWM2_* et de C1 ; réserve v2 scellée. |
| T-B02 | Chaîne de régime v2 | La loi stationnaire et la durée moyenne empiriques égalent la loi déclarée (3 000 tirages, tolérance 0,03). |
| T-B03 | Convention à t0 | L'état vrai d'un instant contient les événements de t0. S_pub = S_true dans un monde sans retard et sans état caché. |
| T-B04 | Décisions de l'opérateur publiques | Placements, débuts de transport et de nettoyage ont un retard nul. |
| T-B05 | Effet des actions selon l'état caché | Effet du renfort de nettoyage nul en régime normal, positif en régime lent : test sur 1 000 tirages appariés. |
| T-B06 | Dérive de θ | Marche aléatoire de variance déclarée, testée. |
| T-B07 | G_alt-v2 indépendant | Aucun code partagé hors numpy. Il reproduit les marges de G_main-v2 à 10 % près sur 5 statistiques déclarées. |
| T-B08 | L4-v2 exact | Énumération sur des préfixes, et forward-backward indépendant (écart ≤ 1e-9), comme en A. |
| T-B09 | L4-N-v2 | Identité dans un monde sans retard, bit à bit (comme N-c). |
| T-B10 | Fichiers gelés | Les fichiers G0 et F1 de HOWM-1 et les résultats livrés sont inchangés (hash). |

## Plan de calcul B

CPU, 0 €, registre `BUDGET_LEDGER_HOWM2_B`.

| Lot | Contenu | Plafond (s) |
|---|---|---:|
| B.SETUP | Consignation, code v2, G_alt-v2, tests | 1 200 |
| B.ITER × 3 | Par itération : génération, échelle L0–L5 sur 200, filtre, décision sur 96 instants | 3 × 3 000 |
| B.GEL | Gel G0-v2 (seulement si une itération passe) et paquet | 600 |
| B.REST | Rapport, paquet P2, reçu de restauration | 600 |
| **Total** | | **11 400** (≈ 3,2 h) |
