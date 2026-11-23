# État vivant d'une unité et observation silencieuse

Statut : prototype local de recherche, 24 octobre 2026. Ce lot apporte les
contrôles d'ingestion, de disponibilité et de concurrence nécessaires pour
préparer un pilote. Il ne raccorde aucun SI hospitalier, ne commande aucun
transport et ne démontre aucun bénéfice clinique. Le boosting et le superviseur
expérimental ne sont pas activés dans cette boucle.

## Comportement livré

`LiveStore` conserve dans une même base SQLite le périmètre, les observations,
les confirmations de ressources, les évaluations silencieuses et, uniquement
en mode sandbox, les propositions, réservations locales et transitions.

- Une base correspond à un hôpital et une unité. La politique, les sources
  configurées, le mode et les seuils sont immuables après création. Un pool
  partagé entre plusieurs unités n'est pas accepté dans ce lot.
- Le mode par défaut est `shadow`. Il permet de conserver une évaluation
  hypothétique ; `LiveWorkflow` refuse ce mode. Aucune approbation, réservation
  locale ou commande n'est créée par le chemin silencieux.
- En sandbox explicite, une seule action peut être approuvée/en cours par unité.
  Plusieurs propositions peuvent être calculées, mais les suivantes doivent
  attendre la réconciliation de la première puis être recalculées. Ce choix
  évite de simuler des engagements locaux que le moteur ne représente pas encore.
- `BEGIN IMMEDIATE` protège dans une même transaction les dernières observations,
  leur revalidation et la prise de ressources. Deux connexions au même fichier
  ne peuvent pas approuver simultanément deux actions. **Cette garantie est locale** :
  elle n'empêche pas un opérateur externe d'utiliser la ressource dans le SI.

## Contrat à faire correspondre aux sources du pilote

Le connecteur doit produire `ObservationBatch` avec le manifeste complet des
entités actives, sa version et les événements `HYBRID_MVP_2` déjà définis. Une
modification du manifeste exige la version suivante. Une entité retirée reste
conservée dans l'historique ; une référence active devenue orpheline bloque.
La complétude du manifeste dépend du connecteur : le programme ne découvre pas
un patient absent de tous les flux.

| Information | Interprétation attendue | Confirmation requise |
| --- | --- | --- |
| Lit | État, unité, occupant, réservation, compatibilités attestées | Fait observé et horodaté ; aucun lit estimé n'est déclaré libre |
| Capacité soignante | `Unit.staffed_beds` = capacité totale attestée ; `staffed:unit` = places supplémentaires réellement disponibles | Résiduel après occupation, réservations et autres engagements |
| Nettoyage | `Unit.cleaning_teams` = équipes nominales ; `cleaning:unit` = équipes libres pour ce périmètre | Une équipe planifiée n'est pas présumée disponible |
| Transport | Pool résiduel après engagements extérieurs à la cohorte | `transport:pool`, cohérent avec `ResourcePool.available` |
| Aval | Places résiduelles effectivement utilisables et acceptation du patient | `downstream:pool` et attestation individuelle distinctes |
| Sortie | Autorisation médicale et prérequis logistiques | Observations métier ; aucune décision médicale inférée |

Chaque `Availability` contient `available`, `observed_at`, `source` et
`evidence_ref`. `None` signifie inconnu ; zéro signifie indisponibilité connue.
Une ressource inconnue, périmée ou contradictoire bloque l'évaluation. Un zéro
connu ne bloque que les actions qui en ont besoin : zéro place soignante libre
n'interdit pas de préparer le départ d'un patient déjà hospitalisé.

La simulation utilise une projection conservatrice séparée des observations :
les équipes occupées hors cohorte ne reviennent pas pendant l'horizon et la
capacité soignante mobilisable correspond aux places déjà engagées plus au
résiduel confirmé, plafonné par le total observé. Les faits originaux restent
intacts. Cette projection n'est pas un calendrier de tâches ; un état de tâche
non représentable doit être signalé inconnu par le connecteur.

## Deux horloges, fraîcheur et corrections

`ingest(batch, received_at)` reçoit l'heure du **récepteur de confiance**. Elle
ne vient pas d'un champ libre du message. Le stockage borne `available_at` par
cette réception ; les corrections tardives ne deviennent pas connues dans le
passé. Les dates source futures sont rejetées. Un lot s'insère entièrement ou
est annulé ; une retransmission identique n'actualise pas la confirmation.

