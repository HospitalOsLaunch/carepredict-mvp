# Rapport B-FRAG 2 — fragilité dynamique et interventions différées

**Décision** n° 7, 17 novembre 2026.

**Statuts inchangés :** `PROTOTYPE_UNVALIDATED`, `clinical_validation=false`, `G2=NO-GO`.

**Nature des résultats.** Il s'agit d'un benchmark **synthétique** : aucun résultat ci-dessous n'est clinique.

**Sources :**

- Protocole : `PROTOCOLE_BFRAG2.md`, gel 1 (registre, note `protocol_freeze_bfrag2`), puis gel 2 (`freeze2_bfrag2`) avant la campagne CONF unique.
- Audit de F : `AUDIT_F_BFRAG2.md`.
- Résultats : `evidence/howm2_bfrag2/RESULTS_BFRAG2_CONF.json`.
- Sélections : `SELECTION_VAL.json` et `LEARN.json`.

## Verdicts (CONF, IC Bonferroni 98,33 %, bootstrap par structure)

| Question | Comparaison principale | Estimation [IC 98,33 %] | Verdict |
|---|---|---|---|
| **A. Valeur de l'historique** | ΔAUC conditionnelle S2 − S1 (LR C = 0,01 commun), 200 structures, 96 avec paires | **−0,004** [−0,012 ; +0,005] | **EQUIVALENT** (marge ±0,02) : l'historique n'ajoute rien de mesurable au-delà de l'état instantané |
| **B. Avantage de F** | ΔAUC conditionnelle F − C\*, C\* = LR-S2 (choisi sur VAL-S) ; CONF-S, 24 structures, **8 avec paires** | **−0,103** [−0,222 ; +0,020] | **INDETERMINE**, estimation **défavorable à F** |
| **C. Bénéfice des interventions** | attente(D\*) − attente(planificateur F), D\* = planificateur R1 (choisi sur VAL-S) ; 24 structures × 3 décisions | **+254 patients-minutes** [+79 ; +461] sur 168 h | **GAIN_F** (aucun garde-fou dégradé) |
| **D. World model latent appris** | — | — | **NON TESTÉ** |

## A. Valeur de l'historique (S2) au-delà de la structure (S0) et de l'état (S1)

- **Données.** 8 680 origines CONF, dont 1 190 positives ; 96 des 200 structures ont des paires intra-structure.
- **Références apprises.** Ajustées sur TRAIN : 8 721 lignes, 1 251 positives ; temps d'apprentissage < 6 s pour les 24 modèles.
- **Ce qui porte l'information : l'état instantané.** S1 − S0 = **+0,333** [0,290 ; 0,377] (IC 95 %). L'AUC conditionnelle de S0 vaut 0,53, presque aléatoire. C'est attendu : la structure est constante au sein d'une structure, et seuls l'heure et le calendrier varient.
- **Sous-ensembles et variantes :** S2 − S1 reste nul partout (IC 95 %).
  - Meilleure configuration par vue (HGB-d3 pour S1) : −0,009 [−0,022 ; +0,004].
  - Même phase horaire : −0,006 [−0,014 ; +0,002].
  - Avant pression manifeste (81 structures) : +0,003 [−0,016 ; +0,018].
  - Horizon 24 h : −0,003 [−0,009 ; +0,002].
- **À famille et capacité identiques.** Sur les 8 configurations, S2 − S1 va de −0,009 (LR) à +0,002 (HGB), en estimation ponctuelle.
- **Alertes, références apprises seulement** (CONF entier, 308 épisodes de rupture, seuils fixés sur VAL à ≤ 0,10 fausse alerte par unité-jour) :

| Vue | Détection | Temps sous alerte | Fausses alertes par unité-jour |
|---|---|---|---|
| S2 | 65 % | 34 % | 0,085 |
| S1 | 60 % | 43 % | 0,095 |

  Le seul gain secondaire de l'historique est donc **opérationnel**, et modeste : moins de temps sous alerte à détection égale ou meilleure. Il n'est pas testé formellement.
