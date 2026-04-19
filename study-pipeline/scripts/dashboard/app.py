"""Study Pipeline v3 Dashboard — Streamlit 대시보드 (Soft Aesthetic Glassmorphism ✨)."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import streamlit as st

# ── 경로 설정 ──
DASHBOARD_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = DASHBOARD_DIR.parent
CONFIG_PATH = SCRIPTS_DIR / "config.yaml"

if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from dashboard.config_editor import load_config, save_config, list_backups, restore_backup
from dashboard.data_loader import (
    get_pipeline_paths, load_weak_concepts, load_learning_history,
    list_queue_files, list_note_files, list_subject_pdfs, read_log_tail, get_subject_display_names,
)
from dashboard.pipeline_runner import PipelineRunner
from dashboard.quiz_manager import QuizManager
from dashboard.report_generator import generate_session_report
from dashboard.change_monitor import render_change_monitor
from env_utils import has_env_value

# ══════════════════════════════════════════════════════════════
# App Config
# ══════════════════════════════════════════════════════════════

st.set_page_config(page_title="Study Pipeline", page_icon=None, layout="wide")


def _inject_styles() -> None:
    st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;600;700&family=JetBrains+Mono:wght@400;700&display=swap');

/* ─── 기본 배경 (Soft Warm Aesthetic) ───────────────────── */
.stApp { 
    background: radial-gradient(circle at 50% 0%, #F5EDE0 0%, #E8DCC8 85%) !important;
    font-family: 'Space Grotesk', sans-serif !important;
}

/* ─── 전체 기본 텍스트 ───────────────────────────────────── */
.stApp, .stApp p, .stApp span, .stApp div,
.stApp label, .stApp li { color: #1A2E38 !important; }

/* ─── 사이드바 (Dark Teal Glass) ───────────────────────────── */
[data-testid="stSidebar"] { 
    background: rgba(26, 58, 69, 0.9) !important; /* #1A3A45 base */
    backdrop-filter: blur(16px);
    -webkit-backdrop-filter: blur(16px);
    border-right: 1px solid rgba(196, 168, 130, 0.3); /* #C4A882 base */
}
[data-testid="stSidebar"] * { color: #EAD5B8 !important; }
[data-testid="stSidebar"] h1,
[data-testid="stSidebar"] h2,
[data-testid="stSidebar"] h3,
[data-testid="stSidebar"] strong { 
    color: #F5EDE0 !important; 
    font-weight: 600 !important; 
    text-shadow: 0 0 10px rgba(234, 213, 184, 0.3);
}
[data-testid="stSidebar"] hr { border-color: rgba(196, 168, 130, 0.3) !important; }

/* ─── 메인 콘텐츠 여백 ───────────────────────────────────── */
.main .block-container { padding: 2rem 3rem 3rem; max-width: 1280px; }

/* ─── 헤더 (Soft Amber Glow) ───────────────────────────────────── */
h1 {
    color: #1A3A45 !important;
    font-family: 'Space Grotesk', sans-serif !important;
    font-weight: 700 !important;
    font-size: 2.2rem !important;
    letter-spacing: -0.02em;
    text-shadow: 0 4px 15px rgba(201, 120, 48, 0.2);
    border-bottom: 1.5px solid rgba(201, 120, 48, 0.5); /* #C97830 */
    padding-bottom: 0.6rem;
    margin-bottom: 1.5rem !important;
}
h2 {
    color: #2B5769 !important;
    font-family: 'Space Grotesk', sans-serif !important;
    font-weight: 600 !important;
    font-size: 1.1rem !important;
    letter-spacing: 0.05em;
    text-transform: uppercase;
    margin-top: 1.8rem !important;
}
h3 { color: #C97830 !important; font-weight: 600 !important; }

/* ─── 메트릭 카드 (Light Glass Panels) ─────────────────────────── */
[data-testid="metric-container"] {
    background: rgba(255, 255, 255, 0.65) !important;
    backdrop-filter: blur(12px) !important;
    border: 1px solid rgba(212, 196, 170, 0.6) !important; /* #D4C4AA */
    border-radius: 12px !important;
    padding: 1rem 1.4rem;
    box-shadow: 0 8px 32px rgba(26, 46, 56, 0.04), inset 0 0 20px rgba(255, 255, 255, 0.5);
}
[data-testid="stMetricLabel"] p { 
    color: #4A6A78 !important; 
    font-family: 'JetBrains Mono', monospace !important;
    font-size: 0.75rem !important;
    text-transform: uppercase; 
    letter-spacing: 0.1em; 
}
[data-testid="stMetricValue"] div { 
    color: #1A3A45 !important; 
    font-weight: 700 !important;
    font-size: 2.2rem !important; 
}

/* ─── 버튼 ───────────────────────────────────────────────── */
.stButton > button { 
    border-radius: 8px !important; 
    font-family: 'Space Grotesk', sans-serif !important;
    font-weight: 600 !important;
    text-transform: uppercase !important;
    transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1) !important;
}
.stButton > button[kind="primary"] { 
    background: linear-gradient(135deg, #C97830 0%, #A85F20 100%) !important;
    border: none !important; 
    color: #FFFFFF !important; 
    box-shadow: 0 4px 15px rgba(201, 120, 48, 0.3) !important;
}
.stButton > button[kind="primary"]:hover { 
    transform: translateY(-2px) !important;
    box-shadow: 0 8px 25px rgba(201, 120, 48, 0.4) !important;
    filter: brightness(1.05) !important;
}
.stButton > button:not([kind="primary"]) { 
    background: rgba(255, 255, 255, 0.5) !important;
    border: 1px solid rgba(201, 120, 48, 0.4) !important;
    color: #1A3A45 !important; 
}
.stButton > button:not([kind="primary"]):hover { 
    background: rgba(255, 255, 255, 0.8) !important;
    border-color: #C97830 !important;
    color: #C97830 !important;
    box-shadow: 0 4px 12px rgba(201, 120, 48, 0.15) !important;
}

/* ─── 입력 위젯 (Light Translucent) ───────────────────────── */
.stSelectbox > div > div,
.stMultiSelect > div > div,
.stTextInput > div > div,
.stNumberInput > div > div,
.stTextArea > div > div { 
    background: rgba(255, 255, 255, 0.6) !important;
    border: 1px solid rgba(212, 196, 170, 0.8) !important; 
    border-radius: 8px !important; 
}
.stSelectbox > div > div:focus-within, 
.stTextInput > div > div:focus-within,
.stTextArea > div > div:focus-within {
    border-color: #C97830 !important;
    box-shadow: 0 0 10px rgba(201, 120, 48, 0.2) !important;
}
.stSelectbox p, .stMultiSelect span,
.stTextInput p, .stTextInput input,
.stTextArea p, .stTextArea textarea,
.stNumberInput input { 
    color: #1A2E38 !important; 
    font-family: 'JetBrains Mono', monospace !important;
}
.stRadio > div { gap: 0.4rem; }
.stRadio label p { color: #1A2E38 !important; }
[data-testid="stSidebar"] .stRadio > div { gap: 0.55rem; }
[data-testid="stSidebar"] .stRadio label {
    background: rgba(245, 237, 224, 0.08) !important;
    border: 1px solid rgba(234, 213, 184, 0.18) !important;
    border-radius: 10px !important;
    padding: 0.45rem 0.65rem !important;
    transition: all 0.2s ease !important;
}
[data-testid="stSidebar"] .stRadio label:hover {
    background: rgba(245, 237, 224, 0.14) !important;
    border-color: rgba(234, 213, 184, 0.34) !important;
}
[data-testid="stSidebar"] .stRadio label p {
    color: #F5EDE0 !important;
    font-weight: 600 !important;
}

/* ─── 탭 ─────────────────────────────────────────────────── */
.stTabs [data-baseweb="tab-list"] { 
    background: transparent;
    border-bottom: 1px solid rgba(212, 196, 170, 0.8); 
    gap: 0; 
}
.stTabs [data-baseweb="tab"] { 
    background: transparent; 
    border: none; 
    border-radius: 0;
    padding: 0.8rem 1.4rem; 
    color: #7A8A90 !important; 
    font-family: 'Space Grotesk', sans-serif !important;
}
.stTabs [aria-selected="true"] { 
    color: #C97830 !important;
    border-bottom: 2px solid #C97830 !important;
    background: transparent !important; 
}

/* ─── 익스팬더 ───────────────────────────────────────────── */
details { 
    background: rgba(255, 255, 255, 0.65) !important;
    backdrop-filter: blur(12px) !important;
    border: 1px solid rgba(212, 196, 170, 0.6) !important;
    border-radius: 12px !important; 
}
summary { 
    color: #1A3A45 !important; 
    font-weight: 600 !important;
    padding: 0.8rem 1.2rem !important; 
}
details p, details span, details div { color: #1A2E38 !important; }

/* ─── 데이터프레임 ───────────────────────────────────────── */
.stDataFrame { 
    border: 1px solid rgba(212, 196, 170, 0.8); 
    border-radius: 12px; 
    overflow: hidden;
}

/* ─── 알림 박스 (Soft Alerts) ────────────────────────────── */
[data-testid="stInfo"] { background: rgba(43, 87, 105, 0.1) !important; border-left-color: #2B5769 !important; }
[data-testid="stInfo"] * { color: #1A3A45 !important; }
[data-testid="stSuccess"] { background: rgba(34, 197, 94, 0.1) !important; border-left-color: #22C55E !important; }
[data-testid="stWarning"] { background: rgba(201, 120, 48, 0.1) !important; border-left-color: #C97830 !important; }
[data-testid="stError"] { background: rgba(239, 68, 68, 0.1) !important; border-left-color: #ef4444 !important; }

/* ─── 프로그레스 바 ──────────────────────────────────────── */
[data-testid="stProgressBar"] > div > div { background: linear-gradient(90deg, #C97830 0%, #EAD5B8 100%) !important; }

/* ─── 코드 블록 ──────────────────────────────────────────── */
.stCode, pre { 
    background: rgba(26, 46, 56, 0.9) !important; /* #1A2E38 */
    border: 1px solid rgba(212, 196, 170, 0.4) !important;
    border-radius: 8px; 
}
.stCode *, pre * { 
    color: #EAD5B8 !important; 
    font-family: 'JetBrains Mono', monospace !important;
}

/* ─── 구분선 & 캡션 ──────────────────────────────────────── */
hr { border-color: rgba(212, 196, 170, 0.6) !important; margin: 1.5rem 0 !important; }
.stCaption p, [data-testid="stCaptionContainer"] p { 
    color: #7A8A90 !important; 
    font-family: 'JetBrains Mono', monospace !important;
}

/* ─── 차트 컨테이너 ──────────────────────────────────────── */
.stPlotlyChart { 
    background: rgba(255, 255, 255, 0.6) !important; 
    border: 1px solid rgba(212, 196, 170, 0.8);
    border-radius: 12px; 
    padding: 0.5rem; 
}

/* ─── 체크박스·슬라이더 레이블 ──────────────────────────── */
.stCheckbox label p,
.stSlider label p,
.stNumberInput label p,
.stTextArea label p { color: #1A2E38 !important; }

/* ─── 파이프라인 상태 표시 (가독성 강화) ─────────────────── */
.pipeline-status {
    display: block;
    margin-top: 0.7rem;
    margin-bottom: 0.35rem;
    padding: 0.72rem 0.9rem;
    border-radius: 10px;
    border-left: 6px solid transparent;
    background: rgba(255, 255, 255, 0.86);
    color: #10212A !important; /* high contrast on light bg */
    font-size: 1.14rem;
    font-weight: 700;
    line-height: 1.4;
    letter-spacing: 0.01em;
}
.pipeline-status--running { border-left-color: #007bff; }
.pipeline-status--success { border-left-color: #28a745; }
.pipeline-status--error { border-left-color: #dc3545; }
</style>
""", unsafe_allow_html=True)