La fraîcheur des faits utilise `event_time`, celle des ressources `observed_at`.
Un heartbeat reçu maintenant n'améliore ni l'une ni l'autre. Les confirmations
contradictoires au même instant restent bloquantes jusqu'à une observation plus
récente. Les sources configurées doivent toutes être cohérentes et fraîches ;
le connecteur doit expliciter leur autorité et les règles de retrait d'une source.
Une liste de noms de sources n'est **pas** une authentification.

Valeurs de recherche par défaut, à remplacer par les valeurs qualifiées du pilote :

| Contrôle | Défaut |
| --- | --- |
| Âge maximal des faits | 300 secondes |
| Âge maximal des confirmations de disponibilité | 120 secondes |
| Durée de validité d'une proposition vivante | 120 secondes |
| Réservation locale avant émission | 60 secondes, limitée par la proposition |

Ces seuils ne sont pas issus d'une validation hospitalière. La fraîcheur est
recontrôlée à chaque étape, même si la proposition n'est pas encore expirée.
L'empreinte sémantique compare les faits utiles, les valeurs de disponibilité
et le manifeste. Une confirmation plus récente de la même valeur reste
compatible ; une modification de capacité, patient, lit ou périmètre impose
un nouveau plan. L'empreinte brute et les observations restent dans l'audit.

Les opérations vivantes suivent une horloge monotone. Les lectures historiques
se font sur les épisodes figés, pas en mélangeant des réservations actuelles
avec un état ancien. Le fichier SQLite conserve l'historique réceptionné.

## Réservation locale, émission et réconciliation

Cycle sandbox : `proposed → approved → sent → acknowledged/unknown →
completed/not_executed`. `sent` peut aussi être réconcilié directement. Avant
`sent`, une proposition peut être rejetée avec motif. Après `sent`, elle exige
une réconciliation : l'émission est persistée **avant** retour de la commande,
et un crash peut laisser une livraison ambiguë.

- À l'approbation : relecture de l'état, du périmètre, des confirmations, de
  l'expiration et des prérequis ; réservation du lit/patient et des ressources
  nécessaires dans la même transaction. Les noms d'acteurs sont des métadonnées
  sandbox, pas des identités authentifiées.
- À l'émission : même revalidation et vérification de toutes les réservations.
  Le résultat porte `external_execution=false`. Aucune écriture SI n'a lieu.
- Une réservation **non émise** expire. Une réservation émise, acquittée ou
  inconnue ne se libère jamais sur simple timeout, même après redémarrage.
- L'accusé de réception ne prouve pas l'exécution. Un échec ambigu doit être
  marqué `unknown`, pas déclaré `not_executed` pour récupérer une ressource.
- Pour terminer : preuve liée à l'identifiant de commande, source configurée,
  observation récente après émission, faits liés et disponibilités réobservés
  après émission, puis attestation explicite que les comptes résiduels incluent
  les effets de la commande. Une demande de transport acceptée ne prouve pas
  le départ ; le patient doit être observé parti. Un nettoyage exige un lit
  propre ; une réservation exige le lit réservé ou occupé par ce patient.
- `not_executed` exige aussi une preuve liée à la commande et un état compatible.
  Il ne déclenche aucun retry ; une nouvelle proposition est nécessaire.

Ces contrôles vérifient la cohérence d'attestations locales. Leur authenticité
et leur lien effectif avec la commande doivent être garantis par le futur
adaptateur. Un état final compatible, seul, ne prouve pas sa cause.

Le résiduel affiché est `max(0, disponibilité confirmée − réservations locales)`.
Si les engagements locaux sont déjà intégrés dans le SI, un double décompte
conservateur peut subsister jusqu'à réconciliation. Une divergence reste visible
et ne libère jamais automatiquement une réservation. Définir la règle de
transfert de propriété de chaque ressource avant toute émission réelle.

## Exécution locale et observation silencieuse

```bash
PYTHONPATH=src python -m hospitalos.hybrid.shadow --demo
PYTHONPATH=src python -m hospitalos.hybrid.shadow \
  --policy /chemin/prive/policy.json \
  --batches /chemin/prive/receipts.jsonl \
  --db /chemin/prive/shadow.sqlite
```

Le premier mode utilise des données fictives : une évaluation possible, puis
un heartbeat qui laisse les confirmations périmer. Le second attend un fichier
JSON `LivePolicy` en mode `shadow`, puis des lignes JSON `ReplayReceipt` contenant
`received_at` et `batch`, dans l'ordre de réception. Ces heures sont des entrées
de replay ; elles ne remplacent pas l'horloge de confiance d'un connecteur réel.
Les résumés portent uniquement sur les épisodes créés pendant cet appel ; les
lots retransmis ne produisent pas de nouvel épisode.

