"""test_exam_postmortem.py -- Phase 3.4 시험 사후 분석 테스트."""

import json
import sys
from datetime import datetime
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from memory_manager import MemoryManager


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def config(tmp_path):
    (tmp_path / "cache").mkdir()
    return {
        "vault_path": str(tmp_path),
        "notes_dir": "notes",
        "pipeline_dir": str(tmp_path),
        "scripts_dir": str(tmp_path),
        "folder_mapping": {"유기화학": "organic_chem"},
        "subjects": {"organic_chem": {"folder": "유기화학"}},
        "mem0": {"enabled": False},
        "llm": {},
        "output": {"md": {"vault_inject": False}},
    }


def _record_events(mem: MemoryManager, events: list[dict]) -> None:
    """테스트용 이벤트를 history에 직접 삽입."""
    if "events" not in mem._history:
        mem._history["events"] = []
    for ev in events:
        mem._history["events"].append(ev)
    mem._save_json(mem.history_path, mem._history)


def _make_exam_event(
    subject: str,
    concepts: list[str],
    result: str = "wrong",
    error_category: str | None = None,
    record_source: str = "exam",
) -> dict:
    return {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "subject": subject,
        "concepts": concepts,
        "result": result,
        "source": "",
        "confidence": None,
        "error_category": error_category,
        "record_source": record_source,
        "record_weight": 2.0 if record_source == "exam" else 1.0,
    }


# ── get_postmortem_summary 기본 동작 ──────────────────────────────────────────

def test_postmortem_empty_when_no_exam_events(config):
    """시험 이벤트가 없으면 빈 결과를 반환해야 한다."""
    mem = MemoryManager(config)
    # quiz 이벤트만 추가
    mem.record_result("organic_chem", ["sn2"], "wrong", source="quiz")
    summary = mem.get_postmortem_summary("organic_chem")
    assert summary["total_exam_events"] == 0
    assert summary["top_weak"] == []


def test_postmortem_only_exam_sources_counted(config):
    """record_source=exam 및 mock_exam만 집계되어야 한다."""
    mem = MemoryManager(config)
    events = [
        _make_exam_event("organic_chem", ["sn2"], "wrong", record_source="exam"),
        _make_exam_event("organic_chem", ["sn1"], "wrong", record_source="mock_exam"),
        _make_exam_event("organic_chem", ["elimination"], "wrong", record_source="quiz"),  # 제외
    ]
    _record_events(mem, events)
    summary = mem.get_postmortem_summary("organic_chem")
    assert summary["total_exam_events"] == 2


def test_postmortem_top_weak_sorted_by_lowest_avg(config):
    """top_weak은 시험 평균 정답률이 낮은 순으로 정렬되어야 한다."""
    mem = MemoryManager(config)
    events = [
        _make_exam_event("organic_chem", ["sn2"], "correct", record_source="exam"),  # avg=1.0
        _make_exam_event("organic_chem", ["elimination"], "wrong", record_source="exam"),  # avg=0.0
        _make_exam_event("organic_chem", ["sn1"], "partial", record_source="exam"),  # avg=0.5
    ]
    _record_events(mem, events)
    summary = mem.get_postmortem_summary("organic_chem")
    top = summary["top_weak"]
    # 낮은 정답률 순: elimination(0.0) → sn1(0.5) → sn2(1.0)
    assert top[0] == "elimination"
    assert top[1] == "sn1"
    assert top[2] == "sn2"


def test_postmortem_top_weak_max_5(config):
    """top_weak은 최대 5개만 반환해야 한다."""
    mem = MemoryManager(config)
    concepts = ["a", "b", "c", "d", "e", "f", "g"]
    events = [
        _make_exam_event("organic_chem", [c], "wrong", record_source="exam")
        for c in concepts
    ]
    _record_events(mem, events)
    summary = mem.get_postmortem_summary("organic_chem")
    assert len(summary["top_weak"]) <= 5


def test_postmortem_error_distribution(config):
    """error_category 분포가 올바르게 집계되어야 한다."""
    mem = MemoryManager(config)
    events = [
        _make_exam_event("organic_chem", ["sn2"], "wrong", "knowledge_gap", "exam"),
        _make_exam_event("organic_chem", ["sn2"], "wrong", "confusion", "exam"),
        _make_exam_event("organic_chem", ["sn2"], "wrong", "confusion", "exam"),
        _make_exam_event("organic_chem", ["sn2"], "wrong", "careless", "exam"),
    ]
    _record_events(mem, events)
    summary = mem.get_postmortem_summary("organic_chem")
    dist = summary["error_distribution"]
    assert dist["knowledge_gap"] == 1
    assert dist["confusion"] == 2
    assert dist["careless"] == 1
    assert dist["misread"] == 0


def test_postmortem_subject_isolation(config):
    """다른 과목의 시험 이벤트는 집계에 포함되지 않아야 한다."""
    mem = MemoryManager(config)
    events = [
        _make_exam_event("organic_chem", ["sn2"], "wrong", record_source="exam"),
        _make_exam_event("genomics_ai", ["snp"], "wrong", record_source="exam"),
    ]
    _record_events(mem, events)
    summary = mem.get_postmortem_summary("organic_chem")
    assert summary["total_exam_events"] == 1
    assert "snp" not in summary["top_weak"]


def test_postmortem_recommended_focus_has_mastery(config):
    """recommended_focus 항목에 current_mastery 필드가 있어야 한다."""
    mem = MemoryManager(config)
    # 먼저 quiz로 마스터리 생성
    mem.record_result("organic_chem", ["sn2"], "correct", source="quiz")
    mem.record_result("organic_chem", ["sn2"], "correct", source="quiz")
    # 시험에서 틀림
    events = [_make_exam_event("organic_chem", ["sn2"], "wrong", record_source="exam")]
    _record_events(mem, events)

    summary = mem.get_postmortem_summary("organic_chem")
    assert len(summary["recommended_focus"]) > 0
    item = summary["recommended_focus"][0]
    assert "concept" in item
    assert "exam_avg" in item
    assert "current_mastery" in item
    assert item["current_mastery"] > 0  # quiz에서 쌓인 마스터리 반영


def test_postmortem_exam_name_preserved(config):
    """exam_name 파라미터가 결과에 보존되어야 한다."""
    mem = MemoryManager(config)
    summary = mem.get_postmortem_summary("organic_chem", exam_name="중간고사")
    assert summary["exam_name"] == "중간고사"


def test_postmortem_via_record_result(config):
    """record_result(source='exam') 호출로 쌓인 이벤트가 집계되어야 한다."""
    mem = MemoryManager(config)
    mem.record_result(
        "organic_chem",
        ["elimination"],
        "wrong",
        error_category="knowledge_gap",
        source="exam",
    )
    mem2 = MemoryManager(config)  # reload
    summary = mem2.get_postmortem_summary("organic_chem")
    assert summary["total_exam_events"] == 1
    assert "elimination" in summary["top_weak"]
