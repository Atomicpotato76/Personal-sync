import os
import base64
import re
import time
from datetime import date, timedelta
from dataclasses import dataclass, field

import requests
from bs4 import BeautifulSoup

from collectors.http_client import cached_get
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from config import (
    GMAIL_CREDENTIALS_FILE,
    GMAIL_TOKEN_FILE,
    GMAIL_SCOPES,
    GMAIL_FILTERS,
)


@dataclass
class GmailMessage:
    subject: str
    sender: str
    date: str
    body: str
    source: str  # "nyt" or "yahoo_morning_brief"
    article_url: str = ""
    article_body: str = ""


def get_gmail_service():
    """Gmail API 서비스 객체를 생성한다. 최초 실행시 브라우저 인증 필요."""
    creds = None

    if GMAIL_TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(GMAIL_TOKEN_FILE), GMAIL_SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not GMAIL_CREDENTIALS_FILE.exists():
                raise FileNotFoundError(
                    f"Gmail credentials 파일이 없습니다: {GMAIL_CREDENTIALS_FILE}\n"
                    "Google Cloud Console에서 OAuth 2.0 Client ID를 생성한 후\n"
                    f"credentials.json 파일을 {GMAIL_CREDENTIALS_FILE} 경로에 저장해주세요."
                )
            flow = InstalledAppFlow.from_client_secrets_file(str(GMAIL_CREDENTIALS_FILE), GMAIL_SCOPES)
            creds = flow.run_local_server(port=0)

        GMAIL_TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        GMAIL_TOKEN_FILE.write_text(creds.to_json())

    return build("gmail", "v1", credentials=creds)


def collect_gmail_messages(target_date: date | None = None) -> list[GmailMessage]:
    """Gmail에서 NYT와 Yahoo Morning Brief 메일을 수집한다."""
    if target_date is None:
        target_date = date.today()

    try:
        service = get_gmail_service()
    except FileNotFoundError as e:
        print(f"  [오류] {e}")
        return []

    after_str = target_date.strftime("%Y/%m/%d")
    before_str = (target_date + timedelta(days=1)).strftime("%Y/%m/%d")
    all_messages: list[GmailMessage] = []

    for source_name, filter_query in GMAIL_FILTERS.items():
        query = f"{filter_query} after:{after_str} before:{before_str}"
        try:
            messages = _fetch_messages(service, query, source_name)
            all_messages.extend(messages)
        except Exception as e:
            print(f"  [오류] Gmail {source_name} 수집 실패: {e}")

    # NYT 메일: 제목 기반으로 원문 URL 검색 후 크롤링 시도
    for msg in all_messages:
        if msg.source == "nyt":
            try:
                url = _search_nyt_article_url(msg.subject)
                if url:
                    msg.article_url = url
                    body = _fetch_nyt_article(url)
                    if body:
                        msg.article_body = body
                        print(f"    [NYT 원문] {msg.subject[:40]}... ({len(body)}자)")
            except Exception as e:
                print(f"    [NYT 원문 실패] {msg.subject[:30]}: {e}")

    return all_messages


def _fetch_messages(service, query: str, source_name: str) -> list[GmailMessage]:
    """Gmail API로 메일을 검색하고 내용을 추출한다."""
    results = service.users().messages().list(userId="me", q=query, maxResults=20).execute()
    message_ids = results.get("messages", [])

    messages = []
    for msg_ref in message_ids:
        msg = service.users().messages().get(userId="me", id=msg_ref["id"], format="full").execute()

        headers = {h["name"]: h["value"] for h in msg["payload"]["headers"]}
        subject = headers.get("Subject", "(제목 없음)")
        sender = headers.get("From", "")
        msg_date = headers.get("Date", "")

        body = _extract_body(msg["payload"])

        messages.append(GmailMessage(
            subject=subject,
            sender=sender,
            date=msg_date,
            body=body[:3000],
            source=source_name,
        ))

    return messages


def _extract_body(payload: dict) -> str:
    """메일 payload에서 본문 텍스트를 추출한다."""
    plain_text = ""
    html_text = ""

    if "body" in payload and payload["body"].get("data"):
        raw = base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")
        mime = payload.get("mimeType", "")
        if mime == "text/plain":
            plain_text = raw
        else:
            html_text = raw

    if "parts" in payload:
        for part in payload["parts"]:
            mime = part.get("mimeType", "")
            if mime == "text/plain" and part["body"].get("data"):
                plain_text = base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", errors="replace")
            elif mime == "text/html" and part["body"].get("data"):
                html_text = base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", errors="replace")
            elif mime.startswith("multipart/"):
                sub = _extract_body(part)
                if sub:
                    plain_text = plain_text or sub

    # HTML이 훨씬 풍부한 경우 (뉴스레터) HTML 우선 사용
    if html_text and len(html_text) > len(plain_text) * 3:
        return _html_to_text(html_text).strip()
    if plain_text:
        return plain_text.strip()
    if html_text:
        return _html_to_text(html_text).strip()
    return ""


def _html_to_text(html: str) -> str:
    """HTML → 텍스트 변환."""
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "head"]):
        tag.decompose()
    text = soup.get_text(separator="\n")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return "\n".join(lines)


def _search_nyt_article_url(subject: str) -> str:
    """NYT 메일 제목으로 nytimes.com 검색하여 원문 URL을 찾는다."""
    clean = re.sub(r"^(Breaking news|Opinion Today|The Evening|The Morning|The World):\s*", "", subject)
    clean = clean.strip()
    if not clean or len(clean) < 10:
        return ""

    search_url = f"https://www.nytimes.com/search?query={requests.utils.quote(clean)}"
    resp = cached_get(search_url)
    if resp is None:
        return ""
    soup = BeautifulSoup(resp.text, "lxml")

    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "/2026/" in href and ".html" in href and href.startswith("/"):
            return f"https://www.nytimes.com{href.split('?')[0]}"

    return ""


def _fetch_nyt_article(url: str) -> str:
    """NYT 기사 페이지에서 가능한 본문을 추출한다."""
    resp = cached_get(url)
    if resp is None:
        return ""
    soup = BeautifulSoup(resp.text, "lxml")

    # 방법 1: articleBody in ld+json
    import json
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string)
            if isinstance(data, list):
                data = data[0]
            if "articleBody" in data:
                return data["articleBody"]
        except (json.JSONDecodeError, TypeError):
            pass

    # 방법 2: article body section
    body = soup.find("section", {"name": "articleBody"}) or soup.find("article")
    if body:
        paragraphs = body.find_all("p")
        text = "\n\n".join(p.get_text(strip=True) for p in paragraphs if p.get_text(strip=True))
        if text:
            return text

    # 방법 3: meta description
    meta = soup.find("meta", {"property": "og:description"}) or soup.find("meta", {"name": "description"})
    if meta and meta.get("content"):
        return meta["content"]

    return ""


def setup_gmail():
    """Gmail OAuth 인증을 설정한다."""
    print("Gmail OAuth 인증을 시작합니다...")
    try:
        service = get_gmail_service()
        profile = service.users().getProfile(userId="me").execute()
        print(f"인증 성공! 연결된 계정: {profile.get('emailAddress', 'unknown')}")
        return True
    except Exception as e:
        print(f"인증 실패: {e}")
        return False


if __name__ == "__main__":
    setup_gmail()
