"""Diagnostics and expert-mode panel for Hospitalos."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np
import plotly.graph_objects as go
import streamlit as st

LOGGER = logging.getLogger(__name__)


def render(client: object | None = None) -> None:
    """Render expert diagnostics and reproducibility guidance."""
    _ = client
    st.markdown("### Diagnostics modèle")
    render_training_curves()
    render_model_card()
    render_conformal_coverage(Path("artifacts/conformal_residuals.npz"))
    render_limitations()
    render_reproducibility()


def render_training_curves() -> None:
    """Display training curves or a graceful empty state."""
    curve_path = Path("artifacts/training_curves.png")
    st.markdown("#### Courbes d’entraînement")
    if curve_path.exists():
        st.image(str(curve_path), caption="Courbes d’entraînement RSSM")
    else:
        st.markdown(
            '<div class="hos-empty-state">Courbes d’entraînement non disponibles '
            "dans ce checkout.<br><code>python scripts/train_rssm_synthetic.py --plot</code></div>",
            unsafe_allow_html=True,
        )


def render_model_card() -> None:
    """Render the operational model card with checkpoint-derived metadata."""
    metadata = load_checkpoint_metadata(Path("artifacts/rssm_checkpoint.pt"))
    steps = metadata.get("step", "inconnu")
    st.markdown(
        f"""
#### Model card

**Architecture** : RSSM DreamerV3-style (état déterministe h_t via GRU
+ état stochastique z_t gaussien diagonal)

**Calibration** : split-conformal au niveau α=0.10 (IC 90%)

**Entraînement actuel** : {steps} steps sur SIIPS synthétique calibré

**Référence** : Hafner et al. 2023, "Mastering Diverse Domains
through World Models" (DreamerV3)
"""
    )


def load_checkpoint_metadata(checkpoint_path: Path) -> dict[str, Any]:
    """Load checkpoint metadata without assuming artifact availability."""
    if not checkpoint_path.exists():
        return {}
    try:
        import torch

        payload = torch.load(checkpoint_path, map_location="cpu", weights_only=False)
        if isinstance(payload, dict):
            return payload
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("rssm_checkpoint_metadata_load_failed", exc_info=exc)
    return {}


def render_conformal_coverage(residual_path: Path) -> None:
    """Display residual histograms per horizon step when residuals are available."""
    st.markdown("#### Couverture conformelle")
    if not residual_path.exists():
        st.info("Résidus conformels non disponibles.")
        return
    residuals = load_residuals(residual_path)
    if residuals.size == 0:
        st.info("Le fichier de résidus conformels est vide ou illisible.")
        return
    figure = go.Figure()
    max_steps = min(8, residuals.shape[0])
    for step_index in range(max_steps):
        figure.add_trace(
            go.Histogram(
                x=residuals[step_index, :],
                name=f"T+{step_index + 1}h",
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

- Modèle entraîné uniquement sur données synthétiques
- Périmètre actuel : un service, un établissement
- Federated learning conçu mais non validé empiriquement
- Sans validation clinique : non utilisable comme dispositif médical
"""
    )


def render_reproducibility() -> None:
    """Render reproducibility commands for the local demo."""
    st.markdown(
        """
#### Reproductibilité

```bash
python scripts/train_rssm_synthetic.py --plot
uvicorn services.api.main:app --port 8000
bash docs/demo/run_demo.sh
```
"""
    )
