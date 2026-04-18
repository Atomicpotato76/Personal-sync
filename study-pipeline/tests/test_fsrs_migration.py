"""test_fsrs_migration.py -- FSRS 마이그레이션 및 스케줄러 테스트."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


# ──────────────────────────────────────────────
# FSRS 활성 config fixture
# ──────────────────────────────────────────────

@pytest.fixture
def fsrs_config(config):
    c = dict(config)
    c["scheduler"] = "fsrs"
    return c


# ──────────────────────────────────────────────
# FSRS 스케줄러 기본 동작
# ──────────────────────────────────────────────

def test_fsrs_first_correct_populates_card(fsrs_config, tmp_pipeline):
    from memory_manager import MemoryManager

    mem = MemoryManager(fsrs_config)
    mem.record_result("organic_chem", ["sn2"], "correct")

    entry = mem._weak_data["organic_chem"]["sn2"]
    assert entry["fsrs_card"] is not None
    assert entry["fsrs_next_review"] is not None


def test_fsrs_wrong_resets_to_short_interval(fsrs_config, tmp_pipeline):
    from memory_manager import MemoryManager

    mem = MemoryManager(fsrs_config)
    # 여러 번 맞춰서 interval을 늘림
    for _ in range(3):
        mem.record_result("organic_chem", ["sn2"], "correct")

    entry_before = mem._weak_data["organic_chem"]["sn2"]
    due_before = datetime.fromisoformat(entry_before["fsrs_card"]["due"])

    mem.record_result("organic_chem", ["sn2"], "wrong")

    entry_after = mem._weak_data["organic_chem"]["sn2"]
    due_after = datetime.fromisoformat(entry_after["fsrs_card"]["due"])

    # wrong 후 due가 앞당겨져야 함
    assert due_after <= due_before


def test_fsrs_correct_streak_increases_interval(fsrs_config, tmp_pipeline):
    from memory_manager import MemoryManager

    mem = MemoryManager(fsrs_config)
    dates = []
    for _ in range(4):
        mem.record_result("organic_chem", ["sn2"], "correct")
        due = mem._weak_data["organic_chem"]["sn2"]["fsrs_next_review"]
        dates.append(due)

    # 날짜가 단조 증가해야 함
    assert dates == sorted(dates)


def test_fsrs_rating_override_easy(fsrs_config, tmp_pipeline):
    from memory_manager import MemoryManager

    mem_easy = MemoryManager(fsrs_config)
    mem_good = MemoryManager(fsrs_config)

    mem_easy.record_result("organic_chem", ["sn2"], "correct", rating_override="easy")
    mem_good.record_result("organic_chem", ["sn2"], "correct")

    due_easy = mem_easy._weak_data["organic_chem"]["sn2"]["fsrs_next_review"]
    due_good = mem_good._weak_data["organic_chem"]["sn2"]["fsrs_next_review"]

    # Easy는 Good보다 더 먼 미래로 스케줄
    assert due_easy >= due_good


def test_fsrs_get_due_reviews_uses_fsrs_field(fsrs_config, tmp_pipeline):
    from memory_manager import MemoryManager

    mem = MemoryManager(fsrs_config)
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    mem._weak_data = {
        "organic_chem": {
            "sn2": {
                "mastery": 0.5, "priority": "medium",
                "sr_next_review": "2099-12-31",   # SM-2는 먼 미래
                "fsrs_next_review": yesterday,     # FSRS는 어제 (due)
                "sr_interval": 1, "last_encounter": yesterday,
                "fsrs_card": None,
            }
        }
    }

    due = mem.get_due_reviews()
    assert len(due) == 1
    assert due[0]["concept"] == "sn2"


def test_sm2_get_due_reviews_uses_sr_field(config, tmp_pipeline):
    """SM-2 모드에서는 sr_next_review를 사용해야 함."""
    from memory_manager import MemoryManager

    mem = MemoryManager(config)  # scheduler: sm2 (기본)
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    mem._weak_data = {
        "organic_chem": {
            "sn2": {
                "mastery": 0.5, "priority": "medium",
                "sr_next_review": yesterday,       # SM-2는 어제
                "fsrs_next_review": "2099-12-31",  # FSRS는 먼 미래
                "sr_interval": 1, "last_encounter": yesterday,
                "fsrs_card": None,
            }
        }
    }

    due = mem.get_due_reviews()
    assert len(due) == 1


# ──────────────────────────────────────────────
# migrate_to_fsrs.py
# ──────────────────────────────────────────────

def _make_weak_data():
    return {
        "organic_chem": {
            "sn2": {
                "mastery": 0.8, "priority": "low",
                "sr_interval": 15, "sr_ease_factor": 2.7, "sr_next_review": "2026-04-20",
                "encounter_count": 10, "correct_count": 8,
                "last_encounter": "2026-04-05", "related_notes": [], "recent_mistakes": [],
                "fsrs_card": None, "fsrs_next_review": None,
            },
            "e2": {
                "mastery": 0.3, "priority": "high",
                "sr_interval": 1, "sr_ease_factor": 1.5, "sr_next_review": "2026-04-18",
                "encounter_count": 5, "correct_count": 1.5,
                "last_encounter": "2026-04-17", "related_notes": [], "recent_mistakes": [],
                "fsrs_card": None, "fsrs_next_review": None,
            },
        }
    }


def test_migration_adds_fsrs_fields(tmp_pipeline):
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
    from migrate_to_fsrs import migrate

    weak_data = _make_weak_data()
    migrated, count = migrate(weak_data, dry_run=False)

    assert count == 2
    for concept in migrated["organic_chem"].values():
        assert concept["fsrs_card"] is not None
        assert concept["fsrs_next_review"] is not None


def test_migration_preserves_due_order(tmp_pipeline):
    """마이그레이션 후 due 날짜 순서가 원래 sr_next_review와 유사해야 함."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
    from migrate_to_fsrs import migrate

    weak_data = _make_weak_data()
    migrated, _ = migrate(weak_data, dry_run=False)

    sn2_due = migrated["organic_chem"]["sn2"]["fsrs_next_review"]
    e2_due = migrated["organic_chem"]["e2"]["fsrs_next_review"]

    # sn2(sr_next_review: 2026-04-20) > e2(2026-04-18) 이므로 FSRS도 유사 순서여야 함
    assert sn2_due >= e2_due


