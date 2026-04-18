import re
import time
from datetime import date, datetime, timezone
from dataclasses import dataclass, field

import yfinance as yf
from bs4 import BeautifulSoup

from config import YAHOO_FINANCE_TICKERS
from collectors.http_client import cached_get


@dataclass
class StockMove:
    """개별 종목 변동 데이터"""
    name: str
    ticker: str
    change_pct: float
    direction: str  # "up" or "down"
    note: str = ""


@dataclass
class MarketIndex:
    """주요 지수/자산 시세 데이터"""
    name: str
    symbol: str
    price: float
    change: float
    change_pct: float


@dataclass
class YahooArticle:
    title: str
    summary: str
    link: str
    source: str
    published: str
    ticker: str
    body: str = ""
    stock_moves: list = field(default_factory=list)


def collect_market_data() -> list[MarketIndex]:
    """yfinance로 주요 지수/자산 시세를 가져온다."""
    symbols = {
        "^GSPC": "S&P 500",
        "^IXIC": "NASDAQ",
        "^DJI": "DOW",
        "^VIX": "VIX",
        "CL=F": "WTI 원유",
        "GC=F": "금",
        "DX-Y.NYB": "달러인덱스",
        "^KS11": "KOSPI",
        "^KQ11": "KOSDAQ",
        "USDKRW=X": "USD/KRW",
    }

    results = []
    for sym, name in symbols.items():
        try:
            t = yf.Ticker(sym)
            info = t.fast_info
            price = info.get("lastPrice", 0)
            prev = info.get("previousClose", 0)
            change = price - prev if prev else 0
            pct = (change / prev * 100) if prev else 0
            results.append(MarketIndex(
                name=name, symbol=sym,
                price=round(price, 2),
                change=round(change, 2),
                change_pct=round(pct, 2),
            ))
        except Exception as e:
            print(f"  [시세 오류] {name}: {e}")

    return results


def collect_yahoo_news(target_date: date | None = None) -> list[YahooArticle]:
    """Yahoo Finance에서 주요 지수 관련 뉴스를 수집한다."""
    if target_date is None:
        target_date = date.today()

    all_articles: list[YahooArticle] = []
    seen_links: set[str] = set()

    for ticker_symbol in YAHOO_FINANCE_TICKERS:
        try:
            ticker = yf.Ticker(ticker_symbol)
            news_items = ticker.news or []

            for item in news_items:
                content = item.get("content", item)

                title = content.get("title", "")
                summary = content.get("summary", content.get("description", ""))

                canonical = content.get("canonicalUrl", {})
                link = canonical.get("url", "") if isinstance(canonical, dict) else str(canonical)
                if not link:
                    click = content.get("clickThroughUrl", {})
                    link = click.get("url", "") if isinstance(click, dict) else str(click)
                if not link:
                    link = content.get("link", "")

                if not link or link in seen_links:
                    continue
                seen_links.add(link)

                pub_str = content.get("pubDate", content.get("displayTime", ""))
                pub_date_obj = None
                if pub_str:
                    try:
                        pub_dt = datetime.fromisoformat(pub_str.replace("Z", "+00:00"))
                        pub_date_obj = pub_dt.date()
                    except (ValueError, TypeError):
                        pass

                if pub_date_obj and pub_date_obj != target_date:
                    continue

                provider = content.get("provider", {})
                source = provider.get("displayName", "Yahoo Finance") if isinstance(provider, dict) else "Yahoo Finance"

                pub_display = pub_str[:16].replace("T", " ") if pub_str else ""

                article = YahooArticle(
                    title=title, summary=summary, link=link,
                    source=source, published=pub_display, ticker=ticker_symbol,
                )
                all_articles.append(article)

        except Exception as e:
            print(f"  [오류] {ticker_symbol} 뉴스 수집 실패: {e}")

    # 기사 본문 크롤링 + 종목 변동 추출
    for article in all_articles:
        try:
            article.body = _fetch_article_body(article.link)
            if article.body:
                article.stock_moves = _extract_stock_moves(article.body)
        except Exception as e:
            print(f"  [본문 수집 실패] {article.title[:30]}: {e}")

    return all_articles