def get_config() -> dict:
    if "config" not in st.session_state:
        st.session_state["config"] = load_config(CONFIG_PATH)
    return st.session_state["config"]


def get_runner() -> PipelineRunner:
    if "runner" not in st.session_state:
        st.session_state["runner"] = PipelineRunner(SCRIPTS_DIR)
    return st.session_state["runner"]


# ══════════════════════════════════════════════════════════════
# Sidebar Navigation
# ══════════════════════════════════════════════════════════════

_inject_styles()

PAGES = {
    "Dashboard":  "dashboard",
    "Pipeline":   "pipeline",
    "Hermes":     "hermes",
    "Quiz Review": "quiz",
    "Analytics":  "analytics",
    "Report":     "report",
    "Settings":   "settings",
}

with st.sidebar:
    st.markdown("### Study Pipeline")
    st.divider()
    page = st.radio("Navigation", list(PAGES.keys()), label_visibility="collapsed")
    st.divider()

    config = get_config()
    paths = get_pipeline_paths(config)
    queue_count = len(list(paths["queue"].glob("*.json"))) if paths["queue"].exists() else 0
    st.caption(f"queue  ·  {queue_count}")

    runner = get_runner()
    if runner.is_running:
        st.caption("pipeline running")

selected = PAGES[page]


# ══════════════════════════════════════════════════════════════
# Page 1: Dashboard
# ══════════════════════════════════════════════════════════════

def render_dashboard():
    st.header("Dashboard")
    config = get_config()

    # ── 자동 변경 감지 (세션 시작 시 1회) ──
    approved = render_change_monitor(config)
    if approved is None:
        # 사용자 응답 대기 중 — 아래 대시보드 렌더링 중단
        return
    if approved:
        # 사용자가 승인한 파일 → 파이프라인 자동 실행
        runner = get_runner()
        if not runner.is_running:
            for item in approved:
                runner.start_note(item["path"])
            st.success(f"{len(approved)}개 파일 파이프라인 실행 시작!")

    paths = get_pipeline_paths(config)
    subjects = get_subject_display_names(config)
    weak = load_weak_concepts(str(paths["pipeline"]))

    # ── Metrics ──
    cols = st.columns(4)
    total = sum(len(concepts) for concepts in weak.values())
    mastered = sum(1 for s in weak.values() for c in s.values() if c.get("mastery", 0) >= 0.8)
    struggling = sum(1 for s in weak.values() for c in s.values() if c.get("mastery", 0) < 0.5)
    avg = sum(c.get("mastery", 0) for s in weak.values() for c in s.values()) / max(total, 1)

    cols[0].metric("Concepts", total)
    cols[1].metric("Mastered", mastered, help="mastery ≥ 0.8")
    cols[2].metric("Struggling", struggling, help="mastery < 0.5")
    cols[3].metric("Avg Mastery", f"{avg:.0%}")

    # ── Due Reviews ──
    st.subheader("Today")
    from datetime import datetime
    today = datetime.now().strftime("%Y-%m-%d")
    due = []
    for subj, concepts in weak.items():
        for tag, info in concepts.items():
            if info.get("sr_next_review") and info["sr_next_review"] <= today:
                due.append({
                    "과목": subjects.get(subj, subj),
                    "개념": tag,
                    "mastery": f"{info['mastery']:.0%}",
                    "priority": info["priority"],
                    "interval": f"{info.get('sr_interval', '?')}일",
                })

    if due:
        import pandas as pd
        st.dataframe(pd.DataFrame(due), width="stretch", hide_index=True)
    else:
        st.info("오늘 복습할 항목이 없습니다.")

    # ── Queue ──
    queue_files = list_queue_files(paths["queue"])
    if queue_files:
        st.subheader(f"Queue  ·  {len(queue_files)}")
        for q in queue_files[:5]:
            items = q.get("items", [])
            st.caption(f"{q.get('id', '?')}  ·  {q.get('subject', '?')}  ·  {len(items)} items")

    # ── Recent Log ──
    with st.expander("Pipeline Log", expanded=False):
        log_text = read_log_tail(paths["logs"], 25)
        st.code(log_text, language="log")


# ══════════════════════════════════════════════════════════════
# Page 2: Pipeline Runner
# ══════════════════════════════════════════════════════════════

