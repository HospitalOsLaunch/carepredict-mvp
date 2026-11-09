# WM-DISCOVERY-01 — Public prior-art index (initial, not exhaustive)

**Scope:** literature dated no later than 2026-11-09, relevant to the question of whether temporal latent prediction learns information beyond trivial baselines. Source articles need full-text and appendix review before novelty claims. This file contains citations and methodological implications only.

| Work | Grounded scope | Consequence for H1-TEMP |
|---|---|---|
| Zeng et al., *Are Transformers Effective for Time Series Forecasting?*, AAAI 2023 — https://ojs.aaai.org/index.php/AAAI/article/view/26317 | Shows the importance of strong simple time-series forecasting baselines | Include linear/recency/simple baselines; do not interpret model complexity as temporal insight |
| Feng et al., *Does JEPA Pretraining Help Time Series Forecasting?*, 2026 — https://arxiv.org/abs/2609.31680 | JEPA benefit varies across backbones in evaluated benchmarks | No unconditional JEPA superiority claim |
| Lee & Sim, *CF-JEPA*, 2026 — https://arxiv.org/abs/2606.07031 | Studies temporally continuous forward-cropped JEPA supervision | Ordered latent forecasting alone is not a new research mechanism |
| Peng et al., *T-JEPA*, 2026 — https://arxiv.org/abs/2610.05731 | Studies time-gap-conditioned transitions and metadata shortcut mitigation for EO data | Novelty must be more specific than using elapsed time and anti-shortcut constraints |
| Zhang et al., *On the Identifiability of Controlled World Models*, 2026 — https://arxiv.org/abs/2607.22430 | Provides identification results only under specific state/action assumptions | Do not equate action conditioning with causal identification |
| Giakoumoglou et al., *S-JEPA*, Nov 2026 — https://arxiv.org/abs/2611.09302 | Proposes stochastic latent JEPA for masked image prediction | Stochastic JEPA components alone are insufficient for a new claim |

**Verdict:** originality **UNVERIFIED**; related methods already address time-series JEPA, temporal order and shortcut controls. This index is a starting point for a mechanism-level novelty review, not a literature survey or an empirical test.

Do not cite unpublished internal results in this public index.
