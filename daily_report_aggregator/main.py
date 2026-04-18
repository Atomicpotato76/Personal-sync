#!/usr/bin/env python3
"""
Daily Financial Report Aggregator
국내/해외 증권사 리포트 + Gmail 뉴스레터를 자동 수집하여 일별 Markdown 리포트 생성
"""

import argparse
import sys
from datetime import date, datetime

# 프로젝트 루트를 path에 추가
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))

from collectors.naver_research import collect_naver_reports, download_and_extract_pdfs
from collectors.yahoo_finance import collect_yahoo_news, collect_market_data
from collectors.seeking_alpha import collect_seeking_alpha
from collectors.gmail_reader import collect_gmail_messages, setup_gmail
from collectors.http_client import close_browser
from processor.summarizer import generate_daily_report


def run_collection(target_date: date, skip_gmail: bool = False):
    """모든 소스에서 데이터를 수집하고 일별 리포트를 생성한다."""
    print(f"\n{'='*60}")
    print(f"  일일 금융 리포트 수집 - {target_date.strftime('%Y-%m-%d')}")
    print(f"{'='*60}\n")

    # 1. 네이버증권 리서치
    print("[1/4] 네이버증권 리서치 리포트 수집 중...")
    naver_reports = collect_naver_reports(target_date)
    print(f"  -> {len(naver_reports)}건 목록 수집 완료")

    pdf_reports = [r for r in naver_reports if r.pdf_url]
    if pdf_reports:
        print(f"  PDF 다운로드 및 텍스트 추출 중... ({len(pdf_reports)}건)")
        download_and_extract_pdfs(naver_reports, target_date)

    # 2. Yahoo Finance
    print("\n[2/4] Yahoo Finance 시세 및 뉴스 수집 중...")
    market_data = collect_market_data()
    print(f"  -> 시세 {len(market_data)}건 수집 완료")
    yahoo_articles = collect_yahoo_news(target_date)
    stock_moves_count = sum(len(a.stock_moves) for a in yahoo_articles)
    print(f"  -> 뉴스 {len(yahoo_articles)}건 수집 완료 (종목 변동 {stock_moves_count}건 추출)")

    # 3. Seeking Alpha
    print("\n[3/4] Seeking Alpha 기사 수집 중...")
    seeking_alpha_articles = collect_seeking_alpha(target_date)
    print(f"  -> {len(seeking_alpha_articles)}건 수집 완료")

    # 4. Gmail
    gmail_messages = []
    if not skip_gmail:
        print("\n[4/4] Gmail 뉴스레터 수집 중...")
        gmail_messages = collect_gmail_messages(target_date)
        print(f"  -> {len(gmail_messages)}건 수집 완료")
    else:
        print("\n[4/4] Gmail 수집 건너뜀 (--skip-gmail)")

    # 리포트 생성
    print("\n리포트 생성 중...")
    report_path = generate_daily_report(
        target_date=target_date,
        naver_reports=naver_reports,
        yahoo_articles=yahoo_articles,
        seeking_alpha_articles=seeking_alpha_articles,
        gmail_messages=gmail_messages,
        market_data=market_data,
    )

    # 브라우저 정리
    close_browser()

    total = len(naver_reports) + len(yahoo_articles) + len(seeking_alpha_articles) + len(gmail_messages)
    print(f"\n{'='*60}")
    print(f"  수집 완료! 총 {total}건")
    print(f"  리포트 저장: {report_path}")
    print(f"{'='*60}\n")

    return report_path


def main():
    parser = argparse.ArgumentParser(
        description="일일 금융 리포트 자동 수집기",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
사용 예시:
  python main.py                    # 오늘 날짜 리포트 수집
  python main.py --date 2026-04-07  # 특정 날짜 리포트 수집
  python main.py --setup-gmail      # Gmail OAuth 초기 설정
  python main.py --skip-gmail       # Gmail 제외하고 수집
  python main.py --download-pdfs    # 네이버 리포트 PDF 다운로드 포함
        """,
    )

    parser.add_argument(
        "--date", "-d",
        type=str,
        default=None,
        help="수집 대상 날짜 (YYYY-MM-DD 형식, 기본: 오늘)",
    )
    parser.add_argument(
        "--setup-gmail",
        action="store_true",
        help="Gmail OAuth 인증 설정",
    )
    parser.add_argument(
        "--skip-gmail",
        action="store_true",
        help="Gmail 수집을 건너뜀",
    )
    args = parser.parse_args()

    if args.setup_gmail:
        setup_gmail()
        return

    if args.date:
        try:
            target_date = datetime.strptime(args.date, "%Y-%m-%d").date()
        except ValueError:
            print(f"오류: 날짜 형식이 잘못되었습니다. YYYY-MM-DD 형식으로 입력해주세요: {args.date}")
            sys.exit(1)
    else:
        target_date = date.today()

    run_collection(
        target_date=target_date,
        skip_gmail=args.skip_gmail,
    )


if __name__ == "__main__":
    main()
