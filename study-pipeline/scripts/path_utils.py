#!/usr/bin/env python3
"""path_utils.py -- 설정 기반 공용 경로 계산 유틸리티."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class StudyPaths:
    vault: Path
    notes_base: Path
    pipeline: Path
    scripts: Path
    cache: Path
    queue: Path
    approved: Path
    rejected: Path
    logs: Path
    output_md: Path
    output_pdf: Path


def resolve_path(value: str | Path, base: Path) -> Path:
    """절대경로는 그대로, 상대경로는 base 기준으로 해석."""
    path = Path(value)
    if path.is_absolute():
        return path
    return (base / path).resolve()


def get_study_paths(config: dict) -> StudyPaths:
    """config에서 주요 경로를 정규화하여 반환."""
    cwd = Path.cwd()
    vault = resolve_path(config["vault_path"], cwd)
    notes_base = resolve_path(config["notes_dir"], vault)
    pipeline = resolve_path(config["pipeline_dir"], vault)
    scripts = resolve_path(config.get("scripts_dir", "scripts"), vault)

    return StudyPaths(
        vault=vault,
        notes_base=notes_base,
        pipeline=pipeline,
        scripts=scripts,
        cache=pipeline / "cache",
        queue=pipeline / "queue",
        approved=pipeline / "approved",
        rejected=pipeline / "rejected",
        logs=pipeline / "logs",
        output_md=pipeline / "output" / "md",
        output_pdf=pipeline / "output" / "pdf",
    )


def get_subject_dir(config: dict, subject: str) -> Path | None:
    """과목 키에 해당하는 노트 폴더 경로를 반환."""
    subject_cfg = config.get("subjects", {}).get(subject)
    if not subject_cfg:
        return None

    folder_name = subject_cfg.get("folder")
    if not folder_name:
        return None

    return get_study_paths(config).notes_base / folder_name
