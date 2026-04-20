from __future__ import annotations

from pathlib import Path
import sys

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import verifier


def _config() -> dict:
    return {
        "verifier": {
            "llm_quick_scan": True,
        }
    }


class _FakeRouter:
    def __init__(self, _config: dict) -> None:
        self.config = _config

    def generate_json(self, *_args: object, **_kwargs: object) -> dict:
        return {
            "checks": {
                "pedagogy": {"pass": False, "issues": [{"problem": "extra issue"}]},
                "style_alignment": {"pass": True, "deviations": []},
                "coverage": {
                    "pass": False,
                    "required_topics": ["Lewis acid/base"],
                    "covered": [],
                    "covered_detail": [],
                    "missing": ["Lewis acid/base"],
                },
                "provenance_claims": {"pass": True, "false_claims": []},
                "provenance_tags": {"pass": True, "mistagged": []},
            },
            "score": 0,
            "verdict": "FAIL",
            "notes": "LLM augmented",
        }


def test_llm_quick_scan_preserves_deterministic_coverage_and_recalculates_score(monkeypatch) -> None:
    monkeypatch.setattr(verifier, "LLMRouter", _FakeRouter)
    monkeypatch.setattr(verifier, "VERIFIER_SYSTEM_PATH", Path(__file__))

    deterministic_result = {
        "checks": {
            "pedagogy": {"pass": True, "issues": []},
            "style_alignment": {"pass": True, "deviations": []},
            "coverage": {
                "pass": True,
                "required_topics": ["Lewis acid/base"],
                "covered": ["Lewis acid/base"],
                "covered_detail": [
                    {
                        "topic": "Lewis acid/base",
                        "method": "alias:루이스 산-염기",
                        "evidence": "루이스 산-염기",
                    }
                ],
                "missing": [],
            },
            "provenance_claims": {"pass": True, "false_claims": []},
            "provenance_tags": {"pass": True, "mistagged": []},
        },
        "score": 100,
        "verdict": "PASS",
        "fix_instructions": "- 수정 필요 없음.",
    }

    merged = verifier._run_llm_quick_scan(
        deterministic_result,
        _config(),
        note_text="루이스 산-염기 정리",
        synthesis="요약",
    )

    assert merged["checks"]["pedagogy"]["pass"] is False
    coverage = merged["checks"]["coverage"]
    assert coverage["pass"] is True
    assert coverage["covered_detail"][0]["method"].startswith("alias:")
    assert merged["score"] == 70
    assert merged["verdict"] == "FAIL"
