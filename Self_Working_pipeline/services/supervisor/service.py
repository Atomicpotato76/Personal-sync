from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from contracts.models import (
    ApprovalStage,
    CheckpointSummary,
    DirectionSnapshot,
    PlanBundle,
    StageNarrative,
    SupervisorDecision,
    SupervisorTrace,
    TestReport,
)
from core.prompting import compose_system_prompt
from services.adapters.base import JsonModelAdapter


class SupervisorEnvelope(BaseModel):
    decision: SupervisorDecision


@dataclass
class SupervisorAgent:
    agent_id: str
    stage: ApprovalStage
    adapter: JsonModelAdapter
    guidance_prompt: str = ""

    @property
    def model_name(self) -> str:
        return getattr(self.adapter, "model", self.adapter.__class__.__name__)

    def evaluate(self, *, run_id: str, payload: dict[str, Any], sequence: int) -> tuple[SupervisorDecision, SupervisorTrace]:
        system_prompt = compose_system_prompt(
            self._system_prompt(),
            self.guidance_prompt,
            section_name="approval gates, direction review, and delivery workflow",
        )
        user_prompt = (
            "Review the current approval gate for the Hermes pipeline.\n"
            "Requirements:\n"
            "- evaluate only the provided payload\n"
            "- do not ask for more information unless continuing would be unsafe\n"
            "- approve when the gate can safely continue based on direction and status\n"
            "- reject when human confirmation is needed or the direction is not coherent\n"
            "- keep rationale short and actionable\n"
            "- return JSON only\n\n"
            f"Gate payload:\n{json.dumps(payload, indent=2, ensure_ascii=False)}"
        )
        input_digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        started_at = time.perf_counter()
        result = self.adapter.generate_structured(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_model=SupervisorEnvelope,
        )
        latency_ms = int((time.perf_counter() - started_at) * 1000)
        assert isinstance(result, SupervisorEnvelope)
        if result.decision.stage != self.stage:
            raise RuntimeError(
                f"{self.agent_id} returned {result.decision.stage.value} but expected {self.stage.value}."
            )
        trace = SupervisorTrace(
            run_id=run_id,
            sequence=sequence,
            stage=self.stage,
            agent_id=self.agent_id,
            decision_source="gate_agent",
            approved=result.decision.approved,
            rationale=result.decision.rationale,
            risk_flags=result.decision.risk_flags,
            requires_human=result.decision.requires_human,
            input_digest=input_digest,
            latency_ms=latency_ms,
            model_name=self.model_name,
        )
        return result.decision, trace

    def _system_prompt(self) -> str:
        if self.stage == ApprovalStage.plan:
            return (
                "You are the Plan Gate Agent for a multi-agent software delivery pipeline. "
                "Review plan summary, change log, and latest direction. Approve only when the implementation "
                "direction is coherent enough to begin coding."
            )
        if self.stage == ApprovalStage.checkpoint:
            return (
                "You are the Checkpoint Gate Agent for a multi-agent software delivery pipeline. "
                "Review checkpoint summary, stage narrative, and recent events. Approve only when the current "
                "implementation checkpoint is coherent enough to continue automatically."
            )
        return (
            "You are the Merge Gate Agent for a multi-agent software delivery pipeline. "
            "Review the passing test summary, artifact highlights, and latest direction. Approve only when the run "
            "is ready to package without human intervention."
        )


class SupervisorService:
    def __init__(
        self,
        *,
        plan_agent: SupervisorAgent,
        checkpoint_agent: SupervisorAgent,
        merge_agent: SupervisorAgent,
    ) -> None:
        self._agents = {
            ApprovalStage.plan: plan_agent,
            ApprovalStage.checkpoint: checkpoint_agent,
            ApprovalStage.merge: merge_agent,
        }

    def agent_for_stage(self, stage: ApprovalStage) -> SupervisorAgent:
        return self._agents[stage]

    def evaluate(
        self,
        *,
        run_id: str,
        sequence: int,
        stage: ApprovalStage,
        summary: CheckpointSummary,
        direction: DirectionSnapshot | None,
        plan_bundle: PlanBundle | None = None,
        stage_narrative: StageNarrative | None = None,
        recent_events: list[dict[str, Any]] | None = None,
        test_report: TestReport | None = None,
        artifact_highlights: list[str] | None = None,
    ) -> tuple[SupervisorDecision, SupervisorTrace]:
        payload = self._build_payload(
            stage=stage,
            summary=summary,
            direction=direction,
            plan_bundle=plan_bundle,
            stage_narrative=stage_narrative,
            recent_events=recent_events or [],
            test_report=test_report,
            artifact_highlights=artifact_highlights or [],
        )
        return self.agent_for_stage(stage).evaluate(run_id=run_id, payload=payload, sequence=sequence)

    @staticmethod
    def _build_payload(
        *,
        stage: ApprovalStage,
        summary: CheckpointSummary,
        direction: DirectionSnapshot | None,
        plan_bundle: PlanBundle | None,
        stage_narrative: StageNarrative | None,
        recent_events: list[dict[str, Any]],
        test_report: TestReport | None,
        artifact_highlights: list[str],
    ) -> dict[str, Any]:
        base_payload: dict[str, Any] = {
            "stage": stage.value,
            "summary": summary.model_dump(mode="json"),
            "direction": direction.model_dump(mode="json") if direction else None,
        }
        if stage == ApprovalStage.plan:
            plan_summary = None
            change_log = []
            if plan_bundle is not None:
                plan_summary = {
                    "title": plan_bundle.project_brief.title,
                    "objective": plan_bundle.project_brief.objective,
                    "deliverables": plan_bundle.project_brief.deliverables,
                    "workstreams": [
                        {
                            "id": item.id,
                            "name": item.name,
                            "layer": item.layer,
                            "objective": item.objective,
                        }
                        for item in plan_bundle.workstreams
                    ],
                }
                change_log = [item.model_dump(mode="json") for item in plan_bundle.change_log[-3:]]
            base_payload["plan"] = plan_summary
            base_payload["change_log"] = change_log
            return base_payload
        if stage == ApprovalStage.checkpoint:
            base_payload["stage_narrative"] = stage_narrative.model_dump(mode="json") if stage_narrative else None
            base_payload["recent_events"] = recent_events[:5]
            return base_payload
        test_summary = None
        if test_report is not None:
            test_summary = {
                "passed": test_report.passed,
                "command": test_report.command,
                "results": [item.model_dump(mode="json") for item in test_report.results],
            }
        base_payload["test_report"] = test_summary
        base_payload["artifact_highlights"] = artifact_highlights[:5]
        return base_payload
