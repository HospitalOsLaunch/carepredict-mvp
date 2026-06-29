# SPARCS adapter Step 1 summary

- Feature extract: `runs/sparcs_adapter/source/sparcs_2024_extract_100k.csv` (100000 rows)
- Disposition audit source: `runs/sparcs_adapter/source/sparcs_2024_all_dispositions.csv`
- Canonical rows: 100000
- Mapping decision: **PASS**
- Unmapped: 0 (0.000%)
- aval_institu: 13.371%
- No-skill AUPRC reference: 0.1337
- Active feature configuration: `no_apr`

## APR sensitivity

`no_apr` is the primary conservative configuration. `with_apr` adds APR Severity and APR Risk of Mortality only when `--include-apr` is explicit.
Predictive AUPRC comparison and bootstrap are deferred to Step 5.
A future gain from `with_apr` must be treated as potentially dependent on information unavailable at admission.

## Scope

This step audits mapping, class prevalence, and feature leakage only. It does not train a predictor, compute model AUPRC, or bootstrap predictive metrics.
