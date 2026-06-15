# -*- coding: utf-8 -*-
"""
Configuration pytest partagée.

Marque automatiquement comme `slow` les tests qui entraînent un modèle fédéré
(appels à run_federated), pour que la CI de PR puisse les exclure via
`-m "not slow"` tout en les exécutant en nightly.

Le marquage est NON INTRUSIF : il se fait par motif de nom, sans modifier les
fichiers de test. On peut aussi marquer explicitement un test avec
`@pytest.mark.slow` si besoin d'un contrôle plus fin.
"""

import pytest

# Motifs de noms identifiant les tests coûteux (entraînement fédéré complet).
# Choisis pour NE PAS capturer les tests légers homonymes :
#   - 'ema_update_is_no_grad' est léger (init seule) -> on évite 'ema_update' nu
#   - on cible 'single_ema' (qui lance run_federated), pas 'ema' tout court
_SLOW_NAME_PATTERNS = (
    "fedprox",        # test_fedprox_reduces_drift_vs_fedavg
    "single_ema",     # test_single_ema_update
    "collapse",       # test_no_collapse_short_run
    "reproducib",     # test_reproducibility
)


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "slow: test coûteux (entraînement fédéré), exclu des CI de PR, "
        "exécuté en nightly.",
    )


def pytest_collection_modifyitems(config, items):
    for item in items:
        name = item.name.lower()
        if any(pat in name for pat in _SLOW_NAME_PATTERNS):
            item.add_marker(pytest.mark.slow)
