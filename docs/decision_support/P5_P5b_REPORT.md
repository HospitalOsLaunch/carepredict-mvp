# P5b — Test de représentation M_agg contre M_ent (14 novembre 2026)

**Autorisation :** (iii), option A, adoptée explicitement (« Approuve », précisé par le choix
« Mandat P5b, option A »). Relevé `docs/decision_support/P5_DECISIONS_v7_P5b.json`, registre n° 89.
Protocole : P5-PROTO-3 + 3.1 (D13). Rien d'autre n'est lancé : pas de D16, de P6, d'AJ-H,
d'installation ni de push. Arrêt après cette livraison.

**Verdict R1 (principal) : `insufficient`.** Δ_rep = U(choix M_agg) − U(choix M_ent) =
**+2,27 minutes-soignant par épisode, IC 95 % [−2,54 ; +6,94]**. La borne supérieure est inférieure
à δ = 15. Dans ce protocole synthétique, le modèle qui voit les séjours et les offres ne choisit
**pas** de meilleurs plans que le modèle par agrégats d'au moins le seuil pré-enregistré. Ce
résultat négatif est rapporté tel quel. La lecture avait été déclarée **confirmatoire avant F_b**
(précision projetée suffisante), et il n'y a aucun réglage après lecture.

Données synthétiques seulement. Statuts inchangés : `PARTIAL_WITH_CHECKPOINT`,
`PROTOTYPE_UNVALIDATED`, `clinical_validation=false`, `G2=NO-GO`. P5a reste `exploratory`.

## 1. Déroulé (registre P5)

