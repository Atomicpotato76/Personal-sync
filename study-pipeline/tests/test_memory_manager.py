"""test_memory_manager.py -- MemoryManager 단위 테스트."""

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest


# ──────────────────────────────────────────────
# record_result: correct / wrong / partial
# ──────────────────────────────────────────────

def test_record_correct_increments_counts(config, tmp_pipeline):
    from memory_manager import MemoryManager

    mem = MemoryManager(config)
    mem.record_result("organic_chem", ["sn2"], "correct")

    data = json.loads((tmp_pipeline / "weak_concepts.json").read_text(encoding="utf-8"))
    entry = data["organic_chem"]["sn2"]
    assert entry["encounter_count"] == 1
    assert entry["correct_count"] == 1
    assert entry["mastery"] == 1.0
    assert entry["priority"] == "low"


def test_record_wrong_sets_high_priority(config, tmp_pipeline):
    from memory_manager import MemoryManager

    mem = MemoryManager(config)
    mem.record_result("organic_chem", ["sn2"], "wrong", memo="forgot mechanism")

    data = json.loads((tmp_pipeline / "weak_concepts.json").read_text(encoding="utf-8"))
    entry = data["organic_chem"]["sn2"]
    assert entry["correct_count"] == 0
    assert entry["mastery"] == 0.0
    assert entry["priority"] == "high"
    assert len(entry["recent_mistakes"]) == 1
    assert entry["recent_mistakes"][0]["memo"] == "forgot mechanism"


def test_record_partial_adds_half_credit(config, tmp_pipeline):
    from memory_manager import MemoryManager

    mem = MemoryManager(config)
    mem.record_result("organic_chem", ["sn2"], "partial")

    data = json.loads((tmp_pipeline / "weak_concepts.json").read_text(encoding="utf-8"))
    entry = data["organic_chem"]["sn2"]
    assert entry["correct_count"] == 0.5
    assert entry["mastery"] == 0.5
    assert entry["priority"] == "medium"


def test_recent_mistakes_capped_at_five(config):
    from memory_manager import MemoryManager

    mem = MemoryManager(config)
    for _ in range(7):
        mem.record_result("organic_chem", ["sn2"], "wrong")

    entry = mem._weak_data["organic_chem"]["sn2"]
    assert len(entry["recent_mistakes"]) == 5


def test_correct_does_not_append_mistake(config):
    from memory_manager import MemoryManager

    mem = MemoryManager(config)
    mem.record_result("organic_chem", ["sn2"], "correct")

    entry = mem._weak_data["organic_chem"]["sn2"]
    assert entry["recent_mistakes"] == []


# ──────────────────────────────────────────────
# SM-2 interval progression
# ──────────────────────────────────────────────

def test_sm2_first_correct_sets_interval_6(config):
    from memory_manager import MemoryManager

    mem = MemoryManager(config)
    mem.record_result("organic_chem", ["sn2"], "correct")

    entry = mem._weak_data["organic_chem"]["sn2"]
    assert entry["sr_interval"] == 6


def test_sm2_second_correct_grows_beyond_6(config):
    from memory_manager import MemoryManager

    mem = MemoryManager(config)
    mem.record_result("organic_chem", ["sn2"], "correct")
    mem.record_result("organic_chem", ["sn2"], "correct")

    entry = mem._weak_data["organic_chem"]["sn2"]
    assert entry["sr_interval"] > 6


def test_sm2_wrong_resets_interval_to_1(config):
    from memory_manager import MemoryManager

    mem = MemoryManager(config)
    mem.record_result("organic_chem", ["sn2"], "correct")
    mem.record_result("organic_chem", ["sn2"], "correct")
    mem.record_result("organic_chem", ["sn2"], "wrong")

    entry = mem._weak_data["organic_chem"]["sn2"]
    assert entry["sr_interval"] == 1


def test_sm2_partial_shrinks_interval(config):
    from memory_manager import MemoryManager

    mem = MemoryManager(config)
    # 먼저 correct 두 번으로 interval > 6 만들기
    mem.record_result("organic_chem", ["sn2"], "correct")
    mem.record_result("organic_chem", ["sn2"], "correct")
    before = mem._weak_data["organic_chem"]["sn2"]["sr_interval"]

    mem.record_result("organic_chem", ["sn2"], "partial")
    after = mem._weak_data["organic_chem"]["sn2"]["sr_interval"]

    assert after < before


def test_sm2_ease_factor_lower_bounded(config):
    from memory_manager import MemoryManager

    mem = MemoryManager(config)
    for _ in range(20):
        mem.record_result("organic_chem", ["sn2"], "wrong")

    entry = mem._weak_data["organic_chem"]["sn2"]
    assert entry["sr_ease_factor"] >= 1.3