def render_pipeline():
    st.header("Pipeline")
    config = get_config()
    paths = get_pipeline_paths(config)
    subjects = get_subject_display_names(config)
    runner = get_runner()

    mode = st.radio(
        "Mode",
        ["Single Note", "Chapter Synthesis", "Folder", "소스 직접 선택"],
        horizontal=True,
    )

    run_args = None  # 실행 준비가 안 된 경우 None으로 보호

    if mode == "Single Note":
        subj_key = st.selectbox("과목", list(subjects.keys()), format_func=lambda k: f"{subjects[k]} ({k})")
        subj_cfg = config["subjects"][subj_key]
        notes = list_note_files(paths["vault"], config["notes_dir"], subj_cfg["folder"])
        if notes:
            selected_note = st.selectbox("노트 파일", notes, format_func=lambda p: p.name)
            run_args = ("note", str(selected_note))
        else:
            st.warning("필기 파일이 없습니다.")

    elif mode == "Chapter Synthesis":
        subj_key = st.selectbox("과목", list(subjects.keys()), format_func=lambda k: f"{subjects[k]} ({k})")
        chapters = list(config["subjects"][subj_key].get("textbook_chapter_pages", {}).keys())
        if chapters:
            chapter = st.selectbox("Chapter", chapters)
            run_args = ("chapter", subj_key, chapter)
        else:
            st.warning("textbook_chapter_pages 설정이 없습니다.")

    elif mode == "Folder":
        folder = st.text_input("폴더 경로", str(paths["notes_base"]))
        run_args = ("folder", folder)

    else:  # 소스 직접 선택
        subj_key = st.selectbox(
            "과목",
            list(subjects.keys()),
            format_func=lambda k: f"{subjects[k]} ({k})",
            key="src_subject",
        )
        subj_cfg = config["subjects"][subj_key]
        subject_folder = subj_cfg["folder"]

        # ── PDF 목록 ──
        all_pdfs = list_subject_pdfs(paths["vault"], config["notes_dir"], subject_folder)
        _AUTO = "(config 기본값)"
        pdf_options = [_AUTO] + [str(p) for p in all_pdfs]

        def _pdf_label(p: str) -> str:
            return _AUTO if p == _AUTO else Path(p).name

        col_tb, col_sl = st.columns(2)
        with col_tb:
            sel_textbook = st.selectbox(
                "교재 PDF",
                pdf_options,
                format_func=_pdf_label,
                key="src_textbook",
                help="선택하지 않으면 config에 설정된 교재를 사용합니다.",
            )
        with col_sl:
            sel_slides = st.selectbox(
                "강의자료 PDF",
                pdf_options,
                format_func=_pdf_label,
                key="src_slides",
                help="선택하지 않으면 config에 설정된 강의자료를 사용합니다.",
            )

        # ── 필기본 다중 선택 ──
        notes = list_note_files(paths["vault"], config["notes_dir"], subject_folder)
        if not notes:
            st.warning("필기 파일이 없습니다.")
        else:
            sel_notes = st.multiselect(
                "필기본 (여러 개 선택 가능)",
                notes,
                format_func=lambda p: str(p.relative_to(paths["vault"])),
                key="src_notes",
            )
            if sel_notes:
                tb_arg = None if sel_textbook == _AUTO else sel_textbook
                sl_arg = None if sel_slides == _AUTO else sel_slides
                run_args = ("sources", [str(n) for n in sel_notes], tb_arg, sl_arg, subj_key)

                # 선택 요약
                st.caption(
                    f"필기 {len(sel_notes)}개"
                    + (f" | 교재: {Path(tb_arg).name}" if tb_arg else " | 교재: config 기본값")
                    + (f" | 강의자료: {Path(sl_arg).name}" if sl_arg else " | 강의자료: config 기본값")
                )
            else:
                st.info("필기본을 하나 이상 선택하세요.")

    # ── Run Button ──
    col1, col2 = st.columns([1, 4])
    with col1:
        run_disabled = runner.is_running or run_args is None
        if st.button("▶ 실행", disabled=run_disabled, type="primary", width="stretch"):
            if run_args[0] == "note":
                runner.start_note(run_args[1])
            elif run_args[0] == "chapter":
                runner.start_chapter(run_args[1], run_args[2])
            elif run_args[0] == "sources":
                runner.start_with_sources(run_args[1], run_args[2], run_args[3], run_args[4])
            else:
                runner.start_folder(run_args[1])
            st.session_state["pipeline_output"] = []

    with col2:
        if runner.is_running and st.button("⏹ 중지"):
            runner.stop()

    def _render_pipeline_status(text: str, state: str) -> None:
        state_class = {
            "running": "pipeline-status--running",
            "success": "pipeline-status--success",
            "error": "pipeline-status--error",
        }.get(state, "pipeline-status--running")
        st.markdown(
            f'<div class="pipeline-status {state_class}">{text}</div>',
            unsafe_allow_html=True,
        )

    # ── Progress ──
    if runner.is_running or "pipeline_output" in st.session_state:
        new_lines = runner.get_new_lines()
        if "pipeline_output" not in st.session_state:
            st.session_state["pipeline_output"] = []
        st.session_state["pipeline_output"].extend(new_lines)

        output_lines = st.session_state["pipeline_output"]

        # 진행률 바
        current_step = 0
        total_steps = 10
        for line in reversed(output_lines):
            parsed = PipelineRunner.parse_step(line)
            if parsed:
                current_step, total_steps = parsed
                break
        st.progress(current_step / total_steps, text=f"Step {current_step}/{total_steps}")
        _render_pipeline_status(
            f"진행 상태: Step {current_step}/{total_steps} (실행 중)",
            "running",
        )

        # 출력
        st.code("\n".join(output_lines[-40:]), language="log")

        if runner.is_running:
            time.sleep(1.5)
            st.rerun()
        elif runner.return_code is not None:
            if runner.return_code == 0:
                _render_pipeline_status("진행 상태: 완료 (성공)", "success")
                st.success("파이프라인 완료!")
            else:
                _render_pipeline_status(
                    f"진행 상태: 실패 (exit code: {runner.return_code})",
                    "error",
                )
                st.error(f"파이프라인 실패 (exit code: {runner.return_code})")


# ══════════════════════════════════════════════════════════════
# Page 3: Quiz Review
# ══════════════════════════════════════════════════════════════

def render_quiz():
    st.header("Quiz Review")
    config = get_config()
    qm = QuizManager(config)

    # ── 교재 연습문제 생성 탭 ──
    tab_review, tab_textbook = st.tabs(["Quiz Review", "Textbook Exercises"])

    with tab_textbook:
        _render_textbook_quiz_generator(config)

    with tab_review:
        _render_quiz_review(config, qm)


def _render_textbook_quiz_generator(config: dict):
    """교재 챕터별 연습문제 → queue 생성 UI."""
    from textbook_quiz import generate_textbook_quiz_to_queue, generate_all_chapters_quiz

    subjects = get_subject_display_names(config)
    col_subj, col_ch = st.columns(2)

    with col_subj:
        subj_key = st.selectbox(
            "과목",
            list(subjects.keys()),
            format_func=lambda k: f"{subjects[k]} ({k})",
            key="tb_subject",
        )
    with col_ch:
        chapters = list(config["subjects"].get(subj_key, {}).get("textbook_chapter_pages", {}).keys())
        ch_options = ["(전체)"] + chapters
        selected_ch = st.selectbox("Chapter", ch_options, key="tb_chapter")

    # 교재 존재 확인
    subj_cfg = config["subjects"].get(subj_key, {})
    if not subj_cfg.get("textbook"):
        st.warning(f"{subjects.get(subj_key, subj_key)}: 교재 PDF가 설정되어 있지 않습니다.")
        return
    if not chapters:
        st.warning("textbook_chapter_pages 설정이 없습니다.")
        return

    st.caption("교재 연습문제를 추출하여 Quiz Review에 등록합니다. "
               "관련 이미지는 교재/강의자료에서 자동으로 크롭됩니다.")

    if st.button("Generate Textbook Quiz", type="primary", key="tb_gen"):
        with st.spinner("교재 연습문제 추출 + 이미지 크롭 중..."):
            try:
                if selected_ch == "(전체)":
                    results = generate_all_chapters_quiz(subj_key, config)
                    if results:
                        st.success(f"{len(results)}개 챕터 퀴즈 생성 완료! Quiz Review 탭에서 확인하세요.")
                    else:
                        st.error("퀴즈 생성 실패. 교재 PDF와 페이지 매핑을 확인하세요.")
                else:
                    result = generate_textbook_quiz_to_queue(subj_key, selected_ch, config)
                    if result:
                        st.success(f"{selected_ch.upper()} 퀴즈 생성 완료! → {result.name}")
                    else:
                        st.error(f"{selected_ch} 퀴즈 생성 실패.")
            except Exception as e:
                st.error(f"오류: {e}")
                import traceback
                st.code(traceback.format_exc(), language="python")

    # ── 기존 교재 퀴즈 목록 ──
    paths = get_pipeline_paths(config)
    queue_files = list(paths["queue"].glob("textbook_*.json")) if paths["queue"].exists() else []
    if queue_files:
        st.divider()
        st.subheader(f"Generated Textbook Quizzes ({len(queue_files)})")
        for qf in sorted(queue_files, reverse=True):
            try:
                data = json.loads(qf.read_text(encoding="utf-8"))
                ch = data.get("chapter", "?")
                subj = data.get("subject", "?")
                n_items = len(data.get("items", []))
                n_imgs = data.get("image_count", 0)
                st.caption(f"`{qf.name}` — {subjects.get(subj, subj)} {ch.upper()} · "
                           f"{n_items} problems · {n_imgs} images")
            except Exception:
                st.caption(f"`{qf.name}`")


