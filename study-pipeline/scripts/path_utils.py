#!/usr/bin/env python3
"""path_utils.py -- 설정 기반 공용 경로 계산 유틸리티."""

from __future__ import annotations

from dataclasses import dataclass
import os
import platform
from pathlib import Path
import re as _re


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


def _convert_win_to_wsl(path_str: str) -> str:
    """Windows 경로(C:/... 또는 C:\\...)를 WSL 경로(/mnt/c/...)로 변환.

    Linux(WSL)에서 실행 중일 때만 변환하며, 그 외 환경에서는 원본 그대로 반환.
    """
    if platform.system() != "Linux":
        return path_str
    m = _re.match(r"^([A-Za-z]):[/\\]", path_str)
    if m:
        drive = m.group(1).lower()
        rest = path_str[2:].replace("\\", "/")
        return f"/mnt/{drive}{rest}"
    return path_str


def resolve_path(value: str | Path, base: Path) -> Path:
    """절대경로는 그대로, 상대경로는 base 기준으로 해석. Windows 형식 경로는 WSL 실행 시 자동 변환."""
    converted = _convert_win_to_wsl(str(value))
    path = Path(converted)
    if path.is_absolute():
        return path
    return (base / path).resolve()


def _env_or_default(env_name: str, default: str) -> str:
    value = os.environ.get(env_name, "").strip()
    return value or default


def _normalize_path_str(value: str | Path, base: Path) -> str:
    return str(resolve_path(value, base))


def apply_env_path_overrides(config: dict) -> dict:
    """config 경로 키를 환경변수로 override(미설정 시 config 기본값 유지)."""
    cfg = config or {}
    cwd = Path.cwd()

    default_vault = str(cfg.get("vault_path", ""))
    default_pipeline = str(cfg.get("pipeline_dir", ""))
    default_scripts = str(cfg.get("scripts_dir", ""))

    vault_path = _env_or_default("STUDY_VAULT_PATH", default_vault)
    pipeline_dir = _env_or_default("STUDY_PIPELINE_DIR", default_pipeline)
    scripts_dir = _env_or_default("STUDY_SCRIPTS_DIR", default_scripts)
    cache_root = os.environ.get("STUDY_CACHE_DIR", "").strip()
    router_dir = os.environ.get("PBL_ROUTER_DIR", "").strip()

    if vault_path:
        cfg["vault_path"] = _normalize_path_str(vault_path, cwd)
    if pipeline_dir:
        cfg["pipeline_dir"] = _normalize_path_str(pipeline_dir, cwd)
    if scripts_dir:
        cfg["scripts_dir"] = _normalize_path_str(scripts_dir, cwd)

    if cache_root:
        cache_root_norm = _normalize_path_str(cache_root, cwd)
        papers_cfg = cfg.setdefault("papers", {})
        papers_cfg["cache_dir"] = str(Path(cache_root_norm) / "papers")

    if router_dir:
        # External router support has been retired; keep the env var harmless.
        pass

    return cfg


def get_study_paths(config: dict) -> StudyPaths:
    """config에서 주요 경로를 정규화하여 반환."""
    config = apply_env_path_overrides(config)
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
