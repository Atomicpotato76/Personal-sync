import os
from pathlib import Path

BASE_DIR = Path(__file__).parent
OUTPUT_DIR = BASE_DIR / "output"
REPORTS_DIR = OUTPUT_DIR / "reports"
CREDENTIALS_DIR = BASE_DIR / "credentials"

GMAIL_CREDENTIALS_FILE = CREDENTIALS_DIR / "credentials.json"
GMAIL_TOKEN_FILE = CREDENTIALS_DIR / "token.json"
GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

NAVER_RESEARCH_BASE_URL = "https://finance.naver.com/research/"
NAVER_RESEARCH_CATEGORIES = {
    "investment_info": "investmentStyleList.naver",
    "stock_analysis": "company_list.naver",
    "industry_analysis": "industry_list.naver",
    "market_outlook": "market_info_list.naver",
    "economy_analysis": "economy_list.naver",
    "bond_analysis": "debenture_list.naver",
}

YAHOO_FINANCE_TICKERS = ["^GSPC", "^IXIC", "^DJI"]

SEEKING_ALPHA_BASE_URL = "https://seekingalpha.com"
SEEKING_ALPHA_SECTIONS = ["/market-news", "/market-outlook"]

GMAIL_FILTERS = {
    "nyt": "from:nytimes.com",
    "yahoo_morning_brief": "from:finance-morning-brief@newsletters.yahoo.net",
}

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]

REQUEST_HEADERS = {
    "User-Agent": USER_AGENTS[0],
}

REQUEST_DELAY_MIN = 2   # 최소 딜레이 (초)
REQUEST_DELAY_MAX = 5   # 최대 딜레이 (초)

CACHE_DIR = BASE_DIR / ".cache"