def test_sm2_next_review_date_set(config):
    from memory_manager import MemoryManager

    mem = MemoryManager(config)
    mem.record_result("organic_chem", ["sn2"], "correct")

    entry = mem._weak_data["organic_chem"]["sn2"]
    assert entry["sr_next_review"] is not None
    # 오늘 + 6일 이어야 함
    expected = (datetime.now() + timedelta(days=6)).strftime("%Y-%m-%d")
    assert entry["sr_next_review"] == expected


# ──────────────────────────────────────────────
# get_due_reviews sorting
# ──────────────────────────────────────────────

def test_get_due_reviews_returns_overdue(config):
    from memory_manager import MemoryManager

    mem = MemoryManager(config)
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")

    mem._weak_data = {
        "organic_chem": {
            "sn2": {
                "mastery": 0.5, "priority": "medium",
                "sr_next_review": yesterday, "sr_interval": 6,
                "last_encounter": yesterday,
            },
            "e2": {
                "mastery": 0.5, "priority": "medium",
                "sr_next_review": tomorrow, "sr_interval": 6,
                "last_encounter": yesterday,
            },
        }
    }

    due = mem.get_due_reviews()
    assert len(due) == 1
    assert due[0]["concept"] == "sn2"


def test_get_due_reviews_sorted_priority_then_mastery(config):
    from memory_manager import MemoryManager

    mem = MemoryManager(config)
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    mem._weak_data = {
        "organic_chem": {
            "easy_concept": {
                "mastery": 0.9, "priority": "low",
                "sr_next_review": yesterday, "sr_interval": 30,
                "last_encounter": yesterday,
            },
            "hard_concept": {
                "mastery": 0.2, "priority": "high",
                "sr_next_review": yesterday, "sr_interval": 1,
                "last_encounter": yesterday,
            },
            "mid_concept": {
                "mastery": 0.55, "priority": "medium",
                "sr_next_review": yesterday, "sr_interval": 6,
                "last_encounter": yesterday,
            },
        }
    }

    due = mem.get_due_reviews()
    concepts = [d["concept"] for d in due]
    assert concepts.index("hard_concept") < concepts.index("mid_concept")
    assert concepts.index("mid_concept") < concepts.index("easy_concept")


# ──────────────────────────────────────────────
# _load_json: 손상 파일 격리
# ──────────────────────────────────────────────

def test_load_json_corrupt_weak_concepts_raises(config, tmp_pipeline):
    from memory_manager import MemoryManager

    corrupt = tmp_pipeline / "weak_concepts.json"
    corrupt.write_text("{invalid json", encoding="utf-8")

    with pytest.raises(RuntimeError, match="weak_concepts.json"):
        MemoryManager(config)


def test_load_json_corrupt_file_quarantined(config, tmp_pipeline):
    from memory_manager import MemoryManager

    corrupt = tmp_pipeline / "weak_concepts.json"
    corrupt.write_text("{bad}", encoding="utf-8")

    with pytest.raises(RuntimeError):
        MemoryManager(config)

    # 격리 파일이 생성되어야 함
    quarantined = list(tmp_pipeline.glob("weak_concepts.corrupt.*.json"))
    assert len(quarantined) == 1


def test_load_json_corrupt_non_critical_returns_empty(config, tmp_pipeline):
    from memory_manager import MemoryManager

    # learning_history.json이 손상된 경우: RuntimeError 없이 {} 반환
    history_path = tmp_pipeline / "cache" / "learning_history.json"
    history_path.write_text("{bad}", encoding="utf-8")

    mem = MemoryManager(config)  # 예외 없이 생성되어야 함
    assert mem._history == {}


# ──────────────────────────────────────────────
# 2.1: 인터리빙 필드
# ──────────────────────────────────────────────

def test_new_concept_has_interleaving_fields(config, tmp_pipeline):
    from memory_manager import MemoryManager

    mem = MemoryManager(config)
    mem.record_result("organic_chem", ["sn2"], "correct")
    entry = mem._weak_data["organic_chem"]["sn2"]
    assert "confusable_with" in entry
    assert entry["confusable_with"] == []
    assert "interleaving_eligible" in entry
    assert entry["interleaving_eligible"] is False


def test_interleaving_eligible_flips_after_5_encounters(config, tmp_pipeline):
    from memory_manager import MemoryManager

    mem = MemoryManager(config)
    for i in range(4):
        mem.record_result("organic_chem", ["sn2"], "correct")
    assert mem._weak_data["organic_chem"]["sn2"]["interleaving_eligible"] is False
    mem.record_result("organic_chem", ["sn2"], "correct")
    assert mem._weak_data["organic_chem"]["sn2"]["interleaving_eligible"] is True
