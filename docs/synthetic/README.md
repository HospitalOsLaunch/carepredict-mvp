# Socle synthétique et générateur multi-pôles — lot 01

Le [lot 02](lot02.md) ajoute un pipeline séparé d'observations telles que connues
et une référence de prévision à 24 h à partir des sorties décrites ici.
Le [lot 03](lot03.md) ajoute le registre de cohortes et réserve des structures
entières aux ensembles d'apprentissage, de validation et de test.
Le [lot 04](lot04.md) ajoute des services réservés par pôle, une organisation mixte,
le routage dirigé et des comparaisons de mécanismes à état et aléas communs.
Le [lot 05](lot05.md) fixe un premier protocole et compare persistance, saisonnalité
et gradient boosting à 24 h sur des hôpitaux de validation distincts.
Le [lot 06](lot06.md) branche une politique sur les observations en direct et trace
les recommandations, décisions du cadre et résultats d’exécution.

Le [lot 07](lot07.md) diversifie les arrivées, sorties et effectifs et réserve
les variantes dans trois plans de cohortes indépendants.

Le [lot 08](lot08.md) ajoute des ruptures datées de lits, services et effectifs,
avec audit des frontières et contrôle de non-anticipation.

Le [lot 09](lot09.md) ajoute des profils d’observation par établissement : délais,
informations manquantes et pannes de transmission, en rejeu et en boucle fermée.

Le [lot 10](lot10.md) ajoute les parcours de mouvements patient tels que connus,
les corrections et des cibles de départ censurées, séparées des observations.

Le [lot 11](lot11.md) ajoute les recensements patient complets ou partiels et la
réconciliation des localisations, sans transformer une absence locale en sortie.

Le [lot 12](lot12.md) enrichit chaque ligne patient par les évaluations de charge,
les sorties prévisionnelles et les besoins d’aval disponibles à cet instant,
avec une provenance séparée de la présence et des cibles réalisées.

Le [lot 13](lot13.md) diversifie les prévisions du staff et les confirmations
d’aval, réserve leurs familles par axe et contrôle leur indépendance vis-à-vis
des trajectoires physiques.

Le [lot 14](lot14.md) corrige les mesures de réalisme, réconcilie présences et files
avec les événements, conserve les séjours censurés et les demandes non admises,
et prépare la [séquence gériatrie–aval](realism_plan.md). Son scénario GHT-600
représente 250 lits de médecine ; aucun réalisme externe n'est encore validé.

Le [lot 15](../operational/lot15.md) introduit le contrat opérationnel commun et
entraîne un premier petit modèle sur ce générateur. Les mêmes poids traitent les
observations par unité, pôle ou établissement ; les résultats restent exploratoires.

Ce premier lot intègre le moteur corrigé v0.4.1 et permet de définir un hôpital
composé de plusieurs pôles et unités. Une simulation unique fait partager aux
patients les lits compatibles, le nettoyage, l'imagerie, le transport et les avis
spécialisés. Il s'agit du début de la phase 0, pas d'un world model entraîné ni de
la validation de la généralisation G1–G4.

## Exécuter

Depuis la racine du dépôt, avec Python 3.11 ou ultérieur :

```bash
python -m pip install 'numpy>=1.26,<3' 'pandas>=2.2,<3' 'pydantic>=2.7,<3'
PYTHONPATH=src python -m hospitalos.synthetic \
  --config configs/synthetic/hospital_two_poles.json \
  --output runs/synthetic/annual
```

La configuration d'exemple produit l'année 2025 après 61 jours de chauffe :
102 lits standard, répartis entre 2 pôles et 4 unités, plus les 2 lits de renfort
activables par unité du moteur historique. Ajouter `--days 7` pour raccourcir la
période enregistrée ; les 61 jours de chauffe restent exécutés. Le chemin de sortie
doit être nouveau. Une sortie n'est publiée qu'après succès des contrôles et des
écritures. Aucun service, GPU, accès SI ou dossier patient réel n'est nécessaire.

Les unités ont des identifiants indépendants de leur modèle de spécialité ;
plusieurs unités peuvent réutiliser `MED_POLY`, `CSG`, `PNEUMO` ou `CARDIO`.
Les tailles, lits spécialisés et volumes d'arrivée sont configurables. Les lits
d'isolement sont inclus dans les lits avec oxygène, conformément au moteur repris.
Les capacités des services communs sont dimensionnées d'après le nombre de lits,
puis multipliées par `shared_resources` et arrondies à l'entier inférieur.
Un multiplicateur nul ferme le service pendant toute la simulation.

## Contrat des sorties

| Fichier | Contenu |
|---|---|
| `config.json` | Configuration effective, incluant les valeurs par défaut et la graine |
| `manifest.json` | Version, empreintes du code et des fichiers, dépendances, contrôles et hypothèses |
| `truth/units_hourly.csv` | États horaires, avec identifiants d'hôpital, de pôle et d'unité |
| `truth/poles_hourly.csv` | Sommes des stocks, flux et charges des unités du pôle |
| `truth/hospital_hourly.csv` | Agrégats hospitaliers et ratios recalculés sur les totaux |
| `truth/shared_resources_hourly.csv` | Capacités et files communes, comptées une seule fois à l'hôpital |
| `truth/events.jsonl.gz` | Événements de vérité, dont la chauffe pour initialiser un futur rejeu |

