# RS-JEPA hospital dynamics scaffold

This scaffold implements the first two gates of the RS-JEPA plan: deterministic configuration, site-aware validation splits, and a Phase A synthetic multi-site simulator with known unitless criticality labels.

Stage 1 will train only on latent dynamics. The synthetic `criticality` column is held out for probes and Stage 2 supervision sanity; it is not a Stage 1 training target.

## Current gate

Implemented now:

- `rs_jepa.config`: dataclass/YAML configuration; all starting hyperparameters are explicit.
- `rs_jepa.seed`: deterministic seeding for Python, NumPy and Torch.
- `rs_jepa.splits`: cross-site validation plus temporal hold-out, with a guard against shuffled per-site histories.
- `rs_jepa.synthetic`: heterogeneous multi-site simulator, queueing occupancy dynamics, static covariates, temporal features, and known unitless criticality.
- `train --config configs/phaseA.yaml --stage 1`: validates the Phase A scaffold and prints split/feature summaries.

Not implemented at this gate: encoder, EMA target, masking, RSSM, JEPA losses, probes and Stage 2 heads. Those start after approval of this scaffold and simulator.
