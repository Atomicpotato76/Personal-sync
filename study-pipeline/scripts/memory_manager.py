#!/usr/bin/env python3
"""memory_manager.py -- 로컬 JSON 기반 학습 메모리 관리 + 간격반복.

기능:
  1. weak_concepts.json / cache/learning_history.json 저장·조회
  2. 간격반복 알고리즘: SM-2(기본) 또는 FSRS (config scheduler: fsrs)
     - FSRS: fsrs 6.x Scheduler 사용, Card 상태 직렬화 보관
     - SM-2: 기존 sr_interval/sr_ease_factor 기반
"""

from __future__ import annotations

import json
import logging
import re
from collections import Counter
from copy import deepcopy
from datetime import datetime, timedelta
from math import sqrt
from pathlib import Path
from typing import Optional

from path_utils import get_study_paths

logger = logging.getLogger("pipeline")

# FSRS 선택적 임포트
try:
    from fsrs import Card, Rating, Scheduler, State as FsrsState
    _FSRS_AVAILABLE = True
except ImportError:
    _FSRS_AVAILABLE = False


class MemoryManager:
    """로컬 JSON 학습 메모리."""

    def __init__(self, config: dict):
        self.config = config
        paths = get_study_paths(config)
        self.vault = paths.vault
        self.pipeline_dir = paths.pipeline
        self.memory_cfg = config.get("memory", {})
        self.enabled = True
        self.user_id = self.memory_cfg.get("user_id", "student_main")

        # FSRS 스케줄러 (feature flag: config.scheduler = "fsrs")
        self._use_fsrs = (
            _FSRS_AVAILABLE
            and config.get("scheduler", "sm2") == "fsrs"
        )
        self._fsrs_scheduler = Scheduler() if self._use_fsrs else None
        if self._use_fsrs:
            logger.info("FSRS 스케줄러 활성화 (fsrs 6.x)")
        else:
            logger.info("SM-2 스케줄러 사용 중 (config.scheduler = sm2)")

        # 로컬 JSON
        self.weak_path = self.pipeline_dir / "weak_concepts.json"
        self.history_path = self.pipeline_dir / "cache" / "learning_history.json"
        self.pending_links_path = self.pipeline_dir / "cache" / "pending_links.json"
        self.note_index_path = self.pipeline_dir / "cache" / "note_index.json"
        self._weak_data = self._load_json(self.weak_path)
        self._history = self._load_json(self.history_path)
        self._note_index = self._load_json(self.note_index_path)

    # ── JSON I/O ──

    def _load_json(self, path: Path) -> dict:
        if not path.exists():
            return {}
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError as e:
            logger.error(f"JSON 파싱 실패 ({path.name}): {e}")
            corrupt_name = (
                f"{path.stem}.corrupt.{datetime.now().strftime('%Y%m%d_%H%M%S')}{path.suffix}"
            )
            corrupt_path = path.parent / corrupt_name
            try:
                path.rename(corrupt_path)
                logger.error(f"손상된 파일 격리: {corrupt_path.name}")
            except Exception as rename_err:
                logger.error(f"파일 격리 실패: {rename_err}")
            if path.name == "weak_concepts.json":
                raise RuntimeError(
                    f"critical data file corrupted and quarantined: {path.name}"
                ) from e
            return {}
        except Exception as e:
            logger.error(f"JSON 로드 실패 ({path.name}): {e}")
            return {}

    def _save_json(self, path: Path, data: dict):
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    # ── FSRS 카드 직렬화 ──

    @staticmethod
    def _card_to_dict(card: "Card") -> dict:
        return {
            "card_id": card.card_id,
            "state": card.state.value,
            "step": card.step,
            "stability": card.stability,
            "difficulty": card.difficulty,
            "due": card.due.isoformat(),
            "last_review": card.last_review.isoformat() if card.last_review else None,
        }

    @staticmethod
    def _dict_to_card(d: dict) -> "Card":
        return Card(
            card_id=d["card_id"],
            state=FsrsState(d["state"]),
            step=d.get("step", 0),
            stability=d.get("stability"),
            difficulty=d.get("difficulty"),
            due=datetime.fromisoformat(d["due"]),
            last_review=datetime.fromisoformat(d["last_review"]) if d.get("last_review") else None,
        )

    # ── 개념 마스터리 관리 ──

    # 2.4: 출처별 가중치
    _SOURCE_WEIGHTS: dict[str, float] = {
        "quiz": 1.0,
        "mock_exam": 1.5,
        "exam": 2.0,
    }

    def record_result(
        self,
        subject: str,
        concept_tags: list[str],
        result: str,
        source_note: str = "",
        memo: str = "",
        rating_override: Optional[str] = None,
        confidence: Optional[int] = None,
        error_category: Optional[str] = None,
        source: str = "quiz",
        weight: Optional[float] = None,
    ):
        """퀴즈/복습 결과를 기록.

        result: "correct" | "wrong" | "partial"
        rating_override: FSRS 전용 — "easy" | "good" | "hard" | "again"
        confidence: 1(전혀모름) ~ 5(확실) — 답 공개 전 자기 평가
        error_category: "knowledge_gap" | "confusion" | "careless" | "misread"
        source: "quiz" | "mock_exam" | "exam"  — 출처 (2.4)
        weight: 출처별 가중치 (None이면 source에서 자동 결정)
        """
        effective_weight = weight if weight is not None else self._SOURCE_WEIGHTS.get(source, 1.0)
        now = datetime.now().isoformat(timespec="seconds")

        if subject not in self._weak_data:
            self._weak_data[subject] = {}

        for tag in concept_tags:
            if tag not in self._weak_data[subject]:
                self._weak_data[subject][tag] = {
                    "encounter_count": 0,
                    "correct_count": 0,
                    "last_encounter": None,
                    "mastery": 0.0,
                    "priority": "high",
                    "related_notes": [],
                    "recent_mistakes": [],
                    # SM-2 파라미터 (항상 유지, FSRS 비활성 시 사용)
                    "sr_interval": 1,
                    "sr_ease_factor": 2.5,
                    "sr_next_review": None,
                    # FSRS 파라미터 (scheduler: fsrs 시 사용)
                    "fsrs_card": None,
                    "fsrs_next_review": None,
                    # 2.1: 인터리빙 파라미터
                    "confusable_with": [],
                    "interleaving_eligible": False,
                    # 2.3: 교차과목 링크
                    "cross_linked_concepts": [],
                    # 2.4: 가중치 누산기 (exam=2.0, mock_exam=1.5, quiz=1.0)
                    "weighted_score": 0.0,
                    "weighted_total": 0.0,
                }

            entry = self._weak_data[subject][tag]
            entry["encounter_count"] += 1
            entry["last_encounter"] = now

            # 2.1: 5회 만남 이후 인터리빙 대상으로 전환
            if entry["encounter_count"] >= 5 and not entry.get("interleaving_eligible", False):
                entry["interleaving_eligible"] = True

            if result == "correct":
                entry["correct_count"] += 1
                entry["weighted_score"] = entry.get("weighted_score", 0.0) + effective_weight
            elif result == "partial":
                entry["correct_count"] += 0.5
                entry["weighted_score"] = entry.get("weighted_score", 0.0) + effective_weight * 0.5
            entry["weighted_total"] = entry.get("weighted_total", 0.0) + effective_weight

            # 2.4: 가중치 반영 마스터리 (기존 quiz-only 대비 시험이 더 강하게 반영됨)
            if entry["weighted_total"] > 0:
                entry["mastery"] = round(entry["weighted_score"] / entry["weighted_total"], 2)
            elif entry["encounter_count"] > 0:
                entry["mastery"] = round(entry["correct_count"] / entry["encounter_count"], 2)

            if entry["mastery"] < 0.5:
                entry["priority"] = "high"
            elif entry["mastery"] < 0.8:
                entry["priority"] = "medium"
            else:
                entry["priority"] = "low"

            if source_note and source_note not in entry["related_notes"]:
                entry["related_notes"].append(source_note)

            if result in ("wrong", "partial"):
                entry["recent_mistakes"].append({
                    "date": now,
                    "result": result,
                    "memo": memo,
                    "confidence": confidence,
                    "error_category": error_category,
                })
                entry["recent_mistakes"] = entry["recent_mistakes"][-5:]

            # 1.2: 고신뢰 오답 3회 이상 → priority 강제 high
            self._check_overconfidence(entry)

            # 2.3: 교차과목 마스터리 30% 전파
            old_mastery = entry.get("mastery", 0.0)
            # 간격반복 업데이트 (feature flag)
            if self._use_fsrs:
                self._update_fsrs(entry, result, rating_override)
            else:
                self._update_spaced_repetition(entry, result)

            # 2.3: 교차과목 마스터리 30% 전파 (업데이트 이후)
            mastery_delta = entry.get("mastery", 0.0) - old_mastery
            if mastery_delta != 0.0:
                self._propagate_linked_mastery(subject, tag, mastery_delta)

        self._save_json(self.weak_path, self._weak_data)

        if "events" not in self._history:
            self._history["events"] = []
        self._history["events"].append({
            "timestamp": now,
            "subject": subject,
            "concepts": concept_tags,
            "result": result,
            "source": source_note,
            "confidence": confidence,
            "error_category": error_category,
            "record_source": source,
            "record_weight": effective_weight,
        })
        self._history["events"] = self._history["events"][-500:]
        self._save_json(self.history_path, self._history)

    # ── 신뢰도 과적합 감지 (1.2) ──

    @staticmethod
    def _check_overconfidence(entry: dict) -> None:
        """신뢰도 >= 4이면서 오답인 이벤트가 3회 이상이면 priority를 high로 강제."""
        mistakes = entry.get("recent_mistakes", [])
        overconfident = [
            m for m in mistakes
            if (m.get("confidence") or 0) >= 4
        ]
        if len(overconfident) >= 3 and entry.get("mastery", 1.0) < 0.6:
            entry["priority"] = "high"

    # ── SM-2 알고리즘 ──

    def _update_spaced_repetition(self, entry: dict, result: str):
        """SM-2 알고리즘 변형으로 간격반복 파라미터 갱신."""
        ef = entry.get("sr_ease_factor", 2.5)
        interval = entry.get("sr_interval", 1)

        if result == "correct":
            if interval == 1:
                interval = 6
            elif interval <= 3:
                interval = 6
            else:
                interval = int(interval * ef)
            ef = max(1.3, ef + 0.1)
        elif result == "partial":
            interval = max(1, int(interval * 0.7))
            ef = max(1.3, ef - 0.1)
        else:  # wrong
            interval = 1
            ef = max(1.3, ef - 0.3)

        entry["sr_interval"] = interval
        entry["sr_ease_factor"] = round(ef, 2)
        entry["sr_next_review"] = (datetime.now() + timedelta(days=interval)).strftime("%Y-%m-%d")

    # ── FSRS 알고리즘 ──

    _FSRS_RATING_MAP = {
        "correct": 3,   # Rating.Good
        "partial": 2,   # Rating.Hard
        "wrong": 1,     # Rating.Again
    }
    _FSRS_OVERRIDE_MAP = {
        "easy": 4,      # Rating.Easy
        "good": 3,      # Rating.Good
        "hard": 2,      # Rating.Hard
        "again": 1,     # Rating.Again
    }

    def _update_fsrs(
        self,
        entry: dict,
        result: str,
        rating_override: Optional[str] = None,
    ):
        """FSRS 6.x 스케줄러로 카드 상태 갱신."""
        rating_value = (
            self._FSRS_OVERRIDE_MAP.get(rating_override or "")
            or self._FSRS_RATING_MAP.get(result, 1)
        )
        rating = Rating(rating_value)

        card_dict = entry.get("fsrs_card")
        if card_dict:
            try:
                card = self._dict_to_card(card_dict)
            except Exception as e:
                logger.warning(f"FSRS 카드 복원 실패, 새 카드 생성: {e}")
                card = Card()
        else:
            card = Card()

        card, _ = self._fsrs_scheduler.review_card(card, rating)

        entry["fsrs_card"] = self._card_to_dict(card)
        entry["fsrs_next_review"] = card.due.astimezone().strftime("%Y-%m-%d")

    # ── 조회 ──

    def get_due_reviews(self, subject: Optional[str] = None) -> list[dict]:
        """오늘 복습해야 할 개념 목록.

        FSRS 활성 시 fsrs_next_review, SM-2 시 sr_next_review 기준.
        """
        today = datetime.now().strftime("%Y-%m-%d")
        due = []
        review_field = "fsrs_next_review" if self._use_fsrs else "sr_next_review"

        subjects = [subject] if subject else list(self._weak_data.keys())
        for subj in subjects:
            concepts = self._weak_data.get(subj, {})
            for tag, info in concepts.items():
                next_review = info.get(review_field)
                if next_review and next_review <= today:
                    due.append({
                        "subject": subj,
                        "concept": tag,
                        "mastery": info["mastery"],
                        "priority": info["priority"],
                        "last_encounter": info["last_encounter"],
                        "interval": info.get("sr_interval", 1),
                    })

        due.sort(key=lambda x: ({"high": 0, "medium": 1, "low": 2}.get(x["priority"], 3), x["mastery"]))
        return due

    def get_weak_concepts(self, subject: str, top_n: int = 10) -> list[dict]:
        """특정 과목의 취약 개념 목록 (mastery 낮은 순)."""
        concepts = self._weak_data.get(subject, {})
        sorted_concepts = sorted(concepts.items(), key=lambda x: x[1]["mastery"])
        return [
            {"concept": tag, **info}
            for tag, info in sorted_concepts[:top_n]
        ]

    def search_memory(self, query: str) -> list[dict]:
        """로컬 learning_history.json에서 관련 학습 기록 검색."""
        query_lower = query.lower().strip()
        if not query_lower:
            return []
        results = []
        for event in self._history.get("events", []):
            haystack = " ".join(
                str(value)
                for value in [
                    event.get("subject", ""),
                    event.get("source", ""),
                    " ".join(event.get("concepts", [])),
                ]
            ).lower()
            if query_lower in haystack:
                results.append(event)
        return results[-20:]

    def get_study_stats(self, subject: Optional[str] = None) -> dict:
        """학습 통계 요약."""
        subjects = [subject] if subject else list(self._weak_data.keys())
        stats = {}
        for subj in subjects:
            concepts = self._weak_data.get(subj, {})
            total = len(concepts)
            mastered = sum(1 for c in concepts.values() if c["mastery"] >= 0.8)
            struggling = sum(1 for c in concepts.values() if c["mastery"] < 0.5)
            avg_mastery = sum(c["mastery"] for c in concepts.values()) / max(total, 1)
            stats[subj] = {
                "total_concepts": total,
                "mastered": mastered,
                "struggling": struggling,
                "avg_mastery": round(avg_mastery, 2),
            }
        return stats

    def get_weak_snapshot(self, subject: Optional[str] = None) -> dict:
        """현재 weak_concepts 상태의 복사본을 반환."""
        if subject:
            return {subject: deepcopy(self._weak_data.get(subject, {}))}
        return deepcopy(self._weak_data)

    def get_history_snapshot(self) -> dict:
        """현재 learning_history의 복사본을 반환."""
        return deepcopy(self._history)

    # ── 3.4: 시험 사후 분석 ──

    def get_postmortem_summary(
        self,
        subject: str,
        exam_name: Optional[str] = None,
    ) -> dict:
        """시험 이벤트만 집계한 사후 분석 요약을 반환.

        반환:
          top_weak             — 시험에서 가장 자주 틀린 개념 (최대 5개)
          error_distribution   — error_category 별 빈도
          recommended_focus    — top_weak 개념의 현재 마스터리와 함께 정렬한 목록
        """
        _VALID_SOURCES = {"exam", "mock_exam"}
        _VALID_CATS = {"knowledge_gap", "confusion", "careless", "misread"}

        exam_events = [
            ev for ev in self._history.get("events", [])
            if ev.get("record_source") in _VALID_SOURCES
            and ev.get("subject") == subject
        ]

        concept_scores: dict[str, list[float]] = {}
        error_dist: dict[str, int] = {cat: 0 for cat in _VALID_CATS}

        for ev in exam_events:
            result = ev.get("result", "")
            score = 1.0 if result == "correct" else 0.5 if result == "partial" else 0.0
            ec = ev.get("error_category")
            if ec in error_dist:
                error_dist[ec] += 1
            for concept in ev.get("concepts", []):
                concept_scores.setdefault(concept, []).append(score)

        concept_avgs = {
            c: sum(s) / len(s) for c, s in concept_scores.items()
        }
        top_weak_pairs = sorted(concept_avgs.items(), key=lambda x: x[1])[:5]
        top_weak = [c for c, _ in top_weak_pairs]

        weak_subj = self._weak_data.get(subject, {})
        recommended_focus = [
            {
                "concept": concept,
                "exam_avg": round(avg, 2),
                "current_mastery": round(weak_subj.get(concept, {}).get("mastery", 0.0), 2),
            }
            for concept, avg in top_weak_pairs
        ]

        return {
            "subject": subject,
            "exam_name": exam_name,
            "total_exam_events": len(exam_events),
            "top_weak": top_weak,
            "error_distribution": error_dist,
            "recommended_focus": recommended_focus,
        }

    # ── 2.3: 노트 임베딩 / 유사도 검색 ──

    @staticmethod
    def _tokenize(text: str) -> Counter:
        words = re.findall(r'[가-힣a-zA-Z]{2,}', text.lower())
        return Counter(words)

    @staticmethod
    def _cosine(a: dict, b: dict) -> float:
        common = set(a) & set(b)
        if not common:
            return 0.0
        dot = sum(a[w] * b[w] for w in common)
        mag_a = sqrt(sum(v * v for v in a.values())) or 1.0
        mag_b = sqrt(sum(v * v for v in b.values())) or 1.0
        return dot / (mag_a * mag_b)

    def embed_note(self, note_path: str, note_text: str, subject: str) -> None:
        """노트를 bag-of-words로 인덱싱 (cache/note_index.json)."""
        freq = self._tokenize(note_text)
        total = max(sum(freq.values()), 1)
        tf = {w: round(c / total, 6) for w, c in freq.most_common(300)}
        self._note_index.setdefault("notes", {})[note_path] = {
            "subject": subject,
            "tf": tf,
            "indexed_at": datetime.now().isoformat(timespec="seconds"),
        }
        self._save_json(self.note_index_path, self._note_index)

    def find_similar_notes(
        self,
        query_text: str,
        top_n: int = 5,
        exclude_subject: Optional[str] = None,
    ) -> list[dict]:
        """쿼리와 유사한 노트 목록 반환 (TF cosine similarity 기준)."""
        query_tf = self._tokenize(query_text)
        total = max(sum(query_tf.values()), 1)
        q_vec = {w: c / total for w, c in query_tf.most_common(300)}

        results = []
        for path, info in self._note_index.get("notes", {}).items():
            if exclude_subject and info.get("subject") == exclude_subject:
                continue
            score = self._cosine(q_vec, info.get("tf", {}))
            if score > 0.0:
                results.append({
                    "note_path": path,
                    "subject": info.get("subject", ""),
                    "similarity": round(score, 4),
                })

        results.sort(key=lambda x: -x["similarity"])
        return results[:top_n]

    # ── 2.3: 교차과목 링크 관리 ──

    def add_pending_links(self, connections: list[dict], note_name: str) -> None:
        """CrossSubjectAgent 결과를 검토 대기 큐에 추가."""
        pending = self._load_json(self.pending_links_path)
        pending.setdefault("pending", [])
        now = datetime.now().isoformat(timespec="seconds")
        for conn in connections:
            pending["pending"].append({
                "note_name": note_name,
                "source_subject": conn.get("current_subject", ""),
                "target_subject": conn.get("other_subject", ""),
                "shared_concept": conn.get("shared_concept", ""),
                "relationship": conn.get("relationship", ""),
                "strength": conn.get("strength", "moderate"),
                "detected_at": now,
                "status": "pending",
            })
        self._save_json(self.pending_links_path, pending)

    def approve_link(
        self,
        source_subject: str,
        source_concept: str,
        target_subject: str,
        target_concept: str,
        strength: str = "moderate",
    ) -> bool:
        """개념 수준 교차과목 링크를 weak_concepts.json에 등록."""
        src_entry = self._weak_data.get(source_subject, {}).get(source_concept)
        if src_entry is None:
            return False
        src_entry.setdefault("cross_linked_concepts", [])
        link = {"subject": target_subject, "concept": target_concept, "strength": strength}
        if link not in src_entry["cross_linked_concepts"]:
            src_entry["cross_linked_concepts"].append(link)
        # 역방향도 등록
        tgt_entry = self._weak_data.get(target_subject, {}).get(target_concept)
        if tgt_entry is not None:
            tgt_entry.setdefault("cross_linked_concepts", [])
            rev = {"subject": source_subject, "concept": source_concept, "strength": strength}
            if rev not in tgt_entry["cross_linked_concepts"]:
                tgt_entry["cross_linked_concepts"].append(rev)
        self._save_json(self.weak_path, self._weak_data)
        return True

    def _propagate_linked_mastery(self, subject: str, tag: str, delta: float) -> None:
        """교차과목 링크 개념에 mastery delta의 30%를 전파 (범위 clamp [0,1])."""
        entry = self._weak_data.get(subject, {}).get(tag, {})
        for link in entry.get("cross_linked_concepts", []):
            t_subj = link.get("subject", "")
            t_tag = link.get("concept", "")
            t_entry = self._weak_data.get(t_subj, {}).get(t_tag)
            if t_entry is None:
                continue
            old_m = t_entry.get("mastery", 0.0)
            new_m = min(1.0, max(0.0, old_m + delta * 0.3))
            t_entry["mastery"] = round(new_m, 2)
            if t_entry["mastery"] < 0.5:
                t_entry["priority"] = "high"
            elif t_entry["mastery"] < 0.8:
                t_entry["priority"] = "medium"
            else:
                t_entry["priority"] = "low"
