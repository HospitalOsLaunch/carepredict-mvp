# Lot 07 — diversité des dynamiques hospitalières

Le générateur dispose de trois choix par axe : arrivées, planification des sorties
et effectifs. Ils sont composables avec les trois familles de ressources du lot 04.
Les choix par défaut conservent les tirages, trajectoires et empreintes de configuration
v0.4.1 ; les exports ajoutent une provenance explicite `dynamics`.

Il s'agit de mécanismes d'ingénierie, non calibrés sur des données réelles. Ce lot
n'entraîne aucun modèle et ne démontre ni plausibilité clinique ni généralisation G4.

## Contrat et hypothèses

La configuration immuable `dynamics` sélectionne indépendamment les axes :

```json
{
  "dynamics": {
    "arrivals": "shared_bursts_v1",
    "discharges": "daily_rounds_v1",
    "staffing": "persistent_absence_v1"
  }
}
```

| Axe | Référence `v041` | Variante 1 | Variante 2 |
|---|---|---|---|
| Arrivées | Comptages de Poisson par unité/source/jour, avec calendrier et épidémies | `shared_bursts_v1` : intensité Gamma(2, 0,5), de moyenne 1, commune aux urgences de toutes les unités d'un même jour ; comptages Poisson conditionnels | `appointments_v1` : admissions programmées par créneaux et présence binomiale, réparties entre 8 h et 13 h ; urgences et transferts restent Poisson |
| Sorties | Planification historique, dépendante de la destination, du week-end et de l'aide | `daily_rounds_v1` : un passage à 14 h les jours ouvrés pour les sorties vivantes, après disponibilité médicale et sociale | `rolling_v1` : sortie planifiable de 8 h à 20 h exclue, tous les jours, après disponibilité médicale et sociale |
| Effectifs | Absences par poste et remplacements binomiaux historiques | `persistent_absence_v1` : 75 % de persistance du déficit au poste suivant, nouveaux absents à 2,5 %, remplacement à 35 % | `shared_float_v1` : mêmes absences que la référence, pool de remplacement limité à `floor(total prévu / 12)` par poste, allocation au déficit restant le plus important |

Les profils cliniques, durées médicales, destinations, aide à domicile, maladies
saisonnières et services restent hérités. Ce lot diversifie l'organisation de la
sortie, pas la maladie ou son traitement. Les paramètres ne sont pas tirés au hasard
entre mécanismes : les variantes sont affectées explicitement dans chaque plan,
et les paramètres de capacité/volume des hôpitaux restent tirés par le registre.

### Arrivées

Les volumes moyens utilisent les mêmes formules de référence et multiplicateurs
de spécialité/calendrier. Pour les admissions programmées, si la moyenne est `m`,
le nombre de créneaux est `ceil(m / 0,85)` et la probabilité de présence `m / n`.
La moyenne est donc conservée, avec une variance inférieure à celle de Poisson.
Aucune calibration de l'occupation après changement de mécanisme n'est effectuée.

L'intensité des afflux est commune entre unités pour créer une dépendance explicite,
mais indépendante d'un jour à l'autre. Elle ne représente pas encore un épisode
persistant ou une rupture datée. Les aléas des arrivées alternatives ont une graine
dédiée. Changer les arrivées change la population et peut déplacer les tirages
ultérieurs du moteur historique : deux variantes d'arrivées ne constituent **pas**
des contrefactuels patient par patient à aléas communs.

### Sorties

Les deux nouvelles règles respectent la disponibilité médicale, l'aide à domicile
et, pour les autres destinations vivantes, une attente d'aval d'au moins 24 h.
Les décès gardent leur heure de disponibilité. Le calendrier est évalué même au-delà
de la borne de simulation ; les événements exportés ne dépassent pas la borne.
La règle de passage quotidien ne libère pas un patient la veille du week-end.

Le transport, les examens, la charge et les leviers historiques interviennent encore
sur l'exécution. Une heure planifiée n'est donc pas une sortie réalisée ; les actions
d'anticipation et les sorties sous pression peuvent encore avancer certains plans.
Les estimations documentaires du staff conservent leur modèle historique : elles
peuvent devenir moins précises dans les variantes.

### Effectifs

Les absences persistantes sont un **processus agrégé de déficit**, pas un suivi
nominatif des mêmes salariés entre postes. Le pool représente des agents externes
aux effectifs prévus des unités, compétents pour toutes les unités ; il n'y a pas
encore de contraintes IDE/AS individuelles, de repos ou de compétences.

