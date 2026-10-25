# Raccordement en lecture : contrat d'export et qualification locale

Statut : adaptateur local de recherche, 24 octobre 2026. Testé sur un format
fictif ; aucun flux SI hospitalier n'est connecté. Le composant prépare la
correspondance des données et leur diagnostic avant une observation de terrain.
Il ne fournit ni client HL7/FHIR, ni authentification, ni décision de soin.

Le contrat Nantes existant porte sur des agrégats horaires par unité. Il ne
permet pas de retrouver les patients, lits ou autorisations individuelles.
Ce lot utilise une extension explicite `UNIT_SOURCE_EXPORT_1` vers
`LIVE_OBSERVATION_BATCH_1` ; il ne modifie pas le schéma Nantes, ses gates ou ses
connecteurs. Un succès ici ne constitue pas un GO Nantes ou une autorisation
hospitalière. La mise à disposition du nouveau périmètre se cadre avec le site.

## Chemin livré

Un fichier JSON local → contrôle d'enveloppe et de colonnes → mapping explicite
→ contrôles temporels et de complétude → observations et audit dans `LiveStore`.
L'heure de réception vient du programme, pas du fichier. Aucun appel réseau ni
écriture dans un logiciel hospitalier. Le fichier source est ouvert en lecture
et n'est jamais modifié.

Le profil impose le site, l'unité, la source, la version de schéma et exactement
six tables : unité, lits, patients, pools, prérequis de sortie et confirmations
de disponibilité. Les noms des tables et colonnes sources sont configurables.
Le destinataire doit être une base en mode `shadow`.

Deux modes d'évaluation dans le profil :

- `quality_only`, **par défaut** : stockage des observations et diagnostic ;
  aucun calcul de plan, épisode de simulation, approbation ou commande.
- `shadow`, explicitement configuré : enregistrement d'un épisode hypothétique
  dans la même transaction que les observations et leur audit. Les contrôles
  d'état vivant restent bloquants. Les recommandations restent hors décision
  de soin pour que l'étude soit réellement silencieuse.

Le profil est figé dans la base, y compris le mode d'évaluation. Modifier une
correspondance ou passer à la simulation exige une nouvelle base ou une
migration revue ; aucune modification implicite à chaud n'est appliquée.

## Ce que le site doit fournir

| Élément | Contenu nécessaire |
| --- | --- |
| Dictionnaire d'export | Noms, types, unités, codes d'état, signification des valeurs inconnues et version |
| Périmètre indépendant | Manifeste complet des entités actives, sa version et la règle de retrait |
| Identités techniques | Identifiants pseudonymisés stables, cohérents entre lit, patient et sortie |
| Horloges | Date d'observation, disponibilité réelle dans la source et date de production d'export |
| Ressources | Résiduels disponibles après engagements, source autoritaire et confirmations observées |
| Corrections | Identifiant d'événement stable, version croissante ; même entité, source et instant d'événement |
| Observation pilote | Responsable de chaque donnée, fréquence réelle, procédure de panne/reprise et interprétation des écarts |

Le format attend des **instantanés complets d'une unité**, pas des messages ADT
incrémentaux. Toutes les tables doivent être présentes, éventuellement vides.
Les entités livrées doivent correspondre exactement au manifeste ; les
confirmations doivent couvrir la capacité soignante, le nettoyage et tous les
pools déclarés. Une ligne ou confirmation absente n'est jamais remplacée par
la valeur du précédent export. La complétude du manifeste reste une propriété
à vérifier côté site, hors de portée du fichier lui-même.

Les tâches en cours dans la cohorte et les pools multi-unités restent hors
contrat, comme dans [le lot état vivant](live-unit-pilot.md). Ne pas transformer
une situation non représentable en état « disponible » pour contourner un rejet.

## Correspondances et préflight

