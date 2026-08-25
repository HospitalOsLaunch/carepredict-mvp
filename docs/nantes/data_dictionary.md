# Nantes Data Contract — Dictionnaire de données (HOS-003)

- **Réf. schéma** : `canonical@1.0.0` (`services/connectors/schemas/canonical_schema.yaml`)
- **Template de mapping** : `services/validation/nantes/nantes_mapping_template.yaml`
- **Timezone** : Europe/Paris (tz-aware obligatoire, DST-correct) · **Fréquence** : horaire · **Historique min.** : 90 j
- **Aucune donnée nominative** n'est demandée. Le preflight n'inspecte que le manifeste de colonnes.

## Horodatages (sur chaque enregistrement)

| Canonical | Colonne source attendue | Type | Sémantique |
|---|---|---|---|
| `temporal.event_time` | `horodatage_mesure` | datetime Europe/Paris | Temps métier de la mesure/état |
| `temporal.available_at` | `horodatage_disponibilite` | datetime Europe/Paris | Temps où la valeur devient connaissable (base Temporal-Leakage Gate, HOS-010) |

> **Règle available_at (critique fuite)** : `available_at` doit provenir d'une **source réelle de
> disponibilité** (lag d'ingestion / de reporting). Le défaut `available_at := event_time` est un
> **défaut de contrat** : il neutralise la Temporal-Leakage Gate. Le preflight n'inspecte que les **noms
> de colonnes** et **ne peut donc pas** détecter une dégénérescence de valeurs `available_at == event_time` :
> ce contrôle de niveau valeur est délégué au **Validator v2 (HOS-006)** et à la gate `available_at` (HOS-010).

## Identité (sur chaque enregistrement)

| Canonical | Source | Type | Requirement | Sensibilité |
|---|---|---|---|---|
| `identity.hospital_id` | `etablissement_id` | string | required | operational |
| `identity.service_id` | `uf_code` | string | required | operational |
| `identity.source_system` | (constante d'extraction) | string | required | operational |

## Domaines core

| Canonical | Source | Type · Unité | Requirement | Nullable | Sensibilité |
|---|---|---|---|---|---|
| `care_load.siips_score` | `score_siips` | number · points | required | non | operational |
| `care_load.patient_count` | `nb_patients` | integer · count | required | non | operational |
| `care_load.aas_score` | `score_aas` | number · points | optional | oui | operational |
| `flow.admissions` | `nb_admissions` | integer · count | required | non | operational |
| `flow.discharges` | `nb_sorties` | integer · count | required | non | operational |
| `flow.occupancy` | `nb_presents` | integer · count | required (stock — exigé en direct) | non | operational |
| `flow.transfers_in` | `nb_mutations_entrantes` | integer · count | optional | oui | operational |
| `flow.transfers_out` | `nb_mutations_sortantes` | integer · count | optional | oui | operational |
| `capacity.beds_total` | `lits_armes` | integer · count | optional | non | operational |
| `capacity.beds_available` | `lits_disponibles` | integer · count | optional | oui | operational |
| `staffing.nurse_count` | `etp_ide` | number · headcount | optional | non | operational |
| `staffing.aide_count` | `etp_as` | number · headcount | optional | non | operational |
| `staffing.overtime_hours` | (optionnel) | number · hours | optional | oui | operational |
| `staffing.avg_seniority_months` | (optionnel) | number · months | optional | oui | **restricted** (ré-identifiant en petit effectif) |
| `actions.action_type` | `type_action` | enum {staffing_change, discharge_planning, bed_management} | optional | non | operational |

> **`optional` (Nantes) vs `nullable` (canonical)** : `optional` signifie **domaine facultatif pour le
> pilote** — une extraction GO peut ne pas fournir staffing/capacity. En revanche, **si** un domaine est
> fourni, ses champs non-nullables (ex. `nurse_count`, `beds_total`) s'appliquent et sont contrôlés en
> HOS-006. Un GO preflight n'implique donc pas que tous les champs canonical non-nullables sont présents,
> seulement que le contrat de colonnes est satisfait. Si staffing **et** capacity sont tous deux absents,
> le preflight rend **RESTRICT** (jumeau réduit au forecasting).

## Colonnes interdites (NO-GO fail-closed)

Toute colonne dont le nom (normalisé, sans accents, minuscules) contient l'un de ces motifs déclenche NO-GO :
`nom, prenom, ipp, nir, ins, date_naissance, ddn, adresse, telephone, email, commentaire, motif, texte,
libelle_libre, note`. Rationale : nominatif ou texte libre — hors périmètre canonical, jamais ingéré.
