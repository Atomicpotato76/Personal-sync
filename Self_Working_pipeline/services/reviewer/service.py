from __future__ import annotations

from pydantic import BaseModel

from contracts.models import ExecutionResult, PlanBundle, ReviewReport
from core.prompting import compose_system_prompt
from services.adapters.base import JsonModelAdapter


class ReviewEnvelope(BaseModel):
    report: ReviewReport


class ReviewerService:
    def __init__(self, adapter: JsonModelAdapter, *, guidance_prompt: str = "") -> None:
        self.adapter = adapter
        self.guidance_prompt = guidance_prompt

    def review(self, *, execution_result: ExecutionResult, plan_bundle: PlanBundle) -> ReviewReport:
        system_prompt = compose_system_prompt(
            (
                "You are Claude Code acting as a reviewer. Evaluate generated files for correctness, "
                "scope control, maintainability, and alignment with the contract."
            ),
            self.guidance_prompt,
            section_name="review, testing discipline, repository expectations, and safety rules",
        )
        user_prompt = (
            "Review the implementation against the plan bundle.\n"
            "Approve only when the workstream is complete, scoped correctly, and still follows any user additions in plan_bundle.change_log.\n"
            "Return JSON only.\n\n"
            f"Plan bundle:\n{plan_bundle.model_dump_json(indent=2)}\n\n"
            f"Execution result:\n{execution_result.model_dump_json(indent=2)}"
        )
        result = self.adapter.generate_structured(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_model=ReviewEnvelope,
        )
        assert isinstance(result, ReviewEnvelope)
        return result.report