`SourceProfile.tables` contient pour chaque table un `kind`, son nom source,
`columns` (champ canonique → colonne exacte) et d'éventuels `value_maps`.
Tous les champs doivent être mappés, **y compris les champs nullable** : pas de
priorité clinique, autorisation, compatibilité ou capacité inventée par défaut.
Le type `TableMapping` vérifie le jeu complet à partir des contrats du dépôt.

- Les conversions de codes sont limitées aux états énumérés et booléens
  explicites. Par exemple `{"Y": true, "N": false}` pour un champ attesté par
  la source ; tout autre code est rejeté. `"False"` n'est pas converti en vrai
  parce que la chaîne est non vide.
- Les nombres sont des nombres JSON de type entier lorsque le contrat le demande.
  Une chaîne `"1"` ou un booléen ne devient pas une capacité.
- Les listes restent des tableaux JSON. Les inconnus restent `null` ; zéro est
  une disponibilité connue. Une absence de colonne est différente d'un `null`.
- Les dates sont des chaînes ISO avec offset explicite ou UTC. Les heures locales
  sans offset et les nombres interprétables comme timestamps sont rejetés.
  Les deux occurrences d'une heure au passage hiver restent deux instants distincts.
- `event_time` et `available_at` doivent venir de colonnes distinctes. L'égalité
  de leurs valeurs n'est pas une preuve de fuite, ni une preuve de validité :
  leur sémantique réelle doit être qualifiée avec la source.
- Pas d'expressions, de code dynamique, de dérivations implicites, de jointures
  floues, ni de déduction depuis un texte libre.

Le préflight ne lit que `ColumnManifest` : `schema_version=UNIT_SOURCE_COLUMNS_1`,
`source_schema` et `tables` contenant les listes de noms de colonnes. Colonnes
inconnues, manquantes, dupliquées ou nominatives connues bloquent la compatibilité.
La réussite vérifie uniquement le contrat de colonnes, pas les valeurs.

```bash
PYTHONPATH=src python -m hospitalos.hybrid.source_cli --example-profile
PYTHONPATH=src python -m hospitalos.hybrid.source_cli \
  --profile /chemin/prive/profile.json \
  --preflight /chemin/prive/columns.json
```

L'exemple est **fictif** et en `quality_only`. Il sert à établir un profil du site,
pas à prétendre connaître son schéma. Les modèles Pydantic fournissent aussi
leurs schémas JSON via `model_json_schema()`.

## Import, horloges et état de la source

```bash
PYTHONPATH=src python -m hospitalos.hybrid.source_cli --demo
PYTHONPATH=src python -m hospitalos.hybrid.source_cli \
  --profile /chemin/prive/profile.json \
  --policy /chemin/prive/live-policy.json \
  --import-export /chemin/prive/export.json \
  --db /chemin/prive/unit-shadow.sqlite
```

L'enveloppe contient `source_schema`, `export_id`, `hospital_id`, `unit_id`,
`source`, `exported_at`, `manifest_version`, `expected_entities` et `tables`.
La réception réelle borne la disponibilité des faits. Les événements connus
après la date d'export ou les exports datés dans le futur sont rejetés. Le rapport
sépare retard de la source, délai de transfert, âge des faits et âge des
confirmations ; un export récent peut contenir des observations périmées.

Les doublons JSON, les valeurs non finies et les lots excessifs sont rejetés.
Le budget est de 8 Mio par fichier, 2 000 événements, 100 confirmations et
400 entités déclarées. Ce sont des limites locales de prototype, pas une
qualification de débit ni une protection réseau complète.

Les faits, confirmations, audit d'import et éventuel épisode silencieux sont
commis ensemble. Un échec annule ces écritures. Le même export relu ne crée pas
un nouvel épisode et conserve la première réception ; un même identifiant avec
un contenu différent est rejeté. Un doublon renvoie un **rapport historique**
avec `current_state_assessed=false`, sans déclarer l'état actuel utilisable.

