# Lot 08 — vérifications et scénarios annuels

Exécution locale du 15 octobre 2026. Données exclusivement synthétiques, partition de développement. Aucun entraînement, aucun benchmark d'adaptation, aucun test final ouvert.

- **254 tests du socle**, dont 35 nouveaux, et **54 tests historiques** passent : **308 tests** au total.
- Ruff, format et typage strict réussis (26 fichiers typés ; 28 fichiers formatés, script de diagnostic compris).
- Six simulations annuelles : référence et quatre ruptures pour chacune des trois organisations de ressources.
- Une année supplémentaire avec la politique à règles limitée aux observations.
- Chaque année comporte 365 jours enregistrés après 61 jours de chauffe, 2 pôles et 4 unités : **71 568 heures vérifiées sans violation des contraintes contrôlées**.
- **59 empreintes de fichiers vérifiées** : 43 sur les six générations et 16 sur la boucle observée. Les sources et le script correspondent aux empreintes du rapport.

## Non-anticipation

Sur les trois paires annuelles, tous les états, événements et décisions historiques avant la première rupture, le 1er avril à 07 h (heure relative 2167), sont identiques. La comparaison inclut également les 1464 heures de chauffe, soit 3631 heures de passé vérifiées par paire.

Les fixtures supplémentaires vérifient l'égalité des observations reçues, valeurs, masques et provenance, ainsi que des recommandations à règles jusqu'à la frontière de début. Les identifiants d'exécution dépendent de la configuration et sont exclus de la comparaison sémantique.

## Ruptures du scénario annuel

| Changement | Début, UTC+01 fixe | Fin | Portée |
|---|---|---|---|
| 8 lits standards supplémentaires demandés fermés | 1er avril, 07 h | 29 avril, 07 h | U_MED |
| Capacité imagerie multipliée par 0 | 1er juin, 09 h | 4 juin, 09 h | Hôpital |
| 2 absents supplémentaires par poste | 1er octobre, 07 h | 15 octobre, 07 h | U_GER |
| Capacité transport multipliée par 0,5, arrondie vers le bas | 1er novembre, 09 h | Fin de période | Hôpital |

Chaque réalisation perturbée produit **7 événements de frontière** : quatre débuts et trois fins. La dernière rupture reste active à la borne ; aucune fin future n'est exportée. Les tâches en cours se terminent, les patients des lits concernés ne sont pas expulsés et les files ne sont pas effacées à la restauration des capacités.

## Boucle sur observations

L'année avec la politique à règles produit 61 320 lignes de variables, 41 313 livraisons reçues, 365 contextes de décision et 5 840 lignes unité–jour–levier. Le rejeu des livraisons reproduit exactement les variables présentées en ligne. Les contrôles physiques sont tous à zéro hors compteur d'heures.

Ces résultats vérifient l'implémentation. Ils ne démontrent aucune adaptation de poids, détection de dérive, amélioration prédictive ou efficacité organisationnelle. Les horaires des postes et l'information privilégiée du cadre sont hérités ; les mécanismes ne sont pas calibrés sur le réel.

Reproduction : `PYTHONPATH=src python scripts/validate_synthetic_changes.py --output runs/synthetic/lot08/diagnostics` dans un répertoire neuf. Voir [le rapport et ses empreintes](lot08_validation.json) et [le contrat détaillé](../lot08.md).
