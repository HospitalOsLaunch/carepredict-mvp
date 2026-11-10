# S0d — contrôle des dépendances entre mondes et des supports temporels

10 novembre 2026. Code de contrôle de métadonnées train/dev, testé sur fixtures
écrites à la main. **G1 non gelé ; G2 NO-GO.** Aucune qualification de corpus,
simulation, inférence ou autorisation d'entraînement.

## Usage et portée

`research_lab.s0d_cohort_separation.audit_cohort_metadata` complète l'audit
par monde `s0d_source_audit.py`. C'est une fonction pure : elle reçoit trois
objets déjà chargés et une empreinte épinglée indépendamment, sans ouvrir de
fichier, lire des archives, importer de modèle ou appeler le simulateur.

```python
from research_lab.s0d_cohort_separation import audit_cohort_metadata

receipt = audit_cohort_metadata(
    manifest,
    world_registry=world_registry,
    exposure_index=exposure_index,
    expected_manifest_sha256=operator_pinned_sha256,
)
```

L'appelant doit préparer **uniquement les métadonnées autorisées**. Aucun chemin
d'archive ni chargeur automatique n'est proposé. Les identifiants de preuves
sont des engagements, jamais des chemins que ce module pourrait résoudre.
Les objets ne sont pas modifiés. Le reçu n'expose que des compteurs, des
engagements et des codes de raison fixes, pas les identifiants d'épisodes.

## Relation avec la proposition documentaire V0

Le schéma implémenté est `hospitalos.s0d_cohort_metadata_v1`, une projection
exécutable train/dev du contrat documentaire S0d. Il ne se fait pas passer
pour le manifeste complet signé `hospitalos.synthetic_cohort_separation_v0`.

Un résultat favorable est **`CONSISTENT_METADATA_ONLY`**, jamais une
qualification de sources. Même avec des empreintes cohérentes, le module ne
peut pas vérifier la sincérité du lignage RNG, la complétude réelle des
événements de couplage, le contenu des exports, les signatures du producteur,
ou les frontières avec des mondes réservés. Il ne s'agit pas d'un simple
booléen d'attestation que l'appelant pourrait positionner à `true`.

`separation_status=NOT_QUALIFIED`, `source_authenticity_verified=false`,
`coverage_authenticity_verified=false`, `holdout_separation_status=NOT_TESTED`,
`supervision_status=NOT_QUALIFIED` et `statistical_design_status=NOT_QUALIFIED`
restent explicites après un contrôle cohérent. Les quatre autorisations
training/forward/simulation/promotion restent `false`.

## Contrat exact des entrées

Les objets du manifeste sont fermés : pas de clés inconnues, d'identifiants
dupliqués, de durées négatives/non finies ou d'horodatages sans offset.
Le test `fixture()` dans `tests/test_s0d_cohort_separation.py` fournit un
exemple intégral, fictif, lié aux deux interfaces S0c existantes.

| Objet | Champs |
|---|---|
| Racine | `schema`, `scope`, `mode`, `bindings`, `episodes`, `dependencies`, `worlds`, `samples`, `policy`, `coverage`, `preprocessing` |
| `bindings` | `world_registry_sha256`, `exposure_index_sha256` : engagements de l'intégralité des objets fournis |
| `episodes[]` | `id`, `root`, `parents`, `realization_sha256`, `initial_state_group`, `rng_groups`, `proof_sha256`, `start`, `end_exclusive`, `source_clock` |
| `dependencies[]` | `id`, `kind`, `members`, `start`, `end_exclusive`, `proof_sha256` |
| `worlds[]` | `id`, `episode`, `hospital_id`, `canonical_partition`, `registry_partition`, les trois champs S0c `source_manifest_sha256`, `observation_manifest_sha256`, `action_manifest_sha256` |
| `samples[]` | `id`, `world`, `role`, `origin`, `label_cutoff`, `support_start`, `support_end`, `uses` |
| `uses[]` | `lineage_id`, `event_id`, `version`, `kind`, `start`, `end`, `available_at` |
| `policy` | `history_steps`, `step_hours`, `horizons_hours`, `max_age_hours`, `aggregation_lookback_hours`, `recurrent_lookback_hours`, `extra_embargo_hours`, `bounds`, `model_spec_sha256` |
| `coverage` | `episodes`, `start`, `end_exclusive`, `completeness`, `proof_sha256` |
| `preprocessing` | `fit_sample_ids`, `proof_sha256` |

`scope` vaut exclusivement `train_dev_only`. Les listes sont bornées à 4 096
éléments chacune, et l'ensemble des références sources à 16 384. Parents,
dépendances et échantillons de fit peuvent être vides lorsque la sémantique
le permet ; la couverture doit lister tous les épisodes, y compris les
ancêtres sans monde sélectionné. `completeness=declared_complete` signifie
« déclaration présente », jamais « authenticité démontrée ».

Les `rng_groups` identifient les réalisations de flux effectivement partagées,
et non le nom d'un algorithme. L'état initial doit recevoir le même groupe
si la même réalisation a été réutilisée. Une configuration déterministe
commune ne suffit pas à relier deux épisodes. Le producteur doit canoniser
ces identités avant toute future qualification de sources.

## Deux modes et correspondance des partitions

- `independent_episode` : fermeture transitive du lignage et des dépendances ;
  toute composante traversant des rôles est rejetée, même à des dates disjointes.
- `within_episode_temporal` : seule la paire train/development_temporal peut
  partager une composante. Tous les supports train doivent précéder tous les
  supports dev de cette composante, y compris entre établissements distincts.
  Aucune indépendance d'épisode ou de site n'est revendiquée.