**Un rejet reçu par l'adaptateur bloque durablement la source**, même si les
anciennes observations sont encore dans leur durée de validité. Seul un nouvel
export complet dont les faits et disponibilités ont été observés au plus tôt
à l'instant de l'incident peut lever ce blocage. Un heartbeat, le renvoi du
fichier précédent ou une nouvelle enveloppe contenant les mêmes observations
anciennes ne suffisent pas. Les autres contrôles de cohérence/fraîcheur restent
applicables après cette reprise. Si le SI ne fournit que la dernière date de
modification, il faut définir un mécanisme attestant une nouvelle observation ;
la date d'export ne doit pas être substituée à cette confirmation.

Les erreurs d'ouverture/configuration **avant** l'appel de réception ne créent
pas de blocage de source ; l'orchestration du connecteur doit les superviser.
L'absence de flux entraîne en outre l'expiration habituelle des observations.
Aucun polling, supervision d'infrastructure ou notification externe n'est livré.

## Lire le diagnostic

Le rapport `UNIT_SOURCE_QUALITY_1` expose des nombres de lignes par type, des
comptages de champs inconnus, les tailles du manifeste et du lot, les motifs
normalisés de rejet/blocage, les retards maximaux et les empreintes du profil
et du contenu. Les valeurs nulles ne sont pas toutes des défauts : certaines
sont légitimes pour les patients en attente ou les ressources non requises.
Le compteur ne tranche pas seul leur signification métier.

| Statut | Signification |
| --- | --- |
| `REJECTED` | Export non accepté ; aucune ligne source du lot n'est stockée ; blocage de source sans contenu brut |
| `OBSERVATION_ONLY` | Observations reçues ; qualité seule ou état bloqué ; lire `state_ready` et les motifs |
| `SHADOW_EVALUATED` | État ayant franchi les contrôles d'entrée et épisode hypothétique calculé ; aucune efficacité démontrée |

`state_ready` décrit uniquement l'état **au moment de réception évalué**. Le code
CLI `0` indique un import alors sans blocage (ou un préflight de colonnes
compatible), `10` un import bloqué ou un doublon nécessitant une vérification
actuelle, `20` un rejet et `1` une erreur de fichier/configuration. Aucun de ces
codes n'autorise l'usage clinique.

Les sorties CLI et erreurs contrôlées n'affichent ni identifiants patients,
ni valeurs sources, ni détails d'erreur Pydantic. Les noms canoniques de champs
et les comptages sont conservés. Les lignes rejetées ne sont pas persistées ;
leur diagnostic est retourné à l'appelant, avec un marqueur de blocage durable
sans contenu brut. Les observations acceptées et l'audit restent dans la base locale.

Ce composant **ne pseudonymise pas** les données. La déclaration
`upstream_pseudonymized_ids=true`, le contrôle de noms de colonnes et les types
ne prouvent pas leur anonymat ; un identifiant peut contenir une information
identifiante sans être détecté. Minimisation, pseudonymisation amont, accès,
conservation, sauvegarde et qualification du périmètre restent à organiser avec
le site. Aucune base, donnée patient, configuration du site ou sortie d'exécution
ne doit être versionnée dans Git. La PR contient seulement code, tests et documentation.

## Passage à un premier export du site

1. Recevoir le dictionnaire et un manifeste de colonnes sans données patient.
2. Remplir le profil avec le responsable de chaque donnée et lancer le préflight.
3. Qualifier les horloges, codes, inconnus, liens entre entités et ressources sur
   un export minimisé/pseudonymisé, dans l'environnement retenu avec l'établissement.
4. Mesurer les défauts et retards sur plusieurs réceptions, y compris panne,
   doublon, correction et reprise ; définir les seuils acceptables avant évaluation.
5. Activer éventuellement la simulation silencieuse selon le protocole du pilote.
   L'assistance aux équipes et toute exécution hospitalière restent des étapes distinctes.

Le branchement réel nécessite encore le format et l'accès autorisé fournis par
l'établissement. Il n'est pas réalisé par ce lot.
