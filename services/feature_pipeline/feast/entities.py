"""Feast entities for CarePredict."""

from __future__ import annotations

from feast import Entity


hospital = Entity(name="hospital_id", join_keys=["hospital_id"])
service = Entity(name="service_id", join_keys=["service_id"])
patient = Entity(name="patient_id", join_keys=["patient_id"])
