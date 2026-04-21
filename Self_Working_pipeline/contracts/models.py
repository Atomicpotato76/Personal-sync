from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class RunStage(str, Enum):
    intake = "intake"
    planning = "planning"
    plan_approved = "plan_approved"
    executing = "executing"
    reviewing = "reviewing"
    testing = "testing"
    merge_approved = "merge_approved"
    packaging = "packaging"
    completed = "completed"


class RunStatus(str, Enum):
    pending = "pending"
    waiting_approval = "waiting_approval"
    in_progress = "in_progress"
    completed = "completed"
    failed = "failed"
    blocked = "blocked"


class ApprovalStage(str, Enum):
    plan = "plan"
    checkpoint = "checkpoint"
    merge = "merge"


class WorkstreamStatus(str, Enum):
    pending = "pending"
    in_progress = "in_progress"
    retry_requested = "retry_requested"
    completed = "completed"
    failed = "failed"


class UserRequest(BaseModel):
    raw_request: str = Field(min_length=1)
    created_at: datetime = Field(default_factory=utc_now)
    requester: str = "local-user"


class ProjectBrief(BaseModel):
    title: str
    objective: str
    audience: str
    scope: list[str]
    deliverables: list[str]
    constraints: list[str] = Field(default_factory=list)


class ArchitectureSpec(BaseModel):
    overview: str
    components: list[str]
    data_flow: list[str]
    decisions: list[str]
    risks: list[str] = Field(default_factory=list)


class ApiEndpoint(BaseModel):
    name: str
    method: str
    path: str
    description: str
    request_schema: dict[str, Any] = Field(default_factory=dict)
    response_schema: dict[str, Any] = Field(default_factory=dict)


class ApiContract(BaseModel):
    interfaces: list[str]
    endpoints: list[ApiEndpoint] = Field(default_factory=list)
    events: list[str] = Field(default_factory=list)
    storage: list[str] = Field(default_factory=list)


class Workstream(BaseModel):
    id: str
    name: str
    layer: str
    objective: str
    deliverables: list[str]
    dependencies: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str]


class PlanChange(BaseModel):
    version: int
    summary: str
    additions: list[str] = Field(default_factory=list)
    actor: str = "local-user"
    created_at: datetime = Field(default_factory=utc_now)


class HarnessContract(BaseModel):
    invariant_anchor: str = ""
    scope_boundaries: list[str] = Field(default_factory=list)
    evidence_policy: list[str] = Field(default_factory=list)
    reasoning_protocol: str = ""
    output_contract: str = ""
    validation_checklist: list[str] = Field(default_factory=list)


class ResearchSource(BaseModel):
    source_id: str
    title: str = ""
    url: str | None = None
    doi: str | None = None
    pmid: str | None = None
    accession: str | None = None
    source_type: str
    tier: str
    retrieved_at: datetime = Field(default_factory=utc_now)
    notes: str = ""


class ResearchClaim(BaseModel):
    claim_id: str
    claim: str
    source_ids: list[str]
    confidence: str
    status: str
    notes: str = ""


class ResearchConflict(BaseModel):
    conflict_id: str
    topic: str
    source_ids: list[str]
    description: str
    resolution: str = ""


class ResearchReport(BaseModel):
    workstream_id: str
    scope: str
    claims: list[ResearchClaim]
    sources: list[ResearchSource]
    conflicts: list[ResearchConflict] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    confidence_summary: str = ""


class SynthesisReport(BaseModel):
    run_id: str
    source_workstream_ids: list[str]
    synthesis: str
    claims: list[ResearchClaim]
    sources: list[ResearchSource]
    conflicts: list[ResearchConflict] = Field(default_factory=list)
    unresolved_gaps: list[str] = Field(default_factory=list)


class JudgeFinding(BaseModel):
    severity: str
    target_workstream_id: str | None = None
    description: str
    suggested_fix: str


class JudgeReport(BaseModel):
    approved: bool
    summary: str
    findings: list[JudgeFinding] = Field(default_factory=list)
    retry_workstream_ids: list[str] = Field(default_factory=list)


class PlanBundle(BaseModel):
    project_brief: ProjectBrief
    architecture_spec: ArchitectureSpec
    api_contract: ApiContract
    workstreams: list[Workstream]
    test_plan: list[str]
    change_log: list[PlanChange] = Field(default_factory=list)
    harness_contract: HarnessContract | None = None


