# WM-B0/V-D — Accounting-summary erratum (public-safe summary)

**Date:** 2026-11-09. **Scope:** archival synthetic train-panel occupancy/flow decomposition. **Status:** documentary reconciliation on a separately supplied CSV; original archival source-byte equivalence remains subject to local verification.

## Nature of the erratum

The historical final closure table displayed only three mean-square components — initial state, admissions, and exits — while its `cross_sum` included interactions involving *all* components. In the underlying source panel, the decomposition also includes transfer-in and transfer-out square terms, and a residual square term. Omitting those square columns from the display creates an apparent gap between the displayed partial sum and the complete mean-square error.

A separate read-only arithmetic check on a supplied archival panel CSV reconstructed the full six-component squared-error identity, including all 15 pairwise cross terms, with floating-point precision. On the hospital aggregate, the transfer-in and transfer-out components cancel through their cross terms under the recorded balance conventions.

**This corrects an incomplete published decomposition table; it is NOT evidence of improved forecasting, a new model result, causal identification, or validated hospital physics.** The signed off archived numerical outputs, manifest, status, and model weights are left unchanged. The source CSV's SHA-256 in the *Mac original* must still be compared to the independently audited supplied copy.

## Historical scientific decision remains unchanged

- WM-B0/V: `INDETERMINATE`.
- WM-B0/V-D: `diagnostic_complete_no_promotion`.
- No new H24, model forward, simulation, training, independent holdout access or model promotion was performed as part of this erratum.

## Evidence custody and other unresolved issues

The detailed arithmetic table, exact archived values, local source fingerprints, execution receipts, and code inspection are held in a **restricted private dossier**; do not upload them to public GitHub. The distinct transmitted-vs-executed mandate identity/diff remains **unresolved**, and the prospective H1-TEMP experimental protocol remains **not frozen**.

**G1: in review. G2: NO-GO.**

This erratum must remain a **separate addendum**, not an edit to the historical closure or its hashed artifacts.
