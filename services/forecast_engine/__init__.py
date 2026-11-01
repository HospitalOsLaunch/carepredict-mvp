"""Forecast engine for LISCOP: arrivals, available beds, tension and boarding at 10:00.

A separate package, run as a scheduled job: it reads the database through the models of
``services.admissions_smr`` and writes ``forecast_runs`` / ``forecast_values``. The API
never imports it (no numpy, pandas or numba in the API image).
"""

MODEL_VERSION = "liscop-forecast-1.0"
