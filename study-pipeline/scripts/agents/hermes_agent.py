#!/usr/bin/env python3
"""hermes_agent.py -- Hermes 일정 관리 에이전트."""

from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta

from hermes_store import HermesStore
from path_utils import get_study_paths


class HermesAgent:
    """학습 데이터와 시험 일정을 바탕으로 일간/주간 계획을 만든다."""

    def __init__(self, config: dict):
        self.config = config
        self.store = HermesStore(config)
        self.paths = get_study_paths(config)
        self._subject_display = {v: k for k, v in config.get("folder_mapping", {}).items()}

    def plan_day(self, target_date: str | None = None, reason: str = "manual") -> dict:
        anchor = self._parse_date(target_date) or date.today()
        plan = self._build_plan([anchor], scope="day", reason=reason)
        self.store.save_day_plan(anchor.isoformat(), plan)
        self.store.record_generation("day", anchor.isoformat(), reason, len(plan["blocks"]))
        return plan

    def plan_week(self, start_date: str | None = None, reason: str = "manual") -> dict:
        anchor = self._parse_date(start_date) or self._week_start(date.today())
        days = [anchor + timedelta(days=offset) for offset in range(7)]
        plan = self._build_plan(days, scope="week", reason=reason)
        self.store.save_week_plan(anchor.isoformat(), plan)
        self.store.record_generation("week", anchor.isoformat(), reason, len(plan["blocks"]))
        return plan

    def reschedule(self, period: str = "day", anchor_date: str | None = None, reason: str = "reschedule") -> dict:
        if period == "week":
            return self.plan_week(anchor_date, reason=reason)
        return self.plan_day(anchor_date, reason=reason)

    def get_schedule(self, period: str = "day", anchor_date: str | None = None, auto_create: bool = True) -> dict:
        if period == "week":
            anchor = self._parse_date(anchor_date) or self._week_start(date.today())
            cached = self.store.get_week_plan(anchor.isoformat())
            if cached or not auto_create:
                return cached or {}
            return self.plan_week(anchor.isoformat(), reason="auto_create")

        anchor = self._parse_date(anchor_date) or date.today()
        cached = self.store.get_day_plan(anchor.isoformat())
        if cached or not auto_create:
            return cached or {}
        return self.plan_day(anchor.isoformat(), reason="auto_create")

    def refresh_from_event(self, reason: str) -> dict:
        day_plan = self.plan_day(reason=reason)
        week_plan = self.plan_week(reason=reason)
        return {"day": day_plan, "week": week_plan}

    def _build_plan(self, dates: list[date], scope: str, reason: str) -> dict:
        start = dates[0]
        end = dates[-1]
        options = self.store.get_planning_options()
        candidates = self._collect_candidates(start, end, options)
        task_units = self._expand_task_units(candidates)

        # 2.1: 인터리빙 파라미터
        interleaving_mode = self.config.get("interleaving_mode", "off")
        weak_snapshot = self._load_weak_snapshot() if interleaving_mode != "off" else {}
        last_focus: list[str] = []

        blocks: list[dict] = []
        backlog: list[dict] = []
        daily_subject_counts: dict[str, dict[str, int]] = {}
        max_blocks_per_day = int(options.get("max_blocks_per_day", 3))
        max_same_subject_per_day = int(options.get("max_same_subject_per_day", 2))

        for current in dates:
            windows = self.store.get_daily_windows(current)[:max_blocks_per_day]
            date_key = current.isoformat()
            daily_subject_counts.setdefault(date_key, {})

            for window in windows:
                slot_energy = window.get("energy", "medium")
                chosen = self._pick_task(
                    task_units,
                    daily_subject_counts[date_key],
                    max_same_subject_per_day,
                    interleaving_mode=interleaving_mode,
                    last_focus=last_focus,
                    weak_snapshot=weak_snapshot,
                    slot_energy=slot_energy,
                )
                if chosen is None:
                    continue
                last_focus = chosen.get("focus", [])[:2]

                start_time = window["start"]
                duration = int(window.get("duration_min", 60))
                block = {
                    "id": f"{date_key}_{len(blocks) + 1}",
                    "date": date_key,
                    "start": start_time,
                    "end": self._end_time(start_time, duration),
                    "label": window.get("label", ""),
                    "energy": slot_energy,
                    "subject": chosen["subject"],
                    "subject_display": self._display_subject(chosen["subject"]),
                    "title": chosen["title"],
                    "category": chosen["category"],
                    "priority": chosen["priority"],
                    "status": "planned",
                    "reason": chosen["reason"],
                    "focus": chosen["focus"],
                    "minutes": duration,
                }
                blocks.append(block)
                daily_subject_counts[date_key][chosen["subject"]] = daily_subject_counts[date_key].get(chosen["subject"], 0) + 1

        backlog = [self._task_preview(task) for task in task_units]

        plan = {
            "scope": scope,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "reason": reason,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "summary": self._build_summary(scope, start, end, blocks, backlog),
            "source_counts": {
                "candidate_tasks": len(candidates),
                "scheduled_blocks": len(blocks),
                "backlog": len(backlog),
            },
            "blocks": blocks,
            "backlog": backlog,
            "upcoming_events": self.store.upcoming_events(start, within_days=int(options.get("lookahead_days", 21))),
        }
        return plan

    def _collect_candidates(self, start: date, end: date, options: dict) -> list[dict]:
        candidates: list[dict] = []
        weak_snapshot = self._load_weak_snapshot()
        due_tasks = self._collect_due_review_tasks(weak_snapshot, end)
        weak_tasks = self._collect_weak_concept_tasks(weak_snapshot)
        exam_tasks = self._collect_exam_tasks(start, options)
        research_tasks = self._collect_research_tasks(start, options)

        candidates.extend(due_tasks)
        candidates.extend(weak_tasks)
        candidates.extend(exam_tasks)
        candidates.extend(research_tasks)
        candidates.sort(
            key=lambda task: (
                -task["score"],
                task["subject"],
                task["title"],
            )
        )
        return candidates

    def _collect_due_review_tasks(self, weak_snapshot: dict, end: date) -> list[dict]:
        tasks: list[dict] = []
        for subject, concepts in weak_snapshot.items():
            due_concepts: list[dict] = []
            priority_seed = 0
            for tag, info in concepts.items():
                next_review = info.get("sr_next_review")
                if not next_review:
                    continue
                try:
                    review_date = date.fromisoformat(next_review)
                except ValueError:
                    continue
                if review_date > end:
                    continue
                due_concepts.append({
                    "tag": tag,
                    "mastery": info.get("mastery", 0),
                    "priority": info.get("priority", "medium"),
                })
                priority_seed += {"high": 12, "medium": 7, "low": 3}.get(info.get("priority", "medium"), 5)

            if not due_concepts:
                continue

            due_concepts.sort(key=lambda item: (item["mastery"], item["tag"]))
            focus = [item["tag"] for item in due_concepts[:4]]
            avg_mastery = sum(item["mastery"] for item in due_concepts) / max(len(due_concepts), 1)
            score = 120 + priority_seed - int(avg_mastery * 25)
            tasks.append({
                "subject": subject,
                "title": "간격반복 복습 블록",
                "category": "due_review",
                "priority": "high",
                "score": score,
                "reason": f"복습 기한이 도래한 개념 {len(due_concepts)}개를 다시 점검합니다.",
                "focus": focus,
                "recommended_blocks": 2 if len(due_concepts) >= 5 else 1,
            })
        return tasks

    def _collect_weak_concept_tasks(self, weak_snapshot: dict) -> list[dict]:
        tasks: list[dict] = []
        for subject, concepts in weak_snapshot.items():
            ranked = sorted(
                concepts.items(),
                key=lambda item: (
                    {"high": 0, "medium": 1, "low": 2}.get(item[1].get("priority", "low"), 3),
                    item[1].get("mastery", 1),
                ),
            )
            if not ranked:
                continue
            focus = [tag for tag, _info in ranked[:3]]
            mastery_values = [info.get("mastery", 0) for _tag, info in ranked[:3]]
            avg_mastery = sum(mastery_values) / max(len(mastery_values), 1)
            tasks.append({
                "subject": subject,
                "title": "취약 개념 보강",
                "category": "weak_concept",
                "priority": "medium",
                "score": 80 - int(avg_mastery * 20),
                "reason": "정답률이 낮은 핵심 개념을 다시 정리하고 예시 문제를 풀어봅니다.",
                "focus": focus,
                "recommended_blocks": 1,
            })
        return tasks

    def _collect_exam_tasks(self, start: date, options: dict) -> list[dict]:
        tasks: list[dict] = []
        window_days = int(options.get("exam_focus_window_days", 21))
        for event in self.store.upcoming_events(start, within_days=window_days):
            days_left = int(event.get("days_left", window_days))
            priority = "high" if days_left <= 7 else "medium"
            score = 105 if days_left <= 7 else 92 if days_left <= 14 else 78
            blocks = 2 if days_left <= 7 else 1
            tasks.append({
                "subject": event["subject"],
                "title": f"{event['title']} 대비",
                "category": "exam_prep",
                "priority": priority,
                "score": score,
                "reason": f"{days_left}일 뒤 일정에 맞춰 핵심 범위와 예상 문제 유형을 점검합니다.",
                "focus": [event["title"], event.get("details", "")] if event.get("details") else [event["title"]],
                "recommended_blocks": blocks,
            })
        return tasks

    def _collect_research_tasks(self, start: date, options: dict) -> list[dict]:
        papers_enabled = self.config.get("papers", {}).get("enabled", False)
        pubmed_enabled = self.config.get("pubmed", {}).get("enabled", False)
        if not papers_enabled and not pubmed_enabled:
            return []

        research_subjects = set(options.get("research_subjects", []))
        if not research_subjects:
            return []

        tasks: list[dict] = []
        for event in self.store.upcoming_events(start, within_days=int(options.get("lookahead_days", 21))):
            subject = event.get("subject", "")
            if subject not in research_subjects:
                continue
            tasks.append({
                "subject": subject,
                "title": "연구 보강 블록",
                "category": "research_enrichment",
                "priority": "medium",
                "score": 58 if event.get("days_left", 99) <= 14 else 45,
                "reason": "심화 과목은 최신 리뷰/논문 맥락을 함께 보면 이해와 기억이 오래갑니다.",
                "focus": [event["title"], "review article", "recent papers"],
                "recommended_blocks": 1,
            })
        return tasks

    def _expand_task_units(self, candidates: list[dict]) -> list[dict]:
        units: list[dict] = []
        for task in candidates:
            count = max(1, int(task.get("recommended_blocks", 1)))
            for idx in range(count):
                unit = dict(task)
                unit["unit_index"] = idx + 1
                if idx > 0:
                    unit["score"] = max(1, unit["score"] - (idx * 5))
                units.append(unit)
        units.sort(key=lambda task: (-task["score"], task["subject"], task["title"]))
        return units

    def _pick_task(
        self,
        task_units: list[dict],
        subject_counts: dict[str, int],
        max_same_subject_per_day: int,
        interleaving_mode: str = "off",
        last_focus: list[str] | None = None,
        weak_snapshot: dict | None = None,
        slot_energy: str = "medium",
    ) -> dict | None:
        if not task_units:
            return None

        # 2.1: confusable 쌍 계산
        confusable_set: set[str] = set()
        if interleaving_mode in ("soft", "strict") and last_focus and weak_snapshot:
            confusable_set = self._get_confusable_set(last_focus, weak_snapshot)

        # 3.3: 에너지 + 인터리빙 통합 정렬
        _prio_map = {"high": 0, "medium": 1, "low": 2}

        def _combined_key(task: dict) -> tuple:
            base = task["score"]
            if confusable_set:
                base += 15 if any(c in confusable_set for c in task.get("focus", [])) else 0
            prio_num = _prio_map.get(task.get("priority", "medium"), 1)
            if slot_energy == "high":
                # 어려운 개념(high priority) 우선: prio_num 작을수록 bonus 크게
                energy_bonus = (2 - prio_num) * 20
            elif slot_energy == "low":
                # 쉬운 복습(low priority) 우선: prio_num 클수록 bonus 크게
                energy_bonus = prio_num * 20
            else:
                energy_bonus = 0
            return (-(base + energy_bonus), task["subject"], task["title"])

        task_units.sort(key=_combined_key)

        # subject 제한 준수하면서 선택
        fallback = None
        for idx, task in enumerate(task_units):
            count = subject_counts.get(task["subject"], 0)
            if count < max_same_subject_per_day:
                return task_units.pop(idx)
            if fallback is None:
                fallback = idx
        if fallback is not None:
            return task_units.pop(fallback)
        return None

    @staticmethod
    def _get_confusable_set(concepts: list[str], weak_snapshot: dict) -> set[str]:
        """최근 배치된 개념들의 confusable_with 파트너 집합을 반환."""
        confusable: set[str] = set()
        for subject_data in weak_snapshot.values():
            for concept, info in subject_data.items():
                if concept in concepts:
                    confusable.update(info.get("confusable_with", []))
        return confusable

    def _task_preview(self, task: dict) -> dict:
        return {
            "subject": task["subject"],
            "subject_display": self._display_subject(task["subject"]),
            "title": task["title"],
            "category": task["category"],
            "priority": task["priority"],
            "reason": task["reason"],
            "focus": task["focus"],
        }

    def _build_summary(
        self,
        scope: str,
        start: date,
        end: date,
        blocks: list[dict],
        backlog: list[dict],
    ) -> str:
        if not blocks:
            return "현재 일정 창에 배치된 학습 블록이 없습니다. 시험 일정이나 가용 시간을 먼저 조정하세요."

        category_labels = {
            "due_review": "복습",
            "weak_concept": "취약 개념",
            "exam_prep": "시험 대비",
            "research_enrichment": "연구 보강",
        }
        counts: dict[str, int] = {}
        for block in blocks:
            counts[block["category"]] = counts.get(block["category"], 0) + 1

        summary_parts = []
        for category, count in counts.items():
            summary_parts.append(f"{category_labels.get(category, category)} {count}블록")

        window_text = start.isoformat() if scope == "day" else f"{start.isoformat()} ~ {end.isoformat()}"
        backlog_text = f" 남은 후보 {len(backlog)}개는 다음 재계획 때 이어집니다." if backlog else ""
        return f"{window_text} 계획: " + ", ".join(summary_parts) + f" 중심으로 배치했습니다.{backlog_text}"

    def _load_weak_snapshot(self) -> dict:
        weak_path = self.paths.pipeline / "weak_concepts.json"
        if not weak_path.exists():
            return {}
        try:
            with open(weak_path, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}

    def _parse_date(self, value: str | None) -> date | None:
        if not value:
            return None
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None

    def _week_start(self, target: date) -> date:
        return target - timedelta(days=target.weekday())

    def _display_subject(self, subject: str) -> str:
        return self._subject_display.get(subject, subject)

    def _end_time(self, start_text: str, duration_min: int) -> str:
        hour, minute = [int(part) for part in start_text.split(":", 1)]
        start_dt = datetime.combine(date.today(), time(hour=hour, minute=minute))
        end_dt = start_dt + timedelta(minutes=duration_min)
        return end_dt.strftime("%H:%M")
