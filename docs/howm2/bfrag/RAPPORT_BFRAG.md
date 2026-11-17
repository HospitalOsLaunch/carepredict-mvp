# HOWM-2 — Rapport B-FRAG : fragilités dormantes, cascades et prévention

## Cadre

| Élément | Référence |
|---|---|
| Décision | n° 6 (`docs/howm2/HOWM2_DECISION_6.json`, mandat `docs/howm2/inputs/MANDAT_HOWM2_DECISION_6_BFRAG.md`) |
| Protocole | `PROTOCOLE_BFRAG.md`, version P1 du 17 novembre 2026, gelé au registre B (n° 19) avant toute mesure comparative |
| Gel avant CONF | `FREEZE_BFRAG.json` (n° 31), sha 9b348dee… |

**Statuts inchangés :** `PROTOTYPE_UNVALIDATED`, `clinical_validation=false`, `G2=NO-GO`.

**Portée.** Benchmark **synthétique** sur le monde HOWM-1. Aucune validation clinique.
- Aucun entraînement, aucune descente de gradient.
- Aucune boucle fermée : une décision unique à t0, puis la politique de fond commune.
- Rien n'a été poussé.

## 0. Verdicts (BFRAG_CONF, 96 mondes indépendants, campagne unique)

| Question | Verdict | Estimation [IC 95 %, bootstrap en grappes de mondes] |
|---|---|---|
| Validité technique du benchmark | **VALIDE** | V1 : 11 tests réussis. V2 : prévalence de rupture à 168 h sous la politique de référence = 0,28. V3 : aucune rupture active à t0. V4 : 31 % des mondes sans rupture ; témoin de charge faible (0,07) bien en dessous des familles fragiles (0,42). |
| **Avantage d'anticipation accessible** | **`AVANTAGE_ANTICIPATION`** (dans ce dispositif) | ΔAUC à 72 h, F − R1 (concurrent gelé) = **+0,117 [+0,047 ; +0,202]** |
| **Avantage décisionnel accessible** | **`INDETERMINE`** | Gain = perte(R0, concurrent gelé) − perte(F) = **+31 minutes-patient [−52 ; +123]** sur 168 h, pour une attente totale d'environ 40 300 minutes-patient. Contraintes respectées. |
| Preuve pour un réseau appris | **NON TESTÉ** | — |

**Lecture.**
- À information publique identique, la chaîne explicite F classe mieux, à 72 h, les mondes qui vont
  rompre que le concurrent statistique gelé, R1.
- Cet avantage est **modeste** : AUC de F = 0,80 contre 0,68 pour R1.
- Il tient **surtout à des différences entre familles de mondes**, et non à une meilleure lecture
  à l'intérieur d'une famille (§ 3).
- Face à la règle R0, que je n'ai pas retenue comme concurrent sur TUNE, l'écart est plus mince
  et non principal : +0,088 [+0,002 ; +0,173].
- Le diagnostic privilégié O fait nettement mieux (AUC 0,90). Il reste donc une information non
  captée par F, au moins par la voie de l'état vrai.
- En décision, aucune méthode n'a d'effet substantiel. Une intervention unique à t0 déplace
  l'attente cumulée sur 7 jours d'environ 0,6 % au mieux. Ce dispositif ne permet pas de
  départager F et la règle.

## 1. Ce qui a été exécuté

**Clôture C1** (lot CLOSE.C1, environ 2,6 s) :
- correctif documentaire `docs/howm2/c1/CORRECTIF_C1_CLOTURE.md` ;
- lecture exploratoire des journaux (`evidence/howm2_c1_closure/`) ;
- enveloppe `HOWM2_C1_CLOSURE_ENVELOPE.zip`.

**Conception.**
- Protocole P1 ; générateur **dérivé**, sans aucune source gelée modifiée.
- Six familles de scénarios, avec leurs fiches (protocole, § 3).
- Comparateurs R0, R1, R2, F et O.

**Calibrage du régime de fonctionnement sur BFRAG_DEV** (n° 9 à 17).
- Politique de référence seule, aucune méthode, avant le protocole.
- **Le monde natif HOWM-1 est saturé de façon chronique.** Tous les mondes, le témoin de charge
  faible compris, ont des patients qui attendent plus de 4 h dès t0, et les files doublent en une
  semaine.
