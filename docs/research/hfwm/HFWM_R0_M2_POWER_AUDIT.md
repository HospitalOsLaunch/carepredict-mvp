# HFWM-R0 — Audit de puissance M2

## Portée et unité d'analyse

Cet audit réutilise uniquement les erreurs brutes M2. Les trois labels de seed
sont des répétitions déterministes; une seule copie par configuration est
analysée. Le test contient **9 épisodes**, chacun composé de 4 pas synchronisés
et 2 targets. Les 72 cellules ne sont pas 72 observations indépendantes.

Les épisodes sont croisés sur seulement 3 sites/unités et 3 périodes communes
(15 mars, 9 avril, 4 mai 2025). Les pas d'un épisode partagent le même rollout
initial et forment un bloc temporel indivisible.

## Dépendance observée

Sur la différence appariée de NMAE `partagé - local` :

- moyenne par épisode : `0.03424412752250818`;
- écart-type inter-épisode : `0.08400742844559261`;
- autocorrélation lag-1 des deltas par pas : `0.00635`;
- autocorrélation lag-1 occupation : `0.00820`;
- ICC site/unité : `0.14788`;
- ICC période : `0.46308`.

Les autocorrélations sont proches de zéro, mais leur estimation sur 9
trajectoires est trop instable pour établir l'indépendance. Les ICC révèlent au
contraire une structure de cluster, surtout temporelle. Une approximation
croisée prudente `1 + 2*ICC_site + 2*ICC_période` donne un design effect de
`2.22192` et une taille effective **n_eff ≈ 4.05**. Cette estimation est une
analyse de sensibilité, pas une preuve confirmatoire, car il n'existe que trois
clusters par axe.

## Puissance et MDE

M2 n'avait pas pré-enregistré de puissance cible. Les chiffres suivants sont
donc une analyse post-hoc de sensibilité à alpha bilatéral 5 % et puissance 80 %,
fondée sur l'écart-type apparié observé :

| Hypothèse d'indépendance | n effectif | MDE absolu NMAE | MDE relatif au local |
|---|---:|---:|---:|
| 9 épisodes IID | 9.00 | 0.07845 | 15.14 % |
| clustering site seul | 6.95 | 0.08930 | 17.24 % |
| clustering site + période | 4.05 | 0.11694 | **22.57 %** |

Pour détecter un gain relatif de 5 % (`0.0259011` NMAE), il faudrait environ
**83 épisodes IID**. En conservant le design effect observé, il faudrait environ
**184 épisodes bruts**, équilibrés entre davantage de sites/unités et de blocs
temporels. La puissance approximative actuelle pour 5 % n'est que **15.2 %**
sous l'hypothèse IID, donc inférieure encore sous clustering.

Ces tailles sont des minima de planification : elles doivent être recalculées
avant déverrouillage de M3 si la variance ou le design change.

## Incertitude de calibration

Intervalles binomiaux exacts 95 % (naïfs, 36 cellules par target), suivis d'un
bootstrap exploratoire par épisode :

| Modèle / target | Couvertes | Couverture | IC exact 95 % | IC bootstrap épisode 95 % |
|---|---:|---:|---:|---:|
| local / occupation | 34/36 | 94.44 % | [81.34 %, 99.32 %] | [83.33 %, 100 %] |
| partagé / occupation | 33/36 | 91.67 % | [77.53 %, 98.25 %] | [80.56 %, 100 %] |
| local / inflow | 35/36 | 97.22 % | [85.47 %, 99.93 %] | [91.67 %, 100 %] |
| partagé / inflow | 35/36 | 97.22 % | [85.47 %, 99.93 %] | [91.67 %, 100 %] |

Les intervalles binomiaux supposent à tort des cellules IID; ils ne servent que
de référence. Les intervalles par épisode restent très larges.

## Validité du bootstrap M2

Le bootstrap M2 resample les `episode_id` et conserve ensemble targets et pas :
il respecte donc le bloc intra-épisode. Il ne respecte pas les clusters croisés
site/unité et période. Avec seulement trois clusters par axe, son IC ne peut pas
étayer une conclusion globale de supériorité ou d'infériorité.

M3 devra utiliser un **clustered/block bootstrap croisé** : resampling des sites
et des blocs temporels, épisodes conservés entiers, puis agrégation des cellules
au sein de chaque épisode. Aucun comptage par seeds déterministes.

## Matrice d'observabilité world model

| Propriété | Variable nécessaire | Disponible M1 | Testable | Action M3 |
|---|---|---:|---:|---|
| conservation des patients | admissions, sorties, transferts, présence | Non (inflow agrégé seulement) | REQUIRES_DATASET_ENRICHMENT | Ajouter flux signés synchronisés et identifiants de transfert |
| capacité | lits ouverts, occupés, indisponibilités | Non | REQUIRES_PARTNER_DATA | Obtenir séries capacité horodatées; sinon retirer le critère |
| staffing | prévu, présent, charge | Non | REQUIRES_PARTNER_DATA | Obtenir roster/présence agrégés et fraîcheur |
| cohérence jointe | variables synchronisées | Partiel : occupation + inflow | REQUIRES_DATASET_ENRICHMENT | Ajouter sorties/transferts/capacité au même `as_of` |
| rollout libre | trajectoires multi-pas | Oui, 4 pas | TESTABLE_NOW | Conserver, avec davantage d'épisodes et blocs |
| observabilité partielle | missingness et fraîcheur | Partiel : heures observées; pas de fraîcheur complète | REQUIRES_DATASET_ENRICHMENT | Ajouter masque par variable, `available_at` et âge |
| changement de régime | périodes ou unités distinctes | Partiel : 3 périodes, 1 unité/site | REQUIRES_DATASET_ENRICHMENT | Multiplier blocs, unités et régimes pré-étiquetés |
| transfert | sites indépendants | Non : 3 pseudo-sites synthétiques | REQUIRES_PARTNER_DATA | Sites réels indépendants, holdout site obligatoire |

`TESTABLE_NOW` ne signifie pas suffisamment puissant. M3 ne peut conserver
comme contraintes confirmatoires que conservation, capacité ou staffing si les
variables correspondantes sont ajoutées et passent un gate de complétude avant
tout entraînement. Le transfert réel reste hors de portée sans données partenaire.

## Conclusion

La supériorité primaire et l'infériorité primaire sont toutes deux
**inconclusives** sur M1. Le guardrail occupation demeure échoué, car il est une
règle d'arrêt pré-enregistrée appliquée au résultat observé, non un test de
supériorité globale. Un M3 interprétable exige un dataset enrichi et au moins un
ordre de grandeur supplémentaire d'unités indépendantes.
