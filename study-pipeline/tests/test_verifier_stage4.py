"""Stage 4 verifier 재현 테스트 (Case 1/2/3)."""

from __future__ import annotations

from pathlib import Path
import sys

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from verifier import verify_note_and_quiz


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
