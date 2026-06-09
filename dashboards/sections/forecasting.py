"""Executive 48h forecasting section for HospitalOS Command."""

from __future__ import annotations

import logging

import pandas as pd
import streamlit as st

from dashboards.api_client import (
    SimulationResponse,
    WorldModelClient,
    WorldModelClientServerError,
    WorldModelClientUnreachable,
    WorldModelClientValidationError,
)
from dashboards.components import (
    ACTION_COLUMNS,
    build_request,
    command_forecast_figure,
    default_action_frame,
    fallback_response,
    forecast_frame,
    load_sample_payload,
)

LOGGER = logging.getLogger(__name__)


def render(client: WorldModelClient) -> None:
    """Render editable 48h forecast inputs and executive forecast output."""
    sample, demo_payload_used = load_sample_payload()
    if demo_payload_used:
        st.info("Payload de démonstration utilisé.")
    history = st.session_state.get("rssm_history", sample["history_siips"])
    st.markdown('<div class="hos-section-title">Prévision 48h</div>', unsafe_allow_html=True)
    st.caption("Ajuster l’historique et les actions prévues, puis recalculer la charge en soins.")

    left, right = st.columns([0.95, 1.25], gap="large")
    with left:
        st.markdown("#### Historique observé")
        history_frame = pd.DataFrame({"Charge en soins": history})
        edited_history = st.data_editor(
            history_frame,
            num_rows="fixed",
            use_container_width=True,
            key="forecast_history_editor",
        )
        history_values = [float(value) for value in edited_history["Charge en soins"].tolist()]
        st.session_state["rssm_history"] = history_values
    with right:
        st.markdown("#### Actions recommandées")
        steps = st.slider("Horizon de simulation", min_value=4, max_value=48, value=48, step=4)
        action_frame = default_action_frame(sample.get("actions", []), steps)
        edited_actions = st.data_editor(
            action_frame[ACTION_COLUMNS],
            num_rows="fixed",
            use_container_width=True,
            key="forecast_action_editor",
        )

    if st.button("Recalculer la charge prévue"):
        request = build_request(sample, history_values, edited_actions)
        with st.spinner("Calcul de la prévision opérationnelle..."):
            try:
                response = client.simulate(request)
            except WorldModelClientUnreachable:
                st.warning("API indisponible — prévision de démonstration affichée.")
                response = fallback_response(sample, horizon=steps)
            except WorldModelClientValidationError as exc:
                st.error(f"Demande non valide : {exc}")
                return
            except WorldModelClientServerError as exc:
                st.error(f"Erreur backend : {exc}")
                LOGGER.exception("forecast_backend_error")
                return
            st.session_state["forecast_response"] = response

    response_obj = st.session_state.get("forecast_response")
    if not isinstance(response_obj, SimulationResponse):
        response_obj = fallback_response(sample, horizon=48)
    st.markdown('<div class="hos-card">', unsafe_allow_html=True)
    st.plotly_chart(
        command_forecast_figure(response_obj, horizon=48),
        use_container_width=True,
        key="forecasting_command_forecast_48h",
    )
    st.markdown('</div>', unsafe_allow_html=True)
    frame = forecast_frame(response_obj, limit=48)
    if not frame.empty:
        display = frame[
            ["hour", "predicted_siips", "lower_bound", "upper_bound", "is_critical"]
        ].rename(
            columns={
                "hour": "Heure",
                "predicted_siips": "Charge en soins prévue",
                "lower_bound": "Fourchette basse",
                "upper_bound": "Fourchette haute",
                "is_critical": "Situation critique",
            }
        )
        st.dataframe(display, use_container_width=True, hide_index=True)
