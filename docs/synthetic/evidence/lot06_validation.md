# Vérification exécutée — lot 06

Exécution locale du 15 octobre 2026. Politique `observed_rules` version 1 sur
l'hôpital H_SYN_001, graine 41, 2 pôles et 4 unités. Une réalisation de 2025,
après 61 jours de chauffe sous la politique historique commune. Aucune donnée
réelle ni trajectoire d'un registre de test n'a été utilisée.

## Contrôles

- **185 tests du socle** passent, dont **35 nouveaux**, ainsi que **54 tests historiques**.
- Lint de tout le dépôt, format et typage strict du socle réussis (22 fichiers typés).
- Adaptateur d'observation comparé au code publié du lot 05 : livraisons identiques
  sur tous les types d'événements de la fixture, y compris les corrections/doublons.
- États en direct comparés au rejeu publié du lot 05 et au rejeu courant ; anciennes
  trajectoires physiques toujours comparées au moteur publié du lot 03.
- Tests de livraison future, contexte immuable, probabilité invalide, mauvaise
  heure/version/unité, doublon et omission : refus avant application.
- Retry identique sans nouvelle application ; décision changée à la même heure refusée.
- Refus, non-exposition, initiative du cadre, pourvoi nul/partiel/complet et lits
  déjà actifs distingués ; présence du renfort vérifiée au début du poste.
- Mutations du journal détectées : identité, empreinte de contexte, probabilité,
  quantité et omission. Version, recommandation et journal physique rapprochés.
- Exports reproductibles octet pour octet sur une fixture courte ; échec d'un
  plugin sans résultat partiel ; partition test refusée avant simulation.
- Interface exercée sur une unité, un hôpital de trois pôles et les trois familles
  de ressources v041/local_v1/hybrid_v1. Ce sont des tests techniques, pas G2–G4.

## Année exécutée

**10 224 heures hospitalières contrôlées**, chauffe comprise, sans violation des
invariants de lits, patients ou flux. 61,320 lignes de
variables telles que connues, 41,363 reçus disponibles
et 152,150 événements physiques. Toutes les lignes
horaires ont été reconstruites à l'identique depuis les reçus effectivement délivrés.
Les 15 empreintes de fichiers du manifeste ont été vérifiées après l'exécution.

365 appels hospitaliers à la politique, 1 460 décisions d'unité et **5 840 lignes
unité–jour–levier**, toutes liées au contexte exact et à la version du recommandeur.

- 1 405 recommandations positives : 1 215 présentées, dont 849 approuvées et
  366 refusées ; 190 non présentées.
- 1 319 demandes effectives : 849 recommandations approuvées et 470 initiatives
  du cadre. Une initiative n'est jamais étiquetée approbation.
- 929 applications complètes, 134 partielles, 46 échecs de pourvoi et
  210 demandes sans changement applicable. Les 4 521 autres lignes ne sont pas
  des demandes et n'ont aucun effet d'exécution.

| Levier | Demandes | Applications complètes | Partielles | Échecs | Sans changement applicable |
|---|---:|---:|---:|---:|---:|
| anticipation_sorties | 362 | 313 | 0 | 0 | 49 |
| lits_supplementaires | 63 | 62 | 0 | 0 | 1 |
| renfort_soignant | 331 | 151 | 134 | 46 | 0 |
| acceleration_aval | 563 | 403 | 0 | 0 | 160 |

Les quantités ne sont pas additionnées entre leviers : plans de patients, lits
et postes sont des unités différentes. Pour le renfort, « application » signifie
confirmation de postes futurs, pas présence immédiate. Pour l'aval et les sorties,
le mécanisme modifie un plan ; ce n'est ni une sortie observée ni un gain estimé.
Les [exemples de reçus avec leur contexte](lot06_examples.json) montrent chaque cas.

## Limites et suite

Une seule réalisation annuelle de développement, sans comparaison statistique de
politiques, sans entraînement ni mesure de généralisation. Les règles proposées
servent à vérifier le branchement et ne constituent pas une recommandation métier.
La chauffe, les aléas et le mécanisme clinique restent ceux du générateur hérité.

Le recommandeur reçoit uniquement les observations disponibles. Le **cadre simulé**
conserve, séparément, le facteur caché hérité construit à partir des arrivées des
24 h suivantes ; cette approximation d'une anticipation privée reste une hypothèse
de simulation. Le journal correspondant est de la vérité et ne doit pas devenir
une entrée du modèle. Les confirmations synchrones n'incluent pas de no-show.

Phase 0, portes G1–G4 et SYN restent ouvertes. L'interface prépare la politique
apprise et le modèle hybride à règles, sans démontrer leur performance.

## Artefacts

- [Manifeste annuel](lot06_annual_manifest.json),
  [manifeste de simulation](lot06_simulation_manifest.json), [politique](lot06_policy.json).
- [Contrôles détaillés](lot06_validation.json), [exemples de chaîne](lot06_examples.json).
- Observations, variables, contextes, recommandations, reçus et vérité complète
  sous `runs/synthetic/lot06/annual/`, régénérables via [la documentation](../lot06.md).
