from __future__ import annotations

import sys
import time
from pathlib import Path

import typer

from contracts.models import ApprovalStage
from core.prompting import load_guidance_prompt
from core.secret_scanner import scan_for_secrets
from core.settings import Settings, get_settings
from core.state_machine import HermesStateMachine
from services.adapters.anthropic_adapter import AnthropicJsonAdapter
from services.adapters.openai_adapter import OpenAIJsonAdapter
from services.executor.service import ExecutorService
from services.memory.db import create_session_factory
from services.memory.service import MemoryService
from services.notifier.service import DiscordWebhookNotificationService, NullNotificationService, NotificationService
from services.orchestrator.service import HermesOrchestrator
from services.planner.service import PlannerService
from services.reviewer.service import ReviewerService
from services.supervisor.service import SupervisorService
from services.testing.service import TestRunnerService

app = typer.Typer(help="Hermes multi-agent auto-development pipeline.")


def safe_echo(message: str = "") -> None:
    try:
        typer.echo(message)
    except UnicodeEncodeError:
        encoding = sys.stdout.encoding or "utf-8"
        sanitized = message.encode(encoding, errors="replace").decode(encoding, errors="replace")
        typer.echo(sanitized)


def _read_text_input_file(path: Path, *, field_name: str) -> str:
    if not path.exists() or not path.is_file():
        raise typer.BadParameter(f"{field_name} file does not exist: {path}")
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise typer.BadParameter(f"{field_name} file must be UTF-8 text: {path}") from exc
    if not text.strip():
        raise typer.BadParameter(f"{field_name} file cannot be empty: {path}")
    return text.strip()


def resolve_text_input(
    value: str | None,
    *,
    file_path: Path | None,
    field_name: str,
    allow_existing_path_value: bool = False,
) -> str:
    if value and file_path is not None:
        raise typer.BadParameter(f"Use either {field_name} text or {field_name} file, not both.")
    if file_path is not None:
        return _read_text_input_file(file_path, field_name=field_name)
    if value is None:
        raise typer.BadParameter(f"{field_name} text or {field_name} file is required.")
    candidate = Path(value)
    if allow_existing_path_value and candidate.exists() and candidate.is_file():
        return _read_text_input_file(candidate, field_name=field_name)
    if not value.strip():
        raise typer.BadParameter(f"{field_name} cannot be empty.")
    return value.strip()


def render_status_text(memory: MemoryService, run_id: str) -> str:
    run = memory.get_run(run_id)
    summary = memory.build_checkpoint_summary(run_id)
    latest_direction = memory.get_latest_direction(run_id)
    latest_supervisor_session = memory.get_latest_supervisor_session(run_id)
    lines = [
        f"run_id={run.run_id}",
        f"stage={run.stage.value}",
        f"status={run.status.value}",
        f"plan_version=v{summary.plan_version:03d}",
    ]
    if run.last_error:
        lines.append(f"last_error={run.last_error}")
    lines.append("workstreams:")
    workstreams = memory.list_workstreams(run_id)
    if workstreams:
        for item in workstreams:
            lines.append(
                f"- {item['workstream_id']} | {item['layer']} | {item['status']} | retries={item['retry_count']}"
            )
    else:
        lines.append("- none")
    lines.append("recent_events:")
    events = list(reversed(memory.list_events(run_id, limit=10)))
    if events:
        for event in events:
            lines.append(
                f"- {event.created_at.isoformat()} | {event.stage.value} | {event.event_type} | {event.message}"
            )
    else:
        lines.append("- none")
    lines.append("plain_summary:")
    lines.append(f"- overview: {summary.overview}")
    lines.append(f"- completed: {', '.join(summary.completed) if summary.completed else 'none yet'}")
    lines.append(f"- in_progress: {', '.join(summary.in_progress) if summary.in_progress else 'none'}")
    lines.append(f"- pending: {', '.join(summary.pending) if summary.pending else 'none'}")
    lines.append(f"- recent_changes: {', '.join(summary.recent_changes) if summary.recent_changes else 'none'}")
    lines.append(f"- risks: {', '.join(summary.risks) if summary.risks else 'none'}")
    lines.append(f"- next_step: {summary.next_step}")
    lines.append(f"- latest_stage: {summary.latest_stage_name or 'none'}")
    lines.append(f"- latest_stage_summary: {summary.latest_stage_summary or 'none'}")
    lines.append("direction_guidance:")
    if latest_direction is None:
        lines.append("- none saved yet")
    else:
        lines.append(f"- headline: {latest_direction.headline}")
        lines.append(f"- summary: {latest_direction.summary}")
        lines.append(f"- recommendation: {latest_direction.recommendation}")
        lines.append(f"- options: {', '.join(latest_direction.options) if latest_direction.options else 'none'}")
        lines.append(f"- completed_stage: {latest_direction.completed_stage or 'none'}")
        lines.append(f"- client_summary: {latest_direction.client_summary or 'none'}")
        lines.append(f"- artifact_highlights: {', '.join(latest_direction.artifact_highlights) if latest_direction.artifact_highlights else 'none'}")
    lines.append("supervisor:")
    if latest_supervisor_session is None:
        lines.append("- none saved yet")
    else:
        lines.append(f"- status: {latest_supervisor_session.status}")
        lines.append(f"- current_gate: {latest_supervisor_session.current_gate.value if latest_supervisor_session.current_gate else 'none'}")
        lines.append(f"- current_agent: {latest_supervisor_session.current_agent_id or 'none'}")
        lines.append(f"- cycles_completed: {latest_supervisor_session.cycles_completed}")
        lines.append(f"- cycles_remaining: {max(latest_supervisor_session.max_cycles - latest_supervisor_session.cycles_completed, 0)}")
    return "\n".join(lines)


