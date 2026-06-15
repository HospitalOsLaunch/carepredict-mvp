"""Plan A / Plan B impact simulation section for Hospitalos."""

from __future__ import annotations

import logging

import pandas as pd
import streamlit as st

from dashboards.api_client import (
    SimulationResponse,
    WorldModelClient,
    WorldModelClientError,
)
from dashboards.components import (
    build_request,
    canonical_action_frame,
    comparison_figure,
    default_action_frame,
    display_action_frame,
    format_float,
    format_int,
    load_sample_payload,
)
from dashboards.state import get_state, update_state

LOGGER = logging.getLogger(__name__)


def render(client: WorldModelClient) -> None:
    """Render the operational Plan A / Plan B comparison workflow."""
    sample, demo_payload_used = load_sample_payload()
    if demo_payload_used:
        st.info("Payload de démonstration utilisé.")

    state = get_state()
    history = state.history_siips or [float(value) for value in sample["history_siips"]]

    st.markdown("### Simulation what-if")
    st.caption(
        "Comparez deux plans d'actions opérationnelles pour anticiper "
        "leur impact respectif sur la charge soignante."
    )

    history_frame = pd.DataFrame({"Charge en soins observée": history})
    edited_history = st.data_editor(
        history_frame,
        num_rows="fixed",
        use_container_width=True,
        key="simulation_history_editor",
    )
    history_values = [float(value) for value in edited_history["Charge en soins observée"]]

    steps = st.slider("Horizon de comparaison (heures)", 1, 48, 24)
    baseline_default = default_action_frame(sample.get("actions", []), steps)
    intervention_default = baseline_default.copy()
    intervention_default["staff_redeployments"] = intervention_default["staff_redeployments"] + 1
    intervention_default["scheduled_discharges"] = intervention_default["scheduled_discharges"] + 1

    left, right = st.columns(2, gap="large")
    with left:
        st.markdown("#### Plan A — Situation actuelle")
        plan_a_display = st.data_editor(
            display_action_frame(baseline_default),
            num_rows="fixed",
            use_container_width=True,
            key="scenario_a_actions",
        )
    with right:
        st.markdown("#### Plan B — Action envisagée")
        plan_b_display = st.data_editor(
            display_action_frame(intervention_default),
            num_rows="fixed",
            use_container_width=True,
            key="scenario_b_actions",
        )

    if st.button("Comparer les deux plans", type="primary", use_container_width=True):
        plan_a = canonical_action_frame(plan_a_display)
        plan_b = canonical_action_frame(plan_b_display)
        with st.spinner("Évaluation des deux plans opérationnels..."):
            try:
                response_a = client.simulate(build_request(sample, history_values, plan_a))
                response_b = client.simulate(build_request(sample, history_values, plan_b))
            except WorldModelClientError as exc:
                st.error(
                    "API indisponible ou réponse invalide. "
                    "Aucune simulation de remplacement n'est générée."
                )
                LOGGER.exception("simulation_backend_error", exc_info=exc)
                return
            update_state(
                history_siips=history_values,
                compare_baseline=response_a,
                compare_intervention=response_b,
            )
            st.rerun()

    state = get_state()
    response_a_obj = state.compare_baseline
    response_b_obj = state.compare_intervention
    if isinstance(response_a_obj, SimulationResponse) and isinstance(
        response_b_obj, SimulationResponse
    ):
        st.plotly_chart(
            comparison_figure(response_a_obj, response_b_obj),
            use_container_width=True,
            key="simulation_before_after_chart",
        )
        summary = comparison_frame(response_a_obj, response_b_obj)
        st.markdown(
            f'<div class="hos-synthesis">{impact_sentence(summary)}</div>',
            unsafe_allow_html=True,
        )
        with st.expander("Comparaison détaillée"):
            st.dataframe(summary, use_container_width=True, hide_index=True)


def comparison_frame(
    response_a: SimulationResponse,
    response_b: SimulationResponse,
) -> pd.DataFrame:
    """Return a French-labeled operational comparison table."""
    rows = []
    for left, right in zip(response_a.results, response_b.results, strict=True):
        rows.append(
            {
                "Horaire (h)": left.step_index + 1,
                "Plan A (SIIPS)": round(left.predicted_siips, 1),
                "Plan A IC": f"[{format_int(left.lower_bound)}, {format_int(left.upper_bound)}]",
                "Plan B (SIIPS)": round(right.predicted_siips, 1),
                "Plan B IC": f"[{format_int(right.lower_bound)}, {format_int(right.upper_bound)}]",
                "Différence": round(right.predicted_siips - left.predicted_siips, 1),
                "Critique?": right.is_critical,
            }
        )
    return pd.DataFrame(rows)


def impact_sentence(summary: pd.DataFrame) -> str:
    """Build a concise Plan B vs Plan A operational summary."""
    if summary.empty:
        return "Aucun résultat de simulation disponible."
    total_a = float(summary["Plan A (SIIPS)"].sum())
    total_delta = float(summary["Différence"].sum())
    pct = (total_delta / total_a * 100.0) if total_a else 0.0
    critical_reduction = int(((~summary["Critique?"]) & (summary["Plan A (SIIPS)"] >= 850.0)).sum())
    if total_delta <= 0:
        direction = f"Plan B réduit la charge totale de {format_float(abs(pct))}% sur 48h."
    else:
        direction = f"Plan B augmente la charge totale de {format_float(abs(pct))}% sur 48h."
    return f"{direction} {critical_reduction} créneaux critiques en moins que le Plan A."
