# HOWM-1 — Relevé des changements v1 → v1.1

Les originaux v1 sont **inchangés** ; leurs empreintes figurent dans
`MANIFESTE_COMPLETUDE_v1_1.json`. Les changements sont portés par
`AMENDEMENT_HOWM1_R0_R1_v1_1.md` et `EXPERIMENT_HOWM1_R0_R1_v1_1.json`.

| # | v1 | v1.1 | Raison |
|---|---|---|---|
| 1 | Cible « NLL de H1 ≥ 10 % sous B0-local » | **Retirée.** Critère principal : différence appariée de score logarithmique Δ_LS en nats, sur supports discrets, sans constante, borne basse > 0 à H6 et H24. Ambition de 10 % reportée sur le **CRPS normalisé** (score non négatif), séparée de la lecture statistique (A1) | revue § 3.1 |
| 2 | Soins évalués par densité log-normale | Évalués sur intervalles de 5 min. La paramétrisation d'entraînement est inchangée | même raison (score indépendant des unités) |
| 3 | δ_dec = 15 et cible décisionnelle 5 sans distinction écrite | Deux objets définis : seuil de marge accessible (précontrôle, contrôleurs privilégiés) et ambition sur la différence de regret, lue seulement si la marge est informative (A1.3) | revue § 3.2 |
| 4 | U « à fixer avant G0 » | **U-HOWM-1 fixé** : soins non couverts + 15 × heures d'attente d'un lit, avec OBJ-LEX-1 (tolérance 15) pour la sélection (A2) | revue § 3.2 |
| 5 | Ordre « avant le gel concerné » | Ordre normatif explicite en 8 rangs, avec renvois (A3) | revue, demande 3 |
| 6 | w_k réglés sur VAL ; patience « après pilote » | w_k = 1 fixés ; patience de 20 époques ; règle de choix du lr écrite (A4) | revue, demande 3 |
| 7 | torch 2.4.1, options A/B/C | **torch 2.15.0** ; A : index CPU, **hôte actuellement bloqué par le proxy** ; B : PyPI avec dépendances CUDA ; **C retirée** ; politique de chargement des checkpoints (A5) | revue § 4 ; avis GHSA-63cw et GHSA-v32g |
| 8 | Temps mural seulement | Temps mural (plafonds) et temps CPU (rapporté) distingués ; parallélisme fixé ; pilote inclus (A6) | revue, demande 5 |
| 9 | P0 ou P1 | Dépôt constaté **public**. Ajout de **P2** (paquet de jalon envoyé comme fichier, recommandé) ; conditions écrites de P1 ; reçu de restauration depuis le paquet livré (A7) | revue, demande 6 |
| 10 | — | Nouveau test **T-PLAN-07** : ensemble d'éléments évalués identique pour tous les modèles (empreinte). La matrice v1 est inchangée ; ce test s'y ajoute | conséquence de 1 |

**Valeurs encore ouvertes :** seulement vos deux choix (route d'installation et persistance).
