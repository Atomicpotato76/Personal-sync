#!/usr/bin/env python3
"""path_utils.py -- 설정 기반 공용 경로 계산 유틸리티."""

from __future__ import annotations

from dataclasses import dataclass
import os
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

        mem0_cfg = cfg.setdefault("mem0", {})
        vector_store_cfg = mem0_cfg.setdefault("vector_store", {})
        vector_store_cfg["local_path"] = str(Path(cache_root_norm) / "mem0")

    if router_dir:
        llm_cfg = cfg.setdefault("llm", {})
        router_cfg = llm_cfg.setdefault("router", {})
        router_cfg["project_path"] = _normalize_path_str(router_dir, cwd)

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