def build_memory(settings: Settings | None = None) -> MemoryService:
    settings = settings or get_settings()
    return MemoryService(settings=settings, session_factory=create_session_factory(settings))


def build_notifier(settings: Settings | None = None) -> NotificationService:
    settings = settings or get_settings()
    if not settings.discord_webhook_url:
        return NullNotificationService()
    return DiscordWebhookNotificationService(
        webhook_url=settings.discord_webhook_url,
        username=settings.discord_webhook_username,
    )


def build_orchestrator(settings: Settings | None = None) -> HermesOrchestrator:
    settings = settings or get_settings()
    if not settings.anthropic_api_key:
        raise typer.BadParameter("ANTHROPIC_API_KEY is required.")
    if not settings.openai_api_key:
        raise typer.BadParameter("OPENAI_API_KEY is required.")

    guidance_prompt = load_guidance_prompt(settings)
    planner_adapter = AnthropicJsonAdapter(
        api_key=settings.anthropic_api_key,
        model=settings.planner_model,
        thinking_enabled=settings.anthropic_thinking_enabled,
        thinking_type=settings.anthropic_thinking_type,
        thinking_budget_tokens=settings.anthropic_thinking_budget_tokens,
        max_output_tokens=settings.anthropic_max_output_tokens,
    )
    reviewer_adapter = AnthropicJsonAdapter(
        api_key=settings.anthropic_api_key,
        model=settings.reviewer_model,
        thinking_enabled=settings.anthropic_thinking_enabled,
        thinking_type=settings.anthropic_thinking_type,
        thinking_budget_tokens=settings.anthropic_thinking_budget_tokens,
        max_output_tokens=settings.anthropic_max_output_tokens,
    )
    executor_adapter = OpenAIJsonAdapter(api_key=settings.openai_api_key, model=settings.executor_model)

    memory = build_memory(settings)
    notifier = build_notifier(settings)
    return HermesOrchestrator(
        planner=PlannerService(
            planner_adapter,
            guidance_prompt=guidance_prompt,
            request_digest_chars=settings.planner_request_digest_chars,
            mode=settings.pipeline_mode,
        ),
        executor=ExecutorService(
            executor_adapter,
            guidance_prompt=guidance_prompt,
            mode=settings.pipeline_mode,
        ),
        reviewer=ReviewerService(
            reviewer_adapter,
            guidance_prompt=guidance_prompt,
            mode=settings.pipeline_mode,
        ),
        tester=TestRunnerService(mode=settings.pipeline_mode),
        memory=memory,
        notifier=notifier,
        state_machine=HermesStateMachine(),
        max_retries_per_workstream=settings.max_retries_per_workstream,
    )


