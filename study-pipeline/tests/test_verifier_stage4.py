<<<<<<< HEAD
"""Stage 4 verifier coverage tests (substring/alias/semantic)."""
=======
"""Stage 4 verifier 재현 테스트 (Case 1/2/3)."""
>>>>>>> origin/main

from __future__ import annotations

from pathlib import Path
import sys

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

<<<<<<< HEAD
import verifier


def _base_config(semantic_matching: bool = True) -> dict:
    return {
        "scripts_dir": str(SCRIPTS_DIR),
        "verifier": {
            "semantic_matching": semantic_matching,
            "semantic_threshold": 0.75,
            "topic_aliases_file": "templates/topic_aliases.yaml",
        },
        "mem0": {
            "vector_store": {"mode": "local"},
            "embedder": {
                "model": "text-embedding-nomic-embed-text-v1.5",
                "base_url": "http://localhost:1234/v1",
                "api_key": "lm-studio",
            },
        },
    }


def test_case1_substring_still_passes() -> None:
    result = verifier.check_coverage(
        note_text="Lewis acid/base 개념을 정리했고 formal charge 도 계산했다.",
        synthesis="",
        required_topics=["Lewis acid/base", "formal charge"],
        config=_base_config(semantic_matching=False),
    )

    coverage = result["coverage"]
    assert coverage["pass"] is True
    assert {item["method"] for item in coverage["covered"]} == {"substring"}


def test_case2_missing_topic_still_missing() -> None:
    result = verifier.check_coverage(
        note_text="결합 길이 이야기만 정리함",
        synthesis="",
        required_topics=["Lewis acid/base"],
        config=_base_config(semantic_matching=False),
    )

    coverage = result["coverage"]
    assert coverage["pass"] is False
    assert coverage["missing"] == ["Lewis acid/base"]


def test_case3_mixed_substring_and_missing_unchanged() -> None:
    result = verifier.check_coverage(
        note_text="formal charge는 다뤘다.",
        synthesis="",
        required_topics=["formal charge", "hybridization"],
        config=_base_config(semantic_matching=False),
    )

    coverage = result["coverage"]
    assert coverage["pass"] is False
    assert coverage["covered"][0]["topic"] == "formal charge"
    assert coverage["covered"][0]["method"] == "substring"
    assert coverage["missing"] == ["hybridization"]


def test_alias_matching_korean_for_lewis_acid_base() -> None:
    result = verifier.check_coverage(
        note_text="루이스 산-염기 개념을 예시와 함께 설명했다.",
        synthesis="",
        required_topics=["Lewis acid/base"],
        config=_base_config(semantic_matching=False),
    )

    covered = result["coverage"]["covered"]
    assert result["coverage"]["pass"] is True
    assert covered[0]["method"].startswith("alias:")
    assert "루이스" in covered[0]["method"]


def test_semantic_matching_covers_concept_without_keyword(monkeypatch) -> None:
    def fake_embedding_cosine(topic: str, corpus_chunks: list[str], embedder_cfg: dict) -> tuple[float, str] | None:
        if topic == "hybridization":
            return 0.82, "sp3, sp2, sp 세 가지 혼성 오비탈을 비교함"
        return 0.2, ""

    monkeypatch.setattr(verifier, "_embedding_cosine", fake_embedding_cosine)

    result = verifier.check_coverage(
        note_text="결합축 배향과 오비탈 중첩 방식의 차이를 중심으로 세 구조를 비교 설명했다.",
        synthesis="",
        required_topics=["hybridization"],
        config=_base_config(semantic_matching=True),
    )

    covered = result["coverage"]["covered"]
    assert result["coverage"]["pass"] is True
    assert covered[0]["method"].startswith("semantic:0.82")


def test_semantic_shallow_mention_stays_missing(monkeypatch) -> None:
    def fake_embedding_cosine(topic: str, corpus_chunks: list[str], embedder_cfg: dict) -> tuple[float, str] | None:
        return 0.40, "Lewis 라는 이름만 언급"

    monkeypatch.setattr(verifier, "_embedding_cosine", fake_embedding_cosine)

    result = verifier.check_coverage(
        note_text="Lewis 라는 이름만 한번 언급하고 넘어감.",
        synthesis="",
        required_topics=["Lewis acid/base"],
        config=_base_config(semantic_matching=True),
    )

    assert result["coverage"]["pass"] is False
    assert result["coverage"]["missing"] == ["Lewis acid/base"]


def test_semantic_disabled_runs_layer1_layer2_only(monkeypatch) -> None:
    called = {"semantic": False}

    def fake_embedding_cosine(topic: str, corpus_chunks: list[str], embedder_cfg: dict) -> tuple[float, str] | None:
        called["semantic"] = True
        return 0.99, ""

    monkeypatch.setattr(verifier, "_embedding_cosine", fake_embedding_cosine)

    result = verifier.check_coverage(
        note_text="formal charge만 정리함",
        synthesis="",
        required_topics=["formal charge", "hybridization"],
        config=_base_config(semantic_matching=False),
    )

    assert called["semantic"] is False
    assert result["coverage"]["missing"] == ["hybridization"]


def test_remote_chroma_failure_skips_semantic(monkeypatch) -> None:
    called = {"semantic": False}

    def fake_embedding_cosine(topic: str, corpus_chunks: list[str], embedder_cfg: dict) -> tuple[float, str] | None:
        called["semantic"] = True
        return 0.95, ""

    monkeypatch.setattr(verifier, "_embedding_cosine", fake_embedding_cosine)

    cfg = _base_config(semantic_matching=True)
    cfg["mem0"]["vector_store"] = {"mode": "remote", "host": "127.0.0.1", "port": 1}

    result = verifier.check_coverage(
        note_text="세 가지 오비탈 배향 비교만 설명",
        synthesis="",
        required_topics=["hybridization"],
        config=cfg,
    )

    assert called["semantic"] is False
    assert result["coverage"]["missing"] == ["hybridization"]
=======
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
>>>>>>> origin/main
