# Lot 12 — preuves d’enrichissement patient

Validation locale du 15 octobre 2026, exclusivement sur données synthétiques.
Aucun modèle entraîné et aucune partition finale de test ouverte.

## Périmètre

La campagne réutilise la réalisation physique vérifiée du lot 10 : année 2025,
365 jours et 61 jours de chauffe, graine 41, 2 pôles et 4 unités, profil intermittent,
partition `development`. Le journal physique inclut 4 925 demandes/séjours avec
chauffe, dont 74 séjours admis ouverts à l’extraction. Les 10 224 heures physiques
ont passé les contrôles d’invariants du simulateur. La physique n’a pas été
relancée pour ce rapport local.

Les nouveaux documents sont observés avec les paramètres de perte, délai, bruit,
correction, doublon et panne de l’établissement. Les tirages sont indépendants
de ceux des mouvements et recensements. Les présences et cibles ne reçoivent
aucun des nouveaux documents en entrée.

## Résultats annuels

**Comparaison intégrale réussie** : 47 157 réceptions documentaires,
672 009 lignes patient–heure enrichies et leurs cibles séparées.
Les 14 462 réceptions de mouvements, 1 655
réceptions de recensement et 37 942 changements de
réconciliation correspondent également au traitement incrémental.
**15 empreintes de fichiers et 8 archives gzip** vérifiées ;
les cardinalités sont contrôlées avant la comparaison des contenus.

Les documents couvrent 45 979 événements distincts,
avec 778 versions correctives et 400 doublons.
Les 4 277 séjours ayant des lignes actives reçoivent chacun
uniquement les informations disponibles à chaque instant. Les 643
séjours documentés sans ligne active incluent des séjours de chauffe clos avant
le début de l’année ; ce compteur ne mesure pas les seules présences manquées.

| Groupe documentaire | Lignes renseignées | Lignes manquantes | Part manquante | Lignes renseignées de plus de 96 h |
|---|---:|---:|---:|---:|
| Charge, dépendance, mobilité | 602 313 | 69 696 | 10.37 % | 0 |
| Sortie prévisionnelle | 377 620 | 294 389 | 43.81 % | 83 485 |
| Destination demandée | 519 274 | 152 735 | 22.73 % | 233 083 |
| Demande ou statut d’aval | 193 637 | 478 372 | 71.19 % | 101 559 |
| Aide à domicile | 106 897 | 565 112 | 84.09 % | 29 499 |

Ces parts décrivent la couverture des documents reçus, pas leur exactitude.
Les besoins d’aval et d’aide à domicile ne concernent pas tous les séjours ;
une valeur absente ne permet pas de trancher entre absence de besoin et absence
d’information. L’ancienneté est calculée depuis le fait source, champ par champ.

- 22 788 lignes ont une prévision dépassée ;
  5 823 comportent une prévision au-delà du 31 décembre.
  Ces annonces restent autorisées, sans révéler une sortie future réalisée.
- 1 201 lignes ont un statut d’aval reçu sans demande connue,
  avec durée d’attente inconnue ; 1 325 signalent au moins
  un événement d’aval non apparié. Ces deux compteurs peuvent se recouper.
- 4 messages documentaires différés au-delà de la borne restent
  dans la file en ligne et ne figurent pas dans les réceptions exportées.
- Les 74 séjours physiquement ouverts restent censurés dans les cibles ;
  les 221 présences hospitalières inconnues restent dans le journal de réconciliation.

Réceptions par groupe : 32 062 évaluations de charge,
6 578 prévisions de sortie,
4 880 orientations,
2 172 messages d’aval et
1 465 messages d’aide à domicile.
Ces nombres incluent les corrections et doublons.

Une tentative antérieure a été écartée après détection d’une archive de
réceptions tronquée, dont l’empreinte correspondait pourtant au manifeste.
Sa cause n’a pas été établie. Les résultats publiés proviennent d’une
régénération complète dans un nouveau répertoire, avec lecture intégrale des
archives et contrôle des cardinalités ajoutés au script avant le rejeu.


## Contrôles locaux

- **402 tests du socle synthétique**, dont 34 nouveaux cas documentaires et
  deux variantes supplémentaires de cohorte ; **54 tests historiques** :
  **456 tests réussis** au total.
- Ruff lint/format et mypy strict validés sur le socle, les tests, les deux
  nouveaux modules et le script de validation annuelle.
- Projections fermées et mutations de fuite : les dates médicales cachées,
  départs réalisés et destinations finales ne sont pas projetés. Retirer les
  événements futurs ne modifie pas les réceptions du préfixe déjà disponible.
- Révisions, doublons, annulations, prévisions dépassées ou au-delà de
  l’extraction, absence de demande, réouverture de demande et ancienneté par
  champ contrôlées. Un lot contenant un message invalide est rejeté avant
  modification de l’état.
- Les exports courts avec et sans enrichissement ont des présences,
  réconciliations et cibles identiques après neutralisation des identifiants
  de run. Les sorties enrichies sont reproductibles et la source est immuable.
- Les quatre combinaisons d’options recensement/enrichissement sont testées
  dans les cohortes, avec maintien des partitions et de la réservation du test.

Le script annuel vérifie toutes les réceptions de mouvements, recensements et
documents, puis toutes les lignes de présence, de réconciliation, d’enrichissement
et de cibles. Les sources documentaires n’entrent ni dans le curseur de présence
ni dans le calcul des cibles. Les empreintes du code et du script figurent dans
le [rapport machine](lot12_validation.json).

## Reproduire

```bash
PYTHONPATH=src python scripts/validate_synthetic_care.py \
  --source runs/synthetic/lot10/annual/truth \
  --output runs/synthetic/lot12/annual-verified
```

Le répertoire de sortie doit être nouveau. Omettre `--source` pour régénérer la
réalisation physique. La CI réutilise sa propre année de développement issue de
la vérification des recensements, puis exécute le même script. Ses résultats sont
suivis séparément des preuves locales dans la PR et la roadmap.

## Portée des résultats

La charge reste un proxy de soins de base sur 24 h, non SIIPS. Elle ne correspond
ni à la demande horaire totale du simulateur, qui applique d’autres multiplicateurs,
ni aux soins effectivement délivrés. La mobilité et la dépendance proviennent
des évaluations synthétiques, sans validation d’une échelle clinique réelle.

Les prévisions de sortie sont des annonces du staff synthétique, fondées sur le
cours latent courant bruité, pas les sorties réalisées. La confirmation d’aval
utilise encore le seuil « départ programmé moins 18 h », sous condition de préparation
médicale. Ce mécanisme peut fournir un signal artificiellement favorable à la
prévision de sortie. Le respect des horloges ne démontre pas sa plausibilité réelle.

La prochaine étape proposée est de diversifier ces mécanismes et de réserver des
variantes à l’évaluation. Les notes, l’encodeur appris, l’adaptation et le raccordement
patient à la politique restent ouverts. Ce lot ne clôture ni la phase 0 ni la porte SYN.
