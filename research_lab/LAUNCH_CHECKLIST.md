# Cycle 01 — local controlled activation

**Status:** ready for authorized local activation, **not executed with real API calls**. Never paste your key into ChatGPT, GitHub issues, PR text or a committed file.

## User-only step (secret)

1. Create a separate OpenAI API project called `HospitalOS Research Lab` and create a project-scoped secret key. Do not share the key.
2. In the project's billing settings, set a hard enforcement limit if your account supports it and use conservative usage alerts. A project cap may not stop charges instantly and a local estimate is not a guaranteed provider-side cap.
3. On a trusted Mac, clone/checkout **the exact feature branch**, not `main` or `mvp/computer-use`:

```bash
git fetch origin research/lab-runtime-2026-11
git switch research/lab-runtime-2026-11
bash research_lab/launch-mac.sh --live
```

When asked, paste the key directly into the hidden terminal prompt. The shell script does not save it in any file and exits after the bounded cycle. All local outputs live in a gitignored `.research-lab-live-*` directory. Do not upload that directory to a public repository.

The script installs a dedicated venv at `~/.venvs/hospitalos-research-lab`, verifies both requested model IDs, and then attempts a six-agent, *text-only* cycle. It does not train or simulate world models. Its `--budget-usd 1.00` cap is a conservative **preflight quote**, not a billing API hard cap; the provider's actual billing may differ. Stopping after a failed stage produces a partial journal, not a research success. No automatic retries.

## Human review after launch

Inspect `events.jsonl` offline with `python3 -m research_lab status --workspace <path>`. Compare the generated hypotheses with pre-registered baselines and independently verify every reference. No model may promote results or authorize a compute run. Human G1 sign-off is required before any ML experiment.

## Unconnected dependencies

This repository cannot receive or store your secret through the available GitHub connector. GitHub Actions must remain keyless and offline. The live engine does not yet have a private persistent remote executor, asynchronous API monitoring, or retrieval of proprietary scientific artifacts. These require an explicitly connected private environment and independent access controls.


## Safe recovery from the 2026-11-09 partial live run

If the original journal is intact, the cycle can continue without calling the already completed
`prior_art` stage. The first run must remain untouched. After fetching this branch,
perform the new preflight and run:

```bash
cd ~/hospitalos-research-lab
git pull --ff-only
python3 -m research_lab status --workspace .research-lab-live-20261109T195551Z
bash research_lab/launch-mac.sh --resume .research-lab-live-20261109T195551Z
```

The second command only checks the journal; the final command may incur API charges.
The launcher starts a **new** workspace and copies verified previous stage outputs with
provenance hashes. It accounts for reservations from the original failed attempt in
the same nominal local 1 USD budget; the balance is an estimate, not an actual spend.
It increases Astra's output token cap, adds medium reasoning effort, and records sanitized
response status, incomplete reason and token usage *before parsing*. It does not
automatically retry failed calls, and never sends raw provider errors to public GitHub.
Do not copy or publish the events journal: it contains proprietary research text.

The original five-event record verifies its integrity, but does not prove why Astra's
response failed schema validation. This change improves future diagnosis; no scientific
conclusion is inferred from a partially completed run.
