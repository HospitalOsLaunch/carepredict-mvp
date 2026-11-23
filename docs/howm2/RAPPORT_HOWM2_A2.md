# HOWM-2 — Rapport de la tranche A′ : l'état présent comme état caché

Statuts inchangés : `PROTOTYPE_UNVALIDATED`, `clinical_validation=false`, `G2=NO-GO`. Données
synthétiques seulement ; aucun bénéfice hospitalier réel n'est revendiqué.

**Ce qui a été respecté :**
- aucun entraînement, aucune descente de gradient ;
- la réserve HOWM-1, DEVTEST et DIAG-DEV n'ont pas été lus ;
- aucun fichier gelé G0 ou F1 n'a été modifié, ni v6, P5, `mvp/computer-use`, ni les résultats
  R1 et A ; le test `test_frozen_code_unchanged` le vérifie ;
- aucun push.

**Règles :**
- `NORME_HOWM2_A2.md` (registre n° 34) et addendum A2-1 (n° 35), consignés avant toute mesure ;
- addendum A2-2 (décision n° 4, n° 40), consigné avant A2.DEC, A2.COV et A2.L2C.

## 0. Verdicts

| Question | Résultat |
|---|---|
| **A2.DEC** (critère principal) | **`NOWCAST_MARGE_LT_15`**. marge_N = U(règle) − U(L4-N) = **−47,2** [−81,6 ; −19,2] sur 96 instants et 24 grappes. La règle renforcée reste meilleure que le planificateur nourri par l'état présent estimé. ⚑ Limite de validation : (N-o′) non concluant. |
| Part récupérée de l'état présent | **κ = 0,07** [0,001 ; 0,18]. L4-N récupère environ 7 % de l'écart entre L4 et C_full. Gain apparié de L4-N sur L4 : +5,1 [+0,1 ; +11,1]. ⚑ |
| Validation de L4-N | (N-c) réussi, bit à bit. (N-a) réussi pour les 7 types. (N-o) littéral dégénéré (+∞). (N-o′) Brier : échec pour L4-N **et** pour le témoin L5-N, d'où un arrêt et la décision n° 4 : « limite du test, poursuivre ». |
| A2.COV (descriptif) | L4-N ne récupère presque rien de l'écart de couverture entre départ public et départ vrai : 2 % à H1, −4 % à H24. ⚑ |
| A2.L2C | La référence corrigée L2c est **moins bonne** que L2 à H6 et H24. M_pub, avec la meilleure de {L2, L2c}, est inchangé : 0,099 [0,087 ; 0,109] à H6 et 0,141 [0,121 ; 0,160] à H24. Il baisse à H1 : 0,035 [0,031 ; 0,038]. **Aucun signalement pour C1.** |

⚑ = L4-N n'a pas passé (N-o′). Cet échec est traité comme une limite du test (addendum A2-2).

**Lecture.**
- L'hypothèse de travail de A′ n'est **pas confirmée**. L'état présent masqué par le retard de
  publication est rare : environ 0,4 événement en attente appliqué par tirage, et 1,3 événement en
  attente vrai par instant. Le récupérer ne vaut qu'environ 5 minutes-soignant.
- L'écart d'environ 72 entre C_full et L4 (96 instants) a donc d'autres causes :
  - les opérations de l'opérateur non publiées (placements, débuts de nettoyage) ;
  - le fait que l'état public est **en avance** sur l'état vrai à t0 (§ 1) ;
  - les tirages privés de l'état vrai.
- La défaite de L4 face à la règle tient aussi en partie à OBJ-LEX-1. Avec une sélection par U
  minimal pur, L4-N passe de −47,2 à −32,2 contre la règle : il reste battu.

## 1. Faits du § 1, revérifiés (`evidence/howm2/FACTS_CHECK_A2.json`, registre n° 33)

