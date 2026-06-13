"""Guide rapide drawer for Hospitalos dashboard users."""

from __future__ import annotations

import streamlit as st

from dashboards import microcopy as copy
from dashboards.glossary import GLOSSARY


def render() -> None:
    """Render the guide rapide content in the main area."""
    st.markdown(copy.HELP_INTRO)
    st.markdown(f"### {copy.HELP_HOW_IT_WORKS_TITLE}")
    st.markdown(copy.HELP_HOW_IT_WORKS_BODY)

    st.divider()
    st.markdown(f"### {copy.HELP_GLOSSARY_TITLE}")
    st.markdown(copy.HELP_GLOSSARY_INTRO)
    for term, definition in GLOSSARY.items():
        st.markdown(f"**{term}** — {definition}")

    st.divider()
    st.markdown(f"### {copy.HELP_USE_CASES_TITLE}")
    st.markdown(copy.HELP_USE_CASES_BODY)

    st.divider()
    if st.button(copy.HELP_CLOSE, key="help_close_button", use_container_width=True):
        st.session_state.show_help = False
        st.rerun()
