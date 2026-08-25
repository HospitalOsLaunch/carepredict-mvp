"""Feast feature view definitions.

The full 50+ feature contract is implemented in pass 1 step 4.
"""

from __future__ import annotations

from datetime import timedelta

from feast import FeatureView, Field
from feast.infra.offline_stores.contrib.postgres_offline_store.postgres_source import (
    PostgreSQLSource,
)
from feast.types import Float32, Int32

from services.feature_pipeline.feast.entities import service

care_load_source = PostgreSQLSource(
    name="mart_care_load_features_source",
    query="select * from marts.mart_care_load_features",
    timestamp_field="event_hour",
)

care_load_features = FeatureView(
    name="care_load_features_v1",
    entities=[service],
    ttl=timedelta(days=30),
    schema=[
        Field(name="siips_mean_1h", dtype=Float32),
        Field(name="patient_count_mean_1h", dtype=Float32),
    ],
    online=True,
    source=care_load_source,
)

temporal_source = PostgreSQLSource(
    name="mart_temporal_features_source",
    query="select * from marts.mart_temporal_features",
    timestamp_field="event_hour",
)

temporal_features = FeatureView(
    name="temporal_features_v1",
    entities=[service],
    ttl=timedelta(days=30),
    schema=[
        Field(name="hour_of_day", dtype=Int32),
        Field(name="day_of_week", dtype=Int32),
        Field(name="month_of_year", dtype=Int32),
    ],
    online=True,
    source=temporal_source,
)
