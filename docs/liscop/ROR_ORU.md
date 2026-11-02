# Export ROR et indicateurs ORU

Module `ror-oru-export`. Code : `services/admissions_smr/domain/ror.py` (export par unité,
pur), `domain/oru.py` (indicateurs quotidiens, pur), `api/routes_ror.py` (routes minces),
`services/admissions_web/src/pages/RorPage.tsx`. **Rien n'est envoyé** au ROR, à Inéa ni à
l'ORU : la file `ror_outbox` ne contient que des envois `simulated`.

## Sources

| Réf. | Document | Accès dans cette session |
|---|---|---|
| [J187] | JDV_J187_NatureCapacite_ROR, <https://interop.esante.gouv.fr/terminologies/ValueSet-JDV-J187-NatureCapacite-ROR.html> | Lu : 01 Lit, 02 Place, 04 Salle (version 20260928) |
| [J188] | JDV_J188_TypeStatutCapacite_ROR, <https://interop.esante.gouv.fr/terminologies/ValueSet-JDV-J188-TypeStatutCapacite-ROR.html> | Repris des phases précédentes : 01 Installé, 02 Disponible, 03 Occupé, 04 Réservé, 05 Fermé, 06 Supplémentaire |
| [J189] | JDV_J189_TemporaliteCapacite_ROR (TRE_R331), <https://interop.esante.gouv.fr/terminologies/ValueSet-JDV-J189-TemporaliteCapacite-ROR.html> | Lu : 01 Courant, 02 Prévisionnel 1 heure, 03 Prévisionnel 24 heures, 04 Prévisionnel 48 heures, 05 Prévisionnel 7 jours |
| [J190] | JDV_J190_GenreCapacite_ROR / TRE_R332, <https://interop.esante.gouv.fr/terminologies/CodeSystem-TRE-R332-GenreCapacite.html> | Repris : 01 Femme, 02 Homme, 04 Indéterminé (03 Indifférencié déprécié le 28/08/2025) |
| [J191] | JDV_J191_TypeFermetureCapacite_ROR, <https://interop.esante.gouv.fr/terminologies/ValueSet-JDV-J191-TypeFermetureCapacite-ROR.html> | Repris : 01 Réactivable, 02 Non réactivable, 03 Indéterminé |
| [IG] | ROR FHIR IG, extension `ror-location-supported-capacity`, <https://interop.esante.gouv.fr/ig/fhir/ror/StructureDefinition-ror-location-supported-capacity-definitions.html> | Lu (table différentielle) : noms des sous-extensions, cardinalités, jeux de valeurs liés |
| [CS] | ROR FHIR IG 0.1.1, CapabilityStatement serveur, <https://interop.esante.gouv.fr/ig/fhir/ror/0.1.1/CapabilityStatement-ror-serveur.json.html> | Lu : paramètres de recherche `Location` (`capacity-status`, `nb-capacity`, `additional-bed-type`, `capacity-closing-type`, `capacity-type`, `capacity-update-date`, `gender-capacity-available`, `temporality-capacity`, `temporary-assignement`) ; profil `ror-location` |
| [DEF] | ANS, *ROR — Capacité en lits — Indicateurs — Définitions* v1.0.1 | Repris de `domain/beds.py` (phase 1b) |
| [LISCOP] | Présentation du service LISCOP (ARS Hauts-de-France) et infographie ANS « éditeurs » | Repris du cadrage : colonnes affichées, légende, familles de capacité, canal EAI régional |

**Non vérifiés** (pages bloquées pendant la session) : le profil `ror-location` lui-même
(`StructureDefinition-ror-location.html`), et les codes de JDV_J192 TypeLitSupplementaire,
J193 TypeSourceCapacite, J194 TypeCrise, J195 AffectationTemporaire. Les champs
correspondants sont laissés vides (`null`) dans l'export.

## Extension `supported-capacity` [IG]

