#!/usr/bin/env python3
"""chapter_router.py -- 필기의 챕터 경계를 감지해 타겟 챕터 섹션만 추출."""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from source_extractor import SourceAggregator


_DEFAULT_LABEL_PATTERNS = [
    r"챕터\s*(\d+)",
    r"Chapter\s*(\d+)",
    r"Ch\.?\s*(\d+)",
    r"(\d+)\s*장",
    r"(\d+)\s*단원",
]

_STOPWORDS = {
    "the", "and", "that", "this", "with", "from", "have", "were", "been", "into", "for", "are", "is",
    "was", "to", "of", "in", "on", "at", "it", "as", "by", "be", "or", "an", "a", "등", "및", "에서",
    "으로", "대한", "있는", "한다", "한다", "있다", "그리고", "또는", "그", "이", "저", "수업", "정리",
}


@dataclass
class RoutingResult:
    text: str
    used_fallback: bool
    reason: str


class ChapterRouter:
    """명시 라벨 + semantic fallback 기반 챕터 라우터."""

    def __init__(self, config: dict, subject_cfg: dict, aggregator: "SourceAggregator") -> None:
        routing_cfg = config.get("chapter_routing", {})
        self.enabled: bool = routing_cfg.get("enabled", True)
        self.similarity_threshold: float = float(routing_cfg.get("similarity_threshold", 0.65))
        self.label_patterns: list[re.Pattern[str]] = [
            re.compile(pat, re.IGNORECASE)
            for pat in routing_cfg.get("label_patterns", _DEFAULT_LABEL_PATTERNS)
        ]
        self.subject_cfg = subject_cfg
        self.aggregator = aggregator

    def extract_for_chapter(self, note_text: str, target_chapter: int) -> RoutingResult:
        if not self.enabled:
            return RoutingResult(note_text, used_fallback=False, reason="disabled")

        paragraphs = self._split_paragraphs(note_text)
        if not paragraphs:
            return RoutingResult(note_text, used_fallback=False, reason="empty")

        label_assignments = self._assign_by_labels(paragraphs)
        found_labels = {chapter for chapter in label_assignments if chapter is not None}

        if found_labels:
            selected = [para for para, chapter in zip(paragraphs, label_assignments) if chapter == target_chapter]
            if selected:
                return RoutingResult("\n\n".join(selected).strip(), used_fallback=False, reason="label")

            if len(found_labels) == 1:
                only_label = next(iter(found_labels))
                if only_label == target_chapter:
                    return RoutingResult(note_text, used_fallback=False, reason="single_label_unchanged")

            return RoutingResult("", used_fallback=False, reason="label_mismatch")

        semantic = self._assign_by_semantic(paragraphs)
        if semantic is None:
            # fallback 실패 시 기존 동작 보장
            return RoutingResult(note_text, used_fallback=True, reason="semantic_unavailable_keep_original")

        smoothed = self._smooth_assignments(semantic)
        selected = [para for para, chapter in zip(paragraphs, smoothed) if chapter == target_chapter]
        if not selected:
            return RoutingResult("", used_fallback=True, reason="semantic_mismatch")
        return RoutingResult("\n\n".join(selected).strip(), used_fallback=True, reason="semantic")

    def _split_paragraphs(self, text: str) -> list[str]:
        chunks = re.split(r"\n\s*\n", text)
        return [chunk.strip() for chunk in chunks if chunk.strip()]

    def _detect_label(self, paragraph: str) -> Optional[int]:
        for pattern in self.label_patterns:
            m = pattern.search(paragraph)
            if m:
                return int(m.group(1))
        return None

    def _assign_by_labels(self, paragraphs: list[str]) -> list[Optional[int]]:
        assignments: list[Optional[int]] = []
        current: Optional[int] = None
        for para in paragraphs:
            detected = self._detect_label(para)
            if detected is not None:
                current = detected
            assignments.append(current)
        return assignments

    def _assign_by_semantic(self, paragraphs: list[str]) -> Optional[list[Optional[int]]]:
        profiles = self._build_chapter_profiles()
        if not profiles:
            return None

        assignments: list[Optional[int]] = []
        for para in paragraphs:
            vector = self._token_counter(para)
            if not vector:
                assignments.append(None)
                continue

            best_ch = None
            best_score = -1.0
            for chapter, profile in profiles.items():
                score = self._cosine_similarity(vector, profile)
                if score > best_score:
                    best_score = score
                    best_ch = chapter

            if best_ch is None or best_score < self.similarity_threshold:
                assignments.append(None)
            else:
                assignments.append(best_ch)

        # 대부분 미분류면 semantic 라우팅 실패로 간주
        assigned_count = sum(1 for item in assignments if item is not None)
        if assigned_count < max(1, len(paragraphs) // 3):
            return None
        return assignments

    def _build_chapter_profiles(self) -> dict[int, Counter[str]]:
        chapter_pages = self.subject_cfg.get("textbook_chapter_pages", {})
        profiles: dict[int, Counter[str]] = {}
        for ch_key, pages in chapter_pages.items():
            if not isinstance(ch_key, str) or not ch_key.startswith("ch"):
                continue
            if not isinstance(pages, list) or len(pages) != 2:
                continue
            chapter_num = int(ch_key[2:])
            text = self.aggregator.get_textbook_text(pages=(pages[0], pages[1]))
            if not text:
                continue
            token_counter = self._token_counter(text)
            if token_counter:
                profiles[chapter_num] = token_counter
        return profiles

    def _token_counter(self, text: str) -> Counter[str]:
        tokens = re.findall(r"[A-Za-z가-힣]{2,}", text.lower())
        return Counter(token for token in tokens if token not in _STOPWORDS)

    def _cosine_similarity(self, v1: Counter[str], v2: Counter[str]) -> float:
        common = set(v1) & set(v2)
        numerator = sum(v1[token] * v2[token] for token in common)
        v1_norm = math.sqrt(sum(value * value for value in v1.values()))
        v2_norm = math.sqrt(sum(value * value for value in v2.values()))
        if v1_norm == 0 or v2_norm == 0:
            return 0.0
        return numerator / (v1_norm * v2_norm)

    def _smooth_assignments(self, assignments: list[Optional[int]]) -> list[Optional[int]]:
        if not assignments:
            return assignments

        smoothed = assignments[:]

        # 1문단 outlier 제거
        for i in range(1, len(smoothed) - 1):
            prev_ch = smoothed[i - 1]
            next_ch = smoothed[i + 1]
            if prev_ch is not None and prev_ch == next_ch and smoothed[i] != prev_ch:
                smoothed[i] = prev_ch

        # 다른 챕터 전환은 최소 3문단 연속일 때만 허용
        i = 0
        while i < len(smoothed):
            curr = smoothed[i]
            j = i + 1
            while j < len(smoothed) and smoothed[j] == curr:
                j += 1

            run_len = j - i
            if curr is not None and i > 0 and run_len < 3:
                smoothed[i:j] = [smoothed[i - 1]] * run_len
            i = j

        return smoothed
