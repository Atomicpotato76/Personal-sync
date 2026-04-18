from contracts.models import UserRequest, Workstream
from services.planner.service import PlannerService
from tests.helpers import sample_plan_bundle


def test_condense_request_keeps_short_text() -> None:
    planner = PlannerService(object(), request_digest_chars=200)

    raw = "Build a small Python CLI with tests."

    assert planner.condense_request(raw) == raw


def test_condense_request_prioritizes_key_sections() -> None:
    planner = PlannerService(object(), request_digest_chars=700)
    raw = "\n".join(
        [
            "# Big Proposal",
            "",
            "Intro line " * 20,
            "",
            "## Reference Links",
            "- filler " * 40,
            "",
            "## Project Goal",
            "- build the core pipeline",
            "- keep approvals in the loop",
            "",
            "## Absolute Rules",
            "- do not modify legacy files",
            "- always add tests",
            "",
            "## First Milestone",
            "- create API contract",
            "- create router v5 plan",
        ]
    )

    digest = planner.condense_request(raw)

    assert "Condensed planning digest" in digest
    assert "## Project Goal" in digest
    assert "## Absolute Rules" in digest
    assert "## First Milestone" in digest
    assert len(digest) <= 700


def test_create_plan_uses_digest_for_long_requests() -> None:
    plan_bundle = sample_plan_bundle(
        [
            Workstream(
                id="WS1",
                name="Foundation",
                layer="infrastructure",
                objective="Build the first slice.",
                deliverables=["router_v5.py"],
                acceptance_criteria=["pytest passes"],
            )
        ]
    )
    captured: dict[str, str] = {}

    class CapturingAdapter:
        def generate_structured(self, *, system_prompt: str, user_prompt: str, response_model):
            captured["system_prompt"] = system_prompt
            captured["user_prompt"] = user_prompt
            return plan_bundle

    planner = PlannerService(CapturingAdapter(), request_digest_chars=500)
    raw_request = "# Project Goal\n" + ("Build a long request.\n" * 120)

    result = planner.create_plan(UserRequest(raw_request=raw_request))

    assert result == plan_bundle
    assert "Planning digest:" in captured["user_prompt"]
    assert "Condensed planning digest" in captured["user_prompt"]
