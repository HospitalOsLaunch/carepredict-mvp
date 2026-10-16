# Nantes Data Contract — Spécification d'extraction & Preflight (HOS-003)

Document destiné au **DIM du CHU de Nantes**. Il décrit l'extraction attendue et la commande de
**preflight** qui rend en quelques minutes une décision **GO / RESTRICT / NO-GO** sur son exploitabilité.
Aucune donnée nominative n'est demandée.

## 1. Format d'extraction

- **Granularité** : un enregistrement par **unité de soins (UF)** et par **pas horaire**.
- **Fréquence** : horaire. **Historique minimal** : 90 jours.
- **Timezone** : Europe/Paris, horodatages **tz-aware** (offset explicite `+01:00`/`+02:00`, DST correct).
- **Encodage** : UTF-8. Format tabulaire (CSV ou Parquet), une ligne d'en-tête de noms de colonnes.
- **Deux horodatages obligatoires** : `horodatage_mesure` (event_time) et `horodatage_disponibilite`
  (available_at = moment réel où la valeur devient connaissable). Voir la règle available_at ci-dessous.

## 2. Colonnes

- **Requises** (absence → NO-GO) : `etablissement_id`, `uf_code`, `horodatage_mesure`,
  `horodatage_disponibilite`, `score_siips`, `nb_patients`, `nb_admissions`, `nb_sorties`, `nb_presents`.
  *(`nb_presents` = occupation, un **stock** : exigé en direct, non dérivable des flux admissions/sorties
  sans état initial ni transferts.)*
- **Domaines optionnels absents** : si **staffing** (`etp_ide`/`etp_as`) **et** **capacity**
  (`lits_*`) sont tous deux absents, le jumeau est réduit au forecasting → **RESTRICT** (non bloquant).
- **Optionnelles** (améliorent la couverture) : `score_aas`, `nb_mutations_entrantes`,
  `nb_mutations_sortantes`, `lits_armes`, `lits_disponibles`, `etp_ide`, `etp_as`, `type_action`.
- **Interdites** (présence → NO-GO) : toute colonne nominative ou de texte libre (nom, prénom, IPP, NIR,
  INS, date de naissance, adresse, téléphone, email, commentaire, motif, texte libre, note…).

Le mapping colonne↔canonical fait foi dans `nantes_mapping_template.yaml` (à co-remplir avec le DIM).

## 3. Règle `available_at` (anti-fuite — critique)

`horodatage_disponibilite` doit refléter le **lag réel** entre la survenue de l'événement et le moment où la
donnée est disponible dans le SIH. **Ne jamais** le fixer égal à `horodatage_mesure` par commodité : cela
neutralise la Temporal-Leakage Gate (HOS-010) et fait passer une extraction qui fuit. En l'absence de lag
mesurable, le signaler explicitement — c'est un défaut de contrat, pas une valeur par défaut.

## 4. Commande preflight & codes de sortie

Le preflight n'inspecte que le **manifeste de colonnes** (noms), jamais les valeurs patients.

```bash
python -m services.validation.preflight --columns manifeste_colonnes.json --json rapport_preflight.json
```

`manifeste_colonnes.json` : `{"columns": ["etablissement_id", "uf_code", ...]}` (ou une liste JSON simple).

| Décision | Signification | Exit code |
|---|---|---|
| **GO** | Toutes les colonnes requises mappées directement ; aucune interdite ; aucune inconnue | `0` |
| **RESTRICT** | Requises couvertes mais champ requis seulement dérivé, ou colonnes inconnues présentes → exploitable sous réserves | `10` |
| **NO-GO** | Colonne interdite présente, ou champ requis manquant (ni mappé ni dérivable) | `20` |
| (erreur d'usage) | Manifeste illisible / mal formé | `1` |

Le rapport machine-readable distingue cinq catégories de couverture : **mapped, derived, missing, unknown,
forbidden**, avec les raisons de la décision et la provenance (`run_id`, `schema_version`, `template_version`).

## 5. Actions correctives typiques

- **NO-GO interdite** → retirer la/les colonnes nominatives ou texte libre avant réextraction.
- **NO-GO manquante** → ajouter la colonne requise, ou fournir les colonnes permettant sa dérivation.
- **RESTRICT dérivé/inconnu** → fournir la colonne directe (ex. `nb_presents`) ou documenter/retirer les
  colonnes hors contrat pour passer GO.
