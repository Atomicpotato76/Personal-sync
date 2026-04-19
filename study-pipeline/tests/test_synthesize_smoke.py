"""synthesize smoke_mode/provenance 후처리 테스트."""

from pathlib import Path
import sys

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from synthesize import (
    enforce_provenance_and_emphasis,
    remove_unverified_user_state,
    split_smoke_mode_sections,
)


def _config(smoke_mode: bool = False) -> dict:
    return {
        "output": {
            "smoke_mode": smoke_mode,
            "emphasis_levels": {
                "S": "★★★",
                "D": "★★",
                "E": "★",
                "default": "★★",
            }
        }
    }


def test_remove_unverified_user_state_filters_mastery_lines() -> None:
    text = """개념 정리 [S] ★★★
mastery: 100%
- next_review: 2026-04-20
본문 유지 [D] ★★"""
    cleaned = remove_unverified_user_state(text)
    assert "mastery" not in cleaned.lower()
    assert "next_review" not in cleaned.lower()
    assert "본문 유지" in cleaned


def test_enforce_provenance_and_emphasis_appends_default_on_plain_paragraph() -> None:
    text = """## 제목

태그 없는 본문 문단"""
    tagged = enforce_provenance_and_emphasis(text, _config())
    assert "태그 없는 본문 문단 [S] ★★" in tagged


def test_split_smoke_mode_sections_keeps_d_in_main_and_e_in_enrichment() -> None:
    content = """A 문단 [S] ★★★

B 문단 [D] ★★

C 문단 [E] ★"""
    main, enrichment = split_smoke_mode_sections(content)

    assert "A 문단 [S] ★★★" in main
    assert "## 심화 해설" in main
    assert "B 문단 [D] ★★" in main
    assert "C 문단 [E] ★" not in main

    assert "## Enrichment" in enrichment
    assert "C 문단 [E] ★" in enrichment
