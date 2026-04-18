#!/usr/bin/env python3
"""memory_manager_legacy.py -- SM-2 간격반복 로직 보존 (롤백용).

memory_manager.py에서 scheduler: sm2 → fsrs 전환 시 이 파일이 원본 SM-2 구현을 보존.
롤백이 필요하면 config.yaml의 scheduler 값을 sm2로 되돌리면 됨.
직접 임포트하지 말 것 — memory_manager.py가 feature flag로 SM-2를 내부 호출함.
"""

from datetime import datetime, timedelta


def update_spaced_repetition_sm2(entry: dict, result: str) -> None:
    """SM-2 알고리즘 변형으로 간격반복 파라미터 갱신 (원본 v3 구현).

    Fields updated: sr_interval, sr_ease_factor, sr_next_review
    """
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
