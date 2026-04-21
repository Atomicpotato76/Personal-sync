import json
from pathlib import Path

from services.testing.service import TestRunnerService


def _write_report(workspace: Path, *, contested: bool = False, with_source_id: bool = True) -> None:
    (workspace / "reports").mkdir(parents=True, exist_ok=True)
    (workspace / "research_evidence").mkdir(parents=True, exist_ok=True)
    (workspace / "reports" / "ws.md").write_text("# report\nsource: https://example.com\n" + ("data " * 200), encoding="utf-8")
    payload = {
        "workstream_id": "ws",
        "scope": "scope",
        "claims": [
            {
                "claim_id": "c1",
                "claim": "A claim",
                "source_ids": ["s1"] if with_source_id else [],
                "confidence": "high",
                "status": "contested" if contested else "supported",
                "notes": "",
            }
        ],
        "sources": [
            {
                "source_id": "s1",
                "title": "source",
                "url": "https://example.com",
                "source_type": "official",
                "tier": "primary",
            }
        ],
        "conflicts": [
            {
                "conflict_id": "x1",
                "topic": "topic",
                "source_ids": ["s1"],
                "description": "desc",
                "resolution": "",
            }
        ]
        if contested
        else [],
        "gaps": [],
        "confidence_summary": "ok",
    }
    (workspace / "research_evidence" / "ws.json").write_text(json.dumps(payload), encoding="utf-8")


def test_research_validation_passes_with_evidence_json(tmp_path: Path) -> None:
    _write_report(tmp_path)
    service = TestRunnerService(mode="research", research_require_evidence_json=True)

    report = service.run(tmp_path)

    assert report.passed is True
    names = {item.name for item in report.results}
    assert "evidence_json_exists" in names
    assert "claims_have_sources" in names


def test_research_validation_fails_when_claim_missing_source_ids(tmp_path: Path) -> None:
    _write_report(tmp_path, with_source_id=False)
    service = TestRunnerService(mode="research", research_require_evidence_json=True)

    report = service.run(tmp_path)

    assert report.passed is False
    by_name = {item.name: item for item in report.results}
    assert by_name["claims_have_sources"].passed is False