Le calendrier et la maintenance des fermetures sont rejoués exactement, puis les
fermetures faute de personnel sont recalculées à partir du nouveau déficit du matin.
Un contrôle vérifie la position finale du générateur aléatoire de référence lors de
ce rejeu. Il n'y a pas de double comptage des anciennes fermetures pour absentéisme.
Les aléas dédiés des effectifs préservent les patients, services et tirages de politique.
Les renforts décidés ensuite par le cadre restent un mécanisme supplémentaire distinct.

## Réservation des variantes

Trois plans indépendants sont fournis :

- `configs/synthetic/cohort_arrivals_v1.json` ;
- `configs/synthetic/cohort_discharges_v1.json` ;
- `configs/synthetic/cohort_staffing_v1.json`.

Chaque plan réserve, sur son axe seulement, `v041` à l'apprentissage, la variante 1
à la validation et la variante 2 au test. Chaque partition contient 2 hôpitaux et
2 réplications par hôpital : 12 mondes par plan, dont 4 de test. Les autres axes et
la structure sont maintenus à leur référence. Les paramètres numériques varient
par hôpital ; ces cohortes ne sont pas des comparaisons causales appariées.

Le validateur refuse qu'une variante de l'axe réservé apparaisse dans plusieurs
partitions, même après renommage des hôpitaux. Le registre est déterministe, vérifié
contre son plan, et les signatures de source et d'environnement sont contrôlées.
La génération de cohortes reste limitée par défaut à train/validation. Ouvrir le test
exige le protocole explicite déjà prévu au lot 03 ; ce lot ne l'ouvre pas.

**Ne pas mélanger ces trois plans pour entraîner un modèle de benchmark.** Une variante
de référence appartient à plusieurs rôles sur des axes différents. Chaque plan définit
une expérience séparée, avec son propre registre. La validation inter-registres doit
être appelée avec le même axe ; aucune réservation globale de tous les axes à la fois
n'est revendiquée. Les variantes sont conçues et testées sur des fixtures de développement,
pas écrites à l'aveugle par un évaluateur indépendant. Leurs mondes de test restent réservés.

```bash
PYTHONPATH=src python -m hospitalos.synthetic.cohort freeze \
  --plan configs/synthetic/cohort_arrivals_v1.json \
  --output runs/synthetic/arrivals-registry
PYTHONPATH=src python -m hospitalos.synthetic.cohort generate \
  --registry runs/synthetic/arrivals-registry \
  --output runs/synthetic/arrivals-runs --with-learning
```

## Intégration et validation

Les variantes passent par `build_simulation` : génération batch, observation,
préparation des vues d'apprentissage et boucle de politique partagent le même moteur.
Les noms de mécanismes restent dans les configurations et manifestes, jamais ajoutés
aux variables du recommandeur. Les fonctions de simulation ne modifient aucun paramètre
global du moteur historique. Le module de contrefactuels de ressources refuse de changer
`dynamics` entre ses deux bras ; son contrat d'aléas communs reste inchangé.

Les tests couvrent : conservation stock–flux et ressources sur six compositions,
trajectoire/exogènes historiques inchangés, reproductibilité binaire, contrôle des
réservations et mutations, test non ouvert, observation en boucle, moments des afflux,
dépendance temporelle des déficits, limite du pool, bornes de disponibilité et calendrier.

La campagne annuelle de développement est reproductible avec :

```bash
PYTHONPATH=src python scripts/validate_synthetic_dynamics.py \
  --output runs/synthetic/lot07/diagnostics
```

Elle exécute une référence et six changements d'axe isolés, sur sept identités de
**développement** de même structure, graine et capacité. Elle fige aussi les trois
registres annuels sans matérialiser leurs mondes. Les diagnostics annuels inspectent
les variantes pour valider le générateur ; ils ne mesurent aucune performance de modèle
sur les familles réservées. Résultats et empreintes :
[evidence/lot07_validation.json](evidence/lot07_validation.json) et
[evidence/lot07_validation.md](evidence/lot07_validation.md).

## Suite et limites

La diversité couvre seulement trois écritures par axe, quatre spécialités et les
ressources déjà disponibles. Les plages ne sont pas encore bornées sur statistiques
publiques. Ni blocs opératoires, ni urgences autonomes, ni réanimation ne sont ajoutés.
Le cadre conserve son facteur de confusion privilégié hérité, y compris son lien aux
arrivées futures ; le recommandeur du lot 06 reste limité aux observations.

La phase 0 reste ouverte. Prochain lot proposé : ruptures organisationnelles datées
(lits, capacités, effectifs), avec provenance et test de non-anticipation, pour préparer
l'évaluation de l'adaptation. Les parcours patients tels que connus, le modèle hybride
et le protocole final restent également à achever.
