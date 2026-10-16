# Lot 11 — réconciliation par recensements observés

Le lot 10 révélait l’accumulation de patients fantômes lorsque des sorties étaient
perdues. Ce lot ajoute une seconde source d’observation : le recensement des lits
occupés d’une unité. Le consommateur reconstruit les séjours à partir des seuls
mouvements et recensements disponibles à l’heure de décision.

**L’absence dans une unité n’est pas une sortie de l’hôpital.** Elle retire une
localisation devenue contredite, mais conserve le séjour dans un journal de
réconciliation avec une présence hospitalière inconnue. Aucune date de départ,
destination ou durée restante n’est inventée. La vérité physique reste réservée
à la génération des observations, aux cibles et à l’évaluation.

## Contrat et règles

Un `CensusDelivery` contient l’hôpital, le pôle, l’unité recensée, la liste des
couples séjour–lit et une déclaration explicite de couverture `complete`.
Il possède quatre horloges ordonnées, des identifiants de message et d’événement,
une version et, pour une correction, la version remplacée. Les champs étrangers,
doublons de séjour ou de lit dans un même recensement sont refusés.

| Observation disponible | Conséquence |
|---|---|
| Patient présent, recensement complet ou partiel | Localisation connue à la date du recensement ; pas de date d’admission fabriquée |
| Patient absent d’un recensement complet de son unité connue | `unit_absence`, localisation et présence hospitalière inconnues ; aucune clôture |
| Patient absent d’un recensement partiel | Aucune preuve d’absence |
| Recensement complet d’une autre unité | Aucune preuve d’absence dans l’unité du patient |
| Silence, panne ou information ancienne | Aucun effacement automatique ; le masque d’ancienneté reste disponible |
| Sortie ou non-admission enregistrée | `closed`, avec la nature du mouvement ayant clos le séjour |
| Correction ou annulation de recensement | Nouvelle reconstruction à sa réception, sans réécrire les lignes antérieures |

Une liste vide complète est une observation d’unité vide. Une liste vide partielle
n’affirme rien sur son occupation. Le contrat ne permet pas de déduire la
complétude du nombre de lignes ou du silence d’un flux.

Les recensements portent uniquement sur les patients occupant un lit. Une demande
encore en attente n’est donc pas close par leur absence. Un patient retrouvé par
recensement peut ne pas avoir de demande ni d’admission connue : les masques,+l’âge, le mode d’entrée et la durée écoulée restent manquants.

## Temps, versions et contradictions

Les mouvements sont rejoués selon leur date et leur ordre source. Un recensement
décrit la fin de sa borne horaire, après les mouvements de cette borne. Un ancien
recensement livré tardivement ne peut donc pas annuler un transfert ou un départ
plus récent. La version la plus élevée reçue remplace les précédentes ; les
doublons n’ajoutent ni mouvement ni fraîcheur à l’information.

Une présence après une clôture enregistrée, ou deux présences dans des unités
différentes au même instant, activent `observation_conflict`. Dans le second cas,
l’ordre déterministe des identifiants départage la localisation affichée ; le
masque interdit de considérer ce choix comme une résolution certaine du conflit.
Les conflits de lits entre séjours restent signalés par `bed_conflict`.

Une absence locale peut être levée par un transfert, un recensement positif ou
une correction invalidant la preuve d’absence. Une correction ancienne ne
supprime pas une preuve d’absence plus récente. Si toute preuve de présence est
annulée, le journal passe à `unobserved`, pas à une sortie.

`PatientAsOfCursor.advance(hour, movements, censuses)` valide tout le lot avant
de changer son état. Les messages futurs, changements d’identité et versions
contradictoires sont refusés. La provenance des lignes indique la source, la
version et, pour un recensement, sa complétude. Le journal indique également les
messages qui ont déclenché chaque changement.

## Générateur d’observation

`OnlineCensus.push/receive` reçoit chaque lot horaire de mouvements physiques,
maintient l’occupation courante et produit les recensements programmés. Il ne lit
ni les séjours finaux, ni les dates médicales cachées, ni les mouvements futurs.
Cette lecture de l’état physique appartient à la génération synthétique ; elle
n’est jamais exposée à la reconstruction comme un moyen de nettoyer ses entrées.

