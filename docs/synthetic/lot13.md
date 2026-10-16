# Lot 13 — mécanismes documentaires du staff et de l’aval

Les vues du lot 12 exposaient les prévisions du moteur historique : le staff
utilise le cours latent courant et la destination prévue, tandis qu’une
confirmation d’aval peut apparaître à partir du seuil « départ programmé moins
18 h ». Ce lot conserve cette référence et ajoute des mécanismes fondés sur les
constats présents et les demandes déjà émises. L’objectif est de pouvoir éprouver
la sensibilité d’un futur modèle à ces hypothèses.

## Configuration et séparation des responsabilités

Deux champs indépendants de `dynamics` et des profils de transmission sont
introduits dans `documentary` :

| Axe | Référence | Variante 1 | Variante 2 |
|---|---|---|---|
| `staff_forecasts` | `v041` | `admission_prior_v1` | `milestones_v1` |
| `downstream_confirmation` | `v041` | `request_delay_v1` | `review_capacity_v1` |

Les valeurs par défaut conservent les trajectoires et identifiants des anciennes
configurations. Le contrôleur documentaire possède ses propres tirages indexés
par graine, séjour, mécanisme et épisode. Il ne consomme aucun tirage de la
physique, des arrivées ou de la politique. Les configurations non triviales
changent leur empreinte, sont exportées et sont reprises dans les cohortes.

Les confirmations sont des **messages administratifs synthétiques**. Elles
n’allouent pas de lit d’aval et ne conditionnent pas la sortie physique. Une
sortie peut ainsi survenir sans confirmation reçue ou même sans confirmation
émise. Ce lot diversifie l’information disponible ; il ne construit pas encore
un réseau physique de lits de SMR/EHPAD en concurrence.

## Prévisions du staff

Les deux nouvelles familles partagent un contrat fermé `StaffSnapshot` :
admission passée, dépendance, indicateur d’âge ≥75 ans, oxygène, blocage actuel,
aptitude médicale actuelle à sortir, aide à domicile actuellement en attente,
orientation déclarée et confirmation documentaire connue. Le calcul ne reçoit
ni date future d’aptitude, ni date programmée/réalisée de sortie, ni calendrier
futur des files de ressources.

- **Priorité à la durée depuis l’admission (`admission_prior_v1`).** Une durée
  initiale indicative est construite à partir de la dépendance, de l’âge et de
  l’oxygène, puis de l’orientation demandée. Le bruit propre au séjour est stable.
  L’annonce reste ancrée sur l’admission jusqu’à ce que l’état présent impose
  de la repousser.
- **Étapes courantes (`milestones_v1`).** Une durée restante est estimée à
  chaque révision à partir de l’aptitude actuelle, des blocages, de l’aide et de
  l’orientation. Le bruit varie selon le jour de revue ; une confirmation
  disponible réduit l’attente administrative estimée.

Le staff se tient à 10 h les jours ouvrés, après au moins 12 h d’admission.
Trente pour cent des séjours n’obtiennent jamais de date annoncée. Les révisions
spontanées ont une probabilité de 25 % ou 60 % selon la famille ; une annonce
atteinte ou dépassée est réévaluée. Seuls les changements de date sont journalisés.

Les nouvelles orientations sont également fondées sur la dépendance actuelle,
avec un tirage initial, puis des réévaluations possibles quand le patient est
actuellement apte à sortir. Elles ne sont pas recopiées depuis la destination
physique prévue. Elles peuvent donc être erronées, annulées ou modifiées.
Le champ `staff_forecasts` couvre bien la date **et le processus d’orientation**.

Les constantes sont des hypothèses d’ingénierie versionnées : par exemple,
`admission_prior_v1` utilise `2 + 1,5 × dépendance + âge75 + oxygène` jours de
base. Elles ne proviennent pas d’un calibrage clinique ou de statistiques publiques.

## Confirmations d’aval

Les variantes suivent les demandes SMR/EHPAD émises à la source. Un changement
de type démarre un nouvel épisode ; une annulation invalide l’ancien. Répéter
la même orientation ne redémarre pas l’horloge. La perte éventuelle d’un message
intervient ensuite dans l’adaptateur du lot 12.

- **Délai administratif (`request_delay_v1`).** Délai lognormal tiré au moment
  de la demande : médiane 36 h en SMR et 72 h en EHPAD, sigma 0,55. Une
  confirmation devient possible une fois ce délai écoulé, entre 9 h incluses
  et 17 h exclues les jours ouvrés, si le patient est actuellement apte et
  non bloqué.
