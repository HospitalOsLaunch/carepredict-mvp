# WM-DISCOVERY-01/H1-TEMP — Internal AI-assisted method review decision

**Date:** 2026-11-10. **Decision:** internal G1 methodological review is **accepted with revisions** by the project owner. **Experimental protocol: NOT FROZEN. G2: NO-GO.**

## Scope and governance

The project owner elected to **count the critical AI pre-review as the working internal methodological review**, rather than waiting for outside scientists to advance documentation and contract preparation. The review's substantive verdict is **REVISE**. An LLM critique is not an independent expert replication or a human scientific signature. The original Cycle-01 charter still requires independent review and a human scientific verdict for formal cycle completion or model promotion; this decision does not silently rewrite that charter.

No research results, weights, historical experimental closures, SHA receipts or test outcomes were modified. No H24 forward, simulator call, training, new dataset evaluation, paid API/GPU execution, merging or deployment was authorized.

## Methodological changes accepted for the next protocol draft

1. **H1a** tests *incremental* prediction performance of ordered history beyond a robust, order-attenuated summary (including last value and observation age). This is not proof of a unique or causal latent state.
2. **H1b** tests JEPA/RSSM against robust explicit temporal baselines, controlling as-of feature information, pretraining, tuning and compute as far as demonstrable. H1a and H1b have separate decision outcomes.
3. **C0/C1** are strong comparators; **N0** is mandatory identity check; **N1/N2** are secondary and become `NOT_DISCRIMINATIVE` if physical support, overlap or exchangeability assumptions fail; **N3** isolates observation-policy proxies.
4. Sources need observation-version availability (not `event_at` alone), late-entry/correction handling, and no target, future-regime or data-normalization leakage.
5. The currently provided historical error summary does **not** contain an as-of versioned event stream. Data validity and witness invariants are therefore **not tested**.
6. The H+24 hospital urgent queue and MSE remain **candidate** outcome/loss. Operational `delta_a/delta_b`, population, power, split purge, final metrics and source mandate diff are not frozen. Historical dev is not an untouched holdout.

## Result and next activity

- **G1 methodology review**: `AI_ACCEPTED_REVISE` — internal design workflow may continue.
- **G1 data/metric/negative-control preflight**: `BLOCKED_MISSING_EVIDENCE`.
- **G1 final preregistration**: `NOT_FROZEN`.
- **G2 new compute, inference or training**: `NO_GO`.
- **Historical WM-B0/V-D**: `diagnostic_complete_no_promotion` unchanged.
- **Independent human review**: `NOT_PERFORMED`; cannot be claimed as accomplished for Cycle-01 completion or model promotion.

Only the documentation/metadata schema of a future as-of source may be inspected now. The private detailed protocol, governance receipt and metadata validator remain off the public repository.
