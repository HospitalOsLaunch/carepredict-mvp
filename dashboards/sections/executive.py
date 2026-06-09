"""Executive synthesis tab derived from the latest model response."""

from __future__ import annotations

import streamlit as st

from dashboards.api_client import WorldModelClient
from dashboards.components import (
    CRITICAL_THRESHOLD,
    forecast_frame,
    format_int,
    kpi_card,
    mini_sparkline,
    status_badge,
)
from dashboards.labels import fr_service_name, status_from_score
from dashboards.state import derive_synthesis, get_state
from dashboards.styles import BLUE, ORANGE, RED


def render(client: WorldModelClient) -> None:
    """Render the factual executive view from shared dashboard state."""
    _ = client
    st.markdown("### Vue exécutive")
    st.caption("Synthèse opérationnelle dérivée de la dernière prédiction.")

    state = get_state()
    if state.latest_response is None:
        st.info(
            "Aucune prédiction disponible. Lancez d'abord une prédiction "
            "dans l'onglet 'Prévision 48h'."
        )
        return

    response = state.latest_response
    synthesis = derive_synthesis(response, critical_threshold=CRITICAL_THRESHOLD)
    render_top_metrics(response.model_version, synthesis)
    render_service_section()
    render_alerts()
    st.markdown(
        "Le modèle prédit la charge service par service. "
        "La propagation inter-services nécessite une instance par service et "
        "n'est pas encore exposée dans cette démo."
    )


def render_top_metrics(model_version: str, synthesis: dict[str, object]) -> None:
    """Render system status, expected peak and model version."""
    critical_count = int(synthesis["critical_count"])
    if critical_count >= 3:
        status = "Critique"
        color = RED
    elif critical_count >= 1:
        status = "Sous surveillance"
        color = ORANGE
    else:
        status = "Stable"
        color = BLUE

    columns = st.columns(3)
    with columns[0]:
        kpi_card("Statut système", status, f"{critical_count} créneaux critiques", color)
    with columns[1]:
        kpi_card(
            "Pic prévu (48h)",
            format_int(float(synthesis["peak_value"])),
            f"à T+{int(synthesis['peak_time_hours'])}h",
            ORANGE,
        )
    with columns[2]:
        kpi_card("Modèle", model_version, "Dernière réponse API", BLUE)


def render_service_section() -> None:
    """Render one real service card from the latest response."""
    state = get_state()
    response = state.latest_response
    if response is None:
        return
    frame = forecast_frame(response, limit=48)
    if frame.empty:
        st.info("Aucun point de prévision disponible pour le service.")
        return

    current_siips = float(state.history_siips[-1]) if state.history_siips else 0.0
    peak_siips = float(frame["predicted_siips"].max())
    status = status_from_score(peak_siips, CRITICAL_THRESHOLD)
    label = fr_service_name(response.service_id)

    _, center, _ = st.columns([1, 1.2, 1])
    with center:
        st.markdown(
            f"""
<div class="hos-card">
  <div class="hos-card-kicker">Service à risque</div>
  <div class="hos-section-title">{label}</div>
  <div class="hos-caption">SIIPS actuel : {format_int(current_siips)}</div>
  <div class="hos-big-number">{format_int(peak_siips)}</div>
  <div class="hos-caption">SIIPS prévu maximal sur 48h</div>
  <div style="margin-top:10px;">{status_badge(status)}</div>
</div>
""",
            unsafe_allow_html=True,
        )
        st.plotly_chart(
            mini_sparkline(response),
            use_container_width=True,
            key=f"executive_service_sparkline_{response.service_id}",
        )


def render_alerts() -> None:
    """Render factual alerts from critical forecast steps."""
    state = get_state()
    response = state.latest_response
    if response is None:
        return

    critical_steps = [step for step in response.results if step.is_critical]
    st.markdown("#### Alertes prédictives")
    if not critical_steps:
        st.info("Aucune alerte sur les 48 prochaines heures.")
        return

    for step in critical_steps[:6]:
        st.markdown(
            f"""
<div class="hos-card hos-alert-card" style="--risk-color:{RED};">
  <div class="hos-card-kicker">T+{step.step_index + 1}h</div>
  <div class="hos-section-title">Dépassement seuil critique prévu</div>
  <div class="hos-caption">
    SIIPS {format_int(step.predicted_siips)}
    (IC 90% [{format_int(step.lower_bound)}, {format_int(step.upper_bound)}]).
  </div>
</div>
""",
            unsafe_allow_html=True,
        )
