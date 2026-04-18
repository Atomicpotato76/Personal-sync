from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from contracts.models import TestReport, TestResult


class TestRunnerService:
    def __init__(self, *, mode: str = "code") -> None:
        self.mode = mode

    def run(self, workspace_path: Path) -> TestReport:
        if self.mode == "research":
            return self._run_research_validation(workspace_path)
        return self._run_pytest(workspace_path)

    def _run_research_validation(self, workspace_path: Path) -> TestReport:
        """조사 결과물의 기본 품질 검증을 수행한다."""
        results: list[TestResult] = []

        md_files = list(workspace_path.rglob("*.md"))
        if not md_files:
            results.append(
                TestResult(
                    name="output_files_exist",
                    passed=False,
                    details="No markdown output files found in workspace.",
                )
            )
            return TestReport(
                passed=False,
                command="research_validation",
                results=results,
                stderr="No output files found.",
            )
        results.append(
            TestResult(
                name="output_files_exist",
                passed=True,
                details=f"Found {len(md_files)} markdown file(s).",
            )
        )

        empty_files = [f for f in md_files if f.stat().st_size < 100]
        has_content = len(empty_files) == 0
        results.append(
            TestResult(
                name="files_have_content",
                passed=has_content,
                details=f"{len(empty_files)} file(s) are nearly empty." if not has_content else "All files have content.",
            )
        )

        files_with_refs = 0
        for md_file in md_files:
            content = md_file.read_text(encoding="utf-8", errors="ignore").lower()
            if any(marker in content for marker in ["http", "source:", "reference", "doi:", "출처", "참고"]):
                files_with_refs += 1
        has_refs = files_with_refs > 0
        results.append(
            TestResult(
                name="sources_cited",
                passed=has_refs,
                details=f"{files_with_refs}/{len(md_files)} file(s) contain source references.",
            )
        )

        total_chars = sum(f.stat().st_size for f in md_files)
        min_chars = 500
        meets_length = total_chars >= min_chars
        results.append(
            TestResult(
                name="minimum_length",
                passed=meets_length,
                details=f"Total output: {total_chars} chars (minimum: {min_chars}).",
            )
        )

        passed = all(result.passed for result in results)
        return TestReport(
            passed=passed,
            command="research_validation",
            results=results,
            stdout=f"Validated {len(md_files)} file(s), {total_chars} total chars.",
            stderr="" if passed else "Some validation checks failed.",
        )

    def _run_pytest(self, workspace_path: Path) -> TestReport:
        """기존 pytest 실행 로직 (원래 코드 그대로)"""
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
