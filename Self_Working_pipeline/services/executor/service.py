from __future__ import annotations

from pydantic import BaseModel

from contracts.models import ExecutionResult, PlanBundle, TaskAssignment
from core.prompting import compose_system_prompt
from services.adapters.base import JsonModelAdapter


class ExecutionEnvelope(BaseModel):
    result: ExecutionResult


class ExecutorService:
    def __init__(self, adapter: JsonModelAdapter, *, guidance_prompt: str = "", mode: str = "code") -> None:
        self.adapter = adapter
        self.guidance_prompt = guidance_prompt
        self.mode = mode

    def execute(
        self,
        *,
        assignment: TaskAssignment,
        plan_bundle: PlanBundle,
        workspace_snapshot: str,
        review_feedback: list[str],
    ) -> ExecutionResult:
        feedback_text = "\n".join(f"- {item}" for item in review_feedback) or "- none"
        if self.mode == "research":
            system_prompt = compose_system_prompt(
                (
                    "You are a research agent in a multi-agent investigation pipeline. "
                    "Your job is to research the assigned topic thoroughly, cite sources, "
                    "and produce well-structured investigation results. "
                    "Return your findings as structured files (markdown reports)."
                ),
                self.guidance_prompt,
                section_name="research methodology, source verification, and output formatting",
            )
            user_prompt = (
                "Research the following topic and produce investigation results.\n"
                "Rules:\n"
                "- cite all claims with source URLs or references\n"
                "- distinguish facts from speculation\n"
                "- flag any conflicting information found across sources\n"
                "- produce one or more markdown files with your findings\n"
                "- keep scope focused on the assigned workstream only\n\n"
                f"Task assignment:\n{assignment.model_dump_json(indent=2)}\n\n"
                f"Plan bundle:\n{plan_bundle.model_dump_json(indent=2)}\n\n"
                f"Current workspace snapshot:\n{workspace_snapshot or '[empty workspace]'}\n\n"
                f"Review feedback to address:\n{feedback_text}\n\n"
                "Return JSON only."
            )
        else:
            system_prompt = compose_system_prompt(
                (
                    "You are Codex acting as the implementation agent in a controlled delivery pipeline. "
                    "Write only the files needed for the assigned workstream and keep changes scoped."
                ),
                self.guidance_prompt,
                section_name="implementation, repository expectations, testing, reversibility, and workflow rules",
            )
            user_prompt = (
                "Create or update files for this workstream.\n"
                "Rules:\n"
                "- modify only files relevant to the workstream layer\n"
                "- include tests when the workstream implies behavior\n"
                "- keep dependencies minimal and use Python standard library when possible\n"
                "- honor any user additions recorded in plan_bundle.change_log\n"
                "- return relative file paths only\n\n"
                f"Task assignment:\n{assignment.model_dump_json(indent=2)}\n\n"
                f"Plan bundle:\n{plan_bundle.model_dump_json(indent=2)}\n\n"
                f"Current workspace snapshot:\n{workspace_snapshot or '[empty workspace]'}\n\n"
                f"Review feedback to address:\n{feedback_text}\n\n"
                "Return JSON only."
            )
        result = self.adapter.generate_structured(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_model=ExecutionEnvelope,
        )
        assert isinstance(result, ExecutionEnvelope)
        return result.result
