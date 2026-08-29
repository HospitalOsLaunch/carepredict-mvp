# HFWM-R0 M3D.1 — Demande de revue partenaire du contrat de données

## Objet de cette demande

Nous demandons une **revue de faisabilité et de conventions**, pas encore des données.
La finalité candidate est le pilotage et l'évaluation de l'organisation des soins ; elle
reste à confirmer par l'établissement. Aucune donnée HCL, Nantes ou Dijon n'a été reçue ou
consommée. Nantes garde le rôle `FUTURE_M3F_HOLDOUT_ONLY` et aucune donnée Nantes n'est
demandée pour M3-L.

## Tier A prioritaire — agrégats unité-temps

Pour chaque site, unité et intervalle temporel proposé :

1. `patient_census_count` selon une définition administrative explicite ;
2. admissions externes effectives ;
3. sorties externes, décès et permissions modifiant le census ;
4. transferts entrants/sortants couplables par `transfer_event_id` ou règle auditée ;
5. autres ajustements signés, corrections et annulations ;
6. lits ouverts et lits indisponibles, avec validité temporelle ;
7. identifiants techniques de site/unité, intervalle, système source ;
8. `extract_generated_at`, règles de correction, version/last-modified si disponible ;
9. `recorded_at`, `available_at`, `ingested_at` et snapshots successifs si disponibles.

La granularité de six heures n'est **pas présumée stockée**. L'option retenue pour cette
revue est que l'établissement exécute, dans son environnement autorisé, la spécification
`HFWM_R0_M3_AGGREGATION_SPEC.yaml` sur ses mouvements horodatés et transmette uniquement
les agrégats Tier A et le rapport de conformité. Aucun mouvement pseudonymisé n'est demandé
à Spika à ce stade. Un census quotidien autoritatif, notamment au point de minuit retenu
par l'établissement, est demandé pour réconcilier la reconstruction.

Aucun identifiant patient n'est demandé au Tier A. Les petites cellules doivent suivre
une règle définie par l'établissement : suppression, regroupement ou accès contrôlé. Des
agrégats fins ne sont pas automatiquement anonymes ; le risque d'individualisation, de
corrélation et d'inférence reste à évaluer par l'établissement.

Propriétaires probables à confirmer : DPI/PMSI/DIM/interfaces ADT pour les mouvements ;
gestion des lits, direction des soins ou direction opérationnelle pour capacité et
fermetures ; DSI pour temporalité, versions et extractions.

## Périmètre calendaire demandé pour la revue de faisabilité

Le banc interne de planification et sa sensibilité à la dépendance entre sites se
traduisent par la plage candidate suivante à confirmer :

```yaml
continuous_history_months_minimum: 28
continuous_history_months_preferred: 36
hospital_sites_target: up_to_12_subject_to_comparable_unit_availability
hospital_sites_minimum_subject_to_blinded_recalculation: 8
site_count_semantics: FEASIBILITY_TARGET_NOT_INSTITUTION_WIDE_REQUIREMENT
comparable_unit_family: PARTNER_TO_CONFIRM
units_per_site: 4
temporal_granularity: candidate_granularity_subject_to_partner_disclosure_and_feasibility_review
candidate_aggregation_granularity: 6_hours_reconstructed_by_executable_spec
daily_authoritative_census_for_reconciliation: required
usable_start_date: after_last_non_bridgeable_information_system_break
end_date: latest_complete_period_available_for_feasibility_review

row_absence_reason:
  enum:
    - DISCLOSURE_SUPPRESSED
    - SOURCE_OUTAGE
    - UNIT_CLOSED
    - NOT_APPLICABLE
  required: true
extract_row_counts:
  expected_rows: required
  released_rows: required
  disclosure_suppressed_rows: required
  source_outage_rows: required
  unit_closed_rows: required
  not_applicable_rows: required
  disclosure_suppression_rate: required
disclosure_threshold: PARTNER_DPO_TO_CONFIRM
```

Cette plage est une demande de faisabilité, pas une demande de données ni un engagement
de disponibilité. Merci d'indiquer, pour chaque site et source :

- la date de dernière migration majeure du SIH ;
- la date du dernier changement de DPI ;
- la date du dernier changement de gestion des lits ;
- les dates de modification des conventions de census ;
- les ruptures de codage et périodes de double run ;
- l'existence d'une table de correspondance validée entre conventions ou systèmes.