def _fetch_article_body(url: str) -> str:
    """Yahoo Finance 기사 본문을 크롤링한다."""
    resp = cached_get(url)
    if resp is None:
        return ""
    soup = BeautifulSoup(resp.text, "lxml")

    body_div = (
        soup.find("div", class_="body") or
        soup.find("div", {"data-test-locator": "articleBody"}) or
        soup.find("article") or
        soup.find("div", class_="caas-body")
    )

    if body_div:
        for tag in body_div(["script", "style", "nav", "aside", "figure"]):
            tag.decompose()
        paragraphs = body_div.find_all("p")
        if paragraphs:
            return "\n\n".join(p.get_text(strip=True) for p in paragraphs if p.get_text(strip=True))
        return body_div.get_text(separator="\n", strip=True)

    return ""


# 종목 변동 추출 패턴들
_MOVE_PATTERNS = [
    # "Teradyne (TER) surged 11.80%"
    re.compile(r"([A-Z][A-Za-z\s&'.]+?)\s*\(([A-Z]{1,5})\)\s*(surged|jumped|rose|gained|rallied|climbed|soared)\s+([\d.]+)%", re.IGNORECASE),
    # "Venture Global (VG) declined 9.69%"
    re.compile(r"([A-Z][A-Za-z\s&'.]+?)\s*\(([A-Z]{1,5})\)\s*(declined|fell|dropped|slipped|tumbled|plunged|sank|lost)\s+([\d.]+)%", re.IGNORECASE),
    # "AAPL rose 3.5%"  or "NVDA fell 2.1%"
    re.compile(r"\b([A-Z]{1,5})\s+(surged|jumped|rose|gained|rallied|climbed|soared)\s+([\d.]+)%", re.IGNORECASE),
    re.compile(r"\b([A-Z]{1,5})\s+(declined|fell|dropped|slipped|tumbled|plunged|sank|lost)\s+([\d.]+)%", re.IGNORECASE),
]

_UP_WORDS = {"surged", "jumped", "rose", "gained", "rallied", "climbed", "soared"}
_DOWN_WORDS = {"declined", "fell", "dropped", "slipped", "tumbled", "plunged", "sank", "lost"}


def _extract_stock_moves(body: str) -> list[StockMove]:
    """기사 본문에서 개별 종목 변동 데이터를 추출한다."""
    moves = []
    seen_tickers = set()

    # 패턴 1, 2: "Company Name (TICK) verb XX%"
    for pattern in _MOVE_PATTERNS[:2]:
        for match in pattern.finditer(body):
            name = match.group(1).strip()
            ticker = match.group(2)
            verb = match.group(3).lower()
            pct = float(match.group(4))

            if ticker in seen_tickers:
                continue
            seen_tickers.add(ticker)

            direction = "up" if verb in _UP_WORDS else "down"
            moves.append(StockMove(
                name=name, ticker=ticker,
                change_pct=pct if direction == "up" else -pct,
                direction=direction,
            ))

    # 패턴 3, 4: "TICK verb XX%" (이름 없는 경우)
    for pattern in _MOVE_PATTERNS[2:]:
        for match in pattern.finditer(body):
            ticker = match.group(1)
            verb = match.group(2).lower()
            pct = float(match.group(3))

            if ticker in seen_tickers:
                continue
            seen_tickers.add(ticker)

            direction = "up" if verb in _UP_WORDS else "down"
            moves.append(StockMove(
                name="", ticker=ticker,
                change_pct=pct if direction == "up" else -pct,
                direction=direction,
            ))

    # 변동률 절대값 기준 정렬
    moves.sort(key=lambda m: abs(m.change_pct), reverse=True)
    return moves


if __name__ == "__main__":
    print("=== 주요 시장 시세 ===")
    for m in collect_market_data():
        arrow = "▲" if m.change >= 0 else "▼"
        print(f"  {m.name:14s} {m.price:>10.2f} {arrow} {m.change:>+8.2f} ({m.change_pct:>+.2f}%)")

    print("\n=== Yahoo Finance 뉴스 ===")
    articles = collect_yahoo_news()
    print(f"수집된 기사: {len(articles)}건")
    for a in articles:
        print(f"\n[{a.ticker}] {a.title}")
        if a.stock_moves:
            print(f"  종목 변동 {len(a.stock_moves)}건:")
            for s in a.stock_moves:
                print(f"    {s.name} ({s.ticker}) {s.change_pct:>+.2f}%")