- **Lecture.** Dans ce monde, l'état public instantané résume presque toute l'information utile à 72 h. Les dérivées et les comptes historiques ne s'y ajoutent pas de façon mesurable.

## B. F face à la meilleure référence publique

- **Données.** CONF-S : 1 067 origines, 103 positives, mais seulement **8 structures sur 24 avec paires** intra-structure. VAL-S en avait 5 sur 18. La comparaison principale repose donc sur peu de structures : c'est la limite principale de la question B.
- **AUC conditionnelles sur CONF-S** (IC 95 %) :

| Méthode | AUC conditionnelle [IC 95 %] |
|---|---|
| O (privilégié) | 0,896 [0,837 ; 0,956] |
| LR-S2 | 0,901 [0,828 ; 0,973] |
| HGB-S1 | 0,898 [0,842 ; 0,953] |
| **F** | **0,798** [0,752 ; 0,859] |
| R1 | 0,785 [0,706 ; 0,878] |
| R0 | 0,754 [0,635 ; 0,863] |
| LR/HGB-S0 | 0,541 |

- **F face aux références apprises** (secondaire, IC 95 %) :
  - F − S1 = −0,100 [−0,165 ; −0,028] ;
  - F − S2 = −0,103 [−0,200 ; −0,002] ;
  - O − F = +0,098 [0,025 ; 0,165].
- **F face aux références simulées :** F − R1 = +0,013 [−0,066 ; +0,105] ; F − R0 = +0,044 [−0,029 ; +0,130].
- **Résultat défavorable.** Avec une classe de modèle exacte, F reste à environ 0,10 d'AUC sous des régressions logistiques sur l'état public instantané, et sous O. L'écart à O désigne l'inférence de F, c'est-à-dire le prior large, le régime et le nowcast, et non la classe de modèle. Le bruit Monte-Carlo à M = 32, non atteint en rang sur DEV, atténue aussi les AUC de F, R1 et O ; il n'explique pas un écart de 0,10 avec O, qui a le même M.
- **Alertes sur CONF-S** (20 ruptures, seuils fixés sur VAL) :

| Méthode | Détection | Fausses alertes par unité-jour | Temps sous alerte | Avance médiane | Détectées avant pression manifeste |
|---|---|---|---|---|---|
| F | 80 % | 0,096 | 20 % | 41,5 h | 7 |
| R1 | 80 % | 0,059 | 10 % | 44,5 h | 9 |
| LR-S2 | 70 % | 0,106 | 33 % | 57 h | 9 |

  O détecte peu en alertes (55 %) car son seuil VAL est plus haut. Toutes ces métriques reposent sur de petits nombres.

## C. Interventions différées (168 h, contrefactuels indépendants, 8 futurs vrais communs)

| Politique | Attente moyenne (patients-minutes / décision) | Écart avec le planificateur F [IC 95 %] |
|---|---|---|
| Aucune | 33 587 | +1 360 [911 ; 1 871] |
| Règle structurelle VAL (renfort de la ressource la plus rare, créneau 2 : `cl+1_w2` ou `tr+1_w2`) | 33 114 | +887 [562 ; 1 255] |
| Structurelle verrouillée S2 | 33 115 | +888 [564 ; 1 255] |
| Historique (`hist_coord_compat`) | 32 662 | +435 [130 ; 823] |
| **Planificateur R1 (D\*)** | 32 481 | **+254** [112 ; 419] (IC 98,33 % : [79 ; 461]) |
| **Planificateur F** | **32 227** | — |
| Planificateur O (privilégié) | 32 248 | +21 [−95 ; +161] |
| Meilleure action a posteriori | 32 074 | (borne) |

- **Garde-fous** (F − D\*, IC 98,33 %) :
  - soins non couverts : −6 min [−66 ; +68] ;
  - rejets : 0 ;
  - minutes de rupture : −10 [−25 ; +1] ;
  - file terminale : −0,01 [−0,04 ; +0,02] ;
  - attente terminale max : −17 min [−35 ; −2] ;
  - déplacement de charge : part de l'unité A +0,002 [−0,001 ; +0,006] ;
  - heures-agents moyennes : F 3,3, D\* 4,3.

  Aucune dégradation.
