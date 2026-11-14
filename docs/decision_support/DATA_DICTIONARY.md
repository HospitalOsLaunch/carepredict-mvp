# Dictionnaire de données — aide à la décision HospitalOS (prototype auto-first)

Toutes les données sont **synthétiques et pseudonymes** (`S01`…, `A01`…, `L01`…). Les paramètres
métier sont des hypothèses de démonstration : aucun entretien n'a été réalisé, aucune
calibration réelle n'est revendiquée. Schémas validables : `contracts/decision_support/*.schema.json`
(régénérés par `scripts/ds_export_schemas.py`, contrôlés par `test_p1_contracts.py`).

## Temps

- Tous les instants sont **UTC** (`datetime` avec fuseau, converti). L'affichage et les échéances
  civiles (« demain 20 h ») passent par `Europe/Paris` (`clock.py`).
- Heure locale ambiguë (changement d'heure d'automne) : `fold` explicite exigé, sinon
  `AMBIGUOUS_LOCAL_TIME`. Heure inexistante (printemps) : `NONEXISTENT_LOCAL_TIME`.
- Horizon : durée UTC réelle ≤ 24 h (`supported_horizon_hours`). Au-delà : `UNSUPPORTED_HORIZON`,
  jamais de troncature.
- `as_of` sur une heure pleine dans cette version ; grille horaire `h = 0..H-1`.

## Observation (`Observation`)

| Champ | Sens |
|---|---|
| `event_time` | date de l'événement |
| `available_at` | date à laquelle l'unité pouvait le savoir (≥ `event_time`) |
| `kind`, `subject` | type et sujet ; la dernière version utilisable par `(kind, subject)` gagne |
| `value` | contenu typé par `kind` (voir ci-dessous) |

Une observation n'est utilisable pour une décision à `as_of` que si `event_time ≤ as_of` **et**
`available_at ≤ as_of`. Les exclusions sont comptées dans `excluded_observations`.

Types : `bed`, `stay`, `medical_authorization` (`authorized|not_authorized|revoked`),
`discharge_logistics` (destination, besoin de transport, délai de réservation),
`readiness_estimate` (au plus tôt + distribution de retard, **estimation**),
`planned_departure` (**prévision** de la pratique habituelle, pas une certitude),
`care_profile` (minutes-soignant par heure jour/nuit et par compétence), `care_task`
(minutes, présence simultanée requise), `obstacle`, `admission_request`, `staff_shift`,
`roster_coverage` (planning déclaré complet sur une fenêtre ; absent ⇒ planning inconnu),
`reinforcement_option`, `team_capacity` (capacité et engagements extérieurs).

## PublicSnapshot

`snapshot_id`, `fingerprint` (SHA-256 canonique), `as_of`, `schema_version`, unité (profil
versionné), séjours, lits, admissions, planning, couverture du planning, options de renfort,
capacités d'équipes, `issues` (contradictions/manques explicites).

**Inconnu reste inconnu** : `None`/`"unknown"` n'est jamais converti en zéro ni en « disponible ».
Capacité d'équipe non déclarée sur une heure ⇒ 0 + heure marquée inconnue.

**Exclusions contractuelles** (modèles fermés, champs supplémentaires refusés) : heures réelles
futures de sortie, `ready_h`/`dis_h` privés, aléas futurs, bras contrefactuels, labels de résultat.
Les fixtures portent une section `private_truth` que `snapshot.py` ne lit jamais.

## ActionSpec / Plan

`ActionSpec` : `action_id`, `type` (`coordinate_discharge`, `reinforcement`, `locked_discharge`,
`locked_extension`), `target`, fenêtre, `preconditions`, `resources`, `reinforcement_hours`,
`interventions`, `validator`, `depends_on`, `idempotency_key`, `valid_until`, `origin`
(`auto|manual_lock`), `basis` (`observed_authorization|validated_instruction|hypothesis_only|resource_option`),
`conditional` (renfort demandé non confirmé).

Cycle séparé : demande → approbation → réservation (registre local de démo) → exécution
(**jamais** dans ce prototype) → résultat (non observé). Un renfort demandé n'est pas présent ;
une sortie autorisée n'est pas un lit propre.

`Plan` : actions, snapshot de départ, mode, actions verrouillées, hypothèses. Le plan vide est la
**pratique habituelle** `HABITUAL-1` (pas « ne rien faire »).

