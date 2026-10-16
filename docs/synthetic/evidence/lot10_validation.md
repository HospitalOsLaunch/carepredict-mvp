# Validation du lot 10 — 15 octobre 2026

Les contrats de mouvements et de censure passent les contrôles. La campagne
annuelle révèle toutefois une dégradation importante sans recensement de contrôle :
**cette réalisation n’est pas prête au préentraînement telle quelle**. Le prochain
lot doit traiter la réconciliation des états observés.

Les chiffres proviennent du [rapport machine](lot10_validation.json) produit par
`scripts/validate_synthetic_patients.py`. Aucun ensemble de test final n’est ouvert.

## Contrôles du code

- **332 tests synthétiques**, dont 44 nouveaux : réussite (35,89 s).
- **54 tests historiques**, y compris mutations de fuite et fusion documentaire :
  réussite (112,77 s). Total : **386 tests**.
- Ruff et contrôle de format : réussite, 34 fichiers.
- Mypy strict : réussite, 33 fichiers incluant le script de diagnostic.
- Sources et script conformes aux empreintes enregistrées dans le rapport.

Les nouveaux tests vérifient le schéma fermé, la minimisation de l’âge, les quatre
horloges, les arrivées hors ordre, corrections et annulations, l’idempotence,
l’absence de réécriture du passé, les pannes, les frontières d’extraction et
la censure. Ils couvrent aussi la reconstruction sans admission reçue, les sorties
perdues, conflits de lit, lots de messages rejetés atomiquement, sorties sans
admission et exports reproductibles.

Sans perte, délai ni erreur, le recensement dérivé des mouvements correspond
exactement à chaque occupation unité–heure dans les trois organisations
`v041`, `local_v1` et `hybrid_v1`. Une fixture de cohorte vérifie le rattachement
des jeux patient aux établissements et partitions, sans ouvrir les hôpitaux de test.

## Campagne annuelle

Configuration de développement `hospital_observation_intermittent_v1.json` :
2 pôles, 4 unités, graine 41, 365 jours enregistrés après 61 jours de chauffe.
Elle contient une panne hospitalière de 48 h en avril et une panne de 48 h de
`U_MED` en octobre, avec une probabilité de perte de mouvement de 5 %.

| Mesure | Valeur |
|---|---:|
| Demandes/séjours physiques, chauffe comprise | 4 925 |
| Séjours ayant au moins une ligne observée pendant l’année | 4 296 |
| Réceptions patient | 14 462 |
| Événements distincts reçus | 14 252 |
| Révisions reçues | 88 |
| Doublons de transport reçus | 122 |
| Lignes patient–heure | 1 808 744 |
| Lignes de cibles correspondantes | 1 808 744 |
| Séjours ouverts et censurés à l’extraction | 74 |
| Parmi eux, séjours effectivement admis | 74 |

Les 74 séjours censurés gardent leur départ inconnu, leur borne de suivi et
leur masque de censure. Aucune date de sortie future n’est exposée.

Chaque réception en ligne correspond exactement à l’export hors ligne.
Chacune des **1 808 744 lignes de variables** est comparée à sa reconstruction
par le curseur en ligne, puis à sa cible indépendante. **11 empreintes de fichiers**
sont vérifiées. Les **10 224 heures physiques**, chauffe comprise, passent les
contrôles de conservation des lits, patients et flux sans violation.

## Limite révélée : accumulation d’incertitude

| Signal | Lignes | Part des lignes patient–heure |
|---|---:|---:|
| Dernier fait vieux de plus de 96 h | 1 447 595 | 80,03 % |
| Lit apparemment occupé par plusieurs séjours | 1 387 489 | 76,71 % |
| Absence physique réelle à la décision | 1 151 621 | 63,67 % |
| Admission non reçue | 117 423 | — |
| Demande d’admission non reçue | 79 365 | — |

Ces catégories peuvent se chevaucher. L’absence physique inclut les patients
encore en attente réelle et les états conservés après une sortie perdue ; ce
n’est pas un décompte pur de séjours fantômes. L’âge d’un fait peut aussi être élevé
pendant un séjour long sans mouvement. Une admission manquante est normale pour
une demande en attente : les masques ne sont pas des estimations directes des pertes.

Le curseur conserve volontairement les faits reçus, sans inventer de sortie ni
consulter la vérité pour les corriger. Les erreurs de présence s’accumulent donc
quand le flux ne comporte que des mouvements perdables et aucun recensement
permettant une réconciliation. La conservation physique du simulateur ne garantit
pas la qualité de ce recensement observé.

Les lignes sans présence vraie à la décision reçoivent des cibles de départ
`null`. Parmi les lignes à risque, 1 481 cibles à 24 h, 2 722 à 48 h et 3 780 à
72 h sont censurées faute de suivi complet. Les positifs déjà observés restent
étiquetés positifs même si l’horizon théorique dépasse la borne.

**Décision de suite :** construire une source de recensement patient elle-même
observée, retardée et versionnée, avec règles de réconciliation explicites. Elle
doit réduire l’incertitude sans transformer une absence dans un recensement
incomplet en sortie certaine. Ce chantier précède le préentraînement et
l’enrichissement par la charge, les sorties prévisionnelles et l’aval.

Ces résultats valident les propriétés du contrat et identifient un domaine
d’échec du flux. Ils ne démontrent ni réalisme clinique, ni performance prédictive,
ni généralisation G1–G4, ni adaptation d’un modèle.
