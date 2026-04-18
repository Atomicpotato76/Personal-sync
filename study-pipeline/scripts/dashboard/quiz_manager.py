"""quiz_manager.py -- review.py 순수 함수 래핑 (web UI용)."""
from __future__ import annotations

import json
from datetime import datetime
from typing import Optional

from path_utils import get_study_paths
from quiz_store import approve_quiz, load_quiz_json, save_quiz_json


class QuizManager:
    """퀴즈 로딩, 채점, 이동을 관리. review.py의 순수 함수를 래핑."""

    def __init__(self, config: dict):
        self.config = config
        from memory_manager import MemoryManager

        paths = get_study_paths(config)
        self.queue_dir = paths.queue
        self.approved_dir = paths.approved
        self.rejected_dir = paths.rejected
        self.memory = MemoryManager(config)
        self.approved_dir.mkdir(parents=True, exist_ok=True)

    def list_queue(self) -> list[dict]:
        """queue/의 퀴즈 목록."""
        results = []
        if not self.queue_dir.exists():
            return results
        for jf in sorted(self.queue_dir.glob("*.json")):
            try:
                with open(jf, encoding="utf-8") as f:
                    data = json.load(f)
                data["_path"] = str(jf)
                data["_filename"] = jf.name
                results.append(data)
            except Exception:
                pass
        return results

    def load_quiz(self, quiz_id: str) -> Optional[dict]:
        """특정 퀴즈 로드."""
        path = self.queue_dir / f"{quiz_id}.json"
        if not path.exists():
            path = self.approved_dir / f"{quiz_id}.json"
        if not path.exists():
            return None
        data = load_quiz_json(path)
        if data is None:
            return None
        data["_path"] = str(path)
        return data

    def grade_item(self, quiz_id: str, item_index: int, result: str, memo: str = ""):
        """단일 항목 채점 + MemoryManager 상태 갱신."""
        path = self.queue_dir / f"{quiz_id}.json"
        if not path.exists():
            return
        data = load_quiz_json(path)
        if data is None:
            return

        items = data.get("items", [])
        if item_index >= len(items):
            return

        now = datetime.now().isoformat(timespec="seconds")
        items[item_index]["review"] = {
            "result": result,
            "memo": memo or None,
            "reviewed_at": now,
        }

        save_quiz_json(path, data)

        subject = data.get("subject", "unknown")
        source_note = data.get("source_note", "")
        tags = items[item_index].get("concept_tags", [])
        self.memory.record_result(subject, tags, result, source_note=source_note, memo=memo or "")

    def complete_quiz(self, quiz_id: str):
        """퀴즈를 approved/로 이동."""
        approve_quiz(self.config, quiz_id)

    def is_quiz_complete(self, quiz_data: dict) -> bool:
        """모든 항목이 채점되었는지."""
        for item in quiz_data.get("items", []):
            review = item.get("review", {})
            if review.get("result") is None:
                return False
        return True
