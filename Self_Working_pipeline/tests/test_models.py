import pytest
from pydantic import ValidationError

from contracts.models import ExecutionResult, GeneratedFile, HarnessContract, ResearchReport, UserRequest
from tests.helpers import sample_plan_bundle


def test_user_request_requires_text() -> None:
    with pytest.raises(ValidationError):
        UserRequest(raw_request="")


def test_plan_bundle_accepts_optional_harness_contract() -> None:
    bundle = sample_plan_bundle([])
    bundle.harness_contract = HarnessContract(invariant_anchor="must-keep")
    assert bundle.harness_contract is not None
    assert bundle.harness_contract.invariant_anchor == "must-keep"


def test_execution_result_accepts_optional_research_report() -> None:
    result = ExecutionResult(
        workstream_id="ws1",
        summary="ok",
        files=[GeneratedFile(path="reports/ws1.md", content="x")],
        research_report=ResearchReport(workstream_id="ws1", scope="scope", claims=[], sources=[]),
    )
    assert result.research_report is not None
