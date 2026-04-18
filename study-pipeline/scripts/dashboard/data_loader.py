"""data_loader.py -- 파이프라인 데이터 로딩 유틸리티."""
from __future__ import annotations

import json
from pathlib import Path

import streamlit as st

from path_utils import get_study_paths


def get_pipeline_paths(config: dict) -> dict:
    """config에서 주요 경로 추출."""
    paths = get_study_paths(config)
    return {
        "vault": paths.vault,
        "notes_base": paths.notes_base,
        "pipeline": paths.pipeline,
        "queue": paths.queue,
        "approved": paths.approved,
        "logs": paths.logs,
        "cache": paths.cache,
        "scripts": paths.scripts,
    }


@st.cache_data(ttl=15)
def load_weak_concepts(pipeline_dir: str) -> dict:
    path = Path(pipeline_dir) / "weak_concepts.json"
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {}


@st.cache_data(ttl=15)
def load_learning_history(cache_dir: str) -> dict:
    path = Path(cache_dir) / "learning_history.json"
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {}


def list_queue_files(queue_dir: Path) -> list[dict]:
    """queue/ 에서 퀴즈 JSON 목록 로드."""
    results = []
    if not queue_dir.exists():
        return results
    for jf in sorted(queue_dir.glob("*.json")):
        try:
            with open(jf, encoding="utf-8") as f:
                data = json.load(f)
            data["_path"] = str(jf)
            results.append(data)
        except Exception:
            pass
    return results


def list_note_files(vault: Path, notes_dir: str, subject_folder: str) -> list[Path]:
    """과목 폴더에서 .md 필기 파일 목록 (날짜 자연순 정렬)."""
    import re

    def _natural_key(path: Path) -> tuple:
        parts = [path.parent, path.stem]
        return tuple(
            tuple(
                int(tok) if tok.isdigit() else tok
                for tok in re.split(r"(\d+)", str(part))
            )
            for part in parts
        )

    base = vault / notes_dir / subject_folder
    if not base.exists():
        return []
    excluded = {"퀴즈", "정리"}
    files = []
    for f in base.rglob("*.md"):
        rel_parts = f.relative_to(base).parts
        if not any(p in excluded for p in rel_parts):
            files.append(f)
    return sorted(files, key=_natural_key)


def list_subject_pdfs(vault: Path, notes_dir: str, subject_folder: str) -> list[Path]:
    """과목 폴더 내 PDF 파일 목록 (재귀 탐색)."""
    base = vault / notes_dir / subject_folder
    if not base.exists():
        return []
    return sorted(base.rglob("*.pdf"))


def read_log_tail(log_dir: Path, n: int = 30) -> str:
    """pipeline.log 마지막 N줄 읽기."""
    path = log_dir / "pipeline.log"
    if not path.exists():
        return "(로그 파일 없음)"
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        return "\n".join(lines[-n:])
    except Exception as e:
        return f"(로그 읽기 실패: {e})"


def get_subject_display_names(config: dict) -> dict[str, str]:
    """과목 키 → 한글 표시명 매핑. (역방향 folder_mapping)"""
    mapping = config.get("folder_mapping", {})
    subjects = config.get("subjects", {})
    result = {}
    reverse = {v: k for k, v in mapping.items()}
    for key in subjects:
        result[key] = reverse.get(key, key)
    return result
