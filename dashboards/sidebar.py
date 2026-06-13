"""Persistent sidebar for the Hospitalos dashboard."""

from __future__ import annotations

from datetime import date

import streamlit as st

from dashboards import microcopy as copy
from dashboards.api_client import WorldModelClient
from dashboards.components import format_int
from dashboards.state import derive_synthesis, get_state


def render(client: WorldModelClient) -> None:
    """Render persistent navigation, API status, and prediction summary."""
    state = get_state()
    with st.sidebar:
        st.markdown(f"### {copy.SIDEBAR_BRAND}")
        st.caption(copy.SIDEBAR_TAGLINE)
        st.divider()

        st.markdown(f"#### {copy.SIDEBAR_TITLE}")
        api_url = st.text_input(
            copy.SIDEBAR_API_LABEL,
            value=st.session_state.get("api_base_url", client.base_url),
            help=copy.SIDEBAR_API_HELP,
            key="sb_api_url_input",
        )
        st.session_state.api_base_url = api_url
        if st.button(
            copy.SIDEBAR_TEST_BUTTON,
            use_container_width=True,
            key="sb_test_connection_button",
        ):
            st.session_state.api_status = client.health_check()
        if "api_status" in st.session_state:
            if st.session_state.api_status:
                st.success(copy.SIDEBAR_STATUS_OK_MARKED)
            else:
                st.error(copy.SIDEBAR_STATUS_DOWN_MARKED)

        st.divider()
        st.markdown(f"#### {copy.SIDEBAR_NAV_TITLE}")
        st.caption(copy.SIDEBAR_NAV_FORECAST)
        st.caption(copy.SIDEBAR_NAV_SIMULATION)
        st.caption(copy.SIDEBAR_NAV_EXECUTIVE)
        st.caption(copy.SIDEBAR_NAV_DIAGNOSTICS)

        if state.latest_response is not None:
            st.divider()
            synthesis = derive_synthesis(state.latest_response)
            st.caption(
                copy.SIDEBAR_LAST_PREDICTION.format(
                    datetime=state.last_refreshed_at or copy.SIDEBAR_UNDATED
                )
            )
            st.caption(
                copy.SIDEBAR_PEAK_TEMPLATE.format(
                    peak_value=format_int(float(synthesis["peak_value"])),
                    peak_hours=int(synthesis["peak_time_hours"]),
                )
            )
            st.caption(copy.SIDEBAR_CRITICAL_TEMPLATE.format(count=synthesis["critical_count"]))

        st.divider()
        st.markdown(f"#### {copy.SIDEBAR_HELP_TITLE}")
        if st.button(
            copy.SIDEBAR_HELP_OPEN,
            use_container_width=True,
            key="sb_open_help_button",
        ):
            st.session_state.show_help = True
            st.rerun()

        st.divider()
        st.caption(copy.SIDEBAR_FOOTER_TEMPLATE.format(date=date.today().isoformat()))
