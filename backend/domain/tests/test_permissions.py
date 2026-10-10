from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from domain.errors import DomainError
from domain.permissions import check_role_set, resolve_permissions, role_grants

ROLES = ["a", "b", "c", "d"]
CODES = ["x.one", "x.two", "y.three", "z.four"]

role_sets = st.frozensets(st.sampled_from(ROLES))
defaults_st = st.fixed_dictionaries(dict.fromkeys(CODES, role_sets))
overrides_st = st.dictionaries(
    st.tuples(st.sampled_from(ROLES), st.sampled_from([*CODES, "unknown.code"])), st.booleans()
)


@given(st.lists(st.sampled_from(ROLES)), defaults_st)
def test_without_overrides_defaults_apply(
    roles: list[str], defaults: dict[str, frozenset[str]]
) -> None:
    result = resolve_permissions(roles, defaults, {})
    assert result == {code for code, granted in defaults.items() if granted & set(roles)}


@given(st.lists(st.sampled_from(ROLES)), defaults_st, overrides_st)
def test_result_is_union_of_per_role_grants(
    roles: list[str], defaults: dict[str, frozenset[str]], overrides: dict[tuple[str, str], bool]
) -> None:
    result = resolve_permissions(roles, defaults, overrides)
    for code in defaults:
        expected = any(role_grants(r, code, defaults, overrides) for r in roles)
        assert (code in result) == expected


@given(st.lists(st.sampled_from(ROLES)), defaults_st, overrides_st)
def test_only_registered_codes_can_be_granted(
    roles: list[str], defaults: dict[str, frozenset[str]], overrides: dict[tuple[str, str], bool]
) -> None:
    assert resolve_permissions(roles, defaults, overrides) <= set(defaults)


@given(
    st.lists(st.sampled_from(ROLES)), st.lists(st.sampled_from(ROLES)), defaults_st, overrides_st
)
def test_more_roles_never_remove_permissions(
    a: list[str],
    b: list[str],
    defaults: dict[str, frozenset[str]],
    overrides: dict[tuple[str, str], bool],
) -> None:
    assert resolve_permissions(a, defaults, overrides) <= resolve_permissions(
        a + b, defaults, overrides
    )


@given(defaults_st, overrides_st)
def test_no_roles_no_permissions(
    defaults: dict[str, frozenset[str]], overrides: dict[tuple[str, str], bool]
) -> None:
    assert resolve_permissions([], defaults, overrides) == frozenset()


def test_override_beats_default_for_that_role_only() -> None:
    defaults = {"x.one": frozenset({"a", "b"})}
    overrides = {("a", "x.one"): False}
    assert resolve_permissions(["a"], defaults, overrides) == frozenset()
    assert resolve_permissions(["b"], defaults, overrides) == {"x.one"}
    # A revoke on one role does not cancel a grant from another role the user holds.
    assert resolve_permissions(["a", "b"], defaults, overrides) == {"x.one"}
    assert resolve_permissions(["c"], defaults, {("c", "x.one"): True}) == {"x.one"}


# --- Device roles stand alone (ADR 0019) -------------------------------------------------

PEOPLE = ["receptionist", "doctor", "nurse", "cashier", "manager", "admin"]


@given(st.frozensets(st.sampled_from(PEOPLE), min_size=1))
def test_person_roles_combine_freely(chosen: frozenset[str]) -> None:
    assert check_role_set(chosen, device_roles={"display"}) == sorted(chosen)


def test_the_display_role_alone_is_accepted() -> None:
    assert check_role_set(["display", "display"], device_roles={"display"}) == ["display"]


@given(st.frozensets(st.sampled_from(PEOPLE), min_size=1))
def test_the_display_role_never_combines_with_a_person_role(people: frozenset[str]) -> None:
    with pytest.raises(DomainError) as err:
        check_role_set({"display", *people}, device_roles={"display"})
    assert err.value.code == "DEVICE_ROLE_ALONE"
    assert err.value.details["role"] == "display"


def test_an_empty_role_set_is_refused() -> None:
    with pytest.raises(DomainError) as err:
        check_role_set([], device_roles={"display"})
    assert err.value.code == "ROLE_REQUIRED"