| N° | Étape | Résultat |
|---|---|---|
| 89 | accord consigné ; lot P5.4 ouvert | — |
| 90–91 | lint ; tests avant E8 | 84 réussis + 3 échecs expliqués (2 tests utilisaient « P5.4 » comme lot interdit, adaptés à « RESERVE » ; 1 refus d'intégrité attendu) |
| 92–93 | **E8** (code P5b engagé avant toute génération) | graines inchangées, moteur v6 identique à `856a57c` |
| 94 | tests sous E8 | **87/87** (`pytest_p5_1_E8.xml`) |
| 95 | garde : validation refusée avant le précontrôle | code 4 |
| 96–98 | étiquettes d'entraînement : 24 × 15 parents × 2 jumeaux, R1, K = 3 | 360 parents ; 6 exclusions sur 366 candidats (1,6 %) |
| 99 | **précontrôle des jumeaux** | **informatif** (§ 2) |
| 100 | étiquettes de validation : 8 × 15 × 2 | 120 parents |
| 101–102 | matrices | entraînement 5 608 lignes, validation 1 982 ; M_agg 290 et M_ent 718 variables |
| 103–112 | **24 ajustements de sélection** (graine 0) | durées réelles 0,7 à 14,1 s, aucune au-delà de 30 s ; 2 ajustements reportés automatiquement dans leur propre commande |
| 113 | sélection sur la validation | M_agg (profondeur 5, lr 0,05, 400) ; M_ent (profondeur 5, lr 0,1, 400) |
| 114–118 | **4 contrôles L2** (graines 1 et 2 sur les configurations retenues) | écart maximal des prédictions **0,0** pour les deux familles ; **28 ajustements au total** |
| 119 | **projection de précision** de Δ_rep sur la validation (écart-type propre à P5b) | écart-type entre structures 5,96 ; demi-largeur projetée **2,13 ≤ 7,5** ⇒ lecture **confirmatoire déclarée avant F_b** |
| 120–123 | **isolation sur 50 épisodes avant F_b** (méthode v2 pour les modèles), sélection consignée au registre (n° 122) avant contrôle | 50 sur 50 ; variables, prédictions et choix invariants sous les 6 vérités ; T04-b/c/d réussis ; T04-a détecté 47 fois, **NON_INFORMATIF 3 fois** (nommé d'avance) ; **0 véritable échec** |
| 124 | garde : réservé refusé sans F_b | code 4, rien de généré |
| 125–126 | **F_b** (25 fichiers figés, dont les 2 modèles retenus) | `F_b.json` `ef1be9c0…ba2b` |
| 127–128 | **évaluation réservée** : 30 × 4 × 2 jumeaux, R1 et R2, K = 3, plus le planificateur v6 | 120 parents ; 0 exclusion sur 120 candidats ; aucun arrêt |
| 129–130 | matrices réservées ; prédictions des modèles figés | — |
| 131 | analyse finale (graine de bootstrap engagée en E0) | § 3 |

## 2. Précontrôle des jumeaux (entraînement, R1, K = 3)

- θ ponctuel 846,7 ; **borne inférieure unilatérale à 95 % 581,9 ≥ 25**, soit un écart
  quadratique moyen d'effet d'environ 29 minutes-soignant entre jumeaux, sur les plans homologues.
- 300 parents utilisés ; 60 sans plan homologue non habituel.
- Le **meilleur plan homologue change entre jumeaux dans 10 % des parents seulement** : les effets
  diffèrent, mais l'ordre des plans change peu.

## 3. Résultats réservés

| R1 (principal), par épisode, IC 95 % | Valeur |
|---|---|
| **Δ_rep = U(M_agg) − U(M_ent)** | **+2,27 [−2,54 ; +6,94]** |
| U pratique habituelle | 903,8 |
| U choix M_agg / M_ent / planificateur v6 | 724,9 / 722,6 / 721,0 |
| U\* (minimum exact de l'univers public) | 712,8 |
| Gain contre la pratique habituelle : M_ent / M_agg / v6 | 181,2 / 179,0 / 182,9 |
| Regret contre U\* : M_ent / M_agg | 9,8 [5,6 ; 14,8] / **12,1 [7,7 ; 17,2]** |
| Même plan choisi par les deux modèles | 70 % des épisodes jumeaux |
| Décomposition du choix M_ent : renforts seuls / coordination à renforts égaux / interaction | 82,8 / 98,4 / −4,3 |
| Heures de renfort prévues : M_ent / M_agg | 3,46 / 3,40 |
| Erreur pondérée sur le réservé, MAE / RMSE : M_ent ; M_agg | 155,2 / 202,5 ; 156,1 / 208,2 |

**Garde-fous R1 :**
- exclusions : 0 % ;
- **dégradation de M_ent contre la pratique habituelle : 0 structure sur 30**, borne de
  Clopper–Pearson 9,50 % ≤ 10 % ;
- M_agg : 0 structure sur 30 ;
- isolation sur 50 épisodes : aucun véritable échec.

**R2 (robustesse seulement) :**
- Δ_rep = +1,38 [−3,42 ; +6,02], soit `insufficient`.
- Une structure est dégradée pour M_ent : borne 14,86 %, au-dessus de 10 % sous ce régime.
  Signalé, sans effet sur le verdict R1.

## 4. Lecture

1. **Résultat principal.** Dans ce simulateur et sur cette population construite, voir les séjours
   et les offres n'apporte pas d'amélioration de choix d'au moins 15 minutes-soignant par épisode.
   L'effet estimé est petit (+2,3) et l'IC contient 0.
2. **Limite structurelle, observée après lecture et sans rien changer au verdict.**
   - L'écart que M_ent peut gagner sur M_agg est borné par le regret de M_agg, 12,1 en moyenne.
   - Même un M_ent parfait n'aurait donc pas pu dépasser δ = 15 en moyenne sur cette population.
   - Les deux modèles, comme le planificateur v6, sont déjà proches du minimum exact. Le précontrôle
     montrait d'ailleurs que le meilleur plan change rarement entre jumeaux (10 %).
   - Le test était donc peu capable de démontrer un bénéfice de cette taille ici.
   - Un futur protocole devrait construire des populations où l'information par entité change
     réellement le meilleur plan. Ce serait une nouvelle expérience annoncée à l'avance, pas une
     relecture de celle-ci.
3. Les erreurs absolues de prédiction sont élevées (MAE environ 155) alors que le classement des
   plans d'un même épisode reste bon. Les modèles servent ici à ordonner des plans, pas à prévoir
   U en valeur absolue.
4. **Ce que P5b ne démontre pas :** pas de causalité ni de calibration réelles, pas de
   généralisation hospitalière, rien sur une architecture latente. La population de jumeaux est
   construite.

## 5. Budget

| Lot | Utilisé | Plafond |
|---|---:|---:|
| P5.4 | **218,288 s**, dont 157,5 s pour les 14 commandes d'ajustement (28 ajustements) | 470 s |
| P5.5 | 4,858 s avant la vérification de livraison | 90 s |
| P5.0 / P5.1 | 4,916 s / 51,735 s | 30 s / 130 s |
| **Total** | **369,173 s** avant la vérification de livraison | 1200 s |

Le devis prévoyait environ 290 s brut et 410 s avec marge pour P5.4. Le réel est plus bas : les
ajustements sur des données diverses ont été plus rapides que sur le banc tuilé. Aucun plafond
n'a été modifié ni transféré.

## 6. Artefacts

Relevés d'exécution, sans dossier `runs/` :
- `evidence/decision_support/p5/p5b/P5b_{train,val,eval}/executions/<id>/`.

Reçus et jalons :
- `FITS.jsonl` (28 ajustements avec empreintes des modèles et des prédictions) ;
- `SELECTION.json`, `CONTROLS.json`, `PRECHECK.json`, `PRECISION_P5b.json` ;
- `ISOLATION50_*`, `F_b.json`, `EVAL_CHOICES.json`, `RESULTS_P5b.json`.

Modèles et matrices :
- les **2 modèles retenus** (figés dans F_b) sont versionnés ;
- les 26 autres modèles et les matrices (`.npz`, `.npy`) restent hors dépôt, avec empreintes dans
  les reçus ; les matrices sont régénérables à l'identique.