- **Une limite de 4 h ou de 12 h** est franchie chaque nuit, à cause du nettoyage limité à
  06 h–22 h.
- **La compatibilité des lits d'isolement** compte pour 20 à 100 % des attentes de 12 h ou plus.
- **Conséquences :**
  - lits tampons publics, au-dessus d'une capacité nominale qui pilote les arrivées ;
  - rupture définie comme ≥ 5 patients attendant ≥ 24 h.

  Ces deux choix ont été faits avant toute méthode.

**Tests de validité.** T-B1 à T-B10 : 11 réussis (n° 20) avant toute comparaison.

**Pilote de coût** (n° 22, 4 mondes DEV) :
- environ 42 s de CPU par monde, 0,3 Go ;
- aucune réduction nécessaire.

**TUNE**, itération 1 (conception D2, 48 mondes, n° 25 à 29) : V1 à V4 satisfaits. Elle est donc
retenue selon la règle du protocole (§ 4), et il n'y a pas eu d'autre itération.

**Choix gelés sur TUNE :**
- concurrent décisionnel de F = **R0** (perte TUNE 44 336, contre 44 473 pour R2) ;
- concurrent d'anticipation = **R1** (AUC à 72 h sur TUNE : 0,701, contre 0,667 pour R0) ;
- seuils d'alerte : Youden, avec une charge d'alerte ≤ 0,5.

**Gel F-B / G0-v2-BFRAG-D2** (n° 31) : **gel technique seulement**, et non un passage
scientifique. Puis campagne unique **CONF** (96 mondes, n° 33 à 37, reprise sans réglage), analyse
gelée (n° 39) et compléments descriptifs (n° 41).

## 2. Résultats TUNE, itération 1 (descriptifs ; ils servent aux choix)

| Grandeur | Valeur |
|---|---|
| Prévalence de rupture à 168 h | 0,35 |
| Prévalence par famille | SF1 0,42 ; SF2 0,45 ; SF3 0,39 ; SC4 0,27 ; SC5 0,33 ; SC6 0,22 |
| AUC à 72 h | R0 0,667 ; R1 0,701 ; F 0,706 ; O 0,867 |
| Gain décisionnel R0 − F sur TUNE | **−61 [−125 ; −12]** : la règle meilleure sur TUNE |

**Contrôles appariés** (V5 : variante détendue moins variante de base, même monde et mêmes clés) :

| Famille | Attente évitée en minutes-patient [IC 95 %] | Ruptures en moins (points) |
|---|---|---|
| SF1, nettoyeur +1 | 20 494 [8 442 ; 33 203] | 23 |
| SF2, brancardier +1 | 3 391 [1 146 ; 6 579] | 3 |
| SF3, sans la baisse planifiée | 1 603 [459 ; 3 186] | 0 |

La dépendance propage donc bien ses effets à l'attente, surtout pour le nettoyage.

## 3. Résultats CONF (96 mondes)

### A. Anticipation

AUC sur les paires de réalisations de mondes différents, sous la politique de référence. Aucun
monde n'était en rupture active à t0.

| Méthode | 24 h | 72 h (principal) | 168 h |
|---|---:|---:|---:|
| R0 (règle) | 0,790 | 0,707 | 0,667 |
| R1 (statistique L2) | 0,865 | 0,679 | 0,691 |
| **F** (filtre explicite + propagation) | **0,901** | **0,795** | 0,699 |
| O (privilégié) | 0,935 | 0,899 | 0,845 |

**Horizon 6 h.** Il n'y a pas de rupture possible avant 24 h d'attente, sauf pour des patients
déjà en attente. Les AUC à 6 h valent 0,5 et ne sont pas informatives.

**Alertes aux seuils gelés** (TUNE), sur 127 réalisations en rupture à 72 h et 215 à 168 h :

| Méthode, horizon | Sensibilité | Manquées | Fausses alertes | Charge d'alerte | Avance moyenne, ratées à 0 (h) | Brier |
|---|---:|---:|---:|---:|---:|---:|
| R0, 72 h | 0,32 | 86 | 0,14 | 0,17 | 12,7 | — |
| R1, 72 h | 0,40 | 76 | 0,06 | 0,12 | 10,3 | 0,128 |
| **F, 72 h** | **0,50** | **64** | **0,05** | 0,13 | **13,7** | **0,104** |
| O, 72 h | 0,69 | 39 | 0,09 | 0,19 | 21,1 | 0,085 |
| R0, 168 h | 0,65 | 76 | 0,41 | 0,48 | 36,5 | — |
| F, 168 h | 0,55 | 96 | 0,22 | 0,31 | 27,8 | 0,181 |
| O, 168 h | 0,80 | 44 | 0,24 | 0,40 | 46,1 | 0,137 |

