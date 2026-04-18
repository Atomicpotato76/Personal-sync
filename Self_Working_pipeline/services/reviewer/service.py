from __future__ import annotations

from pydantic import BaseModel

from contracts.models import ExecutionResult, PlanBundle, ReviewReport
from core.prompting import compose_system_prompt
from services.adapters.base import JsonModelAdapter


class ReviewEnvelope(BaseModel):
    report: ReviewReport


class ReviewerService:
    def __init__(self, adapter: JsonModelAdapter, *, guidance_prompt: str = "", mode: str = "code") -> None:
        self.adapter = adapter
        self.guidance_prompt = guidance_prompt
        self.mode = mode

    def review(self, *, execution_result: ExecutionResult, plan_bundle: PlanBundle) -> ReviewReport:
        if self.mode == "research":
            system_prompt = compose_system_prompt(
                (
                    "You are a fact-checker and quality reviewer in a multi-agent investigation pipeline. "
                    "Evaluate research findings for accuracy, source quality, completeness, "
                    "logical consistency, and alignment with the investigation plan."
                ),
                self.guidance_prompt,
                section_name="fact-checking, source verification, and research quality standards",
            )
            user_prompt = (
                "Review the investigation results against the plan bundle.\n"
                "Check for:\n"
                "- unsupported claims (claims without sources)\n"
                "- conflicting information not flagged by the researcher\n"
                "- missing coverage of required subtopics\n"
                "- logical gaps or non-sequiturs\n"
                "- source quality (prefer academic, official, and authoritative sources)\n"
                "Approve only when the research is complete, well-sourced, and aligned with the plan.\n"
                "Return JSON only.\n\n"
                f"Plan bundle:\n{plan_bundle.model_dump_json(indent=2)}\n\n"
                f"Research results:\n{execution_result.model_dump_json(indent=2)}"
            )
        else:
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