def _render_quiz_review(config: dict, qm: QuizManager):
    """기존 Quiz Review 로직."""
    queue = qm.list_queue()

    if not queue:
        st.info("리뷰할 퀴즈가 없습니다. 파이프라인을 실행하거나 Textbook Exercises 탭에서 교재 퀴즈를 생성하세요.")
        return

    # ── Quiz Selector ──
    quiz_options = {q["id"]: q for q in queue}
    selected_id = st.selectbox(
        "퀴즈 선택",
        list(quiz_options.keys()),
        format_func=lambda qid: f"{qid} ({quiz_options[qid].get('subject', '?')} / {len(quiz_options[qid].get('items', []))} items)",
    )
    quiz = quiz_options[selected_id]
    items = quiz.get("items", [])

    # ── Item Navigation ──
    if "quiz_item_idx" not in st.session_state:
        st.session_state["quiz_item_idx"] = 0
    idx = st.session_state["quiz_item_idx"]
    idx = min(idx, len(items) - 1)

    nav_cols = st.columns([1, 3, 1])
    with nav_cols[0]:
        if st.button("◀ Prev", disabled=idx == 0):
            st.session_state["quiz_item_idx"] = max(0, idx - 1)
            st.rerun()
    with nav_cols[2]:
        if st.button("Next ▶", disabled=idx >= len(items) - 1):
            st.session_state["quiz_item_idx"] = min(len(items) - 1, idx + 1)
            st.rerun()
    with nav_cols[1]:
        st.caption(f"Q{idx + 1} / {len(items)} | {quiz.get('subject', '')} | {quiz.get('source_note', '')}")

    st.divider()

    # ── Question Display ──
    item = items[idx]
    diff_icons = {"easy": "🟢", "medium": "🟡", "hard": "🔴"}
    diff = item.get("difficulty", "?")
    problem_num = item.get("problem_number", "")
    type_label = item.get("type", "")
    header = f"{diff_icons.get(diff, '⚪')} [{diff}] {type_label}"
    if problem_num:
        header += f" (#{problem_num})"
    st.subheader(header)
    st.markdown(item.get("question", ""))

    # ── 첨부 이미지 표시 (교재/첨부자료에서 크롭된 이미지) ──
    img_path = item.get("image_path", "")
    if img_path:
        from pathlib import Path as _P
        img_file = _P(img_path)
        if img_file.exists():
            img_source = item.get("image_source", "")
            source_label = {"textbook": "교재", "slides": "강의자료"}.get(img_source, img_source)
            st.image(str(img_file), caption=f"[{source_label}]", width=500)

    tags = item.get("concept_tags", [])
    if tags:
        st.caption("Tags: " + ", ".join(f"`{t}`" for t in tags))

    # ── Answer ──
    show_answer = st.checkbox("정답 보기", key=f"show_ans_{idx}")
    if show_answer:
        st.success("**Expected Answer Keys:**")
        for key in item.get("expected_answer_keys", []):
            st.write(f"✓ {key}")

    # ── Grading ──
    review = item.get("review", {})
    if review.get("result"):
        st.info(f"이미 채점됨: **{review['result']}** ({review.get('reviewed_at', '')})")
    else:
        st.divider()
        grade_cols = st.columns(4)
        memo = ""

        with grade_cols[0]:
            if st.button("✅ Correct", key=f"correct_{idx}", width="stretch"):
                qm.grade_item(selected_id, idx, "correct")
                st.rerun()
        with grade_cols[1]:
            if st.button("🟡 Partial", key=f"partial_{idx}", width="stretch"):
                memo = st.session_state.get(f"memo_{idx}", "")
                qm.grade_item(selected_id, idx, "partial", memo)
                st.rerun()
        with grade_cols[2]:
            if st.button("❌ Wrong", key=f"wrong_{idx}", width="stretch"):
                memo = st.session_state.get(f"memo_{idx}", "")
                qm.grade_item(selected_id, idx, "wrong", memo)
                st.rerun()
        with grade_cols[3]:
            if st.button("⏭ Skip", key=f"skip_{idx}", width="stretch"):
                st.session_state["quiz_item_idx"] = min(len(items) - 1, idx + 1)
                st.rerun()

        st.text_input("오답 메모 (optional)", key=f"memo_{idx}")

    # ── Complete Quiz ──
    reloaded = qm.load_quiz(selected_id)
    if reloaded and qm.is_quiz_complete(reloaded):
        st.divider()
        if st.button("🎉 퀴즈 완료 → Approved", type="primary"):
            qm.complete_quiz(selected_id)
            st.session_state["quiz_item_idx"] = 0
            st.rerun()


# ══════════════════════════════════════════════════════════════
# Page 4: Analytics
# ══════════════════════════════════════════════════════════════

def render_analytics():
    st.header("Analytics")
    config = get_config()
    paths = get_pipeline_paths(config)
    subjects = get_subject_display_names(config)
    weak = load_weak_concepts(str(paths["pipeline"]))

    if not weak:
        st.info("학습 데이터가 없습니다. 퀴즈를 풀어 데이터를 축적하세요.")
        return

    # ── Subject Filter ──
    all_subjects = list(weak.keys())
    selected_subjects = st.multiselect(
        "과목 필터",
        all_subjects,
        default=all_subjects,
        format_func=lambda k: subjects.get(k, k),
    )

    # ── Mastery Chart & SR Schedule: 탭으로 분리 ──
    import pandas as pd
    import plotly.express as px

    rows = []
    for subj in selected_subjects:
        for tag, info in weak.get(subj, {}).items():
            rows.append({
                "concept": tag,
                "subject": subjects.get(subj, subj),
                "mastery": info.get("mastery", 0),
                "priority": info.get("priority", "?"),
                "encounters": info.get("encounter_count", 0),
            })

    tab_chart, tab_sr, tab_detail = st.tabs(["Mastery Chart", "Spaced Repetition", "Concept Details"])

    with tab_chart:
        if rows:
            df = pd.DataFrame(rows).sort_values("mastery", ascending=True)
            color_map = {"high": "#ef4444", "medium": "#f59e0b", "low": "#22c55e"}

            fig = px.bar(
                df, x="mastery", y="concept", color="priority",
                color_discrete_map=color_map,
                orientation="h",
                hover_data=["subject", "encounters"],
                title="Concept Mastery",
                labels={"mastery": "Mastery", "concept": ""},
            )
            fig.update_layout(
                height=max(350, len(rows) * 28),
                xaxis=dict(range=[0, 1], tickformat=".0%"),
                yaxis=dict(autorange="reversed"),
                paper_bgcolor='rgba(0,0,0,0)',
                plot_bgcolor='rgba(0,0,0,0)',
                font=dict(color="#1A2E38")  # 네이비 폰트 색상으로 복구!
            )
            st.plotly_chart(fig, width="stretch")
        else:
            st.info("데이터 없음")

    with tab_sr:
        sr_rows = []
        for subj in selected_subjects:
            for tag, info in weak.get(subj, {}).items():
                sr_rows.append({
                    "과목": subjects.get(subj, subj),
                    "개념": tag,
                    "mastery": f"{info.get('mastery', 0):.0%}",
                    "interval": info.get("sr_interval", "?"),
                    "next_review": info.get("sr_next_review", "-"),
                    "ease": info.get("sr_ease_factor", "?"),
                    "priority": info.get("priority", "?"),
                })
        if sr_rows:
            st.dataframe(pd.DataFrame(sr_rows), width="stretch", hide_index=True)
        else:
            st.info("데이터 없음")

    with tab_detail:
        # 과목별 탭으로 분리하여 겹침 방지
        if selected_subjects:
            detail_tabs = st.tabs([subjects.get(s, s) for s in selected_subjects])
            for subj, dtab in zip(selected_subjects, detail_tabs):
                with dtab:
                    items = sorted(weak.get(subj, {}).items(), key=lambda x: x[1].get("mastery", 0))
                    if not items:
                        st.caption("개념 데이터 없음")
                        continue
                    for tag, info in items:
                        with st.expander(f"[{info.get('priority', '?')}] {tag} — {info.get('mastery', 0):.0%}"):
                            col1, col2 = st.columns(2)
                            col1.write(f"**Encounters:** {info.get('encounter_count', 0)}")
                            col1.write(f"**Correct:** {info.get('correct_count', 0)}")
                            col2.write(f"**SR Interval:** {info.get('sr_interval', '?')} days")
                            col2.write(f"**Next Review:** {info.get('sr_next_review', '-')}")
                            notes = info.get("related_notes", [])
                            if notes:
                                st.write("**Related Notes:** " + ", ".join(notes))
                            mistakes = info.get("recent_mistakes", [])
                            if mistakes:
                                st.write("**Recent Mistakes:**")
                                for m in mistakes:
                                    st.caption(f"  {m['date'][:10]} ({m['result']}) {m.get('memo', '')}")


