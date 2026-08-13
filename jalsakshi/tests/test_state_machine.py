"""The lifecycle rules, tested as rules rather than as a happy path.

The single most important assertion in this file is
`test_closed_is_reachable_only_from_verifying`. Every claim JAL-SAKSHI makes
about accountability reduces to that edge not existing anywhere else.
"""

from __future__ import annotations

import pytest

from app.schemas.workorder import WorkOrderStatus as S
from app.workorders.state_machine import (
    TRANSITIONS,
    InvalidTransition,
    allowed_from,
    assert_transition,
    can_transition,
    is_terminal,
)


def test_closed_is_reachable_only_from_verifying() -> None:
    """The load-bearing edge. A field message can never reach CLOSED alone."""
    sources = [state for state, targets in TRANSITIONS.items() if S.CLOSED in targets]

    assert sources == [S.VERIFYING]


def test_every_status_has_a_rule() -> None:
    """A status missing from the table would be silently unreachable."""
    assert set(TRANSITIONS) == set(S)


def test_a_field_report_cannot_skip_verification() -> None:
    for origin in (S.IN_REPAIR, S.RESTORATION_DETECTED, S.ACKNOWLEDGED):
        assert not can_transition(origin, S.CLOSED)


def test_unverifiable_is_reachable_from_every_live_state() -> None:
    """Instruments can fail at any point, and saying so must always be legal."""
    for state in S:
        if state in (S.CLOSED, S.UNVERIFIABLE):
            continue
        assert S.UNVERIFIABLE in allowed_from(state), state


def test_unverifiable_is_not_an_end_state() -> None:
    """It means 'a human must look', not 'give up'."""
    assert allowed_from(S.UNVERIFIABLE)
    assert not is_terminal(S.UNVERIFIABLE)


def test_a_closed_order_reopens_rather_than_restarting() -> None:
    assert allowed_from(S.CLOSED) == frozenset({S.REOPENED})


def test_reassignment_is_legal_but_regression_is_not() -> None:
    assert can_transition(S.ASSIGNED, S.ASSIGNED)
    assert not can_transition(S.ASSIGNED, S.CLASSIFIED)


def test_a_no_op_transition_is_allowed() -> None:
    """Matches the trigger's early return on `new.status = old.status`."""
    for state in S:
        assert can_transition(state, state)


def test_the_error_names_the_states_and_the_order() -> None:
    with pytest.raises(InvalidTransition) as caught:
        assert_transition(S.IN_REPAIR, S.CLOSED, "WO-007")

    message = str(caught.value)
    assert "IN_REPAIR" in message
    assert "CLOSED" in message
    assert "WO-007" in message
    # It also says what *would* have been legal, so a human can act on it.
    assert "VERIFYING" in message


# -- parity with the database ----------------------------------------------
#
# Transcribed from `enforce_work_order_transition` in Postgres. If the two ever
# disagree, the API would accept a transition the database then rejects -- or
# worse, refuse one the database allows and quietly stall an incident.
_TRIGGER_TABLE: dict[S, set[S]] = {
    S.DETECTED: {S.TRIAGING, S.CLASSIFIED, S.UNVERIFIABLE},
    S.TRIAGING: {S.CLASSIFIED, S.UNVERIFIABLE},
    S.CLASSIFIED: {S.ASSESSED, S.TRIAGING, S.UNVERIFIABLE},
    S.ASSESSED: {S.ASSIGNED, S.UNVERIFIABLE},
    S.ASSIGNED: {S.ACKNOWLEDGED, S.ASSIGNED, S.UNVERIFIABLE},
    S.ACKNOWLEDGED: {S.IN_REPAIR, S.ASSIGNED, S.UNVERIFIABLE},
    S.IN_REPAIR: {S.RESTORATION_DETECTED, S.VERIFYING, S.UNVERIFIABLE},
    S.RESTORATION_DETECTED: {S.VERIFYING, S.UNVERIFIABLE},
    S.VERIFYING: {S.CLOSED, S.REOPENED, S.UNVERIFIABLE},
    S.REOPENED: {S.TRIAGING, S.CLASSIFIED, S.ASSESSED, S.ASSIGNED, S.UNVERIFIABLE},
    S.UNVERIFIABLE: {
        S.TRIAGING,
        S.CLASSIFIED,
        S.ASSESSED,
        S.ASSIGNED,
        S.VERIFYING,
        S.REOPENED,
    },
    S.CLOSED: {S.REOPENED},
}


def test_python_and_postgres_agree_on_every_edge() -> None:
    assert {state: set(targets) for state, targets in TRANSITIONS.items()} == (
        _TRIGGER_TABLE
    )