Les types de dépendance sont `transfer`, `shared_shock`, `shared_resource`,
`shared_staff`, `shared_rng`, `inherited_state`. La fin d'une arête ne supprime
pas ses effets hérités : le regroupement reste conservateur sur l'épisode
entier. Les ancêtres non résolus et les cycles empêchent la qualification.

| Source canonique | Rôle d'exposition | Partition du registre par monde |
|---|---|---|
| `train` | `train` ou `development_temporal` | `train`, même monde, plages distinctes |
| `validation` | `development_ood` | `development` |
| `test` ou rôle réservé | Aucun dans cette API | Refus |

Les hashes des triplets, identités hospitalières, mécanismes, durées et plages
d'origines sont rapprochés. Les métadonnées d'un monde train et de sa vue
chronologique doivent être identiques hors plages d'origines. La réutilisation
d'archives et le partage d'un groupe de graines entre partitions sont refusés.

Cette correspondance n'alloue pas une quatrième partition : une validation
finale distincte et un blind OOD restent à définir et à attester séparément.
Elle ne démontre pas non plus le caractère OOD d'une source simplement parce
qu'elle porte ce rôle dans l'index. Aucun registre canonique réservé n'est
chargé par cette API.

## Support temporel

La V1 retient des enveloppes fermées conservatrices. Pour N points espacés de
Δ heures, H maximal, âge A, agrégation passée B et mémoire supplémentaire R :

- support minimal gauche : `D - ((N-1)*Δ + max(A+B, Δ, R))` ;
- support minimal droit : `D + H` ;
- condition train/dev : `support_start_dev > support_end_train + E`.

R désigne une extension maximale **avant le premier point de grille**, pas
un état récurrent traversant arbitrairement les batches. Une mémoire non
bornée est non qualifiable. L'âge et l'agrégation se composent ; un intervalle
d'action étend au moins d'un pas le support à gauche. Les supports déclarés
peuvent être plus larges, mais jamais plus étroits que cette borne.

L'embargo E ne peut pas être réduit sous celui de l'index S0c. La première
version exige le pas horaire, les mêmes N/H et le même engagement du modèle
que l'index. Les supports doivent tenir strictement avant `end_exclusive`
de l'épisode ; cela peut refuser conservativement sa dernière origine.

Les références d'événements effectivement déclarées doivent tenir dans
l'enveloppe. Les observations/actions doivent être disponibles à D ; les
labels à leur cutoff séparé. Le couple `(lineage_id, event_id)` est comparé
sans numéro de version : une révision ne crée pas une observation indépendante.
La couverture réelle de tous les points de grille/cibles et les empreintes
exactes d'usage restent à vérifier contre les exports par le responsable des
données. Le présent module ne reconstruit pas les tenseurs de l'adaptateur.

## Résultats et matrice de vérification

Le contrôle s'arrête à la première anomalie : le reçu n'affirme donc pas avoir
inspecté toutes les règles d'une entrée rejetée. Une contradiction produit
`REJECTED`, un élément manquant/malformé `NOT_QUALIFIED`, une sélection réservée
`ACCESS_REFUSED`. Un retour cohérent est limité aux métadonnées soumises.

| Témoins du contrat | Couverture des tests |
|---|---|
| P1/P2/P5 | Épisodes indépendants, mêmes dates et mécanismes, sans revendication de source qualifiée |
| P3/P4 | Purge temporelle autorisée ; chevauchements internes au train comptés |
| N1/N5 | Réalisations, états initiaux ou RNG partagés malgré des IDs différents |
| N2/N14 | Transferts, chocs, ressources, personnel, forks et fermeture transitive, même après la fin d'une arête |
| N3 | Chevauchement contexte–cible, borne égale, carry-forward et agrégations, contrôle interhospitalier |
| N4/N6 | Provenance incomplète, ancêtres inconnus/cycliques, horloges et schémas invalides |
| N7/N8/N9 | Événement révisé partagé, disponibilité future, fit sur développement |
| N10/N11 | Triplette incohérente, réétiquetage et divergences entre registres |
| N12/N13 | Sélections réservées sans I/O ; empreinte externe et falsification des registres |
| N15/N16 | Statistique et supervision demeurent non qualifiées, même après succès des contrôles |

Le test de N13 vérifie l'ancrage d'intégrité, **pas une signature de producteur**.
Les cas à réaliser sur des preuves authentiques restent non exécutés.

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -q \
  tests/test_s0d_cohort_separation.py \
  tests/test_s0c_synthetic_registry.py tests/test_s0c_world_registry.py
python3 -m ruff check research_lab/s0d_cohort_separation.py tests/test_s0d_cohort_separation.py
python3 -m mypy --strict research_lab/s0d_cohort_separation.py tests/test_s0d_cohort_separation.py
```

Ces commandes ne lisent aucune archive réservée et n'exécutent aucun modèle.
La suite générale du dépôt a un périmètre différent, incluant des tests ML ;
elle n'est pas requise pour revendiquer cette vérification ciblée.

## Suite nécessaire avant qualification de sources

Un responsable privé doit fournir le lignage vérifiable, les dérivations RNG,
les preuves de couverture, les correspondances de configuration/exports et
les références d'événements complètes. Les signatures et la chaîne de confiance
ne sont pas implémentées ici. Il faut ensuite un audit autorisé sur les
exports train/dev et une attestation séparée des frontières réservées.

La supervision actionnée factuelle, les forwards/gradients, le réalisme et la
généralisation restent des validations séparées. Aucun succès de cette API
ne lève G1 ou G2.
