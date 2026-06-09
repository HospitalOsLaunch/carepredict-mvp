"""Reusable dashboard data helpers and visual components."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from dashboards.api_client import ActionStep, SimulationRequest, SimulationResponse
from dashboards.labels import ACTION_COLUMN_LABELS, STATUS_LABELS, fr_action_columns
from dashboards.styles import BLUE, GRAY, ORANGE, RED, STATUS_COLORS

ACTION_COLUMNS = list(ACTION_COLUMN_LABELS.keys())
FRENCH_TO_ACTION = {label: column for column, label in ACTION_COLUMN_LABELS.items()}
CRITICAL_THRESHOLD = 850.0


def format_int(value: float) -> str:
    """Format an integer-like value with French thousands spacing."""
    return f"{value:,.0f}".replace(",", " ")


def format_float(value: float) -> str:
    """Format one decimal value with French decimal comma."""
    return f"{value:,.1f}".replace(",", " ").replace(".", ",")


def load_sample_payload() -> tuple[dict[str, Any], bool]:
    """Load the demo payload, falling back only for input defaults."""
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
    """Return a canonical action dataframe repeated to a requested horizon."""
    base = actions or [dict.fromkeys(ACTION_COLUMNS, 0)]
    rows = [base[index % len(base)] for index in range(steps)]
    frame = pd.DataFrame(rows)
    for column in ACTION_COLUMNS:
        if column not in frame:
            frame[column] = 0
    return frame[ACTION_COLUMNS].astype(int)


def display_action_frame(actions: pd.DataFrame) -> pd.DataFrame:
    """Return an action dataframe with French display headers."""
    display = actions[ACTION_COLUMNS].copy()
    display.columns = fr_action_columns(ACTION_COLUMNS)
    return display


def canonical_action_frame(display: pd.DataFrame) -> pd.DataFrame:
    """Convert a French-labeled action dataframe back to API field names."""
    renamed = display.rename(columns=FRENCH_TO_ACTION)
    for column in ACTION_COLUMNS:
        if column not in renamed:
            renamed[column] = 0
    return renamed[ACTION_COLUMNS].fillna(0).astype(int)


def build_request(
    sample: dict[str, Any],
    history: list[float],
    actions: pd.DataFrame,
) -> SimulationRequest:
    """Build a typed simulation request from canonical action rows."""
    action_steps = [
        ActionStep(**{column: int(row[column]) for column in ACTION_COLUMNS})
        for row in actions[ACTION_COLUMNS].to_dict(orient="records")
    ]
    return SimulationRequest(
        hospital_id=str(sample.get("hospital_id", "hosp-001")),
        service_id=str(sample.get("service_id", "urg-001")),
        history_siips=history,
        actions=action_steps,
    )


def forecast_frame(response: SimulationResponse, limit: int | None = None) -> pd.DataFrame:
    """Convert simulation results into a dataframe with derived columns."""
    rows = [item.model_dump() for item in response.results]
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    frame["hour"] = frame["step_index"] + 1
    frame["ci_width"] = frame["upper_bound"] - frame["lower_bound"]
    if limit is not None:
        frame = frame.head(limit)
    return frame


def kpi_card(title: str, value: str, subtext: str, color: str = BLUE) -> None:
    """Render one compact KPI card."""
    st.markdown(
        f"""
<div class="hos-kpi-card">
  <div class="hos-kpi-label">{title}</div>
  <div class="hos-kpi-value" style="color:{color};">{value}</div>
  <div class="hos-kpi-note">{subtext}</div>
