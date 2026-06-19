# Rapport diagnostic — run DREES réel

Commande demandée :

```bash
PYTHONPYCACHEPREFIX=/tmp/carepredict_pycache .venv/bin/python run_all.py
```

Statut : **échec avant entraînement quantile / CQR**. Le CSV DREES se charge correctement,
mais `to_canonical()` renvoie 0 ligne. Le pipeline s'arrête ensuite dans
`temporal_split()` avec `Aucun épisode de surge dans le test`.

## Sortie console brute

```text
[load] téléchargement DREES …
[load] OK — séparateur ';', 247,933 lignes
[surge] taux surge global = nan% (cible ≈ 10%)
Traceback (most recent call last):
  File "/Users/saorygiovanni/Documents/carepredict-mvp/run_all.py", line 23, in <module>
    main()
  File "/Users/saorygiovanni/Documents/carepredict-mvp/run_all.py", line 17, in main
    report = run_pipeline(synthetic=args.synthetic, deps=args.dep, surge_weight=args.surge_weight)
             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/Users/saorygiovanni/Documents/carepredict-mvp/carepredict_cqr.py", line 203, in run_pipeline
    split = build_split(synthetic=synthetic, deps=deps)
            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/Users/saorygiovanni/Documents/carepredict-mvp/carepredict_quantile.py", line 184, in build_split
    return temporal_split(canon)
           ^^^^^^^^^^^^^^^^^^^^^
  File "/Users/saorygiovanni/Documents/carepredict-mvp/carepredict_ingest.py", line 197, in temporal_split
    raise ValueError("Aucun épisode de surge dans le test — ajuster la découpe ou le seuil.")
ValueError: Aucun épisode de surge dans le test — ajuster la découpe ou le seuil.
```

## CP1 — Chargement CSV

| Mesure | Valeur obtenue | Valeur attendue | Verdict |
|---|---:|---:|---|
| Lignes brutes chargées | 247 933 | ordre de grandeur ~240 000 | OK |
| Séparateur retenu | `;` | `;` ou `,` | OK |
| Encodage | UTF-8 implicite via `pandas.read_csv(BytesIO(...))` | UTF-8 attendu par le pipeline | OK |
| Départements distincts bruts | 98 | ~95-100 | OK |
| Départements bruts après exclusion couverture partielle | 93 | ~90 | OK |
| Départements distincts après `to_canonical()` | 0 | ~90 | ANORMAL |
| Plage temporelle brute parsée automatiquement | 2017-01-01 → 2023-12-31 | 2017-01-01 → 2023-12-31 | OK |
| Plage temporelle après `to_canonical()` | aucune ligne | 2017-01-01 → 2023-12-31 | ANORMAL |

Échantillon observé :

```text
DATE_SAMPLE ['2017-12-25', '2018-01-29', '2018-02-18', ...]
NB_PASSAGES_SAMPLE [397.1, 429.6, 378.7, 385.8, ...]
```

Diagnostic : le schéma réel actuel expose `date` au format ISO `YYYY-MM-DD`, alors que
`to_canonical()` force `pd.to_datetime(..., format="%d/%m/%Y", errors="coerce")`.
Toutes les dates deviennent donc `NaT`, puis `dropna(subset=["ts", "load_proxy"])`
supprime toutes les lignes.

## CP2 — Surge flag

| Mesure | Valeur obtenue | Valeur attendue | Verdict |
|---|---:|---:|---|
| Taux de surge global | `nan%` | ~10 % | ANORMAL |
| Distribution surge par mois | non calculable, canonique vide | pics hiver, éventuellement été | ANORMAL |

Cause probable : pas un problème statistique de `add_surge_flag`, mais une entrée canonique
vide à cause du parsing de dates dans CP1.

Comptage brut par mois, avant canonicalisation :

```text
{1: 21049, 2: 19110, 3: 21049, 4: 20370, 5: 21049, 6: 20370,
 7: 21049, 8: 21049, 9: 20370, 10: 21049, 11: 20370, 12: 21049}
```

## CP3 — Brique A (skill score)

| Mesure | Valeur obtenue | Valeur attendue | Verdict |
|---|---:|---:|---|
| `skill_score` | non calculé | calculable après split temporel valide | ANORMAL |
| MAE modèle | non calculée | calculable après quantile head | ANORMAL |
| MAE baseline | non calculée | calculable après split temporel valide | ANORMAL |

Le run n'atteint pas la Brique A. Aucun résultat modèle ne doit être interprété.
Dans ce pipeline, `run_all.py` utilise la tête quantile HGBR comme modèle, pas le placeholder
`baseline + bruit` de la démo `carepredict_ingest.py`.

## CP4 — Tableau de couverture

Le tableau réel à 4 méthodes n'a pas été produit, car le pipeline s'arrête avant
`temporal_split()` sur une table canonique vide.

Tableau attendu mais indisponible :

```text
method        cov_global  cov_normal  cov_surge  width_mean  width_surge  width_normal
split         non calculé
mondrian      non calculé
cqr_global    non calculé
cqr_mondrian  non calculé
```

Lecture imposée :

1. `cov_surge(split)` : non calculable. Le signal de décrochage réel ne peut pas être évalué tant
   que la canonicalisation produit 0 ligne.
2. `cov_global(cqr_global/cqr_mondrian) ≥ 0.89` : non calculable.
3. `cov_surge(cqr_mondrian) ≥ 0.90` : non calculable.
4. `width_surge` vs `width_normal` : non calculable.

## CP5 — Cas d'échec statistique légitime

Ce run n'est pas un échec statistique légitime de CQR. C'est un échec de préparation des données :
la strate surge calib n'existe pas parce que le DataFrame canonique est vide.

| Mesure | Valeur obtenue | Diagnostic |
|---|---:|---|
| Points surge dans calib | non calculable | split impossible |
| `q_normal` CQR global | non calculable | CQR non exécuté |
| `q_surge` CQR global | non calculable | CQR non exécuté |
| `q_normal` CQR-Mondrian | non calculable | CQR non exécuté |
| `q_surge` CQR-Mondrian | non calculable | CQR non exécuté |

## Bonus — Croisement de quantiles HGBR

Non calculable. La tête HGBR n'est jamais entraînée, car `temporal_split()` échoue avant
l'étape quantile.

## Décisions à valider

1. **Adapter le parsing de dates dans `to_canonical()`**
   - Justification : le CSV DREES réel chargé le 2026-06-19 expose `date` au format ISO
     `YYYY-MM-DD`, alors que le pipeline attend `dd/mm/YYYY`.
   - Proposition : accepter les deux formats, par exemple tenter `%d/%m/%Y`, puis fallback
     `pd.to_datetime(..., errors="coerce")`.
   - Impact attendu : restaurer les ~247k lignes canonisées, puis permettre CP2–CP4.

2. **Ajouter un test anti-régression sur la source DREES actuelle**
   - Justification : le pipeline avait une hypothèse de schéma correcte historiquement mais fragile.
   - Proposition : test unitaire minimal sur un mini-DataFrame ISO + un mini-DataFrame `dd/mm/YYYY`.

3. **Relancer ensuite le run DREES complet sans modifier CQR**
   - Justification : aucun diagnostic CQR n'est possible tant que l'ingestion réelle produit 0 ligne.
   - Critère : obtenir le tableau `split/mondrian/cqr_global/cqr_mondrian` réel brut, puis seulement
     ensuite arbitrer les éventuels réglages statistiques.