La fenêtre exploitable commence après la dernière rupture rendant les variables non
comparables, sauf table de correspondance validée. La préférence de 36 mois vise trois
cycles saisonniers et une marge de 60 % d'attrition ; 28 mois constitue le minimum demandé,
pas une garantie de puissance. **8 sites = `feasibility_floor`**. La qualification finale
dépend de `N_effective` après exclusions/attrition et du `blinded sample-size
recalculation`. Si douze sites, quatre unités par site ou cette profondeur
ne sont pas plausibles, la réponse attendue est le périmètre calendaire réellement
documentable ; M3-L demeure non autorisé jusqu'à un recalcul blinded de la structure, de
la variance et des ICC.

Les sites et unités proposés doivent appartenir à une famille opérationnellement
comparable, à confirmer par l'établissement : activité d'hospitalisation, conventions de
census, structure des flux, activité continue, capacité documentée et absence de rupture
SIH non franchissable. MCO adulte, SSR, maternité, pédiatrie et urgences ne sont pas
regroupés silencieusement.

## Contrat de disclosure statistique — question DPO

Quel standard de Statistical Disclosure Control les HCL exigent-ils pour les agrégats
Tier A, et la sortie résultante est-elle qualifiée par les HCL/DPO de donnée anonyme ou
demeure-t-elle une donnée personnelle/pseudonymisée ?

Le seuil ou la règle de petites cellules reste `PARTNER_DPO_TO_CONFIRM` : aucune valeur de
`k` n'est imposée. Si une ligne `site × unit × time_window` est supprimée, la ligne entière
est supprimée, son `row_absence_reason` est conservé, un gap temporel est créé et aucun
épisode ne peut franchir ce gap. Les champs stock et flux ne sont jamais masqués
partiellement et les valeurs supprimées ne sont jamais reconstruites à partir des lignes
adjacentes.

Scénarios de gouvernance à qualifier par HCL/DPO :

- **A** : traitement interne HCL et transmission d'un résultat réellement anonymisé ;
- **B** : Spika sous-traitant sur instructions documentées ;
- **C** : recherche, étude ou évaluation avec accès externe pseudonymisé après gouvernance ;
- **D** : responsabilité conjointe si finalités et moyens sont effectivement codéterminés.

## Questions générées des conventions supposées

La liste complète est générée automatiquement dans
`artifacts/hfwm-r0/m3d/partner_questions.json` depuis toutes les conventions
`status: assumed`. Les points prioritaires sont :

- « occupation » est-il un census, une présence physique, un taux ou autre chose ?
- bloc, permission, mutation administrative et hébergement temporaire changent-ils le
  census source ?
- quelle heure fait foi pour chaque mouvement et correction ?
- un transfert A→B a-t-il un identifiant commun aux deux jambes ?
- l'historique d'`available_at` et des corrections existe-t-il ?
- quelle source fait foi pour les lits ouverts/indisponibles ?
- quelles ruptures de source et réorganisations d'unités sont documentées ?

Sans `available_at` historique, le projet reste rétrospectif avec limite explicite. Après
accord partenaire seulement, des extractions prospectives append-only pourront établir
une observabilité de fraîcheur. `extract_generated_at` ne sera jamais substitué
silencieusement à `available_at`.

## Tier B — uniquement sur justification formelle

Un Tier B ne peut être demandé que si une question impossible à résoudre avec Tier A est
documentée. Sa demande séparera finalité, variables minimales, gouvernance, environnement
d'accès et analyse de risque. Aucun identifiant patient ou donnée plus fine n'est inclus
par défaut.

## Gouvernance publique HCL à considérer

Statut de toutes les affirmations ci-dessous :
`PROVISIONAL_PENDING_DPO_AND_GOVERNANCE_CONFIRMATION`.

- **COSTRAT — Comité Stratégique** : orientations stratégiques et scientifiques et
  catalogue de l'EDS ;
- **COMOR — Comité d'orientation des projets** : évaluation des projets au regard de la
  stratégie du COSTRAT, à l'appui des avis CIDS et du **Comité Scientifique et Éthique de
  la recherche sur les données de santé** — abrégé `CSE` par la gouvernance EDS et désigné
  `CSE-EDS` dans ce document pour éviter toute ambiguïté ;
