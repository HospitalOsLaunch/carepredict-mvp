# Politique sur observations et journal de décision — lot 06

Le recommandeur peut maintenant intervenir pendant la simulation, à partir des
seules observations déjà disponibles. La réaction du cadre et l'application des
leviers restent deux mécanismes distincts. Le lot livre une interface et des
preuves d'exécution ; il n'entraîne pas de world model ou de politique optimale.

## Contrat de l'environnement

| Opération | Comportement |
|---|---|
| `reset()` | Initialise le monde et la chauffe commune, vide les journaux de politique, fournit l'observation de frontière 0 |
| `observe()` | Renvoie le contexte courant immuable, sans avancer ni modifier l'historique ; `None` après la dernière heure |
| `act(batch)` | À 9 h, valide le lot complet puis tire recommandations, exposition et décisions du cadre, et applique les demandes |
| `advance()` | Avance d'une heure, produit les nouvelles observations et ne délivre que celles disponibles à cette frontière |

À 9 h, avancer sans soumettre une décision ou une abstention explicite est refusé.
Une répétition exactement identique de `act` à la même frontière renvoie le reçu
existant ; elle ne réapplique pas les leviers. Une soumission différente à cette
frontière est refusée. Une réponse d'une ancienne heure, d'un autre contexte ou
d'une autre version est refusée avant toute application.

Un plugin reçoit seulement :

- `PolicySite` au démarrage : établissement, date et convention d'horloge,
  identifiants des unités/pôles et spécialités. Pas de graine ni d'état simulé.
- `PolicyContext` à la décision : horodatage et états unité/pôle/hôpital du
  contrat d'observation, avec sources, disponibilité et ancienneté.

Il renvoie une probabilité pour chacun des quatre leviers et chacune des unités,
une raison, son identifiant/version, l'empreinte de son code ou artefact, l'heure
et l'empreinte du contexte. Les modèles Pydantic sont fermés et immuables. Le lot
complet est revalidé à la frontière, même si un plugin Python a contourné son
constructeur. Un changement de version en cours de réalisation est refusé :
l'adaptation des poids n'est pas ajoutée par ce lot.

C'est une frontière de données pour du code de confiance, pas un bac à sable de
sécurité isolant un plugin Python hostile. Aucun connecteur hospitalier réel,
appel réseau d'action ou donnée patient réelle n'intervient.

## Observation pendant la simulation

Le moteur produit l'état de fin de l'intervalle `[h,h+1)`. Cet état entre dans
l'adaptateur à la frontière `h+1`, puis subit les retards de saisie, ingestion,
pannes, absences, corrections et doublons hérités. Une file conserve les reçus
futurs et les libère uniquement à leur date de disponibilité. Le recommandeur
ne reçoit ni cette file, ni ses tirages, ni le simulateur.

`ObservationStream` extrait le traitement par événement de l'adaptateur v0.4.1.
Le wrapper historique conserve ses livraisons et son ordre de tirages : un test
compare sa sortie complète au fichier publié au commit `4d0e4f9`. La physique
historique conserve aussi sa comparaison au moteur publié du lot 03.

`AsOfCursor` partage la reconstruction avec le rejeu du lot 02. Les corrections
anciennes ne remplacent pas un événement plus récent ; les doublons sont sans
effet, les versions contradictoires sont refusées, les unités manquantes ne sont
pas remplacées par zéro. Le rejeu du lot 05 sert aussi de référence de régression.
Chaque export du lot 06 vérifie **toutes** ses lignes de variables en les
reconstruisant à partir des reçus effectivement délivrés.

Les identifiants en direct désignent l'unité, l'heure de l'état et le reçu ; ils
ne dépendent pas du rang dans une future liste de livraisons. Les reçus après
la fin d'extraction ne sont pas exportés. Les états horaires de la période de
chauffe servent à initialiser la connaissance disponible au début de l'année.
La chauffe utilise la politique historique commune ; le plugin prend la main
à la frontière 0 et décide la première fois à 9 h.

## Deux politiques d'ingénierie

| Politique | Utilité |
|---|---|
| `no_recommendation` | Aucune recommandation du système ; le cadre peut toujours prendre une initiative |
| `observed_rules` | Règles simples sur occupation, attente, sortants documentés et charge par soignant observé |

Les règles n'utilisent pas les effectifs futurs, les dates vraies de sortie,
les arrivées futures ou la disponibilité future des renforts. Elles s'abstiennent
quand l'observation d'une unité manque ou dépasse six heures. Le ratio de charge
utilise une efficacité supposée de 0,84, déclarée comme choix d'ingénierie.
Les coefficients ne sont pas calibrés et aucune supériorité n'est revendiquée.
Le gradient boosting du lot 05 n'est pas transformé ici en recommandeur.

Quatre Bernoulli indépendantes conditionnellement au contexte tirent les
recommandations de chaque unité. L'exposition est commune à ses quatre leviers.
Le journal conserve les probabilités marginales et la probabilité du vecteur
réalisé, conditionnelle à ce contexte. Ce ne sont pas les propensions des actions
réellement exécutées ; la positivité n'est pas garantie dans tout l'espace.

