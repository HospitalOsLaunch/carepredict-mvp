"""HospitalOS Command Center default dashboard section."""

from __future__ import annotations

import logging

import streamlit as st

from dashboards.api_client import WorldModelClient, WorldModelClientError
from dashboards.components import (
    DashboardScenario,
    alert_cards,
    build_request,
    command_forecast_figure,
    default_action_frame,
    fallback_response,
    forecast_frame,
    load_sample_payload,
    now_label,
    propagation_figure,
    render_alert_card,
    render_kpi_strip,
    render_service_card,
    render_topbar,
    service_statuses,
)

LOGGER = logging.getLogger(__name__)


def load_command_scenario(client: WorldModelClient) -> DashboardScenario:
    """Load live command-center forecast or deterministic demo fallback."""
    sample, demo_payload_used = load_sample_payload()
    history = [float(value) for value in sample["history_siips"]]
    actions = default_action_frame(sample.get("actions", []), 48)
    request = build_request(sample, history, actions)
    try:
        response = client.simulate(request)
    except WorldModelClientError as exc:
        LOGGER.warning("command_center_fallback", exc_info=exc)
        return DashboardScenario(
            response=fallback_response(sample, horizon=48),
            backend_live=False,
            demo_payload_used=True,
            error_message=str(exc),
        )
    return DashboardScenario(
        response=response,
        backend_live=True,
        demo_payload_used=demo_payload_used,
        error_message=None,
    )


def render(client: WorldModelClient) -> None:
    """Render the first-screen HospitalOS operations command center."""
    scenario = st.session_state.get("command_center_scenario")
    if not isinstance(scenario, DashboardScenario):
        with st.spinner("Actualisation de la situation hospitalière..."):
            scenario = load_command_scenario(client)
            st.session_state["command_center_scenario"] = scenario
    sample, _demo = load_sample_payload()
    history = [float(value) for value in sample["history_siips"]]
    statuses = service_statuses(scenario.response, history)
    render_topbar(
        live=scenario.backend_live,
        model_version=scenario.response.model_version,
        hospital_id=scenario.response.hospital_id,
        service_id=scenario.response.service_id,
        refreshed_at=now_label(),
    )
    if scenario.demo_payload_used:
        st.info("Payload de démonstration utilisé.")
    if scenario.error_message:
        st.warning("API indisponible — données de démonstration affichées.")

    left, center, right = st.columns([0.95, 1.65, 1.0], gap="large")
    with left:
        st.markdown(
            '<div class="hos-section-title">Services à risque</div>',
            unsafe_allow_html=True,
        )
        for index, status in enumerate(statuses):
            render_service_card(status, dominant=index == 0)
    with center:
        st.markdown(
            '<div class="hos-section-title">Propagation de la charge</div>',
            unsafe_allow_html=True,
        )
        st.markdown('<div class="hos-card">', unsafe_allow_html=True)
        st.plotly_chart(
            propagation_figure(statuses),
            use_container_width=True,
            key="command_center_propagation_chart",
        )
        st.markdown(
            '<div class="hos-caption">La charge opérationnelle se diffuse entre '
            'services via les lits, les transferts et les équipes disponibles.</div></div>',
            unsafe_allow_html=True,
        )
    with right:
        st.markdown(
            '<div class="hos-section-title">Alertes prédictives</div>',
            unsafe_allow_html=True,
        )
        for alert in alert_cards(scenario.response, statuses):
            render_alert_card(alert)

    st.markdown(
        '<div class="hos-section-title">Prévision exécutive 48h</div>',
        unsafe_allow_html=True,
    )
    st.markdown('<div class="hos-card">', unsafe_allow_html=True)
    st.plotly_chart(
        command_forecast_figure(scenario.response, horizon=48),
        use_container_width=True,
        key="command_center_forecast_chart",
    )
    frame = forecast_frame(scenario.response, limit=48)
    if not frame.empty:
        peak = frame.loc[frame["predicted_siips"].idxmax()]
        critical_count = int(frame["is_critical"].sum())
        st.caption(
            f"Pic prévu à T+{int(peak['hour'])}H · "
            f"{critical_count} pas horaires en situation critique sur 48h."
        )
    st.markdown("</div>", unsafe_allow_html=True)

    render_kpi_strip(scenario.response, statuses)
    if st.button("Rafraîchir la situation opérationnelle"):
        st.session_state.pop("command_center_scenario", None)
        st.rerun()
