"""Bed-level availability: usable beds, gender groups (ROR), isolation, closures."""

from __future__ import annotations

from itertools import count

from services.admissions_smr.domain.beds import (
    Availability,
    BedState,
    UnitDeclared,
    accepted_sexes,
    add,
    unit_availability,
)

_ids = count(1)


def bed(
    room: str,
    status: str = "libre",
    sex: str = "X",
    occupant: str | None = None,
    isolation: bool = False,
    pool_id: int = 1,
    active: bool = True,
) -> BedState:
    n = next(_ids)
    return BedState(
        id=n,
        site_id=1,
        pool_id=pool_id,
        room=room,
        label=f"{room}-{n}",
        sex_constraint=sex,
        isolation=isolation,
        status=status,
        active=active,
        occupant_sex=occupant,
    )


def unit(
    beds: list[BedState], installed: int | None = None, open_: int | None = None
) -> Availability:
    n = installed if installed is not None else len(beds)
    return unit_availability(UnitDeclared(1, n, open_ if open_ is not None else n), beds)


def test_single_free_room_takes_either_sex() -> None:
    a = unit([bed("101")])

    assert (a.usable, a.either, a.female, a.male) == (1, 1, 0, 0)


def test_double_room_with_a_man_only_takes_a_man() -> None:
    a = unit([bed("102", "occupe", occupant="M"), bed("102")])

    assert (a.usable, a.either, a.female, a.male) == (1, 0, 0, 1)


def test_double_room_with_a_woman_only_takes_a_woman() -> None:
    a = unit([bed("102", "occupe", occupant="F"), bed("102")])

    assert (a.female, a.male, a.either) == (1, 0, 0)


def test_mixed_room_free_bed_is_a_conflict_not_usable() -> None:
    a = unit([bed("103", "occupe", occupant="F"), bed("103", "occupe", occupant="M"), bed("103")])

    assert a.usable == 0
    assert a.sex_conflict == 1


def test_constraint_contradicting_occupant_is_a_conflict() -> None:
    a = unit([bed("104", "occupe", sex="F", occupant="M"), bed("104", sex="F")])

    assert (a.usable, a.sex_conflict) == (0, 1)


def test_sex_constraint_on_an_empty_room() -> None:
    a = unit([bed("105", sex="F"), bed("105", sex="F"), bed("106", sex="M")])

    assert (a.female, a.male, a.either) == (2, 1, 0)


def test_unknown_occupant_sex_does_not_restrict_the_room() -> None:
    a = unit([bed("107", "occupe", occupant="U"), bed("107")])

    assert a.either == 1


def test_cleaning_blocked_reserved_occupied_are_not_usable() -> None:
    a = unit(
        [
            bed("201", "a_nettoyer"),
            bed("202", "bloque"),
            bed("203", "reserve"),
            bed("204", "occupe", occupant="F"),
            bed("205"),
        ]
    )

    assert (a.usable, a.cleaning, a.blocked, a.reserved, a.occupied) == (1, 1, 1, 1, 1)
    assert a.female + a.male + a.either == a.usable


def test_inactive_beds_are_not_installed() -> None:
    a = unit([bed("301"), bed("302", active=False)], installed=1)

    assert (a.installed, a.usable) == (1, 1)


def test_isolation_counts_usable_isolation_beds_only() -> None:
    a = unit([bed("401", isolation=True), bed("402", "a_nettoyer", isolation=True), bed("403")])

    assert a.isolation == 1


def test_declared_closures_beyond_blocked_beds_reduce_usable_from_either_first() -> None:
    beds = [bed("501"), bed("502"), bed("503", sex="F"), bed("504", "bloque")]

    a = unit(beds, installed=4, open_=1)  # 3 closed declared, 1 blocked bed

    assert a.closed == 3
    assert (a.usable, a.either, a.female) == (1, 0, 1)


def test_blocked_beds_beyond_declared_closures_count_as_closed() -> None:
    a = unit([bed("601", "bloque"), bed("602", "bloque"), bed("603")], installed=3, open_=2)

    assert (a.closed, a.usable) == (2, 1)


def test_roommates_from_another_unit_are_seen_when_passed() -> None:
    other = bed("701", "occupe", occupant="M", pool_id=2)
    mine = bed("701")

    assert accepted_sexes(mine, [other]) == {"M"}


def test_site_total_sums_units_and_recomputes_tension() -> None:
    a = unit([bed("801"), bed("802", "occupe", occupant="F")])
    b = unit([bed("901", "occupe", occupant="M")])

    total = add([a, b])

    assert (total.installed, total.usable, total.occupied) == (3, 1, 2)
    assert total.tension.level == "normal"  # 1 / 3 >= 20 %
    assert b.tension.level == "critique"


def test_extra_and_crisis_beds_come_from_the_unit_declaration() -> None:
    a = unit_availability(UnitDeclared(1, 1, 1, extra_beds=2, crisis_reserved_beds=1), [bed("1")])

    assert (a.extra_beds, a.crisis_reserved_beds, a.usable) == (2, 1, 1)
