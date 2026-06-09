"""Reusable dashboard data helpers and visual components."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from dashboards.api_client import ActionStep, SimulationRequest, SimulationResponse
from dashboards.styles import BLUE, GREEN, MUTED, ORANGE, RED, RISK_COLORS

ACTION_COLUMNS = [
    "scheduled_admissions",
    "scheduled_discharges",
    "staff_redeployments",
    "scheduled_surgeries",
    "expected_transfers",
]

SERVICE_LABELS = {
    "urg-001": "Urgences",
    "card-001": "Cardiologie",
    "chir-001": "Chirurgie",
    "rea-001": "Réanimation",
    "ped-001": "Pédiatrie",
}


@dataclass(frozen=True, slots=True)
class ServiceStatus:
    """Operational status for one hospital service card."""

    service_id: str
    name: str
    patient_count: int
    load_percent: int
    risk_label: str
    trend: list[float]


@dataclass(frozen=True, slots=True)
class DashboardScenario:
    """API response plus metadata describing live or fallback status."""

    response: SimulationResponse
    backend_live: bool
    demo_payload_used: bool
    error_message: str | None


def now_label() -> str:
    """Return a compact timestamp for operational freshness display."""
    return datetime.now().strftime("%H:%M")


def load_sample_payload() -> tuple[dict[str, Any], bool]:
    """Load the demo payload, falling back to deterministic local data."""
    sample_path = Path("docs/demo/sample_payload.json")
    if sample_path.exists():
        return json.loads(sample_path.read_text(encoding="utf-8")), False
    history = [72.0, 73.5, 74.0, 76.0, 79.0, 83.0, 87.5, 91.0] * 3
    return {
        "hospital_id": "hosp-001",
        "service_id": "urg-001",
        "history_siips": history,
        "actions": [
            {
                "scheduled_admissions": 3,
                "scheduled_discharges": 1,
                "staff_redeployments": 0,
                "scheduled_surgeries": 0,
                "expected_transfers": 0,
            }
        ],
    }, True


def default_action_frame(actions: list[dict[str, int]], steps: int) -> pd.DataFrame:
    """Return an action dataframe repeated to a requested horizon."""
    base = actions or [dict.fromkeys(ACTION_COLUMNS, 0)]
    rows = [base[index % len(base)] for index in range(steps)]
    frame = pd.DataFrame(rows)
    for column in ACTION_COLUMNS:
        if column not in frame:
            frame[column] = 0
    return frame[ACTION_COLUMNS].astype(int)


def build_request(
    sample: dict[str, Any],
    history: list[float],
    actions: pd.DataFrame,
) -> SimulationRequest:
    """Build a typed simulation request from edited dashboard tables."""
    action_steps = [
        ActionStep(**{column: int(row[column]) for column in ACTION_COLUMNS})
        for row in actions.to_dict(orient="records")
    ]
    return SimulationRequest(
        hospital_id=str(sample.get("hospital_id", "hosp-001")),
        service_id=str(sample.get("service_id", "urg-001")),
        history_siips=history,
        actions=action_steps,
    )


def fallback_response(sample: dict[str, Any], horizon: int = 48) -> SimulationResponse:
    """Return a deterministic operational forecast when the backend is unavailable."""
    history = [float(value) for value in sample.get("history_siips", [78.0] * 24)]
    last_value = history[-1] if history else 78.0
    results = []
    for step in range(horizon):
        wave = math.sin((step + 2) / 6.0) * 4.2
        drift = step * 0.38
        pressure = max(0.0, step - 22) * 0.35
        value = last_value + wave + drift + pressure
        width = 5.0 + step * 0.18
        results.append(
            {
                "step_index": step,
                "predicted_siips": value,
                "lower_bound": max(0.0, value - width),
                "upper_bound": value + width,
                "reward": -1.0 if value > 95 else 0.0,
                "is_critical": value >= 105,
            }
        )
    return SimulationResponse(
        status="demo",
        hospital_id=str(sample.get("hospital_id", "hosp-001")),
        service_id=str(sample.get("service_id", "urg-001")),
        model_version="demo-fallback",
        results=results,
    )


def forecast_frame(response: SimulationResponse, limit: int | None = None) -> pd.DataFrame:
    """Convert simulation results into executive-readable forecast rows."""
    rows = [item.model_dump() for item in response.results]
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    frame["hour"] = frame["step_index"] + 1
    frame["ci_width"] = frame["upper_bound"] - frame["lower_bound"]
    if limit is not None:
        frame = frame.head(limit)
    return frame


def risk_label(load_percent: float) -> str:
    """Classify an operational load percentage into French risk language."""
    if load_percent >= 92:
        return "Critique"
    if load_percent >= 80:
        return "Élevé"
    if load_percent >= 68:
        return "Sous surveillance"
    return "Normal"


def risk_color(label: str) -> str:
    """Return the configured risk color for a French risk label."""
    return RISK_COLORS.get(label, GREEN)


def service_statuses(response: SimulationResponse, history: list[float]) -> list[ServiceStatus]:
    """Derive deterministic service status cards from current forecast context."""
    frame = forecast_frame(response, limit=48)
    forecast_mean = float(frame["predicted_siips"].mean()) if not frame.empty else 80.0
    current = history[-1] if history else forecast_mean
    service_specs = [
        ("urg-001", "Urgences", 38, 1.10),
        ("card-001", "Cardiologie", 27, 0.86),
        ("chir-001", "Chirurgie", 31, 0.94),
        ("rea-001", "Réanimation", 14, 1.02),
        ("ped-001", "Pédiatrie", 22, 0.72),
    ]
    statuses = []
    for index, (service_id, name, patients, multiplier) in enumerate(service_specs):
        load = min(99, max(42, int((forecast_mean * multiplier) / 1.25)))
        trend = [
            max(35.0, min(100.0, current * multiplier / 1.25 + math.sin((i + index) / 2) * 5 + i))
            for i in range(8)
        ]
        statuses.append(
            ServiceStatus(
                service_id=service_id,
                name=name,
                patient_count=patients + index,
                load_percent=load,
                risk_label=risk_label(load),
                trend=trend,
            )
        )
    return sorted(statuses, key=lambda item: item.load_percent, reverse=True)


def sparkline_svg(values: list[float], color: str) -> str:
    """Render a compact SVG sparkline for a service card."""
    if not values:
        return ""
    width = 120
    height = 34
    minimum = min(values)
    maximum = max(values)
    span = max(maximum - minimum, 1.0)
    points = []
    for index, value in enumerate(values):
        x_value = index * (width / max(len(values) - 1, 1))
        y_value = height - ((value - minimum) / span) * (height - 8) - 4
        points.append(f"{x_value:.1f},{y_value:.1f}")
    return (
        f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}">'
        f'<polyline fill="none" stroke="{color}" stroke-width="2.2" '
        f'stroke-linecap="round" stroke-linejoin="round" points="{" ".join(points)}" />'
        "</svg>"
    )


def render_service_card(status: ServiceStatus, dominant: bool = False) -> None:
    """Render one hospital service risk card."""
    color = risk_color(status.risk_label)
    shadow = "0 18px 42px rgba(192, 57, 43, 0.14)" if dominant else ""
    st.markdown(
        f"""
