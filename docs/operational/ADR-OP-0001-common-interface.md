# ADR-OP-0001 — Interface opérationnelle commune de recherche

Décision du 15 octobre 2026, après accord de Guy sur la revue du contrat et sur
une première expérience complète. Statut : implémentée pour la recherche,
validation d'un connecteur hospitalier réel non réalisée. Le réel reste après SYN.

## Problème

`rs_jepa.train` et `train_stage2` utilisent encore `rs_jepa.synthetic`. Les lots
hospitaliers produisent un autre corpus. Le contrat Nantes v1 de la PR #2 est une
autre interface, à granularité service. Une expérience utilisant les deux côtés
doit séparer observations accessibles, vérité, topologie et hypothèses du moteur.

## Décision

Introduire `hospitalos.operational` et le contrat `OPERATIONAL_V2_RESEARCH_1`.
Le consommateur as-of n'importe aucun simulateur. Les noms d'entités identifient
la structure mais ne sont pas des embeddings entraînés. Les observations peuvent
venir d'une unité, d'un pôle ou d'un établissement. Une frontière mixte est possible
si elle couvre le périmètre sans superposer parent et enfant.

La topologie est un arbre unité → pôle → établissement → GHT, avec pôle optionnel,
validité et disponibilité datées. Un extrait limité à une unité ou un agrégat
peut être une topologie racine autonome. Les enfants inconnus n'ont pas à être
inventés. La version disponible à l'origine est choisie explicitement. La première
expérience utilise une topologie constante ; réorganisations et GHT couplés restent
à éprouver par des expériences dédiées.

Le socle ne demande aucun identifiant patient. Les domaines ADT, demandes d'aval,
urgences événementielles et actions sont des extensions futures versionnées ; ils
ne sont pas artificiellement déclarés livrés par l'ajout de colonnes vides.

Le contrat Nantes v1 et le chemin de service existant restent distincts. Les deux
correctifs du validateur v1 sont proposés dans une PR dédiée basée sur la PR #2.
Ce nouveau module ne remplace pas implicitement le validateur ou le pilote Nantes.

## Sémantique commune

| Variable | Unité | Traitement |
|---|---|---|
| `occupancy` | patients présents | Stock à l'instant de l'observation |
| `open_beds` | lits ouverts | Capacité observée, distincte de la capacité nominale |
| `ed_waiting` | patients | Demandes de lit en attente vers le périmètre ; pas tous les passages aux urgences |
| `medically_ready` | patients | Disponibilité médicale documentée ; pas un blocage d'aval causal |
| `nurse_count`, `aide_count` | personnes présentes | Effectifs présents, pas l'absentéisme brut |
| `care_workload_proxy` | minutes synthétiques par heure | Proxy du générateur, non utilisable comme mesure SIIPS réelle |
| `siips_score` | points SIIPS | Champ séparé ; aucune conversion depuis le proxy |

Les valeurs absentes restent absentes ou nulles ; zéro reste une mesure observée.
Le dictionnaire est fermé, les nombres non finis et comptes fractionnaires sont
refusés. Les états à la même entité/instant provenant de sources distinctes sont
refusés sans réconciliation explicite. Une version corrigée ne remplace pas les
prévisions passées. Les retransmissions identiques ne rafraîchissent pas le fait.
L'interface est un contrat de données, pas une garantie d'anonymisation d'identifiants.

`event_time` et `available_at` sont requis. `recorded_at` et `ingested_at` sont
optionnels quand le site ne les fournit pas ; tout ordre connu est vérifié.
Les instants sont normalisés en UTC, avec fuseau explicite à l'entrée. Le calendrier
métier est une information séparée utilisée pour les variables calendaires.

## Horloge : portée exacte

Le contrat conserve les instants et distingue les deux heures répétées d'automne.
Le consommateur peut utiliser `Europe/Paris`. Le moteur actuel conserve son
calendrier UTC+01 fixe : l'export porte `source_clock=fixed_utc_plus_01_no_dst` et
la première expérience utilise ce même calendrier. **Le moteur n'est pas passé à
Europe/Paris.** Les journées 23/25 h, profils d'arrivée et équipes nécessitent un
lot physique, pas un renommage de fuseau. La porte 0 complète n'est pas déclarée
franchie pour le réel.

## Export synthétique

L'adaptateur utilise les livraisons observées existantes, avec leurs pertes,
retards et versions. Un agrégat est publié seulement quand chaque unité membre
dispose d'une observation au même instant métier. Sa disponibilité est celle du
dernier membre. Les corrections produisent des versions d'agrégat. Les flux agrégés
ne contiennent pas de valeurs fines et n'utilisent pas les lignes de vérité pour
combler un manque. Cette construction est une hypothèse de flux, pas une preuve
de réalisme des exports agrégés hospitaliers.

La capacité nominale et les capacités techniques sont supposées connues au début
du monde ; elles sont des attributs structurels, pas des paramètres latents de
durée de séjour. Dans un connecteur réel, leur disponibilité devra être établie.

## Première expérience et limites

Le modèle partagé `TopologyForecaster` utilise l'historique observé et le contexte
des nœuds voisins et du périmètre. Il accepte un nombre variable de nœuds avec les
mêmes poids. Il prédit des moyennes conditionnelles : leur somme est l'estimand
agrégé approprié. Il ne publie pas de détails d'unité à partir d'un seul total.
La cohérence vaut pour les agrégats issus d'une même frontière d'observation.
Deux expériences recevant des informations différentes (unités ou totaux seuls)
ne sont pas contraintes à produire la même prévision conditionnelle.

Ce modèle constitue une première référence neuronale, pas un RS-JEPA connecté,
un pré-entraînement auto-supervisé, une distribution jointe ou un world model
achevé. L'ancien entraînement RS-JEPA est conservé ; il faudra évaluer son
remplacement ou son adaptation sur ce contrat à partir des résultats de cette
expérience. Aucun transfert réel ni bénéfice d'adaptation n'est établi ici.

## Critères de la livraison

- Export et lecture par le même contrat indépendant de la source.
- Absence de valeurs fines dans un flux agrégé, absence de détail prédit inventé.
- Invariance du préfixe en ajoutant des livraisons futures, respect des versions.
- Invariance des prévisions à l'ordre des nœuds et passage à un nombre inédit.
- Références quotidiennes et climatologiques ; aucune exclusion des origines
  pour observations périmées ; vérité de validation ouverte après gel des prévisions.
- Tests finaux réservés non générés ; rapports et poids de l'expérience traçables.
