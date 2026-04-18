from datetime import date
from dataclasses import dataclass

from bs4 import BeautifulSoup

from config import (
    SEEKING_ALPHA_BASE_URL,
    SEEKING_ALPHA_SECTIONS,
)
from collectors.http_client import cached_get


@dataclass
class SeekingAlphaArticle:
    title: str
    author: str
    summary: str
    link: str
    date: str
    section: str
    body: str = ""


def collect_seeking_alpha(target_date: date | None = None) -> list[SeekingAlphaArticle]:
    """Seeking Alpha에서 최신 기사를 수집한다."""
    if target_date is None:
        target_date = date.today()

    target_str = target_date.strftime("%Y-%m-%d")
    all_articles: list[SeekingAlphaArticle] = []

    for section in SEEKING_ALPHA_SECTIONS:
        try:
            url = f"{SEEKING_ALPHA_BASE_URL}{section}"
            resp = cached_get(url, cache_hours=1)
            if resp is None:
                print(f"  [차단] Seeking Alpha {section} - 브라우저에서 직접 확인해주세요")
                continue
            soup = BeautifulSoup(resp.text, "lxml")

            articles = _parse_articles(soup, section, target_str)
            all_articles.extend(articles)
        except Exception as e:
            print(f"  [오류] Seeking Alpha {section} 수집 실패: {e}")

    # 각 기사 본문 크롤링
    for article in all_articles:
        body = _fetch_article_body(article.link)
        if body:
            article.body = body

    return all_articles


def _parse_articles(soup: BeautifulSoup, section: str, target_str: str) -> list[SeekingAlphaArticle]:
    """페이지에서 기사 목록을 파싱한다."""
    articles = []

    article_tags = soup.find_all("article") or soup.find_all("div", {"data-test-id": "post-list-item"})

    for tag in article_tags[:20]:
        title_tag = tag.find("a", {"data-test-id": "post-list-item-title"})
        if not title_tag:
            title_tag = tag.find("h3")
            if title_tag:
                title_tag = title_tag.find("a") or title_tag

        if not title_tag:
            continue

        title = title_tag.get_text(strip=True)
        link = title_tag.get("href", "")
        if link and not link.startswith("http"):
            link = f"{SEEKING_ALPHA_BASE_URL}{link}"

        author_tag = tag.find("a", {"data-test-id": "post-list-author"})
        author = author_tag.get_text(strip=True) if author_tag else ""

        summary_tag = tag.find("div", {"data-test-id": "post-list-summary"})
        if not summary_tag:
            summary_tag = tag.find("p")
        summary = summary_tag.get_text(strip=True) if summary_tag else ""

        time_tag = tag.find("time")
        article_date = ""
        if time_tag:
            dt = time_tag.get("datetime", "")
            if dt:
                article_date = dt[:10]

        if article_date and article_date != target_str:
            continue

        articles.append(SeekingAlphaArticle(
            title=title,
            author=author,
            summary=summary[:200],
            link=link,
            date=article_date or target_str,
            section=section,
        ))

    return articles


def _fetch_article_body(url: str) -> str:
    """Seeking Alpha 기사 본문을 크롤링한다."""
    resp = cached_get(url)
    if resp is None:
        return ""
    soup = BeautifulSoup(resp.text, "lxml")

    # 기사 본문 영역 탐색
    body_div = (
        soup.find("div", {"data-test-id": "article-body"}) or
        soup.find("div", {"data-test-id": "news-body"}) or
        soup.find("section", {"data-test-id": "article-body"}) or
        soup.find("div", class_="paywall-full-content") or
        soup.find("article")
    )

    if body_div:
        for tag in body_div(["script", "style", "nav", "aside", "figure", "header"]):
            tag.decompose()
        paragraphs = body_div.find_all("p")
        if paragraphs:
            text = "\n\n".join(p.get_text(strip=True) for p in paragraphs if p.get_text(strip=True))
            if text:
                return text

    # fallback: meta description
    meta = soup.find("meta", {"name": "description"}) or soup.find("meta", {"property": "og:description"})
    if meta:
        return meta.get("content", "")

    return ""


if __name__ == "__main__":
    print("=== Seeking Alpha 기사 수집 ===")
    articles = collect_seeking_alpha()
    print(f"\n수집된 기사: {len(articles)}건")
    for a in articles:
        print(f"\n[{a.section}] {a.title} - {a.author}")
        if a.body:
            print(f"  본문: {a.body[:200]}...")
        else:
            print(f"  (본문 없음)")