</div>
""",
        unsafe_allow_html=True,
    )


def status_badge(status: str) -> str:
    """Return a styled status badge as HTML."""
    label = STATUS_LABELS.get(status, status)
    color = STATUS_COLORS.get(status, GRAY)
    return (
        f'<span class="hos-pill"><span class="hos-risk-dot" '
        f'style="background:{color};"></span>{label}</span>'
    )


def forecast_figure(
    history: list[float],
    response: SimulationResponse,
    horizon: int = 48,
    critical_threshold: float = CRITICAL_THRESHOLD,
) -> go.Figure:
    """Create the 48h operational forecast figure with French labels."""
    frame = forecast_frame(response, limit=horizon)
    figure = go.Figure()
    x_history = list(range(-len(history) + 1, 1))
    figure.add_trace(
        go.Scatter(
            x=x_history,
            y=history,
            mode="lines",
            name="Historique",
            line={"color": BLUE, "width": 2},
            hovertemplate="T%{x}h<br>Historique %{y:.0f} SIIPS<extra></extra>",
        )
    )
    if frame.empty:
        return figure
    peak = frame.loc[frame["predicted_siips"].idxmax()]
    figure.add_trace(
        go.Scatter(
            x=frame["hour"],
            y=frame["upper_bound"],
            mode="lines",
            line={"width": 0},
            showlegend=False,
            hoverinfo="skip",
        )
    )
    figure.add_trace(
        go.Scatter(
            x=frame["hour"],
            y=frame["lower_bound"],
            mode="lines",
            fill="tonexty",
            fillcolor="rgba(192,57,43,0.15)",
            line={"width": 0},
            name="Intervalle 90%",
            hovertemplate="T+%{x}h<br>Borne basse %{y:.0f} SIIPS<extra></extra>",
        )
    )
    figure.add_trace(
        go.Scatter(
            x=frame["hour"],
            y=frame["predicted_siips"],
            mode="lines",
            name="Prévision médiane",
            line={"color": BLUE, "width": 3},
            hovertemplate="T+%{x}h<br>Charge prévue %{y:.0f} SIIPS<extra></extra>",
        )
    )
    figure.add_trace(
        go.Scatter(
            x=[0, horizon],
            y=[critical_threshold, critical_threshold],
            mode="lines",
            name="Seuil critique",
            line={"color": RED, "width": 2, "dash": "dash"},
            hovertemplate="Seuil critique %{y:.0f} SIIPS<extra></extra>",
        )
    )
    figure.add_trace(
        go.Scatter(
            x=[peak["hour"]],
            y=[peak["predicted_siips"]],
            mode="markers+text",
            name="Pic prévu",
            text=["Pic prévu"],
            textposition="top center",
            marker={"color": ORANGE, "size": 13, "symbol": "diamond"},
            hovertemplate="Pic T+%{x}h<br>%{y:.0f} SIIPS<extra></extra>",
        )
    )
    figure.update_layout(
        height=455,
        template="plotly_white",
        margin={"l": 18, "r": 18, "t": 22, "b": 18},
        xaxis_title="Horizon opérationnel (heures)",
        yaxis_title="Charge en soins prévue (SIIPS)",
        legend_title_text="Lecture",
    )
    return figure


def comparison_figure(
    response_a: SimulationResponse,
    response_b: SimulationResponse,
    critical_threshold: float = CRITICAL_THRESHOLD,
) -> go.Figure:
    """Create a Plan A / Plan B comparison chart."""
    figure = go.Figure()
    add_plan_trace(figure, response_a, "Plan A", BLUE)
    add_plan_trace(figure, response_b, "Plan B", RED)
    frame_a = forecast_frame(response_a)
    horizon = int(frame_a["hour"].max()) if not frame_a.empty else 48
    figure.add_trace(
        go.Scatter(
            x=[0, horizon],
            y=[critical_threshold, critical_threshold],
            mode="lines",
            name="Seuil critique",
            line={"color": RED, "width": 2, "dash": "dash"},
        )
    )
    figure.update_layout(
        height=430,
        template="plotly_white",
        xaxis_title="Horizon opérationnel (heures)",
        yaxis_title="Charge en soins prévue (SIIPS)",
        legend_title_text="Plans évalués",
    )
    return figure


def add_plan_trace(figure: go.Figure, response: SimulationResponse, label: str, color: str) -> None:
    """Add one plan with median and conformal interval to a Plotly figure."""
    frame = forecast_frame(response)
    figure.add_trace(
        go.Scatter(
            x=frame["hour"],
            y=frame["upper_bound"],
            mode="lines",
            line={"width": 0},
            showlegend=False,
            hoverinfo="skip",
        )
    )
    figure.add_trace(
        go.Scatter(
            x=frame["hour"],
            y=frame["lower_bound"],
            mode="lines",
            fill="tonexty",
            fillcolor="rgba(31,78,121,0.11)" if label == "Plan A" else "rgba(192,57,43,0.12)",
            line={"width": 0},
            name=f"{label} (IC 90%)",
        )
    )
    figure.add_trace(
        go.Scatter(
            x=frame["hour"],
            y=frame["predicted_siips"],
            mode="lines",
            line={"color": color, "width": 3},
            name=label,
        )
    )


def mini_sparkline(response: SimulationResponse) -> go.Figure:
    """Create a small sparkline from one response forecast."""
    frame = forecast_frame(response, limit=48)
    figure = go.Figure()
    if not frame.empty:
        figure.add_trace(
            go.Scatter(
                x=frame["hour"],
                y=frame["predicted_siips"],
                mode="lines",
                line={"color": BLUE, "width": 2},
                hoverinfo="skip",
            )
        )
    figure.update_xaxes(visible=False)
    figure.update_yaxes(visible=False)
    figure.update_layout(
        height=70,
        margin={"l": 0, "r": 0, "t": 0, "b": 0},
        template="plotly_white",
        showlegend=False,
    )
    return figure
