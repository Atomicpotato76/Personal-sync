#!/usr/bin/env python3
"""paper_fetcher.py -- PubMed/PMC + Semantic Scholar 논문 검색 및 풀텍스트 다운로드 (v3).

기능:
  1. PubMed 검색 → PMC 오픈액세스 PDF 다운로드
  2. Semantic Scholar API 연동 (citation 기반)
  3. marker-pdf로 논문 본문 추출
  4. 논문 메타데이터 JSON 관리
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

PAPER_CACHE_TTL_DAYS = 30

import requests

from path_utils import get_study_paths, apply_env_path_overrides

logger = logging.getLogger("pipeline")

SCRIPT_DIR = Path(__file__).resolve().parent

# Semantic Scholar API (무료, rate limit 주의)
S2_API = "https://api.semanticscholar.org/graph/v1"
# PMC OA 서비스
PMC_OA_API = "https://www.ncbi.nlm.nih.gov/pmc/utils/oa.cgi"


def _get_papers_dir(config: dict) -> Path:
    vault = get_study_paths(config).vault
    papers_dir = vault / config.get("papers", {}).get("cache_dir", "_pipeline/cache/papers")
    papers_dir.mkdir(parents=True, exist_ok=True)
    return papers_dir


def _paper_id(title: str) -> str:
    return hashlib.md5(title.lower().strip().encode()).hexdigest()[:12]


# ══════════════════════════════════════════════════════════════
# Semantic Scholar 검색
# ══════════════════════════════════════════════════════════════

def search_semantic_scholar(
    query: str,
    max_results: int = 5,
    year_range: str | None = None,
    fields: list[str] | None = None,
) -> list[dict]:
    """Semantic Scholar API로 논문 검색.

    반환: [{paperId, title, abstract, year, citationCount, openAccessPdf, authors}]
    """
    default_fields = ["title", "abstract", "year", "citationCount", "openAccessPdf", "authors"]
    field_str = ",".join(fields or default_fields)

    params = {
        "query": query,
        "limit": min(max_results * 2, 20),
        "fields": field_str,
    }
    if year_range:
        params["year"] = year_range

    try:
        r = requests.get(f"{S2_API}/paper/search", params=params, timeout=15)
        if r.status_code == 429:
            logger.warning("Semantic Scholar rate limit, 3초 대기 후 재시도")
            time.sleep(3)
            r = requests.get(f"{S2_API}/paper/search", params=params, timeout=15)

        if r.status_code != 200:
            logger.error(f"Semantic Scholar 검색 오류: {r.status_code}")
            return []

        data = r.json()
        papers = data.get("data", [])

        # citation 수로 정렬
        papers.sort(key=lambda p: p.get("citationCount") or 0, reverse=True)
        return papers[:max_results]

    except Exception as e:
        logger.error(f"Semantic Scholar 검색 실패: {e}")
        return []


# ══════════════════════════════════════════════════════════════
# PMC 오픈액세스 PDF 다운로드
# ══════════════════════════════════════════════════════════════

def check_pmc_open_access(pmid: str, email: str = "") -> Optional[str]:
    """PubMed ID로 PMC 오픈액세스 PDF URL 확인."""
    try:
        if not email:
            logger.warning("PMC ID 변환: email 미설정")

        r = requests.get(
            "https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/",
            params={"ids": pmid, "format": "json", "tool": "study_pipeline", "email": email or "noreply@example.com"},
            timeout=10,
        )
        if r.status_code == 200:
            records = r.json().get("records", [])
            for rec in records:
                pmcid = rec.get("pmcid")
                if pmcid:
                    return f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmcid}/pdf/"
        return None
    except Exception as e:
        logger.warning(f"PMC ID 변환 실패: {e}")
        return None


def download_pdf(url: str, save_path: Path) -> bool:
    """PDF를 다운로드하여 저장."""
    if save_path.exists():
        logger.info(f"PDF 이미 존재: {save_path.name}")
        return True
    try:
        save_path.parent.mkdir(parents=True, exist_ok=True)
        r = requests.get(url, timeout=30, headers={"User-Agent": "StudyPipeline/3.0"})
        if r.status_code == 200 and len(r.content) > 1000:
            save_path.write_bytes(r.content)
            logger.info(f"PDF 다운로드: {save_path.name} ({len(r.content)} bytes)")
            return True
        else:
            logger.warning(f"PDF 다운로드 실패: {url} (status={r.status_code})")
            return False
    except Exception as e:
        logger.error(f"PDF 다운로드 오류: {e}")
        return False


# ══════════════════════════════════════════════════════════════
# 통합: 검색 → 다운로드 → 텍스트 추출
# ══════════════════════════════════════════════════════════════

def _is_cache_fresh(cache_file: Path, ttl_days: int = PAPER_CACHE_TTL_DAYS) -> bool:
    """캐시 파일이 TTL 이내이면 True."""
    if not cache_file.exists():
        return False
    try:
        with open(cache_file, encoding="utf-8") as f:
            data = json.load(f)
        if not data:
            return False
        cached_at_str = data[0].get("cached_at") if isinstance(data, list) else None
        if not cached_at_str:
            return False
        cached_at = datetime.fromisoformat(cached_at_str)
        return datetime.now() - cached_at < timedelta(days=ttl_days)
    except Exception:
        return False


def fetch_papers(
    query: str,
    config: dict,
    max_papers: int | None = None,
    force_refresh: bool = False,
) -> list[dict]:
    """논문 검색 + PDF 다운로드 + 텍스트 추출.

    반환: [{
        "paper_id": str,
        "title": str,
        "authors": str,
        "year": int,
        "citation_count": int,
        "abstract": str,
        "pdf_path": str | None,
        "full_text": str | None,
        "source": "semantic_scholar" | "pubmed",
        "cached_at": str,
    }]
    """
    papers_cfg = config.get("papers", {})
    if not papers_cfg.get("enabled", True):
        return []

    papers_dir = _get_papers_dir(config)
    max_papers = max_papers or papers_cfg.get("max_papers_per_topic", 5)

    # 캐시 확인 (30일 TTL)
    cache_key = hashlib.md5(query.encode()).hexdigest()[:12]
    cache_file = papers_dir / f"search_{cache_key}.json"
    if not force_refresh and _is_cache_fresh(cache_file):
        with open(cache_file, encoding="utf-8") as f:
            cached = json.load(f)
        if cached:
            logger.info(f"논문 캐시 사용: {len(cached)}편")
            return cached

    results = []

    # 1. Semantic Scholar 검색
    if papers_cfg.get("semantic_scholar", {}).get("enabled", True):
        s2_fields = papers_cfg.get("semantic_scholar", {}).get("fields")
        s2_papers = search_semantic_scholar(query, max_papers, fields=s2_fields)
        for p in s2_papers:
            authors = ", ".join(
                a.get("name", "") for a in (p.get("authors") or [])[:3]
            )
            if len(p.get("authors") or []) > 3:
                authors += " et al."

            pdf_url = None
            oa = p.get("openAccessPdf")
            if oa and isinstance(oa, dict):
                pdf_url = oa.get("url")

            entry = {
                "paper_id": _paper_id(p.get("title", "")),
                "title": p.get("title", ""),
                "authors": authors,
                "year": p.get("year"),
                "citation_count": p.get("citationCount") or 0,
                "abstract": p.get("abstract") or "",
                "pdf_url": pdf_url,
                "pdf_path": None,
                "full_text": None,
                "source": "semantic_scholar",
            }
            results.append(entry)

    # 2. PDF 다운로드 (오픈액세스만)
    if papers_cfg.get("prefer_open_access", True):
        for entry in results:
            if entry["pdf_url"]:
                pdf_name = f"{entry['paper_id']}.pdf"
                pdf_path = papers_dir / "pdfs" / pdf_name
                if download_pdf(entry["pdf_url"], pdf_path):
                    entry["pdf_path"] = str(pdf_path)
            time.sleep(0.5)  # rate limit 준수

    # 3. 텍스트 추출 (marker-pdf fallback)
    from marker_reader import convert_with_fallback
    marker_cache = papers_dir / "marker_cache"
    for entry in results:
        if entry["pdf_path"]:
            text = convert_with_fallback(Path(entry["pdf_path"]), marker_cache, config=config)
            if text:
                entry["full_text"] = text[:50000]  # 최대 50K자 제한

    # 캐시 저장 (pdf_url 제외, cached_at 추가)
    now_str = datetime.now().isoformat(timespec="seconds")
    save_data = []
    for entry in results:
        save_entry = {k: v for k, v in entry.items() if k != "pdf_url"}
        save_entry["cached_at"] = now_str
        save_data.append(save_entry)

    with open(cache_file, "w", encoding="utf-8") as f:
        json.dump(save_data, f, ensure_ascii=False, indent=2)

    logger.info(f"논문 수집 완료: {len(results)}편 (query: {query[:50]})")
    return results


def fetch_papers_for_note(
    note_text: str,
    subject: str,
    config: dict,
    force_refresh: bool = False,
) -> list[dict]:
    """노트 내용에서 키워드를 추출하여 관련 논문 수집."""
    from pubmed_client import extract_keywords_from_note
    query = extract_keywords_from_note(note_text, subject, config)
    if not query:
        logger.info("논문 검색 키워드 없음")
        return []

    print(f"    논문 검색: {query}")
    return fetch_papers(query, config, force_refresh=force_refresh)


# ══════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys
    import yaml

    if len(sys.argv) < 2:
        print("사용법: python paper_fetcher.py <검색어>")
        print('예시: python paper_fetcher.py "organic reaction mechanism"')
        sys.exit(1)

    logging.basicConfig(level=logging.INFO)
    config_path = SCRIPT_DIR / "config.yaml"
    with open(config_path, encoding="utf-8") as f:
        config = apply_env_path_overrides(yaml.safe_load(f) or {})

    query = " ".join(sys.argv[1:])
    papers = fetch_papers(query, config, max_papers=3)

    for p in papers:
        print(f"\n{'='*60}")
        print(f"  제목: {p['title']}")
        print(f"  저자: {p['authors']}")
        print(f"  연도: {p['year']} | 인용: {p['citation_count']}")
        print(f"  PDF: {'있음' if p['pdf_path'] else '없음'}")
        print(f"  본문: {len(p['full_text'] or '')}자")
