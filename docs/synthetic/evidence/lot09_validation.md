# Validation du lot 09 — 15 octobre 2026

Le lot ajoute les profils `site_v1` aux états d’unité. Les chiffres ci-dessous
proviennent du [rapport machine](lot09_validation.json), produit par
`scripts/validate_synthetic_observations.py`. Toutes les exécutions sont en
développement ; aucun ensemble de test final n’est ouvert.

## Contrôles locaux

- **288 tests synthétiques**, dont 34 nouveaux pour ce lot : réussite (23,47 s).
- **54 tests historiques**, y compris les mutations de fuite et fusion documentaire :
  réussite (102,49 s). Total : **342 tests**.
- Ruff : lint et format du socle, des tests et du script de diagnostic réussis.
- Mypy strict : **29 fichiers** contrôlés, sans erreur.
- Les sources et le script du rapport correspondent aux empreintes du code livré.

Les nouveaux tests vérifient les profils invalides, l’identité historique par défaut,
la sous-documentation, la dépendance à la tension, les pannes globales/locales,
les fenêtres adjacentes, le blocage des corrections et doublons, le retard de
disponibilité après une ingestion antérieure, l’invariance du passé, la concordance
batch/direct, la borne d’extraction, l’abstention complète, les cohortes et les
exports reproductibles. L’invariance physique est testée pour `v041`, `local_v1`
et `hybrid_v1` à politique indépendante des observations.

## Trois profils, une même trajectoire physique

Chaque réalisation utilise 2 pôles, 4 unités, 365 jours enregistrés et 61 jours de
chauffe, avec la graine 41. La physique est recalculée indépendamment pour chaque
profil. Les cinq fichiers de vérité — événements, états des unités/pôles/hôpital
et ressources communes — sont **identiques octet pour octet** entre les trois
réalisations. Les configurations, observations et identifiants des jeux diffèrent.

| Profil | Réceptions | États distincts reçus | États non reçus à la borne | Corrections | Doublons | Lignes d’unité trop anciennes |
|---|---:|---:|---:|---:|---:|---:|
| Rapide | 41 825 | 40 662 | 234 | 825 | 338 | 0 |
| Lent | 37 074 | 36 057 | 4 839 | 722 | 295 | 1 798 |
| Intermittent | 39 666 | 38 567 | 2 329 | 774 | 325 | 216 |

Les états possibles comprennent la chauffe : **40 896 états unité–heure par
réalisation**. Les « non reçus » regroupent pertes et messages retardés au-delà
de l’extraction. Ce nombre n’est pas une estimation du seul taux de perte.

L’ancienneté est évaluée sur les **35 040 lignes unité–heure enregistrées**,
avec un seuil strictement supérieur à 6 h depuis l’événement. Aucune unité
n’est entièrement inconnue après la chauffe dans ces trois réalisations :
`unit_rows_missing = 0`. Cela ne signifie pas qu’il n’y a aucune perte de message.
Le scénario de perte totale est testé séparément : abstention et erreurs `null`.

Le profil intermittent comporte deux pannes de 48 h, hospitalière en avril
et limitée à `U_MED` en octobre. **238 réceptions d’événements survenus pendant
ces fenêtres arrivent ultérieurement**. Aucune ingestion ni disponibilité
ne tombe dans une fenêtre bloquée pour l’unité concernée.

## Année avec recommandeur sur observations

Une quatrième année utilise le profil intermittent et la politique à règles :

- **39 669 réceptions**, 61 320 lignes de variables, 365 contextes journaliers ;
- **5 840 lignes unité–jour–levier**, dont 797 actions demandées issues de
  recommandations approuvées et 486 initiatives du cadre ;
- 916 exécutions complètes, 125 partielles, 43 échecs et 199 demandes inapplicables ;
- rejeu des réceptions exactement égal aux variables produites en direct ;
- mêmes contrôles d’absence de réception pendant les pannes, borne incluse selon
  la convention début inclus/fin exclue.

L’égalité de vérité n’est pas exigée entre ce scénario et les trois précédents :
la politique utilise ici les observations et peut changer la trajectoire.

Sur les quatre simulations : **40 896 heures physiques contrôlées**, chauffe
comprise, sans violation des contraintes vérifiées. **51 empreintes de fichiers**
sont contrôlées. Les contrôles de stock–flux, lits, patients, compatibilités et
équilibre des transferts restent actifs à chaque heure.

## Portée

Ces résultats valident les contrats et les scénarios du générateur. Ils ne
mesurent ni réalisme hospitalier, ni gain prédictif d’un modèle entraîné,
ni généralisation G1–G4, ni adaptation AdaJEPA. Un profil explicite se transmet
aux réplications d’un établissement ; sa distribution aléatoire et sa calibration
sur statistiques publiques restent à construire. Les flux patient et notes
restent hors du nouveau contrat d’observation.