## ScenarioLocks (mode manuel X1/X2)

- `discharge_at` : sortie de X1 à une heure fixée ; `basis` = `validated_instruction` ou
  `hypothesis_only`. Une instruction « validée » sans autorisation observée est rétrogradée en
  hypothèse (diagnostic explicite).
- `extend_presence` : présence de X2 prolongée de `extension_hours` à partir de `reference_time`
  (heure de référence visible) ; `target_time = reference_time + t`.
- `reinforcement` : option de renfort imposée ou exclue.
- `deadline` : échéance civile (`day_offset`, `local_time`, `fold`).
Verrous contradictoires, sujet inconnu, heure hors horizon ⇒ `INFEASIBLE` (« scénario contradictoire »).

## ForecastBundle / Recommendation

Bundle : backend (nom, version, SHA-256 du code, `reads_private`, `product_allowed`),
configuration, snapshot, horizon, **graines de sélection** (rôle `selection_in_sample`),
hypothèses, rapport de recherche (`enumerated`, `evaluated`, `limit`, `complete`, règles de
filtrage, rejets motivés), évaluations, descripteur de score.

Par évaluation : admissibilité, violations, avertissements, `conditional_on`, métriques,
trajectoire horaire, `confirmed_only` (même plan sans renfort non confirmé), `effect_onset_hour`.

Unités natives des métriques :

| Métrique | Unité |
|---|---|
| `uncovered_care_minutes` | minutes-soignant non couvertes sur l'horizon = dans l'unité (compétence et présence simultanée) + soins des patients attribués en attente de lit + travail d'admission encore dû à la fin de l'horizon pour un patient arrivé non admis |
| `waiting_patient_hours` | patients × heures d'attente de lit |
| `beds_returned` | lits remis à disposition après départ (une fois par lit/départ) |
| `staff_scheduled` / `staff_reinforcement` / `staff_required` | personnes présentes par heure et compétence |
| `max_additional_staff_required` | max horaire de (requis − déjà prévu), calculé, non imposé |
| `reinforcement_hours` | heures-soignant de renfort du plan |
| `pressure_score` | 0–10, `PS-EXP-1` `EXPERIMENTAL_SYNTHETIC`, ou absent si `UNCONFIGURED` |

Règles ajoutées après l'audit (P2/P3bis) : heures de verrou et d'échéance **entières** obligatoires
(`unsupported_time_precision` sinon) ; heures « pas avant » observées arrondies à l'heure suivante ;
un verrou validé doit satisfaire les mêmes préconditions qu'une action automatique, sinon il reste
une hypothèse (heure conservée) ; un lit pouvant être libéré sans durée de nettoyage connue entraîne
l'abstention, sauf hypothèse configurée et signalée (`unknown_cleaning_assumption`) ; le planning de
chaque compétence requise doit être déclaré ; prêts de personnel contrôlés en cumul ; identifiants
adressés par le contenu ; revue : clé d'idempotence liée à `request_fingerprint`, rejeu avec
`replayed`/`current_validity`, conflit explicite sinon.

Statuts fonctionnels : `RECOMMENDATION_READY`, `NO_ACTION_PREFERRED`, `INSUFFICIENT_DATA`,
`INFEASIBLE`, `HYPOTHETICAL_ONLY`, `INVALIDATED` (ce dernier porté par la revue).
Statut scientifique figé : `PROTOTYPE_UNVALIDATED`, `clinical_validation=false`, `G2=NO-GO`.

## Objectif `OBJ-LEX-1` (fixé en P1, avant tout résultat)

0. Admissibilité stricte (sécurité, autorisation, ressources, ordre, verrous).
1. Minimiser `uncovered_care_minutes` (moyenne sur scénarios de sélection) ; tolérance
   d'équivalence 15 minutes.
2. À résultat équivalent : moins d'heures de renfort ; 3. moins d'interventions.
Égalité : la pratique habituelle gagne. Rapportés sans être optimisés : attente, lits remis à
disposition, admissions, trajectoire de pression. Les admissions ne sont **pas** un levier : le travail d'admission d'un patient arrivé et non admis reste dû (ajouté à la dernière heure), donc retarder ou refuser une admission ne peut jamais réduire le score (règle ajoutée en P2 après l'échec initial de T14, avant tout résultat de planification utilisé).
Convention de démonstration, pas une politique clinique validée.