| Sous-extension | Card. | Jeu de valeurs | Rempli par HospitalOS |
|---|---|---|---|
| `capacityType` | 1..1 | J187 | 01 Lit |
| `capacityStatus` | 1..1 | J188 | oui |
| `temporalityCapacity` | 1..1 | J189 | 01 (courant), 03/04/05 (prévisionnel) |
| `nbCapacity` | 1..1 | entier | oui |
| `capacitySourceType` | 1..1 | J193 | **non** (codes non vérifiés) |
| `genderCapacityAvailable` | 0..1 | J190 | sur les disponibles, quand l'unité a un plan des lits |
| `capacityUpdateDate` | 1..1 | dateTime | fraîcheur de l'unité ; date de calcul pour le prévisionnel |
| `capacityClosingType` | 0..1 | J191 | sur les fermés |
| `additionalBedType` | 0..1 | J192 | **non** |
| `crisisType` | 0..1 | J194 | **non** (les réservés crise-SSE sont exportés à part) |
| `temporaryAssignement` | 1..1 | J195 | **non** |
| `comment` | 0..1 | texte | non |

L'export donne ces enregistrements dans `unites[].ror_capacites` (noms de l'IG), une ligne
par combinaison statut × temporalité × genre × type de fermeture. Ce n'est **pas** une
ressource FHIR complète : il manque `Location`, l'identifiant ROR, les champs 1..1 non
remplis ci-dessus et le profil exact attendu par le canal (voir questions).

## Correspondance champ par champ

| Champ de l'export | Concept ROR / LISCOP | Code ANS | Source HospitalOS | Calculé / déclaré |
|---|---|---|---|---|
| `capacites[01]` | Installé | J188 01 | lits actifs de l'unité (`beds`) ; sans plan : `bed_pools.beds_installed` | calculé (plan) / déclaré |
| `capacites[02]`, `disponibles_par_genre.total` | Disponible, capacité disponible totale | J188 02 | lits utilisables (`domain/beds.py` : libre, au moins un sexe accepté, fermetures déclarées non portées retirées) ; sans plan : ouverts − présents − admissions promises à 24 h | calculé |
| `disponibles_par_genre.femme / homme / indetermine` | Capacité disponible F / H / indifférencié | J190 01 / 02 / 04 | sexe du lit × sexe des occupants de la chambre | calculé ; `null` sans plan |
| `disponibles_par_genre.isolement` | (pas de code ROR vérifié) | — | lits utilisables en chambre d'isolement | calculé |
| `capacites[03]` | Occupé | J188 03 | lits `occupe` ; sans plan : séjours présents | calculé |
| `capacites[04]` | Réservé | J188 04 | lits `reserve` (patient attendu sous 24 h) ; sans plan : admissions accordées pour aujourd'hui ou demain | calculé |
| `capacites[05]`, `fermetures[]` | Fermé, type de fermeture | J188 05, J191 | max(lits bloqués, fermetures déclarées) ; type par motif : personnel, saisonnier → 01 ; travaux → 02 ; lits bloqués au-delà des fermetures déclarées, autre motif → 03 | déclaré (motif) + calculé |
| `capacites[06]`, `operationnel.supplementaires` | Supplémentaire | J188 06 | `bed_pools.extra_beds` (`PUT /api/ror/units/{id}`) | déclaré |
| `operationnel.en_service` | Capacité opérationnelle en service (LISCOP) | — | installés − fermés | calculé |
| `operationnel.reactivables` | Réactivables (LISCOP) | J191 01 | fermetures de type 01 | calculé |
| `reserves_crise_sse` | Réservé en temps de crise / SSE (LISCOP) | J194 non vérifié | `bed_pools.crisis_reserved_beds` | déclaré |
| `previsionnel[]` (`disponibles_attendus`) | Capacité et disponibilité prévisionnelles J+1, J+2, J+7 | J189 03, 04, 05 ; statut J188 02 | `forecast_values` (dernière exécution `ok`, cible `available_beds`, portée `unit`) : moyenne, q10–q90, `p_tension`, `p_critique` | calculé (moteur de prévision) |
| `previsionnel[]` (`liberes_non_promis`) | — (pas une disponibilité ROR) | — | prévision des sorties (`build_forecast`), sans arrivées non programmées | calculé ; jamais transmis en `ror_capacites` |
| `tension` | Légende LISCOP normal / tension / critique | — | `domain/tension.py` : disponibles / installés, normal ≥ 20 %, critique à 0 | calculé |
| `fraicheur` | Fraîcheur de la donnée (LISCOP -3 h … -24 h) | `capacityUpdateDate` | le plus récent de : mouvement appliqué (`movements.received_at`), statut de lit (`beds.updated_at`), capacité (`capacity_changes.created_at`, `bed_pools.updated_at`), séjour saisi ou importé (`stays.updated_at`) | calculé |
| `identifiant_unite_ror` | Identifiant de l'unité dans le ROR | — | `bed_pools.ror_unit_id` | déclaré |
| `finess_geographique` | FINESS ET | — | `sites.finess` | déclaré |

