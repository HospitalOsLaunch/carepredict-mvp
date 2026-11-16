# HOWM-2 — Proposition bornée après la tranche A′ (rédigée, non exécutée)

Statut : **proposition**. Rien n'est lancé sans accord adopté. Statuts inchangés :
`PROTOTYPE_UNVALIDATED`, `clinical_validation=false`, `G2=NO-GO`.

## Verdict de A′ et ce qu'il impose (§ 5 du programme A′)

Verdict A2.DEC : **`NOWCAST_MARGE_LT_15`**. La ligne correspondante du tableau du § 5 prescrit :
**« C1 amendé (§ 6) et proposition séparée de B, avec la mesure de κ comme justification »**.
HOWM2-N n'est pas proposé.

Les deux volets sont **indépendants**, chacun avec son propre texte d'accord :

| Volet | Question | Entraînement | Documents |
|---|---|---|---|
| **C1 amendé** | Un réseau appris capte-t-il la marge de **prévision** identifiable de HOWM-1 (M_pub = 0,099 à H6 et 0,141 à H24) ? | oui | `C1_AMENDE/` |
| **B** | Peut-on construire un monde où l'état caché pèse sur la **décision**, ce que HOWM-1 ne permet pas (κ ≈ 0,07) ? | non | `B/` |

Il est possible d'adopter les deux, l'un des deux, ou aucun.

## Justification par κ

Sur HOWM-1, aucun des deux états cachés mesurés ne pèse sur la décision :
- **régime m2** : non récupérable (π ≤ 0, tranche A) ;
- **état présent masqué par le retard de publication** : récupérable et calibré, mais rare (environ
  1,3 événement en attente par instant). Il ne vaut qu'environ 5 minutes-soignant : κ = 0,07
  [0,001 ; 0,18], loin du seuil de 15.

L'écart d'environ 72 entre C_full et les planificateurs publics vient surtout :
- de décisions de l'opérateur non publiées ;
- d'un décalage de convention à t0 : l'état public est en avance sur l'état vrai ;
- de tirages privés.

Aucune de ces causes ne se prête à un estimateur appris. Une marge **décisionnelle** pour un world
model exige donc un autre monde : c'est la tranche B.

La marge de **prévision**, elle, existe sur HOWM-1 et résiste à la correction de la référence
(A2.L2C). C1 reste donc pertinent sur HOWM-1, pour la prévision seulement.

## Ce qui n'est pas proposé

HOWM2-N ; le diagnostic décisionnel sur HOWM-1 ; 100 000 établissements ; GPU ; réserve ; JEPA ;
boucle fermée ; P6 ; AJ-H ; push, merge, rebase.
