# ADR-0001 — Périmètre Nantes v0.1 & quatre décisions structurantes

- **Statut** : Accepté (gelé jusqu'au sign-off Gate A du 2026-09-04 ; revue de gel au 2026-08-30)
- **Version** : 1.1
- **Date** : 2026-08-11
- **Ticket** : HOS-001
- **Owners décisionnels** : CEO (Guy) · Lead Dev
- **Contexte amont** : HOS-000 (`docs/nantes/repo_map.md`, base `main@a727382`)
- **Réouverture** : 2026-08-30 (revue de gel) puis reconduction jusqu'au sign-off. Toute modification du core
  avant sign-off exige un nouvel ADR versionné.
- **Revu par** : Head of Product (GO), Head of Engineering (GO after v1.1), Head of ML (GO after v1.1).

---

## Contexte

Capacité contrainte (Junior plein temps ; CEO hors code critique). Objectif 30 août **At Risk** ; sign-off Gate A
rebaseliné au **4 septembre 2026**. Le pilote Nantes v0.1 vise mi-septembre un **jumeau numérique d'un service**
qui **forecast**, **recommande des actions** et **simule des scénarios**. Le dépôt (`main`) expose **trois
surfaces servies** (fait établi en revue) :

| Endpoint | Sert | Incertitude |
|---|---|---|
| `/predict` | `CarePredictTFT` (`services/api/dependencies/model_loader.py`) | `services/ml/uq/conformal.py:ConformalForecaster` |
| `/forecast` | `V2ForecastService` → `hospitalos.dynamics.jepa_rssm.JepaRSSM` + encodeur `ts_jepa` | calibration interne v2 |
| `/simulate` + `/actions` | `services/ml/world_model/` (`WorldModelService`, `HospitalRSSM`) | `ConformalState` propre (`artifacts/conformal_residuals.npz`) |

Cet ADR gèle le périmètre et les frontières pour éliminer les décisions ouvertes.

---

## Décision 1 — Périmètre Nantes v0.1 (dedans / dehors)

**Owner** : CEO · **Date** : 2026-08-11 · **Réouverture** : 2026-08-30

### DANS Gate A (livrables du sign-off)

| Domaine | Inclus |
|---|---|
| Contrat de données | Canonical Schema v1 (HOS-002) + Nantes Data Contract + preflight GO/RESTRICT/NO-GO (HOS-003) |
| Qualité | Validator v2 déterministe sur les 8 défauts NO-GO (HOS-006) |
| Sécurité données | Privacy Gate fail-closed (HOS-009) ; Temporal-Leakage Gate sur `available_at` fail-closed (HOS-010) |
| État modèle | UnitState v1 versionné (HOS-010U) |
| Chaîne | ingestion→UnitState offline dockerisée (HOS-011), provenance `run_id` de bout en bout (HOS-012), idempotence/reprise (HOS-013) |
| Forecast | forecast + incertitude + **cascade d'abstention** (HOS-014) ; benchmark vs persistence/seasonal-naive (HOS-015) |
| **World model (décision CEO 2026-08-11)** | Surfaces `simulate` + `actions` **INCLUSES en Gate A**, en **shadow / read-only**, **capables d'ABSTAIN**, **sans revendication causale**. Le RSSM servi hérite des **mêmes garanties Gate A** : privacy, Temporal-Leakage `available_at`, provenance `run_id`, validation d'entrée — **y compris sur son artefact de calibration conforme** (cf. Décision 3). |
| Sortie | rapport traçable, exécution offline sans outbound |

**Distinction `simulate` vs `actions` (finding ML F2)** :
- `simulate` (rollout de scénario) : autorisé en shadow Gate A.
- `actions` (delta action→criticité) : **ABSTAIN par défaut** en Gate A. N'affiche un delta que pour les
  interventions dont la direction est **testée stable** (cf. journal : « discharge+ stable 3/3 » OK ;
  « staffing unstable », « discharge- non générable » → ABSTAIN). Toute autre intervention → ABSTAIN jusqu'à
  validation Gate B (HOS-019/020). Rationale : servir un delta interventionnel est interprété causalement par
  l'utilisateur malgré le disclaimer ; borner par ABSTAIN-par-défaut est la seule garantie réelle.

**ABSTAIN world-model = livrable Gate A explicite (finding ML F1)** : HOS-014 est **étendu** aux surfaces
`simulate`/`actions` (mécanisme + critères de déclenchement : entrée hors-domaine, intervalle conforme trop
large, action hors support d'entraînement). Sans ce mécanisme, la garantie « shadow capable d'ABSTAIN » n'a pas
d'owner. À défaut d'extension de HOS-014, ouvrir HOS-014W.

**Served ≠ validated (finding ML F5)** : la surface world-model **n'a aucun critère d'exactitude en Gate A**
(sa validation quantitative — rollouts falsifiables, invariants — est Gate B). Son **unique contrat Gate A** est :
gates de sécurité passées + ABSTAIN opérationnel + non-causal. Le sign-off (HOS-021S) ne doit pas confondre
« servi » et « validé ».

> **Conséquence actée (capacité)** : inclure `simulate`/`actions` en Gate A **élargit le chemin critique** et
> **augmente le risque sur la date** (déjà At Risk). Mitigation : périmètre strictement shadow + ABSTAIN par
> défaut sur `actions` ; validation expérimentale renvoyée Gate B ; repli au checkpoint 30 août (Décision 4).

### HORS périmètre Nantes v0.1 (explicite)

Console opérationnelle · Ghost Worker · ORTools / MPC · niveaux **L3** et **L7** · pré-entraînement multi-sites ·
**PhysioNet** · champs cliniques fins / texte libre · migration de l'historique complet · extension spéculative
du schéma avant premier contact Nantes.

> **Note produit (finding Product F1)** : la Console étant hors périmètre, la **surface d'exposition** des
> capacités phares à Nantes et leur **libellé utilisateur** (« shadow / non causal / ABSTAIN ») restent à fixer
> en aval (HOS-004 / dashboard), pour éviter la sur-promesse. Ce cadrage n'est pas un prérequis du gel.

---

## Décision 2 — Frontières Gate A / Gate B

**Owner** : Lead Dev · **Date** : 2026-08-11 · **Réouverture** : 2026-08-30

- **Règle cardinale** : **Gate B ne peut pas retarder Gate A.** Gate B ne consomme jamais la capacité requise
  pour fermer Gate A, et démarre **uniquement après sign-off Gate A** (no-go Gate B du 20 août maintenu).
- **Gate A** (Nantes Integration Ready) : extraction conforme → validation → privacy + temporal-leakage →
  UnitState reproductible → forecast sans fuite → incertitude + abstention → comparaison baselines → sortie
  traçable offline. **Inclut** la surface world-model **servie en shadow** (simulate/actions, ABSTAIN, non causal).
- **Gate B** (World Model Experimental Ready) : protocole **pré-enregistré** (HOS-B00) — factual rollout
  held-out falsifiable (HOS-018), trajectoires sous action alternative avec invariants (HOS-019),
  recommandations shadow validées capables d'ABSTAIN (HOS-020), incertitude. **Aucune revendication causale.**
- **Ligne de partage nette** : *servir* la surface world-model en shadow = **Gate A** ; *valider
  expérimentalement* (rollouts falsifiables, contrefactuels pré-enregistrés) = **Gate B**. Distinction
  épistémique : associatif servi ≠ interventionnel validé.

---

## Décision 3 — Source de vérité du schéma & chemin servi Gate A

**Owner** : Lead Dev · **Date** : 2026-08-11 · **Réouverture** : 2026-08-30

**Schéma** :
- **Source unique de vérité** = **Canonical Schema v1** (`canonical_schema.yaml`, HOS-002), dérivé et étendant
  `services/connectors/schemas/canonical.py` (Pydantic v2 existant). **Pas de seconde architecture** de schéma.
- Domaines core gelés : `flow`, `capacity`, `staffing`, `care_load`, `actions`. Sémantique bitemporelle
  **`event_time` / `available_at`** obligatoire. Zone `extensions` **fermée** avant premier contact Nantes.
- Core gelé jusqu'au sign-off. Modification du core ⇒ nouvelle version + test de compatibilité. Version exposée
  dans les sorties de pipeline.

**Chemin servi Gate A (corrigé — findings Eng F1)** — le dépôt expose 3 surfaces (cf. Contexte). Décision :
- **Chemin forecast+world-model servi et signé Gate A = la lignée JEPA/RSSM** : `/forecast`
  (`V2ForecastService` → `JepaRSSM`) **et** `/simulate`+`/actions` (`services/ml/world_model/`), unifiés sous
  **un seul contrat** UnitState v1 (HOS-010U) + Temporal-Leakage `available_at` (HOS-010) + provenance `run_id`
  (HOS-012). Rationale : le CEO ayant inclus le world model (RSSM) en Gate A, unifier sur la lignée JEPA/RSSM
  déjà partagée par `/forecast` et `/simulate`+`/actions` évite deux stacks parallèles.
- **`/predict` (`CarePredictTFT` + `uq/conformal`)** : **retenu comme chemin de référence d'incertitude**
  (méthodologie conforme auditée) mais **non-autoritatif** comme surface forecast signée Gate A. Sa méthode de
  calibration conforme sert de référence pour discipliner les `ConformalState`/calibrations v2 et world-model.
- **Calibration conforme sous discipline temporelle (finding ML F3)** : les résidus de calibration des surfaces
  servies — v2 (`/forecast`) **et** world-model (`ConformalState`, `artifacts/conformal_residuals.npz`) — doivent
  être calibrés **sous `available_at`** (aucun échantillon de calibration issu de données non disponibles à
  l'origine d'inférence) et reliés à `run_id`. C'est le point de fuite le plus subtil de l'inclusion ; il est
  nommément couvert par HOS-010 + HOS-012.
- **Prior art leakage (finding ML F4)** : la **gate `available_at` (HOS-010) est autoritative**. Le check
  d'ordre `carepredict_cqr.py:assert_no_temporal_leakage` (train<calib<test) est strictement plus faible ;
  conservé au mieux comme invariant secondaire bon marché, jamais comme garantie principale.
- Scripts racine `carepredict_*.py` = R&D legacy non servis, hors chemin Gate A.
- **Charge de preuve reportée (revue ML, non bloquante)** : signer la lignée JEPA/RSSM tout en rétrogradant
  `uq/conformal.py` (méthode conforme la plus auditée) à référence impose à **HOS-014P** de porter la méthode
  conforme auditée sur les calibrations v2 + world-model et de **prouver la validité de couverture**. À inscrire
  comme **critère d'acceptation explicite de HOS-014P** — ne pas supposer acquis par héritage de lignée.

---

## Décision 4 — Politique et ordre de coupe

**Owner** : CEO · **Date** : 2026-08-11 · **Réouverture** : 2026-08-30

Ordre de coupe si la capacité manque (du premier coupé au dernier) :

1. CUSUM (détecteur de régime, HOS-016).
2. Automatisation du rapport — version manuelle acceptée.
3. Restartability avancée — conserver atomicité + manifests.
4. Toute **anticipation** de Gate B (de toute façon interdite par Décision 2) — aucune ressource Gate B avant sign-off.
5. Troisième action simulée et recommandations avancées.
6. **Repli world-model Gate A** : si la date reste intenable, `simulate`/`actions` repassent en **démonstration
   read-only non signée** (hors sign-off Gate A) plutôt que de retarder le sign-off. Décision de repli = CEO,
   au checkpoint 30 août (HOS-M30).

**Jamais coupés** : Validator, Privacy Gate, Temporal-Leakage Gate, UnitState, provenance, baseline minimale,
E2E offline.

**Propriétaires des décisions humaines** : périmètre & repli = CEO ; frontières Gate & schéma & chemin servi =
Lead Dev ; protocole forecast/calibration (HOS-014P) = Lead Dev + ML ; sign-off Gate A (HOS-021S) = Lead Dev + CEO.

---

## Conséquences

- **Positives** : implémentation non divergente ; les 2 capacités phares (recommander, simuler) sont dans le
  pilote signé ; frontières Gate A/B nettes ; schéma à source unique ; chemin servi unifié (JEPA/RSSM).
- **Négatives / risques** : chemin critique élargi (world-model shadow soumis aux gates + unification des
  calibrations conformes) → pression accrue sur le 4 septembre. Suivi via HOS-M30 et l'ordre de coupe (item 6).

## Références

- Roadmap HospitalOS (Gates, règles d'exécution, ordre de coupe).
- HOS-000 `docs/nantes/repo_map.md`.
- Débloqués par HOS-001 : HOS-002, HOS-003, HOS-004, HOS-005, HOS-025.
- Tickets dépendants cités dans le corps : HOS-006, HOS-009, HOS-010, HOS-010U, HOS-011, HOS-012, HOS-013,
  HOS-014 (étendu world-model / HOS-014W), HOS-015, HOS-016 ; Gate B : HOS-B00, HOS-018, HOS-019, HOS-020.

## Journal

- **2026-08-11 v1.0** — ADR créé. Décision CEO : simulate/actions inclus en Gate A (shadow/ABSTAIN, no causal).
- **2026-08-11 v1.1** — Intégration revue AAA : (Eng) correction du câblage servi — 3 surfaces réelles, `/forecast`
  = JEPA/RSSM, chemin servi Gate A unifié sur la lignée JEPA/RSSM, `/predict` non-autoritatif ; (ML) ABSTAIN
  world-model = livrable Gate A (HOS-014 étendu), `actions` ABSTAIN-par-défaut, calibration conforme sous
  `available_at`, gate `available_at` autoritative, « servi ≠ validé » ; (Product) exposition/libellé pilote
  renvoyés en aval, gel étendu au sign-off, item 4 reformulé, références réconciliées.
