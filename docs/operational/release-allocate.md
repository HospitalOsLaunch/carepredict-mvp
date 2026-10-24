# WM-0 — lot libérer → attribuer

24 octobre 2026. Statut : mécanismes exécutables sur cas fictifs, revue en PR.
Ce lot étend le socle hybride ; il ne valide ni un pilote, ni une prévision,
ni l'efficacité réelle d'une intervention. Aucun logiciel hospitalier n'est appelé.
L'extension suivante ajoute les [arrivées et perturbations futures](future-events.md)
sans changer les attestations médicales et logistiques décrites ici.

## Comportement

Une autorisation médicale de sortie ne libère pas immédiatement un lit.
Le moteur vérifie les attestations logistiques, attend les ressources déclarées,
simule le départ, le bionettoyage puis une admission compatible avec la capacité
soignante. Il conserve les surcharges observées à D et bloque les admissions
supplémentaires qui dépasseraient la capacité.

Le cadrage métier s'inspire de la [check-list HAS de sortie d'hospitalisation](https://www.has-sante.fr/jcms/c_2035081/fr/check-list-de-sortie-d-hospitalisation-superieure-a-24h),
qui distingue continuité, information du patient et logistique, avec des items
applicables selon la situation. Les champs ci-dessous sont une abstraction
d'ingénierie à valider localement, pas la check-list HAS ni une autorisation clinique.

## Contrat de données v2

Les faits `HYBRID_MVP_2` réutilisent source, `event_time`, `available_at`, version
et manifeste du périmètre. Les nouvelles entités ont leur propre fraîcheur
au niveau du fait ; les TTL par attribut restent à développer.

| Entité | Champs | Sens |
| --- | --- | --- |
| `patient` | `medically_cleared` | Autorisation attestée par un professionnel, jamais calculée |
| `patient` | `downstream_confirmed` | Acceptation de la destination lorsque nécessaire ; n'alloue pas une place |
| `discharge` | `id` | Identifiant du patient concerné |
| `discharge` | `documents_ready` | Attestation métier que les documents requis sont prêts |
| `discharge` | `escort_required`, `escort_confirmed` | Besoin d'accompagnement et confirmation s'il est nécessaire |
| `discharge` | `downstream_required`, `downstream_pool_id` | Besoin d'une place dans un pool d'aval identifié |
| `discharge` | `transport_required`, `transport_pool_id`, `transport_requested` | Besoin de transport, pool compatible, demande déjà confirmée |
| `pool` | `resource`, `unit_ids`, `available` | Type, unités desservies et capacité résiduelle attestée à D |

Les booléens sont stricts. `None` signifie inconnu ; `required=False` signifie
explicitement non applicable. Un retour à domicile sans transport ni place d'aval
peut ainsi être représenté sans inventer une confirmation d'aval. Une ancienne
paire « médicalement sortant + aval confirmé » ne suffit plus à simuler un départ.

Une logistique absente ou non confirmée bloque le départ concerné ; les autres
actions restent examinables si l'état global est cohérent. Un pool périmé,
contradictoire, de capacité inconnue ou référencé hors de son périmètre entraîne
l'abstention. Les corrections reçues après D ne déverrouillent pas l'état à D.

`available` est une capacité résiduelle, après engagements extérieurs à la cohorte :
nombre d'équipes simultanément disponibles pour le transport, nombre de places
libres non déjà réservées pour l'aval. Les patients de cette cohorte ne peuvent
pas déjà avoir une réservation d'aval ou un transport en cours à D dans cette
version. Ne pas convertir un flux réel contenant ces cas en inventant des zéros.

## Dynamique et ressources

1. Seuls les patients déjà autorisés médicalement et dont la logistique est
   confirmée peuvent entrer dans la préparation de départ simulée.
2. Un délai résiduel hypothétique produit l'événement `departure_ready`.
3. La file est ordonnée par instant de disponibilité, priorité professionnelle
   fournie puis identifiant. Les places d'aval et équipes de transport sont
   partagées entre toutes les unités déclarées du pool.
4. Une place d'aval est réservée lorsque le transport peut démarrer, ou juste
   avant un départ sans transport. Elle reste consommée jusqu'à la fin de
   l'horizon : aucune libération d'aval future n'est supposée.
5. `transport_start` mobilise une équipe. `transport_depart` permet le départ
   effectif et libère le lit ; l'équipe reste occupée jusqu'à `transport_end`,
   après un délai supplémentaire de fin de mission/retour.
6. Le lit devient sale au départ, puis propre à la fin du nettoyage. L'admission
   respecte compatibilité, réservations et capacité soignante disponible.

Les fins de service à un même instant sont traitées avant les nouvelles
allocations. Une mission inachevée à l'horizon conserve sa ressource ; un
transport non encore parti conserve aussi le patient dans son lit.

Les délais `departure_minutes`, `transport_minutes`, `transport_return_minutes`
et `cleaning_minutes` sont des supports discrets déclarés, avec un facteur de
charge commun. Les tirages sont indexés par graine, scénario, mécanisme et entité.
Changer la décision ne raccourcit pas artificiellement une durée de service.

## Décision et validation humaine

Le catalogue ajoute `request_transport(patient_id, bed_id)` aux réservations et
priorités de nettoyage. La demande est proposée seulement si elle est attestée
non encore faite et si les autres prérequis sont confirmés. Une demande inconnue
n'est pas traitée comme une demande absente. L'envoi sandbox revalide les faits
et ne modifie pas automatiquement les observations.

La simulation conditionne les scénarios sur la réalisation de l'action proposée.
Elle suppose que cette demande est prise en compte : ni l'adhésion, ni le taux
de succès d'un transporteur ne sont estimés. La différence avec la référence
est une différence entre hypothèses simulées, pas un effet causal mesuré.

La politique de référence alloue déjà les lits propres selon les priorités
professionnelles fournies. Une admission dans la trace est une transition du
simulateur, pas une commande d'attribution envoyée à un DPI. Le workflow conserve
approbation humaine, expiration, revalidation et réconciliation sans retry aveugle.

La sortie `discharge_readiness` expose les blocages : autorisation médicale non
confirmée, logistique bloquée, transport à demander ou prêt pour simulation.
Ce dernier statut ne promet ni un départ ni une heure de départ.

Sans hypothèses d'arrivées, `service_status` concerne les patients en attente
d'un lit connus à D. Avec l'extension de scénarios futurs, les arrivées simulées
s'ajoutent à cette file :

- `not_assessed` : état ou mécanique ne permettant pas l'évaluation ;
- `served_in_all_sampled_scenarios` : aucune attente résiduelle dans cet échantillon ;
- `unserved_in_some_sampled_scenarios` : attente résiduelle dans au moins un scénario.

`no_change` ne signifie donc pas que tout est résolu. Aucun de ces statuts n'est
une preuve d'infaisabilité globale, une garantie probabiliste ou un résultat CP-SAT.
Le catalogue reste borné à une seule action immédiate ; sa troncature est visible.

## Démonstration et qualification locale

```bash
PYTHONPATH=src python -m hospitalos.hybrid --demo-pathway --show-trace
PYTHONPATH=src python -m hospitalos.hybrid --demo-pathway --show-input > /tmp/pathway.json
PYTHONPATH=src:. uvicorn services.api.hybrid_app:app --host 127.0.0.1 --port 8010
curl -H 'Content-Type: application/json' --data-binary @/tmp/pathway.json \
  http://127.0.0.1:8010/hybrid/plan
PYTHONPATH=src:. pytest -q tests/hybrid
```

Le cas fictif à un lit sert d'oracle calculable à la main : préparation 30 min,
prise en charge jusqu'au départ 45 min, nettoyage 30 min. L'admission apparaît
à D+105 min. L'équipe de transport n'est à nouveau disponible qu'après son
délai supplémentaire de 30 min. Ce sont des hypothèses de test, pas des mesures.

La qualification comprend :

- oracles de parcours et conflits de ressources entre deux unités ;
- absence de personnel, aval saturé, logistique inconnue et perturbations combinées à D ;
- événements simultanés, fin de mission après départ et troncature à l'horizon ;
- correction future, péremption, mauvais périmètre et revalidation à l'envoi ;
- journaux falsifiés : étapes omises, départ prématuré, double consommation de
  place, transport au-delà de la capacité, mauvais pool et fin prématurée ;
- matrice de cinq régimes de ressources × quatre graines × douze scénarios ;
- comparaison appariée vérifiant que demander un transport ne modifie pas ses
  durées physiques et que les autres conditions inchangées produisent la même trace.

Le notateur reconstruit ressources et parcours depuis le journal, sans appeler
le générateur de transitions ni son helper de prérequis de sortie. Il reste dans
la même base de code ; ce n'est pas une expertise externe indépendante.

## Migration et limites

Le changement de contrat est explicite : `HYBRID_MVP_1` et les propositions
`HYBRID_PLAN_1` ne sont pas migrés silencieusement. Reconstituer les faits v2 et
régénérer les propositions avec `HYBRID_PLAN_3` (la v2 était celle de ce lot avant
l'extension de scénarios futurs). Conserver les anciens journaux
pour audit et réconcilier tout résultat inconnu avant une éventuelle nouvelle
demande ; ne pas réémettre une commande en changeant simplement sa version.

Les données OPERATIONAL_V2 agrégées ne permettent pas de reconstruire ces entités.
Un flux patient/ressource adapté reste nécessaire avant le pilote.

L'extension suivante couvre les nouvelles arrivées, fermetures d'admission et
variations de capacité après D. Restent hors périmètre : transferts internes,
séjours des nouveaux admis, fenêtres d'accueil, annulations de transport/aval,
tâches déjà en cours à D, modèle de survie appris, calibration conforme,
planification CP-SAT, console métier, extraction des SI et exécution réelle.
Horizon maximal actuel : 24 h, sans extrapolation validée à 72 h.

Les tests vérifient une mécanique locale sous hypothèses. Ils ne font pas passer
G0 (fidélité réelle), G1 (calibration) ou l'intégralité de G2 (résistance en boucle
opérationnelle). L'extension de la dynamique sous hypothèses ne remplace pas
l'apprentissage des délais ni l'évaluation sur données réelles.
