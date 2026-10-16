# Validation du lot 03 — registre de cohortes

Exécution locale du 15 octobre 2026. Données intégralement synthétiques.

## Périmètre vérifié

- 96 tests du nouveau socle passent : 31 du lot 01, 32 du lot 02 et 33 du lot 03.
- Les 54 tests historiques v0.4.1 passent, dont les mutations de fuite et de fusion.
- Lint du dépôt, format des 14 fichiers du socle et typage strict de 13 fichiers
  (10 modules et 3 fichiers de tests) réussis.
- Étape CLI de la CI exécutée localement : cohorte jetable de 3 jours, 8 mondes
  matérialisés avec observations et référence à 24 h, test laissé fermé.
- Cohorte annuelle générée avec le plan versionné, puis contrôle des 96 fichiers
  référencés par les 16 manifestes enfants (vérité et apprentissage).
- Les deux CI du lot 02 étaient vertes au commit parent `d56280d`.
  Les CI propres à cette PR sont consultables sur GitHub.

## Réservation et réalisation

| Ensemble | Hôpitaux | Pôles / hôpital | Unités / hôpital | Lits standard par hôpital | Mondes annuels | Réalisés |
|---|---:|---:|---:|---|---:|---:|
| Apprentissage | 2 | 2 | 4 | 90 et 102 | 4 | 4 |
| Validation | 2 | 3 | 6 | 148 et 150 | 4 | 4 |
| Test réservé | 2 | 4 | 8 | 197 et 202 | 4 | 0 |

Les lits de renfort activables ne sont pas inclus dans les lits standard.
Chaque hôpital a deux répétitions de l'année 2025, avec des graines distinctes ;
les paramètres hospitaliers sont identiques entre ses répétitions.
Les structures et établissements sont disjoints entre partitions.
Le test n'a produit ni trajectoires ni scores.

## Volumes effectivement produits

| Mesure | Valeur |
|---|---:|
| Mondes annuels matérialisés | 8 |
| Établissements matérialisés | 4 |
| Heures d'hôpital enregistrées | 70 080 |
| Heures d'hôpital contrôlées, chauffe comprise | 81 792 |
| Lignes unité-heure de vérité | 350 400 |
| Événements de vérité, chauffe comprise | 1 428 205 |
| Livraisons d'observation | 412 816 |
| Lignes de variables aux trois niveaux | 595 680 |
| Lignes de cibles, censures comprises | 595 680 |
| Violations des invariants de lits et de flux | 0 |

L'export complet local représente environ 335 Mio. Les fichiers volumineux
peuvent être régénérés avec le code, le plan et les versions du manifeste.
Les empreintes et configurations sont versionnées ici ; aucun fichier patient
réel n'a été utilisé.

## Référence de persistance

La préparation calcule la même référence à 24 h que le lot 02, sans apprentissage.
Pour les lits occupés à l'hôpital, les MAE individuelles vont de **4,4675 à
4,7837 lits** dans l'apprentissage et de **6,1028 à 6,4378 lits** dans la validation.
Les tailles d'hôpital diffèrent : ces erreurs brutes ne mesurent pas, à elles
seules, une perte de généralisation. Aucun réglage n'a été sélectionné sur ces
résultats et aucun résultat de test n'est disponible.

Les mesures détaillées par monde, les erreurs par cible et niveau, la couverture
hospitalière et la qualité des observations figurent dans
[lot03_reference_metrics.json](lot03_reference_metrics.json).

## Preuves versionnées

- [lot03_registry.json](lot03_registry.json) : plan et configurations des 12 mondes.
- [lot03_registry_manifest.json](lot03_registry_manifest.json) : empreintes du
  registre, sources et versions d'exécution.
- [lot03_annual_manifest.json](lot03_annual_manifest.json) : 8 exécutions,
  empreintes des manifestes enfants et 4 mondes réservés.
- [lot03_reference_metrics.json](lot03_reference_metrics.json) : totaux audités et
  référence descriptive sur apprentissage/validation.

La reproductibilité octet pour octet est testée sur une cohorte courte complète,
incluant les observations, cibles et scores. La cohorte annuelle a été exécutée
une fois ; ses fichiers ont ensuite été vérifiés par empreintes.

## Ce que ce lot ne démontre pas

Une seule famille physique `v041` est utilisée. Le protocole de réservation de
mécanismes refuse de présenter cette famille partagée comme un test G4.
Une seule structure par partition ne constitue pas une campagne statistique de
généralisation. Les paramètres sont des plages d'ingénierie non calibrées, les
politiques locales restent à implémenter et les notes/trajectoires patient ne
sont pas encore des entrées du pipeline d'apprentissage.

GEN-003 est livré pour le registre, les cohortes et la réservation des structures.
La réservation effective de mécanismes inédits dépend de GEN-004 ; aucune porte
G1–G4 ou SYN n'est déclarée franchie.
