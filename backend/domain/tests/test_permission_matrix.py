"""Planning an edit of the role permission matrix (FEATURES 0.3, ARCHITECTURE 4.10)."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from domain.errors import DomainError
from domain.permissions import MatrixChange, plan_matrix_update, resolve_permissions, role_grants

ROLES = ["a", "b", "c", "d"]
CODES = ["x.one", "x.two", "y.three", "z.four"]

role_sets = st.frozensets(st.sampled_from(ROLES))
defaults_st = st.fixed_dictionaries(dict.fromkeys(CODES, role_sets))
overrides_st = st.dictionaries(
    st.tuples(st.sampled_from(ROLES), st.sampled_from(CODES)), st.booleans()
)
change_st = st.builds(
    MatrixChange, role=st.sampled_from(ROLES), code=st.sampled_from(CODES), allowed=st.booleans()
)


def _dedupe(changes: list[MatrixChange]) -> list[MatrixChange]:
    """Last change per (role, code) wins, as a client sending one final state would."""
    out: dict[tuple[str, str], MatrixChange] = {}
    for change in changes:
        out[(change.role, change.code)] = change
    return list(out.values())


def _apply(
    overrides: dict[tuple[str, str], bool],
    upserts: dict[tuple[str, str], bool],
    deletes: frozenset[tuple[str, str]],
) -> dict[tuple[str, str], bool]:
    after = {k: v for k, v in overrides.items() if k not in deletes}
    after.update(upserts)
    return after


@given(defaults_st, overrides_st, st.lists(change_st, max_size=12))
def test_applying_the_plan_gives_the_requested_grants(
    defaults: dict[str, frozenset[str]],
    overrides: dict[tuple[str, str], bool],
    raw: list[MatrixChange],
) -> None:
    changes = _dedupe(raw)
    plan = plan_matrix_update(defaults, overrides, changes, roles=ROLES)
    after = _apply(overrides, plan.upserts, plan.deletes)
    for change in changes:
        assert role_grants(change.role, change.code, defaults, after) is change.allowed


@given(defaults_st, overrides_st, st.lists(change_st, max_size=12))
def test_untouched_cells_keep_their_grant(
    defaults: dict[str, frozenset[str]],
    overrides: dict[tuple[str, str], bool],
    raw: list[MatrixChange],
) -> None:
    changes = _dedupe(raw)
    touched = {(c.role, c.code) for c in changes}
    plan = plan_matrix_update(defaults, overrides, changes, roles=ROLES)
    after = _apply(overrides, plan.upserts, plan.deletes)
    for role in ROLES:
        for code in CODES:
            if (role, code) not in touched:
                assert role_grants(role, code, defaults, after) == role_grants(
                    role, code, defaults, overrides
                )


@given(defaults_st, overrides_st, st.lists(change_st, max_size=12))
def test_touched_cells_never_store_an_override_equal_to_the_default(
    defaults: dict[str, frozenset[str]],
    overrides: dict[tuple[str, str], bool],
    raw: list[MatrixChange],
) -> None:
    changes = _dedupe(raw)
    plan = plan_matrix_update(defaults, overrides, changes, roles=ROLES)
    after = _apply(overrides, plan.upserts, plan.deletes)
    for change in changes:
        key = (change.role, change.code)
        if key in after:
            assert after[key] is not (change.role in defaults[change.code])


@given(defaults_st, overrides_st, st.lists(change_st, max_size=12))
def test_changed_lists_exactly_the_cells_whose_grant_flips(
    defaults: dict[str, frozenset[str]],
    overrides: dict[tuple[str, str], bool],
    raw: list[MatrixChange],
) -> None:
    changes = _dedupe(raw)
    plan = plan_matrix_update(defaults, overrides, changes, roles=ROLES)
    flipped = {
        (c.role, c.code)
        for c in changes
        if role_grants(c.role, c.code, defaults, overrides) is not c.allowed
    }
    assert {(c.role, c.code) for c in plan.changed} == flipped
    assert all(
        c.allowed is not role_grants(c.role, c.code, defaults, overrides) for c in plan.changed
    )


@given(defaults_st, overrides_st, st.lists(change_st, max_size=12))
def test_plan_is_idempotent(
    defaults: dict[str, frozenset[str]],
    overrides: dict[tuple[str, str], bool],
    raw: list[MatrixChange],
) -> None:
    changes = _dedupe(raw)
    first = plan_matrix_update(defaults, overrides, changes, roles=ROLES)
    after = _apply(overrides, first.upserts, first.deletes)
    second = plan_matrix_update(defaults, after, changes, roles=ROLES)
    assert second.changed == ()
    assert second.upserts == {}
    assert second.deletes == frozenset()


@given(
    defaults_st, overrides_st, st.lists(change_st, max_size=12), st.lists(st.sampled_from(ROLES))
)
def test_effective_permissions_follow_the_plan(
    defaults: dict[str, frozenset[str]],
    overrides: dict[tuple[str, str], bool],
    raw: list[MatrixChange],
    holder: list[str],
) -> None:
    changes = _dedupe(raw)
    plan = plan_matrix_update(defaults, overrides, changes, roles=ROLES)
    after = _apply(overrides, plan.upserts, plan.deletes)
    granted = resolve_permissions(holder, defaults, after)
    for code in CODES:
        expected = any(role_grants(r, code, defaults, after) for r in holder)
        assert (code in granted) is expected


def test_unknown_code_is_refused() -> None:
    with pytest.raises(DomainError) as exc:
        plan_matrix_update(
            {"x.one": frozenset({"a"})}, {}, [MatrixChange("a", "x.nope", True)], roles=ROLES
        )
    assert exc.value.code == "PERMISSION_UNKNOWN"
    assert exc.value.details == {"permission": "x.nope"}


def test_unknown_role_is_refused() -> None:
    with pytest.raises(DomainError) as exc:
        plan_matrix_update(
            {"x.one": frozenset({"a"})}, {}, [MatrixChange("zz", "x.one", True)], roles=ROLES
        )
    assert exc.value.code == "ROLE_UNKNOWN"
    assert exc.value.details == {"role": "zz"}


def test_contradicting_changes_are_refused() -> None:
    with pytest.raises(DomainError) as exc:
        plan_matrix_update(
            {"x.one": frozenset()},
            {},
            [MatrixChange("a", "x.one", True), MatrixChange("a", "x.one", False)],
            roles=ROLES,
        )
    assert exc.value.code == "MATRIX_CHANGE_CONFLICT"


def test_repeated_identical_change_is_fine() -> None:
    plan = plan_matrix_update(
        {"x.one": frozenset()},
        {},
        [MatrixChange("a", "x.one", True), MatrixChange("a", "x.one", True)],
        roles=ROLES,
    )
    assert plan.upserts == {("a", "x.one"): True}
    assert plan.changed == (MatrixChange("a", "x.one", True),)


def test_protected_grant_cannot_be_revoked() -> None:
    with pytest.raises(DomainError) as exc:
        plan_matrix_update(
            {"core.manage_roles": frozenset({"admin"})},
            {},
            [MatrixChange("admin", "core.manage_roles", False)],
            roles=["admin"],
            protected={("admin", "core.manage_roles")},
        )
    assert exc.value.code == "PERMISSION_PROTECTED"
    assert exc.value.details == {"role": "admin", "permission": "core.manage_roles"}


def test_protected_grant_may_be_confirmed() -> None:
    plan = plan_matrix_update(
        {"core.manage_roles": frozenset({"admin"})},
        {("admin", "core.manage_roles"): False},
        [MatrixChange("admin", "core.manage_roles", True)],
        roles=["admin"],
        protected={("admin", "core.manage_roles")},
    )
    assert plan.deletes == frozenset({("admin", "core.manage_roles")})
    assert plan.changed == (MatrixChange("admin", "core.manage_roles", True),)


def test_back_to_default_removes_the_override() -> None:
    plan = plan_matrix_update(
        {"x.one": frozenset({"a"})},
        {("a", "x.one"): False},
        [MatrixChange("a", "x.one", True)],
        roles=ROLES,
    )
    assert plan.upserts == {}
    assert plan.deletes == frozenset({("a", "x.one")})


def test_changed_is_sorted_by_role_then_code() -> None:
    plan = plan_matrix_update(
        {"x.one": frozenset(), "x.two": frozenset()},
        {},
        [
            MatrixChange("b", "x.two", True),
            MatrixChange("a", "x.two", True),
            MatrixChange("a", "x.one", True),
        ],
        roles=ROLES,
    )
    assert [(c.role, c.code) for c in plan.changed] == [
        ("a", "x.one"),
        ("a", "x.two"),
        ("b", "x.two"),
    ]