| Fait | Statut |
|---|---|
| L4 5 002,8 ; C_param 5 007,0 ; C_pub_snap 4 999,5 | conforme |
| C_full 4 945,2 (écart 57,6 avec L4) ; règle 4 974,1 | conforme |
| V_latent = +61,8 | **conforme, mais attribution à préciser.** V_latent = C_param − C_full mélange régime, événements en attente et **toute** autre différence entre état public et état vrai. |
| Pour m2, π ≤ 0 | conforme : transport −0,75, nettoyage −0,22 à H24 |
| Couverture à 1 h : 0,573 public, 0,877 vrai | conforme |
| Retard de publication 0 à 60 min (REF), 0 à 120 min (DIAG) | **à préciser.** C'est la **moyenne** θ_lag tirée par établissement. Chaque retard suit une loi floor(Exp(θ_lag)), non bornée. Quatre types d'événements ont un retard nul : demande de transport, demande d'offre, plan, statique. |
| M_pub à H24 par famille : ready 0,242, confirmation 0,299, soins 0,021, arrivées 0,001 | conforme ; aucun item de présence |
| OBJ-LEX-1 retient souvent un plan sans coordination, la règle coordonne toujours | conforme : L4 coordonne 13 fois sur 48, la règle 48 fois sur 48 |
| § 6.1 : H1 n'utilise aucune statistique de fenêtre | **conforme.** Ma proposition C1 précédente (C.2 « statistiques locales remplacées par celles de L2 ») reposait sur une prémisse fausse ; elle est corrigée dans la nouvelle proposition. |
| § 2 : la fenêtre B0-local de la confirmation ne compte que les transports | conforme |
| **§ 2 : E_pend est « la seule différence » entre S_pub et S_true** | **écart.** L'état vrai d'un instant est cloné **avant** le pas t0. S_pub contient déjà, par instant, 0,94 demande de transport habituelle, 0,52 plan habituel et 0,38 offre de renfort publiés à t0 avec un retard nul. L4-N part de S_pub, comme prescrit, et ne corrige pas ce décalage. |

Recensement des événements en attente aux 96 instants, par instant : authorised 0,23 ;
cleaning_start 0,19 ; ready 0,18 ; cleaning_done 0,18 ; placed 0,13 ; departure 0,11 ;
transport_done 0,10 ; bed_dirty 0,09 ; request_arrival 0,07 ; transport_start 0,03 ;
transport_accepted 0,03. Les soins dus (4,96 par instant) ne changent pas l'état.

## 2. L4-N : construction (addendum A2-1) et validation

**Construction.**
- Postérieure de L4 inchangée : θ, mécanisme, régime à τ et θ_lag.
- Pour chaque élément public en cours, l'instant E de l'événement de fin est tiré selon la loi du
  générateur, puis accepté avec la probabilité d'être encore non publié à t (rejet clé, 64
  tentatives au plus).
- Arrivées non publiées : amincissement négatif binomial exact.
- Les événements en attente sont appliqués au clone de S_pub, à leur tick, par la sémantique du
  moteur. Les violations de préconditions sont comptées, jamais corrigées.
- Les décisions de l'opérateur ne sont pas antidatées.
- Code : `src/hospitalos/howm2/nowcast.py` et `a2.py`.

**Validation** (`evidence/howm2/VALIDATION_L4N.json`, registre n° 37).

**(N-c), registre n° 36 : réussi.** Dans un monde sans retard (VAL 0, `lag_min = 0`), le moteur
L4-N **est** S_pub. Les U moyens des 16 candidats sont égaux bit à bit à ceux de L4, aux 4 instants.

**(N-o) littéral : dégénéré.** La masse ponctuelle sur S_pub a une NLL infinie aux 20 instants sur
96 qui ont au moins un événement en attente. La différence vaut +∞, et l'IC calculé vaut NaN
(∞ − ∞). Ce cas était anticipé par l'addendum A2-1.

**(N-o′), Brier, sur 96 instants et 2 109 éléments publics, dont 74 en attente :**

| Système | Gain sur la masse ponctuelle (IC 95 %) | Décision |
|---|---|---|
| L4-N | +0,003 [−0,049 ; +0,051] | échec |
| L5-N (témoin privilégié) | +0,019 [−0,019 ; +0,059] | échec |

Il faudrait environ 480 instants pour détecter l'effet de L5-N, et environ 16 000 pour celui de
L4-N. Conformément à la règle pré-déclarée : arrêt, paquet `HOWM2_P2_A2_BLOCKED_VALIDATION.zip`
(sha 461eab38…), question. Décision n° 4 : « Limite du test, poursuivre ».

**(N-a) : réussi pour les 7 types**, au seuil 0,166 (n = 96).

| Type | Vrai (total) | L4-N (moyenne des tirages) | L5-N | D(L4-N) | D(L5-N) |
|---|---:|---:|---:|---:|---:|
| auth | 22 | 7,9 | 6,8 | 0,064 | 0,087 |
| ready | 17 | 10,8 | 10,3 | 0,077 | 0,153 |
| conf_transport | 3 | 2,3 | 2,2 | 0,050 | 0,093 |
| conf_offer | 0 | 0,8 | 0,7 | 0,074 | 0,071 |
| transport | 10 | 1,3 | 0,6 | 0,076 | 0,104 |
| cleaning | 17 | 4,4 | 4,3 | 0,161 | 0,133 |
| arrival | 5 | 6,5 | 6,4 | 0,064 | 0,101 |