**Les charges d'alerte ne sont pas égalisées** ; je n'ai pas réajusté sur CONF. À 168 h, R0 alerte
deux fois plus souvent que F : sa sensibilité est plus haute, mais au prix de deux fois plus de
fausses alertes.

**Par famille** (AUC à 72 h, descriptif, sans correction) :

| Famille | R0 | R1 | F | O |
|---|---:|---:|---:|---:|
| SF1 nettoyage | 0,75 | 0,72 | 0,78 | 0,87 |
| SF2 transport | **0,92** | 0,77 | 0,88 | 0,90 |
| SF3 baisse planifiée | 0,69 | 0,55 | 0,69 | 0,85 |
| SC4 | 0,80 | 0,50 | 0,58 | 0,85 |
| SC5 | 0,98 | 0,75 | 0,90 | 0,98 |
| SC6 | 0,63 | 0,43 | 0,47 | 0,47 |

**Lecture.**
- Dans une famille donnée, F ne fait pas mieux que R0, sauf pour SF1.
- L'avantage regroupé de F tient en grande partie à **séparer les familles**, c'est-à-dire à
  exploiter la structure publique (capacités, calendrier, lits tampons) au travers des lois du
  générateur, que F connaît par construction.
- **F partage la structure de lois du générateur.** C'est un avantage de spécification dont R1 ne
  dispose pas ; il est déclaré et n'est pas un « apprentissage ».

### B. Intervention (critère primaire : attente cumulée, minutes-patient, 168 h)

| Plan choisi par | Attente moyenne | Écart avec F [IC 95 %] | Soins non couverts | Rupture à 168 h | Renfort (h) | Refus au plan |
|---|---:|---|---:|---:|---:|---:|
| Référence (plan 0) | 40 509 | +229 [+126 ; +359] | 14 465 | 0,30 | 0 | 0 |
| R0 (règle) | 40 311 | **+31 [−52 ; +123]** (principal) | 14 366 | 0,30 | 4 | 0 |
| R2 (planificateur sur R1) | 40 393 | +113 [+1 ; +234] | 14 435 | 0,30 | 0 | 0 |
| **F** | **40 280** | — | 14 435 | 0,30 | 0 | 0 |
| O | 40 320 | +40 [−49 ; +132] | 14 422 | 0,30 | 0 | 0 |

