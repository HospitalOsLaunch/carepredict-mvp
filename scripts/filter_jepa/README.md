# Five-year synthetic filter and JEPA pilot

Daily midnight censuses of two 32-bed wards, 2020–2024 inclusive. Each independent seed generates a continuous trajectory with shared seasonal demand, a hidden autocorrelated shock, scheduled cleaning reinforcement and sparse per-bed audits. An exact audit can arrive 0–3 days late. Bed states are occupied, ready and dirty. The filter propagates categorical state probabilities from the latest available dated audit using nominal transition kernels. These kernels share the generator's functional form but omit its hidden shock. This gives the nominal benchmark a structural advantage.

The experiment uses the actual GraphWM class with a daily adapter, fresh 24-dimensional weights and a shared cleaning node. Only its three bed fractions are supervised. Other INT-1 outputs, histories, actions and operational outcomes are outside the pilot. Daily features use publicly available reports and a precommitted cleaning calendar. Simulated true census labels are available for offline training. The source corpus is a dedicated bed process rather than a five-year extension of the INT-1 engine.

Each of ten calendar semesters has five training months followed by a full forecast month. Parameters and optimizer state carry forward. Training uses windows wholly inside the five training months. The ten forecast months are permanently excluded from gradient updates, although reports received during those months remain legitimate past inputs at later dates. Each test origin is the end of the previous month. All daily predictions start there and receive only the known future calendar and committed schedule. The three arms start with identical weights, training origins and draws for a given seed.

Raw and filtered GraphWM train with smooth L1 loss on the three bed fractions. The JEPA arm adds 0.15 times mean squared error between the projected recurrent representation and a stopped-gradient, exponentially averaged encoding of the future public filtered census and calendar. The encoder moves across rounds. Its embedding loss alone does not measure improvement in operational forecasting. Scores include absolute error in ready beds per unit and day, multiclass Brier error for day-of-report filtering, a fixed round-one checkpoint as comparator, and a nominal filter projected to month end. The nominal comparator was scored after training without altering learned models. No model selection or early stopping uses test months.

Run with Python, NumPy and PyTorch on CPU from the repository root:

```bash
for seed in 11 23 37; do
    python scripts/filter_jepa/run.py --seed "$seed" --out "runs/$seed"
done
python scripts/filter_jepa/check.py runs
```

In evidence/filter_jepa, rounds.csv reports equal-weight means over three seeds. Each seed archive contains the simulated ground truth and timestamped reports, three final PyTorch state dictionaries for Experiment, forecast rows, nominal baseline and metrics. In cohort.npz the report columns are arrival day, event day, ward, bed, status (0/1/2 for occupied/ready/dirty). Day zero is 2020-01-01. The runs used NumPy 2.3.5, PyTorch 2.15.0+cpu, one Torch thread. Model scores address bed forecasts only. No patient-wait or action-selection gain was measured.
