"""Diagnostics and expert-mode panel for HospitalOS Command."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np
import plotly.graph_objects as go
import streamlit as st

from dashboards.api_client import WorldModelClient

LOGGER = logging.getLogger(__name__)


def render(client: WorldModelClient | None = None) -> None:
    """Render expert diagnostics without loading model objects directly."""
    st.markdown('<div class="hos-section-title">Diagnostics expert</div>', unsafe_allow_html=True)
    render_runtime_status(client)
    render_training_curves()
    render_model_card()
    render_conformal_coverage(Path("artifacts/conformal_residuals.npz"))
    render_limitations()


def render_runtime_status(client: WorldModelClient | None) -> None:
    """Show API and artifact availability for expert review."""
    api_health = client.health_check() if client is not None else False
    artifact_paths = {
        "RSSM checkpoint": Path("artifacts/rssm_checkpoint.pt"),
        "Scaler": Path("artifacts/siips_scaler.npz"),
        "Conformal residuals": Path("artifacts/conformal_residuals.npz"),
        "Training curves": Path("artifacts/training_curves.png"),
    }
    rows = [
        {"Signal": "API health", "Statut": "LIVE" if api_health else "Indisponible"},
        {"Signal": "Fallback mode", "Statut": "Actif si API ou bundle indisponible"},
    ]
    rows.extend(
        {"Signal": label, "Statut": "Disponible" if path.exists() else "Manquant"}
        for label, path in artifact_paths.items()
    )
    st.dataframe(rows, use_container_width=True, hide_index=True)


def render_training_curves() -> None:
    """Display training curves or a graceful empty state."""
    curve_path = Path("artifacts/training_curves.png")
    st.markdown("#### Courbes d’entraînement")
    if curve_path.exists():
        st.image(str(curve_path), caption="Courbes d’entraînement RSSM")
    else:
        st.markdown(
            '<div class="hos-empty-state">Courbes d’entraînement non disponibles '
            'dans ce checkout.<br><code>python scripts/train_rssm_synthetic.py --plot</code></div>',
            unsafe_allow_html=True,
        )


def render_model_card() -> None:
    """Render the operational model card with file-derived metadata."""
    checkpoint_path = Path("artifacts/rssm_checkpoint.pt")
    checkpoint_status = "disponible" if checkpoint_path.exists() else "manquant"
    residual_path = Path("artifacts/conformal_residuals.npz")
    residual_status = "disponible" if residual_path.exists() else "manquant"
    st.markdown(
        f"""
#### Model card

- Model backend: RSSM Hospital World Model via FastAPI `/simulate/hospital-world`.
- Bundle status: checkpoint {checkpoint_status}; résidus conformal {residual_status}.
- Architecture: RSSM DreamerV3-style, état déterministe `h_t` + latent gaussien `z_t`.
- Calibration: split-conformal alpha = 0.1.
- Critical threshold: p95 de la charge SIIPS du service.
- Référence: Hafner et al. 2023, "Mastering Diverse Domains through World Models".
"""
    )


def render_conformal_coverage(residual_path: Path) -> None:
    """Display residual histograms per horizon step when residuals are available."""
    st.markdown("#### Couverture conformal")
    if not residual_path.exists():
        st.info("Résidus conformal non disponibles.")
        return
    residuals = load_residuals(residual_path)
    if residuals.size == 0:
        st.info("Le fichier de résidus conformal est vide ou illisible.")
        return
    figure = go.Figure()
    max_steps = min(8, residuals.shape[0])
    for step_index in range(max_steps):
        figure.add_trace(
            go.Histogram(
                x=residuals[step_index, :],
                name=f"T+{step_index + 1}H",
                opacity=0.48,
            )
        )
    figure.update_layout(
        barmode="overlay",
        xaxis_title="Erreur absolue (points SIIPS)",
        yaxis_title="Fréquence",
        template="plotly_white",
    )
    st.plotly_chart(
        figure,
        use_container_width=True,
        key="diagnostics_conformal_residuals_chart",
    )


@st.cache_data(show_spinner=False)
def load_residuals(residual_path: Path) -> np.ndarray:
    """Load residuals in horizon-major shape for plotting."""
    try:
        payload: Any = np.load(residual_path)
        if "residuals_per_step" in payload:
            return np.asarray(payload["residuals_per_step"], dtype=float)
        if "residuals" in payload:
            return np.asarray(payload["residuals"], dtype=float).T
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("conformal_residuals_load_failed", exc_info=exc)
    return np.asarray([], dtype=float)


def render_limitations() -> None:
    """Render explicit scientific and operational limitations."""
    st.markdown(
        """
#### Limites

- Données SIIPS synthétiques uniquement à ce stade.
- Périmètre single-service, single-hospital pour la démonstration.
- Federated learning conçu mais non validé opérationnellement.
- Aucune validation clinique; ce n’est pas un dispositif médical.
"""
    )
