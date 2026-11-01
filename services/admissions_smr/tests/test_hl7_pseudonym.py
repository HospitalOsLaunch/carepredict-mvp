from __future__ import annotations

import re

import pytest

from services.admissions_smr.domain.pseudonym import pseudonym


def test_pseudonym_is_stable_hex_per_tenant_and_kind() -> None:
    # Arrange
    secret = "s" * 32

    # Act
    first = pseudonym(secret, 1, "ipp", "123456")
    again = pseudonym(secret, 1, "ipp", " 123456 ")
    other_group = pseudonym(secret, 2, "ipp", "123456")
    as_nda = pseudonym(secret, 1, "nda", "123456")
    other_secret = pseudonym("x" * 32, 1, "ipp", "123456")

    # Assert
    assert re.fullmatch(r"[0-9a-f]{64}", first)
    assert first == again
    assert len({first, other_group, as_nda, other_secret}) == 4
    assert "123456" not in first


@pytest.mark.parametrize(("kind", "value"), [("nir", "1"), ("ipp", "  ")])
def test_pseudonym_rejects_unknown_kind_or_empty_value(kind: str, value: str) -> None:
    with pytest.raises(ValueError):
        pseudonym("s" * 32, 1, kind, value)  # type: ignore[arg-type]
