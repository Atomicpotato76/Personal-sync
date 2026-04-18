from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from queue import Empty, Queue
from typing import Callable

from contracts.models import (
    ApprovalStage,
    CheckpointSummary,
    DirectionSnapshot,
    EventRecord,
    RunRecord,
    RunStage,
    RunStatus,
    StageNarrative,
    SupervisorSession,
    SupervisorTrace,
)
from services.memory.service import MemoryService
from services.orchestrator.service import HermesOrchestrator
from services.supervisor.service import SupervisorService


@dataclass
class StatusSnapshot:
    run: RunRecord
    summary: CheckpointSummary
    direction: DirectionSnapshot | None
    stage_narrative: StageNarrative | None
    supervisor_session: SupervisorSession | None
    supervisor_traces: list[SupervisorTrace]
    workstreams: list[dict]
    events: list[EventRecord]
    plan_summary_text: str
    manifest_text: str


def _read_optional_text(path: Path | None) -> str:
    if path is None or not path.exists() or not path.is_file():
        return ""
    return path.read_text(encoding="utf-8")


def default_dashboard_messages() -> tuple[str, str, str, str]:
    overview = (
        "Hermes 파이프라인 대시보드\n\n"
        "1. 제안서를 붙여넣거나 마크다운 파일을 불러옵니다.\n"
        "2. 계획을 생성합니다.\n"
        "3. 개요와 방향 탭을 검토합니다.\n"
        "4. 추천된 승인을 진행한 뒤 파이프라인을 실행합니다.\n"
        "5. 산출물 탭과 폴더 열기 버튼으로 결과를 확인합니다.\n"
        "6. 완전히 다른 작업을 시작하려면 상단의 '새 세션 시작'을 누르세요."
    )
    direction = "첫 계획 또는 단계 체크포인트가 저장되면 방향 안내가 여기에 표시됩니다."
    artifacts = "실행을 불러오면 산출물, 매니페스트 내용, 로컬 파일 경로가 여기에 표시됩니다."
    plan = "실행을 생성하거나 불러오면 마크다운 계획 요약이 여기에 표시됩니다."
    return overview, direction, artifacts, plan


def build_status_snapshot(memory: MemoryService, run_id: str) -> StatusSnapshot:
    run = memory.get_run(run_id)
    plan_summary_path = Path(run.plan_path).with_name("summary.md") if run.plan_path else None
    manifest_path = Path(run.manifest_path) if run.manifest_path else None
    return StatusSnapshot(
        run=run,
        summary=memory.build_checkpoint_summary(run_id),
        direction=memory.get_latest_direction(run_id),
        stage_narrative=memory.get_latest_stage_narrative(run_id),
        supervisor_session=memory.get_latest_supervisor_session(run_id),
        supervisor_traces=memory.list_supervisor_traces(run_id, limit=5),
        workstreams=memory.list_workstreams(run_id),
        events=memory.list_events(run_id, limit=20),
        plan_summary_text=_read_optional_text(plan_summary_path),
        manifest_text=_read_optional_text(manifest_path),
    )


def recommended_approval_stage(snapshot: StatusSnapshot) -> ApprovalStage | None:
    if snapshot.run.stage.value == "planning" and snapshot.run.status.value == "waiting_approval":
        return ApprovalStage.plan
    if snapshot.run.stage.value in {"executing", "reviewing"} and snapshot.run.status.value == "waiting_approval":
        return ApprovalStage.checkpoint
    if snapshot.run.stage.value == "testing" and snapshot.run.status.value == "waiting_approval":
        return ApprovalStage.merge
    return None


def approve_and_maybe_continue(
    orchestrator: HermesOrchestrator,
    *,
    run_id: str,
    stage: ApprovalStage,
    actor: str,
    comment: str,
    supervisor: SupervisorService | None = None,
) -> RunRecord:
    latest_session = orchestrator.memory.get_latest_supervisor_session(run_id)
    should_resume_supervisor = (
        supervisor is not None
        and stage == ApprovalStage.checkpoint
        and latest_session is not None
        and latest_session.status == "blocked"
        and latest_session.current_gate == ApprovalStage.checkpoint
    )
    run = orchestrator.approve(run_id, stage=stage, actor=actor, comment=comment)
    if (
        stage == ApprovalStage.checkpoint
        and run.stage in {RunStage.executing, RunStage.reviewing}
        and run.status == RunStatus.pending
    ):
        if should_resume_supervisor:
            return orchestrator.supervise(run.run_id, supervisor=supervisor, actor="direction-supervisor")
        return orchestrator.run(run.run_id)
    return run


