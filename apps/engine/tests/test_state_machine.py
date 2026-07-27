"""Tests de la machine à états du setup sweep."""

import pytest

from app.strategy_v2.state_machine import (
    CONTEXT_VALIDATED,
    IDLE,
    READY_TO_EXECUTE,
    REINTEGRATION_CONFIRMED,
    REJECTED,
    STRUCTURE_SHIFT_CONFIRMED,
    SWEEP_DETECTED,
    WAITING_RETEST,
    ZONE_DETECTED,
    ForbiddenTransition,
    SetupStateMachine,
)

FULL_PATH = [
    CONTEXT_VALIDATED,
    ZONE_DETECTED,
    SWEEP_DETECTED,
    REINTEGRATION_CONFIRMED,
    STRUCTURE_SHIFT_CONFIRMED,
    WAITING_RETEST,
    READY_TO_EXECUTE,
]


def test_full_nominal_progression():
    fsm = SetupStateMachine()
    for state in FULL_PATH:
        fsm.to(state, f"step {state}")
    assert fsm.state == READY_TO_EXECUTE
    assert len(fsm.history) == len(FULL_PATH)
    assert all("at" in h and h["reason"] for h in fsm.history)


def test_skipping_a_stage_is_forbidden():
    fsm = SetupStateMachine()
    fsm.to(CONTEXT_VALIDATED, "ctx")
    with pytest.raises(ForbiddenTransition):
        fsm.to(SWEEP_DETECTED, "saut de ZONE_DETECTED")
    # L'état n'a pas bougé et aucune transition fantôme n'est historisée.
    assert fsm.state == CONTEXT_VALIDATED
    assert len(fsm.history) == 1


def test_rejection_allowed_from_any_active_state():
    fsm = SetupStateMachine()
    fsm.to(CONTEXT_VALIDATED, "ctx")
    fsm.to(ZONE_DETECTED, "zone")
    fsm.to(REJECTED, "spread trop large")
    assert fsm.state == REJECTED
    with pytest.raises(ForbiddenTransition):
        fsm.to(SWEEP_DETECTED, "un setup rejeté ne repart pas")


def test_reset_returns_to_idle_and_is_logged():
    fsm = SetupStateMachine()
    fsm.to(CONTEXT_VALIDATED, "ctx")
    fsm.reset("fin d'évaluation")
    assert fsm.state == IDLE
    assert fsm.history[-1]["to"] == IDLE


def test_direct_ready_without_retest_when_not_required():
    fsm = SetupStateMachine()
    for state in FULL_PATH[:5]:
        fsm.to(state, "...")
    fsm.to(READY_TO_EXECUTE, "retest non requis")
    assert fsm.state == READY_TO_EXECUTE


def test_history_persists_but_state_restarts_idle(tmp_path):
    path = tmp_path / "fsm.json"
    fsm = SetupStateMachine(path)
    fsm.to(CONTEXT_VALIDATED, "ctx")
    fsm.to(REJECTED, "test")

    reloaded = SetupStateMachine(path)
    assert reloaded.state == IDLE  # jamais de reprise d'un setup périmé
    assert len(reloaded.history) == 2
    assert reloaded.history[-1]["reason"] == "test"