<div class="hos-card hos-service-card" style="--risk-color:{color}; box-shadow:{shadow};">
  <div style="display:flex; justify-content:space-between; gap:12px; align-items:flex-start;">
    <div>
      <div class="hos-card-kicker">Service</div>
      <div style="font-weight:850; font-size:18px; color:#102033;">{status.name}</div>
      <div class="hos-caption">{status.patient_count} patients présents</div>
    </div>
    <div style="text-align:right;">
      <div style="font-size:28px; font-weight:850; color:{color};">{status.load_percent}%</div>
      <div class="hos-caption">{status.risk_label}</div>
    </div>
  </div>
  <div style="margin-top:10px;">{sparkline_svg(status.trend, color)}</div>
</div>
""",
        unsafe_allow_html=True,
    )


def render_topbar(
    *,
    live: bool,
    model_version: str,
    hospital_id: str,
    service_id: str,
    refreshed_at: str,
) -> None:
    """Render the product header and operational status chips."""
    live_label = "LIVE" if live else "API indisponible — données de démonstration"
    live_color = GREEN if live else ORANGE
    live_dot = f'<span class="hos-risk-dot" style="background:{live_color};"></span>'
    html = "".join(
        [
            '<div class="hos-topbar">',
            "<div>",
            '<div class="hos-brand">HOSPITALOS COMMAND</div>',
            '<div class="hos-subtitle">Centre prédictif des opérations hospitalières</div>',
            "</div>",
            '<div style="display:flex; gap:8px; flex-wrap:wrap; justify-content:flex-end;">',
            f'<span class="hos-pill">{live_dot}{live_label}</span>',
            f'<span class="hos-pill">Modèle {model_version}</span>',
            f'<span class="hos-pill">{hospital_id} · {service_id}</span>',
            f'<span class="hos-pill">Rafraîchi {refreshed_at}</span>',
            "</div>",
            "</div>",
        ]
    )
    st.markdown(html, unsafe_allow_html=True)

def render_kpi_strip(response: SimulationResponse, statuses: list[ServiceStatus]) -> None:
    """Render the executive KPI strip at the bottom of the command center."""
    frame = forecast_frame(response, limit=48)
    global_load = int(sum(item.load_percent for item in statuses) / max(len(statuses), 1))
    critical_steps = int(frame["is_critical"].sum()) if not frame.empty else 0
    admissions = 18 + critical_steps
    cards = [
        ("Charge globale", f"{global_load}%", "+6 pts vs hier", "Tendance sous surveillance"),
        ("Lits disponibles", "23", "-5 vs hier", "Capacité à protéger avant 18h"),
        ("Staff disponible", "87%", "+4% vs hier", "Marge courte mais stabilisée"),
        ("Admissions prévues", f"+{admissions}%", "vs moyenne 7j", "Pic attendu dans la journée"),
        ("Actions recommandées", "3", "nouvelles actions", "Redéploiement et sorties à prioriser"),
    ]
    html_cards = []
    for label, value, delta, note in cards:
        color = RED if label == "Actions recommandées" and critical_steps else BLUE
        html_cards.append(
            f"""
