#!/usr/bin/env python3
"""pubmed_client.py -- PubMed Entrez API로 관련 논문 검색 + citation 기반 정렬 + overview 작성."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from pathlib import Path
from typing import Optional

from path_utils import get_study_paths

logger = logging.getLogger("pipeline")

SCRIPT_DIR = Path(__file__).resolve().parent


def _get_cache_dir(config: dict) -> Path:
    return get_study_paths(config).cache / "pubmed"


def _cache_key(query: str) -> str:
    return hashlib.md5(query.encode()).hexdigest()[:12]


# ══════════════════════════════════════════════════════════════
# PubMed 검색 (citation count 포함)
# ══════════════════════════════════════════════════════════════

def search_pubmed(
    query: str,
    max_results: int = 5,
    email: str = "",
    sort_by: str = "citation",
) -> list[dict]:
    """PubMed에서 논문 검색 → citation count로 정렬.

    sort_by: "citation" (인용수 높은 순) | "relevance" | "date"
    """
    try:
        from Bio import Entrez
    except ImportError:
        logger.error("biopython 미설치: pip install biopython")
        return []

    Entrez.email = email or "student@example.com"

    try:
        # 검색 (더 많이 가져와서 citation으로 재정렬)
        fetch_count = max_results * 3 if sort_by == "citation" else max_results
        handle = Entrez.esearch(
            db="pubmed", term=query, retmax=fetch_count, sort="relevance",
        )
        record = Entrez.read(handle)
        handle.close()
        id_list = record.get("IdList", [])
        if not id_list:
            return []

        # 상세 정보
        handle = Entrez.efetch(db="pubmed", id=",".join(id_list), rettype="xml")
        records = Entrez.read(handle)
        handle.close()

        results = []
        for article in records.get("PubmedArticle", []):
            medline = article.get("MedlineCitation", {})
            art = medline.get("Article", {})

            pmid = str(medline.get("PMID", ""))
            title = str(art.get("ArticleTitle", ""))

            # Authors
            author_list = art.get("AuthorList", [])
            authors = []
            for a in author_list[:3]:
                last = a.get("LastName", "")
                init = a.get("Initials", "")
                if last:
                    authors.append(f"{last} {init}".strip())
            if len(author_list) > 3:
                authors.append("et al.")

            # Journal + ISSNs (IF 추정용)
            journal_info = art.get("Journal", {})
            journal = str(journal_info.get("Title", ""))
            issn = str(journal_info.get("ISSN", ""))

            # Year
            pub_date = journal_info.get("JournalIssue", {}).get("PubDate", {})
            year = str(pub_date.get("Year", ""))

            # Abstract
            abstract_parts = art.get("Abstract", {}).get("AbstractText", [])
            abstract = " ".join(str(p) for p in abstract_parts)

            results.append({
                "pmid": pmid,
                "title": title,
                "authors": ", ".join(authors),
                "journal": journal,
                "year": year,
                "abstract": abstract,
                "citation_count": 0,  # 아래에서 채움
            })

        # citation count 가져오기 (elink → cited-by)
        if sort_by == "citation" and results:
            _fill_citation_counts(results, Entrez)

        # 정렬
        if sort_by == "citation":
            results.sort(key=lambda x: x["citation_count"], reverse=True)

        return results[:max_results]

    except Exception as e:
        logger.error(f"PubMed 검색 실패: {e}")
        return []


def _fill_citation_counts(results: list[dict], Entrez) -> None:
    """PubMed Central의 cited-by 링크로 인용 횟수 추정."""
    pmids = [r["pmid"] for r in results]
    try:
        # elink로 cited-by 수 가져오기
        handle = Entrez.elink(
            dbfrom="pubmed", db="pubmed", id=pmids, linkname="pubmed_pubmed_citedin",
        )
        link_results = Entrez.read(handle)
        handle.close()

        for i, link_set in enumerate(link_results):
            if i >= len(results):
                break
            link_sets = link_set.get("LinkSetDb", [])
            if link_sets:
                count = len(link_sets[0].get("Link", []))
                results[i]["citation_count"] = count
    except Exception as e:
        logger.warning(f"Citation count 조회 실패: {e}")


# ══════════════════════════════════════════════════════════════
# 키워드 추출 (AND→OR 완화)
# ══════════════════════════════════════════════════════════════

def extract_keywords_from_note(note_text: str, subject: str, config: dict) -> str:
    """노트 텍스트에서 PubMed 검색 키워드 추출. OR 기반으로 완화."""
    subject_cfg = config["subjects"].get(subject, {})
    base_keywords = subject_cfg.get("pubmed_keywords", [])

    # 노트에서 영문 키워드 추출 (2단어 이상 영문 구)
    english_terms = re.findall(r"[A-Za-z][a-z]+(?: [A-Za-z][a-z]+)+", note_text)
    term_counts = {}
    for t in english_terms:
        t_lower = t.lower()
        if len(t_lower) > 5 and t_lower not in {"the and", "this is", "that is"}:
            term_counts[t_lower] = term_counts.get(t_lower, 0) + 1

    top_terms = sorted(term_counts, key=term_counts.get, reverse=True)[:3]

    # 검색 전략: base 키워드 1개 AND (노트 키워드 OR 조합)
    if base_keywords and top_terms:
        base = base_keywords[0]
        note_part = " OR ".join(f'"{t}"' for t in top_terms)
        return f"({base}) AND ({note_part})"
    elif base_keywords:
        return " OR ".join(f'"{k}"' for k in base_keywords[:3])
    elif top_terms:
        return " OR ".join(f'"{t}"' for t in top_terms)
    return ""


# ══════════════════════════════════════════════════════════════
# 종합: 검색 → overview 작성
# ══════════════════════════════════════════════════════════════

def search_and_summarize(subject: str, note_text: str, config: dict) -> Optional[str]:
    """PubMed 검색 (citation 높은 순) → LLM으로 overview 작성."""
    pubmed_cfg = config.get("pubmed", {})
    if not pubmed_cfg.get("enabled", False):
        return None

    cache_dir = _get_cache_dir(config)
    cache_dir.mkdir(parents=True, exist_ok=True)

    # 키워드 추출
    query = extract_keywords_from_note(note_text, subject, config)
    if not query:
        logger.info("PubMed 검색 키워드 없음")
        return None

    print(f"    PubMed 검색: {query}")

    # 캐시 확인
    cache_file = cache_dir / f"{_cache_key(query)}.json"
    if cache_file.exists():
        with open(cache_file, encoding="utf-8") as f:
            papers = json.load(f)
        print(f"    캐시 사용: {len(papers)}편")
    else:
        max_papers = pubmed_cfg.get("max_papers", 3)
        email = pubmed_cfg.get("email", "")
        papers = search_pubmed(query, max_papers, email, sort_by="citation")
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(papers, f, ensure_ascii=False, indent=2)
        print(f"    검색 결과: {len(papers)}편 (citation 순 정렬)")

    if not papers:
        return None

    # citation 정보 표시
    for p in papers:
        cite = p.get("citation_count", 0)
        print(f"      [{cite} citations] {p['title'][:60]}")

    # v3: 풀텍스트 보충 시도
    enriched = _enrich_with_fulltext(papers, config)

    # LLM으로 overview 작성
    from llm_router import LLMRouter
    router = LLMRouter(config)

    template_path = SCRIPT_DIR / "templates" / "pubmed_prompt.txt"
    if not template_path.exists():
        logger.warning("pubmed_prompt.txt 없음")
        return None

    template = template_path.read_text(encoding="utf-8")

    abstracts_text = ""
    for i, p in enumerate(enriched):
        cite = p.get("citation_count", 0)
        key_findings = p.get("key_findings", "")
        abstracts_text += (
            f"\n### Paper {i+1} (cited {cite} times)\n"
            f"**Title**: {p['title']}\n"
            f"**Authors**: {p['authors']}\n"
            f"**Journal**: {p.get('journal', 'N/A')} ({p['year']})\n"
            f"**PMID**: {p.get('pmid', 'N/A')}\n"
            f"**Abstract**: {p['abstract'][:500]}\n"
        )
        if key_findings:
            abstracts_text += f"**Key Findings (from full text)**: {key_findings}\n"

    topic_lines = [l for l in note_text.split("\n") if l.strip().startswith("#")]
    topic = topic_lines[0].strip("# ").strip() if topic_lines else "수업 내용"

    prompt = template.format(topic=topic, abstracts=abstracts_text)

    print("    PubMed overview 생성 중...")
    overview = router.generate(prompt, task_type="pubmed_overview")
    return overview


def _enrich_with_fulltext(papers: list[dict], config: dict) -> list[dict]:
    """PubMed 논문에 PMC 풀텍스트 key findings를 보충 (v3)."""
    papers_cfg = config.get("papers", {})
    if not papers_cfg.get("enabled", False):
        return papers

    try:
        from paper_fetcher import check_pmc_open_access, download_pdf
        from marker_reader import convert_with_fallback
    except ImportError:
        return papers

    vault = get_study_paths(config).vault
    papers_dir = vault / papers_cfg.get("cache_dir", "_pipeline/cache/papers")
    papers_dir.mkdir(parents=True, exist_ok=True)
    marker_cache = papers_dir / "marker_cache"

    for p in papers:
        pmid = p.get("pmid")
        if not pmid:
            continue
        pdf_url = check_pmc_open_access(pmid)
        if not pdf_url:
            continue
        pdf_path = papers_dir / "pdfs" / f"pmid_{pmid}.pdf"
        if download_pdf(pdf_url, pdf_path):
            text = convert_with_fallback(pdf_path, marker_cache, config=config)
            if text and len(text) > 500:
                p["key_findings"] = _extract_key_findings(text[:3000])

    return papers


def _extract_key_findings(text: str) -> str:
    """논문 텍스트에서 핵심 발견 추출 (휴리스틱)."""
    sentences = re.split(r'[.!?]\s+', text)
    keywords = {"result", "found", "showed", "demonstrated", "revealed", "concluded", "significant"}
    findings = []
    for s in sentences:
        if any(kw in s.lower() for kw in keywords) and len(s) > 30:
            findings.append(s.strip())
            if len(findings) >= 3:
                break
    return " ".join(findings) if findings else ""
