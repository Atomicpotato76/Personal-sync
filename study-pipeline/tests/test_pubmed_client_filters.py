"""pubmed_client relevance filtering regression tests."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from pubmed_client import _filter_irrelevant_papers


def test_filter_skips_when_all_citations_are_zero() -> None:
    papers = [
        {"title": "Paper A", "abstract": "Intro chemistry", "citation_count": 0},
        {"title": "Paper B", "abstract": "Bonding basics", "citation_count": 0},
    ]
    cfg = {"skip_if_semantic_mismatch": True, "min_keyword_overlap": 1}
    out = _filter_irrelevant_papers(papers, "Organic chemistry bonding", cfg)
    assert out == []


def test_filter_keeps_semantically_overlapping_papers() -> None:
    papers = [
        {
            "title": "Covalent bonding and tetrahedral carbon",
            "abstract": "Undergraduate organic chemistry fundamentals",
            "citation_count": 15,
        },
        {
            "title": "E3 ligase covalent modifier screening",
            "abstract": "Drug discovery platform for ubiquitin pathways",
            "citation_count": 12,
        },
    ]
    cfg = {"skip_if_semantic_mismatch": True, "min_keyword_overlap": 2}
    out = _filter_irrelevant_papers(
        papers,
        "Week 1 organic chemistry: carbon compounds and tetrahedral geometry",
        cfg,
    )
    assert len(out) == 1
    assert "tetrahedral carbon" in out[0]["title"].lower()
