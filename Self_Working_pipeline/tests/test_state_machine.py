import pytest

from contracts.models import RunStage
from core.state_machine import HermesStateMachine, InvalidStageTransition


def test_invalid_transition_is_blocked() -> None:
    machine = HermesStateMachine()
    with pytest.raises(InvalidStageTransition):
        machine.ensure_transition(RunStage.plan_approved, RunStage.testing)
