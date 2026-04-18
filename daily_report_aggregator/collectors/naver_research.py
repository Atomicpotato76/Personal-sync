import time
from datetime import date
from dataclasses import dataclass

import requests
from bs4 import BeautifulSoup

from config import (
    NAVER_RESEARCH_BASE_URL,
    NAVER_RESEARCH_CATEGORIES,
    REPORTS_DIR,
    REQUEST_HEADERS,
)
from collectors.http_client import cached_get


@dataclass
class NaverReport:
    title: str
    broker: str
    date: str
    pdf_url: str
    category: str
    pdf_path: str = ""
    content: str = ""


def collect_naver_reports(target_date: date | None = None) -> list[NaverReport]:
    """네이버증권 리서치 페이지에서 리포트 목록을 수집한다."""
    if target_date is None:
        target_date = date.today()

    target_str = target_date.strftime("%y.%m.%d")
    all_reports: list[NaverReport] = []

    for cat_name, cat_path in NAVER_RESEARCH_CATEGORIES.items():
        try:
            reports = _scrape_category(cat_name, cat_path, target_str)
            all_reports.extend(reports)
        except Exception as e:
            print(f"  [오류] {cat_name} 수집 실패: {e}")

    return all_reports


def _scrape_category(cat_name: str, cat_path: str, target_str: str) -> list[NaverReport]:
    """단일 카테고리의 리포트 목록을 파싱한다."""
    url = f"{NAVER_RESEARCH_BASE_URL}{cat_path}"
    resp = cached_get(url, cache_hours=1)
    if resp is None:
        return []
    resp.encoding = "euc-kr"
    soup = BeautifulSoup(resp.text, "lxml")

    reports = []
    table = soup.find("table", class_="type_1")
    if not table:
        return reports

    rows = table.find_all("tr")
    for row in rows:
        cols = row.find_all("td")
        if len(cols) < 3:
            continue

        date_cell = ""
        for col in reversed(cols):
            text = col.get_text(strip=True)
            if target_str in text:
                date_cell = text
                break
        if not date_cell:
            continue

        title = ""
        for col in cols:
            a_tag = col.find("a")
            if a_tag and a_tag.get_text(strip=True):
                title = a_tag.get_text(strip=True)
                break
        if not title:
            continue

        broker = ""
        for idx in [2, 3, 1]:
            if idx < len(cols):
                text = cols[idx].get_text(strip=True)
                if text and text != title and target_str not in text and not text.isdigit():
                    broker = text
                    break

        pdf_tag = row.find("a", href=lambda h: h and ".pdf" in h.lower())
        pdf_url = pdf_tag["href"] if pdf_tag else ""

        reports.append(NaverReport(
            title=title, broker=broker, date=date_cell,
            pdf_url=pdf_url, category=cat_name,
        ))

    return reports


def download_and_extract_pdfs(reports: list[NaverReport], target_date: date | None = None) -> list[NaverReport]:
    """수집된 리포트의 PDF를 다운로드하고 텍스트를 추출한다."""
    import fitz  # pymupdf

    if target_date is None:
        target_date = date.today()

    save_dir = REPORTS_DIR / target_date.strftime("%Y-%m-%d")
    save_dir.mkdir(parents=True, exist_ok=True)

    for report in reports:
        if not report.pdf_url:
            continue
        try:
            resp = requests.get(report.pdf_url, headers=REQUEST_HEADERS, timeout=30)
            resp.raise_for_status()

            safe_title = "".join(c if c.isalnum() or c in " _-" else "_" for c in report.title)[:80]
            filename = f"{report.broker}_{safe_title}.pdf"
            filepath = save_dir / filename
            filepath.write_bytes(resp.content)
            report.pdf_path = str(filepath)
            report.content = _extract_pdf_text(resp.content)
            print(f"  [완료] {filename} ({len(report.content)}자)")
        except Exception as e:
            print(f"  [실패] {report.title}: {e}")

    return reports


def _extract_pdf_text(pdf_bytes: bytes) -> str:
    import fitz
    text_parts = []
    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        for page in doc:
            text = page.get_text()
            if text.strip():
                text_parts.append(text.strip())
    return "\n\n".join(text_parts)


if __name__ == "__main__":
    print("=== 네이버증권 리서치 리포트 수집 ===")
    reports = collect_naver_reports()
    print(f"\n수집된 리포트: {len(reports)}건")
    for r in reports:
        print(f"  [{r.category}] {r.broker} - {r.title} ({r.date})")
