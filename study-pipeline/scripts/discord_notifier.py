"""discord_notifier.py — Discord 웹훅 알림 모듈.

파이프라인 결과, 에러, 퀴즈 생성, 스케줄 알림을 Discord로 전송.
config.yaml의 discord.webhook_url 또는 DISCORD_WEBHOOK_URL 환경변수 사용.
"""

import json
import logging
import os
from datetime import datetime
from typing import Optional

import requests
import yaml

logger = logging.getLogger("pipeline")

# 색상 상수 (Discord embed color)
COLOR_SUCCESS = 0x2ECC71   # 초록
COLOR_ERROR = 0xE74C3C     # 빨강
COLOR_INFO = 0x3498DB      # 파랑
COLOR_WARNING = 0xF39C12   # 주황
COLOR_QUIZ = 0x9B59B6      # 보라

_webhook_url: Optional[str] = None


def _get_webhook_url() -> Optional[str]:
    """config.yaml 또는 환경변수에서 webhook URL 가져오기."""
    global _webhook_url
    if _webhook_url:
        return _webhook_url

    # 1순위: 환경변수
    url = os.environ.get("DISCORD_WEBHOOK_URL")
    if url:
        _webhook_url = url
        return url

    # 2순위: config.yaml
    config_path = os.path.join(os.path.dirname(__file__), "config.yaml")
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        url = cfg.get("discord", {}).get("webhook_url", "")
        if url:
            _webhook_url = url
            return url
    except Exception:
        pass

    logger.warning("Discord webhook URL 미설정 (config.yaml discord.webhook_url 또는 DISCORD_WEBHOOK_URL)")
    return None


def send(title: str, description: str, color: int = COLOR_INFO,
         fields: list[dict] | None = None, footer: str = "") -> bool:
    """Discord embed 메시지 전송."""
    url = _get_webhook_url()
    if not url:
        return False

    embed = {
        "title": title,
        "description": description[:4096],
        "color": color,
        "timestamp": datetime.utcnow().isoformat(),
    }
    if fields:
        embed["fields"] = [
            {"name": f["name"][:256], "value": f["value"][:1024], "inline": f.get("inline", True)}
            for f in fields[:25]
        ]
    if footer:
        embed["footer"] = {"text": footer[:2048]}

    payload = {"embeds": [embed]}

    try:
        r = requests.post(url, json=payload, timeout=10)
        if r.status_code in (200, 204):
            logger.info(f"Discord 알림 전송: {title}")
            return True
        else:
            logger.warning(f"Discord 알림 실패: {r.status_code} {r.text[:200]}")
            return False
    except Exception as e:
        logger.warning(f"Discord 알림 전송 오류: {e}")
        return False


# ── 편의 함수들 ──

def pipeline_start(pipeline: str, note: str = "") -> bool:
    desc = f"📄 노트: {note}" if note else "파이프라인 시작됨"
    return send(f"🚀 {pipeline} 시작", desc, COLOR_INFO)


def pipeline_complete(pipeline: str, summary: str = "", note: str = "") -> bool:
    fields = []
    if note:
        fields.append({"name": "📄 노트", "value": note})
    if summary:
        fields.append({"name": "📊 요약", "value": summary[:1024], "inline": False})
    return send(f"✅ {pipeline} 완료", "파이프라인이 정상 완료되었습니다.", COLOR_SUCCESS, fields=fields)


def pipeline_error(pipeline: str, error: str, note: str = "") -> bool:
    fields = [{"name": "❌ 에러", "value": f"```{error[:900]}```", "inline": False}]
    if note:
        fields.append({"name": "📄 노트", "value": note})
    return send(f"🔴 {pipeline} 에러", "파이프라인 실행 중 오류 발생", COLOR_ERROR, fields=fields)


def quiz_ready(subject: str, count: int, note: str = "") -> bool:
    return send(
        f"📝 퀴즈 생성 완료",
        f"**{subject}** 과목에서 {count}개 퀴즈가 준비되었습니다!",
        COLOR_QUIZ,
        fields=[{"name": "📄 노트", "value": note}] if note else None,
    )


def schedule_update(summary: str) -> bool:
    return send("📅 학습 스케줄 업데이트", summary, COLOR_INFO)


def daily_report(title: str, content: str) -> bool:
    return send(f"📰 {title}", content[:4096], COLOR_INFO)