**Lecture.** L4-N et L5-N **sous-estiment** les totaux vrais d'auth, de transport et de nettoyage.
Les événements en attente qui suivent une décision non publiée de l'opérateur sont hors de portée
par construction : par exemple, l'autorisation d'un séjour dont le placement est lui-même en attente,
ou la fin d'un nettoyage dont le début n'est pas publié. À n = 96, le KS ne le détecte pas.

Replis de l'échantillonneur : 56 sur 96 × 64 × (nombre d'éléments). Rejets de l'opérateur : 0.

## 3. A2.DEC (`evidence/howm2/DECISION_A2.json`, registres n° 41 à 43)

**Dispositif.**
- 96 instants : 48 VAL (ceux de A) et 48 neufs (HOWM2_REF 0 à 11, jour 5).
- Dispositif de A.DEC inchangé : M = 8, clés 201 à 208, OBJ-LEX-1.
- L4 et L4-N sont appariés : mêmes tirages de monde.
- Sur VAL, L4 **reproduit exactement A** : 48 instants sur 48.

| Système | U moyen (96) | VAL (48) | REF neufs (48) |
|---|---:|---:|---:|
| Habituel | 6 147,1 | 5 097,8 | 7 196,3 |
| C_param | 6 016,3 | 5 007,0 | 7 025,6 |
| C_pub_snap | 6 014,3 | 4 999,5 | 7 029,2 |
| L4 | 6 012,4 | 5 002,8 | 7 021,9 |
| **L4-N** | **6 007,3** | 4 996,9 | 7 017,7 |
| Règle renforcée | 5 960,1 | 4 974,1 | 6 946,0 |
| C_full | 5 940,1 | 4 945,2 | 6 934,9 |
| Oracle | 5 924,1 | 4 931,9 | 6 916,3 |

| Mesure | Estimation [IC 95 %] |
|---|---|
| **marge_N = U(règle) − U(L4-N), 96 instants** | **−47,2 [−81,6 ; −19,2]**, d'où `NOWCAST_MARGE_LT_15` ⚑ |
| marge_N sur VAL | −22,8 [−46,6 ; −1,5] |
| marge_N sur REF neufs | −71,6 [−127,9 ; −21,0] |
| marge de A (règle − L4) sur les 96 instants | −52,3 [−85,7 ; −25,2] |
| L4 − L4-N, apparié | +5,1 [+0,1 ; +11,1] |
| L4 − C_full | 72,3 [45,1 ; 103,8] |
| **κ** | **0,070 [0,001 ; 0,180]** ⚑ |

Autres comptes :
- choix différents entre L4 et L4-N : 8 instants sur 96 ;
- événements en attente appliqués : 0,40 par tirage ;
- replis : 10 ;
- rejets de l'opérateur : 0.

**Diagnostic secondaire, pré-déclaré** : sélection par U minimal pur, sans tolérance de 15. Il n'a
aucun effet sur le verdict.

| Mesure | Estimation [IC 95 %] |
|---|---|
| règle − L4 (min pur) | −47,0 [−81,1 ; −19,0] |
| règle − L4-N (min pur) | −32,2 [−56,9 ; −10,7] |
| C_full : OBJ-LEX-1 − min pur | +2,5 [+0,05 ; +5,8] |

OBJ-LEX-1 coûte environ 15 à L4-N et 2,5 à C_full ; il n'explique pas la défaite face à la règle.

## 4. A2.COV (`evidence/howm2/COVERAGE_A2.json`, registre n° 44, descriptif) ⚑

| H | cov90 public | cov90 L4-N | cov90 vrai | Part récupérée (cov90) | Part récupérée (cov90 hors dégénérés) |
|---:|---:|---:|---:|---:|---:|
| 1 | 0,573 | 0,580 | 0,877 | 0,02 | 0,04 |
| 6 | 0,717 | 0,715 | 0,882 | −0,01 | −0,02 |
| 24 | 0,799 | 0,795 | 0,884 | −0,04 | −0,05 |

Les départs public et vrai reproduisent `DIAG_COVERAGE.json` pour les couvertures. Les KS du PIT
diffèrent légèrement, parce que le flux aléatoire de PIT est partagé avec le départ L4-N.
Événements en attente appliqués : 0,22 par déroulé.

## 5. A2.L2C (`evidence/howm2/L2C_A2.json`, registres n° 45 à 47)

**Ajustement sur TRAIN 0–31.**
- Sous-famille transport : 903 items, τ = 0,75.
- Sous-famille offre du pool : 253 items, τ = 0,75.
- Contrôle : la confirmation L2 recalculée par ce code égale celle de l'échelle de A dans 600 cas
  sur 600.

