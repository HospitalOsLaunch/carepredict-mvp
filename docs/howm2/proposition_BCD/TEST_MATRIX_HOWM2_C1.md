# Matrice de tests HOWM2-C1 (proposée)

Tous les tests sont synthétiques. Ils s'exécutent dans le lot C.SETUP, avant tout entraînement, puis
de nouveau dans le reçu de restauration.

| ID | Objet | Condition de réussite |
|---|---|---|
| T-C01 | Espaces de clés | `HOWM2_CTRAIN`, `HOWM2_CVAL` et `HOWM2_CEVAL` sont disjoints entre eux, de G0, de `HOWM2_REF` et de `HOWM2_DIAG`. Les octets du générateur sont inchangés. |
| T-C02 | Réserve | `establishment("RESERVE_*")` lève toujours `SealedPartitionError`. |
| T-C03 | Un passage | Le chargeur de flux refuse une clé déjà consommée. Le journal est égal à [0, N) pour chaque point d'échelle. |
| T-C04 | Origines | Les partitions C1 utilisent exactement `range(24, 166, 3)`. Les cohortes et étiquettes égalent `dataset.build` sur 3 établissements. |
| T-C05 | Fenêtre longue sans fuite | Pour H1-long, toute observation entrante vérifie `available_at ≤ t`. Retirer les observations postérieures à t laisse l'entrée inchangée. |
| T-C06 | H1-long réduit à H1 | Avec un contexte tronqué à 24 h et la fenêtre locale de R1, H1-long reproduit la passe avant de H1 à 1e-6 près, poids identiques. |
| T-C07 | Référence L2 | L2 de C1 égale `howm2.ladder.l2_predict` de la tranche A sur 2 établissements. |
| T-C08 | Perte d'entraînement journalisée | Chaque évaluation écrit la perte d'entraînement et la perte CVAL par famille. |
| T-C09 | Reprise | Interruption au pas k, puis reprise : poids identiques au pas 2k et même ordre des données. |
| T-C10 | Gel F-C1 | La lecture de `HOWM2_CEVAL` est refusée avant que F-C1 soit consigné, puis refusée si le code ou les poids diffèrent de F-C1. |
| T-C11 | Transfert sans réentraînement | Le hash des poids évalués sur DIAG est égal au hash consigné dans F-C1. |
| T-C12 | Agrégation | L'agrégation C1 égale celle de A4 sur les fichiers d'échelle de A (`LADDER_A.json`). |
| T-C13 | Bootstrap | Graine déclarée ; deux exécutions identiques donnent le même IC. |
| T-C14 | Fichiers gelés | `g0check.check()` et `F1.code == corpus.code_hashes()` ; les résultats R1 et A sont inchangés (hash). |
| T-C15 | Dépôt | Aucun push, merge ou rebase : la branche distante est inchangée avant et après (lecture seule). |
| T-C16 | Disque | Les tessons du flux sont supprimés après consommation ; l'occupation maximale est mesurée et inférieure à 1 Go. |
