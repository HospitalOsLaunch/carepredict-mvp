"""Streamlit entrypoint for the Hospitalos predictive operations dashboard."""

from __future__ import annotations

from datetime import date

import streamlit as st

from dashboards.api_client import WorldModelClient
from dashboards.sections import diagnostics, executive, forecasting, simulation
from dashboards.styles import inject_css


def render() -> None:
    """Render the Hospitalos shell and tab navigation."""
    st.set_page_config(
        page_title="Hospitalos — Pilotage prédictif",
        layout="wide",
        initial_sidebar_state="collapsed",
    )
    inject_css()

    st.title("Hospitalos — Pilotage prédictif")
    st.caption(
        "Anticipation de la charge soignante par world model RSSM calibré "
        "sur intervalles conformels."
    )

    default_client = WorldModelClient(timeout_seconds=8.0)
    with st.sidebar:
        st.markdown("### Connexion API")
        api_base_url = st.text_input("URL backend", value=default_client.base_url)
        client = WorldModelClient(base_url=api_base_url, timeout_seconds=8.0)
        if st.button("Tester la connexion API"):
            if client.health_check():
                st.success("Backend opérationnel sur /health.")
            else:
                st.error("Backend indisponible. Les prédictions ne pourront pas être lancées.")
        st.caption("Endpoint principal : POST /simulate/hospital-world")

    tabs = st.tabs(["Prévision 48h", "Simulation what-if", "Vue exécutive", "Diagnostics modèle"])
    with tabs[0]:
        forecasting.render(client)
    with tabs[1]:
        simulation.render(client)
    with tabs[2]:
        executive.render(client)
    with tabs[3]:
        diagnostics.render(client)

    st.caption(f"Hospitalos · Modèle RSSM v1 · Données synthétiques · {date.today().isoformat()}")


if __name__ == "__main__":
    render()