- **Ampleur.**
  - Le gain de F sur R1 vaut **0,8 %** de l'attente.
  - F capte environ 62 % de la marge restante entre R1 et la meilleure action a posteriori.
  - F fait aussi bien qu'O.
  - L'essentiel du bénéfice total vient de **l'action historique** (coordination compatibilité), choisie par F dans 41 décisions sur 72. Les renforts différés comptent moins.
- **Par famille** (moyennes descriptives) : F devance R1 dans SF1, SF2, SF3, SC4 et SC6, avec le plus grand écart dans SF2 (−604). Il fait légèrement moins bien dans SC5 (+57).
- **Lecture.** À information publique identique, le simulateur structurellement exact de F choisit un peu mieux que le modèle statistique R1. Ce gain de décision coexiste avec un **désavantage de F en anticipation** (question B). L'utilité de F tient à la **comparaison d'actions**, et non à la discrimination du risque.

## Propagation (contrôles appariés, CONF structures 0–59, 3 épisodes)

Effet sur les minutes de rupture (base − relâché, IC 95 %) :

| Famille | Effets significatifs | Effets non significatifs |
|---|---|---|
| SF1 (fenêtre nettoyage) | +1 nettoyage **612** [86 ; 1 335] | transport 8 [−74 ; 118] ; compatibilité 91 [−28 ; 238] |
| SF2 (fenêtre transport) | +1 nettoyage et +1 transport **200** [49 ; 349] | +1 transport 117 [−7 ; 251] |
| SF3 (baisse planifiée) | nettoyage **25** [6 ; 48] ; suppression de la baisse **16** [3 ; 30] | — |
| SC4, SC5, SC6 | aucun | — |

- L'interaction nettoyage × transport est non significative partout.
- **Transmission entre unités (cascade A→B) : NON ÉVALUABLE.** Aucun contrôle apparié n'isole ce canal.
- Les traces d'attribution (blocages au moment où des patients attendent ≥ 24 h) sont publiées par famille. Elles ne sont pas exclusives : un même tick peut compter plusieurs blocages.

## Exemples de trajectoires (CONF-S)

- **Structure 12, épisode 0 (SF1).** Rupture dans l'unité B à partir de 157 h ; origines positives de 90 h à 120 h.
  - F reste bas (0,03 à 0,22), O monte à 0,72 puis 0,88.
  - Décision à 42 h : R1, F et O choisissent tous `cl+1_w4`, 1 500 patients-minutes de moins que l'inaction.
- **Structure 20, épisode 0 (SF3).** Ruptures répétées dans l'unité A, dont la baisse planifiée du jour 3.
  - O voit venir la rupture (0,56 à 1,0), alors que F et R1 restent entre 0 et 0,19 : c'est l'illustration du désavantage de F en anticipation.
  - À la décision, F choisit `cl+1_w4` (57 253) contre `cl+1_w3` pour R1 (57 769).
- **Structures 0, 4 et 8.** Aucune rupture. L'action historique domine largement (−3 300 à −5 000 patients-minutes) ; F, R1 et O la choisissent.

## Lecture produit (non clinique)

- Pour **anticiper** une rupture à 72 h, un score appris simple sur l'état public instantané fait au moins aussi bien que les simulateurs, F compris. L'historique n'apporte pas de discrimination supplémentaire mesurable. Il réduit seulement un peu le temps sous alerte.
- Pour **choisir une intervention**, un simulateur structurellement juste, avec inférence publique, apporte un gain faible mais net sur le planificateur statistique, sans dégradation des garde-fous. Le levier dominant reste l'action historique de coordination.
- Ces conclusions valent pour ce monde synthétique, pour un modèle de F qui a la classe exacte du générateur et pour des budgets de calcul réduits (M = 32). Elles ne valent pas au-delà.

## Limites et résultats défavorables