# ══════════════════════════════════════════════════════════════
# Page 5: Hermes
# ══════════════════════════════════════════════════════════════

def render_hermes():
    st.header("Hermes")
    config = get_config()

    from agents.hermes_agent import HermesAgent
    from hermes_store import HermesStore

    agent = HermesAgent(config)
    store = HermesStore(config)
    today_plan = agent.get_schedule("day", "", auto_create=True)
    week_plan = agent.get_schedule("week", "", auto_create=True)
    events = store.upcoming_events(within_days=21)

    col1, col2, col3 = st.columns(3)
    col1.metric("Today Blocks", len(today_plan.get("blocks", [])))
    col2.metric("Week Blocks", len(week_plan.get("blocks", [])))
    col3.metric("Upcoming Exams", len(events))

    st.caption("Hermes는 취약 개념, spaced repetition, 시험 일정을 묶어 오늘/이번 주 학습 흐름을 배치합니다.")

    action_cols = st.columns([1, 1, 2])
    with action_cols[0]:
        if st.button("오늘 다시 짜기", type="primary", width="stretch"):
            agent.reschedule("day", reason="dashboard_reschedule_day")
            st.rerun()
    with action_cols[1]:
        if st.button("이번 주 다시 짜기", width="stretch"):
            agent.reschedule("week", reason="dashboard_reschedule_week")
            st.rerun()

    with st.expander("일정 추가", expanded=False):
        subjects = get_subject_display_names(config)
        subj_key = st.selectbox("과목", list(subjects.keys()), format_func=lambda k: f"{subjects[k]} ({k})", key="hermes_subject")
        event_kind = st.selectbox("종류", ["exam", "deadline"], key="hermes_kind")
        event_date = st.date_input("날짜", key="hermes_date")
        event_title = st.text_input("제목", key="hermes_title")
        event_details = st.text_area("메모", key="hermes_details")
        if st.button("일정 저장", key="hermes_save_event"):
            if event_title.strip():
                store.add_event(subj_key, event_title.strip(), event_date.isoformat(), details=event_details.strip(), kind=event_kind)
                agent.plan_week(reason="dashboard_event_added")
                st.success("일정을 추가하고 Hermes 주간 계획을 갱신했습니다.")
                st.rerun()
            else:
                st.warning("제목을 입력하세요.")

    day_tab, week_tab, event_tab = st.tabs(["Today", "This Week", "Calendar"])

    with day_tab:
        st.markdown(f"**요약:** {today_plan.get('summary', '-')}")
        if today_plan.get("blocks"):
            for block in today_plan["blocks"]:
                with st.expander(f"{block['start']}-{block['end']} | {block['subject_display']} | {block['title']}", expanded=True):
                    st.write(block.get("reason", ""))
                    focus = block.get("focus", [])
                    if focus:
                        st.caption("focus: " + ", ".join(focus))
        else:
            st.info("오늘 배치된 학습 블록이 없습니다.")

        backlog = today_plan.get("backlog", [])
        if backlog:
            st.divider()
            st.caption(f"미배치 후보 {len(backlog)}개")
            for item in backlog[:5]:
                st.write(f"- {item['subject_display']} | {item['title']} | {item['reason']}")

    with week_tab:
        st.markdown(f"**요약:** {week_plan.get('summary', '-')}")
        week_blocks = week_plan.get("blocks", [])
        if week_blocks:
            import pandas as pd

            rows = [{
                "date": block["date"],
                "time": f"{block['start']}-{block['end']}",
                "subject": block["subject_display"],
                "title": block["title"],
                "category": block["category"],
                "reason": block["reason"],
            } for block in week_blocks]
            st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
        else:
            st.info("이번 주 배치된 학습 블록이 없습니다.")

    with event_tab:
        if events:
            for event in events:
                subject_name = get_subject_display_names(config).get(event["subject"], event["subject"])
                st.write(f"- {event['date']} | {subject_name} | {event['title']} ({event['days_left']}일 남음)")
                if event.get("details"):
                    st.caption(event["details"])
        else:
            st.info("등록된 시험/마감 일정이 없습니다.")


# ══════════════════════════════════════════════════════════════
# Page 6: Settings
# ══════════════════════════════════════════════════════════════

