"""quiz 생성 guardrail 테스트."""

from __future__ import annotations

import logging
import sys
import types
from pathlib import Path


def test_save_results_creates_missing_queue_dir(tmp_path: Path) -> None:
    from generate import save_results

    queue_dir = tmp_path / "missing_queue"
    assert not queue_dir.exists()

    items = [
        {
            "type": "short_answer",
            "question": "SN1과 SN2 차이는?",
            "expected_answer_keys": ["carbocation", "stereochemistry"],
            "difficulty": "medium",
            "concept_tags": ["sn1", "sn2"],
        }
    ]

    save_results(
        items=items,
        item_id="organic_chem_test_123",
        subject="organic_chem",
        source_note="note.md",
        queue_dir=queue_dir,
        config=None,
    )

    assert queue_dir.exists()
    assert (queue_dir / "organic_chem_test_123.json").exists()
    assert (queue_dir / "organic_chem_test_123.md").exists()


def test_append_quiz_sections_fails_fast_on_queue_generation_failure(monkeypatch) -> None:
    from synthesize import append_quiz_sections

    monkeypatch.setitem(
        sys.modules,
        "textbook_quiz",
        types.SimpleNamespace(add_textbook_quiz_section=lambda synthesis, *_args, **_kwargs: synthesis),
    )
    monkeypatch.setitem(
        sys.modules,
        "generate",
        types.SimpleNamespace(process_content=lambda *_args, **_kwargs: False),
    )

    logger = logging.getLogger("test_quiz_guardrail")
    synthesis, ok = append_quiz_sections(
        synthesis="# summary",
        quiz_source_note="note.md",
        quiz_note_name="note",
        subject="organic_chem",
        sources={"note_text": "content"},
        config={},
        logger=logger,
    )

    assert synthesis == "# summary"
    assert ok is False