def build_supervisor(settings: Settings | None = None) -> SupervisorService:
    settings = settings or get_settings()
    if not settings.anthropic_api_key:
        raise typer.BadParameter("ANTHROPIC_API_KEY is required.")

    guidance_prompt = load_guidance_prompt(settings)
    plan_adapter = AnthropicJsonAdapter(
        api_key=settings.anthropic_api_key,
        model=settings.supervisor_model_plan,
        thinking_enabled=settings.anthropic_thinking_enabled,
        thinking_type=settings.anthropic_thinking_type,
        thinking_budget_tokens=settings.anthropic_thinking_budget_tokens,
        max_output_tokens=settings.anthropic_max_output_tokens,
    )
    checkpoint_adapter = AnthropicJsonAdapter(
        api_key=settings.anthropic_api_key,
        model=settings.supervisor_model_checkpoint,
        thinking_enabled=settings.anthropic_thinking_enabled,
        thinking_type=settings.anthropic_thinking_type,
        thinking_budget_tokens=settings.anthropic_thinking_budget_tokens,
        max_output_tokens=settings.anthropic_max_output_tokens,
    )
    merge_adapter = AnthropicJsonAdapter(
        api_key=settings.anthropic_api_key,
        model=settings.supervisor_model_merge,
        thinking_enabled=settings.anthropic_thinking_enabled,
        thinking_type=settings.anthropic_thinking_type,
        thinking_budget_tokens=settings.anthropic_thinking_budget_tokens,
        max_output_tokens=settings.anthropic_max_output_tokens,
    )
    from services.supervisor.service import SupervisorAgent

    return SupervisorService(
        plan_agent=SupervisorAgent(
            agent_id="plan_gate_agent",
            stage=ApprovalStage.plan,
            adapter=plan_adapter,
            guidance_prompt=guidance_prompt,
        ),
        checkpoint_agent=SupervisorAgent(
            agent_id="checkpoint_gate_agent",
            stage=ApprovalStage.checkpoint,
            adapter=checkpoint_adapter,
            guidance_prompt=guidance_prompt,
        ),
        merge_agent=SupervisorAgent(
            agent_id="merge_gate_agent",
            stage=ApprovalStage.merge,
            adapter=merge_adapter,
            guidance_prompt=guidance_prompt,
        ),
    )


@app.command()
def plan(
    request: str | None = typer.Argument(
        None,
        help="Plain request text, or a path to a UTF-8 markdown/text file.",
    ),
    request_file: Path | None = typer.Option(
        None,
        "--request-file",
        help="Path to a UTF-8 markdown/text file that contains the proposal.",
    ),
) -> None:
    """Create a new run and save its plan bundle."""
    resolved_request = resolve_text_input(
        request,
        file_path=request_file,
        field_name="request",
        allow_existing_path_value=True,
    )
    orchestrator = build_orchestrator()
    run = orchestrator.create_plan(resolved_request)
    safe_echo(f"run_id={run.run_id}")
    safe_echo(f"stage={run.stage.value}")
    safe_echo(f"plan_path={run.plan_path}")


@app.command()
def approve(
    run_id: str,
    stage: ApprovalStage = typer.Option(..., "--stage"),
    actor: str = "local-user",
    comment: str | None = None,
    comment_file: Path | None = typer.Option(
        None,
        "--comment-file",
        help="Path to a UTF-8 markdown/text file that contains approval notes.",
    ),
) -> None:
    """Approve plan, checkpoint, or merge gates."""
    resolved_comment = ""
    if comment is not None or comment_file is not None:
        resolved_comment = resolve_text_input(
            comment,
            file_path=comment_file,
            field_name="comment",
            allow_existing_path_value=True,
        )
    orchestrator = build_orchestrator()
    run = orchestrator.approve(run_id, stage=stage, actor=actor, comment=resolved_comment)
    safe_echo(f"run_id={run.run_id}")
    safe_echo(f"stage={run.stage.value}")
    safe_echo(f"status={run.status.value}")