- **Revue à capacité limitée (`review_capacity_v1`).** À 14 h les jours ouvrés,
  sélection des demandes âgées d’au moins 24 h pour des patients présents,
  aptes et non bloqués. Les demandes les plus anciennes passent d’abord,
  indépendamment de l’ordre de parcours des unités. Quota hospitalier de
  `max(1, nombre d’unités // 2)` confirmations par revue ; les autres attendent.

Chaque épisode ne peut produire qu’une confirmation. Le type de place annoncé
est celui de la demande courante, sans lecture de la destination finale ou du
départ programmé. Le patient doit toujours être présent lors de l’émission.

La capacité de revue représente une capacité administrative, sans stock de lits
d’aval, refus, expiration d’offre ni réservation physique. Ces mécanismes restent
à construire si l’on veut simuler ces contraintes elles-mêmes.

## Intégration

Trois points d’extension ciblés sont ajoutés au moteur importé : revue du staff,
déclaration de destination et confirmation d’aval. Leur référence `v041` est
comparée au moteur publié du lot 03. La provenance de ces adaptations figure
dans `v041/PROVENANCE.json`.

La physique est comparée avec journal et sans journal, ainsi que sous les trois
organisations de ressources et une dynamique alternative de sortie. Les vues
patient du lot 12 continuent d’utiliser les mêmes huit types de messages, leurs
réceptions différées et leurs corrections. Le manifeste explique les hypothèses
effectivement sélectionnées au lieu de toujours décrire la règle historique.

Le journal utilise encore une numérotation globale des événements. Quand le
nombre de documents change, certains identifiants changent, donc les clés des
tirages de transmission peuvent aussi changer. **L’invariance physique ne
signifie pas une réalisation identique du bruit d’observation entre variantes.**
La comparaison en ligne/rejeu porte sur chaque variante séparément.

## Réservation des familles

Deux plans minimaux sont fournis :

| Plan | Apprentissage | Validation | Test réservé |
|---|---|---|---|
| `cohort_staff_forecasts_v1.json` | `v041` | `admission_prior_v1` | `milestones_v1` |
| `cohort_downstream_confirmation_v1.json` | `v041` | `request_delay_v1` | `review_capacity_v1` |

Chaque plan comporte 6 établissements et 12 réalisations prévues : 2 hôpitaux
par partition et 2 réplications chacun. Le registre est figé avant génération.
La famille réservée ne peut pas traverser les partitions, y compris après
renommage d’hôpital ; ouvrir le test exige toujours un protocole explicite.

Ces deux plans réservent chacun un axe ; les fusionner ne produit pas une
réservation conjointe des deux axes. Les mécanismes sont inspectés sur des
fixtures de développement, même lorsqu’ils figurent dans une partition de test
future : ce n’est pas une conception à l’aveugle par un évaluateur indépendant.
Les établissements du test final ne sont pas matérialisés. La distribution
d’apprentissage reste à élargir et le protocole final reste à préenregistrer.

## Exécution et vérification

```bash
PYTHONPATH=src python -m hospitalos.synthetic.cohort freeze \
  --plan configs/synthetic/cohort_staff_forecasts_v1.json \
  --output runs/synthetic/staff-registry

PYTHONPATH=src python scripts/validate_synthetic_documentary.py \
  --output runs/synthetic/lot13/annual
```

La campagne compare six années de développement : référence, chacune des quatre
variantes prise isolément et composition `milestones_v1 + review_capacity_v1`.
Même hôpital, graine, patients entrants, ressources et politique pour chaque cas.
Elle vérifie l’invariance physique, les invariants horaires, les fichiers et
les réceptions documentaires en ligne/rejeu. Les erreurs des annonces de sortie
et délais confirmation–sortie sont des diagnostics du générateur ; ils ne
mesurent ni performance d’un modèle entraîné ni généralisation.

Preuves : [rapport de validation](evidence/lot13_validation.md) et
[rapport machine](evidence/lot13_validation.json).

Prochain lot proposé : introduire les erreurs non signalées de complétude des
recensements et éprouver la réconciliation face aux présences omises et aux
contradictions. Les demandes non admises, le bornage public, les styles de notes,
le modèle hybride et le protocole final restent ouverts. Phase 0 et porte SYN
restent ouvertes ; le calendrier global n’est pas réestimé par ce lot.
