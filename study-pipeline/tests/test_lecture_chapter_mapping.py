"""lecture_chapters/date_range/lecture-only 동작 테스트."""

from __future__ import annotations

import logging
import sys
import types
from datetime import date
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import source_extractor
import synthesize


def test_parse_note_date_korean_and_iso_formats() -> None:
    assert source_extractor._parse_note_date("3월 10일.md", default_year=2026) == date(2026, 3, 10)
    assert source_extractor._parse_note_date("4월2일.md", default_year=2026) == date(2026, 4, 2)
    assert source_extractor._parse_note_date("2026-04-09.md") == date(2026, 4, 9)


def test_filter_notes_by_date_range() -> None:
    notes = [Path("3월 10일.md"), Path("3월 20일.md"), Path("2026-03-25.md")]
    matched = source_extractor.filter_notes_by_date_range(
        notes,
        start_date=date(2026, 3, 1),
        end_date=date(2026, 3, 15),
        default_year=2026,
    )
    assert [p.name for p in matched] == ["3월 10일.md"]


def test_synthesize_prompt_includes_required_topics_and_mode(monkeypatch) -> None:
    captured: dict[str, str] = {}

    class DummyRouter:
        def __init__(self, _config: dict):
            pass

        def _check_lmstudio(self) -> bool:
            return False

        def generate(self, prompt: str, task_type: str = "") -> str:
            captured["prompt"] = prompt
            captured["task_type"] = task_type
            return "ok"

    fake_llm_router = types.ModuleType("llm_router")
    fake_llm_router.LLMRouter = DummyRouter
    monkeypatch.setitem(sys.modules, "llm_router", fake_llm_router)

    config = {
        "subjects": {
            "organic_chem": {
                "synthesis_template": "templates/synthesis_prompt.txt",
            }
        }
    }
    sources = {
        "note_text": "",
        "textbook_text": "tb",
        "slides_text": "slides",
    }

    result = synthesize.synthesize_notes(
        sources,
        "organic_chem",
        config,
        required_topics=["Lewis acid/base", "formal charge"],
        mode="lecture_only",
    )

    assert result == "ok"
    assert "Execution mode: lecture_only" in captured["prompt"]
    assert "- Lewis acid/base" in captured["prompt"]
    assert "- formal charge" in captured["prompt"]


def test_process_chapter_switches_to_lecture_only_when_no_notes(monkeypatch, tmp_path) -> None:
    subject_dir = tmp_path / "유기화학"
    note_dir = subject_dir / "필기"
    note_dir.mkdir(parents=True)

    config = {
        "subjects": {
            "organic_chem": {
                "folder": "유기화학",
                "lecture_chapters": {
                    "ch1": {
                        "slides": "Chapter 1 - Structure and Bonding.pdf",
                        "textbook_pages": [1, 40],
                        "date_range": ["2026-03-01", "2026-03-13"],
                        "required_topics": ["hybridization"],
                    }
                },
            }
        }
    }

    class DummyAgg:
        def __init__(self, *_args, **_kwargs):
            pass

        def get_textbook_text(self, pages=None):
            return f"tb-{pages}"

        def get_textbook_images(self, pages=None):
            return []

        def get_slides_text(self, slide_filename=None):
            return f"slides-{slide_filename}"

        def get_slides_images(self, slide_filename=None):
            return []

    class DummyRouted:
        text = ""
        reason = "no-match"

    class DummyRouter:
        def __init__(self, *_args, **_kwargs):
            pass

        def extract_for_chapter(self, _text: str, _chapter: int):
            return DummyRouted()

    fake_source = types.ModuleType("source_extractor")
    fake_source.SourceAggregator = DummyAgg
    fake_source.filter_notes_by_date_range = lambda *_args, **_kwargs: []
    fake_chapter = types.ModuleType("chapter_router")
    fake_chapter.ChapterRouter = DummyRouter

    monkeypatch.setitem(sys.modules, "source_extractor", fake_source)
    monkeypatch.setitem(sys.modules, "chapter_router", fake_chapter)
    monkeypatch.setattr(synthesize, "get_subject_dir", lambda *_args, **_kwargs: subject_dir)

    mode_capture: dict[str, str] = {}

    def fake_synthesize_notes(_sources: dict, _subject: str, _config: dict, required_topics=None, mode="full"):
        mode_capture["mode"] = mode
        mode_capture["required_topics"] = ",".join(required_topics or [])
        return "content"

    monkeypatch.setattr(synthesize, "synthesize_notes", fake_synthesize_notes)
    monkeypatch.setattr(synthesize, "add_pubmed_section", lambda text, *_args, **_kwargs: text)
    monkeypatch.setattr(synthesize, "add_supplementary_explanations", lambda text, *_args, **_kwargs: text)
    monkeypatch.setattr(synthesize, "save_synthesis_md", lambda *_args, **_kwargs: tmp_path / "out.md")
    monkeypatch.setattr(synthesize, "save_synthesis_pdf", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(synthesize, "refresh_hermes_schedule", lambda *_args, **_kwargs: None)

    ok = synthesize.process_chapter("organic_chem", "ch1", config, logging.getLogger("test"))

    assert ok is True
    assert mode_capture["mode"] == "lecture_only"
    assert mode_capture["required_topics"] == "hybridization"