**Autres résultats.**
- Cascades (deux unités à moins de 24 h d'écart) : 0 dans toutes les conditions.
- Charge terminale (file d'environ 4,4 ; attente maximale d'environ 29 h) : identique entre
  méthodes.
- **Plans choisis :**
  - R0 : toujours coordination + compatibilité + pool IDE ;
  - F : sans action dans 52 cas, coordination dans 35 ;
  - O : sans action dans 49 cas, coordination dans 36.
- **Temps de réponse moyen par monde** : R1/R2 8,8 s ; F 14,5 s ; O 15,2 s ; R0 instantané.

**Lecture.**
- Toutes les interventions uniques à t0 ont un effet de **moins de 0,6 %** sur l'attente d'une
  semaine.
- F fait mieux que l'inaction et que R2. Il n'est **pas** distinguable de la règle R0, et R0 était
  meilleure sur TUNE.
- Aucun seuil clinique ou économique n'est inventé. Un gain de 30 minutes-patient par semaine,
  même s'il était confirmé, serait minime au regard de l'attente totale.

## 4. Lecture produit

| Question | Réponse, dans ce benchmark synthétique |
|---|---|
| **Où est la fragilité ?** | Surtout le **nettoyage avec un seul agent** (SF1) : la variante à 2 agents évite environ 20 000 minutes-patient par semaine. Puis le transport avec un seul brancardier (SF2), puis la baisse planifiée de nettoyage (SF3). Fragilité transversale : les **lits d'isolement**, qui piègent les patients isolés quand ils sont occupés par d'autres. |
| **Quel déclencheur ?** | Nuit sans nettoyage (22 h–06 h) ; baisse de capacité le jour 3 ; ralentissement d'équipe (régime m2) ; arrivées. |
| **Quel délai ?** | Les ruptures débutent en médiane **56 h** après t0 (P10 22 h, P90 129 h) : une fenêtre d'anticipation de plusieurs jours existe. |
| **Quelles actions ?** | Les seules actions ponctuelles disponibles (coordination, mode de compatibilité, renfort de 4 h) agissent peu sur 7 jours. Le levier structurel (un agent de nettoyage de plus) a un effet environ 100 fois supérieur, mais **ce n'est pas une action disponible à t0** dans ce benchmark. |
| **Quelle incertitude ?** | L'anticipation regroupée est mesurable : ΔAUC +0,12 contre R1. Mais elle est fragile dans une famille, et dépend d'une connaissance structurelle des lois. Aucun avantage décisionnel n'est établi. |

## 5. Limites

1. **Le monde est synthétique**, et le générateur est modifié : capacité nominale et lits tampons,
   pour sortir d'une saturation chronique. Les seuils de rupture (5 patients, 24 h) sont des
   conventions de benchmark, non validées.
2. **F partage la famille de lois du générateur.** Son avantage d'anticipation mesure ce que permet
   une spécification correcte. Il ne mesure pas ce qu'un modèle statistique ou appris atteindrait.
   Il n'existe **aucun** modèle régressif appris comme référence.
3. **Une seule décision à t0, sans boucle fermée** : les interventions ne peuvent pas suivre
   l'évolution sur 7 jours. Une politique de replanification adaptative reste une étape
   ultérieure distincte, non testée.
4. **R1** prolonge les arrivées au-delà de 24 h par le taux de la même heure de la journée.
   C'est déclaré, et R1 en est peut-être désavantagé à 72 et 168 h.
5. **Concurrent d'anticipation.** R1 a été choisi sur TUNE, avec un écart faible avec R0 (0,701
   contre 0,667). Sur CONF, R0 est meilleur que R1. Le verdict principal porte sur R1, comme gelé ;
   la comparaison avec R0 est rapportée à part, sans valeur principale.
6. **Unités de rééchantillonnage.** Pour E = 8 réalisations, l'IC compte le monde comme unité.
   Les seuils et les charges d'alerte ne sont pas égalisés entre méthodes.
7. **L'horizon 6 h** n'est pas informatif avec une limite de 24 h.

**Cascades.** Le critère était : deux unités en rupture à moins de 24 h d'écart. Aucune n'a été
observée. Ce critère ne capte peut-être pas d'autres formes de propagation : ressources, files de
transport.

## 6. Budget (`evidence/howm2_bfrag/BUDGET_LEDGER_HOWM2_B.jsonl`, enveloppe commune de 11 400 s)

| Lot | Mural (s) |
|---|---:|
| CLOSE.C1 (clôture C1) | 2,6 |
| BF.PREP (fumée et calibrage DEV) | 184 |
| BF.TEST | 19,5 |
| BF.PILOT | 48 |
| BF.TUNE | 549 |
| BF.CONF | 1 094 |
| BF.ANAL | 8,5 |
| BF.REST | voir le reçu |

- **Total avant paquet :** environ 1 906 s.
- **CPU :** il est enregistré par commande ; environ 1 690 s de CPU par tranche de 420 s, avec 4
  processus.
- **Mémoire :** maxima des processus enfants journalisés, environ 0,3 Go par monde.
- **Incidents :** aucun échec, aucune OOM, aucune interruption.

## 7. Suite proposée (non lancée, à décider)

1. **Confirmer l'anticipation hors famille.**
   - Une campagne neuve, avec une AUC **stratifiée par famille** déclarée comme critère principal.
   - Cela vérifierait si F lit l'état présent au-delà de la structure publique.
   - BFRAG_CONF est désormais connue et ne peut pas resservir.
2. **Référence apprise manquante.** Un modèle régressif ou de séquence appris sur les mêmes
   entrées publiques. Il exige un mandat d'entraînement.
3. **Interventions** à effet plus large, par exemple un agent de nettoyage supplémentaire sur une
   journée, déclaré comme action à coût explicite. Puis une **replanification quotidienne
   (boucle fermée)**, comme étape distincte.
4. **Gestion complète sur 24 h** de l'hôpital : extension proposée par le mandat, non exécutée.
