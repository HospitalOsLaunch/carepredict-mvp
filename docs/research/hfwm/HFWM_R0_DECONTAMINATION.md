# HFWM-R0 — protocole de décontamination

Version de pré-enregistrement : `hfwm-r0.1`. Statut des résultats :
`NOT_EXECUTED`. Ce protocole est figé avant tout entraînement principal.

## Ordre obligatoire

1. admettre uniquement les sources dont les droits sont explicitement autorisés ;
2. construire les événements point-in-time et leurs familles de corrections ;
3. calculer le hash sémantique canonique de chaque épisode ;
4. regrouper les corrections, doublons exacts et quasi-doublons ;
5. affecter ces groupes indivisibles aux partitions ;
6. appliquer le purge gap temporel ;
7. créer les fenêtres seulement après le gel du manifest de partitions ;
8. relancer l'audit sur les fenêtres et sur tout checkpoint externe exposé.

La hiérarchie est `organisation → établissement → unité → épisode → temps
→ fenêtre`. Aucun épisode, aucune famille de corrections et aucun contenu
sémantiquement identique ne peut traverser deux partitions.

## Identité sémantique

Le hash utilise JSON UTF-8 canonique, clés triées, nombres finis et SHA-256. Les
champs volatils qui peuvent être exclus doivent être déclarés avant le build ; la
liste ne peut jamais inclure un target, une action, un timestamp sémantique, une
identité d'épisode, une provenance ou une lignée.

Le quasi-doublon textuel utilise NFKC, casse Unicode repliée, tokens
alphanumériques, shingles de trois tokens et Jaccard `>= 0.92`. Un finding entre
partitions est bloquant. Le seuil ne peut pas être ajusté après observation du test.

## Fuites temporelles interdites

- une feature dont `available_at > origin_at` ;
- une correction non encore disponible à l'origine ;
- une statistique de normalisation calculée hors train ;
- une target, un proxy de target ou une action future dans les features ;
- une sélection de cohorte utilisant un outcome futur ;
- une imputation, un vocabulaire ou une calibration ajustés sur validation/test ;
- une fenêtre train et une fenêtre test issues du même épisode ;
- une exposition du test à un checkpoint externe non documenté.

## Checkpoints externes

Un checkpoint doit posséder une identité locale vérifiée, une licence, une
provenance, une description de ses données d'entraînement et un audit de
contamination. En l'absence de ces preuves, le comparateur TSFM reste
`NOT_EXECUTED`. Il n'est jamais téléchargé automatiquement.

## Verdicts

Tout chevauchement non résolu invalide le run. Un audit impossible prend l'une des
valeurs `NOT_EXECUTED`, `INSUFFICIENT_DATA`, `INCONCLUSIVE` ou
`ENVIRONMENT_BLOCKER` ; il ne devient jamais un résultat positif par défaut.

L'outil `hfwm.evaluation.decontamination` réalise l'audit exact et approché de
façon déterministe. `hfwm.evaluation.splits` construit un manifest
content-addressé avant fenêtrage.