## Le cadre reste un acteur distinct

Une recommandation présentée peut être approuvée ou refusée. Si elle n'est pas
présentée, ou si aucun conseil n'est donné pour un levier, le cadre peut agir
de sa propre initiative. Une initiative ne reçoit jamais l'étiquette « approbation ».

Le cadre simulé conserve le mécanisme historique : état courant privilégié et
facteur caché `z`. **Ce facteur est construit à partir des arrivées des 24 heures
suivantes dans le simulateur**, comme approximation synthétique d'une information
privée anticipatrice. Il ne s'agit pas d'une observation réellement disponible
prouvée en hôpital. Il reste dans `truth/cadre_private.jsonl.gz`, séparé des
contextes et des variables accessibles au recommandeur. Le lot ne supprime donc
pas le mécanisme de confusion cachée du corpus et ne rend pas l'effet des actions
identifiable par un simple ajustement sur les observations.

## Ce qu'une exécution signifie

| Statut | Sens |
|---|---|
| `not_requested` | Le cadre n'a pas demandé le levier |
| `applied` | Le mécanisme a modifié une capacité ou un plan ; deux postes confirmés pour un renfort |
| `partially_applied` | Un seul des deux postes de renfort est confirmé |
| `failed` | Aucun des deux postes de renfort n'est pourvu |
| `not_applicable` | Demande reçue mais aucun changement applicable : lits supplémentaires déjà actifs ou aucun plan éligible |

Les quantités ont des unités distinctes : plans patients modifiés, lits activés,
postes de renfort confirmés. Une anticipation de sortie appliquée n'est pas une
sortie réalisée, et n'est pas une mesure de gain. Les quatre leviers restent
appliqués dans l'ordre du moteur historique ; ils peuvent interagir.

L'exposition, la décision et la réponse d'exécution sont synchrones à 9 h dans
ce lot. Le renfort confirme à cette heure les postes de l'après-midi et du
lendemain matin ; leurs horaires sont journalisés. Les effectifs n'augmentent
qu'au poste correspondant. Les absences après confirmation et les délais de
passerelle ne sont pas simulés. Une confirmation concernant le lendemain de
la fin d'année reste un engagement connu ; aucune présence future n'est observée.

Les champs de chaîne sont validés entre eux et rapprochés du journal physique :
un refus ne peut pas produire une exécution, une action non demandée ne peut
pas toucher un patient, un lit ou un poste, une quantité ne peut pas contredire
son statut. La grille des décisions, les identités, versions et empreintes de
contexte sont vérifiées avant export.

## Exécuter

```bash
PYTHONPATH=src python -m hospitalos.synthetic.policy_loop \
  --config configs/synthetic/hospital_two_poles.json \
  --policy observed_rules --output runs/synthetic/lot06/annual

PYTHONPATH=src python -m hospitalos.synthetic.policy_loop \
  --config configs/synthetic/hospital_local_v1.json \
  --policy no_recommendation --days 10 --output runs/synthetic/policy-local
```

L'API accepte un plugin implémentant `descriptor`, `reset(site)` et
`recommend(context)`. La CLI expose seulement les deux politiques ci-dessus.
Les trois familles de ressources et les échelles unité/pôle/hôpital fonctionnent
avec la même interface. La partition `test` est refusée avant toute simulation.

Les sorties sont publiées atomiquement dans un nouveau dossier, après validation :

- `simulation/` : états vrais et événements physiques, avec manifeste propre ;
- `observed/` et `features/` : reçus réellement délivrés et états tels que connus ;
- `decisions/contexts.jsonl.gz` : contexte hospitalier présenté à chaque décision ;
- `decisions/recommendations.jsonl.gz` : sortie du plugin avant les tirages ;
- `decisions/ledger.jsonl.gz` : quatre lignes par unité et jour, avec chaîne complète ;
- `truth/cadre_private.jsonl.gz` : information et probabilités privées du cadre ;
- `policy.json`, `config.json`, `manifest.json` : provenance, versions, limites,
  contrôles et empreintes de chaque fichier.

Pour l'apprentissage ultérieur, conserver les observations émises en direct :
réappliquer un bruit d'observation après coup ne reconstituerait pas leurs
identifiants et ne serait pas le contexte effectivement présenté au décideur.
Les cibles de prévision devront être raccordées séparément à ces variables.
Les lignes de vérité et l'audit privé du cadre ne sont jamais des entrées du plugin.

## Vérification et suite

Les [preuves du lot 06](evidence/lot06_validation.md) conservent les résultats
annuels et les contrôles. Les tests couvrent les anciens adaptateurs, les
horloges, les mutations, les retries, les refus, l'initiative, les pourvois
partiels/nuls, les unités des reçus, le rejeu et la reproductibilité des exports.

La phase 0 reste ouverte. Le modèle hybride à règles, la diversification des
arrivées/sorties/effectifs et le protocole final restent à terminer. Le prochain
lot proposé porte sur cette diversité de mécanismes du générateur, avec leurs
réservations explicites. Les parcours patients tels que connus, les interventions
séquentielles et la politique apprise restent des chantiers distincts.
