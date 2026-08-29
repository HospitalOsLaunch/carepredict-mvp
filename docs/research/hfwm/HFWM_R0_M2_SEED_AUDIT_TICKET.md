# Ticket séparé — rejeu contrôlé des fits M2

```yaml
ticket_id: HFWM-R0-M2-SEED-AUDIT
status: AUTHORIZED_NOT_STARTED
blocks_partner_document_review: false
execution_parallel_to_partner_review: allowed
training_replay_authorized: true
new_architecture_authorized: false
m2_results_modification_authorized: false
```

## Objectif

Rejouer une fois les quatre configurations M2 afin de vérifier leur déterminisme réel et
de persister séparément `configuration_hash`, `weights_hash` lorsqu'il existe,
`prediction_hash` et les versions d'environnement. Cette exécution est une réplication
d'audit ; elle ne ressuscite aucun candidat et ne modifie pas la décision M2.

## Gate

- mêmes données et configuration scientifique, labels de seed différents ;
- poids identiques et prédictions identiques attendus uniquement pour les fits déclarés
  déterministes ;
- toute variation ouvre un finding méthodologique ;
- aucune répétition de seed n'est comptée comme unité scientifique ;
- aucun résultat n'est utilisable comme preuve de robustesse avant rapport dédié.
