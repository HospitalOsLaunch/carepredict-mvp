# S0a — Export des décisions natives du même univers synthétique

**10 novembre 2026 — design et code, sans simulation ni entraînement.**

## Source et exactitude

L'exporteur `research_lab/s0a_native_action_exporter.py` lit un **run de simulation déjà produit et vérifié** par `hospitalos.synthetic.learning.verify_source`, sans relancer la physique. Il utilise exclusivement les événements `DECISION` du journal immuable `truth/events.jsonl.gz`, dont l'identité est rattachée au manifeste SHA-256 du même run que l'exporteur d'observations `hospitalos.operational.adapter`.

Le simulateur v0.4.1 enregistre quatre leviers binaires, dans cet ordre :
1. `anticipation_sorties`
2. `lits_supplementaires`
3. `renfort_soignant`
4. `acceleration_aval`

Il ne produit **pas** les canaux continus `staffing_delta` et `discharge_delta` du générateur indépendant RS-JEPA Phase A. Aucune correspondance arbitraire n'est autorisée.

## Temps et couverture

La politique historique émet une décision par unité chaque jour à 9 h. Le lot reconstruit des intervalles `[h,h+1)` et marque l'action connue de façon conservatrice à `h+1`. Les heures sans décision sont représentées par un zéro **uniquement parce que cette cadence est explicite dans le code du simulateur**. Si une décision 9 h manque, est dupliquée, est hors cadence ou comporte un canal inattendu, l'export est refusé.

Cette granularité ne prouve ni l'effet réalisé des quatre leviers, ni l'absence d'actions non enregistrées dans d'autres mécanismes. Le journal décrit des décisions de politique, pas les quantités effectivement mobilisées.

## Format et sécurité

```
<output>/
  manifest.json
  actions/native_unit_intervals.jsonl.gz
```

Le manifeste contient : `schema=hospitalos.synthetic_native_decisions_v1`, `source_manifest_sha256`, `partition`, `hospital_id`, `units`, `native_levers`, `source_clock` et le SHA-256 de l'archive. Les données `test` et les overlays sont interdits. La sortie est publiée dans un nouveau répertoire, sans écraser les sources.

**Ce format n'est pas encore celui de `synthetic_adapter_v1_files`**. Celui-ci exige toujours deux canaux RS-JEPA et doit donc refuser ce journal natif. C'est un blocage intentionnel, pas un succès de raccordement fictif.

## Vérification documentaire sans exécution ML

```bash
python3 -m research_lab.s0a_native_action_smoke
python3 -m pytest -q tests/test_s0a_native_action_exporter.py
```

Ces tests utilisent des décisions fictives, ne lisent aucun univers simulé réel, ne génèrent aucun hôpital et n'exécutent aucun modèle.

## Étape S0b

Définir un contrat `native_action_v2` à quatre canaux pour le RSSM, avec `action_dim=4` et un adaptateur d'agrégation unité→hôpital documenté (compte d'unités activées par levier, dénominateurs, capacité, topologie, latences). **Ne pas transformer les décisions binaires en effets de staffing/discharge**. Le journal natif et les observations hospitalières devront être rapprochés par manifeste source, frontière topologique et horloge. La trajectoire future factuelle doit être distinguée des scénarios contrefactuels et la perte d'entraînement reste bloquée.

**Statut :** `S0A_NATIVE_EXPORTER_SOURCE_IMPLEMENTED` ; `S0B_FOUR_CHANNEL_INTEGRATION_PENDING` ; `G2_NO_GO`.