class TaskAssignment(BaseModel):
    run_id: str
    workstream_id: str
    agent_role: str
    instructions: str
    context_paths: list[str] = Field(default_factory=list)
    retry_count: int = 0


class GeneratedFile(BaseModel):
    path: str
    content: str
    description: str = ""


class ExecutionResult(BaseModel):
    workstream_id: str
    summary: str
    files: list[GeneratedFile]
    notes: list[str] = Field(default_factory=list)
    research_report: ResearchReport | None = None


class ReviewIssue(BaseModel):
    severity: str
    description: str
    file_path: str | None = None
    suggested_fix: str


class ReviewReport(BaseModel):
    workstream_id: str
    approved: bool
    summary: str
    issues: list[ReviewIssue] = Field(default_factory=list)


class TestResult(BaseModel):
    name: str
    passed: bool
    details: str = ""


class TestReport(BaseModel):
    passed: bool
    command: str
    results: list[TestResult] = Field(default_factory=list)
    stdout: str = ""
    stderr: str = ""


class ArtifactEntry(BaseModel):
    path: str
    kind: str
    description: str


class ArtifactManifest(BaseModel):
    run_id: str
    created_at: datetime = Field(default_factory=utc_now)
    package_path: str
    entries: list[ArtifactEntry]


class ApprovalDecision(BaseModel):
    run_id: str
    stage: ApprovalStage
    approved: bool
    actor: str = "local-user"
    comment: str = ""
    created_at: datetime = Field(default_factory=utc_now)


class SupervisorDecision(BaseModel):
    stage: ApprovalStage
    approved: bool
    rationale: str
    risk_flags: list[str] = Field(default_factory=list)
    requires_human: bool = False


class SupervisorTrace(BaseModel):
    run_id: str
    sequence: int
    stage: ApprovalStage
    agent_id: str
    decision_source: str
    approved: bool
    rationale: str
    risk_flags: list[str] = Field(default_factory=list)
    requires_human: bool = False
    input_digest: str
    latency_ms: int = 0
    model_name: str
    error_code: str | None = None
    created_at: datetime = Field(default_factory=utc_now)


class SupervisorSession(BaseModel):
    run_id: str
    enabled: bool = False
    status: str = "idle"
    current_gate: ApprovalStage | None = None
    current_agent_id: str | None = None
    cycles_completed: int = 0
    max_cycles: int = 20
    same_gate_repeats: dict[str, int] = Field(default_factory=dict)
    supervisor_denials: int = 0
    consecutive_failures: int = 0
    max_same_gate_repeats: int = 3
    max_supervisor_denials: int = 1
    max_consecutive_failures: int = 2
    max_plan_revisions: int = 3
    last_rationale: str | None = None
    last_error_code: str | None = None
    updated_at: datetime = Field(default_factory=utc_now)


class RunRecord(BaseModel):
    run_id: str
    request: UserRequest
    stage: RunStage
    status: RunStatus
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    plan_path: str | None = None
    workspace_path: str | None = None
    manifest_path: str | None = None
    last_error: str | None = None


class CheckpointSummary(BaseModel):
    run_id: str
    stage: RunStage
    status: RunStatus
    plan_version: int = 1
    overview: str
    completed: list[str] = Field(default_factory=list)
    in_progress: list[str] = Field(default_factory=list)
    pending: list[str] = Field(default_factory=list)
    recent_changes: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    next_step: str
    latest_stage_name: str | None = None
    latest_stage_summary: str | None = None


class DirectionSnapshot(BaseModel):
    run_id: str
    sequence: int
    trigger_event: str
    stage: RunStage
    status: RunStatus
    headline: str
    summary: str
    recommendation: str
    options: list[str] = Field(default_factory=list)
    completed_stage: str | None = None
    client_summary: str | None = None
    artifact_highlights: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)


class StageNarrative(BaseModel):
    run_id: str
    sequence: int
    stage_name: str
    completed_workstreams: list[str] = Field(default_factory=list)
    summary: str
    client_summary: str
    artifact_highlights: list[str] = Field(default_factory=list)
    next_focus: str | None = None
    created_at: datetime = Field(default_factory=utc_now)


class EventRecord(BaseModel):
    run_id: str
    stage: RunStage
    event_type: str
    message: str
    created_at: datetime = Field(default_factory=utc_now)
    payload: dict[str, Any] = Field(default_factory=dict)