@app.command()
def feedback(
    run_id: str,
    comment: str | None = typer.Argument(
        None,
        help="Direction text, or a path to a UTF-8 markdown/text file.",
    ),
    actor: str = "local-user",
    comment_file: Path | None = typer.Option(
        None,
        "--comment-file",
        help="Path to a UTF-8 markdown/text file that contains the next direction.",
    ),
) -> None:
    """Record a new user direction without resuming execution."""
    resolved_comment = resolve_text_input(
        comment,
        file_path=comment_file,
        field_name="comment",
        allow_existing_path_value=True,
    )
    memory = build_memory()
    memory.append_plan_addition(run_id, resolved_comment, actor=actor)
    run = memory.get_run(run_id)
    safe_echo(f"run_id={run.run_id}")
    safe_echo(f"stage={run.stage.value}")
    safe_echo(f"status={run.status.value}")
    safe_echo(f"plan_path={run.plan_path}")


@app.command(name="run")
def run_command(run_id: str) -> None:
    """Advance an approved run."""
    orchestrator = build_orchestrator()
    result = orchestrator.run(run_id)
    safe_echo(f"run_id={result.run_id}")
    safe_echo(f"stage={result.stage.value}")
    safe_echo(f"status={result.status.value}")
    if result.manifest_path:
        safe_echo(f"manifest={result.manifest_path}")


@app.command()
def status(run_id: str) -> None:
    """Show current run stage, workstreams, and recent events."""
    memory = build_memory()
    safe_echo(render_status_text(memory, run_id))


@app.command()
def summary(run_id: str) -> None:
    """Show a plain-language summary for non-technical approval."""
    memory = build_memory()
    checkpoint = memory.build_checkpoint_summary(run_id)
    latest_direction = memory.get_latest_direction(run_id)
    safe_echo(f"run_id={checkpoint.run_id}")
    safe_echo(f"plan_version=v{checkpoint.plan_version:03d}")
    safe_echo(f"overview={checkpoint.overview}")
    safe_echo(f"completed={', '.join(checkpoint.completed) if checkpoint.completed else 'none yet'}")
    safe_echo(f"in_progress={', '.join(checkpoint.in_progress) if checkpoint.in_progress else 'none'}")
    safe_echo(f"pending={', '.join(checkpoint.pending) if checkpoint.pending else 'none'}")
    safe_echo(f"recent_changes={', '.join(checkpoint.recent_changes) if checkpoint.recent_changes else 'none'}")
    safe_echo(f"risks={', '.join(checkpoint.risks) if checkpoint.risks else 'none'}")
    safe_echo(f"next_step={checkpoint.next_step}")
    safe_echo(f"latest_stage={checkpoint.latest_stage_name or 'none'}")
    safe_echo(f"latest_stage_summary={checkpoint.latest_stage_summary or 'none'}")
    if latest_direction is not None:
        safe_echo(f"direction_headline={latest_direction.headline}")
        safe_echo(f"direction_summary={latest_direction.summary}")
        safe_echo(f"direction_recommendation={latest_direction.recommendation}")
        safe_echo(f"direction_options={', '.join(latest_direction.options) if latest_direction.options else 'none'}")
        safe_echo(f"direction_completed_stage={latest_direction.completed_stage or 'none'}")
        safe_echo(f"direction_client_summary={latest_direction.client_summary or 'none'}")
        safe_echo(
            f"direction_artifact_highlights={', '.join(latest_direction.artifact_highlights) if latest_direction.artifact_highlights else 'none'}"
        )