def render_settings():
    st.header("Settings")
    config = get_config()

    # ── 모델 레지스트리 (탭 공통) ──
    from model_registry import ModelRegistry
    _registry = ModelRegistry(config)
    _oai_models = _registry.get_openai_models()
    _ant_models = _registry.get_anthropic_models()

    tab_llm, tab_routing, tab_subjects, tab_features, tab_backup = st.tabs([
        "LLM Config", "Task Routing", "Subjects", "Features", "Backup",
    ])

    # ── Tab A: LLM Config ──
    with tab_llm:
        llm = config.get("llm", {})

        # ── API Keys (환경변수 전용) ──
        st.subheader("API Keys")
        st.caption("API 키는 config에 저장하지 않고 환경변수에서만 읽습니다.")
        col_k1, col_k2 = st.columns(2)
        with col_k1:
            if has_env_value("OPENAI_API_KEY"):
                st.success("OpenAI API Key detected")
            else:
                st.warning("OPENAI_API_KEY not set")
        with col_k2:
            if has_env_value("ANTHROPIC_API_KEY"):
                st.success("Anthropic API Key detected")
            else:
                st.warning("ANTHROPIC_API_KEY not set")

        st.code(
            "[Environment]::SetEnvironmentVariable(\"OPENAI_API_KEY\", \"<your-key>\", \"User\")\n"
            "[Environment]::SetEnvironmentVariable(\"ANTHROPIC_API_KEY\", \"<your-key>\", \"User\")",
            language="powershell",
        )
        st.caption("환경변수를 바꾼 뒤에는 대시보드나 새 터미널을 다시 시작해야 반영됩니다.")

        st.divider()

        st.subheader("LM Studio (Local)")
        lmstudio = llm.get("lmstudio", {})
        lmstudio["base_url"] = st.text_input("Base URL", lmstudio.get("base_url", "http://localhost:1234"), key="lms_url")
        lmstudio["model"] = st.text_input("Model", lmstudio.get("model", ""), key="lms_model")
        lmstudio["timeout"] = st.slider("Timeout (sec)", 30, 300, int(lmstudio.get("timeout", 180)), key="lms_timeout")

        # ── LM Studio 연결 테스트 ──
        if st.button("Test Connection", key="lms_test"):
            try:
                r = __import__("requests").get(f"{lmstudio['base_url'].rstrip('/')}/v1/models", timeout=5)
                if r.status_code == 200:
                    model_list = [m.get("id", "?") for m in r.json().get("data", [])]
                    st.success(f"Connected! Models: {', '.join(model_list) if model_list else 'none loaded'}")
                else:
                    st.error(f"HTTP {r.status_code}")
            except Exception as e:
                st.error(f"Connection failed: {e}")

        st.subheader("ChatGPT")
        chatgpt = llm.get("chatgpt", {})

        if _oai_models:
            _oai_ids = [m.id for m in _oai_models]
            _oai_labels = {}
            for m in _oai_models:
                badges = []
                if m.thinking:
                    badges.append("thinking")
                if m.reasoning_levels:
                    badges.append(f"reasoning: {'/'.join(m.reasoning_levels)}")
                if m.variant:
                    badges.append(m.variant)
                label = m.display_name
                if badges:
                    label += f"  [{', '.join(badges)}]"
                _oai_labels[m.id] = label

            current_gpt = chatgpt.get("model", "gpt-5.4")
            if current_gpt not in _oai_ids:
                _oai_ids.append(current_gpt)
                _oai_labels[current_gpt] = current_gpt
            chatgpt["model"] = st.selectbox(
                "Model (API)", _oai_ids,
                index=_oai_ids.index(current_gpt) if current_gpt in _oai_ids else 0,
                format_func=lambda x: _oai_labels.get(x, x),
                key="gpt_model",
            )
            # 선택된 모델 정보 표시
            _sel_oai = next((m for m in _oai_models if m.id == chatgpt["model"]), None)
            if _sel_oai:
                _info_parts = []
                if _sel_oai.thinking:
                    _info_parts.append("Thinking: ON")
                if _sel_oai.reasoning_levels:
                    _info_parts.append(f"Reasoning: {', '.join(_sel_oai.reasoning_levels)}")
                _info_parts.append(f"Tier: {_sel_oai.tier}")
                if _sel_oai.context_window:
                    _info_parts.append(f"Context: {_sel_oai.context_window:,}")
                st.caption(" | ".join(_info_parts))
        else:
            chatgpt["model"] = st.text_input("Model", chatgpt.get("model", "gpt-5.4"), key="gpt_model")

        chatgpt["temperature"] = st.slider("Temperature", 0.0, 1.0, float(chatgpt.get("temperature", 0.3)), 0.1, key="gpt_temp")
        chatgpt["prefer_subscription"] = st.checkbox("Prefer Codex CLI (subscription)", chatgpt.get("prefer_subscription", True), key="gpt_sub")

        st.subheader("Claude")
        claude = llm.get("claude", {})

        if _ant_models:
            _ant_ids = [m.id for m in _ant_models]
            _ant_labels = {}
            for m in _ant_models:
                badges = []
                if m.thinking:
                    badges.append("thinking")
                if m.reasoning_levels:
                    badges.append(f"reasoning: {'/'.join(m.reasoning_levels)}")
                badges.append(m.tier)
                label = m.display_name + f"  [{', '.join(badges)}]"
                _ant_labels[m.id] = label

            current_claude = claude.get("model", "claude-sonnet-4-20250514")
            if current_claude not in _ant_ids:
                _ant_ids.append(current_claude)
                _ant_labels[current_claude] = current_claude
            claude["model"] = st.selectbox(
                "API Model", _ant_ids,
                index=_ant_ids.index(current_claude) if current_claude in _ant_ids else 0,
                format_func=lambda x: _ant_labels.get(x, x),
                key="cl_api_model",
            )
            _sel_ant = next((m for m in _ant_models if m.id == claude["model"]), None)
            if _sel_ant:
                _info_parts = []
                if _sel_ant.thinking:
                    _info_parts.append("Extended Thinking: ON")
                if _sel_ant.reasoning_levels:
                    _info_parts.append(f"Reasoning: {', '.join(_sel_ant.reasoning_levels)}")
                _info_parts.append(f"Tier: {_sel_ant.tier}")
                if _sel_ant.context_window:
                    _info_parts.append(f"Context: {_sel_ant.context_window:,}")
                st.caption(" | ".join(_info_parts))
        else:
            claude["model"] = st.text_input("API Model", claude.get("model", "claude-sonnet-4-20250514"), key="cl_api_model")

        # ── CLI 모델 (구독용) ──
        _cli_tiers = [m.tier for m in _ant_models] if _ant_models else ["sonnet", "opus", "haiku"]
        _cli_options = sorted(set(_cli_tiers), key=lambda x: {"opus": 0, "sonnet": 1, "haiku": 2}.get(x, 99))
        if not _cli_options:
            _cli_options = ["sonnet", "opus", "haiku"]
        current_cli = claude.get("cli_model", "sonnet")
        if current_cli not in _cli_options:
            _cli_options.append(current_cli)
        claude["cli_model"] = st.selectbox(
            "CLI Default Model",
            _cli_options,
            index=_cli_options.index(current_cli) if current_cli in _cli_options else 0,
            key="cl_cli",
        )
        claude["prefer_subscription"] = st.checkbox("Prefer Claude Code CLI (subscription)", claude.get("prefer_subscription", True), key="cl_sub")

        st.divider()
        st.subheader("Claude API Parameters")
        st.caption("API fallback 호출 시 적용되는 파라미터입니다. CLI(구독) 호출에는 적용되지 않습니다.")
        col_cl1, col_cl2 = st.columns(2)
        with col_cl1:
            claude["temperature"] = st.slider(
                "Temperature", 0.0, 1.0, float(claude.get("temperature", 0.7)), 0.05,
                key="cl_temp", help="Extended Thinking 모드에서는 자동으로 1.0 적용",
            )
            claude["max_tokens"] = st.number_input(
                "Max Tokens", 1024, 32768, int(claude.get("max_tokens", 4096)),
                step=1024, key="cl_max_tokens",
            )
        with col_cl2:
            claude["top_p"] = st.slider(
                "Top P", 0.0, 1.0, float(claude.get("top_p", 1.0)), 0.05,
                key="cl_top_p", help="Nucleus sampling (1.0 = 비활성화)",
            )
            claude["thinking_budget"] = st.number_input(
                "Thinking Budget (tokens)", 1000, 50000, int(claude.get("thinking_budget", 10000)),
                step=1000, key="cl_think_budget",
                help="Extended Thinking 활성화 시 사용되는 토큰 예산",
            )

        # ── LM Studio 모델 동적 조회 ──
        _lms_models = _registry.get_lmstudio_models()
        if _lms_models:
            st.divider()
            st.caption(f"LM Studio: {len(_lms_models)} models loaded at {lmstudio.get('base_url', '')}")

    # ── Tab B: Task Routing ──
        st.divider()
        st.subheader("External Router")
        router_cfg = llm.get("router", {})
        default_router_path = str((SCRIPTS_DIR.parent / "pbl-router-v4").resolve())
        router_cfg["enabled"] = st.checkbox("Enable external router", router_cfg.get("enabled", False), key="router_enabled")
        router_cfg["mode"] = st.selectbox(
            "Router Mode",
            ["import", "http"],
            index=["import", "http"].index(router_cfg.get("mode", "import")) if router_cfg.get("mode", "import") in ["import", "http"] else 0,
            key="router_mode",
        )
        router_cfg["project_path"] = st.text_input(
            "Router Project Path",
            router_cfg.get("project_path", default_router_path),
            key="router_project_path",
        )
        router_cfg["server_url"] = st.text_input(
            "Router Server URL",
            router_cfg.get("server_url", "http://localhost:8000"),
            key="router_server_url",
        )
        col_router_1, col_router_2 = st.columns(2)
        with col_router_1:
            router_cfg["profile"] = st.text_input("Router Profile", router_cfg.get("profile", "study"), key="router_profile")
        with col_router_2:
            router_cfg["preset"] = st.text_input("Default Preset (optional)", router_cfg.get("preset", ""), key="router_preset")
        router_cfg["timeout"] = st.slider("Router Timeout (sec)", 30, 300, int(router_cfg.get("timeout", 180)), key="router_timeout")

        if st.button("Test Router", key="router_test"):
            if router_cfg.get("mode", "import") == "http":
                try:
                    r = __import__("requests").get(f"{router_cfg['server_url'].rstrip('/')}/health", timeout=5)
                    if r.status_code == 200:
                        data = r.json()
                        st.success(
                            "Router reachable "
                            f"(presets={data.get('presets_loaded', '?')}, profiles={data.get('profiles_loaded', '?')})"
                        )
                    else:
                        st.error(f"HTTP {r.status_code}")
                except Exception as e:
                    st.error(f"Router connection failed: {e}")
            else:
                router_path = Path(router_cfg.get("project_path", "")) / "router_v4.py"
                if router_path.exists():
                    st.success(f"Router found: {router_path}")
                else:
                    st.error(f"router_v4.py not found under {router_cfg.get('project_path', '')}")

    with tab_routing:
        routing = llm.get("routing", {})

        # ── 태스크 설명 매핑 ──
        _TASK_DESC = {
            "collect": "소스 파일 수집·로딩",
            "classify": "노트 주제 분류",
            "caption": "이미지 캡션 생성",
            "extract_keywords": "키워드 추출",
            "summarize_draft": "요약 초안 작성",
            "translate_term": "전문용어 번역",
            "draft": "종합 초안 작성",
            "gap_analysis": "갭 분석 (부족 개념 탐지)",
            "study_plan": "학습 계획 수립",
            "supplement": "보충 콘텐츠 생성",
            "cross_subject": "교차과목 연결",
            "paper_analysis": "논문 분석·요약",
            "synthesis_final": "최종 정리노트 작성",
            "synthesis_deep": "심화 종합 정리",
            "quiz_generate": "퀴즈 생성",
            "quiz": "퀴즈 출제",
            "mechanism": "메커니즘 설명",
            "user_response": "사용자 대면 응답",
            "pubmed_overview": "PubMed 논문 요약",
        }

        # 현재 할당 수집
        all_tasks = set()
        for lst in [routing.get("lmstudio_tasks", []), routing.get("chatgpt_tasks", []), routing.get("claude_tasks", []), routing.get("router_tasks", [])]:
            all_tasks.update(lst)
        all_tasks = sorted(all_tasks)
        router_enabled = bool(llm.get("router", {}).get("enabled", False))
        provider_options = ["chatgpt", "claude"] + (["router"] if router_enabled else [])

        # 단순작업 = lmstudio, 어려운작업 = chatgpt or claude
        simple_tasks = set(routing.get("lmstudio_tasks", []))
        st.subheader("단순작업")
        st.caption("LM Studio가 처리하는 로컬 작업입니다. 체크된 작업은 단순작업으로 유지되고, 체크 해제하면 아래 어려운작업 파트로 이동합니다.")
        st.caption(f"현재 단순작업: {len(simple_tasks)}개")
        st.markdown("**실행 백엔드:** LM Studio (로컬, 무료)")

        # 드래그 가능한 multiselect 대신 체크박스 그리드
        new_simple = set()
        new_heavy = set()
        _s_cols = st.columns(2)
        for i, task in enumerate(all_tasks):
            desc = _TASK_DESC.get(task, task)
            is_simple = task in simple_tasks
            with _s_cols[i % 2]:
                checked = st.checkbox(f"`{task}` — {desc}", value=is_simple, key=f"simple_{task}")
            if checked:
                new_simple.add(task)
            else:
                new_heavy.add(task)

        st.divider()
        st.subheader("어려운작업")
        st.caption("ChatGPT 또는 Claude가 처리하는 고난도 작업입니다. 분석, 계획, 최종 산출물 생성을 여기서 나눕니다.")

        # 고사양 내에서 chatgpt vs claude 배분
        _CHATGPT_DEFAULT = {"gap_analysis", "study_plan", "supplement", "cross_subject", "paper_analysis"}
        heavy_sorted = sorted(new_heavy)
        st.caption(f"현재 어려운작업: {len(heavy_sorted)}개")

        changed_assignments = {}
        overrides = routing.get("cli_model_override", {})
        gpt_overrides = routing.get("gpt_model_override", {})
        reasoning_overrides = routing.get("reasoning_override", {})
        new_overrides = {}
        new_gpt_overrides = {}
        new_reasoning = {}

        _REASONING_OPTIONS = ["auto", "low", "medium", "high"]

        # GPT 모델 목록 (레지스트리에서)
        _gpt_model_ids = [m.id for m in _oai_models] if _oai_models else ["gpt-5.4"]
        _gpt_short_labels = {}
        for m in (_oai_models or []):
            label = m.variant if m.variant else "standard"
            if m.thinking:
                label += " *"
            _gpt_short_labels[m.id] = label
        if not _gpt_short_labels:
            _gpt_short_labels = {"gpt-5.4": "standard"}

        if heavy_sorted:
            hcol_task, hcol_prov, hcol_model, hcol_reason = st.columns([3, 1.5, 1.5, 1.5])
            hcol_task.write("**태스크**")
            hcol_prov.write("**Provider**")
            hcol_model.write("**모델**")
            hcol_reason.write("**Reasoning**")
            for task in heavy_sorted:
                desc = _TASK_DESC.get(task, task)
                # 기존 할당 복원
                if task in routing.get("chatgpt_tasks", []):
                    default_prov = "chatgpt"
                elif task in routing.get("claude_tasks", []):
                    default_prov = "claude"
                elif task in routing.get("router_tasks", []):
                    default_prov = "router"
                else:
                    default_prov = "chatgpt" if task in _CHATGPT_DEFAULT else "claude"

                c1, c2, c3, c4 = st.columns([3, 1.5, 1.5, 1.5])
                c1.write(f"`{task}` — {desc}")
                prov = c2.selectbox(
                    "Provider", provider_options,
                    index=provider_options.index(default_prov) if default_prov in provider_options else 0,
                    key=f"hprov_{task}", label_visibility="collapsed",
                )
                changed_assignments[task] = prov

                # 모델 선택 (provider별)
                if prov == "claude":
                    cur_model = overrides.get(task, claude.get("cli_model", "sonnet"))
                    new_model = c3.selectbox(
                        "Model", ["sonnet", "opus"],
                        index=["sonnet", "opus"].index(cur_model) if cur_model in ["sonnet", "opus"] else 0,
                        key=f"hmodel_{task}", label_visibility="collapsed",
                    )
                    new_overrides[task] = new_model
                elif prov == "chatgpt" and _gpt_model_ids:
                    cur_gpt = gpt_overrides.get(task, chatgpt.get("model", _gpt_model_ids[0]))
                    if cur_gpt not in _gpt_model_ids:
                        cur_gpt = _gpt_model_ids[0]
                    new_gpt = c3.selectbox(
                        "GPT Model", _gpt_model_ids,
                        index=_gpt_model_ids.index(cur_gpt),
                        format_func=lambda x: _gpt_short_labels.get(x, x),
                        key=f"hgpt_{task}", label_visibility="collapsed",
                    )
                    new_gpt_overrides[task] = new_gpt
                elif prov == "router":
                    router_label = llm.get("router", {}).get("preset") or llm.get("router", {}).get("profile", "study")
                    c3.write(f"`{router_label}`")
                else:
                    c3.write("—")

                # Reasoning 레벨 선택
                cur_reason = reasoning_overrides.get(task, "auto")
                if cur_reason not in _REASONING_OPTIONS:
                    cur_reason = "auto"
                new_reason = c4.selectbox(
                    "Reasoning", _REASONING_OPTIONS,
                    index=_REASONING_OPTIONS.index(cur_reason),
                    key=f"hreason_{task}", label_visibility="collapsed",
                )
                if new_reason != "auto":
                    new_reasoning[task] = new_reason
        else:
            st.info("모든 태스크가 단순작업으로 배정되었습니다.")

        # reasoning 설명
        if new_reasoning:
            st.divider()
            st.caption("**Reasoning 레벨:** "
                       "auto = 작업에 따라 자동 | "
                       "low = 빠른 응답 | "
                       "medium = 균형 | "
                       "high = 심화 추론 (thinking 활성화)")

        # config에 반영 (메모리만)
        routing["lmstudio_tasks"] = sorted(new_simple)
        routing["chatgpt_tasks"] = [t for t, p in changed_assignments.items() if p == "chatgpt"]
        routing["claude_tasks"] = [t for t, p in changed_assignments.items() if p == "claude"]
        routing["router_tasks"] = [t for t, p in changed_assignments.items() if p == "router"]
        routing["cli_model_override"] = new_overrides
        routing["gpt_model_override"] = new_gpt_overrides
        routing["reasoning_override"] = new_reasoning

    # ── Tab C: Subjects ──
    with tab_subjects:
        for subj_key, subj_cfg in config.get("subjects", {}).items():
            with st.expander(f"{subj_key} ({subj_cfg.get('folder', '')})"):
                subj_cfg["template"] = st.text_input("Template", subj_cfg.get("template", ""), key=f"sub_tpl_{subj_key}")
                subj_cfg["items_per_note"] = st.number_input("Items per note", 1, 10, int(subj_cfg.get("items_per_note", 2)), key=f"sub_ipn_{subj_key}")
                kw = subj_cfg.get("pubmed_keywords", [])
                kw_key = f"sub_kw_{subj_key}"
                pending_kw_key = f"{kw_key}__pending"
                if pending_kw_key in st.session_state:
                    st.session_state[kw_key] = st.session_state.pop(pending_kw_key)
                elif kw_key not in st.session_state:
                    st.session_state[kw_key] = "\n".join(kw)

                new_kw = st.text_area("PubMed Keywords (one per line)", key=kw_key)
                subj_cfg["pubmed_keywords"] = [k.strip() for k in new_kw.split("\n") if k.strip()]

                # PubMed 키워드 자동 생성
                if st.button("🔍 키워드 자동 생성 (LLM)", key=f"gen_kw_{subj_key}"):
                    with st.spinner("LLM으로 PubMed 검색 키워드 생성 중..."):
                        try:
                            from llm_router import LLMRouter
                            router = LLMRouter(config)
                            folder_name = subj_cfg.get("folder", subj_key)
                            existing = subj_cfg.get("pubmed_keywords", [])
                            kw_prompt = (
                                f"You are a biomedical literature search expert.\n"
                                f"Subject: {folder_name} (key: {subj_key})\n"
                                f"Existing keywords: {existing}\n\n"
                                f"Generate 5-8 highly effective PubMed/MeSH search keywords or phrases "
                                f"for a university-level study of this subject. "
                                f"Include both broad and specific terms. "
                                f"Return ONLY a JSON array of strings, no explanation.\n"
                                f'Example: ["keyword1", "keyword2"]'
                            )
                            raw = router.generate(kw_prompt, task_type="extract_keywords")
                            if raw:
                                import json as _json
                                text = raw.strip()
                                if text.startswith("```"):
                                    text = "\n".join(text.split("\n")[1:])
                                    if text.endswith("```"):
                                        text = text[:-3]
                                generated = _json.loads(text)
                                if isinstance(generated, list):
                                    merged = list(dict.fromkeys(existing + generated))
                                    subj_cfg["pubmed_keywords"] = merged
                                    st.session_state[pending_kw_key] = "\n".join(merged)
                                    st.success(f"{len(generated)}개 키워드 생성 → 총 {len(merged)}개")
                                    st.rerun()
                                else:
                                    st.warning("LLM 응답이 배열이 아닙니다.")
                            else:
                                st.error("LLM 응답 없음 (LM Studio/ChatGPT/Claude 연결 확인)")
                        except Exception as e:
                            st.error(f"키워드 생성 실패: {e}")

    # ── Tab D: Features ──
    with tab_features:
        mem0 = config.get("mem0", {})
        mem0["enabled"] = st.checkbox("mem0 (Learning Memory)", mem0.get("enabled", False), key="ft_mem0")
        if mem0.get("enabled", False):
            st.caption("mem0 backend summary")
            vs_cfg = mem0.get("vector_store", {})
            mem0_llm = mem0.get("llm", {})
            mem0_embedder = mem0.get("embedder", {})
            col_mem_llm, col_mem_emb = st.columns(2)
            with col_mem_llm:
                st.markdown("**mem0 LLM**")
                st.caption(
                    f"provider: `{mem0_llm.get('provider', '-')}`\n\n"
                    f"model: `{mem0_llm.get('model', '-')}`\n\n"
                    f"base_url: `{mem0_llm.get('base_url', '-')}`"
                )
            with col_mem_emb:
                st.markdown("**mem0 Embedder**")
                st.caption(
                    f"provider: `{mem0_embedder.get('provider', '-')}`\n\n"
                    f"model: `{mem0_embedder.get('model', '-')}`\n\n"
                    f"base_url: `{mem0_embedder.get('base_url', '-')}`"
                )
            st.caption(
                f"vector store: `{vs_cfg.get('mode', '-')}` / "
                f"{vs_cfg.get('host', 'local')}:{vs_cfg.get('port', '-')}"
            )

        pubmed = config.get("pubmed", {})
        pubmed["enabled"] = st.checkbox("PubMed Integration", pubmed.get("enabled", True), key="ft_pubmed")
        pubmed["max_papers"] = st.number_input("PubMed Max Papers", 1, 10, int(pubmed.get("max_papers", 3)), key="ft_pm_max")

        papers = config.get("papers", {})
        papers["enabled"] = st.checkbox("Semantic Scholar Papers", papers.get("enabled", True), key="ft_papers")

        marker = config.get("marker", {})
        marker["enabled"] = st.checkbox("marker-pdf (Advanced PDF)", marker.get("enabled", True), key="ft_marker")

    # ── Tab E: Backup ──
    with tab_backup:
        backups = list_backups(CONFIG_PATH)
        if backups:
            st.subheader(f"Backups ({len(backups)})")
            for b in backups:
                col1, col2 = st.columns([3, 1])
                col1.write(f"`{b['name']}` — {b['modified']}")
                if col2.button("Restore", key=f"restore_{b['name']}"):
                    err = restore_backup(Path(b["path"]), CONFIG_PATH)
                    if err:
                        st.error(err)
                    else:
                        st.session_state.pop("config", None)
                        st.success("복원 완료! 페이지를 새로고침하세요.")
                        st.rerun()
        else:
            st.info("백업이 없습니다. 설정을 저장하면 자동으로 백업됩니다.")

    # ── Save Button ──
    st.divider()
    if st.button("💾 설정 저장", type="primary"):
        err = save_config(CONFIG_PATH, config)
        if err:
            st.error(err)
        else:
            st.session_state.pop("config", None)
            st.success("저장 완료! (백업 생성됨)")
            st.rerun()


