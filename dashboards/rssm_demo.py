"""Streamlit entrypoint for the HospitalOS Command Center demo."""

from __future__ import annotations

from datetime import date

import streamlit as st

from dashboards.api_client import WorldModelClient
from dashboards.sections import command_center, diagnostics, forecasting, simulation
from dashboards.styles import inject_css


def render() -> None:
    """Render the HospitalOS command-center shell and tab navigation."""
    st.set_page_config(
        page_title="Hospital World Model — Demo",
        layout="wide",
        initial_sidebar_state="collapsed",
    )
    inject_css()

    default_client = WorldModelClient(timeout_seconds=8.0)
    with st.sidebar:
        st.markdown("### Connexion API")
        api_base_url = st.text_input("URL backend", value=default_client.base_url)
        client = WorldModelClient(base_url=api_base_url, timeout_seconds=8.0)
        if st.button("Tester la connexion API"):
            if client.health_check():
                st.success("Backend opérationnel sur /health.")
            else:
                st.error(
                    "Backend indisponible. "
                    "Le tableau de bord utilisera les données de démonstration."
                )
        st.caption("Endpoint principal : POST /simulate/hospital-world")

    tabs = st.tabs(
        ["Command Center", "Simulation d’impact", "Prévision 48h", "Diagnostics"]
    )
    with tabs[0]:
        command_center.render(client)
    with tabs[1]:
        simulation.render(client)
    with tabs[2]:
        forecasting.render(client)
    with tabs[3]:
        diagnostics.render(client)

    st.caption(f"carepredict-mvp · HospitalOS Command · RSSM v1 · {date.today().isoformat()}")


if __name__ == "__main__":
    render()
