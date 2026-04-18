from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from contracts.models import TestReport, TestResult


class TestRunnerService:
    def run(self, workspace_path: Path) -> TestReport:
        tests_dir = workspace_path / "tests"
        if not tests_dir.exists():
            return TestReport(
                passed=False,
                command="pytest -q",
                results=[TestResult(name="tests_present", passed=False, details="No tests directory found.")],
                stderr="No tests directory found.",
            )

        command = [sys.executable, "-m", "pytest", "-q"]
        completed = subprocess.run(
            command,
            cwd=workspace_path,
            capture_output=True,
            text=True,
            check=False,
        )
        return TestReport(
            passed=completed.returncode == 0,
            command=" ".join(command),
            results=[
                TestResult(
                    name="pytest",
                    passed=completed.returncode == 0,
                    details=f"exit_code={completed.returncode}",
                )
            ],
            stdout=completed.stdout,
            stderr=completed.stderr,
        )