# ══════════════════════════════════════════════════════════════
# Page 7: Report
# ══════════════════════════════════════════════════════════════

def render_report():
    st.header("Report")
    config = get_config()
    paths = get_pipeline_paths(config)
    subjects = get_subject_display_names(config)

    st.caption("파이프라인 세션 내용을 Claude가 정리하여 보고서를 생성합니다. "
               "교재/강의자료의 이미지(분자식, 반응식 등)를 자동으로 크롭하여 포함합니다.")

    # ── 옵션 ──
    col_subj, col_fmt = st.columns(2)
    with col_subj:
        subj_options = ["(전체)"] + list(subjects.keys())
        subj_labels = {k: subjects.get(k, k) for k in subjects}
        subj_labels["(전체)"] = "전체 과목"
        sel_subj = st.selectbox(
            "과목",
            subj_options,
            format_func=lambda k: subj_labels.get(k, k),
        )
    with col_fmt:
        sel_fmt = st.selectbox("출력 형식", ["PDF", "Markdown"], index=0)

    # ── 최근 출력 미리보기 ──
    from pathlib import Path as _Path
    output_base = _Path(config.get("pipeline_dir", ".")) / "output"
    md_dir = output_base / "md"
    recent_md = None
    if md_dir.exists():
        md_files = sorted(md_dir.glob("*.md"), key=lambda f: f.stat().st_mtime, reverse=True)
        if md_files:
            recent_md = md_files[0]

    if recent_md:
        with st.expander(f"최근 세션 노트 미리보기 — {recent_md.name}", expanded=False):
            preview = recent_md.read_text(encoding="utf-8")
            st.markdown(preview[:3000] + ("\n\n..." if len(preview) > 3000 else ""))
    else:
        st.info("출력된 정리노트가 없습니다. 먼저 Pipeline을 실행하세요.")

    # ── 기존 보고서 ──
    report_dir = output_base / "reports"
    if report_dir.exists():
        existing = sorted(report_dir.iterdir(), key=lambda f: f.stat().st_mtime, reverse=True)
        if existing:
            with st.expander(f"기존 보고서 ({len(existing)}개)", expanded=False):
                for f in existing[:10]:
                    st.caption(f"`{f.name}` — {f.stat().st_size // 1024} KB")

    # ── 생성 버튼 ──
    st.divider()
    gen_disabled = recent_md is None
    if st.button("📝 보고서 생성", type="primary", disabled=gen_disabled):
        subject_key = None if sel_subj == "(전체)" else sel_subj
        fmt = "pdf" if sel_fmt == "PDF" else "md"

        with st.spinner("Claude로 보고서 생성 중... (1~2분 소요)"):
            try:
                result_path = generate_session_report(config, output_format=fmt, subject=subject_key)
                if result_path and result_path.exists():
                    st.success(f"보고서 생성 완료!")
                    st.write(f"📄 `{result_path}`")

                    # 다운로드 버튼
                    with open(result_path, "rb") as f:
                        file_bytes = f.read()
                    mime = "application/pdf" if fmt == "pdf" else "text/markdown"
                    st.download_button(
                        "⬇ 다운로드",
                        data=file_bytes,
                        file_name=result_path.name,
                        mime=mime,
                    )

                    # MD인 경우 미리보기
                    if fmt == "md":
                        with st.expander("보고서 미리보기", expanded=True):
                            st.markdown(result_path.read_text(encoding="utf-8"))
                else:
                    st.error("보고서 생성 실패. 로그를 확인하세요.")
            except Exception as e:
                st.error(f"보고서 생성 오류: {e}")
                import traceback
                st.code(traceback.format_exc(), language="python")


# ══════════════════════════════════════════════════════════════
# Page Router
# ══════════════════════════════════════════════════════════════

if selected == "dashboard":
    render_dashboard()
elif selected == "pipeline":
    render_pipeline()
elif selected == "hermes":
    render_hermes()
elif selected == "quiz":
    render_quiz()
elif selected == "analytics":
    render_analytics()
elif selected == "report":
    render_report()
elif selected == "settings":
    render_settings()
