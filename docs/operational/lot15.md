# Lot 15 — contrat commun et première expérience d'entraînement

Cette livraison exécute les deux étapes acceptées après la revue du 15 octobre :
une interface indépendante du simulateur, puis une première expérience sur le
générateur hospitalier relu. Les corrections du validateur Nantes sont dans la
[PR #18](https://github.com/HospitalOsLaunch/carepredict-mvp/pull/18), basée sur #2.
Ce lot se base sur #17 et ne fusionne aucune PR historique.

## Livré

- Contrat de topologie et d'observations datées, valeurs manquantes explicites,
  unités de mesure séparées, instants normalisés et consommateur as-of commun.
- Export des livraisons synthétiques en flux unité, pôle ou établissement ; une
  frontière mixte non superposée est également supportée par le convertisseur.
- Petit réseau de 6 755 paramètres partageant ses poids entre nœuds, utilisant
  l'historique, les voisins de même parent et le contexte moyen du périmètre.
- Prévisions des moyennes à 24 h pour occupation, file d'urgence et proxy de
  charge ; sommes cohérentes au sein d'une même frontière d'observation.
- Persistance, référence à la même heure quotidienne et climatologie ajustée
  uniquement sur entraînement ; tous les points planifiés restent dans le score.
- Protocole, partitions, poids et rapport complets conservés dans les preuves.

Voir [l'ADR](ADR-OP-0001-common-interface.md) pour les définitions, le rôle des
domaines patients optionnels, les limites du contrat et la coexistence avec v1.

## Exécuter

Environnement léger : Python 3.11, NumPy, pandas, Pydantic et PyTorch CPU 2.4.1.
La CI dédiée installe ces dépendances sans exiger le reste de la plateforme.

```bash
# Un export commun à partir d'un monde de développement existant.
PYTHONPATH=src python -m hospitalos.operational.adapter \
  --source runs/synthetic/lot14/ght600-medical-scope \
  --output runs/operational/ght600-observed

# Préparer les 12 mondes d'entraînement et 6 de validation, sans générer le test.
PYTHONPATH=src python -m hospitalos.operational.experiment prepare \
  --plan configs/operational/experiment_v1.json \
  --output runs/operational/lot15/cohort

# Un entraînement, poids figés, puis ouverture des cibles de validation.
PYTHONPATH=src python -m hospitalos.operational.experiment run \
  --cohort runs/operational/lot15/cohort \
  --output runs/operational/lot15/result
```

Les sorties doivent être nouvelles et sont publiées atomiquement. Les poids sont
rechargeables avec `hospitalos.operational.forecast.load_frozen_model` depuis un
répertoire contenant `model.pt` et `model_config.json`. La fonction vérifie leur
empreinte et la définition des variables, et charge seulement le dictionnaire de
tenseurs. `predict(model, inputs)` ne reçoit aucun fichier de vérité.

## Vérification

30 tests opérationnels couvrent schéma fermé, fuseaux, versions, observations
futures, données manquantes, agrégats, frontières mixtes, absence de détails fins,
invariance par permutation, nouveaux nombres de nœuds, rechargement exact des
poids et gel des prévisions avant ouverture des cibles. S'y ajoutent les 457 tests
du socle et 54 régressions historiques, soit 541 tests locaux du lot 15.
Les 49 tests du correctif de validateur sont vérifiés sur la branche dédiée.

Les [résultats](evidence/lot15/results.md) montrent un gain de MSE dans cette
campagne face aux trois références retenues. Il reste à comparer au gradient
boosting et à une référence lissée, puis à tester la contribution du contexte entre
unités par ablation. Aucune sélection de paramètres sur ces résultats n'est faite.

## Non établi

RS-JEPA utilise encore son ancien simulateur dans son chemin historique. La
nouvelle expérience est une référence neuronale sur le corpus relu, pas un
entraînement JEPA/RSSM ni un remplacement validé du modèle existant. Les prévisions
multi-pas, intervalles conjoints, causalité et adaptation restent à développer.

Les six sites de validation ont des tailles inédites mais les mêmes quatre
gabarits médicaux et les mêmes mois. Les mondes restent indépendants, sans aval
territorial partagé. Le biais de mortalité signalé et le calendrier physique
UTC+01 fixe restent des limites du moteur ; le contrat ne les corrige pas.
La campagne n'a produit aucune origine avec observation absente ou périmée de plus
de 6 h : elle ne démontre pas une résistance aux longues pannes. Elle n'établit
ni réalisme clinique, ni transfert au réel, ni passage d'une porte G1–G4/SYN.

## Suite

Avant toute revendication de modèle de monde hospitalier : corriger les hypothèses
de moteur identifiées, introduire l'aval contraint et ses ressources concurrentes,
compléter les références de prévision et l'évaluation des pannes. Étendre ensuite
aux territoires, topologies, types d'unités et dynamiques apprises, avec des
expériences comparables à chaque étape. Les premières données réelles restent
après la porte SYN ; le calendrier global n'est pas avancé par cette preuve.
