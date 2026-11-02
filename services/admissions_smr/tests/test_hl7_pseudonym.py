from __future__ import annotations

import re

import pytest

from services.admissions_smr.domain.pseudonym import (
    Purpose,
    group_key,
    hkdf_sha256,
    keyed_digest,
    pseudonym,
)


def test_pseudonym_is_stable_hex_per_tenant_kind_and_domain() -> None:
    # Arrange
    secret = "s" * 32

    # Act
    first = pseudonym(secret, 1, "ipp", "GAM", "123456")
    again = pseudonym(secret, 1, "ipp", " GAM ", " 123456 ")
    other_group = pseudonym(secret, 2, "ipp", "GAM", "123456")
    as_nda = pseudonym(secret, 1, "nda", "GAM", "123456")
    other_secret = pseudonym("x" * 32, 1, "ipp", "GAM", "123456")
    other_domain = pseudonym(secret, 1, "ipp", "CH-B", "123456")  # REVIEW S-H2

    # Assert
    assert re.fullmatch(r"[0-9a-f]{64}", first)
    assert first == again
    assert len({first, other_group, as_nda, other_secret, other_domain}) == 5
    assert "123456" not in first


@pytest.mark.parametrize(
    ("kind", "domain", "value"), [("nir", "GAM", "1"), ("ipp", "GAM", "  "), ("ipp", " ", "1")]
)
def test_pseudonym_rejects_unknown_kind_or_empty_value_or_domain(
    kind: str, domain: str, value: str
) -> None:
    with pytest.raises(ValueError):
        pseudonym("s" * 32, 1, kind, domain, value)  # type: ignore[arg-type]


def test_hkdf_matches_rfc5869_test_case_1() -> None:
    okm = hkdf_sha256(
        bytes.fromhex("0b" * 22), bytes.fromhex("000102030405060708090a0b0c"),
        bytes.fromhex("f0f1f2f3f4f5f6f7f8f9"), 42,
    )  # fmt: skip
    assert okm.hex() == (
        "3cb25f25faacd57a90434f64d0362f2a2d2d0a90cf1a5a4c5db02d56ecc4c5bf34007208d5b887185865"
    )


def test_keys_are_per_group_and_per_purpose_and_digests_are_keyed() -> None:
    # REVIEW S-L3 and S-H3
    secret = "s" * 32
    purposes: tuple[Purpose, ...] = ("pseudonym", "digest")
    keys = {group_key(secret, g, p) for g in (1, 2) for p in purposes}
    assert len(keys) == 4
    digest = keyed_digest(secret, 1, b"MSH|...|IPP4242")
    assert re.fullmatch(r"[0-9a-f]{64}", digest)
    assert digest != keyed_digest(secret, 2, b"MSH|...|IPP4242")
    assert digest != keyed_digest("x" * 32, 1, b"MSH|...|IPP4242")
