#!/usr/bin/env python3
"""quiz_store.py -- 퀴즈 파일 로드/저장/승인 처리 공용 유틸."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from path_utils import get_study_paths


def load_quiz_json(path: Path) -> dict | None:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def save_quiz_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_vault_quiz_path(config: dict, subject: str, quiz_id: str) -> Path | None:
    subject_cfg = config.get("subjects", {}).get(subject)
    if not subject_cfg:
        return None

    folder_name = subject_cfg.get("folder")
    if not folder_name:
        return None

    paths = get_study_paths(config)
    return paths.notes_base / folder_name / "퀴즈" / f"{quiz_id}.md"


def remove_vault_quiz_copy(config: dict, subject: str, quiz_id: str) -> None:
    vault_quiz_path = get_vault_quiz_path(config, subject, quiz_id)
    if vault_quiz_path is not None and vault_quiz_path.exists():
        vault_quiz_path.unlink()


def find_quiz_json(config: dict, quiz_id: str) -> Path | None:
    paths = get_study_paths(config)
    for candidate in (paths.queue / f"{quiz_id}.json", paths.approved / f"{quiz_id}.json"):
        if candidate.exists():
            return candidate
    return None


def approve_quiz(config: dict, quiz_id: str, data: dict | None = None) -> Path | None:
    """queue의 퀴즈를 approved로 이동하고 vault 사본을 정리."""
    paths = get_study_paths(config)
    src_json = paths.queue / f"{quiz_id}.json"
    if not src_json.exists():
        return None

    if data is None:
        data = load_quiz_json(src_json)
        if data is None:
            return None

    data["status"] = "approved"
    paths.approved.mkdir(parents=True, exist_ok=True)

    dst_json = paths.approved / src_json.name
    save_quiz_json(dst_json, data)
    src_json.unlink()

    src_md = paths.queue / f"{quiz_id}.md"
    if src_md.exists():
        shutil.move(str(src_md), str(paths.approved / src_md.name))

    remove_vault_quiz_copy(config, data.get("subject", "unknown"), quiz_id)
    return dst_json