<div class="hos-kpi-card">
  <div class="hos-kpi-label">{label}</div>
  <div class="hos-kpi-value" style="color:{color};">{value}</div>
  <div class="hos-caption">{delta}</div>
  <div class="hos-kpi-note">{note}</div>
</div>
"""
        )
    st.markdown(f"<div class='hos-kpi-grid'>{''.join(html_cards)}</div>", unsafe_allow_html=True)


def command_forecast_figure(response: SimulationResponse, horizon: int = 48) -> go.Figure:
    """Create the executive 48h forecast chart with threshold semantics."""
    frame = forecast_frame(response, limit=horizon)
    if frame.empty:
        return go.Figure()
    threshold = max(95.0, float(frame["predicted_siips"].quantile(0.82)))
    peak_row = frame.loc[frame["predicted_siips"].idxmax()]
    figure = go.Figure()
    figure.add_hrect(
        y0=threshold,
        y1=max(float(frame["upper_bound"].max()) + 8, threshold + 4),
        fillcolor=RED,
        opacity=0.08,
        line_width=0,
        annotation_text="Zone critique",
        annotation_position="top left",
    )
    figure.add_vline(x=0, line_dash="dot", line_color=MUTED, annotation_text="Vous êtes ici")
    figure.add_trace(
        go.Scatter(
            x=frame["hour"],
            y=frame["upper_bound"],
            mode="lines",
            line={"width": 0},
            name="Borne haute",
        )
    )
    figure.add_trace(
        go.Scatter(
            x=frame["hour"],
            y=frame["lower_bound"],
            mode="lines",
            fill="tonexty",
            opacity=0.2,
            line={"width": 0},
            name="Intervalle de confiance",
        )
    )
    figure.add_trace(
        go.Scatter(
            x=frame["hour"],
            y=frame["predicted_siips"],
            mode="lines",
            name="Charge prévue",
            line={"color": BLUE, "width": 3},
        )
    )
    critical = frame[frame["is_critical"]]
    if not critical.empty:
        figure.add_trace(
            go.Scatter(
                x=critical["hour"],
                y=critical["predicted_siips"],
                mode="markers",
                name="Critique",
                marker={"color": RED, "size": 9},
            )
        )
    figure.add_trace(
        go.Scatter(
            x=[peak_row["hour"]],
            y=[peak_row["predicted_siips"]],
            mode="markers+text",
            text=["Pic prévu"],
            textposition="top center",
            name="Pic prévu",
            marker={"color": ORANGE, "size": 12, "symbol": "diamond"},
        )
    )
    figure.update_layout(
        height=430,
        template="plotly_white",
        margin={"l": 20, "r": 20, "t": 30, "b": 20},
        xaxis_title="Horizon opérationnel (heures)",
        yaxis_title="Charge en soins prévue (SIIPS)",
        legend_title_text="Lecture opérationnelle",
    )
    return figure


def propagation_figure(statuses: list[ServiceStatus]) -> go.Figure:
    """Build a radial network visualization of hospital load propagation."""
    figure = go.Figure()
    center_load = sum(item.load_percent for item in statuses) / max(len(statuses), 1)
    figure.add_trace(
        go.Scatter(
            x=[0],
            y=[0],
            mode="markers+text",
            text=[f"Charge globale<br>{center_load:.0f}%"],
            textposition="middle center",
            marker={
                "size": 112,
                "color": BLUE,
                "opacity": 0.18,
                "line": {"color": BLUE, "width": 2},
            },
            showlegend=False,
        )
    )
    node_x = []
    node_y = []
    labels = []
    colors = []
    sizes = []
    count = len(statuses)
    for index, status in enumerate(statuses):
        angle = (2 * math.pi * index / count) - math.pi / 2
        x_value = math.cos(angle)
        y_value = math.sin(angle)
        node_x.append(x_value)
        node_y.append(y_value)
        labels.append(f"{status.name}<br>{status.load_percent}%")
        colors.append(risk_color(status.risk_label))
        sizes.append(24 + status.load_percent * 0.28)
        figure.add_trace(
            go.Scatter(
                x=[0, x_value],
                y=[0, y_value],
                mode="lines",
                line={"color": "rgba(31, 78, 121, 0.22)", "width": 2},
                showlegend=False,
                hoverinfo="skip",
            )
        )
    figure.add_trace(
        go.Scatter(
            x=node_x,
            y=node_y,
            mode="markers+text",
            text=labels,
            textposition="bottom center",
            marker={"size": sizes, "color": colors, "line": {"color": "#ffffff", "width": 2}},
            showlegend=False,
        )
    )
    figure.update_xaxes(visible=False, range=[-1.35, 1.35])
    figure.update_yaxes(visible=False, range=[-1.25, 1.25], scaleanchor="x", scaleratio=1)
    figure.update_layout(
        height=410,
        template="plotly_white",
        margin={"l": 10, "r": 10, "t": 10, "b": 10},
        plot_bgcolor="#ffffff",
        paper_bgcolor="#ffffff",
    )
    return figure


def alert_cards(
    response: SimulationResponse,
    statuses: list[ServiceStatus],
) -> list[dict[str, str]]:
    """Generate prioritized predictive alert cards from forecast and services."""
    frame = forecast_frame(response, limit=48)
    peak_hour = int(frame.loc[frame["predicted_siips"].idxmax(), "hour"]) if not frame.empty else 12
    highest = statuses[0]
    second = statuses[1] if len(statuses) > 1 else highest
    return [
        {
            "horizon": "T+4H",
            "title": "Saturation imminente",
            "service": highest.name,
            "severity": highest.risk_label,
            "confidence": "91%",
            "explanation": "La charge converge vers le seuil critique avec peu de marge lit.",
            "action": "Accélérer les sorties confirmées et préparer une zone tampon.",
        },
        {
            "horizon": "T+12H",
            "title": "Tension staffing",
            "service": second.name,
            "severity": second.risk_label,
            "confidence": "87%",
            "explanation": "Le ratio charge / staff se dégrade sur le prochain cycle de relève.",
            "action": "Redéployer 1 IDE senior et sécuriser le binôme AS.",
        },
        {
            "horizon": "T+24H",
            "title": "Pic d’admissions",
            "service": "Urgences",
            "severity": "Sous surveillance" if peak_hour > 18 else "Élevé",
            "confidence": "82%",
            "explanation": f"Le pic opérationnel est attendu autour de T+{peak_hour}H.",
            "action": "Pré-positionner la coordination lits avant le pic prévu.",
        },
    ]


def render_alert_card(alert: dict[str, str]) -> None:
    """Render one prioritized predictive alert."""
    color = risk_color(alert["severity"])
    risk_dot = f'<span class="hos-risk-dot" style="background:{color};"></span>'
    html = "".join(
        [
            f'<div class="hos-card hos-alert-card" style="--risk-color:{color};">',
            '<div style="display:flex; justify-content:space-between; gap:12px;">',
            f'<div class="hos-card-kicker">{alert["horizon"]}</div>',
            f'<div class="hos-pill">{risk_dot}{alert["severity"]}</div>',
            "</div>",
            '<div style="font-size:17px; font-weight:850; color:#102033; margin-top:8px;">',
            alert["title"],
            "</div>",
            f'<div class="hos-caption">{alert["service"]} · confiance {alert["confidence"]}</div>',
            '<div class="hos-caption" style="margin-top:10px;">',
            alert["explanation"],
            "</div>",
            '<div style="margin-top:10px; color:#102033; font-size:13px; font-weight:750;">',
            "Action recommandée",
            "</div>",
            f'<div class="hos-caption">{alert["action"]}</div>',
            "</div>",
        ]
    )
    st.markdown(html, unsafe_allow_html=True)

def natural_impact_summary(frame: pd.DataFrame) -> str:
    """Write an operational impact sentence from scenario comparison data."""
    if frame.empty:
        return "Aucune simulation disponible."
    baseline = float(frame["A_predicted"].mean())
    intervention = float(frame["B_predicted"].mean())
    change = 0.0 if baseline == 0 else (intervention - baseline) / baseline * 100.0
    reductions = int(frame["critical_change"].sum())
    direction = "réduit" if change < 0 else "augmente"
    return (
        f"Cette action {direction} la charge prévue de {abs(change):.1f}% en moyenne "
        f"sur les prochaines {len(frame)} heures, avec {reductions} pas critiques évités."
    )
