"""Hero 48h forecasting section for Hospitalos."""

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
    CRITICAL_THRESHOLD,
    build_request,
    canonical_action_frame,
    default_action_frame,
    display_action_frame,
    forecast_figure,
    forecast_frame,
    format_float,
    format_int,
    kpi_card,
    load_sample_payload,
)
from dashboards.state import derive_synthesis, get_state, update_state
from dashboards.styles import BLUE, ORANGE, RED

LOGGER = logging.getLogger(__name__)


def render(client: WorldModelClient) -> None:
    """Render the 48h operational forecast workflow."""
    sample, demo_payload_used = load_sample_payload()
    if demo_payload_used:
        st.info("Payload de démonstration utilisé.")

    state = get_state()
    history = state.history_siips or [float(value) for value in sample["history_siips"]]

    st.markdown("### Prévision opérationnelle 48 heures")
    render_synthesis(state.latest_response)

    left, right = st.columns([2, 1], gap="large")
    with left:
        st.markdown("#### Historique observé")
        history_frame = pd.DataFrame({"Charge en soins observée": history})
        edited_history = st.data_editor(
            history_frame,
            num_rows="fixed",
            use_container_width=True,
            key="forecast_history_editor",
        )
        history_values = [
            float(value) for value in edited_history["Charge en soins observée"].tolist()
        ]

    with right:
        st.markdown("#### Plan d’actions")
        horizon = st.slider("Horizon de prédiction (heures)", 1, 48, 24)
        action_frame = default_action_frame(sample.get("actions", []), horizon)
        edited_actions_display = st.data_editor(
            display_action_frame(action_frame),
            num_rows="fixed",
            use_container_width=True,
            key="forecast_action_editor",
        )
        edited_actions = canonical_action_frame(edited_actions_display)

    if st.button("Lancer la prédiction", type="primary", use_container_width=True):
        request = build_request(sample, history_values, edited_actions)
        with st.spinner("Interrogation du modèle RSSM..."):
            try:
                response = client.simulate(request)
            except WorldModelClientUnreachable:
                st.error(
                    "API indisponible. Démarrez le backend avec "
                    "`uvicorn services.api.main:app --port 8000`."
                )
                return
            except WorldModelClientValidationError as exc:
                st.error(f"Demande non valide : {exc}")
                return
            except WorldModelClientServerError as exc:
                st.error(f"Erreur backend : {exc}")
                LOGGER.exception("forecast_backend_error")
                return
            update_state(latest_response=response, history_siips=history_values)
            st.rerun()

    response_obj = get_state().latest_response
    if not isinstance(response_obj, SimulationResponse):
        st.markdown(
            '<div class="hos-empty-state">Aucune courbe disponible. '
            "Lancez une prédiction pour afficher la charge en soins prévue.</div>",
            unsafe_allow_html=True,
        )
        return

    st.plotly_chart(
        forecast_figure(history_values, response_obj, horizon=48),
        use_container_width=True,
        key="forecasting_command_forecast_48h",
    )
    render_kpis(response_obj)
    render_details(response_obj)


def render_synthesis(response: SimulationResponse | None) -> None:
    """Render the natural-language synthesis block above the chart."""
    if response is None:
        text = (
            "Aucune prédiction disponible. Cliquez sur 'Lancer la prédiction' "
            "ci-dessous pour interroger le modèle."
        )
    else:
        synthesis = derive_synthesis(response, critical_threshold=CRITICAL_THRESHOLD)
        frame = forecast_frame(response, limit=48)
        margin = 0.0
        if not frame.empty:
            margin = float(
                ((CRITICAL_THRESHOLD - frame["predicted_siips"]) / CRITICAL_THRESHOLD).mean()
                * 100.0
            )
        low, high = synthesis["peak_ci"]
        text = (
            f"Pic SIIPS prévu à T+{synthesis['peak_time_hours']}h : "
            f"{format_int(float(synthesis['peak_value']))} "
            f"(IC 90% [{format_int(float(low))}–{format_int(float(high))}]). "
            f"{synthesis['critical_count']} créneaux horaires en situation critique "
            f"sur 48h. Marge moyenne au seuil critique : {format_float(margin)}%."
        )
    st.markdown(f'<div class="hos-synthesis">{text}</div>', unsafe_allow_html=True)


def render_kpis(response: SimulationResponse) -> None:
    """Render the KPI row under the forecast chart."""
    frame = forecast_frame(response, limit=48)
    if frame.empty:
        return
    peak = frame.loc[frame["predicted_siips"].idxmax()]
    average_value = float(frame["predicted_siips"].mean())
    critical_count = int(frame["is_critical"].sum())
    mean_interval = float(frame["ci_width"].mean())
    columns = st.columns(5)
    with columns[0]:
        kpi_card(
            "Charge globale",
            format_int(average_value),
            f"Référence seuil {format_int(CRITICAL_THRESHOLD)}",
            RED if average_value >= CRITICAL_THRESHOLD else BLUE,
        )
    with columns[1]:
        kpi_card(
            "Pic prévu",
            format_int(float(peak["predicted_siips"])),
            f"à T+{int(peak['hour'])}h",
            ORANGE,
        )
    with columns[2]:
        kpi_card(
            "Créneaux critiques",
            str(critical_count),
            "sur 48h",
            RED if critical_count else BLUE,
        )
    with columns[3]:
        kpi_card("Intervalle moyen", format_int(mean_interval), "Largeur IC 90%", BLUE)
    with columns[4]:
        kpi_card("Confiance modèle", "90%", "Calibration conformelle", BLUE)


def render_details(response: SimulationResponse) -> None:
    """Render the per-step forecast details in an expander."""
    frame = forecast_frame(response, limit=48)
    display = frame[
        ["hour", "predicted_siips", "lower_bound", "upper_bound", "is_critical"]
    ].rename(
        columns={
            "hour": "Horaire (h)",
            "predicted_siips": "Charge en soins prévue",
            "lower_bound": "Borne basse",
            "upper_bound": "Borne haute",
            "is_critical": "Situation critique",
        }
    )
    with st.expander("Détails par créneau"):
        st.dataframe(display, use_container_width=True, hide_index=True)
