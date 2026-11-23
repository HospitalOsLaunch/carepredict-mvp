# PLAN48 — amendement A1 (23 novembre 2026), avant toute lecture TEST

Le protocole `PLAN48_A` a été gelé le 20 novembre (commit 519220f) avec une sélection DEV
(`evidence/plan48/selection.json`, `dev_headroom.json`). Aucun résultat TEST n'existe.

## Défauts corrigés

1. **Tirages de projection partagés entre hôpitaux** (`sim.public_forecast`). La clé aléatoire de la
   projection publique ne dépendait que de (tick, tirage) : tous les hôpitaux, partis de la même
   origine de 56 h, utilisaient les mêmes innovations. Les erreurs de la référence « simulation »
   étaient donc corrélées entre hôpitaux, alors que le bootstrap de `evaluate.compare` les traite
   comme indépendants. La clé inclut maintenant `spec.part` et `spec.idx`.
2. **Reconstruction publique** (`src/hospitalos/howmint/world.py`, `PublicStreamN.to_engine_n`).
   Un séjour dont la fin de transport (ou, sans transport, la mise en état de sortie) est publique
   mais dont le départ ne l'est pas encore gardait son lit pendant toute la projection ; il quitte
   désormais son lit au moment impliqué. Les transports inférés reçoivent aussi leur demande, ce
   qui évite une seconde demande habituelle.

## Conséquence

La sélection DEV gelée a été calculée avec le code antérieur. Elle **doit être recalculée** avec le
code corrigé avant toute lecture TEST ; la règle de sélection, les tailles de partition, les graines
et les critères du protocole sont inchangés. Les fichiers actuels de `evidence/plan48` restent
conservés comme trace de la sélection initiale.
