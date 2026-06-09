"""Shared visual styling for the Hospitalos Streamlit dashboard."""

from __future__ import annotations

import streamlit as st

BLUE = "#1f4e79"
RED = "#c0392b"
ORANGE = "#d97706"
GRAY = "#6b7280"
INK = "#102033"
MUTED = GRAY
BORDER = "#e6e8ec"
SURFACE = "#ffffff"
BACKGROUND = "#f7f6f2"

STATUS_COLORS = {
    "critical": RED,
    "watch": ORANGE,
    "normal": BLUE,
}


def inject_css() -> None:
    """Inject the restrained Hospitalos visual system."""
    st.markdown(
        f"""
<style>
.stApp {{
    background: {BACKGROUND};
    color: {INK};
}}
.block-container {{
    padding-top: 1.4rem;
    padding-bottom: 2.5rem;
    max-width: 1500px;
}}
[data-testid="stSidebar"] {{
    background: #ffffff;
    border-right: 1px solid {BORDER};
}}
.hos-topbar {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 18px;
    padding: 16px 18px;
    border: 1px solid {BORDER};
    border-radius: 22px;
    background: rgba(255, 255, 255, 0.92);
    box-shadow: 0 14px 36px rgba(16, 32, 51, 0.06);
    margin-bottom: 18px;
}}
.hos-brand {{
    font-size: 22px;
    font-weight: 800;
    letter-spacing: 0.04em;
    color: {INK};
}}
.hos-subtitle {{
    color: {MUTED};
    font-size: 13px;
    margin-top: 3px;
}}
.hos-pill {{
    display: inline-flex;
    align-items: center;
    gap: 7px;
    padding: 7px 10px;
    border-radius: 999px;
    border: 1px solid {BORDER};
    background: #ffffff;
    color: {MUTED};
    font-size: 12px;
    font-weight: 650;
    white-space: nowrap;
}}
.hos-card {{
    border: 1px solid {BORDER};
    border-radius: 20px;
    background: {SURFACE};
    box-shadow: 0 12px 30px rgba(16, 32, 51, 0.055);
    padding: 16px;
    margin-bottom: 14px;
}}
.hos-synthesis {{
    border: 1px solid {BORDER};
    border-left: 5px solid {BLUE};
    border-radius: 18px;
    background: #ffffff;
    color: {INK};
    box-shadow: 0 10px 24px rgba(16, 32, 51, 0.045);
    padding: 15px 17px;
    margin: 12px 0 18px;
    font-size: 15px;
    line-height: 1.45;
}}
.hos-section-title {{
    font-size: 15px;
    font-weight: 800;
    color: {INK};
    margin: 4px 0 12px;
}}
.hos-card-kicker {{
    color: {MUTED};
    font-size: 12px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.05em;
}}
.hos-big-number {{
    color: {INK};
    font-size: 38px;
    line-height: 1.0;
    font-weight: 850;
    margin: 6px 0;
}}
.hos-caption {{
    color: {MUTED};
    font-size: 13px;
    line-height: 1.45;
}}
.hos-risk-dot {{
    width: 9px;
    height: 9px;
    border-radius: 999px;
    display: inline-block;
}}
.hos-alert-card {{
    border-left: 5px solid var(--risk-color);
}}
.hos-kpi-card {{
    border: 1px solid {BORDER};
    border-radius: 18px;
    background: #ffffff;
    box-shadow: 0 10px 24px rgba(16, 32, 51, 0.045);
    padding: 15px;
    min-height: 116px;
}}
.hos-kpi-value {{
    font-size: 28px;
    font-weight: 850;
    color: {INK};
}}
.hos-kpi-label {{
    font-size: 13px;
    color: {MUTED};
    font-weight: 750;
}}
.hos-kpi-note {{
    color: {MUTED};
    font-size: 12px;
    margin-top: 6px;
}}
.hos-empty-state {{
    border: 1px dashed {BORDER};
    border-radius: 18px;
    background: #fffdf8;
    color: {MUTED};
    padding: 18px;
}}
</style>
""",
        unsafe_allow_html=True,
    )
