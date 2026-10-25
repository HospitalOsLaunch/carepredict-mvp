# Fin de préparation : contrat d'événements et audit rétrospectif

Statut : contrat logiciel proposé et testé sur données fictives, 24 octobre 2026.
Le mapping métier n'a pas encore été validé par un service hospitalier. Aucun flux
réel n'a été consulté, aucun apprentissage réel n'est autorisé par cet audit.
Le calendrier projet situe les premières données réelles au plus tôt en mars 2027.

## Événement cible à faire confirmer par le pilote

À D, le patient doit être observé comme autorisé à sortir, avec les prérequis
logistiques attestés, et sa préparation opérationnelle encore en cours. La cible
est la première fin de cette préparation, avant l'attente des ressources d'aval
et de transport que le simulateur gère séparément.

| Information | Rôle | Substitution interdite |
|---|---|---|
| Autorisation médicale et prérequis confirmés | Éligibilité observée à D | Prédiction de l'aptitude médicale |
| Préparation `pending` | Preuve connue à D que le travail reste à finir | Absence de message de fin |
| Préparation `completed` | Événement cible, avec date de réalisation | Date prévue ou date du départ |
| Départ effectif | Contrôle chronologique et anomalie si cible absente | Label de fin de préparation |
| Suivi continu confirmé | Périmètre dans lequel un non-événement est observable | Silence d'un flux incomplet |

La tâche doit correspondre au reliquat réel de travail après les prérequis déjà
représentés dans HYBRID_MVP_2. Si ce reliquat n'existe pas dans le processus local,
la durée doit être supprimée ou le découpage revu, plutôt qu'inventer une latence.
Si le SI n'enregistre pas cet événement, instrumenter une tâche adaptée ou choisir
une autre cible et revoir le simulateur avant tout entraînement.

## Mapping candidat, sans connecteur livré

FHIR R4 `Task` permet de suivre l'état d'une activité ; `Task.executionPeriod.end`
décrit sa fin d'exécution. Un `Task.code` local et un statut `completed` pourraient
porter notre cible si leur sens est confirmé par le service. `Task.businessStatus`
peut préciser une étape locale. Cette correspondance est une proposition de
mapping, pas une sémantique universelle de fin de préparation hospitalière.

La fin d'un `Encounter` décrit le séjour, pas nécessairement la fin de ce travail.
L'heure de modification d'une ressource ne remplace ni l'heure de réalisation ni
l'heure où HospitalOS pouvait réellement la lire. Conserver l'historique des
versions : la dernière ressource seule ne permet pas de reconstruire D.

