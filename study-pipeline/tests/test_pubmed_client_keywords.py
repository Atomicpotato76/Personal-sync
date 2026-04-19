"""pubmed_client 키워드 파싱/검증 테스트."""

from pubmed_client import _dedupe_keywords, _parse_keyword_response


def test_parse_keyword_response_strips_json_code_fence() -> None:
    raw = """```json
["Carbon compounds", "Isotope labeling", "Tetrahedral geometry"]
```"""

    parsed = _parse_keyword_response(raw)

    assert parsed == ["Carbon compounds", "Isotope labeling", "Tetrahedral geometry"]


def test_dedupe_keywords_filters_code_fence_markers() -> None:
    keywords = ["```json", "Carbon compounds", "```", "Isotope labeling"]

    deduped = _dedupe_keywords(keywords)

    assert deduped == ["Carbon compounds", "Isotope labeling"]


def test_parse_keyword_response_plain_json_unchanged() -> None:
    raw = '["Covalent bonding mechanisms", "Reaction kinetics"]'

    parsed = _parse_keyword_response(raw)

    assert parsed == ["Covalent bonding mechanisms", "Reaction kinetics"]
