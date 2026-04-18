from __future__ import annotations

import json
from abc import ABC, abstractmethod
from urllib import request

from contracts.models import CheckpointSummary


class NotificationService(ABC):
    @abstractmethod
    def publish(self, *, event_name: str, summary: CheckpointSummary) -> None:
        raise NotImplementedError


class NullNotificationService(NotificationService):
    def publish(self, *, event_name: str, summary: CheckpointSummary) -> None:
        return


class DiscordWebhookNotificationService(NotificationService):
    def __init__(self, *, webhook_url: str, username: str = "Hermes Pipeline") -> None:
        self.webhook_url = webhook_url
        self.username = username

    def publish(self, *, event_name: str, summary: CheckpointSummary) -> None:
        content = self._render_message(event_name=event_name, summary=summary)
        payload = {
            "username": self.username,
            "content": content[:1900],
        }
        data = json.dumps(payload).encode("utf-8")
        http_request = request.Request(
            self.webhook_url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with request.urlopen(http_request, timeout=10):
                return
        except Exception as exc:
            raise RuntimeError(f"Discord notification failed: {exc}") from exc

    def _render_message(self, *, event_name: str, summary: CheckpointSummary) -> str:
        completed = ", ".join(summary.completed) if summary.completed else "아직 없음"
        pending = ", ".join(summary.pending) if summary.pending else "없음"
        risks = ", ".join(summary.risks) if summary.risks else "없음"
        recent_changes = ", ".join(summary.recent_changes) if summary.recent_changes else "없음"
        lines = [
            f"**Hermes update: {event_name}**",
            f"실행: `{summary.run_id}`",
            f"단계: `{summary.stage.value}` / `{summary.status.value}`",
            f"계획 버전: `v{summary.plan_version:03d}`",
        ]
        if summary.latest_stage_name:
            lines.append(f"\n:white_check_mark: **방금 완료된 단계:** `{summary.latest_stage_name}`")
            if summary.latest_stage_summary:
                lines.append(f"> {summary.latest_stage_summary}")
        lines.extend(
            [
                f"요약: {summary.overview}",
                f"완료: {completed}",
                f"대기: {pending}",
                f"최근 변경: {recent_changes}",
                f"위험 요소: {risks}",
                f"다음 단계: {summary.next_step}",
            ]
        )
        return "\n".join(lines)