Le profil par défaut programme un recensement toutes les 24 h, y compris pendant
la chauffe. La probabilité de recensement partiel est 15 % ; chaque patient a alors
80 % de probabilité d’être conservé. Ces nombres sont des hypothèses d’ingénierie,
pas des statistiques hospitalières validées. Intervalle et probabilités sont
configurables par `CensusProfile` et enregistrés dans le manifeste patient.

Les pertes de recensement, délais, révisions, doublons et pannes reprennent le
profil d’observation de l’établissement, avec des tirages indépendants des
mouvements et de la physique. Une révision générée complète une première version
explicitement partielle du même instant. Le contrat accepte aussi les annulations
et déclassements de complétude, couverts par les tests construits.

**La déclaration de complétude est supposée fiable dans ce générateur.** Il ne
simule pas encore une omission non signalée dans un recensement déclaré complet.
La robustesse à ce défaut de source doit être évaluée avant tout transfert réel.
Le modèle d’observation ne représente pas non plus le temps nécessaire à une
tournée de recensement : il s’agit d’un instantané daté, puis retardé.

## Exports et utilisation

```bash
PYTHONPATH=src python -m hospitalos.synthetic.patient_learning \
  --source runs/synthetic/annual \
  --output runs/synthetic/patients-reconciled --with-census

PYTHONPATH=src python -m hospitalos.synthetic.cohort generate \
  --registry runs/synthetic/registry --output runs/synthetic/cohort-reconciled \
  --with-learning --with-patients --with-census
```

`--census-profile fichier.json` permet de remplacer les paramètres de recensement
du pipeline patient ; il nécessite `--with-census`. La cohorte utilise actuellement
le profil de recensement par défaut et conserve les profils d’observation propres
aux hôpitaux. Sans `--with-census`, la reconstruction reste fondée sur les mouvements.

| Fichier | Rôle |
|---|---|
| `observed/movements.jsonl.gz` | Mouvements livrés |
| `observed/censuses.jsonl.gz` | Recensements livrés, dont versions partielles et corrections |
| `observed/reconciliation.jsonl.gz` | Changements d’état tels que connus, y compris absences non résolues et clôtures documentées |
| `features/patients_asof.jsonl.gz` | Séjours localisés ou en attente connue, avec provenance et masques |
| `targets/stays.jsonl.gz` et `targets/departures.jsonl.gz` | Vérité et cibles séparées, avec censure inchangée |

Les séjours `unit_absence`, `unobserved` et `closed` ne figurent pas dans les lignes
actives. **L’absence d’une ligne active ne doit donc jamais être utilisée comme
une cible de sortie.** Un consommateur doit conserver le dernier état du journal
de réconciliation, notamment les absences locales non résolues. Le manifeste
en compte le stock final ; il ne s’agit pas d’un stock de patients physiquement
présents. En direct, `cursor.states` conserve ces états et `cursor.reconciliations`
expose les changements de l’appel courant.

Les écritures restent atomiques et reproductibles, les fichiers sont empreintés,
la source est immuable et l’ouverture du test reste protégée. Les identifiants
techniques servent aux jointures, pas de variables prédictives. Les cibles
correspondent à la nouvelle population de lignes actives : une comparaison de
modèles devra fixer cette population avant toute évaluation.

## Validation et suite

```bash
PYTHONPATH=src python scripts/validate_synthetic_census.py \
  --output runs/synthetic/lot11/annual
```

`--source` permet de réutiliser une réalisation physique de développement vérifiée,
pour comparer deux observations d’une même année. La validation contrôle chaque
réception, ligne active, changement de réconciliation et jointure de cible entre
flux incrémental et rejeu. Les recensements complets sont comparés au journal
physique agrégé. Les heures de patients fantômes **et** les heures de patients
physiquement présents manqués sont mesurées pour les deux reconstructions.

Preuves : [résultats](evidence/lot11_validation.md) et
[rapport machine](evidence/lot11_validation.json).

Ce lot ne branche pas les patients à `PolicyContext`, n’entraîne aucun encodeur
et ne démontre ni réalisme clinique ni généralisation. Les demandes closes sans
admission dont le message a été perdu restent sans source de réconciliation.
La prochaine étape proposée est l’enrichissement par **charge observée, sortie
prévisionnelle et besoin d’aval**, avec dates de disponibilité, révisions et cibles
séparées. Le traitement des erreurs de complétude et des attentes non résolues
reste ouvert. Phase 0, porte SYN et calendrier global restent inchangés.
