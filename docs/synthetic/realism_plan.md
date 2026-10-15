# Plan accepté — cible médecine/gériatrie et aval contraint

Décision de Guy du 15 octobre 2026 : poursuivre sur synthétique exclusivement,
en solo avec Codex, avec le CH support de GHT à activité MCO comme cible prioritaire.
La taille 300–1 200 lits décrit un segment commercial ; préciser la capacité MCO,
la capacité totale et le périmètre effectivement simulé dans chaque expérience.
Le développement ne dépend pas de l'arrivée d'une extraction réelle ; les dossiers
individuels restent après SYN. Ce plan ne redate pas la cible globale provisoire
du 19 novembre 2027 et ne ferme aucune porte de recherche.

## Séquence et critères

| Lot | Livrable | Critères avant passage au suivant |
|---|---|---|
| 14 — mesures fiables | Scorecard, référentiel provisoire, scénario médical GHT-600 importé | Comptabilité des présences et files réconciliée ; séjours ouverts et non-admis visibles ; pas de seuil empirique non justifié |
| 15 — scénario gériatrie/aval | Ressources d'aval finies et hypothèses typées par configuration | Départ effectivement empêché sans capacité compatible ; ressources conservées ; demandes et décisions tracées ; annulation/restitution vérifiées |
| 16 — benchmark v2 | Références quotidiennes et climatologiques, populations/estimands/splits corrigés | Protocole gelé avant résultats ; apprentissage non privilégié ; scores et couverture par tension ; cohortes et incertitude au niveau établissement |
| 17 — première dynamique apprise | Une expérience de prévision et déroulement multi-pas face aux références | Même information disponible et mêmes mondes ; poids figés sur validation ; résultats négatifs publiés ; aucun transfert réel ni effet causal déclaré acquis |

## Lot 15 : modèle opérationnel à construire

1. Porter seulement les hypothèses retenues du prototype dans un bloc typé,
   versionné et empreinté. Ne pas modifier les dictionnaires ou méthodes globaux.
   Conserver la variante historique pour les régressions. Revoir chaque valeur
   avant de la qualifier de calibrée, notamment effectifs et destinations.
2. Représenter SMR et EHPAD par capacités, compatibilités et durées d'occupation.
   HAD et aide à domicile nécessitent des capacités de prise en charge distinctes,
   pas une assimilation automatique à des lits. Prévoir de la demande extérieure
   au pôle pour partager réellement les ressources territoriales.
3. Séparer préparation du dossier, envoi, acceptation/refus, réservation, départ
   et annulation ; dater les faits et leur disponibilité documentaire. La
   disponibilité médicale peut évoluer et les réservations doivent être libérées.
4. Relier le départ physique à une capacité effectivement disponible. Tester depuis
   un état commun un aval disponible puis indisponible, à demandes/politique fixées.
   Vérifier la propagation aux autres unités et aux urgences du périmètre.
5. Remplacer les effets d'action imposés en pourcentage par des mécanismes
   explicites, par exemple préparation anticipée d'un dossier avec coût de tâche.
   La conservation des places impose de mesurer les effets sur tous les patients,
   pas seulement le patient priorisé.
6. Conserver des régimes fluides, tendus et de crise. Les paramètres de tension
   sont des hypothèses de scénario jusqu'à validation, pas des normes nationales.

La première implémentation peut se limiter au SMR avec files finies, à condition
que l'EHPAD, l'HAD et la coordination restent explicitement marqués non livrés.
Le profil GHT-600 actuel simule uniquement 250 lits de médecine. La représentation
agrégée active du reste de l'établissement et sa demande concurrente sont à construire.

## Lot 16 : corrections de l'évaluation

- Ajouter une référence quotidienne à heure cible identique, avec information
  disponible à la date de décision, ainsi qu'une climatologie ajustée sur train.
- Définir l'estimand : médiane pour MAE, moyenne pour les scores appropriés de
  comptage, distribution pour pinball multi-quantiles/CRPS. La MAE n'est pas fausse,
  mais une médiane nulle ne mesure pas la capacité à anticiper une tension.
- Ne pas interpréter la somme des médianes comme la médiane de l'hôpital. Évaluer
  les agrégats directement ou construire une distribution jointe cohérente.
- Déclarer une population observable avant apprentissage ; montrer erreurs sur
  présences fantômes, couverture, résultats en tension et comportement en panne.
  Un score sur les seules heures fraîches n'est pas une performance de service.
- Utiliser plusieurs familles non privilégiées à l'apprentissage, réserver des
  familles et structures, séparer décalage de niveau et changement de mécanisme.
  Les familles documentaires privilégiées servent seulement de contrôle de fuite.
- Choisir le nombre de sites et répétitions selon la précision recherchée ; les
  30 sites/quatre familles proposés dans la revue ne sont pas des seuils universels.
  Une graine supplémentaire n'est pas un établissement supplémentaire.
- Tester le calendrier, les épisodes saisonniers et l'influence indirecte des
  informations futures du cadre. Les variations de calendrier et de politique
  doivent être distinctes de l'évaluation finale réservée.

## Lot 17 : première expérience du modèle

Choisir et figer l'architecture minimale, les entrées observées, les horizons,
les références et la population avant l'entraînement. Comparer diversité faible
et diversité accrue sans changer simultanément tous les autres facteurs.
Une bonne prévision à 24 h ne démontre ni dynamique multi-pas, ni couplage
patients/ressources, ni identification causale des actions. Ces capacités auront
leurs preuves séparées avant d'être présentées comme un world model hospitalier
complet. Les premiers résultats utilisent la validation, sans ouvrir les tests finaux.

## Travaux conservés et limites

- Erreurs silencieuses des recensements : chantier initialement proposé comme
  lot 14, conservé avant la campagne finale de robustesse de la branche patient.
- Bugs signalés dans la PR #2 : correctifs distincts à reproduire et vérifier ;
  cette livraison ne certifie ni leur correction ni la PR.
- Temps de coordination : instrumentation de tâches à construire ; pas de gain
  converti en minutes à partir des seuls messages.
- Validité externe : plages publiques comparables, cas métier revus par des
  professionnels puis, après SYN, évaluation réelle indépendante.
- Les revues et nouveaux scénarios ne constituent pas une autorisation de fusion
  des PR historiques. Les livraisons restent soumises à leur revue habituelle.