### Indicateurs ORU (`GET /api/oru/indicators`)

| Colonne CSV | Source | Calculé / déclaré |
|---|---|---|
| Passages aux urgences | `ed_visits.arrived_at`, jour local (Europe/Paris) | calculé |
| Présents, En attente de lit, Hébergés hors unité à 10 h | `domain/ed.py` `daily_series` | calculé, remplacé par la déclaration du jour (`ed_snapshots`) |
| Lits brancards à 10 h / (calculé) / Source | idem ; la valeur calculée reste à côté de la déclarée | `calcul` ou `declaration` |
| Unités suivies / en tension / critiques | lits ouverts du jour (historique `capacity_changes`) − présents en fin de journée (séjours), légende LISCOP. Approximation : ni réservations, ni lits bloqués, ni genre (pas d'historique) | calculé |
| Hôpital en tension, Plan blanc | `tension_declarations` actives pendant le jour (site ou établissement) | déclaré par la direction |
| Prévision lits brancards 10 h (moyenne, bas, haut 80 %), calculée le | `forecast_values` portée `site`, cible `boarding_10h`, dernière exécution | calculé |

Jours futurs (jusqu'à J+7) : seules les colonnes de prévision sont remplies.

## Ce qui manque pour un flux réel

1. **Habilitation** de l'établissement (ou d'HospitalOS comme éditeur) à alimenter le ROR,
   avec l'ARS Hauts-de-France et le GRADeS (Inéa).
2. **Identifiants ROR** de chaque unité (UO), et leur lien avec nos unités (`PUT
   /api/ror/units/{id}`). Le format exact n'est pas vérifié ; la validation actuelle est
   volontairement large.
3. **Canal** : EAI régional d'Inéa ou ROR national directement (infographie ANS), avec
   l'authentification, le transport et la fréquence attendus.
4. **Profil exact** de la charge utile : ressource FHIR `Location` (profil `ror-location`),
   opération (mise à jour complète ou partielle), et les codes J192, J193, J194, J195.
5. Un vrai envoi remplacerait le statut `simulated` par un statut d'accusé de réception ;
   aujourd'hui aucun code n'émet de requête sortante.

## Questions à poser à Inéa

1. Le canal attendu pour un éditeur en Hauts-de-France : EAI Inéa ou ROR national ? Quel
   protocole, quelle authentification (certificat, OAuth), quel environnement de test ?
2. Le profil et la version de l'IG ROR à suivre (0.1.1, 0.6.0…), et un exemple de charge
   utile valide pour une unité MCO.
3. Les codes J193 (type de source : notre donnée est issue du SI / d'un calcul), J192
   (lits supplémentaires), J194 (crise / SSE), J195 (affectation temporaire) à utiliser.
4. Le prévisionnel : LISCOP lit-il les temporalités J189 03/04/05 du ROR ? Accepte-t-il une
   valeur calculée (moyenne arrondie) et peut-on joindre la fourchette et la probabilité de
   tension (en commentaire, ou ailleurs) ?
5. La disponibilité par genre et l'isolement : attendus pour toutes les unités ou seulement
   certaines disciplines ? Comment déclarer les lits d'isolement ?
6. La correspondance de nos motifs de fermeture avec J191 (personnel et saisonnier →
   réactivable, travaux → non réactivable) vous convient-elle ?
7. La fréquence d'envoi souhaitée (à chaque mouvement, toutes les N minutes) et le seuil de
   fraîcheur au-delà duquel LISCOP signale une donnée ancienne.
8. Pour l'ORU : format et canal des indicateurs (fichier CSV, API, RPU), la définition
   régionale de « lits brancards à 10 h », et l'usage des valeurs calculées vs déclarées.
9. Le format de l'identifiant ROR d'une unité et où le lire (export ROR, annuaire).
