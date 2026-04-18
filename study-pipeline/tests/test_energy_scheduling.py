"""test_energy_scheduling.py -- Phase 3.3 에너지 매칭 스케줄링 테스트."""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from agents.hermes_agent import HermesAgent
from hermes_store import HermesStore


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def base_config(tmp_path):
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
        "interleaving_mode": "off",
        "energy_profile": {
            "09:00": "high",
            "14:00": "low",
            "20:00": "medium",
        },
    }


def _make_task(priority: str, score: int, subject: str = "organic_chem") -> dict:
    return {
        "subject": subject,
        "title": f"task_{priority}_{score}",
        "category": "weak_concept",
        "priority": priority,
        "score": score,
        "reason": "test",
        "focus": [f"concept_{priority}"],
        "recommended_blocks": 1,
        "unit_index": 1,
    }


# ── _lookup_energy ─────────────────────────────────────────────────────────────

def test_lookup_energy_exact_match(base_config):
    store = HermesStore(base_config)
    ep = base_config["energy_profile"]
    assert store._lookup_energy("09:00", ep) == "high"
    assert store._lookup_energy("14:00", ep) == "low"
    assert store._lookup_energy("20:00", ep) == "medium"


def test_lookup_energy_closest_time(base_config):
    store = HermesStore(base_config)
    ep = base_config["energy_profile"]
    # 10:00 → 09:00과 가장 가까움 → high
    assert store._lookup_energy("10:00", ep) == "high"
    # 19:30 → 20:00과 가장 가까움 → medium
    assert store._lookup_energy("19:30", ep) == "medium"
    # 15:00 → 14:00과 가장 가까움 → low
    assert store._lookup_energy("15:00", ep) == "low"


def test_lookup_energy_empty_profile(base_config):
    store = HermesStore(base_config)
    assert store._lookup_energy("10:00", {}) == "medium"
    assert store._lookup_energy("", {"09:00": "high"}) == "medium"


# ── get_daily_windows energy 필드 ─────────────────────────────────────────────

def test_get_daily_windows_has_energy_field(base_config):
    store = HermesStore(base_config)
    from datetime import date
    # 주말 사용 (10:00, 15:00, 20:00 윈도우)
    saturday = date(2026, 4, 18)
    windows = store.get_daily_windows(saturday)
    assert all("energy" in w for w in windows)


def test_get_daily_windows_no_profile_no_energy(base_config):
    cfg = dict(base_config)
    cfg.pop("energy_profile")
    store = HermesStore(cfg)
    from datetime import date
    saturday = date(2026, 4, 18)
    windows = store.get_daily_windows(saturday)
    # energy_profile 없으면 energy 필드 없어도 무방 (원본 반환)
    assert isinstance(windows, list)


# ── _pick_task energy 매칭 ────────────────────────────────────────────────────

def test_pick_task_high_energy_prefers_hard(base_config):
    """high energy 슬롯에서는 priority=high (어려운) 태스크가 먼저 선택되어야 한다."""
    agent = HermesAgent(base_config)

    task_easy = _make_task("low", score=90)    # 점수 높지만 쉬운 복습
    task_hard = _make_task("high", score=70)   # 점수 낮지만 어려운 개념

    task_units = [task_easy, task_hard]
    counts: dict = {}
    chosen = agent._pick_task(task_units, counts, 3, slot_energy="high")
    assert chosen is not None
    assert chosen["priority"] == "high", "high energy 슬롯은 어려운 개념(priority=high)을 우선 선택해야 함"


def test_pick_task_low_energy_prefers_easy(base_config):
    """low energy 슬롯에서는 priority=low (쉬운 복습) 태스크가 먼저 선택되어야 한다."""
    agent = HermesAgent(base_config)

    task_hard = _make_task("high", score=90)   # 점수 높지만 어려운 개념
    task_easy = _make_task("low", score=70)    # 점수 낮지만 쉬운 복습

    task_units = [task_hard, task_easy]
    counts: dict = {}
    chosen = agent._pick_task(task_units, counts, 3, slot_energy="low")
    assert chosen is not None
    assert chosen["priority"] == "low", "low energy 슬롯은 쉬운 복습(priority=low)을 우선 선택해야 함"


def test_pick_task_medium_energy_score_based(base_config):
    """medium energy 슬롯에서는 score 가장 높은 태스크가 선택되어야 한다."""
    agent = HermesAgent(base_config)

    task_low_score = _make_task("high", score=50)
    task_high_score = _make_task("low", score=100)

    task_units = [task_low_score, task_high_score]
    counts: dict = {}
    chosen = agent._pick_task(task_units, counts, 3, slot_energy="medium")
    assert chosen is not None
    assert chosen["score"] == 100, "medium energy 슬롯은 score 기준 정렬이어야 함"


def test_pick_task_high_energy_large_energy_bonus_overrides_score(base_config):
    """에너지 보너스(+40)가 score 차이를 극복해야 한다."""
    agent = HermesAgent(base_config)

    # easy task: score=100, energy bonus on high slot = prio_num=2, bonus=(2-2)*20=0
    task_easy = _make_task("low", score=100)
    # hard task: score=50, energy bonus on high slot = prio_num=0, bonus=(2-0)*20=40 → effective=90
    task_hard = _make_task("high", score=50)

    task_units = [task_easy, task_hard]
    counts: dict = {}
    chosen = agent._pick_task(task_units, counts, 3, slot_energy="high")
    # 100+0=100 vs 50+40=90 → easy wins (100 > 90)
    # 하지만 hard task에 energy bonus=40이 붙으면 50+40=90 vs 100+0=100 → 여전히 easy
    # 테스트 목적: easy가 50점 이하일 때 hard 선택
    task_easy2 = _make_task("low", score=80)
    task_hard2 = _make_task("high", score=50)
    task_units2 = [task_easy2, task_hard2]
    chosen2 = agent._pick_task(task_units2, counts, 3, slot_energy="high")
    # 80+0=80 vs 50+40=90 → hard wins
    assert chosen2["priority"] == "high"


def test_block_has_energy_field_in_plan(base_config):
    """생성된 계획 블록에 energy 필드가 포함되어야 한다."""
    from datetime import date
    import json

    # weak_concepts.json 생성
    pipeline_dir = Path(base_config["pipeline_dir"])
    pipeline_dir.mkdir(parents=True, exist_ok=True)
    weak = {
        "organic_chem": {
            "sn2": {
                "encounter_count": 3,
                "correct_count": 1,
                "last_encounter": "2026-04-01T10:00:00",
                "mastery": 0.3,
                "priority": "high",
                "related_notes": [],
                "recent_mistakes": [],
                "sr_interval": 1,
                "sr_ease_factor": 2.5,
                "sr_next_review": "2026-04-01",
                "fsrs_card": None,
                "fsrs_next_review": None,
                "confusable_with": [],
                "interleaving_eligible": False,
                "cross_linked_concepts": [],
                "weighted_score": 1.0,
                "weighted_total": 3.0,
            }
        }
    }
    (pipeline_dir / "weak_concepts.json").write_text(
        json.dumps(weak, ensure_ascii=False), encoding="utf-8"
    )
    (pipeline_dir / "cache").mkdir(exist_ok=True)

    agent = HermesAgent(base_config)
    plan = agent.plan_day("2026-04-19")  # 일요일 (weekend)
    for block in plan.get("blocks", []):
        assert "energy" in block, "블록에 energy 필드가 있어야 함"
