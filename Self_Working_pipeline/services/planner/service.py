from __future__ import annotations

import re

from contracts.models import PlanBundle, UserRequest
from core.prompting import compose_system_prompt
from services.adapters.base import JsonModelAdapter


class PlannerService:
    PRIORITY_KEYWORDS: tuple[tuple[str, ...], ...] = (
        ("goal", "summary", "objective", "overview"),
        ("scope", "out of scope", "deliverable", "outcome"),
        ("rule", "constraint", "guardrail", "absolute"),
        ("architecture", "environment", "directory", "stack"),
        ("roadmap", "phase", "milestone"),
        ("success", "metric", "quality"),
        ("instruction", "checklist", "first", "day 1"),
    )
    HARNESS_KEYWORDS: tuple[str, ...] = (
        "harness",
        "contract",
        "non-negotiable",
        "invariant",
        "source policy",
        "evidence policy",
        "output contract",
        "validation checklist",
        "scope boundary",
    )

    def __init__(
        self,
        adapter: JsonModelAdapter,
        *,
        guidance_prompt: str = "",
        request_digest_chars: int = 4000,
        mode: str = "code",
    ) -> None:
        self.adapter = adapter
        self.guidance_prompt = guidance_prompt
        self.request_digest_chars = request_digest_chars
        self.mode = mode

    def _split_markdown_sections(self, text: str) -> tuple[list[str], list[tuple[str, list[str]]]]:
        preamble: list[str] = []
        sections: list[tuple[str, list[str]]] = []
        current_heading: str | None = None
        current_lines: list[str] = []

        for line in text.splitlines():
            if re.match(r"^\s{0,3}#{1,6}\s+", line):
                if current_heading is None:
                    if current_lines:
                        preamble.extend(current_lines)
                else:
                    sections.append((current_heading, current_lines[:]))
                current_heading = line.strip()
                current_lines = []
                continue
            current_lines.append(line)

        if current_heading is None:
            if current_lines:
                preamble.extend(current_lines)
        else:
            sections.append((current_heading, current_lines[:]))
        return preamble, sections

    def _section_priority(self, heading: str) -> int:
        lowered = heading.lower()
        for index, keywords in enumerate(self.PRIORITY_KEYWORDS):
            if any(keyword in lowered for keyword in keywords):
                return index
        return len(self.PRIORITY_KEYWORDS)

    def _trim_section_body(self, lines: list[str], *, max_chars: int) -> str:
        kept: list[str] = []
        total = 0
        for raw_line in lines:
            line = raw_line.rstrip()
            if not line and (not kept or not kept[-1]):
                continue
            candidate = line[:240]
            projected = total + len(candidate) + 1
            if kept and projected > max_chars:
                break
            if not kept and projected > max_chars:
                kept.append(candidate[: max_chars - 3].rstrip() + "...")
                return "\n".join(kept)
            kept.append(candidate)
            total = projected
        return "\n".join(kept).strip()

    def _extract_preserved_sections(self, sections: list[tuple[str, list[str]]]) -> list[tuple[str, str]]:
        preserved: list[tuple[str, str]] = []
        for heading, body_lines in sections:
            if any(keyword in heading.lower() for keyword in self.HARNESS_KEYWORDS):
                preserved.append((heading, "\n".join(body_lines).strip()))
        return preserved

    def condense_request(self, raw_request: str) -> str:
        text = raw_request.strip()
        if len(text) <= self.request_digest_chars:
            return text

        preamble, sections = self._split_markdown_sections(text)
        preserved_sections = self._extract_preserved_sections(sections)
        if not sections:
            head = text[: self.request_digest_chars // 2].rstrip()
            tail = text[-(self.request_digest_chars // 3) :].lstrip()
            digest = (
                "Condensed request digest:\n"
                f"{head}\n\n"
                "[...]\n\n"
                f"{tail}"
            )
            return digest[: self.request_digest_chars].rstrip()

        preamble_text = self._trim_section_body(preamble, max_chars=500)
        ordered_sections = sorted(
            enumerate(sections),
            key=lambda item: (self._section_priority(item[1][0]), item[0]),
        )

        lines = [
            f"Condensed planning digest from a longer request ({len(text)} chars).",
            "Preserve the original intent, rules, and milestones while keeping the plan compact.",
        ]
        if preserved_sections:
            lines.append("")
            lines.append("## Non-Negotiable Harness Sections")
            for heading, section_text in preserved_sections:
                lines.extend(["", heading, section_text])
        if preamble_text:
            lines.extend(["", "## Request Overview", preamble_text])

        remaining = max(self.request_digest_chars - len("\n".join(lines)) - 1, 600)
        for _, (heading, body_lines) in ordered_sections:
            if remaining <= 160:
                break
            body_budget = min(remaining - len(heading) - 8, 520)
            if body_budget < 80:
                break
            trimmed_body = self._trim_section_body(body_lines, max_chars=body_budget)
            if not trimmed_body:
                continue
            block = f"\n\n{heading}\n{trimmed_body}"
            if len("\n".join(lines)) + len(block) > self.request_digest_chars:
                continue
            lines.append("")
            lines.append(heading)
            lines.append(trimmed_body)
            remaining = self.request_digest_chars - len("\n".join(lines))

        digest = "\n".join(lines).strip()
        if len(digest) > self.request_digest_chars:
            return digest[: self.request_digest_chars].rstrip()
        return digest

    def create_plan(self, user_request: UserRequest) -> PlanBundle:
        planning_request = self.condense_request(user_request.raw_request)
        request_label = "Planning digest" if planning_request != user_request.raw_request else "User request"
        if self.mode == "research":
            system_prompt = compose_system_prompt(
                (
                    "You are a research planning agent for a multi-agent investigation pipeline. "
                    "Decompose the investigation request into focused research workstreams. "
                    "Each workstream should target a specific subtopic or angle of investigation."
                ),
                self.guidance_prompt,
                section_name="research planning, topic decomposition, and investigation methodology",
            )
            user_prompt = (
                "Create a research plan bundle for the following investigation request.\n"
                "Requirements:\n"
                "- decompose the topic into focused, non-overlapping research workstreams\n"
                "- each workstream should have clear deliverables (markdown reports)\n"
                "- include a verification plan (how to cross-check findings)\n"
                "- prioritize authoritative and primary sources\n"
                "- keep workstreams small enough to be completed in one research session\n\n"
                "- HarnessContract fields are non-negotiable and must be filled when present in the request\n\n"
                f"{request_label}:\n{planning_request}\n\n"
                "Return JSON only."
            )
        else:
            system_prompt = compose_system_prompt(
                (
                    "You are Claude Code acting as the architecture and planning lead for a multi-agent "
                    "software delivery pipeline. Produce a compact but implementation-ready plan bundle."
                ),
                self.guidance_prompt,
                section_name="planning, specification, workflow rules, and repository expectations",
            )
            user_prompt = (
                "Create a plan bundle for the following natural language request.\n"
                "Requirements:\n"
                "- produce project brief, architecture spec, API contract, workstreams, and test plan\n"
                "- keep workstreams small and verifiable\n"
                "- make deliverables concrete enough for a coding agent to execute\n"
                "- prefer a Python-first local MVP if the request does not force another stack\n\n"
                f"{request_label}:\n{planning_request}\n\n"
                "Return JSON only."
            )
        result = self.adapter.generate_structured(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_model=PlanBundle,
        )
        assert isinstance(result, PlanBundle)
        return result