L'API existante reste disponible. `create_app(live=shadow_store)` ajoute
`GET /hybrid/live` et `POST /hybrid/shadow` avec `PlanningOptions`, en utilisant
l'horloge serveur. Aucun endpoint d'ingestion, d'approbation ou d'émission n'est
exposé. L'instance globale ne configure aucun stockage vivant. Usage loopback
uniquement : pas d'authentification, d'autorisation, de limitation de débit,
d'isolation multi-hôpital ou de politique de rétention livrés ici.

Un épisode conserve l'état, les confirmations, la politique, la décision
hypothétique, les raisons de blocage et l'expiration. Il ne change pas après
correction tardive. Le résumé compte les évaluations possibles/bloquées et les
motifs avec leur dénominateur ; il ne calcule aucun bénéfice causal. Le stockage
n'émet pas de commandes, mais **l'absence d'influence humaine n'est pas garantie**
si les recommandations sont montrées aux équipes. Pour une phase réellement
silencieuse, réserver ces sorties à l'équipe d'évaluation hors décision de soin.

## Adaptateur de qualification en lecture

Le [contrat d’export et son adaptateur local](source-qualification.md) ajoutent
un mapping explicite, un préflight de colonnes et un diagnostic sans valeurs
patient. Le mode par défaut qualifie les données sans lancer de simulation.
Un export rejeté bloque la source jusqu’à de nouvelles observations complètes ;
aucun connecteur réseau ou branchement à un SI réel n’est livré.

## Conditions de passage au pilote

1. **Périmètre et données** : unité, responsables, sources autoritaires, manifeste
   exhaustif, interprétation de chaque résiduel, retards/corrections et changements
   d'heure. Conserver les instants en UTC et présenter les horaires locaux.
2. **Raccordement en lecture** : adapter les messages réels au contrat, mesurer
   leur retard et leur couverture, tester perte de flux, doublon, contradiction,
   retrait/réapparition d'entité et panne/reprise. Aucun raccordement n'est livré.
3. **Phase silencieuse** : figer protocole et critères avec les équipes, conserver
   séparément les décisions réellement prises et les issues observées. Évaluer
   complétude, blocages, fraîcheur, faisabilité et charge de réconciliation. Une
   concordance avec les pratiques ne démontre pas un effet sur l'attente.
4. **Modèles** : les alarmes de données/ressources de ce lot sont immédiates. Le
   contrôle de dérive prédictive exige des labels devenus disponibles, distincts
   des heartbeats et du résiduel de ressources. Ne pas activer automatiquement
   boosting/mélange sur la base des résultats synthétiques non concluants.
5. **Avant assistance opérationnelle** : authentification et rôles, protection
   des données, conservation, sauvegarde/restauration, exploitation et procédure
   de retour aux pratiques habituelles ; adaptateur avec réservation SI atomique
   ou validation humaine explicite lorsque cette garantie n'existe pas. Qualifier
   les tâches en cours et les ressources partagées avant d'étendre le périmètre.
6. **Évaluation prospective** : fixer les marges acceptables et le plan d'étude
   avant observation des résultats. Ni trois graines ni les tests logiciels
   ci-dessous ne remplacent cette évaluation.

La lecture du journal local est linéaire et le calcul peut garder le verrou
SQLite pendant une évaluation. Débits, volumétrie, tâches déjà en cours et
redondance restent à qualifier ; ce stockage n'est pas une architecture de
production distribuée. Ne pas verser de données patient, bases SQLite, modèles
sérialisés ou rapports d'exécution dans Git. Cette PR contient seulement le
code, les tests et les contrats documentés.

## Vérification

```bash
PYTHONPATH=src:. pytest -q tests/hybrid
ruff check src/hospitalos/hybrid services/api/hybrid_app.py tests/hybrid
ruff format --check src/hospitalos/hybrid services/api/hybrid_app.py tests/hybrid
PYTHONPATH=src:. mypy --strict src/hospitalos/hybrid services/api/hybrid_app.py tests/hybrid
PYTHONPATH=src python -m hospitalos.hybrid.shadow --demo
```

Les tests exercent l'absence de fuite des corrections, la réception sans
confirmation, la distinction inconnu/zéro, le décompte des équipes occupées,
la concurrence entre deux connexions, la revalidation avant émission,
l'expiration des seules réservations non émises, l'acquittement sans libération,
la persistance après statut inconnu et la réconciliation après observation.
Ils ne valident ni un connecteur réel ni les seuils de fonctionnement du pilote.
