# Robustesse du délai de préparation : régimes synthétiques réservés

Statut : diagnostic synthétique, 24 octobre 2026. Il complète le test temporel
du premier modèle, qui partageait son mécanisme avec l'entraînement.

## Question testée

Un modèle peut battre une référence sur une période ultérieure et échouer quand
le processus change. Cette suite évalue le modèle déjà sélectionné, sans
réentraînement, recalibrage ni sélection à partir des nouveaux résultats.

`stress_preparation.py` définit cinq régimes, trois graines fixes (101, 202, 303)
et 200 patients par paire régime/graine, soit 3 000 trajectoires synthétiques.
Les origines sont postérieures à la disponibilité du modèle. Chaque modèle est
noté sur les mêmes patients et mêmes réalisations de chaque cas.

| Régime | Modification | Question |
|---|---|---|
| Référence, nouvelles graines | Mécanisme inchangé | Le comportement se reproduit-il ? |
| Préparation ralentie | Logit du risque diminué de 1 | Résistance à une dérive globale |
| Effet de charge modifié | Signe de l'effet de charge inversé | Dépendance à une association apprise |
| Censure informative | Suivi écourté selon le futur délai latent | Limites des scores pondérés |
| Charge hors support | Ratios supérieurs au maximum d'entraînement | Refus de l'extrapolation |

L'inversion du signe est un stress construit, pas une fréquence estimée dans les
hôpitaux. Elle représente un mécanisme où la même charge n'a plus la même relation
au délai, par exemple après une adaptation organisationnelle. Les valeurs numériques
ne sont pas une mesure de cet exemple métier.

## Trois frontières à conserver

1. Le modèle est verrouillé avant le stress. `train_demo` n'accède pas à ces cas ;
   la suite ne modifie ni ses paramètres ni son identité.
2. La vérité complète du générateur est séparée des variables et des labels
   observés. Elle sert seulement de référence d'évaluation dans cette simulation.
3. Les cas hors plage de charge ou établissement/unité d'entraînement sont comptés
   comme abstentions, avec le même contrôle `HazardModel.supports` qu'en prévision.
   Aucun score sur les prédictions refusées n'est présenté comme performance servie.

La NLL sur vérité complète inclut les événements jusqu'à 24 h et la masse restante
au-delà. Elle n'est pas directement comparable à la NLL précédente sur suivi
partiellement censuré. Les Brier aux quatre horizons sont aussi disponibles
dans le résultat programmatique détaillé.

Pour les régimes à censure indépendante inchangée, la suite calcule également
les scores observés avec la distribution de censure estimée à l'entraînement.
Pour la censure informative, elle supprime ces scores IPCW et expose uniquement
la référence synthétique complète. Connaître le mécanisme de censure de la fixture
permet ce contrôle ; la détecter sur un flux réel reste un problème distinct.

## Lecture du premier essai

Le modèle conserve un avantage sur les nouvelles graines et le ralentissement
global. Il devient moins bon que la référence sans covariables sur les trois
graines du régime où l'effet de charge est modifié. La suite émet donc
`not_robust_to_all_reserved_regimes`.

Les cas de ce régime passent tous le contrôle de plage : une dérive du mécanisme
peut survenir sans variable hors support. Un contrôle de bornes ne suffit donc
pas à autoriser l'usage opérationnel. Les 600 cas hors plage sont, eux, refusés.
La suite ne corrige pas le modèle après ce constat et ne choisit pas a posteriori
une politique par régime. Une future modification doit utiliser un jeu de
développement distinct puis un nouveau test réservé.

Ce résultat laisse le modèle dans son périmètre synthétique optionnel. Il ne
fournit ni seuil de déploiement hospitalier, ni confiance statistique, ni passage
de G1/G2. La comparaison porte sur un petit ensemble de mécanismes écrits à la
main, pas sur toute la diversité des organisations hospitalières.

## Conséquence pour le pilote

Avant un usage réel : confirmer la cible avec le
[contrat d'événements](preparation-endpoint-protocol.md), mesurer les erreurs et
la calibration par service/période, examiner les changements de processus et
prévoir une règle de suspension ou de repli définie avant le test. Les erreurs
ne deviennent observables qu'après suivi et disponibilité des labels ; aucune
détection instantanée d'un changement caché n'est revendiquée.

Le prototype conserve la préparation sous hypothèses sans prévision fournie.
Un repli opérationnel ne peut pas être déclenché automatiquement à partir du
nom de régime du générateur : cette vérité n'existe pas dans un hôpital réel.

## Reproduire

```bash
PYTHONPATH=src python -m hospitalos.hybrid.stress_preparation
PYTHONPATH=src:. pytest -q tests/hybrid/test_stress_preparation.py
```

La commande imprime le diagnostic agrégé. Aucun dataset, rapport généré ou modèle
sérialisé n'est ajouté au dépôt. Les tests contrôlent la séparation des vérités,
l'abstention, la suppression d'IPCW invalide et l'absence de réentraînement ; ils
n'imposent pas que le modèle gagne artificiellement tous les cas.