@app.command()
def directions(run_id: str) -> None:
    """Show the latest saved direction guidance."""
    memory = build_memory()
    latest_direction = memory.get_latest_direction(run_id)
    if latest_direction is None:
        safe_echo("No direction guidance has been saved for this run yet.")
        return
    safe_echo(f"run_id={latest_direction.run_id}")
    safe_echo(f"sequence={latest_direction.sequence}")
    safe_echo(f"trigger_event={latest_direction.trigger_event}")
    safe_echo(f"headline={latest_direction.headline}")
    safe_echo(f"summary={latest_direction.summary}")
    safe_echo(f"recommendation={latest_direction.recommendation}")
    safe_echo(f"options={', '.join(latest_direction.options) if latest_direction.options else 'none'}")
    safe_echo(f"completed_stage={latest_direction.completed_stage or 'none'}")
    safe_echo(f"client_summary={latest_direction.client_summary or 'none'}")
    safe_echo(f"artifact_highlights={', '.join(latest_direction.artifact_highlights) if latest_direction.artifact_highlights else 'none'}")


@app.command()
def notify(run_id: str, event: str = "manual_status") -> None:
    """Send the current run summary to Discord if webhook notifications are configured."""
    orchestrator = build_orchestrator()
    run = orchestrator.notify_status(run_id, event_name=event)
    safe_echo(f"run_id={run.run_id}")
    safe_echo(f"stage={run.stage.value}")
    safe_echo(f"status={run.status.value}")
    safe_echo(f"notified_event={event}")


@app.command()
def gui() -> None:
    """Launch the local desktop GUI."""
    from apps.gui.main import launch_gui

    settings = get_settings()

    def on_mode_change(new_mode: str) -> None:
        settings.pipeline_mode = new_mode

    launch_gui(
        orchestrator_factory=lambda: build_orchestrator(settings),
        memory_factory=lambda: build_memory(settings),
        supervisor_factory=lambda: build_supervisor(settings) if settings.supervisor_mode_enabled else None,
        initial_mode=settings.pipeline_mode,
        on_mode_change=on_mode_change,
    )


@app.command()
def supervise(
    run_id: str,
    actor: str = typer.Option("direction-supervisor", "--actor"),
    max_cycles: int | None = typer.Option(None, "--max-cycles", min=1, max=200),
) -> None:
    """Let the multi-agent supervisor keep approving and running until it stops."""
    orchestrator = build_orchestrator()
    supervisor_service = build_supervisor()
    result = orchestrator.supervise(run_id, supervisor=supervisor_service, actor=actor, max_cycles=max_cycles)
    safe_echo(f"run_id={result.run_id}")
    safe_echo(f"stage={result.stage.value}")
    safe_echo(f"status={result.status.value}")
    if result.last_error:
        safe_echo(f"last_error={result.last_error}")
    if result.manifest_path:
        safe_echo(f"manifest={result.manifest_path}")


@app.command()
def watch(
    run_id: str,
    interval: float = typer.Option(3.0, "--interval", min=1.0),
    clear_screen: bool = typer.Option(True, "--clear/--no-clear"),
) -> None:
    """Continuously print the current run summary in the terminal until you stop it."""
    memory = build_memory()
    try:
        while True:
            if clear_screen:
                typer.clear()
            safe_echo(render_status_text(memory, run_id))
            safe_echo("")
            safe_echo(f"Refreshing every {interval:.1f}s. Press Ctrl+C to stop.")
            time.sleep(interval)
    except KeyboardInterrupt:
        safe_echo("\nStopped watching.")


@app.command()
def artifacts(run_id: str) -> None:
    """Show artifact paths for a run."""
    memory = build_memory()
    run = memory.get_run(run_id)
    safe_echo(f"workspace={run.workspace_path}")
    safe_echo(f"plan={run.plan_path}")
    safe_echo(f"manifest={run.manifest_path}")
    if run.manifest_path and Path(run.manifest_path).exists():
        safe_echo(Path(run.manifest_path).read_text(encoding='utf-8'))


@app.command("doctor")
def doctor() -> None:
    """Run local safety checks for secret exposure."""
    settings = get_settings()
    findings = scan_for_secrets(settings.workspace_root)
    if findings:
        safe_echo("Potential secrets found:")
        for finding in findings:
            safe_echo(
                f"- {finding.path}:{finding.line_number} | {finding.pattern_name} | {finding.preview}"
            )
        raise typer.Exit(code=1)
    safe_echo("No secret-like values found in the workspace scan.")


def run() -> None:
    app()


if __name__ == "__main__":
    run()