def render_overview_text(snapshot: StatusSnapshot) -> str:
    completed = ", ".join(snapshot.summary.completed) if snapshot.summary.completed else "none yet"
    in_progress = ", ".join(snapshot.summary.in_progress) if snapshot.summary.in_progress else "none"
    pending = ", ".join(snapshot.summary.pending) if snapshot.summary.pending else "none"
    recent_changes = ", ".join(snapshot.summary.recent_changes) if snapshot.summary.recent_changes else "none"
    risks = ", ".join(snapshot.summary.risks) if snapshot.summary.risks else "none"
    recommendation = recommended_approval_stage(snapshot)
    supervisor_session = snapshot.supervisor_session
    if supervisor_session is None:
        supervisor_mode = "꺼짐"
        current_gate = "없음"
        remaining_cycles = "없음"
    else:
        supervisor_mode = f"{'켜짐' if supervisor_session.enabled else '꺼짐'} / {supervisor_session.status}"
        current_gate = supervisor_session.current_gate.value if supervisor_session.current_gate else "없음"
        remaining_cycles = str(max(supervisor_session.max_cycles - supervisor_session.cycles_completed, 0))

    lines = [
        "실행 개요",
        "",
        f"실행 ID: {snapshot.run.run_id}",
        f"단계: {snapshot.run.stage.value}",
        f"상태: {snapshot.run.status.value}",
        f"계획 버전: v{snapshot.summary.plan_version:03d}",
        f"추천 승인: {recommendation.value if recommendation else '지금은 없음'}",
        "",
        f"요약: {snapshot.summary.overview}",
        f"완료: {completed}",
        f"진행 중: {in_progress}",
        f"대기: {pending}",
        f"최근 변경: {recent_changes}",
        f"위험 요소: {risks}",
        f"다음 단계: {snapshot.summary.next_step}",
        f"최근 완료 단계: {snapshot.summary.latest_stage_name or '없음'}",
        f"사용자용 요약: {snapshot.summary.latest_stage_summary or '없음'}",
        f"감독 모드: {supervisor_mode}",
        f"현재 감독 게이트: {current_gate}",
        f"남은 자동 진행: {remaining_cycles}",
    ]
    if snapshot.run.last_error:
        lines.extend(["", f"마지막 오류: {snapshot.run.last_error}"])
    return "\n".join(lines)


def render_direction_text(snapshot: StatusSnapshot) -> str:
    lines = ["방향 안내와 승인 맥락", ""]
    if snapshot.direction is None:
        lines.extend(
            [
                "아직 저장된 방향 안내가 없습니다.",
                "",
                "계획을 만들거나 실행을 진행하면 첫 추천 안내가 생성됩니다.",
            ]
        )
    else:
        lines.extend(
            [
                f"제목: {snapshot.direction.headline}",
                f"트리거: {snapshot.direction.trigger_event}",
                f"요약: {snapshot.direction.summary}",
                f"추천: {snapshot.direction.recommendation}",
                "선택지:",
            ]
        )
        if snapshot.direction.options:
            for option in snapshot.direction.options:
                lines.append(f"- {option}")
        else:
            lines.append("- 없음")
        lines.extend(
            [
                "",
                f"완료된 단계: {snapshot.direction.completed_stage or '없음'}",
                f"사용자용 요약: {snapshot.direction.client_summary or '없음'}",
                f"하이라이트: {', '.join(snapshot.direction.artifact_highlights) if snapshot.direction.artifact_highlights else '없음'}",
            ]
        )

    lines.extend(["", "단계 설명", ""])
    if snapshot.stage_narrative is None:
        lines.append("아직 저장된 단계 설명이 없습니다.")
    else:
        lines.extend(
            [
                f"단계: {snapshot.stage_narrative.stage_name}",
                f"기술 요약: {snapshot.stage_narrative.summary}",
                f"쉬운 설명: {snapshot.stage_narrative.client_summary}",
                f"완료된 워크스트림: {', '.join(snapshot.stage_narrative.completed_workstreams) if snapshot.stage_narrative.completed_workstreams else '없음'}",
                f"산출물 하이라이트: {', '.join(snapshot.stage_narrative.artifact_highlights) if snapshot.stage_narrative.artifact_highlights else '없음'}",
                f"다음 초점: {snapshot.stage_narrative.next_focus or '없음'}",
            ]
        )
    return "\n".join(lines)


def render_artifacts_text(snapshot: StatusSnapshot) -> str:
    outputs_dir = Path(snapshot.run.workspace_path).parent if snapshot.run.workspace_path else None
    supervisor_dir = Path(snapshot.run.plan_path).parent / "supervisor" if snapshot.run.plan_path else None
    lines = [
        "산출물과 저장 파일",
        "",
        f"워크스페이스: {snapshot.run.workspace_path or '아직 생성되지 않음'}",
        f"계획 JSON: {snapshot.run.plan_path or '아직 생성되지 않음'}",
        f"계획 요약: {Path(snapshot.run.plan_path).with_name('summary.md') if snapshot.run.plan_path else '아직 생성되지 않음'}",
        f"출력 폴더: {outputs_dir if outputs_dir else '아직 생성되지 않음'}",
        f"매니페스트: {snapshot.run.manifest_path or '아직 패키징되지 않음'}",
        f"감독 세션: {supervisor_dir / 'latest_session.json' if supervisor_dir else '아직 없음'}",
        f"감독 트레이스: {supervisor_dir / 'latest_trace.json' if supervisor_dir else '아직 없음'}",
    ]
    if snapshot.manifest_text:
        lines.extend(["", "매니페스트 내용", "", snapshot.manifest_text])
    else:
        lines.extend(["", "매니페스트 내용", "", "아직 매니페스트가 없습니다. 머지 승인 후 패키징하면 생성됩니다."])
    return "\n".join(lines)


