"""Product-grade impact simulation section for HospitalOS Command."""

from __future__ import annotations

import logging

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from dashboards.api_client import SimulationResponse, WorldModelClient, WorldModelClientError
from dashboards.components import (
    ACTION_COLUMNS,
    BLUE,
    RED,
    build_request,
    default_action_frame,
    fallback_response,
    forecast_frame,
    load_sample_payload,
    natural_impact_summary,
)

LOGGER = logging.getLogger(__name__)


def render(client: WorldModelClient) -> None:
    """Render before/after operational intervention simulation."""
    sample, demo_payload_used = load_sample_payload()
    if demo_payload_used:
        st.info("Payload de démonstration utilisé.")
    history = st.session_state.get("rssm_history", sample["history_siips"])
    st.markdown('<div class="hos-section-title">Simulation d’impact</div>', unsafe_allow_html=True)
    st.caption("Comparer un plan de base et une action opérationnelle recommandée.")

    history_frame = pd.DataFrame({"Charge en soins": history})
    edited_history = st.data_editor(
        history_frame,
        num_rows="fixed",
        use_container_width=True,
        key="simulation_history_editor",
    )
    history_values = [float(value) for value in edited_history["Charge en soins"].tolist()]
    st.session_state["rssm_history"] = history_values

    steps = st.slider("Impact attendu sur les prochaines heures", 4, 48, 24, step=4)
    baseline_default = default_action_frame(sample.get("actions", []), steps)
    intervention_default = baseline_default.copy()
    intervention_default["staff_redeployments"] = intervention_default["staff_redeployments"] + 1
    intervention_default["scheduled_discharges"] = intervention_default["scheduled_discharges"] + 1

    left, right = st.columns(2, gap="large")
    with left:
        st.markdown("#### Situation de référence")
        scenario_a = st.data_editor(
            baseline_default[ACTION_COLUMNS],
            num_rows="fixed",
            use_container_width=True,
            key="scenario_a_actions",
        )
    with right:
        st.markdown("#### Action recommandée")
        scenario_b = st.data_editor(
            intervention_default[ACTION_COLUMNS],
            num_rows="fixed",
            use_container_width=True,
            key="scenario_b_actions",
        )

    if st.button("Simuler l’impact opérationnel"):
        with st.spinner("Simulation des scénarios opérationnels..."):
            try:
                response_a = client.simulate(build_request(sample, history_values, scenario_a))
                response_b = client.simulate(build_request(sample, history_values, scenario_b))
            except WorldModelClientError as exc:
                st.warning("API indisponible — comparaison de démonstration affichée.")
                LOGGER.warning("simulation_fallback", exc_info=exc)
                response_a = fallback_response(sample, horizon=steps)
                response_b = adjusted_intervention_response(response_a)
            st.session_state["scenario_a_response"] = response_a
            st.session_state["scenario_b_response"] = response_b

    response_a_obj = st.session_state.get("scenario_a_response")
    response_b_obj = st.session_state.get("scenario_b_response")
    if isinstance(response_a_obj, SimulationResponse) and isinstance(
        response_b_obj, SimulationResponse
    ):
        st.plotly_chart(
            build_comparison_figure(response_a_obj, response_b_obj),
            use_container_width=True,
            key="simulation_before_after_chart",
        )
        summary = comparison_frame(response_a_obj, response_b_obj)
        st.markdown(f"**Action recommandée.** {natural_impact_summary(summary)}")
        st.dataframe(summary, use_container_width=True, hide_index=True)


def adjusted_intervention_response(response: SimulationResponse) -> SimulationResponse:
    """Return a deterministic improved response for offline intervention demos."""
    rows = []
    for item in response.results:
        improvement = 3.0 + item.step_index * 0.08
        value = max(0.0, item.predicted_siips - improvement)
        rows.append(
            {
                "step_index": item.step_index,
                "predicted_siips": value,
                "lower_bound": max(0.0, item.lower_bound - improvement),
                "upper_bound": max(value + 1.0, item.upper_bound - improvement),
                "reward": item.reward + 0.4,
                "is_critical": value >= 105,
            }
        )
    return SimulationResponse(
        status=response.status,
        hospital_id=response.hospital_id,
        service_id=response.service_id,
        model_version=response.model_version,
        results=rows,
    )


def build_comparison_figure(
    response_a: SimulationResponse,
    response_b: SimulationResponse,
) -> go.Figure:
    """Create a before/after chart with confidence bands."""
    figure = go.Figure()
    add_scenario(figure, response_a, "Avant action", BLUE)
    add_scenario(figure, response_b, "Après action", RED)
    figure.update_layout(
        height=430,
        template="plotly_white",
        xaxis_title="Horizon opérationnel (heures)",
        yaxis_title="Charge en soins prévue (SIIPS)",
        legend_title_text="Simulation d’impact",
    )
    return figure


def add_scenario(figure: go.Figure, response: SimulationResponse, label: str, color: str) -> None:
    """Add one scenario median and interval to a Plotly figure."""
    frame = forecast_frame(response)
    figure.add_trace(
        go.Scatter(
            x=frame["hour"],
            y=frame["upper_bound"],
            line={"width": 0},
            name=f"{label} haut",
        )
    )
    figure.add_trace(
        go.Scatter(
            x=frame["hour"],
            y=frame["lower_bound"],
            line={"width": 0},
            fill="tonexty",
            opacity=0.2,
            name=f"{label} fourchette",
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


def comparison_frame(
    response_a: SimulationResponse,
    response_b: SimulationResponse,
) -> pd.DataFrame:
    """Return an operational comparison table."""
    rows = []
    for left, right in zip(response_a.results, response_b.results, strict=True):
        rows.append(
            {
                "step_index": left.step_index + 1,
                "A_predicted": left.predicted_siips,
                "A_width": left.upper_bound - left.lower_bound,
                "B_predicted": right.predicted_siips,
                "B_width": right.upper_bound - right.lower_bound,
                "delta": right.predicted_siips - left.predicted_siips,
                "critical_change": left.is_critical and not right.is_critical,
            }
        )
    return pd.DataFrame(rows)
