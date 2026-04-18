from __future__ import annotations

from contracts.models import RunStage


class InvalidStageTransition(ValueError):
    """Raised when the orchestrator attempts an invalid stage change."""


class HermesStateMachine:
    allowed_transitions: dict[RunStage, set[RunStage]] = {
        RunStage.intake: {RunStage.planning},
        RunStage.planning: {RunStage.plan_approved},
        RunStage.plan_approved: {RunStage.executing},
        RunStage.executing: {RunStage.reviewing, RunStage.testing},
        RunStage.reviewing: {RunStage.executing, RunStage.testing},
        RunStage.testing: {RunStage.executing, RunStage.merge_approved},
        RunStage.merge_approved: {RunStage.packaging},
        RunStage.packaging: {RunStage.completed},
        RunStage.completed: set(),
    }

    def ensure_transition(self, current: RunStage, target: RunStage) -> None:
        if current == target:
            return
        if target not in self.allowed_transitions[current]:
            raise InvalidStageTransition(f"Cannot move from {current} to {target}.")
