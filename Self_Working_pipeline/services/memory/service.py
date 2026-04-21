from __future__ import annotations

import json
import uuid
import zipfile
from pathlib import Path

from sqlalchemy import select

from contracts.models import (
    ApprovalDecision,
    ArtifactEntry,
    ArtifactManifest,
    CheckpointSummary,
    DirectionSnapshot,
    EventRecord,
    ExecutionResult,
    PlanChange,
    PlanBundle,
    ReviewReport,
    RunRecord,
    RunStage,
    RunStatus,
    StageNarrative,
    SupervisorSession,
    SupervisorTrace,
    TestReport,
    UserRequest,
    WorkstreamStatus,
    utc_now,
)
from core.settings import Settings
from services.memory.models import ApprovalEntity, Base, EventEntity, RunEntity, WorkstreamEntity


class MemoryService:
    def __init__(self, *, settings: Settings, session_factory) -> None:
        self.settings = settings
        self.session_factory = session_factory
        self._initialize_database()

    def _initialize_database(self) -> None:
        # Resolve the bound engine without reaching into sessionmaker internals.
        # Prefer a dedicated `engine` attribute if the factory carries one,
        # otherwise fall back to a throwaway session's bind (public API).
        engine = getattr(self.session_factory, "engine", None)
        if engine is None:
            kw = getattr(self.session_factory, "kw", None)
            if isinstance(kw, dict) and kw.get("bind") is not None:
                engine = kw["bind"]
        if engine is None:
            with self.session_factory() as session:
                engine = session.get_bind()
        Base.metadata.create_all(engine)

    def create_run(self, request_text: str) -> RunRecord:
        run_id = uuid.uuid4().hex[:12]
        now = utc_now()
        request = UserRequest(raw_request=request_text)
        plans_dir = self._default_plan_dir(run_id, created_at=now)
        outputs_dir = self._default_output_dir(run_id, created_at=now)
        workspace_dir = outputs_dir / "workspace"
        for path in (plans_dir, outputs_dir, workspace_dir):
            path.mkdir(parents=True, exist_ok=True)

        run = RunEntity(
            run_id=run_id,
            request_json=request.model_dump_json(),
            stage=RunStage.intake.value,
            status=RunStatus.pending.value,
            created_at=now,
            updated_at=now,
            plan_path=str(plans_dir / "plan_bundle.json"),
            workspace_path=str(workspace_dir),
            manifest_path=None,
            last_error=None,
        )
        with self.session_factory() as session:
            session.add(run)
            session.commit()
        self.append_event(run_id, RunStage.intake, "run_created", "Run created.")
        return self.get_run(run_id)

    def get_run(self, run_id: str) -> RunRecord:
        with self.session_factory() as session:
            entity = session.get(RunEntity, run_id)
            if entity is None:
                raise ValueError(f"Unknown run id: {run_id}")
            return self._entity_to_run_record(entity)

    def list_runs(self, limit: int = 20) -> list[RunRecord]:
        with self.session_factory() as session:
            stmt = select(RunEntity).order_by(RunEntity.updated_at.desc()).limit(limit)
            rows = session.execute(stmt).scalars().all()
        return [self._entity_to_run_record(row) for row in rows]

    def update_run(self, run_id: str, **changes) -> RunRecord:
        with self.session_factory() as session:
            entity = session.get(RunEntity, run_id)
            if entity is None:
                raise ValueError(f"Unknown run id: {run_id}")
            for key, value in changes.items():
                setattr(entity, key, value.value if hasattr(value, "value") else value)
            entity.updated_at = utc_now()
            session.add(entity)
            session.commit()
        return self.get_run(run_id)

    def append_event(self, run_id: str, stage: RunStage, event_type: str, message: str, payload: dict | None = None) -> None:
        event = EventEntity(
            run_id=run_id,
            stage=stage.value,
            event_type=event_type,
            message=message,
            payload_json=json.dumps(payload or {}),
            created_at=utc_now(),
        )
        with self.session_factory() as session:
            session.add(event)
            session.commit()

    def list_events(self, run_id: str, limit: int = 10) -> list[EventRecord]:
        with self.session_factory() as session:
            stmt = select(EventEntity).where(EventEntity.run_id == run_id).order_by(EventEntity.id.desc()).limit(limit)
            rows = session.execute(stmt).scalars().all()
        return [
            EventRecord(
                run_id=row.run_id,
                stage=RunStage(row.stage),
                event_type=row.event_type,
                message=row.message,
                created_at=row.created_at,
                payload=json.loads(row.payload_json),
            )
            for row in rows
        ]

    def save_plan_bundle(self, run_id: str, plan_bundle: PlanBundle, *, reset_workstreams: bool = True) -> Path:
        run = self.get_run(run_id)
        plan_path = Path(run.plan_path) if run.plan_path else self._run_plan_dir(run) / "plan_bundle.json"
        plan_path.parent.mkdir(parents=True, exist_ok=True)
        plan_path.write_text(plan_bundle.model_dump_json(indent=2), encoding="utf-8")
        self._write_plan_markdown(run_id, plan_bundle)
        version_number = self._next_plan_version(run_id)
        self._write_plan_version_files(run_id, plan_bundle, version_number)
        if reset_workstreams:
            with self.session_factory() as session:
                session.query(WorkstreamEntity).filter(WorkstreamEntity.run_id == run_id).delete()
                for workstream in plan_bundle.workstreams:
                    session.add(
                        WorkstreamEntity(
                            run_id=run_id,
                            workstream_id=workstream.id,
                            name=workstream.name,
                            layer=workstream.layer,
                            status=WorkstreamStatus.pending.value,
                            retry_count=0,
                        )
                    )
                session.commit()
            self.update_run(run_id, stage=RunStage.planning, status=RunStatus.waiting_approval, plan_path=str(plan_path))
        else:
            self.update_run(run_id, plan_path=str(plan_path))
        self.append_event(run_id, RunStage.planning, "plan_saved", "Plan bundle generated.")
        return plan_path

    def append_plan_addition(self, run_id: str, addition: str, *, actor: str = "local-user") -> Path:
        plan_bundle = self.load_plan_bundle(run_id)
        next_version = self._next_plan_version(run_id)
        plan_bundle.change_log.append(
            PlanChange(
                version=next_version,
                summary=self._summarize_addition(addition),
                additions=[addition],
                actor=actor,
            )
        )
        path = self.save_plan_bundle(run_id, plan_bundle, reset_workstreams=False)
        self.append_event(
            run_id,
            self.get_run(run_id).stage,
            "plan_updated",
            f"Plan updated with user addition for version {next_version}.",
            payload={"addition": addition, "version": next_version},
        )
        return path

    def _write_plan_markdown(self, run_id: str, plan_bundle: PlanBundle) -> None:
        plan_dir = self._run_plan_dir(run_id)
        plan_dir.mkdir(parents=True, exist_ok=True)
        lines = [
            f"# {plan_bundle.project_brief.title}",
            "",
            "## 목표",
            plan_bundle.project_brief.objective,
            "",
            "## 워크스트림",
        ]
        for workstream in plan_bundle.workstreams:
            lines.append(f"- `{workstream.id}` {workstream.name}: {workstream.objective}")
        lines.extend(["", "## 테스트 계획"])
        for item in plan_bundle.test_plan:
            lines.append(f"- {item}")
        if plan_bundle.change_log:
            lines.extend(["", "## 추가된 방향"])
            for change in plan_bundle.change_log:
                lines.append(f"### v{change.version:03d} - {change.summary}")
                lines.append(f"- 요청자: {change.actor}")
                for addition in change.additions:
                    lines.append(f"- 추가 내용: {addition}")
        (plan_dir / "summary.md").write_text("\n".join(lines), encoding="utf-8")

    def _write_plan_version_files(self, run_id: str, plan_bundle: PlanBundle, version_number: int) -> None:
        version_dir = self._run_plan_dir(run_id) / "versions"
        version_dir.mkdir(parents=True, exist_ok=True)
        json_path = version_dir / f"v{version_number:03d}_plan_bundle.json"
        markdown_path = version_dir / f"v{version_number:03d}_summary.md"
        json_path.write_text(plan_bundle.model_dump_json(indent=2), encoding="utf-8")

        lines = [
            f"# Plan Version v{version_number:03d}",
            "",
            f"- 제목: {plan_bundle.project_brief.title}",
            f"- 목표: {plan_bundle.project_brief.objective}",
        ]
        if version_number == 1:
            lines.extend(["", "초기 계획 스냅샷입니다."])
        else:
            latest_change = next((item for item in reversed(plan_bundle.change_log) if item.version == version_number), None)
            lines.extend(["", "## 이번 버전에 추가된 내용"])
            if latest_change is None:
                lines.append("- 기록된 추가 사항이 없습니다.")
            else:
                lines.append(f"- 요약: {latest_change.summary}")
                lines.append(f"- 요청자: {latest_change.actor}")
                for addition in latest_change.additions:
                    lines.append(f"- 추가 내용: {addition}")
        markdown_path.write_text("\n".join(lines), encoding="utf-8")

    def _next_plan_version(self, run_id: str) -> int:
        version_dir = self._run_plan_dir(run_id) / "versions"
        if not version_dir.exists():
            return 1
        return len(list(version_dir.glob("v*_plan_bundle.json"))) + 1

    def _summarize_addition(self, addition: str) -> str:
        collapsed = " ".join(addition.split())
        if len(collapsed) <= 72:
            return collapsed
        return f"{collapsed[:69]}..."

    def load_plan_bundle(self, run_id: str) -> PlanBundle:
        run = self.get_run(run_id)
        if not run.plan_path:
            raise ValueError(f"No plan exists for run {run_id}")
        return PlanBundle.model_validate_json(Path(run.plan_path).read_text(encoding="utf-8"))

    def record_approval(self, decision: ApprovalDecision) -> None:
        entity = ApprovalEntity(
            run_id=decision.run_id,
            stage=decision.stage.value,
            approved=decision.approved,
            actor=decision.actor,
            comment=decision.comment,
            created_at=decision.created_at,
        )
        with self.session_factory() as session:
            session.add(entity)
            session.commit()
        if decision.stage.value == "plan":
            stage = RunStage.planning
        elif decision.stage.value == "merge":
            stage = RunStage.testing
        else:
            stage = self.get_run(decision.run_id).stage
        outcome = "approved" if decision.approved else "rejected"
        self.append_event(decision.run_id, stage, "approval_recorded", f"{decision.stage.value} {outcome}.")

    def list_workstreams(self, run_id: str) -> list[dict]:
        with self.session_factory() as session:
            stmt = select(WorkstreamEntity).where(WorkstreamEntity.run_id == run_id).order_by(WorkstreamEntity.id.asc())
            rows = session.execute(stmt).scalars().all()
        return [
            {
                "workstream_id": row.workstream_id,
                "name": row.name,
                "layer": row.layer,
                "status": row.status,
                "retry_count": row.retry_count,
                "latest_feedback": json.loads(row.latest_feedback or "[]"),
                "changed_files": json.loads(row.changed_files or "[]"),
                "last_result_path": row.last_result_path,
                "last_review_path": row.last_review_path,
            }
            for row in rows
        ]

    def update_workstream(
        self,
        run_id: str,
        workstream_id: str,
        *,
        status: WorkstreamStatus | None = None,
        retry_count: int | None = None,
        last_result_path: str | None = None,
        last_review_path: str | None = None,
        latest_feedback: list[str] | None = None,
        changed_files: list[str] | None = None,
    ) -> None:
        with self.session_factory() as session:
            stmt = select(WorkstreamEntity).where(
                WorkstreamEntity.run_id == run_id,
                WorkstreamEntity.workstream_id == workstream_id,
            )
            entity = session.execute(stmt).scalar_one_or_none()
            if entity is None:
                raise ValueError(f"Workstream {workstream_id!r} not found for run {run_id!r}")
            if status is not None:
                entity.status = status.value
            if retry_count is not None:
                entity.retry_count = retry_count
            if last_result_path is not None:
                entity.last_result_path = last_result_path
            if last_review_path is not None:
                entity.last_review_path = last_review_path
            if latest_feedback is not None:
                entity.latest_feedback = json.dumps(latest_feedback)
            if changed_files is not None:
                entity.changed_files = json.dumps(changed_files)
            session.add(entity)
            session.commit()

    def get_workspace_path(self, run_id: str) -> Path:
        run = self.get_run(run_id)
        if not run.workspace_path:
            raise ValueError(f"No workspace for run {run_id}")
        path = Path(run.workspace_path)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def workspace_snapshot(self, run_id: str, limit: int = 8) -> str:
        workspace = self.get_workspace_path(run_id)
        snippets: list[str] = []
        for file_path in sorted(workspace.rglob("*")):
            if not file_path.is_file():
                continue
            relative = file_path.relative_to(workspace).as_posix()
            try:
                content = file_path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            snippets.append(f"## {relative}\n{content[:2000]}")
            if len(snippets) >= limit:
                break
        return "\n\n".join(snippets)

    def save_execution_result(self, run_id: str, result: ExecutionResult) -> Path:
        workspace = self.get_workspace_path(run_id)
        workspace_root = workspace.resolve()
        exec_dir = self._run_output_dir(run_id) / "executions"
        exec_dir.mkdir(parents=True, exist_ok=True)
        metadata_path = exec_dir / f"{result.workstream_id}.json"
        metadata_path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
        changed_files: list[str] = []
        for generated_file in result.files:
            file_path = Path(generated_file.path)
            if file_path.is_absolute() or ".." in file_path.parts:
                raise ValueError(f"Unsafe generated file path: {generated_file.path}")
            target = (workspace_root / generated_file.path).resolve()
            if not target.is_relative_to(workspace_root):
                raise ValueError(f"Generated file path escapes workspace: {generated_file.path}")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(generated_file.content, encoding="utf-8")
            changed_files.append(generated_file.path)
        if result.research_report is not None:
            evidence_rel = Path("research_evidence") / f"{result.workstream_id}.json"
            evidence_path = (workspace_root / evidence_rel).resolve()
            evidence_path.parent.mkdir(parents=True, exist_ok=True)
            evidence_path.write_text(result.research_report.model_dump_json(indent=2), encoding="utf-8")
            changed_files.append(evidence_rel.as_posix())
        self.update_workstream(
            run_id,
            result.workstream_id,
            last_result_path=str(metadata_path),
            changed_files=changed_files,
        )
        self.append_event(
            run_id,
            RunStage.executing,
            "execution_saved",
            f"Execution result saved for {result.workstream_id}.",
            payload={"files": changed_files},
        )
        return metadata_path

    def save_review_report(self, run_id: str, report: ReviewReport) -> Path:
        review_dir = self._run_output_dir(run_id) / "reviews"
        review_dir.mkdir(parents=True, exist_ok=True)
        path = review_dir / f"{report.workstream_id}.json"
        path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
        self.update_workstream(
            run_id,
            report.workstream_id,
            last_review_path=str(path),
            latest_feedback=[issue.suggested_fix for issue in report.issues],
        )
        self.append_event(
            run_id,
            RunStage.reviewing,
            "review_saved",
            f"Review saved for {report.workstream_id}.",
            payload={"approved": report.approved},
        )
        return path

    def save_test_report(self, run_id: str, report: TestReport) -> Path:
        test_dir = self._run_output_dir(run_id) / "tests"
        test_dir.mkdir(parents=True, exist_ok=True)
        path = test_dir / "report.json"
        path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
        log_path = test_dir / "pytest.log"
        log_path.write_text(f"STDOUT:\n{report.stdout}\n\nSTDERR:\n{report.stderr}", encoding="utf-8")
        self.append_event(
            run_id,
            RunStage.testing,
            "tests_recorded",
            "Test report recorded.",
            payload={"passed": report.passed},
        )
        return path

    def load_latest_test_report(self, run_id: str) -> TestReport | None:
        path = self._run_output_dir(run_id) / "tests" / "report.json"
        if not path.exists():
            return None
        return TestReport.model_validate_json(path.read_text(encoding="utf-8"))

    def package_workspace(self, run_id: str) -> ArtifactManifest:
        workspace = self.get_workspace_path(run_id)
        package_dir = self._run_output_dir(run_id) / "package"
        package_dir.mkdir(parents=True, exist_ok=True)
        archive_path = package_dir / f"{run_id}.zip"
        if archive_path.exists():
            archive_path.unlink()
        with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as bundle:
            for file_path in workspace.rglob("*"):
                if file_path.is_file():
                    bundle.write(file_path, file_path.relative_to(workspace).as_posix())
        entries = [
            ArtifactEntry(
                path=str(file_path.relative_to(workspace).as_posix()),
                kind="generated_file",
                description="Generated workspace artifact",
            )
            for file_path in workspace.rglob("*")
            if file_path.is_file()
        ]
        manifest = ArtifactManifest(run_id=run_id, package_path=str(archive_path), entries=entries)
        manifest_path = package_dir / "manifest.json"
        manifest_path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
        self.update_run(run_id, manifest_path=str(manifest_path))
        self.append_event(run_id, RunStage.packaging, "package_created", "Package bundle created.")
        return manifest

    def infer_impacted_workstreams(self, run_id: str, report: TestReport) -> list[str]:
        combined = f"{report.stdout}\n{report.stderr}".replace("\\", "/")
        impacted: list[str] = []
        for item in self.list_workstreams(run_id):
            if any(
                path.replace("\\", "/") in combined or Path(path).name in combined
                for path in item["changed_files"]
            ):
                impacted.append(item["workstream_id"])
        if impacted:
            return impacted
        completed = [item for item in self.list_workstreams(run_id) if item["status"] == WorkstreamStatus.completed.value]
        return [completed[-1]["workstream_id"]] if completed else []

    def get_plan_version(self, run_id: str) -> int:
        version_dir = self._run_plan_dir(run_id) / "versions"
        if not version_dir.exists():
            return 0
        return len(list(version_dir.glob("v*_plan_bundle.json")))

    def get_direction_count(self, run_id: str) -> int:
        direction_dir = self._run_plan_dir(run_id) / "directions"
        if not direction_dir.exists():
            return 0
        return len(list(direction_dir.glob("direction_*.json")))

    def get_latest_direction(self, run_id: str) -> DirectionSnapshot | None:
        latest_path = self._run_plan_dir(run_id) / "directions" / "latest_direction.json"
        if not latest_path.exists():
            return None
        return DirectionSnapshot.model_validate_json(latest_path.read_text(encoding="utf-8"))

    def get_supervisor_trace_count(self, run_id: str) -> int:
        trace_dir = self._run_plan_dir(run_id) / "supervisor" / "traces"
        if not trace_dir.exists():
            return 0
        return len(list(trace_dir.glob("trace_*.json")))

    def get_latest_supervisor_trace(self, run_id: str) -> SupervisorTrace | None:
        latest_path = self._run_plan_dir(run_id) / "supervisor" / "latest_trace.json"
        if not latest_path.exists():
            return None
        return SupervisorTrace.model_validate_json(latest_path.read_text(encoding="utf-8"))

    def list_supervisor_traces(self, run_id: str, limit: int = 10) -> list[SupervisorTrace]:
        trace_dir = self._run_plan_dir(run_id) / "supervisor" / "traces"
        if not trace_dir.exists():
            return []
        paths = sorted(trace_dir.glob("trace_*.json"), reverse=True)[:limit]
        return [SupervisorTrace.model_validate_json(path.read_text(encoding="utf-8")) for path in paths]

    def save_supervisor_trace(self, run_id: str, trace: SupervisorTrace) -> Path:
        trace_dir = self._run_plan_dir(run_id) / "supervisor" / "traces"
        trace_dir.mkdir(parents=True, exist_ok=True)
        json_path = trace_dir / f"trace_{trace.sequence:03d}_{trace.stage.value}_{trace.agent_id}.json"
        latest_json = self._run_plan_dir(run_id) / "supervisor" / "latest_trace.json"
        latest_md = self._run_plan_dir(run_id) / "supervisor" / "latest_trace.md"
        trace_text = trace.model_dump_json(indent=2)
        json_path.write_text(trace_text, encoding="utf-8")
        latest_json.write_text(trace_text, encoding="utf-8")
        latest_md.write_text(self._render_supervisor_trace_markdown(trace), encoding="utf-8")
        return json_path

    def get_latest_supervisor_session(self, run_id: str) -> SupervisorSession | None:
        latest_path = self._run_plan_dir(run_id) / "supervisor" / "latest_session.json"
        if not latest_path.exists():
            return None
        return SupervisorSession.model_validate_json(latest_path.read_text(encoding="utf-8"))

    def save_supervisor_session(self, run_id: str, session: SupervisorSession) -> Path:
        supervisor_dir = self._run_plan_dir(run_id) / "supervisor"
        supervisor_dir.mkdir(parents=True, exist_ok=True)
        session_path = supervisor_dir / "latest_session.json"
        markdown_path = supervisor_dir / "latest_session.md"
        session_path.write_text(session.model_dump_json(indent=2), encoding="utf-8")
        markdown_path.write_text(self._render_supervisor_session_markdown(session), encoding="utf-8")
        return session_path

    def get_stage_narrative_count(self, run_id: str) -> int:
        narrative_dir = self._run_plan_dir(run_id) / "stage_narratives"
        if not narrative_dir.exists():
            return 0
        return len(list(narrative_dir.glob("stage_*.json")))

    def get_latest_stage_narrative(self, run_id: str) -> StageNarrative | None:
        latest_path = self._run_plan_dir(run_id) / "stage_narratives" / "latest_stage.json"
        if not latest_path.exists():
            return None
        return StageNarrative.model_validate_json(latest_path.read_text(encoding="utf-8"))

    def save_stage_narrative(self, run_id: str, stage_name: str) -> StageNarrative:
        narrative = self.build_stage_narrative(run_id, stage_name=stage_name)
        narrative_dir = self._run_plan_dir(run_id) / "stage_narratives"
        narrative_dir.mkdir(parents=True, exist_ok=True)
        slug = self._slugify(stage_name)
        json_path = narrative_dir / f"stage_{narrative.sequence:03d}_{slug}.json"
        markdown_path = narrative_dir / f"stage_{narrative.sequence:03d}_{slug}.md"
        latest_json = narrative_dir / "latest_stage.json"
        latest_markdown = narrative_dir / "latest_stage.md"

        json_text = narrative.model_dump_json(indent=2)
        markdown_text = self._render_stage_narrative_markdown(narrative)
        json_path.write_text(json_text, encoding="utf-8")
        markdown_path.write_text(markdown_text, encoding="utf-8")
        latest_json.write_text(json_text, encoding="utf-8")
        latest_markdown.write_text(markdown_text, encoding="utf-8")

        self.append_event(
            run_id,
            RunStage.executing,
            "stage_narrative_saved",
            f"Client-facing stage summary saved for {stage_name}.",
            payload={"sequence": narrative.sequence, "stage_name": stage_name},
        )
        return narrative

    def build_stage_narrative(self, run_id: str, *, stage_name: str) -> StageNarrative:
        plan_bundle = self.load_plan_bundle(run_id)
        workstreams = self.list_workstreams(run_id)
        stage_items = [item for item in workstreams if item["layer"] == stage_name]
        completed_stage_items = [item for item in stage_items if item["status"] == WorkstreamStatus.completed.value]
        stage_specs = [item for item in plan_bundle.workstreams if item.layer == stage_name]

        completed_names = [item["name"] for item in completed_stage_items]
        objective_snippets = [item.objective for item in stage_specs[:3]]
        stage_purpose = " ".join(objective_snippets) if objective_snippets else f"Advance the {stage_name} stage."
        artifact_highlights = self._collect_stage_artifact_highlights(completed_stage_items)

        if artifact_highlights:
            highlighted_items = ", ".join(artifact_highlights[:3])
            client_summary = (
                f"{stage_name} 단계가 완료되었습니다. 쉽게 말해 이번 단계에서 의미 있는 작업 묶음이 끝났고 "
                f"{highlighted_items} 같은 구체적인 결과물이 나왔습니다."
            )
        else:
            client_summary = (
                f"{stage_name} 단계가 완료되었습니다. 쉽게 말해 이번 단계에서 의미 있는 작업 묶음이 끝났고 "
                "다음 단계로 넘어갈 준비가 되었습니다."
            )

        remaining_stage_names: list[str] = []
        for workstream in plan_bundle.workstreams:
            matching = next((item for item in workstreams if item["workstream_id"] == workstream.id), None)
            if matching is None or workstream.layer == stage_name:
                continue
            if matching["status"] != WorkstreamStatus.completed.value and workstream.layer not in remaining_stage_names:
                remaining_stage_names.append(workstream.layer)

        summary = (
            f"{stage_name} 단계에서 {len(completed_names)}개 워크스트림을 완료했습니다. "
            f"핵심 초점: {stage_purpose}"
        )
        return StageNarrative(
            run_id=run_id,
            sequence=self.get_stage_narrative_count(run_id) + 1,
            stage_name=stage_name,
            completed_workstreams=completed_names,
            summary=summary,
            client_summary=client_summary,
            artifact_highlights=artifact_highlights,
            next_focus=remaining_stage_names[0] if remaining_stage_names else None,
        )

    def save_direction_snapshot(self, run_id: str, trigger_event: str) -> DirectionSnapshot:
        snapshot = self.build_direction_snapshot(run_id, trigger_event=trigger_event)
        direction_dir = self._run_plan_dir(run_id) / "directions"
        direction_dir.mkdir(parents=True, exist_ok=True)
        json_path = direction_dir / f"direction_{snapshot.sequence:03d}.json"
        markdown_path = direction_dir / f"direction_{snapshot.sequence:03d}.md"
        latest_json = direction_dir / "latest_direction.json"
        latest_markdown = direction_dir / "latest_direction.md"

        json_text = snapshot.model_dump_json(indent=2)
        markdown_text = self._render_direction_markdown(snapshot)
        json_path.write_text(json_text, encoding="utf-8")
        markdown_path.write_text(markdown_text, encoding="utf-8")
        latest_json.write_text(json_text, encoding="utf-8")
        latest_markdown.write_text(markdown_text, encoding="utf-8")

        self.append_event(
            run_id,
            snapshot.stage,
            "direction_saved",
            f"Direction snapshot saved for {trigger_event}.",
            payload={"sequence": snapshot.sequence, "trigger_event": trigger_event},
        )
        return snapshot

    def build_checkpoint_summary(self, run_id: str) -> CheckpointSummary:
        run = self.get_run(run_id)
        workstreams = self.list_workstreams(run_id)
        completed = [item["name"] for item in workstreams if item["status"] == WorkstreamStatus.completed.value]
        in_progress = [
            item["name"]
            for item in workstreams
            if item["status"] in {WorkstreamStatus.in_progress.value, WorkstreamStatus.retry_requested.value}
        ]
        pending = [item["name"] for item in workstreams if item["status"] == WorkstreamStatus.pending.value]
        risks: list[str] = []
        recent_changes: list[str] = []

        plan_bundle = None
        if run.plan_path and Path(run.plan_path).exists():
            plan_bundle = self.load_plan_bundle(run_id)
        if plan_bundle and plan_bundle.change_log:
            recent_changes = [change.additions[0] for change in plan_bundle.change_log[-3:] if change.additions]

        for item in workstreams:
            if item["status"] == WorkstreamStatus.retry_requested.value:
                risks.extend(item["latest_feedback"])

        latest_test = self.load_latest_test_report(run_id)
        if latest_test and not latest_test.passed:
            raw = (latest_test.stderr or latest_test.stdout).strip()
            if raw:
                risks.append(raw.splitlines()[0])
        latest_stage_narrative = self.get_latest_stage_narrative(run_id)

        total = len(workstreams)
        done = len(completed)
        if run.status == RunStatus.blocked:
            overview = "감독관이 현재 게이트를 자동 승인하지 않고 실행을 멈췄습니다."
            next_step = "마지막 오류와 방향 안내를 확인한 뒤, 방향을 보강하거나 수동으로 승인할지 결정하세요."
        elif run.stage == RunStage.planning:
            overview = f"계획이 준비되었습니다. 아직 구현된 것은 없고, {total}개 워크스트림이 결정을 기다리고 있습니다."
            next_step = "계획을 승인해 첫 체크포인트를 시작하거나, 방향을 먼저 하나 더 추가하세요."
        elif run.stage == RunStage.plan_approved:
            overview = "계획 승인이 끝났고 첫 구현 체크포인트를 시작할 준비가 되었습니다."
            next_step = "파이프라인을 실행해 첫 체크포인트를 진행하세요."
        elif run.stage == RunStage.testing and run.status == RunStatus.waiting_approval:
            overview = "구현과 테스트가 모두 끝났고, 결과물이 최종 머지 승인을 기다리고 있습니다."
            next_step = "머지를 승인해 패키지를 만들거나, 패키징 전에 마지막 방향을 하나 더 추가하세요."
        elif run.stage in {RunStage.executing, RunStage.reviewing} and run.status == RunStatus.waiting_approval:
            overview = f"{total}개 중 {done}개 워크스트림이 완료되었고, 파이프라인은 체크포인트에서 검토를 기다리며 일시정지된 상태입니다."
            next_step = "체크포인트를 승인해 계속 진행하거나, 다음 단계를 조정할 방향을 추가하세요."
        elif run.status == RunStatus.failed:
            overview = "실패 한도에 도달해 실행이 중단되었습니다."
            next_step = "최신 이슈를 검토하고 필요하면 방향을 추가한 뒤, 새 실행을 만들지 결정하세요."
        else:
            overview = f"현재 실행은 {run.stage.value} 단계에 있습니다."
            next_step = "상세 상태 화면에서 현재 진행 상황을 확인하세요."

        return CheckpointSummary(
            run_id=run_id,
            stage=run.stage,
            status=run.status,
            plan_version=max(self.get_plan_version(run_id), 1),
            overview=overview,
            completed=completed,
            in_progress=in_progress,
            pending=pending,
            recent_changes=recent_changes,
            risks=risks[:3],
            next_step=next_step,
            latest_stage_name=latest_stage_narrative.stage_name if latest_stage_narrative else None,
            latest_stage_summary=latest_stage_narrative.client_summary if latest_stage_narrative else None,
        )

    def build_direction_snapshot(self, run_id: str, *, trigger_event: str) -> DirectionSnapshot:
        summary = self.build_checkpoint_summary(run_id)
        workstreams = self.list_workstreams(run_id)
        completed_count = len(summary.completed)
        total_count = len(workstreams)
        pending_preview = ", ".join(summary.pending[:3]) if summary.pending else "none"
        risks = summary.risks[:2]
        latest_stage_narrative = self.get_latest_stage_narrative(run_id)
        completed_stage = None
        client_summary = None
        artifact_highlights: list[str] = []

        if summary.stage == RunStage.planning:
            headline = "구현 방향을 시작하거나 다듬을 시점입니다"
            short_summary = (
                f"계획은 준비되었고 아직 구현된 것은 없습니다. "
                f"{total_count}개 워크스트림이 대기 중입니다."
            )
            recommendation = "범위가 맞다면 계획을 승인하고, 아니라면 코딩 시작 전에 방향을 한 번 더 추가하세요."
            options = [
                "계획을 승인하고 첫 구현 체크포인트를 시작합니다.",
                "코딩 시작 전에 범위, 스타일, 우선순위 방향을 추가합니다.",
            ]
        elif trigger_event == "stage_completed" and latest_stage_narrative is not None:
            headline = f"{latest_stage_narrative.stage_name} 단계 검토 준비가 완료되었습니다"
            short_summary = (
                f"{total_count}개 중 {completed_count}개 워크스트림이 완료되었습니다. "
                f"남은 작업: {pending_preview}."
            )
            recommendation = "쉬운 단계 요약을 읽고, 다음 단계를 시작하려면 체크포인트를 승인하세요."
            options = [
                "다음 단계를 승인해 계속 진행합니다.",
                "방금 끝난 단계에 수정이 필요하면 교정 방향을 남깁니다.",
            ]
            completed_stage = latest_stage_narrative.stage_name
            client_summary = latest_stage_narrative.client_summary
            artifact_highlights = latest_stage_narrative.artifact_highlights[:5]
        elif summary.stage in {RunStage.executing, RunStage.reviewing} and summary.status == RunStatus.waiting_approval:
            headline = "수정 사이클이 끝났고 다음 방향을 기다리고 있습니다"
            short_summary = (
                f"{total_count}개 중 {completed_count}개 워크스트림이 완료되었습니다. "
                f"남은 작업: {pending_preview}."
            )
            recommendation = "최신 체크포인트를 검토한 뒤, 다음 단계를 승인하거나 짧은 수정 방향을 남기세요."
            options = [
                "다음 체크포인트를 승인해 계속 진행합니다.",
                "다음 단계가 바뀌어야 하면 짧은 방향을 저장합니다.",
            ]
            if risks:
                options.append(f"먼저 확인할 위험: {risks[0]}")
        elif summary.stage == RunStage.testing and summary.status == RunStatus.waiting_approval:
            headline = "테스트를 통과한 빌드가 최종 결정을 기다리고 있습니다"
            short_summary = "현재 수정본은 테스트를 통과했고 패키징 직전에서 멈춰 있습니다."
            recommendation = "머지를 승인해 마무리하거나, 한 번 더 다듬고 싶다면 마지막 방향을 추가하세요."
            options = [
                "머지를 승인해 이번 실행을 완료합니다.",
                "패키징 전에 마지막 다듬기 방향을 추가합니다.",
            ]
        elif summary.status == RunStatus.failed:
            headline = "마지막 수정 사이클에 새 방향이 필요합니다"
            short_summary = "재시도 한도를 넘겼거나 안전한 재시도 대상을 찾지 못해 실행이 멈췄습니다."
            recommendation = "최신 위험을 먼저 보고, 다시 시도하기 전에 더 좁은 수정 방향을 남기세요."
            options = [
                "문제를 한 워크스트림으로 좁히는 수정 방향을 저장합니다.",
                "현재 범위를 초기화해야 하면 새 실행을 시작합니다.",
            ]
            if risks:
                options.append(f"가장 먼저 볼 위험: {risks[0]}")
        elif summary.status == RunStatus.blocked:
            headline = "감독관이 추가 확인을 요청했습니다"
            short_summary = "자동 승인 감독관이 지금 단계는 사람 확인이 더 안전하다고 판단해 실행을 멈췄습니다."
            recommendation = "마지막 오류와 방향 요약을 읽고, 방향을 보강한 뒤 수동 승인할지 결정하세요."
            options = [
                "방향 메모를 추가한 뒤 다시 검토합니다.",
                "현재 내용을 직접 확인한 뒤 수동으로 승인합니다.",
            ]
            if risks:
                options.append(f"먼저 확인할 위험: {risks[0]}")
        elif summary.stage == RunStage.completed:
            headline = "실행이 완료되었습니다"
            short_summary = "계획된 수정이 모두 패키징되었고 실행이 끝났습니다."
            recommendation = "패키징된 결과를 검토하고, 새 기능이나 추가 개선이 필요할 때만 새 실행을 시작하세요."
            options = [
                "산출물을 열어 최종 패키지를 검토합니다.",
                "다음 기능이나 개선을 위해 새 실행을 시작합니다.",
            ]
        else:
            headline = "새 방향 스냅샷이 저장되었습니다"
            short_summary = summary.overview
            recommendation = summary.next_step
            options = [summary.next_step]

        return DirectionSnapshot(
            run_id=run_id,
            sequence=self.get_direction_count(run_id) + 1,
            trigger_event=trigger_event,
            stage=summary.stage,
            status=summary.status,
            headline=headline,
            summary=short_summary,
            recommendation=recommendation,
            options=options,
            completed_stage=completed_stage,
            client_summary=client_summary,
            artifact_highlights=artifact_highlights,
        )

    def _render_direction_markdown(self, snapshot: DirectionSnapshot) -> str:
        lines = [
            f"# 방향 스냅샷 {snapshot.sequence:03d}",
            "",
            f"- 실행 ID: {snapshot.run_id}",
            f"- 트리거: {snapshot.trigger_event}",
            f"- 단계: {snapshot.stage.value}",
            f"- 상태: {snapshot.status.value}",
            f"- 생성 시각: {snapshot.created_at.isoformat()}",
            "",
            f"## {snapshot.headline}",
            snapshot.summary,
            "",
            "## 추천",
            snapshot.recommendation,
            "",
        ]
        if snapshot.completed_stage and snapshot.client_summary:
            lines.extend(
                [
                    f"## {snapshot.completed_stage} 단계에서 끝난 내용",
                    snapshot.client_summary,
                    "",
                ]
            )
            if snapshot.artifact_highlights:
                lines.append("## 하이라이트")
                for item in snapshot.artifact_highlights:
                    lines.append(f"- {item}")
                lines.append("")
        lines.append("## 선택지")
        for option in snapshot.options:
            lines.append(f"- {option}")
        return "\n".join(lines)

    def _collect_stage_artifact_highlights(self, stage_items: list[dict], limit: int = 5) -> list[str]:
        highlights: list[str] = []
        for item in stage_items:
            for path in item["changed_files"]:
                if path not in highlights:
                    highlights.append(path)
                if len(highlights) >= limit:
                    return highlights
        return highlights

    @staticmethod
    def _slugify(value: str) -> str:
        cleaned = "".join(ch.lower() if ch.isalnum() else "-" for ch in value.strip())
        while "--" in cleaned:
            cleaned = cleaned.replace("--", "-")
        return cleaned.strip("-") or "stage"

    def _render_stage_narrative_markdown(self, narrative: StageNarrative) -> str:
        lines = [
            f"# 단계 설명 {narrative.sequence:03d}",
            "",
            f"- 실행 ID: {narrative.run_id}",
            f"- 단계: {narrative.stage_name}",
            f"- 생성 시각: {narrative.created_at.isoformat()}",
            "",
            "## 기술 요약",
            narrative.summary,
            "",
            "## 쉬운 설명",
            narrative.client_summary,
            "",
            "## 완료된 워크스트림",
        ]
        if narrative.completed_workstreams:
            for item in narrative.completed_workstreams:
                lines.append(f"- {item}")
        else:
            lines.append("- 기록 없음")
        lines.extend(["", "## 산출물 하이라이트"])
        if narrative.artifact_highlights:
            for item in narrative.artifact_highlights:
                lines.append(f"- {item}")
        else:
            lines.append("- 기록 없음")
        if narrative.next_focus:
            lines.extend(["", "## 다음 초점", narrative.next_focus])
        return "\n".join(lines)

    def _render_supervisor_trace_markdown(self, trace: SupervisorTrace) -> str:
        lines = [
            f"# 감독 트레이스 {trace.sequence:03d}",
            "",
            f"- 실행 ID: {trace.run_id}",
            f"- 게이트: {trace.stage.value}",
            f"- 에이전트: {trace.agent_id}",
            f"- 판단 경로: {trace.decision_source}",
            f"- 승인 여부: {'approved' if trace.approved else 'blocked'}",
            f"- 모델: {trace.model_name}",
            f"- 지연 시간(ms): {trace.latency_ms}",
            f"- 입력 해시: {trace.input_digest}",
            f"- 생성 시각: {trace.created_at.isoformat()}",
        ]
        if trace.error_code:
            lines.append(f"- 오류 코드: {trace.error_code}")
        lines.extend(["", "## 판단 근거", trace.rationale])
        lines.extend(["", "## 위험 플래그"])
        if trace.risk_flags:
            for item in trace.risk_flags:
                lines.append(f"- {item}")
        else:
            lines.append("- 없음")
        lines.extend(["", f"## 사람 확인 필요: {'예' if trace.requires_human else '아니오'}"])
        return "\n".join(lines)

    def _render_supervisor_session_markdown(self, session: SupervisorSession) -> str:
        lines = [
            "# 감독 세션 상태",
            "",
            f"- 실행 ID: {session.run_id}",
            f"- 사용 여부: {'enabled' if session.enabled else 'disabled'}",
            f"- 상태: {session.status}",
            f"- 현재 게이트: {session.current_gate.value if session.current_gate else 'none'}",
            f"- 현재 에이전트: {session.current_agent_id or 'none'}",
            f"- 완료한 cycle: {session.cycles_completed}",
            f"- 최대 cycle: {session.max_cycles}",
            f"- 최대 계획 리비전: {session.max_plan_revisions}",
            f"- 감독 거절 수: {session.supervisor_denials}",
            f"- 연속 실패 수: {session.consecutive_failures}",
            f"- 마지막 오류 코드: {session.last_error_code or 'none'}",
            f"- 마지막 근거: {session.last_rationale or 'none'}",
            f"- 갱신 시각: {session.updated_at.isoformat()}",
            "",
            "## 게이트 반복 횟수",
        ]
        if session.same_gate_repeats:
            for gate_name, count in sorted(session.same_gate_repeats.items()):
                lines.append(f"- {gate_name}: {count}")
        else:
            lines.append("- 기록 없음")
        return "\n".join(lines)

    def _run_plan_dir(self, run: str | RunRecord) -> Path:
        run_record = self.get_run(run) if isinstance(run, str) else run
        if run_record.plan_path:
            return Path(run_record.plan_path).parent
        return self._default_plan_dir(run_record.run_id, created_at=run_record.created_at)

    def _run_output_dir(self, run: str | RunRecord) -> Path:
        run_record = self.get_run(run) if isinstance(run, str) else run
        if run_record.workspace_path:
            return Path(run_record.workspace_path).parent
        if run_record.manifest_path:
            return Path(run_record.manifest_path).parent.parent
        return self._default_output_dir(run_record.run_id, created_at=run_record.created_at)

    def _default_plan_dir(self, run_id: str, *, created_at) -> Path:
        return self._dated_root(self.settings.plans_dir, created_at) / run_id

    def _default_output_dir(self, run_id: str, *, created_at) -> Path:
        return self._dated_root(self.settings.outputs_dir, created_at) / run_id

    @staticmethod
    def _dated_root(root: Path, created_at) -> Path:
        local_time = created_at.astimezone() if getattr(created_at, "tzinfo", None) else created_at
        return root / local_time.strftime("%Y-%m-%d")

    @staticmethod
    def _entity_to_run_record(entity: RunEntity) -> RunRecord:
        return RunRecord(
            run_id=entity.run_id,
            request=UserRequest.model_validate_json(entity.request_json),
            stage=RunStage(entity.stage),
            status=RunStatus(entity.status),
            created_at=entity.created_at,
            updated_at=entity.updated_at,
            plan_path=entity.plan_path,
            workspace_path=entity.workspace_path,
            manifest_path=entity.manifest_path,
            last_error=entity.last_error,
        )
