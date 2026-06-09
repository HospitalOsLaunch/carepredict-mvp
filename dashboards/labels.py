"""French display labels for Hospitalos dashboard fields."""

from __future__ import annotations

ACTION_COLUMN_LABELS: dict[str, str] = {
    "scheduled_admissions": "Admissions prévues",
    "scheduled_discharges": "Sorties prévues",
    "scheduled_surgeries": "Chirurgies programmées",
    "expected_transfers": "Transferts attendus",
    "staff_redeployments": "Redéploiements soignants",
}

SERVICE_LABELS: dict[str, str] = {
    "urg-001": "Urgences",
    "card-001": "Cardiologie",
    "chir-001": "Chirurgie",
    "rea-001": "Réanimation",
    "ped-001": "Pédiatrie",
}

STATUS_LABELS: dict[str, str] = {
    "normal": "Normal",
    "watch": "Sous surveillance",
    "critical": "Critique",
}


def fr_action_columns(columns: list[str]) -> list[str]:
    """Map snake_case action column names to French display labels."""
    return [ACTION_COLUMN_LABELS.get(column, column) for column in columns]


def fr_service_name(service_id: str) -> str:
    """Map a service identifier to a French display name."""
    return SERVICE_LABELS.get(service_id, service_id)


def status_from_score(siips: float, critical_threshold: float) -> str:
    """Return critical, watch, or normal from SIIPS and threshold."""
    if siips >= critical_threshold:
        return "critical"
    if siips >= 0.85 * critical_threshold:
        return "watch"
    return "normal"