**Confirmation sur REF, en nats.**

| H | L2 | **L2c** | L3 | L4 |
|---:|---:|---:|---:|---:|
| 1 | 1,134 | **1,096** | 0,992 | 1,016 |
| 6 | 2,878 | **2,895** | 2,584 | 2,627 |
| 24 | 3,001 | **3,022** | 2,658 | 2,702 |

À H6 et H24, la séparation dégrade la sous-famille des offres (3,69 nats à H24) : elle n'a que
253 items d'ajustement. Cela concorde avec l'annexe exploratoire du programme : séparer les types
n'explique qu'une petite part de l'écart ; l'essentiel tient à l'inférence de θ.

**M_pub, meilleure de {L2, L2c}, choix refait dans chaque réplique.**

| H | M_pub [IC 95 %] | Meilleure référence |
|---|---|---|
| 1 | 0,035 [0,031 ; 0,038] | L2c |
| 6 | 0,099 [0,087 ; 0,109] | L2 |
| 24 | 0,141 [0,121 ; 0,160] | L2 |

Aucune borne basse n'est sous δ_id à H6 ni à H24 : **pas de signalement pour C1**.

**ρ_f**, part de l'écart de A qui reste à capter :
- 1,0 pour toutes les familles à H6 et H24 ;
- 0,67 pour la confirmation à H1.

La référence corrigée ne réduit donc pas la marge identifiable aux horizons du critère. Le
verdict `HOWM1_DISCRIMINANT` de A est inchangé.

## 6. Ce que A′ permet de conclure

1. **Sur HOWM-1, l'état présent masqué par le retard de publication est un état caché réel, mais
   petit.** Il est récupérable depuis l'historique public, de manière calibrée (N-a), mais ne vaut
   qu'environ 5 minutes-soignant par décision (κ ≈ 0,07). Un world model qui l'estimerait
   parfaitement n'atteindrait pas le seuil décisionnel de 15 ; L4-N, qui l'estime au mieux à lois
   connues, ne l'atteint pas.
2. **L'écart avec C_full vient surtout d'ailleurs :**
   - décisions de l'opérateur non publiées ;
   - décalage de convention à t0 : l'état public est en avance sur l'état vrai ;
   - tirages privés.

   Aucune de ces causes n'est une cible pour un estimateur d'état appris sur HOWM-1 tel qu'il est.
3. **La marge de prévision identifiable (M_pub) est robuste** à la correction de la référence
   explicite. C1 peut garder L2 comme référence (meilleure de {L2, L2c}).
4. **La tranche B redevient nécessaire** pour une marge décisionnelle : HOWM-1 ne contient pas
   d'état caché dont dépendent les décisions au point du seuil.

## 7. Coûts (registre `BUDGET_LEDGER_HOWM2`, enveloppe A2)

| Lot | Mural (s) | Plafond (s) |
|---|---:|---:|
| A2.FACTS | 22,7 | 60 |
| A2.TEST | 16,5 | 400 |
| A2.VALID | 10,0 | 600 |
| A2.DEC | 230,0 | 900 |
| A2.COV | 11,7 | 300 |
| A2.L2C | 34,8 | 600 |
| A2.REST | 254,5 | 400 |
| **Total A2** | **580,2** | 3 600 |

**Paquets et restauration**
- Paquet de blocage : `HOWM2_P2_A2_BLOCKED_VALIDATION.zip` (sha 461eab38…), avant la décision
  n° 4.
- Paquet final : `HOWM2_P2_A2_FINAL.zip`, sha256
  `68f9f38f392dfbfc69e37e043e5f5d3fefea407f839dea744cb6068da5f95833`, commit a27c263f.
- Reçu de restauration (`evidence/howm2/RESTORE_RECEIPT_A2.json`), obtenu dans un répertoire neuf :
  - SHA256SUMS intègres ;
  - `tests/howm2` : 14 réussis ;
  - A2.DEC de VAL 0 et de HOWM2_REF 0, et score L2c de HOWM2_REF 0, régénérés à l'identique ;
  - les quatre analyses de A′ refaites à l'identique ;
  - même verdict.
- Une première tentative de reçu (registre n° 49) a échoué à tort. Ma fonction de comparaison
  jugeait +∞ ≠ +∞, sur la valeur dégénérée de (N-o). Elle est conservée dans le registre et dans
  `RESTORE_RECEIPT_A2_attempt1_false_negative.json`. La comparaison a été corrigée, puis le paquet
  refait.
