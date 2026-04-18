from pathlib import Path
from types import SimpleNamespace

from typer.testing import CliRunner

from apps.cli import main as cli_main
from contracts.models import RunStage, RunStatus


runner = CliRunner()


def test_resolve_text_input_reads_markdown_file(tmp_path: Path) -> None:
    proposal = tmp_path / "proposal.md"
    proposal.write_text("# Proposal\n\nBuild a simple tool.\n", encoding="utf-8")

    resolved = cli_main.resolve_text_input(
        None,
        file_path=proposal,
        field_name="request",
    )

    assert resolved == "# Proposal\n\nBuild a simple tool."


def test_plan_command_accepts_request_file(monkeypatch, tmp_path: Path) -> None:
    proposal = tmp_path / "proposal.md"
    proposal.write_text("# Proposal\n\nBuild a simple tool.\n", encoding="utf-8")
    captured: dict[str, str] = {}

    class DummyOrchestrator:
        def create_plan(self, request_text: str):
            captured["request_text"] = request_text
            return SimpleNamespace(
                run_id="run-123",
                stage=RunStage.planning,
                plan_path="plans/run-123/plan_bundle.json",
            )

    monkeypatch.setattr(cli_main, "build_orchestrator", lambda: DummyOrchestrator())

    result = runner.invoke(cli_main.app, ["plan", "--request-file", str(proposal)])

    assert result.exit_code == 0
    assert "run_id=run-123" in result.stdout
    assert captured["request_text"] == "# Proposal\n\nBuild a simple tool."


def test_feedback_command_accepts_comment_file(monkeypatch, tmp_path: Path) -> None:
    direction = tmp_path / "next-direction.md"
    direction.write_text("Keep the UX simple and beginner-friendly.\n", encoding="utf-8")
    captured: dict[str, str] = {}

    class DummyMemory:
        def append_plan_addition(self, run_id: str, addition: str, *, actor: str = "local-user") -> None:
            captured["run_id"] = run_id
            captured["addition"] = addition
            captured["actor"] = actor

        def get_run(self, run_id: str):
            return SimpleNamespace(
                run_id=run_id,
                stage=RunStage.planning,
                status=RunStatus.waiting_approval,
                plan_path="plans/run-123/plan_bundle.json",
            )

    monkeypatch.setattr(cli_main, "build_memory", lambda: DummyMemory())

    result = runner.invoke(
        cli_main.app,
        ["feedback", "run-123", "--comment-file", str(direction)],
    )

    assert result.exit_code == 0
    assert "run_id=run-123" in result.stdout
    assert captured["addition"] == "Keep the UX simple and beginner-friendly."
