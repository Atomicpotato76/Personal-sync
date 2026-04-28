"""Stage 4 verifier coverage and regression tests."""

from __future__ import annotations

from pathlib import Path
import sys

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import verifier
from verifier import verify_note_and_quiz


def _base_config(required_topics: list[str] | None = None) -> dict:
    return {
        "scripts_dir": str(SCRIPTS_DIR),
        "verifier": {
            "topic_aliases_file": "templates/topic_aliases.yaml",
            "required_topics": {
                "organic_chem": required_topics or ["Lewis acid/base", "formal charge", "hybridization"]
            },
        },
    }


def _config() -> dict:
    return {
        "verifier": {
            "coverage_threshold": 0.7,
            "llm_quick_scan": False,
            "required_topics": {
                "organic_chem": [
                    "hybridization",
                    "pKa",
                    "Lewis acid/base",
                    "formal charge",
                ]
            },
        },
        "subjects": {"organic_chem": {}},
    }


def test_case1_substring_still_passes() -> None:
    result = verifier.check_coverage(
        note_text="Lewis acid/base 개념을 정리했고 formal charge 도 계산했다.",
        synthesis="",
        config=_base_config(required_topics=["Lewis acid/base", "formal charge"]),
        subject="organic_chem",
    )

    coverage = result
    assert coverage["pass"] is True
    assert {item["method"] for item in coverage["covered_detail"]} == {"substring"}


def test_case2_missing_topic_still_missing() -> None:
    result = verifier.check_coverage(
        note_text="결합 길이 이야기만 정리함",
        synthesis="",
        config=_base_config(required_topics=["Lewis acid/base"]),
        subject="organic_chem",
    )

    coverage = result
    assert coverage["pass"] is False
    assert coverage["missing"] == ["Lewis acid/base"]


def test_case3_mixed_substring_and_missing_unchanged() -> None:
    result = verifier.check_coverage(
        note_text="formal charge는 다뤘다.",
        synthesis="",
        config=_base_config(required_topics=["formal charge", "hybridization"]),
        subject="organic_chem",
    )

    coverage = result
    assert coverage["pass"] is False
    assert coverage["covered_detail"][0]["topic"] == "formal charge"
    assert coverage["covered_detail"][0]["method"] == "substring"
    assert coverage["missing"] == ["hybridization"]


def test_alias_matching_korean_for_lewis_acid_base() -> None:
    result = verifier.check_coverage(
        note_text="루이스 산-염기 개념을 예시와 함께 설명했다.",
        synthesis="",
        config=_base_config(required_topics=["Lewis acid/base"]),
        subject="organic_chem",
    )

    covered = result["covered_detail"]
    assert result["pass"] is True
    assert covered[0]["method"].startswith("alias:")
    assert "루이스" in covered[0]["method"]


def test_coverage_runs_layer1_layer2_only() -> None:
    result = verifier.check_coverage(
        note_text="formal charge만 정리함",
        synthesis="",
        config=_base_config(required_topics=["formal charge", "hybridization"]),
        subject="organic_chem",
    )

    assert result["missing"] == ["hybridization"]


def test_case1_detects_lone_pair_bonding_confusion() -> None:
    synthesis = "산소의 두 lone pair 중 하나씩이 각 탄소와 결합을 형성한다."
    result = verify_note_and_quiz("hybridization pKa", synthesis, _config(), "organic_chem")
    assert result["checks"]["pedagogy"]["pass"] is False
    assert any("lone pair" in issue["text"].lower() for issue in result["checks"]["pedagogy"]["issues"])


def test_case2_detects_style_alignment_deviation() -> None:
    synthesis = "반응은 에너지가 높은 상태에서 낮은 상태로 자발적으로 진행된다."
    result = verify_note_and_quiz("hybridization pKa", synthesis, _config(), "organic_chem")
    assert result["checks"]["style_alignment"]["pass"] is False
    assert result["checks"]["style_alignment"]["deviations"]


def test_case3_reports_missing_required_topics() -> None:
    note = "이번 노트는 hybridization과 pKa 중심으로 정리했다."
    synthesis = "hybridization과 pKa 문제를 만든다."
    result = verify_note_and_quiz(note, synthesis, _config(), "organic_chem")
    coverage = result["checks"]["coverage"]
    assert coverage["pass"] is False
    assert "Lewis acid/base" in coverage["missing"]
    assert "formal charge" in coverage["missing"]