`h=0` correspond au début de la période enregistrée ; les événements de chauffe ont
un `h` négatif. Les états correspondent à la fin du pas horaire. Les événements
s'arrêtent avant `days * 24`. Les identifiants de séjour et d'événement sont
préfixés par l'hôpital. Ils restent locaux à une exécution identifiée par sa
configuration et ses empreintes : pour réunir plusieurs graines du même hôpital,
la clé doit aussi inclure l'exécution. Les payloads d'événement conservent le schéma
historique v0.4.1, dont les références internes numériques aux unités.

Les capacités partagées ne sont pas dupliquées dans les totaux des pôles. Le ratio
de charge est recalculé ; les minutes non couvertes restent la somme des déficits
locaux, car les soignants ne sont pas implicitement mutualisés. Les transferts
internes comptabilisent les mouvements d'unités, y compris au sein d'un même pôle ;
ils s'annulent au niveau hospitalier et ne sont pas des admissions externes.

**Tous ces fichiers sont de la vérité du simulateur.** Ce lot ne publie pas de
variables d'apprentissage « telles que connues », de cibles, de nouvelles notes,
de contrefactuels multi-pôles ni de poids de modèle. La chaîne d'observation et ses
délais seront raccordés avant tout apprentissage à partir de ces nouveaux exports.
Un état de vérité, même horodaté, n'est pas une observation disponible au SI.

## Reproductibilité et séparation des ensembles

À configuration, source et versions de dépendances identiques, les exports sont
identiques octet pour octet, y compris le gzip. Changer la durée de simulation
change aussi les tirages : les répétitions comparent des configurations identiques,
pas des préfixes de simulations de longueurs différentes.

La partition est portée par l'hôpital entier. Pour vérifier plusieurs configurations :

```bash
PYTHONPATH=src python -m hospitalos.synthetic \
  --config configs/synthetic/hospital_two_poles.json \
  --check-cohort chemin/autre_hopital.json \
  --output runs/synthetic/cohort-check
```

Cette vérification refuse un même identifiant hospitalier dans plusieurs partitions,
même si les graines diffèrent. Elle ne vérifie que les configurations fournies : le
registre complet et la réservation de familles structurelles sont ajoutés par le
[lot 03](lot03.md). Renommer un hôpital ne démontre aucune indépendance statistique. L'exemple
est explicitement dans `development` et ne constitue pas un ensemble de test gelé.

## Vérification du lot

```bash
PYTHONPATH=src python -m pytest -q tests/synthetic
PYTHONPATH=src python -m hospitalos.synthetic.v041.tests
```

La suite du lot couvre la validation de configuration, les doublons d'identifiants,
les partitions, la reproductibilité, les agrégats et ratios, les limites temporelles,
l'absence d'écrasement et la contention entre deux pôles. Pour ce dernier test, retirer
une demande du pôle A de la file commune permet à un patient du pôle B d'utiliser le
même créneau d'imagerie, depuis le même état initial.

La CI dédiée exécute aussi les 54 tests historiques (dont les mutations de fuite et
de fusion des notes), le typage strict du nouveau code et une année complète. Les
contrôles de conservation des patients, des lits et des flux tournent à chaque heure,
y compris pendant la chauffe. Le manifeste et la configuration sont conservés comme
preuves de l'exécution annuelle en CI.

Le répertoire `v041` est un import historique non typé, isolé du lint et du typage
strict du nouveau code. [PROVENANCE.json](v041/PROVENANCE.json) enregistre l'archive
et les empreintes originales ; les modifications sont limitées aux imports relatifs,
aux appels de contrôles en sous-processus et à l'injection de profils d'unité par
instance. Les README/SCHEMA de ce répertoire décrivent **l'ancien corpus** ; leurs
chiffres et chemins ne sont pas ceux de ce nouveau lot.

## Limites et tâches suivantes

- **SOC-001, GEN-001, GEN-002 : implémentés dans le lot 01.** Source corrigée,
  configuration hiérarchique, simulation partagée, export de vérité et vérifications.
- **SOC-002 : livré dans le lot 02.** Contrat d'observation, rejeu « tel que connu », retards
  de saisie, tests d'invariance aux livraisons futures et première référence à 24 h.
- **GEN-003 : livré pour les structures dans le lot 03.** Registre de cohortes,
  paramètres tirés par hôpital, réservation des établissements et structures.
  La réservation de mécanismes distincts attend GEN-004 : une seule famille existe.
- **GEN-004 : livré dans le lot 04 pour les mécanismes opérationnels.** Ressources
  locales/communes, règles de routage et scénarios appariés. Les modèles cliniques,
  d'arrivées et d'effectifs restent ceux de v0.4.1.

Pour ce lot, les pôles sont des groupes organisationnels : ils n'ont pas encore de
politique locale distincte. L'hébergement utilise tous les lits compatibles du
périmètre. Les quatre spécialités et une seule famille de mécanismes sont disponibles ;
les urgences centrales, la réanimation et le bloc ne sont pas modélisés comme services
autonomes. Le calendrier reste en UTC+1 fixe. Les arrivées ne sont pas recalibrées pour
atteindre un taux d'occupation cible. La politique historique consulte certaines
informations privilégiées du simulateur et n'est pas un recommandeur déployable.
La plausibilité et le transfert au réel ne sont pas démontrés par ces contrôles.
