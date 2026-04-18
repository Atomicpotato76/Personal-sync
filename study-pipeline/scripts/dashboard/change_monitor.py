"""change_monitor.py -- 대시보드 시작 시 최근 변경 파일 감지 + 사용자 허가 흐름.

트리거: 대시보드 열때마다 (세션 시작 시 1회)
동작: 수정/추가된 파일 목록을 보여주고, 사용자 확인 후 파이프라인 진행.
수정 내역 없으면 자동 생략.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import streamlit as st

from path_utils import get_study_paths


# ── 마지막 확인 시점 저장 파일 ──
_LAST_CHECK_FILENAME = ".last_monitor_check"


def _get_last_check_path(pipeline_dir: Path) -> Path:
    return pipeline_dir / "cache" / _LAST_CHECK_FILENAME


def _load_last_check(pipeline_dir: Path) -> datetime:
    """마지막 모니터링 확인 시점 로드. 없으면 24시간 전."""
    path = _get_last_check_path(pipeline_dir)
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return datetime.fromisoformat(data["last_check"])
        except Exception:
            pass
    return datetime.now() - timedelta(hours=24)


def _save_last_check(pipeline_dir: Path) -> None:
    """현재 시점을 마지막 확인 시점으로 저장."""
    path = _get_last_check_path(pipeline_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"last_check": datetime.now().isoformat()}, ensure_ascii=False),
        encoding="utf-8",
    )


def scan_recent_changes(config: dict) -> list[dict]:
    """마지막 확인 이후 수정/추가된 파일 목록 반환.

    반환: [{path, name, subject, action, modified_at, size_kb}]
    """
    paths = get_study_paths(config)
    last_check = _load_last_check(paths.pipeline)
    folder_mapping = config.get("folder_mapping", {})
    excluded = {"퀴즈", "정리"}

    changes = []
    notes_base = paths.notes_base
    if not notes_base.exists():
        return []

    for subject_folder, subject_key in folder_mapping.items():
        subject_dir = notes_base / subject_folder
        if not subject_dir.exists():
            continue

        for f in subject_dir.rglob("*"):
            if f.is_dir():
                continue
            if f.suffix.lower() not in (".md", ".pdf", ".pptx"):
                continue
            # 출력 폴더 제외
            try:
                rel = f.relative_to(subject_dir)
            except ValueError:
                continue
            if any(p in excluded for p in rel.parts):
                continue

            mtime = datetime.fromtimestamp(f.stat().st_mtime)
            if mtime <= last_check:
                continue

            # 생성 시간과 수정 시간 비교 → 신규 vs 수정 판별
            ctime = datetime.fromtimestamp(f.stat().st_ctime)
            is_new = (ctime > last_check)

            changes.append({
                "path": str(f),
                "name": f.name,
                "subject": subject_key,
                "subject_display": subject_folder,
                "action": "new" if is_new else "modified",
                "modified_at": mtime.strftime("%Y-%m-%d %H:%M"),
                "size_kb": round(f.stat().st_size / 1024, 1),
            })

    # 수정 시간 역순 정렬
    changes.sort(key=lambda x: x["modified_at"], reverse=True)
    return changes


def render_change_monitor(config: dict) -> list[dict] | None:
    """대시보드 시작 시 변경 감지 패널을 렌더링.

    반환:
      - 사용자가 승인한 파일 리스트 → 파이프라인 실행 대상
      - None → 아직 확인 안 됨 (대기)
      - [] → 변경 없음 (자동 생략)
    """
    # 세션 시작 시 1회만 스캔
    if "monitor_checked" not in st.session_state:
        changes = scan_recent_changes(config)
        st.session_state["monitor_changes"] = changes
        st.session_state["monitor_checked"] = True
        st.session_state["monitor_approved"] = None

    changes = st.session_state.get("monitor_changes", [])

    # 변경 없으면 생략
    if not changes:
        return []

    # 이미 승인/거부됨
    if st.session_state.get("monitor_approved") is not None:
        return st.session_state["monitor_approved"]

    # ── 변경 감지 알림 패널 ──
    st.markdown("""
<div style="background:#FFF8EE; border-left:4px solid #C97830; padding:1rem 1.2rem;
            border-radius:0 4px 4px 0; margin-bottom:1.5rem;">
    <strong style="color:#1A3A45;">New changes detected</strong>
    <span style="color:#4A6A78; font-size:0.85rem; margin-left:0.5rem;">
        since last session
    </span>
</div>
""", unsafe_allow_html=True)

    # 과목별 그룹핑
    by_subject: dict[str, list[dict]] = {}
    for c in changes:
        by_subject.setdefault(c["subject_display"], []).append(c)

    selected_files: list[str] = []

    for subj, files in by_subject.items():
        new_count = sum(1 for f in files if f["action"] == "new")
        mod_count = sum(1 for f in files if f["action"] == "modified")
        summary_parts = []
        if new_count:
            summary_parts.append(f"new {new_count}")
        if mod_count:
            summary_parts.append(f"modified {mod_count}")

        with st.expander(f"{subj} — {', '.join(summary_parts)}", expanded=True):
            for f in files:
                icon = "+" if f["action"] == "new" else "~"
                col1, col2, col3 = st.columns([4, 2, 1])
                col1.write(f"`{icon}` {f['name']}")
                col2.caption(f"{f['modified_at']}  ·  {f['size_kb']} KB")
                checked = col3.checkbox(
                    "select",
                    value=True,
                    key=f"mon_{f['path']}",
                    label_visibility="collapsed",
                )
                if checked:
                    selected_files.append(f["path"])

    # ── 액션 버튼 ──
    col_run, col_skip, col_info = st.columns([1, 1, 3])
    with col_run:
        if st.button("Run Pipeline", type="primary", key="mon_run"):
            approved = [c for c in changes if c["path"] in selected_files]
            st.session_state["monitor_approved"] = approved
            # 마지막 확인 시점 갱신
            _save_last_check(get_study_paths(config).pipeline)
            st.rerun()
    with col_skip:
        if st.button("Skip", key="mon_skip"):
            st.session_state["monitor_approved"] = []
            _save_last_check(get_study_paths(config).pipeline)
            st.rerun()
    with col_info:
        st.caption(f"{len(selected_files)} / {len(changes)} files selected")

    return None  # 아직 대기 중
