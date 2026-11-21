import numpy as np
import pytest

from hospitalos.world_model.projection import reconstruct


def test_extreme_equal_stocks_share_the_bed_capacity() -> None:
    predictions = np.full((2, 1, 5), 1e250)
    hidden = np.full((1, 5), np.nan)
    projected = reconstruct(
        predictions, 0, hidden, np.isfinite(hidden), np.array([8.0]), now=12, published=16
    )
    np.testing.assert_array_equal(projected[..., 1:], 2.0)
    np.testing.assert_array_equal(projected[..., 0], 1e250)


@pytest.mark.parametrize("value", [-1, True, 1.5])
def test_an_invalid_publication_clock_cannot_open_the_readout(value: int) -> None:
    x = np.ones((2, 1, 5))
    with pytest.raises(ValueError, match="clock"):
        reconstruct(x, 0, x[0], np.isfinite(x[0]), np.array([10.0]), now=16, published=value)


def test_known_beds_are_preserved_when_the_imputed_census_exceeds_capacity() -> None:
    x = np.full((2, 1, 5), 2.0)
    report = np.array([[np.nan, 9.0, np.nan, np.nan, np.nan]])
    out = reconstruct(x, 0, report, np.isfinite(report), np.array([10.0]), now=16, published=16)
    np.testing.assert_allclose(out[0, 0], [2.0, 9.0, 1 / 3, 1 / 3, 1 / 3])
    np.testing.assert_allclose(out[1, 0], [2.0, 7.75, 0.75, 0.75, 0.75])
