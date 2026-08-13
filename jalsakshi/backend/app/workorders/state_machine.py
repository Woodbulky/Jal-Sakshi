"""The work-order lifecycle, and the one rule the whole product rests on.

`CLOSED` is reachable only from `VERIFYING`. Every other guarantee in
JAL-SAKSHI — that an incident is closed by sensor evidence rather than by
someone saying "done" — follows from that single edge being absent everywhere
else in this table.

`TRANSITIONS` is a transcription of the `enforce_work_order_transition` trigger
in Postgres, and `test_state_machine.py` asserts the two agree. The database is
the authority: it rejects an illegal transition even if it arrives from outside
this application. This module exists so the API can refuse one *before* the
round trip, with a message a human can act on.
"""

from __future__ import annotations

from app.schemas.workorder import WorkOrderStatus as S

#: Legal successors of each state. Absence of an edge is a deliberate refusal.
TRANSITIONS: dict[S, frozenset[S]] = {
    S.DETECTED: frozenset({S.TRIAGING, S.CLASSIFIED, S.UNVERIFIABLE}),
    S.TRIAGING: frozenset({S.CLASSIFIED, S.UNVERIFIABLE}),
    S.CLASSIFIED: frozenset({S.ASSESSED, S.TRIAGING, S.UNVERIFIABLE}),
    S.ASSESSED: frozenset({S.ASSIGNED, S.UNVERIFIABLE}),
    # Reassignment is ASSIGNED -> ASSIGNED: a new crew, same commitment.
    S.ASSIGNED: frozenset({S.ACKNOWLEDGED, S.ASSIGNED, S.UNVERIFIABLE}),
    S.ACKNOWLEDGED: frozenset({S.IN_REPAIR, S.ASSIGNED, S.UNVERIFIABLE}),
    S.IN_REPAIR: frozenset({S.RESTORATION_DETECTED, S.VERIFYING, S.UNVERIFIABLE}),
    S.RESTORATION_DETECTED: frozenset({S.VERIFYING, S.UNVERIFIABLE}),
    # The only edge into CLOSED in the entire machine.
    S.VERIFYING: frozenset({S.CLOSED, S.REOPENED, S.UNVERIFIABLE}),
    S.REOPENED: frozenset(
        {S.TRIAGING, S.CLASSIFIED, S.ASSESSED, S.ASSIGNED, S.UNVERIFIABLE}
    ),
    S.UNVERIFIABLE: frozenset(
        {S.TRIAGING, S.CLASSIFIED, S.ASSESSED, S.ASSIGNED, S.VERIFYING, S.REOPENED}
    ),
    # A closed order that fails again is reopened, never silently re-run.
    S.CLOSED: frozenset({S.REOPENED}),
}

#: States from which no further progress is possible without human input.
TERMINAL: frozenset[S] = frozenset({S.CLOSED})


class InvalidTransition(ValueError):
    """Raised instead of writing a state change the lifecycle forbids."""

    def __init__(self, current: S, requested: S, wo_code: str | None = None) -> None:
        self.current = current
        self.requested = requested
        self.wo_code = wo_code
        subject = f" for work order {wo_code}" if wo_code else ""
        allowed = ", ".join(sorted(s.value for s in TRANSITIONS.get(current, frozenset())))
        super().__init__(
            f"invalid work_order transition {current.value} -> {requested.value}"
            f"{subject}; allowed: {allowed or 'none'}"
        )


def can_transition(current: S, requested: S) -> bool:
    """A no-op transition is allowed, matching the trigger's early return."""
    if current is requested:
        return True
    return requested in TRANSITIONS.get(current, frozenset())


def assert_transition(current: S, requested: S, wo_code: str | None = None) -> None:
    if not can_transition(current, requested):
        raise InvalidTransition(current, requested, wo_code)


def allowed_from(current: S) -> frozenset[S]:
    return TRANSITIONS.get(current, frozenset())


def is_terminal(status: S) -> bool:
    return status in TERMINAL


__all__ = [
    "TERMINAL",
    "TRANSITIONS",
    "InvalidTransition",
    "allowed_from",
    "assert_transition",
    "can_transition",
    "is_terminal",
]