def launch_gui(
    *,
    orchestrator_factory: Callable[[], HermesOrchestrator],
    memory_factory: Callable[[], MemoryService],
    supervisor_factory: Callable[[], SupervisorService] | None = None,
) -> None:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
    from tkinter.scrolledtext import ScrolledText

    root = tk.Tk()
    root.title("Hermes 파이프라인 대시보드")
    root.geometry("1440x920")
    root.minsize(1180, 760)

    queue: Queue[tuple[str, str, object]] = Queue()
    recent_runs_map: dict[str, str] = {}
    latest_snapshot: StatusSnapshot | None = None
    action_in_progress = False
    passive_refresh_in_progress = False
    last_auto_refresh = 0.0

    run_id_var = tk.StringVar()
    actor_var = tk.StringVar(value="local-user")
    stage_var = tk.StringVar(value=ApprovalStage.plan.value)
    busy_var = tk.StringVar(value="준비됨")
    recent_run_var = tk.StringVar()
    auto_refresh_var = tk.BooleanVar(value=False)
    refresh_seconds_var = tk.StringVar(value="5")
    current_run_var = tk.StringVar(value="선택된 실행 없음")
    lifecycle_var = tk.StringVar(value="단계/상태가 여기에 표시됩니다")
    plan_version_var = tk.StringVar(value="v000")
    completed_var = tk.StringVar(value="완료 0개")
    pending_var = tk.StringVar(value="대기 0개")
    next_step_var = tk.StringVar(value="계획을 만들거나 실행을 불러오면 시작할 수 있습니다.")
    recommended_stage_var = tk.StringVar(value="지금은 승인 필요 없음")
    supervisor_mode_var = tk.StringVar(value="감독 꺼짐")
    supervisor_gate_var = tk.StringVar(value="게이트 없음")
    supervisor_cycles_var = tk.StringVar(value="잔여 cycle -")

    root.columnconfigure(0, weight=1)
    root.rowconfigure(2, weight=1)

    style = ttk.Style(root)
    if "vista" in style.theme_names():
        style.theme_use("vista")

    toolbar = ttk.Frame(root, padding=(14, 12, 14, 8))
    toolbar.grid(row=0, column=0, sticky="ew")
    for idx in range(9):
        toolbar.columnconfigure(idx, weight=1 if idx in {1, 3} else 0)

    ttk.Label(toolbar, text="최근 실행").grid(row=0, column=0, sticky="w", padx=(0, 8))
    recent_runs_box = ttk.Combobox(toolbar, textvariable=recent_run_var, state="readonly")
    recent_runs_box.grid(row=0, column=1, sticky="ew", padx=(0, 8))
    ttk.Button(toolbar, text="불러오기", command=lambda: handle_load_selected()).grid(row=0, column=2, sticky="ew", padx=(0, 8))

    ttk.Label(toolbar, text="실행 ID").grid(row=0, column=3, sticky="w", padx=(4, 8))
    ttk.Entry(toolbar, textvariable=run_id_var).grid(row=0, column=4, sticky="ew", padx=(0, 8))
    ttk.Label(toolbar, text="작성자").grid(row=0, column=5, sticky="w", padx=(4, 8))
    ttk.Entry(toolbar, textvariable=actor_var, width=18).grid(row=0, column=6, sticky="ew", padx=(0, 8))
    ttk.Button(toolbar, text="목록 새로고침", command=lambda: refresh_recent_runs()).grid(row=0, column=7, sticky="ew", padx=(0, 8))
    ttk.Button(toolbar, text="새 세션 시작", command=lambda: handle_new_session()).grid(row=0, column=8, sticky="ew")

    ttk.Checkbutton(toolbar, text="자동 새로고침", variable=auto_refresh_var).grid(row=1, column=0, sticky="w", pady=(10, 0))
    ttk.Label(toolbar, text="주기").grid(row=1, column=1, sticky="e", pady=(10, 0))
    ttk.Spinbox(toolbar, from_=3, to=30, increment=1, textvariable=refresh_seconds_var, width=5).grid(row=1, column=2, sticky="w", pady=(10, 0))
    ttk.Label(toolbar, text="초").grid(row=1, column=3, sticky="w", pady=(10, 0))
    ttk.Button(toolbar, text="상태 새로고침", command=lambda: handle_refresh()).grid(row=1, column=4, sticky="ew", pady=(10, 0), padx=(0, 8))
    ttk.Button(toolbar, text="파이프라인 실행", command=lambda: handle_run()).grid(row=1, column=5, sticky="ew", pady=(10, 0), padx=(0, 8))
    ttk.Button(toolbar, text="디스코드 알림", command=lambda: handle_notify()).grid(row=1, column=6, sticky="ew", pady=(10, 0), padx=(0, 8))
    ttk.Button(toolbar, text="출력 폴더 열기", command=lambda: open_outputs()).grid(row=1, column=7, sticky="ew", pady=(10, 0))
    ttk.Button(toolbar, text="감독관 자동 진행", command=lambda: handle_supervise()).grid(row=1, column=8, sticky="ew", pady=(10, 0))

    cards = ttk.Frame(root, padding=(14, 0, 14, 10))
    cards.grid(row=1, column=0, sticky="ew")
    for idx in range(10):
        cards.columnconfigure(idx, weight=1)

    def add_card(column: int, title: str, variable: tk.StringVar) -> None:
        frame = ttk.LabelFrame(cards, text=title, padding=10)
        frame.grid(row=0, column=column, sticky="nsew", padx=(0 if column == 0 else 6, 0))
        ttk.Label(frame, textvariable=variable, wraplength=180, justify=tk.LEFT).pack(fill=tk.BOTH, expand=True)

    add_card(0, "현재 실행", current_run_var)
    add_card(1, "진행 상태", lifecycle_var)
    add_card(2, "계획 버전", plan_version_var)
    add_card(3, "완료", completed_var)
    add_card(4, "대기", pending_var)
    add_card(5, "추천 승인", recommended_stage_var)
    add_card(6, "다음 단계", next_step_var)
    add_card(7, "감독 모드", supervisor_mode_var)
    add_card(8, "감독 게이트", supervisor_gate_var)
    add_card(9, "남은 Cycle", supervisor_cycles_var)

    body = ttk.Panedwindow(root, orient=tk.HORIZONTAL)
    body.grid(row=2, column=0, sticky="nsew", padx=14, pady=(0, 12))

    actions_panel = ttk.Frame(body, padding=(0, 0, 12, 0))
    details_panel = ttk.Frame(body)
    actions_panel.columnconfigure(0, weight=1)
    actions_panel.rowconfigure(1, weight=1)
    details_panel.columnconfigure(0, weight=1)
    details_panel.rowconfigure(0, weight=1)
    body.add(actions_panel, weight=0)
    body.add(details_panel, weight=1)

    request_frame = ttk.LabelFrame(actions_panel, text="제안서 / 요청", padding=10)
    request_frame.grid(row=0, column=0, sticky="nsew", pady=(0, 12))
    request_frame.columnconfigure(0, weight=1)
    request_frame.rowconfigure(1, weight=1)
    ttk.Label(
        request_frame,
        text="여기에 프로젝트 제안서를 붙여넣거나, 마크다운/텍스트 파일을 불러온 뒤 계획을 생성하세요.",
        wraplength=360,
        justify=tk.LEFT,
    ).grid(row=0, column=0, sticky="w", pady=(0, 8))
    request_box = ScrolledText(request_frame, height=12, wrap=tk.WORD, font=("Consolas", 10))
    request_box.grid(row=1, column=0, sticky="nsew")
    request_buttons = ttk.Frame(request_frame)
    request_buttons.grid(row=2, column=0, sticky="ew", pady=(10, 0))
    request_buttons.columnconfigure(0, weight=1)
    request_buttons.columnconfigure(1, weight=1)
    request_buttons.columnconfigure(2, weight=1)
    ttk.Button(request_buttons, text="제안서 파일 불러오기", command=lambda: load_text_into(request_box)).grid(row=0, column=0, sticky="ew", padx=(0, 6))
    ttk.Button(request_buttons, text="지우기", command=lambda: set_input_text(request_box, "")).grid(row=0, column=1, sticky="ew", padx=3)
    ttk.Button(request_buttons, text="계획 생성", command=lambda: handle_plan()).grid(row=0, column=2, sticky="ew", padx=(6, 0))

    control_notebook = ttk.Notebook(actions_panel)
    control_notebook.grid(row=1, column=0, sticky="nsew")

    approval_tab = ttk.Frame(control_notebook, padding=10)
    approval_tab.columnconfigure(0, weight=1)
    approval_tab.rowconfigure(1, weight=1)
    control_notebook.add(approval_tab, text="방향 / 승인")

    ttk.Label(
        approval_tab,
        text="여기에 방향 수정 메모를 남길 수 있습니다. 같은 메모를 승인 시 코멘트로 함께 붙일 수도 있습니다.",
        wraplength=360,
        justify=tk.LEFT,
    ).grid(row=0, column=0, sticky="w", pady=(0, 8))
    feedback_box = ScrolledText(approval_tab, height=12, wrap=tk.WORD, font=("Consolas", 10))
    feedback_box.grid(row=1, column=0, sticky="nsew")

    feedback_buttons = ttk.Frame(approval_tab)
    feedback_buttons.grid(row=2, column=0, sticky="ew", pady=(10, 10))
    for idx in range(3):
        feedback_buttons.columnconfigure(idx, weight=1)
    ttk.Button(feedback_buttons, text="방향 파일 불러오기", command=lambda: load_text_into(feedback_box)).grid(row=0, column=0, sticky="ew", padx=(0, 6))
    ttk.Button(feedback_buttons, text="지우기", command=lambda: set_input_text(feedback_box, "")).grid(row=0, column=1, sticky="ew", padx=3)
    ttk.Button(feedback_buttons, text="방향 저장", command=lambda: handle_feedback()).grid(row=0, column=2, sticky="ew", padx=(6, 0))

    approve_frame = ttk.LabelFrame(approval_tab, text="승인 작업", padding=10)
    approve_frame.grid(row=3, column=0, sticky="ew")
    for idx in range(4):
        approve_frame.columnconfigure(idx, weight=1)
    ttk.Label(approve_frame, text="선택된 단계").grid(row=0, column=0, sticky="w", padx=(0, 8))
    ttk.Combobox(
        approve_frame,
        textvariable=stage_var,
        state="readonly",
        values=[ApprovalStage.plan.value, ApprovalStage.checkpoint.value, ApprovalStage.merge.value],
    ).grid(row=0, column=1, sticky="ew", padx=(0, 8))
    ttk.Button(approve_frame, text="선택 단계 승인", command=lambda: handle_approve()).grid(row=0, column=2, sticky="ew", padx=(0, 8))
    ttk.Button(approve_frame, text="추천값 적용", command=lambda: apply_recommended_stage()).grid(row=0, column=3, sticky="ew")
    ttk.Button(approve_frame, text="계획 승인", command=lambda: handle_approve(ApprovalStage.plan)).grid(row=1, column=0, sticky="ew", pady=(10, 0), padx=(0, 6))
    ttk.Button(approve_frame, text="체크포인트 승인", command=lambda: handle_approve(ApprovalStage.checkpoint)).grid(row=1, column=1, sticky="ew", pady=(10, 0), padx=3)
    ttk.Button(approve_frame, text="머지 승인", command=lambda: handle_approve(ApprovalStage.merge)).grid(row=1, column=2, sticky="ew", pady=(10, 0), padx=3)
    ttk.Button(approve_frame, text="워크스페이스 열기", command=lambda: open_workspace()).grid(row=1, column=3, sticky="ew", pady=(10, 0), padx=(6, 0))

    results_tab = ttk.Frame(control_notebook, padding=10)
    results_tab.columnconfigure(0, weight=1)
    control_notebook.add(results_tab, text="파일 / 바로가기")
    ttk.Label(
        results_tab,
        text="대시보드 밖에서 생성 파일을 직접 확인하고 싶을 때 로컬 폴더를 바로 열 수 있습니다.",
        wraplength=360,
        justify=tk.LEFT,
    ).grid(row=0, column=0, sticky="w", pady=(0, 12))
    ttk.Button(results_tab, text="계획 요약 열기", command=lambda: open_plan_summary()).grid(row=1, column=0, sticky="ew", pady=(0, 8))
    ttk.Button(results_tab, text="매니페스트 열기", command=lambda: open_manifest()).grid(row=2, column=0, sticky="ew", pady=(0, 8))
    ttk.Button(results_tab, text="출력 폴더 열기", command=lambda: open_outputs()).grid(row=3, column=0, sticky="ew", pady=(0, 8))

    details_notebook = ttk.Notebook(details_panel)
    details_notebook.grid(row=0, column=0, sticky="nsew")

    overview_text = make_text_tab(details_notebook, "개요")
    direction_text = make_text_tab(details_notebook, "방향")
    artifacts_text = make_text_tab(details_notebook, "산출물")
    plan_text = make_text_tab(details_notebook, "계획")
    workstreams_tree = make_tree_tab(
        details_notebook,
        "워크스트림",
        columns=("id", "layer", "name", "status", "retries", "files"),
        headings={
            "id": "ID",
            "layer": "레이어",
            "name": "이름",
            "status": "상태",
            "retries": "재시도",
            "files": "변경 파일",
        },
    )
    events_tree = make_tree_tab(
        details_notebook,
        "이벤트",
        columns=("time", "stage", "type", "message"),
        headings={
            "time": "시각",
            "stage": "단계",
            "type": "이벤트",
            "message": "메시지",
        },
    )

    status_bar = ttk.Label(root, textvariable=busy_var, padding=(14, 0, 14, 12), anchor="w")
    status_bar.grid(row=3, column=0, sticky="ew")

    action_buttons: list[ttk.Button] = []

    def set_output_text(widget: ScrolledText, text: str) -> None:
        widget.configure(state=tk.NORMAL)
        widget.delete("1.0", tk.END)
        widget.insert(tk.END, text)
        widget.configure(state=tk.DISABLED)

    def set_input_text(widget: ScrolledText, text: str) -> None:
        widget.configure(state=tk.NORMAL)
        widget.delete("1.0", tk.END)
        widget.insert(tk.END, text)

    def get_text(widget: ScrolledText) -> str:
        return widget.get("1.0", tk.END).strip()

    def load_text_into(widget: ScrolledText) -> None:
        path = filedialog.askopenfilename(
            title="UTF-8 텍스트 또는 마크다운 파일 선택",
            filetypes=[("Text files", "*.md *.txt"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            text = Path(path).read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            messagebox.showerror("잘못된 파일", f"UTF-8 텍스트 파일만 지원합니다.\n\n{exc}")
            return
        set_input_text(widget, text.strip())

    def require_run_id() -> str | None:
        run_id = run_id_var.get().strip()
        if not run_id:
            messagebox.showerror("실행 ID 없음", "먼저 실행 ID를 입력하거나 최근 실행을 불러오세요.")
            return None
        return run_id

    def open_local_path(path: str | Path | None, *, description: str) -> None:
        if path is None:
            messagebox.showerror("경로 없음", f"아직 {description} 경로를 사용할 수 없습니다.")
            return
        target = Path(path)
        if not target.exists():
            messagebox.showerror("경로 없음", f"{description} 경로가 아직 존재하지 않습니다.\n\n{target}")
            return
        os.startfile(target)  # type: ignore[attr-defined]

    def open_workspace() -> None:
        snapshot = latest_snapshot
        if snapshot is None:
            run_id = require_run_id()
            if run_id is None:
                return
            snapshot = build_status_snapshot(memory_factory(), run_id)
        open_local_path(snapshot.run.workspace_path, description="workspace")

    def open_outputs() -> None:
        snapshot = latest_snapshot
        if snapshot is None:
            run_id = require_run_id()
            if run_id is None:
                return
            snapshot = build_status_snapshot(memory_factory(), run_id)
        outputs_path = Path(snapshot.run.workspace_path).parent if snapshot.run.workspace_path else None
        open_local_path(outputs_path, description="outputs folder")

    def open_plan_summary() -> None:
        snapshot = latest_snapshot
        if snapshot is None:
            run_id = require_run_id()
            if run_id is None:
                return
            snapshot = build_status_snapshot(memory_factory(), run_id)
        summary_path = Path(snapshot.run.plan_path).with_name("summary.md") if snapshot.run.plan_path else None
        open_local_path(summary_path, description="plan summary")

    def open_manifest() -> None:
        snapshot = latest_snapshot
        if snapshot is None:
            run_id = require_run_id()
            if run_id is None:
                return
            snapshot = build_status_snapshot(memory_factory(), run_id)
        open_local_path(snapshot.run.manifest_path, description="manifest")

    def worker(label: str, action: Callable[[], object]) -> None:
        nonlocal action_in_progress

        if action_in_progress:
            busy_var.set("이미 백그라운드 작업이 진행 중입니다. 현재 상태가 갱신될 때까지 잠시만 기다려 주세요.")
            return

        def run_action() -> None:
            queue.put(("busy", label, None))
            try:
                result = action()
            except Exception as exc:  # noqa: BLE001
                queue.put(("error", label, exc))
            else:
                queue.put(("result", label, result))

        action_in_progress = True
        threading.Thread(target=run_action, daemon=True).start()

    def set_action_buttons_enabled(enabled: bool) -> None:
        state = tk.NORMAL if enabled else tk.DISABLED
        for button in action_buttons:
            button.configure(state=state)

    def show_busy_message(label: str) -> None:
        busy_var.set(label)
        set_output_text(
            overview_text,
            f"{label}\n\n"
            "원격 모델 호출이 포함되면 30초에서 2분 정도 걸릴 수 있습니다.\n"
            "창이 멈춘 것이 아니라 백그라운드에서 처리 중일 수 있으니 잠시만 기다려 주세요.",
        )

    def refresh_recent_runs(select_run_id: str | None = None) -> None:
        nonlocal recent_runs_map
        memory = memory_factory()
        runs = memory.list_runs(limit=25)
        values: list[str] = []
        mapping: dict[str, str] = {}
        for run in runs:
            label = f"{run.run_id} | {run.stage.value}/{run.status.value} | {run.updated_at.strftime('%m-%d %H:%M')}"
            values.append(label)
            mapping[label] = run.run_id
        recent_runs_map = mapping
        recent_runs_box["values"] = values
        target_run = select_run_id or run_id_var.get().strip()
        if target_run:
            for label, run_id in mapping.items():
                if run_id == target_run:
                    recent_run_var.set(label)
                    break
        elif values:
            recent_run_var.set(values[0])

    def populate_tree(tree: ttk.Treeview, rows: list[tuple[str, ...]]) -> None:
        for item_id in tree.get_children():
            tree.delete(item_id)
        for row in rows:
            tree.insert("", tk.END, values=row)

    def reset_dashboard(*, confirm: bool) -> None:
        nonlocal latest_snapshot, last_auto_refresh
        has_unsaved_input = bool(
            run_id_var.get().strip()
            or recent_run_var.get().strip()
            or get_text(request_box)
            or get_text(feedback_box)
            or latest_snapshot is not None
        )
        if confirm and has_unsaved_input:
            proceed = messagebox.askyesno(
                "새 세션 시작",
                "현재 화면의 입력과 선택된 실행을 비우고 완전히 새 세션을 시작할까요?\n\n"
                "기존 실행 기록은 최근 실행 목록과 결과 폴더에 그대로 남아 있습니다.",
            )
            if not proceed:
                return

        latest_snapshot = None
        last_auto_refresh = 0.0
        run_id_var.set("")
        recent_run_var.set("")
        stage_var.set(ApprovalStage.plan.value)
        current_run_var.set("선택된 실행 없음")
        lifecycle_var.set("단계/상태가 여기에 표시됩니다")
        plan_version_var.set("v000")
        completed_var.set("완료 0개")
        pending_var.set("대기 0개")
        next_step_var.set("계획을 만들거나 실행을 불러오면 시작할 수 있습니다.")
        recommended_stage_var.set("지금은 승인 필요 없음")
        supervisor_mode_var.set("감독 꺼짐")
        supervisor_gate_var.set("게이트 없음")
        supervisor_cycles_var.set("잔여 cycle -")
        set_input_text(request_box, "")
        set_input_text(feedback_box, "")
        overview_message, direction_message, artifacts_message, plan_message = default_dashboard_messages()
        set_output_text(overview_text, overview_message)
        set_output_text(direction_text, direction_message)
        set_output_text(artifacts_text, artifacts_message)
        set_output_text(plan_text, plan_message)
        populate_tree(workstreams_tree, [])
        populate_tree(events_tree, [])
        refresh_recent_runs()

    def apply_snapshot(snapshot: StatusSnapshot) -> None:
        nonlocal latest_snapshot
        latest_snapshot = snapshot
        run_id_var.set(snapshot.run.run_id)
        current_run_var.set(snapshot.run.run_id)
        lifecycle_var.set(f"{snapshot.run.stage.value} / {snapshot.run.status.value}")
        plan_version_var.set(f"v{snapshot.summary.plan_version:03d}")
        completed_var.set(f"완료 {len(snapshot.summary.completed)}개")
        pending_var.set(f"대기 {len(snapshot.summary.pending)}개")
        next_step_var.set(snapshot.summary.next_step)
        recommendation = recommended_approval_stage(snapshot)
        recommended_stage_var.set(recommendation.value if recommendation else "지금은 승인 필요 없음")
        if snapshot.supervisor_session is None:
            supervisor_mode_var.set("감독 꺼짐")
            supervisor_gate_var.set("게이트 없음")
            supervisor_cycles_var.set("잔여 cycle -")
        else:
            remaining_cycles = max(
                snapshot.supervisor_session.max_cycles - snapshot.supervisor_session.cycles_completed,
                0,
            )
            supervisor_mode_var.set(
                f"{'켜짐' if snapshot.supervisor_session.enabled else '꺼짐'} / {snapshot.supervisor_session.status}"
            )
            supervisor_gate_var.set(
                snapshot.supervisor_session.current_gate.value if snapshot.supervisor_session.current_gate else "없음"
            )
            supervisor_cycles_var.set(f"잔여 {remaining_cycles}")
        if recommendation is not None:
            stage_var.set(recommendation.value)

        set_output_text(overview_text, render_overview_text(snapshot))
        set_output_text(direction_text, render_direction_text(snapshot))
        set_output_text(artifacts_text, render_artifacts_text(snapshot))
        set_output_text(plan_text, snapshot.plan_summary_text or "아직 저장된 계획 요약이 없습니다.")

        workstream_rows = []
        for item in snapshot.workstreams:
            files = ", ".join(item["changed_files"]) if item["changed_files"] else "-"
            workstream_rows.append(
                (
                    item["workstream_id"],
                    item["layer"],
                    item["name"],
                    item["status"],
                    str(item["retry_count"]),
                    files,
                )
            )
        populate_tree(workstreams_tree, workstream_rows)

        event_rows = []
        for event in reversed(snapshot.events):
            event_rows.append(
                (
                    event.created_at.astimezone().strftime("%Y-%m-%d %H:%M:%S"),
                    event.stage.value,
                    event.event_type,
                    event.message,
                )
            )
        populate_tree(events_tree, event_rows)

        refresh_recent_runs(select_run_id=snapshot.run.run_id)

    def handle_plan() -> None:
        request = get_text(request_box)
        if not request:
            messagebox.showerror("요청 없음", "제안서를 붙여넣거나 요청 파일을 먼저 불러오세요.")
            return

        def action() -> StatusSnapshot:
            orchestrator = orchestrator_factory()
            run = orchestrator.create_plan(request)
            return build_status_snapshot(memory_factory(), run.run_id)

        worker("계획 생성 중...", action)

    def handle_refresh(*, silent: bool = False) -> None:
        run_id = run_id_var.get().strip()
        if not run_id:
            if not silent:
                messagebox.showerror("실행 ID 없음", "최근 실행을 불러오거나 실행 ID를 먼저 입력하세요.")
            return

        def action() -> StatusSnapshot:
            return build_status_snapshot(memory_factory(), run_id)

        worker("상태 새로고침 중...", action)

    def handle_run() -> None:
        run_id = require_run_id()
        if run_id is None:
            return

        def action() -> StatusSnapshot:
            orchestrator = orchestrator_factory()
            run = orchestrator.run(run_id)
            return build_status_snapshot(memory_factory(), run.run_id)

        worker("파이프라인 실행 중...", action)

    def handle_feedback() -> None:
        run_id = require_run_id()
        if run_id is None:
            return
        comment = get_text(feedback_box)
        if not comment:
            messagebox.showerror("방향 없음", "방향 메모를 작성하거나 파일에서 먼저 불러오세요.")
            return
        actor = actor_var.get().strip() or "local-user"

        def action() -> StatusSnapshot:
            memory = memory_factory()
            memory.append_plan_addition(run_id, comment, actor=actor)
            return build_status_snapshot(memory, run_id)

        worker("방향 저장 중...", action)

    def handle_approve(stage_override: ApprovalStage | None = None) -> None:
        run_id = require_run_id()
        if run_id is None:
            return
        actor = actor_var.get().strip() or "local-user"
        comment = get_text(feedback_box)
        stage = stage_override or ApprovalStage(stage_var.get())

        def action() -> StatusSnapshot:
            orchestrator = orchestrator_factory()
            latest_session = orchestrator.memory.get_latest_supervisor_session(run_id)
            supervisor = None
            if (
                supervisor_factory is not None
                and stage == ApprovalStage.checkpoint
                and latest_session is not None
                and latest_session.status == "blocked"
                and latest_session.current_gate == ApprovalStage.checkpoint
            ):
                supervisor = supervisor_factory()
            run = approve_and_maybe_continue(
                orchestrator,
                run_id=run_id,
                stage=stage,
                actor=actor,
                comment=comment,
                supervisor=supervisor,
            )
            return build_status_snapshot(memory_factory(), run.run_id)

        label = (
            "체크포인트 승인 후 자동 감독 재개 중..."
            if (
                stage == ApprovalStage.checkpoint
                and latest_snapshot is not None
                and latest_snapshot.supervisor_session is not None
                and latest_snapshot.supervisor_session.status == "blocked"
                and latest_snapshot.supervisor_session.current_gate == ApprovalStage.checkpoint
            )
            else (
                "체크포인트 승인 후 자동 진행 중..."
                if stage == ApprovalStage.checkpoint
                else f"{stage.value} 승인 중..."
            )
        )
        worker(label, action)

    def handle_notify() -> None:
        run_id = require_run_id()
        if run_id is None:
            return

        def action() -> StatusSnapshot:
            orchestrator = orchestrator_factory()
            run = orchestrator.notify_status(run_id)
            return build_status_snapshot(memory_factory(), run.run_id)

        worker("알림 전송 중...", action)

    def handle_supervise() -> None:
        run_id = require_run_id()
        if run_id is None:
            return
        if supervisor_factory is None:
            messagebox.showerror("감독관 없음", "이 GUI 실행에는 자동 감독관이 연결되지 않았습니다.")
            return

        def action() -> StatusSnapshot:
            orchestrator = orchestrator_factory()
            supervisor = supervisor_factory()
            run = orchestrator.supervise(run_id, supervisor=supervisor, actor="direction-supervisor")
            return build_status_snapshot(memory_factory(), run.run_id)

        worker("감독관이 방향을 검토하며 자동 진행 중...", action)

    def handle_load_selected() -> None:
        label = recent_run_var.get().strip()
        if not label:
            messagebox.showerror("선택 없음", "먼저 최근 실행 목록에서 하나를 선택하세요.")
            return
        run_id = recent_runs_map.get(label)
        if not run_id:
            messagebox.showerror("실행 없음", "선택한 실행을 찾지 못했습니다. 목록을 새로고침한 뒤 다시 시도하세요.")
            return
        run_id_var.set(run_id)
        handle_refresh()

    def handle_new_session() -> None:
        reset_dashboard(confirm=True)

    def apply_recommended_stage() -> None:
        if latest_snapshot is None:
            messagebox.showerror("상태 없음", "먼저 실행 상태를 새로고침해야 추천 승인을 계산할 수 있습니다.")
            return
        recommendation = recommended_approval_stage(latest_snapshot)
        if recommendation is None:
            messagebox.showerror("추천 없음", "현재 실행은 지금 승인할 단계가 없습니다.")
            return
        stage_var.set(recommendation.value)

    def process_queue() -> None:
        nonlocal action_in_progress, last_auto_refresh, passive_refresh_in_progress
        try:
            while True:
                kind, label, payload = queue.get_nowait()
                if kind == "busy":
                    set_action_buttons_enabled(False)
                    show_busy_message(label)
                elif kind == "progress":
                    passive_refresh_in_progress = False
                    if isinstance(payload, StatusSnapshot):
                        apply_snapshot(payload)
                        last_auto_refresh = time.monotonic()
                elif kind == "error":
                    action_in_progress = False
                    passive_refresh_in_progress = False
                    set_action_buttons_enabled(True)
                    busy_var.set("준비됨")
                    messagebox.showerror("작업 실패", f"{label}\n\n{payload}")
                elif kind == "result":
                    action_in_progress = False
                    passive_refresh_in_progress = False
                    set_action_buttons_enabled(True)
                    busy_var.set("준비됨")
                    if isinstance(payload, StatusSnapshot):
                        apply_snapshot(payload)
                        last_auto_refresh = time.monotonic()
        except Empty:
            pass
        finally:
            root.after(150, process_queue)

    def auto_refresh_pulse() -> None:
        nonlocal last_auto_refresh, passive_refresh_in_progress
        run_id = run_id_var.get().strip()
        if auto_refresh_var.get() and not action_in_progress and run_id:
            try:
                interval = max(int(refresh_seconds_var.get()), 3)
            except ValueError:
                interval = 5
                refresh_seconds_var.set("5")
            now = time.monotonic()
            if now - last_auto_refresh >= interval:
                last_auto_refresh = now
                handle_refresh(silent=True)
        elif action_in_progress and run_id and not passive_refresh_in_progress:
            try:
                interval = max(int(refresh_seconds_var.get()), 3)
            except ValueError:
                interval = 5
                refresh_seconds_var.set("5")
            now = time.monotonic()
            if now - last_auto_refresh >= interval:
                passive_refresh_in_progress = True
                last_auto_refresh = now

                def refresh_snapshot() -> None:
                    try:
                        snapshot = build_status_snapshot(memory_factory(), run_id)
                    except Exception:  # noqa: BLE001
                        queue.put(("progress", "snapshot_error", None))
                    else:
                        queue.put(("progress", "snapshot", snapshot))

                threading.Thread(target=refresh_snapshot, daemon=True).start()
        root.after(1000, auto_refresh_pulse)

    reset_dashboard(confirm=False)

    for child in toolbar.winfo_children():
        if isinstance(child, ttk.Button):
            action_buttons.append(child)
    for child in request_buttons.winfo_children():
        if isinstance(child, ttk.Button):
            action_buttons.append(child)
    for child in feedback_buttons.winfo_children():
        if isinstance(child, ttk.Button):
            action_buttons.append(child)
    for child in approve_frame.winfo_children():
        if isinstance(child, ttk.Button):
            action_buttons.append(child)

    process_queue()
    auto_refresh_pulse()
    recent_runs_box.bind("<<ComboboxSelected>>", lambda _event: handle_load_selected())
    root.mainloop()


def make_text_tab(notebook, title: str):
    import tkinter as tk
    from tkinter import ttk
    from tkinter.scrolledtext import ScrolledText

    frame = ttk.Frame(notebook, padding=10)
    frame.columnconfigure(0, weight=1)
    frame.rowconfigure(0, weight=1)
    text = ScrolledText(frame, wrap=tk.WORD, font=("Consolas", 10))
    text.grid(row=0, column=0, sticky="nsew")
    text.configure(state=tk.DISABLED)
    notebook.add(frame, text=title)
    return text


def make_tree_tab(notebook, title: str, *, columns: tuple[str, ...], headings: dict[str, str]):
    import tkinter as tk
    from tkinter import ttk

    frame = ttk.Frame(notebook, padding=10)
    frame.columnconfigure(0, weight=1)
    frame.rowconfigure(0, weight=1)

    tree = ttk.Treeview(frame, columns=columns, show="headings")
    for column in columns:
        tree.heading(column, text=headings[column])
        width = 140
        if column == "message":
            width = 520
        elif column == "files":
            width = 340
        elif column == "name":
            width = 220
        tree.column(column, width=width, anchor=tk.W, stretch=True)

    y_scroll = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=tree.yview)
    x_scroll = ttk.Scrollbar(frame, orient=tk.HORIZONTAL, command=tree.xview)
    tree.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)

    tree.grid(row=0, column=0, sticky="nsew")
    y_scroll.grid(row=0, column=1, sticky="ns")
    x_scroll.grid(row=1, column=0, sticky="ew")
    notebook.add(frame, text=title)
    return tree
