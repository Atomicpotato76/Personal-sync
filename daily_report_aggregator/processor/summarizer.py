from datetime import date
from pathlib import Path

from config import OUTPUT_DIR


def generate_daily_report(
    target_date: date,
    naver_reports: list,
    yahoo_articles: list,
    seeking_alpha_articles: list,
    gmail_messages: list,
    market_data: list | None = None,
) -> Path:
    """수집된 모든 데이터를 일별 Markdown 리포트로 생성한다."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    date_str = target_date.strftime("%Y-%m-%d")
    filepath = OUTPUT_DIR / f"{date_str}.md"

    lines = []
    lines.append(f"# 일일 금융 리포트 - {date_str}")
    lines.append("")
    lines.append(f"> 자동 수집 일시: {date_str}")
    lines.append("")

    # 요약 통계
    total = len(naver_reports) + len(yahoo_articles) + len(seeking_alpha_articles) + len(gmail_messages)
    lines.append("## 수집 요약")
    lines.append("")
    lines.append(f"| 소스 | 건수 |")
    lines.append(f"|------|------|")
    lines.append(f"| 네이버증권 리서치 | {len(naver_reports)} |")
    lines.append(f"| Yahoo Finance | {len(yahoo_articles)} |")
    lines.append(f"| Seeking Alpha | {len(seeking_alpha_articles)} |")
    lines.append(f"| Gmail (NYT/Yahoo) | {len(gmail_messages)} |")
    lines.append(f"| **합계** | **{total}** |")
    lines.append("")

    # === 주요 시장 시세 표 ===
    if market_data:
        lines.append("---")
        lines.append("")
        lines.append("## 주요 시장 시세")
        lines.append("")
        lines.append("| 지수/자산 | 현재가 | 변동 | 변동률 |")
        lines.append("|-----------|-------:|-----:|-------:|")
        for m in market_data:
            arrow = "🔺" if m.change >= 0 else "🔻"
            sign = "+" if m.change >= 0 else ""
            lines.append(f"| {m.name} | {m.price:,.2f} | {arrow} {sign}{m.change:,.2f} | {sign}{m.change_pct:.2f}% |")
        lines.append("")

    # === 종목 변동 표 (Yahoo Finance 기사에서 추출) ===
    all_moves = []
    for a in yahoo_articles:
        all_moves.extend(a.stock_moves)
    # 중복 제거 (같은 ticker)
    seen = set()
    unique_moves = []
    for m in all_moves:
        if m.ticker not in seen:
            seen.add(m.ticker)
            unique_moves.append(m)
    unique_moves.sort(key=lambda m: m.change_pct, reverse=True)

    if unique_moves:
        lines.append("---")
        lines.append("")
        lines.append("## 주요 종목 변동")
        lines.append("")

        # 상승 종목
        up_moves = [m for m in unique_moves if m.change_pct > 0]
        down_moves = [m for m in unique_moves if m.change_pct < 0]

        if up_moves:
            lines.append("### 상승 종목")
            lines.append("")
            lines.append("| 종목 | 티커 | 변동률 |")
            lines.append("|------|------|-------:|")
            for m in up_moves:
                name = m.name if m.name else m.ticker
                lines.append(f"| {name} | {m.ticker} | 🔺 +{m.change_pct:.2f}% |")
            lines.append("")

        if down_moves:
            lines.append("### 하락 종목")
            lines.append("")
            lines.append("| 종목 | 티커 | 변동률 |")
            lines.append("|------|------|-------:|")
            for m in down_moves:
                name = m.name if m.name else m.ticker
                lines.append(f"| {name} | {m.ticker} | 🔻 {m.change_pct:.2f}% |")
            lines.append("")

    # === Gmail 뉴스레터 ===
    lines.append("---")
    lines.append("")
    lines.append("## Gmail 뉴스레터")
    lines.append("")
    if gmail_messages:
        source_names = {"nyt": "New York Times", "yahoo_morning_brief": "Yahoo Morning Brief"}
        by_source = {}
        for m in gmail_messages:
            name = source_names.get(m.source, m.source)
            by_source.setdefault(name, []).append(m)

        for source, messages in by_source.items():
            lines.append(f"### {source}")
            lines.append("")
            for m in messages:
                if m.article_url:
                    lines.append(f"#### [{m.subject}]({m.article_url})")
                else:
                    lines.append(f"#### {m.subject}")
                lines.append("")
                if m.article_body:
                    lines.append(m.article_body[:3000])
                else:
                    lines.append(m.body[:3000])
                lines.append("")
    else:
        lines.append("_수집된 메일 없음 (Gmail 설정을 확인해주세요)_")
        lines.append("")

    # === 네이버증권 리서치 ===
    lines.append("---")
    lines.append("")
    lines.append("## 국내 증권사 리포트 (네이버증권 리서치)")
    lines.append("")
    if naver_reports:
        category_map = {
            "investment_info": "투자정보",
            "stock_analysis": "종목분석",
            "industry_analysis": "산업분석",
            "market_outlook": "시장전망",
            "economy_analysis": "경제분석",
            "bond_analysis": "채권분석",
        }
        by_category = {}
        for r in naver_reports:
            cat = category_map.get(r.category, r.category)
            by_category.setdefault(cat, []).append(r)

        for cat, reports in by_category.items():
            lines.append(f"### {cat}")
            lines.append("")
            for r in reports:
                pdf_link = f" | [PDF]({r.pdf_url})" if r.pdf_url else ""
                lines.append(f"- **{r.title}** - {r.broker}{pdf_link}")
            lines.append("")
    else:
        lines.append("_수집된 리포트 없음_")
        lines.append("")

    # === Yahoo Finance 기사 ===
    lines.append("---")
    lines.append("")
    lines.append("## 해외 리서치 - Yahoo Finance")
    lines.append("")
    if yahoo_articles:
        ticker_names = {"^GSPC": "S&P 500", "^IXIC": "NASDAQ", "^DJI": "DOW"}
        by_ticker = {}
        for a in yahoo_articles:
            name = ticker_names.get(a.ticker, a.ticker)
            by_ticker.setdefault(name, []).append(a)

        for ticker, articles in by_ticker.items():
            lines.append(f"### {ticker}")
            lines.append("")
            for a in articles:
                lines.append(f"#### [{a.title}]({a.link})")
                lines.append(f"*{a.source} | {a.published}*")
                lines.append("")

                # 종목 변동 표가 있으면 기사 상단에 표시
                if a.stock_moves:
                    lines.append("| 종목 | 티커 | 변동률 |")
                    lines.append("|------|------|-------:|")
                    for m in a.stock_moves:
                        name = m.name if m.name else m.ticker
                        arrow = "🔺" if m.change_pct > 0 else "🔻"
                        sign = "+" if m.change_pct > 0 else ""
                        lines.append(f"| {name} | {m.ticker} | {arrow} {sign}{m.change_pct:.2f}% |")
                    lines.append("")

                if a.body:
                    lines.append(a.body)
                    lines.append("")
                elif a.summary:
                    lines.append(f"> {a.summary}")
                    lines.append("")
    else:
        lines.append("_수집된 기사 없음_")
        lines.append("")

    # === Seeking Alpha ===
    lines.append("---")
    lines.append("")
    lines.append("## 해외 리서치 - Seeking Alpha")
    lines.append("")
    if seeking_alpha_articles:
        for a in seeking_alpha_articles:
            author_str = f" | {a.author}" if a.author else ""
            lines.append(f"#### [{a.title}]({a.link})")
            lines.append(f"*{a.date}{author_str}*")
            lines.append("")
            if a.body:
                lines.append(a.body)
                lines.append("")
            elif a.summary:
                lines.append(f"> {a.summary}")
                lines.append("")
    else:
        lines.append("_수집된 기사 없음_")
        lines.append("")

    content = "\n".join(lines)
    filepath.write_text(content, encoding="utf-8")
    return filepath