def test_migration_skips_already_migrated(tmp_pipeline):
    """이미 fsrs_card가 있는 항목은 건너뜀."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
    from migrate_to_fsrs import migrate

    weak_data = _make_weak_data()
    weak_data["organic_chem"]["sn2"]["fsrs_card"] = {"card_id": 999, "state": 2}

    _, count = migrate(weak_data, dry_run=False)
    assert count == 1  # sn2는 건너뛰고 e2만 변환


def test_migration_high_mastery_lower_difficulty(tmp_pipeline):
    """mastery 높을수록 FSRS difficulty가 낮아야 함."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
    from migrate_to_fsrs import migrate

    weak_data = _make_weak_data()
    migrated, _ = migrate(weak_data, dry_run=False)

    sn2_diff = migrated["organic_chem"]["sn2"]["fsrs_card"]["difficulty"]  # mastery=0.8
    e2_diff = migrated["organic_chem"]["e2"]["fsrs_card"]["difficulty"]    # mastery=0.3

    assert sn2_diff < e2_diff


def test_migration_interval_monotonicity(tmp_pipeline):
    """correct 연속 시 FSRS interval이 단조 증가해야 함 (마이그레이션 후)."""
    from memory_manager import MemoryManager
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

    config = {
        "vault_path": str(tmp_pipeline),
        "notes_dir": "notes",
        "pipeline_dir": str(tmp_pipeline),
        "scripts_dir": str(tmp_pipeline),
        "folder_mapping": {},
        "subjects": {},
        "mem0": {"enabled": False},
        "llm": {},
        "scheduler": "fsrs",
    }

    mem = MemoryManager(config)
    intervals = []

    for _ in range(5):
        mem.record_result("organic_chem", ["sn2"], "correct")
        due_str = mem._weak_data["organic_chem"]["sn2"]["fsrs_next_review"]
        intervals.append(due_str)

    # due date는 단조 증가 (또는 동일)해야 함
    assert intervals == sorted(intervals)
