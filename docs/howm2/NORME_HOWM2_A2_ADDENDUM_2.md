# NORME HOWM2-A′ — Addendum A2-2 (décision n° 4 de l'utilisateur)

Consigné **avant** toute mesure A2.DEC, A2.COV et A2.L2C.

## Contexte : arrêt à la validation de L4-N

Registre n° 38, paquet `HOWM2_P2_A2_BLOCKED_VALIDATION.zip`, sha256 461eab38…64ee0e2.

| Contrôle | Résultat |
|---|---|
| (N-c) | réussi : identité bit à bit dans un monde sans retard |
| (N-a) | réussi pour les 7 types |
| (N-o) littéral | dégénéré : +∞, car la masse ponctuelle sur S_pub a une NLL infinie à 20 instants sur 96 |
| (N-o′) Brier, L4-N | +0,003 [−0,049 ; +0,051] : échec |
| (N-o′) Brier, témoin privilégié L5-N | +0,019 [−0,019 ; +0,059] : échec |

Le test n'a pas de puissance : 96 instants, 74 événements en attente sur 2 109 éléments. Il
faudrait environ 480 instants pour détecter l'effet de L5-N, et environ 16 000 pour celui de L4-N.

## Question posée et réponse

Question posée à l'utilisateur, avec ses options : limite du test et poursuite, validation
élargie, ou arrêt de A′.

Réponse : **« Limite du test, poursuivre »**.

## Règle appliquée

- L'échec de (N-o′) est traité comme une **limite du test**, et non comme un échec de L4-N, parce
  que le témoin privilégié L5-N échoue aussi. C'est la règle déjà appliquée à (N-a) et, dans A, à
  l'addendum 2.
- Cette limite est signalée dans **chaque verdict** de A′ qui utilise L4-N : A2.DEC, κ et A2.COV.
- Aucun seuil, aucune population et aucun verdict n'est modifié.
- Le verdict A2.DEC (`NOWCAST_*`) reste celui de la norme A2 § N3, appliqué tel quel.
