from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from contracts.models import ResearchReport, TestReport, TestResult


class TestRunnerService:
    def __init__(self, *, mode: str = "code", research_require_evidence_json: bool = True) -> None:
        self.mode = mode
        self.research_require_evidence_json = research_require_evidence_json

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

        evidence_paths = sorted((workspace_path / "research_evidence").glob("*.json"))
        evidence_required = self.research_require_evidence_json
        results.append(
            TestResult(
                name="evidence_json_exists",
                passed=bool(evidence_paths) if evidence_required else True,
                details=f"Found {len(evidence_paths)} evidence JSON file(s).",
            )
        )

        evidence_reports: list[ResearchReport] = []
        evidence_errors: list[str] = []
        for evidence_path in evidence_paths:
            try:
                payload = json.loads(evidence_path.read_text(encoding="utf-8"))
                evidence_reports.append(ResearchReport.model_validate(payload))
            except Exception as exc:  # noqa: BLE001
                evidence_errors.append(f"{evidence_path.name}: {exc}")
        results.append(
            TestResult(
                name="evidence_json_valid",
                passed=len(evidence_errors) == 0,
                details="; ".join(evidence_errors) if evidence_errors else "All evidence JSON parsed as ResearchReport.",
            )
        )

        all_claims = [claim for report in evidence_reports for claim in report.claims]
        results.append(
            TestResult(
                name="claims_have_sources",
                passed=all(len(claim.source_ids) > 0 for claim in all_claims),
                details=f"Validated {len(all_claims)} claim(s).",
            )
        )

        unresolved_claim_sources: list[str] = []
        for report in evidence_reports:
            source_ids = {source.source_id for source in report.sources}
            for claim in report.claims:
                missing = [source_id for source_id in claim.source_ids if source_id not in source_ids]
                if missing:
                    unresolved_claim_sources.append(f"{report.workstream_id}:{claim.claim_id}:{','.join(missing)}")
        results.append(
            TestResult(
                name="claim_sources_resolve",
                passed=len(unresolved_claim_sources) == 0,
                details="; ".join(unresolved_claim_sources) if unresolved_claim_sources else "All claim source_ids resolved.",
            )
        )

        missing_identifiers: list[str] = []
        missing_source_metadata: list[str] = []
        for report in evidence_reports:
            for source in report.sources:
                if not any([source.url, source.doi, source.pmid, source.accession]):
                    missing_identifiers.append(f"{report.workstream_id}:{source.source_id}")
                if not source.source_type.strip() or not source.tier.strip():
                    missing_source_metadata.append(f"{report.workstream_id}:{source.source_id}")
        results.append(
            TestResult(
                name="sources_have_identifiers",
                passed=len(missing_identifiers) == 0 and len(missing_source_metadata) == 0,
                details=(
                    f"missing_identifiers={missing_identifiers}; missing_type_or_tier={missing_source_metadata}"
                    if missing_identifiers or missing_source_metadata
                    else "All sources include identifiers, source_type, and tier."
                ),
            )
        )

        contested_without_conflict: list[str] = []
        for report in evidence_reports:
            has_contested_claim = any(claim.status == "contested" for claim in report.claims)
            if has_contested_claim and not report.conflicts:
                contested_without_conflict.append(report.workstream_id)
        results.append(
            TestResult(
                name="conflicts_recorded_or_declared_absent",
                passed=len(contested_without_conflict) == 0,
                details=(
                    "Contested claims with no conflicts: " + ", ".join(contested_without_conflict)
                    if contested_without_conflict
                    else "Conflicts recorded or no contested claims present."
                ),
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
