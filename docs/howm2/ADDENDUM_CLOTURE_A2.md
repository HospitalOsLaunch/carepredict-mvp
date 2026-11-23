# HOWM-2 — Addendum scientifique de clôture de A′

**Date :** 16 novembre 2026.
**Décision :** n° 5 (`docs/howm2/HOWM2_DECISION_5.json`).
**Rapport concerné :** `docs/howm2/RAPPORT_HOWM2_A2.md`, sha256
`9de8ce53cdaad12dfac22efa6e01b83c11daf2400c6045b242031925b8632f4d`.

**Paquet historique :** `HOWM2_P2_A2_FINAL.zip`, sha256 68f9f38f…95833.

**Statut de cet addendum.**
- Il **ne modifie ni les résultats, ni les normes, ni les paquets, ni les reçus, ni les verdicts**
  de A′. Le rapport historique reste inchangé.
- Il corrige des **interprétations** de ce rapport et de la proposition qui l'accompagne
  (`proposition_A2/`).
- Aucune nouvelle expérience, aucun nouveau calcul et aucun diagnostic décisionnel n'a été fait
  pour le rédiger. Les chiffres cités viennent tous des fichiers livrés.

Verdict historique, inchangé : **`NOWCAST_MARGE_LT_15`**.

Statuts inchangés : `PROTOTYPE_UNVALIDATED`, `clinical_validation=false`, `G2=NO-GO`.

---

## a) Portée du résultat négatif

**Observations** (`evidence/howm2/DECISION_A2.json`) :
- Dans le protocole testé, L4-N reste moins performant que la règle renforcée : marge = U(règle) −
  U(L4-N) = **−47,2 [−81,6 ; −19,2]** sur 96 instants, avec un bootstrap à 24 grappes.
- La sélection par U minimal pur ne renverse pas ce résultat : −32,2 [−56,9 ; −10,7].

**Interprétation corrigée.**
- A′ **ne démontre pas** qu'un estimateur parfait des événements en attente, ni tout autre
  estimateur appris, resterait nécessairement sous le seuil décisionnel de 15.
- **Aucune borne supérieure** de ce type n'a été mesurée.
- Le rapport affirmait (§ 6.1) qu'« un world model qui l'estimerait parfaitement n'atteindrait pas
  le seuil décisionnel de 15 ». **Cette phrase est retirée** : elle ne repose sur aucune mesure.
  - L5-N, le témoin privilégié, n'a pas été utilisé comme planificateur.
  - Aucune expérience n'a borné la valeur décisionnelle d'une estimation exacte de l'état présent.

## b) Calibration

N-a est réussi selon le test et le seuil prévus. Ce résultat ne suffit pas à établir une
calibration satisfaisante, compte tenu des sous-estimations observées et de la limite de
validation N-o′.

**Écarts documentés** (`evidence/howm2/VALIDATION_L4N.json`), en totaux sur 96 instants :

| Type | Vrai | L4-N (moyenne des tirages) | L5-N |
|---|---:|---:|---:|
| autorisations | 22 | 7,9 | 6,8 |
| transports | 10 | 1,3 | 0,6 |
| nettoyages | 17 | 4,4 | 4,3 |

**Formulations corrigées.**
- L'expression du rapport « récupérable depuis l'historique public, de manière calibrée (N-a) »
  (§ 6.1) est remplacée par : « en partie récupérable ; N-a est réussi, mais les totaux sont
  nettement sous-estimés et N-o′ n'est pas concluant ».
- L4-N **n'est pas** un estimateur optimal. Ses limites sont documentées dans l'addendum A2-1 :
  - décisions de l'opérateur non antidatées ;
  - aucun élément pour les entités elles-mêmes non publiées ;
  - repli en cas d'échec du rejet ;
  - régime passé fixé à celui de τ.
- L5-N **n'est pas** un oracle exact de l'état caché. Son caractère privilégié (θ, retard et
  régimes vrais) ne supprime pas les limites de sa construction : il sous-estime les mêmes totaux.

