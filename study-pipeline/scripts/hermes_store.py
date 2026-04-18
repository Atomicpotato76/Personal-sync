#!/usr/bin/env python3
"""hermes_store.py -- Hermes 일정 데이터 저장소."""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import date, datetime, timedelta
from pathlib import Path

from path_utils import get_study_paths


class HermesStore:
    """Hermes 일정/프로필/상태를 로컬 JSON으로 관리한다."""

    def __init__(self, config: dict):
        self.config = config
        self.paths = get_study_paths(config)
        self.base_dir = self.paths.cache / "hermes"
        self.profile_path = self.base_dir / "schedule_profile.json"
        self.exams_path = self.base_dir / "exam_calendar.json"
        self.schedule_path = self.base_dir / "study_schedule.json"
        self.state_path = self.base_dir / "hermes_state.json"
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._ensure_defaults()

    def _ensure_defaults(self) -> None:
        defaults = {
            self.profile_path: self._default_profile(),
            self.exams_path: {"events": []},
            self.schedule_path: {"plans": {"day": {}, "week": {}}},
            self.state_path: {"last_generated": None, "last_reason": "", "history": []},
        }
        for path, default in defaults.items():
            if not path.exists():
                self._save_json(path, default)

    def _default_profile(self) -> dict:
        return {
            "timezone": "local",
            "planning": {
                "week_start": "monday",
                "lookahead_days": 21,
                "exam_focus_window_days": 21,
                "max_blocks_per_day": 3,
                "max_same_subject_per_day": 2,
                "research_subjects": ["genomics_ai", "mycology"],
            },
            "daily_windows": {
                "weekday": [
                    {"start": "19:30", "duration_min": 90, "label": "Evening Focus"},
                    {"start": "21:15", "duration_min": 60, "label": "Review Sprint"},
                ],
                "weekend": [
                    {"start": "10:00", "duration_min": 120, "label": "Morning Deep Work"},
                    {"start": "15:00", "duration_min": 90, "label": "Afternoon Review"},
                    {"start": "20:00", "duration_min": 60, "label": "Light Recall"},
                ],
            },
        }

    def _load_json(self, path: Path, fallback: dict) -> dict:
        if not path.exists():
            return deepcopy(fallback)
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return deepcopy(fallback)

    def _save_json(self, path: Path, data: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def load_profile(self) -> dict:
        return self._load_json(self.profile_path, self._default_profile())

    def save_profile(self, profile: dict) -> None:
        self._save_json(self.profile_path, profile)

    def load_exam_calendar(self) -> dict:
        data = self._load_json(self.exams_path, {"events": []})
        data.setdefault("events", [])
        return data

    def save_exam_calendar(self, data: dict) -> None:
        data.setdefault("events", [])
        self._save_json(self.exams_path, data)

    def add_event(
        self,
        subject: str,
        title: str,
        when: str,
        details: str = "",
        kind: str = "exam",
    ) -> dict:
        data = self.load_exam_calendar()
        event = {
            "id": f"{subject}_{when}_{len(data['events']) + 1}",
            "subject": subject,
            "title": title,
            "date": when,
            "details": details,
            "kind": kind,
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }
        data["events"].append(event)
        data["events"].sort(key=lambda x: (x.get("date", ""), x.get("subject", ""), x.get("title", "")))
        self.save_exam_calendar(data)
        return event

    def upcoming_events(
        self,
        from_date: date | None = None,
        within_days: int = 30,
    ) -> list[dict]:
        base = from_date or date.today()
        limit = base + timedelta(days=within_days)
        events = []
        for event in self.load_exam_calendar().get("events", []):
            try:
                event_date = date.fromisoformat(event["date"])
            except (KeyError, ValueError):
                continue
            if base <= event_date <= limit:
                enriched = dict(event)
                enriched["days_left"] = (event_date - base).days
                events.append(enriched)
        return sorted(events, key=lambda x: (x["days_left"], x.get("subject", ""), x.get("title", "")))

    def load_schedule(self) -> dict:
        data = self._load_json(self.schedule_path, {"plans": {"day": {}, "week": {}}})
        data.setdefault("plans", {})
        data["plans"].setdefault("day", {})
        data["plans"].setdefault("week", {})
        return data

    def save_schedule(self, data: dict) -> None:
        data.setdefault("plans", {})
        data["plans"].setdefault("day", {})
        data["plans"].setdefault("week", {})
        self._save_json(self.schedule_path, data)

    def get_day_plan(self, target_date: str) -> dict | None:
        return self.load_schedule()["plans"]["day"].get(target_date)

    def save_day_plan(self, target_date: str, plan: dict) -> None:
        data = self.load_schedule()
        data["plans"]["day"][target_date] = plan
        self.save_schedule(data)

    def get_week_plan(self, week_start: str) -> dict | None:
        return self.load_schedule()["plans"]["week"].get(week_start)

    def save_week_plan(self, week_start: str, plan: dict) -> None:
        data = self.load_schedule()
        data["plans"]["week"][week_start] = plan
        self.save_schedule(data)

    def load_state(self) -> dict:
        data = self._load_json(self.state_path, {"last_generated": None, "last_reason": "", "history": []})
        data.setdefault("history", [])
        return data

    def record_generation(self, period: str, anchor_date: str, reason: str, block_count: int) -> None:
        state = self.load_state()
        now = datetime.now().isoformat(timespec="seconds")
        state["last_generated"] = now
        state["last_reason"] = reason
        state["history"].append({
            "generated_at": now,
            "period": period,
            "anchor_date": anchor_date,
            "reason": reason,
            "block_count": block_count,
        })
        state["history"] = state["history"][-30:]
        self._save_json(self.state_path, state)

    def get_daily_windows(self, target_date: date) -> list[dict]:
        profile = self.load_profile()
        day_type = "weekend" if target_date.weekday() >= 5 else "weekday"
        windows = profile.get("daily_windows", {}).get(day_type, [])

        energy_profile = self.config.get("energy_profile", {})
        if not energy_profile:
            return windows

        result = []
        for window in windows:
            w = dict(window)
            w["energy"] = self._lookup_energy(w.get("start", ""), energy_profile)
            result.append(w)
        return result

    @staticmethod
    def _lookup_energy(start_time: str, energy_profile: dict) -> str:
        """start_time(HH:MM)에 가장 가까운 energy_profile 값을 반환."""
        if not energy_profile or not start_time:
            return "medium"
        try:
            h, m = map(int, start_time.split(":"))
            start_min = h * 60 + m
        except (ValueError, AttributeError):
            return "medium"
        best_energy = "medium"
        best_diff = float("inf")
        for time_str, energy in energy_profile.items():
            try:
                th, tm = map(int, str(time_str).split(":"))
                diff = abs(start_min - th * 60 - tm)
            except (ValueError, AttributeError):
                continue
            if diff < best_diff:
                best_diff = diff
                best_energy = str(energy)
        return best_energy

    def get_planning_options(self) -> dict:
        return self.load_profile().get("planning", {})

