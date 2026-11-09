# Cycle 01 — local controlled activation

**Status:** ready for authorized local activation, **not executed with real API calls**. Never paste your key into ChatGPT, GitHub issues, PR text or a committed file.

## User-only step (secret)

1. Create a separate OpenAI API project called `HospitalOS Research Lab` and create a project-scoped secret key. Do not share the key.
2. In the project's billing settings, set a hard enforcement limit if your account supports it and use conservative usage alerts. A project cap may not stop charges instantly and a local estimate is not a guaranteed provider-side cap.
3. On a trusted Mac, clone/checkout **the exact feature branch**, not `main` or `mvp/computer-use`:

```bash
git fetch origin research/lab-runtime-2026-11
git switch research/lab-runtime-2026-11
python3 -m pytest -q tests/test_research_lab.py
bash research_lab/launch-mac.sh --live
```

When asked, paste the key directly into the hidden terminal prompt. The shell script does not save it in any file and exits after the bounded cycle. All local outputs live in a gitignored `.research-lab-live-*` directory. Do not upload that directory to a public repository.

The script installs a dedicated venv at `~/.venvs/hospitalos-research-lab`, verifies both requested model IDs, and then attempts a six-agent, *text-only* cycle. It does not train or simulate world models. Its `--budget-usd 1.00` cap is a conservative **preflight quote**, not a billing API hard cap; the provider's actual billing may differ. Stopping after a failed stage produces a partial journal, not a research success. No automatic retries.

## Human review after launch

Inspect `events.jsonl` offline with `python3 -m research_lab status --workspace <path>`. Compare the generated hypotheses with pre-registered baselines and independently verify every reference. No model may promote results or authorize a compute run. Human G1 sign-off is required before any ML experiment.

## Unconnected dependencies

This repository cannot receive or store your secret through the available GitHub connector. GitHub Actions must remain keyless and offline. The live engine does not yet have a private persistent remote executor, asynchronous API monitoring, or retrieval of proprietary scientific artifacts. These require an explicitly connected private environment and independent access controls.