- **CIDS — Cellule d'Ingénierie des Données de Santé** : faisabilité légale, technique,
  financière et méthodologique et préparation des jeux de données ;
- **CSE-EDS — Comité Scientifique et Éthique de la recherche sur les données de santé** :
  pertinence scientifique et éthique.

Le règlement intérieur HCL emploie aussi `CSE` pour le **Comité Social d'Établissement**
(article 21). Cette instance représentative du personnel est distincte du `CSE-EDS` visé
ici. L'article 111 du même règlement établit que les HCL opèrent un Entrepôt de Données de
Santé pour la recherche en santé et les études relatives au pilotage hospitalier. Cette
mention ancre l'existence et les finalités générales de l'EDS ; elle ne préjuge pas du
circuit d'autorisation de ce projet.

Ces quatre instances et leurs missions sont décrites par la page publique actuelle des
HCL consacrée à la recherche médicale sur données. Aucun nom de portail, rythme de comité
ou ordre séquentiel supplémentaire n'est affirmé dans cette demande.

## Cadrage juridique et rôles — provisoire

```yaml
regulatory_status: PROVISIONAL_PENDING_DPO_AND_GOVERNANCE_CONFIRMATION
hospital_role: CONTROLLER_EXPECTED_TO_CONFIRM
spika_role: TO_BE_CONFIRMED_BY_DPO
allowed_spika_role_values:
  - PROCESSOR
  - JOINT_CONTROLLER
  - SEPARATE_CONTROLLER
  - TO_BE_CONFIRMED_BY_DPO
own_purpose_reuse_allowed: false_unless_separately_authorized
product_promotion_use: forbidden
```

Le référentiel CNIL EDS, article 3.1.2, couvre notamment le pilotage stratégique lorsqu'il
est réalisé exclusivement à partir de l'entrepôt, par les personnels habilités du
responsable et pour son usage exclusif. Un partenaire externe impose donc une qualification
juridique et opérationnelle par l'établissement ; cette finalité n'est pas une exemption
acquise. Spika ne peut être qualifiée de sous-traitant que si elle agit sur instructions
documentées sans finalité propre. Une codétermination effective des finalités et moyens
peut conduire à une responsabilité conjointe. Toute réutilisation propre nécessite une
autorisation séparée et sa qualification ; aucune donnée ne sert à promouvoir un produit.

L'accès externe à des données pseudonymisées, l'hébergement, les habilitations et les
transferts doivent être approuvés selon les exigences confirmées par le DPO et la
gouvernance. La pseudonymisation ne vaut pas anonymisation automatique.

## Références officielles consultées le 29 août 2026

- CNIL, référentiel EDS, sections 3.1.2 à 3.2 :
  https://www.cnil.fr/sites/default/files/atoms/files/referentiel_entrepot.pdf
- CNIL, qualification responsable/sous-traitant/responsables conjoints :
  https://www.cnil.fr/fr/reglement-europeen-protection-donnees/chapitre4
- CNIL, pseudonymisation et anonymisation :
  https://www.cnil.fr/fr/recherche-scientifique-hors-sante-enjeux-et-avantages-de-lanonymisation-et-de-la-pseudonymisation
- HCL, recherche médicale sur données et EDS :
  https://recherche.chu-lyon.fr/recherche-medicale-sur-donnees (section « Gouvernance :
  comment est animé l'entrepôt ? »)
- HCL, règlement intérieur, articles 21 et 111 et annexe 9 :
  https://www.chu-lyon.fr/sites/default/files/reglement-interieur-hcl.pdf

## Décisions attendues avant toute donnée

1. confirmer finalité, base/cadre applicable, rôles et environnement d'accès ;
2. confirmer définitions count/rate, census et capacité ;
3. confirmer temporalité, corrections, transfert couplé et disponibilité des champs Tier A ;
4. approuver la règle petites cellules ;
5. déterminer si le Tier A suffit ;
6. maintenir Nantes hors périmètre M3-L ;
7. choisir `dijon_strategy: LOCAL_RETRAIN | TRANSFER_EVALUATION | UNDECIDED`.
