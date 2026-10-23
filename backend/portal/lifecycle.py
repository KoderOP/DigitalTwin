"""Patient-interface lifecycle state machine.

    NOT_ENROLLED -> INVITED -> CONSENT_PENDING -> ACTIVE <-> PAUSED
    any non-terminal state -> REVOKED;  REVOKED -> INVITED (re-launch with a fresh invite)

Enrolment and configuration happen while NOT_ENROLLED (the twin exists and a configuration is
saved). The interface only becomes visible to the patient after INVITED -> CONSENT_PENDING (OTP
verified) -> ACTIVE (consent accepted).
"""
from __future__ import annotations

from enum import Enum


class State(str, Enum):
    NOT_ENROLLED = "NOT_ENROLLED"
    INVITED = "INVITED"
    CONSENT_PENDING = "CONSENT_PENDING"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    REVOKED = "REVOKED"


TRANSITIONS: dict[State, set[State]] = {
    State.NOT_ENROLLED: {State.INVITED},
    State.INVITED: {State.INVITED, State.CONSENT_PENDING, State.REVOKED},  # INVITED->INVITED = regenerate
    State.CONSENT_PENDING: {State.ACTIVE, State.INVITED, State.REVOKED},
    State.ACTIVE: {State.PAUSED, State.REVOKED},
    State.PAUSED: {State.ACTIVE, State.REVOKED},
    State.REVOKED: {State.INVITED},
}

# states in which the patient app may receive twin data
DATA_STATES = {State.ACTIVE}


class InvalidTransition(Exception):
    def __init__(self, frm: State, to: State) -> None:
        super().__init__(f"transition {frm.value} -> {to.value} is not allowed")
        self.frm, self.to = frm, to


def check_transition(frm: State | str, to: State | str) -> tuple[State, State]:
    """Validate a transition; raise :class:`InvalidTransition` if it is not in the table."""
    f, t = State(frm), State(to)
    if t not in TRANSITIONS[f]:
        raise InvalidTransition(f, t)
    return f, t
