"""test_quiz_store.py -- quiz_store.py 단위 테스트."""

import json
from pathlib import Path

import pytest


def _make_quiz(queue_dir: Path, quiz_id: str, subject: str = "organic_chem") -> dict:
    """테스트용 퀴즈 파일(.json + .md)을 queue 디렉토리에 생성."""
    data = {
        "id": quiz_id,
        "subject": subject,
        "source_note": "test.md",
        "items": [
            {
                "type": "short_answer",
                "difficulty": "medium",
                "question": "SN2 반응의 특징은?",
                "expected_answer_keys": ["backside attack", "inversion"],
                "concept_tags": ["sn2"],
            }
        ],
    }
    (queue_dir / f"{quiz_id}.json").write_text(
        json.dumps(data, ensure_ascii=False), encoding="utf-8"
    )
    (queue_dir / f"{quiz_id}.md").write_text("# Quiz\n\nQ: SN2?", encoding="utf-8")
    return data


# ──────────────────────────────────────────────
# approve_quiz: 파일 이동
# ──────────────────────────────────────────────

def test_approve_quiz_moves_json_and_md(config, tmp_pipeline):
    from quiz_store import approve_quiz

    queue = tmp_pipeline / "queue"
    approved = tmp_pipeline / "approved"
    _make_quiz(queue, "q001")

    result = approve_quiz(config, "q001")

    assert result is not None
    assert (approved / "q001.json").exists()
    assert (approved / "q001.md").exists()
    assert not (queue / "q001.json").exists()
    assert not (queue / "q001.md").exists()


def test_approve_quiz_sets_status_approved(config, tmp_pipeline):
    from quiz_store import approve_quiz

    queue = tmp_pipeline / "queue"
    _make_quiz(queue, "q002")

    result = approve_quiz(config, "q002")
    data = json.loads(result.read_text(encoding="utf-8"))

    assert data["status"] == "approved"


def test_approve_quiz_preserves_items(config, tmp_pipeline):
    from quiz_store import approve_quiz

    queue = tmp_pipeline / "queue"
    original = _make_quiz(queue, "q003")
    result = approve_quiz(config, "q003")
    saved = json.loads(result.read_text(encoding="utf-8"))

    assert saved["items"] == original["items"]
    assert saved["subject"] == original["subject"]


# ──────────────────────────────────────────────
# approve_quiz: idempotency
# ──────────────────────────────────────────────

def test_approve_quiz_idempotent(config, tmp_pipeline):
    """이미 approved 상태인 퀴즈를 다시 approve하면 None 반환."""
    from quiz_store import approve_quiz

    queue = tmp_pipeline / "queue"
    _make_quiz(queue, "q004")

    approve_quiz(config, "q004")       # 첫 번째 호출
    result = approve_quiz(config, "q004")  # 두 번째 호출

    assert result is None


def test_approve_quiz_missing_returns_none(config, tmp_pipeline):
    from quiz_store import approve_quiz

    result = approve_quiz(config, "nonexistent_id")
    assert result is None


# ──────────────────────────────────────────────
# load_quiz_json
# ──────────────────────────────────────────────

def test_load_quiz_json_valid(tmp_pipeline):
    from quiz_store import load_quiz_json

    path = tmp_pipeline / "valid.json"
    path.write_text('{"id": "q1", "items": []}', encoding="utf-8")

    data = load_quiz_json(path)
    assert data["id"] == "q1"


def test_load_quiz_json_invalid_returns_none(tmp_pipeline):
    from quiz_store import load_quiz_json

    path = tmp_pipeline / "bad.json"
    path.write_text("{invalid json", encoding="utf-8")

    assert load_quiz_json(path) is None


def test_load_quiz_json_missing_returns_none(tmp_pipeline):
    from quiz_store import load_quiz_json

    path = tmp_pipeline / "missing.json"
    assert load_quiz_json(path) is None


# ──────────────────────────────────────────────
# find_quiz_json
# ──────────────────────────────────────────────

def test_find_quiz_json_in_queue(config, tmp_pipeline):
    from quiz_store import find_quiz_json

    queue = tmp_pipeline / "queue"
    _make_quiz(queue, "q_find")

    result = find_quiz_json(config, "q_find")
    assert result is not None
    assert result.name == "q_find.json"


def test_find_quiz_json_in_approved(config, tmp_pipeline):
    from quiz_store import approve_quiz, find_quiz_json

    queue = tmp_pipeline / "queue"
    _make_quiz(queue, "q_approved")
    approve_quiz(config, "q_approved")

    result = find_quiz_json(config, "q_approved")
    assert result is not None
    assert "approved" in str(result)


def test_find_quiz_json_not_found(config, tmp_pipeline):
    from quiz_store import find_quiz_json

    result = find_quiz_json(config, "no_such_quiz")
    assert result is None
