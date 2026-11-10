# HospitalOS guarded research lab — experimental runtime

A **planning-only** six-role scientific agent sequence. It is NOT a self-driving ML research platform, does not train or forward world models, and does not validate scientific claims.

The six roles: prior-art auditor, hypothesis proposer, adversarial red team, preregistration designer, independent reviewer (role only; not independent evidence), and research director. A model suggestion is always recorded as UNVERIFIED. The fixture mode creates explicitly fake outputs solely to test pipeline wiring.

## Prerequisites

Python 3.11+, no full HospitalOS requirements needed. Optional API dependency: `python -m pip install openai`. Install this only in a locally isolated, approved environment. Live API access and requested model identifiers must be tested against your actual account; their availability is NOT assumed.

## Safe zero-cost verification (default)

From repository root:

```bash
python -m pytest -q tests/test_research_lab.py
python -m research_lab run --mode smoke --brief research_lab/brief.example.txt --workspace .research-lab-smoke-01
python -m research_lab status --workspace .research-lab-smoke-01
```

The 6 fixture stages DO NOT perform actual research or send network calls. The output journal is under the workspace directory, not tracked by Git.

## Optional live text-research cycle — explicit opt-in required

Only on a trusted private computer, with a de-identified, reviewed brief:

```bash
export OPENAI_API_KEY=... # set securely outside version control
python -m research_lab run --mode live --allow-api --budget-usd 1.00 \
    --brief research_lab/brief.example.txt --workspace .research-lab-live-01
```

**Do not run this without separate human permission for this exact API expense.** The API budget is a conservative local pre-call estimate, **not** an external, hard provider billing cap. Prices and actual model access require independent verification. There are no automatic retries; errors stop and get journaled. Responses may not follow the strict JSON shape and may stop without completing all stages. Prompts contain a provided brief and bounded prior-agent outputs; there is no external literature lookup or repo reading.

## Security and scientific limitations

- Public repository: never commit patient information, private checkpoints, secrets, results, or journals. The simple email tripwire is **not** sufficient de-identification.
- Workspace files have basic local permissions; they are **not** encrypted or secured against a malicious local operator.
- The journal is hash-chained but can be rewritten in its entirety by an attacker with full write access. Back it up to access-controlled immutable storage for stronger integrity.
- `max_output_tokens` bounds generated output; preflight input cost is an estimate, not guaranteed protection against billing overruns.
- Model outputs are hypotheses and plans. No empirical metrics, independently checked citations, trained model changes, scientific promotions, actions, or hospital system interactions.
- The actual first research mandate remains: falsify temporal/causal interpretations against marginal-preserving and as-of-correct negative controls, after evidence inventory and review.
- Never merge with the isolated `mvp/computer-use` branch; this runtime branch is based on the protocol branch targeting `main` through a reviewed PR.