## c) Interprétation de κ

**Définition.** κ = 0,07 [0,001 ; 0,18] est la fraction du différentiel U(L4) − U(C_full)
récupérée par L4-N **dans ce dispositif** : mêmes tirages de monde, mêmes déroulés, OBJ-LEX-1,
M = 8.

**Ce que κ n'est pas :**
- une limite fondamentale de l'information publique ;
- une mesure isolée de la valeur de tous les événements en attente : seuls certains types sont
  modélisés, et les décisions de l'opérateur ne le sont pas ;
- une quantité directement comparable au seuil décisionnel de 15 : κ est un rapport sans unité.

**Valeur associée.** Le gain décisionnel associé est **+5,1 [+0,1 ; +11,1]**, dans l'unité de U.

**Formulations retirées** (rapport, § 0 et § 6.1 ; proposition, « Justification par κ ») :
« Le récupérer ne vaut qu'environ 5 minutes-soignant » et « ne vaut qu'environ 5 minutes-soignant
par décision ». Elles sont remplacées par : « le gain mesuré de L4-N sur L4 dans ce dispositif est
de +5,1 unités de U ».

## d) Attribution de l'écart

**Observations.**
- Écart L4 − C_full = 72,3 [45,1 ; 103,8], sur 96 instants.
- Le recensement des faits (`FACTS_CHECK_A2.json`) identifie trois différences entre le
  dispositif public et C_full :
  - décisions de l'opérateur non publiées ;
  - décalage à t0 : S_pub contient des événements de t0 publiés avec un retard nul, absents de
    l'état vrai cloné avant le pas t0 ;
  - tirages privés.

**Ce qui n'a pas été mesuré.** Les contributions respectives de ces trois différences n'ont **pas**
été isolées.

**Formulations corrigées.** Les affirmations suivantes sont retirées :
- « L'écart avec C_full vient surtout d'ailleurs » (rapport § 6.2 ; proposition) ;
- « surtout hors état caché » (`proposition_A2/B/DESIGN_B.md`) ;
- « Aucune de ces causes n'est une cible pour un estimateur d'état appris sur HOWM-1 » (rapport
  § 6.2) ;
- « Aucune de ces causes ne se prête à un estimateur appris » (proposition).

Elles sont remplacées par : « ces différences sont identifiées entre les dispositifs ; leur part
dans l'écart et leur estimabilité depuis l'historique public n'ont pas été mesurées ».

## e) Concurrent pertinent

**Observation.** C_full bat la règle renforcée de **20,0** en moyenne sur les valeurs rapportées
(5 960,1 − 5 940,1, sur 96 instants).

**Limites.**
- Cette différence est **descriptive**.
- Les pièces examinées ne contiennent pas de démonstration propre de sa robustesse après
  correction de la convention à t0.
- Aucun intervalle de confiance n'est calculé ici : il ne peut pas l'être honnêtement à partir des
  seuls agrégats, et aucun nouveau diagnostic décisionnel sur HOWM-1 n'est autorisé.

---

## Conclusion corrigée

« A′ ne démontre pas de marge décisionnelle suffisante avec L4-N sur HOWM-1. Elle ne permet pas de
borner la performance d'un estimateur optimal ni d'exclure toute autre information exploitable. »

**Formulation retirée.** Le point 4 du § 6 du rapport affirmait : « La tranche B redevient
nécessaire […] HOWM-1 ne contient pas d'état caché dont dépendent les décisions au point du
seuil ». Il est remplacé par : « A′ n'a pas mis en évidence, sur HOWM-1, d'état caché dont la
récupération par L4-N franchisse le seuil ; la tranche B est une voie pour construire un tel état,
non une conséquence démontrée ».

**Inchangé.** La conclusion sur la marge de **prévision** (A2.L2C : M_pub inchangé avec la
meilleure de {L2, L2c}) reste un résultat mesuré.