1. **Question B : 8 structures avec paires seulement.** L'IC principal est large, et l'estimation est défavorable à F.
2. **Tolérance de rang MC non atteinte à M = 32 pour le risque.** C'est le plafond préregistré ; l'effet est une atténuation des AUC de R1, F et O.
3. **Stabilité de décision établie sur 2 décisions DEV seulement.** L'étude de stabilité a été faite avant la correction du calendrier, et elle n'a pas été refaite.
4. **Défaut d'implémentation corrigé avant le gel.** La trajectoire de référence omettait le calendrier public (`CORRECTION_CALENDAR.json`).
5. **Deux échecs de tests consignés au registre.** Les #60 et #62 venaient de défauts des tests eux-mêmes, corrigés ensuite ; ils ne venaient pas du code.
6. **F partage la classe du générateur.** L'avantage de décision de F est donc un avantage de modèle exact, pas une preuve de généralisation.
7. **Sélections faites sur VAL-S, petit.** Le choix de C\* et de D\* y repose sur 18 structures.
8. **Horizon 168 h non observable pour l'anticipation.** Cascades entre unités : NON ÉVALUABLE.
9. **Révisions de conception utilisées : 0 sur 2.**

## Budget (registre B, non remis à zéro)

| Lot | Mur (s) | Commandes |
|---|---|---|
| DEV | 533,1 | 5 |
| PREP | 58,4 | 4 |
| TRAIN | 297,9 | 2 |
| VAL | 1 551,0 | 6 |
| CONF | 3 844,0 | 10 |
| ANAL | 6,7 | 1 |
| **Total B-FRAG 2 avant paquet** | **6 291,2** | — |

- Temps CPU : 21 079 s.
- Reste avant paquet et reçu : 3 064,4 s sur les 9 355,654 s disponibles. Les chiffres définitifs, avec le paquet et le reçu, sont dans le message de livraison et dans le registre.
- Aucun dépassement, aucun délai d'expiration. Concurrence 4, mémoire ≈ 305 Mo par processus.

## Paquet et reçu indépendant

- **Paquet scientifique** `HOWM2_P2_BFRAG2_FINAL.zip` : sha256 `04cbc021…f4dea2`, 1 694 fichiers, commit 23ab97d. Vérifié dans un répertoire neuf.
- **Reçu indépendant** (répertoire neuf, tentative 2, registre #117) :

| Contrôle | Résultat |
|---|---|
| Intégrité | 1 694 fichiers, 0 écart |
| Tests | 21 passés |
| Références apprises | 24 modèles rechargés (hashes), ré-ajustés depuis TRAIN, prédictions identiques |
| Reproduction | `SELECTION_VAL.json` et `RESULTS_BFRAG2_CONF.json` identiques |
| Régénérations exécutées (identiques hors temps) | 1 épisode CONF-S complet, 1 épisode VAL-S, 1 épisode CONF de vues, 1 structure de contrôles appariés |

- **Tentative 1 (#114) : échec du script de reçu**, pas de la science.
  - Paramètre `Md` passé différemment du fichier d'origine.
  - Temps `score_seconds` non retiré.
  - Défaut consigné dans `RECEIPT_ATTEMPT1_DEFECT.json`, corrigé, puis reçu relancé sur le même paquet.
- **Enveloppe de clôture** : `HOWM2_BFRAG2_CLOSURE_ENVELOPE.zip`. Le rapport et le registre qu'elle contient sont postérieurs au paquet.

## Suite (proposition, non exécutée)

1. Agrandir CONF-S, ou concentrer les structures sur les familles avec ruptures, pour trancher la question B (environ 8 structures avec paires aujourd'hui).
2. Refaire l'étude de stabilité MC après la correction du calendrier, à M = 64 pour F et O sur VAL, si le budget est accordé.
3. Ajouter un contrôle apparié de la transmission entre unités, pour rendre les cascades évaluables.
4. Évaluer un F à prior informé par famille, pour séparer l'effet du prior et celui de l'inférence d'état.
