"""
HTTP 클라이언트 - 캐싱 + 차단 시 Playwright headless 브라우저로 PDF 캡처 fallback
"""

import hashlib
from pathlib import Path

import requests

from config import REQUEST_HEADERS, CACHE_DIR, OUTPUT_DIR


# Playwright 브라우저 인스턴스 (lazy init)
_playwright = None
_browser = None


def cached_get(url: str, timeout: int = 15, cache_hours: int = 12, **kwargs) -> requests.Response | None:
    """
    캐싱이 적용된 GET 요청. 동일 URL에 대해 cache_hours 내 재요청을 하지 않는다.
    요청 실패(403, 429 등) 시 None을 반환한다.
    """
    cached = _read_cache(url, cache_hours)
    if cached is not None:
        resp = requests.models.Response()
        resp.status_code = 200
        resp._content = cached.encode("utf-8")
        resp.encoding = "utf-8"
        return resp

    try:
        resp = requests.get(url, headers=REQUEST_HEADERS, timeout=timeout, **kwargs)
        resp.raise_for_status()
        _write_cache(url, resp.text)
        return resp

    except requests.exceptions.HTTPError as e:
        status = e.response.status_code if e.response is not None else 0
        if status in (403, 429):
            print(f"    [차단됨] {status} - {url[:80]}")
            print(f"    -> headless 브라우저로 캡처 시도...")
            return _browser_fallback_get(url)
        else:
            print(f"    [HTTP 오류] {status} - {url[:80]}")
        return None
    except requests.exceptions.RequestException as e:
        print(f"    [요청 실패] {url[:80]}: {e}")
        return None


def capture_page_as_pdf(url: str, save_dir: Path | None = None) -> str | None:
    """
    Playwright로 페이지를 열어 PDF로 캡처한다.
    반환: 저장된 PDF 파일 경로, 실패 시 None
    """
    if save_dir is None:
        save_dir = OUTPUT_DIR / "captures"
    save_dir.mkdir(parents=True, exist_ok=True)

    url_hash = hashlib.md5(url.encode()).hexdigest()[:12]
    pdf_path = save_dir / f"{url_hash}.pdf"

    # 이미 캡처한 파일이 있으면 재사용
    if pdf_path.exists():
        return str(pdf_path)

    try:
        browser = _get_browser()
        page = browser.new_page()
        page.goto(url, wait_until="networkidle", timeout=30000)
        page.pdf(path=str(pdf_path), format="A4", print_background=True)
        page.close()
        print(f"    [PDF 캡처 완료] {pdf_path.name}")
        return str(pdf_path)
    except Exception as e:
        print(f"    [PDF 캡처 실패] {url[:60]}: {e}")
        return None


def _browser_fallback_get(url: str) -> requests.Response | None:
    """
    headless 브라우저로 페이지를 렌더링하고 HTML을 가져온다.
    동시에 PDF로도 캡처하여 저장한다.
    """
    try:
        browser = _get_browser()
        page = browser.new_page()
        page.goto(url, wait_until="networkidle", timeout=30000)

        # JS 렌더링 대기 (검색 결과 등)
        page.wait_for_timeout(3000)
        html = page.content()

        # PDF 캡처도 함께 수행
        capture_dir = OUTPUT_DIR / "captures"
        capture_dir.mkdir(parents=True, exist_ok=True)
        url_hash = hashlib.md5(url.encode()).hexdigest()[:12]
        pdf_path = capture_dir / f"{url_hash}.pdf"
        if not pdf_path.exists():
            page.pdf(path=str(pdf_path), format="A4", print_background=True)
            print(f"    [PDF 캡처] {pdf_path.name}")

        page.close()

        # HTML을 캐시에 저장
        _write_cache(url, html)

        resp = requests.models.Response()
        resp.status_code = 200
        resp._content = html.encode("utf-8")
        resp.encoding = "utf-8"
        print(f"    [브라우저 성공] {url[:60]}")
        return resp

    except Exception as e:
        print(f"    [브라우저 실패] {url[:60]}: {e}")
        return None


def _get_browser():
    """Playwright 브라우저를 lazy 초기화한다."""
    global _playwright, _browser
    if _browser is None:
        from playwright.sync_api import sync_playwright
        _playwright = sync_playwright().start()
        _browser = _playwright.chromium.launch(headless=True)
    return _browser


def close_browser():
    """프로그램 종료 시 브라우저를 정리한다."""
    global _playwright, _browser
    if _browser:
        _browser.close()
        _browser = None
    if _playwright:
        _playwright.stop()
        _playwright = None


# --- 캐시 유틸리티 ---

def _cache_path(url: str) -> Path:
    url_hash = hashlib.md5(url.encode()).hexdigest()
    return CACHE_DIR / f"{url_hash}.cache"


def _read_cache(url: str, max_hours: int) -> str | None:
    path = _cache_path(url)
    if not path.exists():
        return None

    import datetime
    mtime = datetime.datetime.fromtimestamp(path.stat().st_mtime)
    age = datetime.datetime.now() - mtime
    if age.total_seconds() > max_hours * 3600:
        path.unlink(missing_ok=True)
        return None

    return path.read_text(encoding="utf-8")


def _write_cache(url: str, content: str):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = _cache_path(url)
    path.write_text(content, encoding="utf-8")