Sources primaires : [Task R4, définitions](https://hl7.org/fhir/R4/task-definitions.html)
et [Encounter R4, définitions](https://hl7.org/fhir/R4/encounter-definitions.html).

## Contrat canonique `PREPARATION_ENDPOINT_AUDIT_1`

`retrospective.py` lit un batch JSON local, après mapping du SI vers ce contrat.
Il n'implémente ni extraction FHIR/HL7 ni accès à un DPI.

- `Landmark` : établissement, patient pseudonymisé, épisode, unité, source et
  version de mapping ; origine D, disponibilité du snapshot, éligibilité attestée
  et variables de charge/calendrier. Un patient n'a qu'une origine dans le batch,
  toutes partitions confondues. Le snapshot doit provenir d'une extraction à D
  contrôlant fraîcheur et disponibilité des observations ; cet audit ne reconstruit
  pas lui-même les variables depuis le SI brut.
- `PreparationEvent` : identifiant physique `record_id`, identifiant logique
  d'occurrence `event_id`, révision, périmètre patient/épisode/source, type,
  `occurred_at`, `available_at`, éventuelle rétractation. UTC obligatoire ;
  une occurrence future n'est pas une observation.
- `Followup` : début et fin du suivi continu, date de disponibilité de cette
  attestation et indicateur de complétude. Cette attestation couvre la capture
  des fins de préparation et des événements concurrents ; elle ne peut pas être
  déduite automatiquement d'une dernière date d'extraction ou d'un dernier message.
- `TemporalProtocol` : quatre fenêtres d'origines et leurs dates limites de labels,
  séparées par l'embargo de suivi déjà utilisé par le modèle.

L'identifiant logique représente une occurrence, pas tout le cycle de vie de la
tâche. Les transitions `pending` puis `completed` sont deux occurrences. Une
révision corrige une occurrence existante. Un adaptateur FHIR doit donc projeter
l'historique des changements d'état et distinguer transition et correction.

La provenance est `synthetic_fixture` ou `observed_unvalidated`. Ces métadonnées
ne constituent ni une preuve d'autorisation d'accès ni une signature de source.
Les fichiers réels restent dans l'environnement autorisé du pilote ; aucune
identité directe, note clinique libre ou extraction réelle ne doit entrer dans
ce dépôt de code public.

## Construction des labels

Les conditions d'entrée sont vérifiées avec ce qui était disponible à D. Les
labels utilisent uniquement les versions disponibles à la date limite de leur
partition. Une correction arrivée ensuite ne réécrit pas ce jeu gelé. Une nouvelle
version de cohorte doit porter une nouvelle date de gel et relancer l'audit.

Une fin de préparation observée avant la fin du suivi et avant ou à D+24 h produit
un événement. Sans événement, une censure à droite n'est possible qu'avec suivi
continu attesté depuis D jusqu'à la borne retenue. La durée exacte reste en
secondes ; aucune conversion silencieuse d'une observation réelle n'est effectuée.

Sont notamment exclus et comptés :

- snapshot disponible après D, éligibilité inconnue, préparation en cours non attestée ;
- absence, trou ou disponibilité tardive de l'attestation de suivi ;
- source inattendue, révisions contradictoires ou non ordonnées ;
- fin de préparation rétractée, plusieurs fins concurrentes, preuve tardive que
  le patient était déjà préparé avant D ;
- départ avant une fin de préparation documentée ;
- décès, transfert, annulation ou retrait d'éligibilité avant ou au même instant
  que la cible. Un départ simultané est accepté seulement si la cible est aussi
  présente ; il ne la remplace jamais.

Ces exclusions ne constituent pas un traitement statistique des risques
concurrents : elles peuvent sélectionner une population différente. L'audit
expose les dénominateurs et motifs ; une étude réelle devra définir un estimand,
un traitement des risques concurrents et analyser ce biais de sélection.

Une suppression d'événement ne devient pas un faux non-événement. Une restauration
par révision ultérieure est prise en compte si elle était disponible à la date
de gel. Les contrôles de structure (identités et unicité physique) portent sur
le batch fourni ; les décisions de label et les conflits de révision portent
sur les observations visibles à leur date limite.

## Sortie et limites de l'audit

`PREPARATION_COHORT_AUDIT_1` expose labels acceptés, exclusions et comptes par
partition, avec `real_training_approved=false` dans tous les cas. La CLI imprime
les comptes agrégés seulement. L'accès programmatique aux lignes permet un audit
local, sans publication des patients.

Le pont `synthetic_record` permet de tester événement → label → séparation
temporelle sur des fixtures. Il refuse `observed_unvalidated` et les durées qui
nécessitent un choix de discrétisation en dessous de la minute. Les premières
mesures réelles devront aussi documenter les retards de saisie, corrections,
pertes de suivi et écarts de mapping entre services.

## Exécution locale

```bash
PYTHONPATH=src python -m hospitalos.hybrid.retrospective --schema
PYTHONPATH=src python -m hospitalos.hybrid.retrospective --demo
PYTHONPATH=src python -m hospitalos.hybrid.retrospective --demo --show-input > /tmp/preparation-fixture.json
PYTHONPATH=src python -m hospitalos.hybrid.retrospective --input /tmp/preparation-fixture.json
```

Le démonstrateur inclut volontairement un départ dont la fin de préparation est
absente : il doit être exclu. Aucun batch ou résultat généré n'est versionné.

## Travail terrain restant

Faire confirmer le découpage par le bed manager et le cadre, identifier le
champ/tâche et son propriétaire, vérifier sur quelques parcours les trois
horloges (réalisation, saisie, disponibilité), puis définir les origines et dates
de gel avant toute ouverture du test. Examiner les taux d'exclusion par service
et les parcours concurrents avant de décider si la cible est exploitable.
Cette confirmation métier et un export autorisé sont encore manquants.
