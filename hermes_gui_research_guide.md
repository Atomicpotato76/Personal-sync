# Hermes GUI — 조사 모드 통합 가이드

## 요약
GUI에 파이프라인 모드 선택(code/research) 기능을 추가한다.
GUI는 tkinter 기반이며 `apps/gui/main.py`에 있다.
orchestrator 등 서비스는 factory 함수로 주입된다.

---

## 수정 1: launch_gui에 mode 파라미터 추가

**파일:** `apps/gui/main.py`
**위치:** `launch_gui` 함수 시그니처 (237줄)

```python
# 변경 전:
def launch_gui(
    *,
    orchestrator_factory: Callable[[], HermesOrchestrator],
    memory_factory: Callable[[], MemoryService],
    supervisor_factory: Callable[[], SupervisorService] | None = None,
) -> None:

# 변경 후:
def launch_gui(
    *,
    orchestrator_factory: Callable[[], HermesOrchestrator],
    memory_factory: Callable[[], MemoryService],
    supervisor_factory: Callable[[], SupervisorService] | None = None,
    initial_mode: str = "code",
    on_mode_change: Callable[[str], None] | None = None,
) -> None:
```

---

## 수정 2: 모드 선택 UI 추가

**파일:** `apps/gui/main.py`
**위치:** toolbar 영역, 약 259~275줄 근처 (변수 선언 영역)

기존 변수 선언부에 mode 변수를 추가한다:

```python
# 기존 변수들 뒤에 추가 (약 274줄 이후):
pipeline_mode_var = tk.StringVar(value=initial_mode)
```

toolbar 2번째 줄(row=1)에 모드 선택 콤보박스를 추가한다.
기존 toolbar row=1에 "감독관 자동 진행" 버튼(column=8) 뒤에 넣는다:

```python
# 약 309줄, "감독관 자동 진행" 버튼 뒤에 추가:
ttk.Label(toolbar, text="모드").grid(row=1, column=9, sticky="w", pady=(10, 0), padx=(8, 4))
mode_combo = ttk.Combobox(
    toolbar,
    textvariable=pipeline_mode_var,
    state="readonly",
    values=["code", "research"],
    width=10,
)
mode_combo.grid(row=1, column=10, sticky="ew", pady=(10, 0))
```

그리고 toolbar columnconfigure에 새 열을 추가한다:

```python
# 기존 (약 286줄):
for idx in range(9):
    toolbar.columnconfigure(idx, weight=1 if idx in {1, 3} else 0)

# 변경:
for idx in range(11):
    toolbar.columnconfigure(idx, weight=1 if idx in {1, 3} else 0)
```

---

## 수정 3: 모드 변경 시 콜백 연결

**파일:** `apps/gui/main.py`
**위치:** `launch_gui` 함수 내부, mainloop 직전 (약 948줄 근처)

```python
# 기존:
recent_runs_box.bind("<<ComboboxSelected>>", lambda _event: handle_load_selected())
root.mainloop()

# 변경:
recent_runs_box.bind("<<ComboboxSelected>>", lambda _event: handle_load_selected())

def _on_mode_selected(_event=None) -> None:
    new_mode = pipeline_mode_var.get()
    if on_mode_change is not None:
        on_mode_change(new_mode)
    mode_label = "조사" if new_mode == "research" else "코딩"
    busy_var.set(f"파이프라인 모드: {mode_label}")

mode_combo.bind("<<ComboboxSelected>>", _on_mode_selected)
root.mainloop()
```

---

## 수정 4: 제안서 영역의 안내 텍스트를 모드에 따라 변경

**파일:** `apps/gui/main.py`
**위치:** request_frame 안의 Label 텍스트 (약 348~353줄)

기존 고정 텍스트 대신 모드에 따라 동적으로 변경한다:

```python
# 기존 (약 348줄):
ttk.Label(
    request_frame,
    text="여기에 프로젝트 제안서를 붙여넣거나, 마크다운 파일을 불러온 뒤 계획을 생성하세요.",
    wraplength=360,
    justify=tk.LEFT,
).grid(row=0, column=0, sticky="w", pady=(0, 8))

# 변경:
request_guide_var = tk.StringVar(
    value="여기에 프로젝트 제안서를 붙여넣거나, 마크다운 파일을 불러온 뒤 계획을 생성하세요."
    if initial_mode == "code"
    else "여기에 조사 주제를 붙여넣거나, 마크다운 파일을 불러온 뒤 조사 계획을 생성하세요."
)
ttk.Label(
    request_frame,
    textvariable=request_guide_var,
    wraplength=360,
    justify=tk.LEFT,
).grid(row=0, column=0, sticky="w", pady=(0, 8))
```

그리고 _on_mode_selected 함수 안에 안내 텍스트 변경을 추가한다:

```python
def _on_mode_selected(_event=None) -> None:
    new_mode = pipeline_mode_var.get()
    if on_mode_change is not None:
        on_mode_change(new_mode)
    mode_label = "조사" if new_mode == "research" else "코딩"
    busy_var.set(f"파이프라인 모드: {mode_label}")
    # 안내 텍스트 업데이트
    if new_mode == "research":
        request_guide_var.set("여기에 조사 주제를 붙여넣거나, 마크다운 파일을 불러온 뒤 조사 계획을 생성하세요.")
    else:
        request_guide_var.set("여기에 프로젝트 제안서를 붙여넣거나, 마크다운 파일을 불러온 뒤 계획을 생성하세요.")
```

---

## 수정 5: 대시보드 기본 메시지에 모드 반영

**파일:** `apps/gui/main.py`
**위치:** `default_dashboard_messages` 함수 (48줄)

```python
# 변경 전:
def default_dashboard_messages() -> tuple[str, str, str, str]:
    overview = (
        "Hermes 파이프라인 대시보드\n\n"
        "1. 제안서를 붙여넣거나 마크다운 파일을 불러옵니다.\n"
        ...
    )

# 변경 후:
def default_dashboard_messages(mode: str = "code") -> tuple[str, str, str, str]:
    if mode == "research":
        overview = (
            "Hermes 조사 파이프라인 대시보드\n\n"
            "1. 조사 주제를 붙여넣거나 마크다운 파일을 불러옵니다.\n"
            "2. 조사 계획을 생성합니다.\n"
            "3. 개요와 방향 탭을 검토합니다.\n"
            "4. 추천된 승인을 진행한 뒤 파이프라인을 실행합니다.\n"
            "5. 산출물 탭과 폴더 열기 버튼으로 조사 결과를 확인합니다.\n"
            "6. 완전히 다른 조사를 시작하려면 상단의 '새 세션 시작'을 누르세요."
        )
    else:
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
```

그리고 이 함수를 호출하는 곳(`reset_dashboard` 내부, 약 636줄)도 수정한다:

```python
# 변경 전:
overview_message, direction_message, artifacts_message, plan_message = default_dashboard_messages()

# 변경 후:
overview_message, direction_message, artifacts_message, plan_message = default_dashboard_messages(
    mode=pipeline_mode_var.get()
)
```

---

## 수정 6: CLI의 gui 커맨드에서 mode 전달

**파일:** `apps/cli/main.py`
**위치:** `gui` 함수 (약 412줄)

CLI의 gui() 커맨드가 launch_gui를 호출할 때 mode를 전달하고,
모드 변경 시 settings를 업데이트하는 콜백을 넘긴다:

```python
@app.command()
def gui() -> None:
    from apps.gui.main import launch_gui

    settings = get_settings()

    def on_mode_change(new_mode: str) -> None:
        settings.pipeline_mode = new_mode

    launch_gui(
        orchestrator_factory=lambda: build_orchestrator(settings),
        memory_factory=lambda: build_memory(settings),
        supervisor_factory=lambda: build_supervisor(settings) if settings.supervisor_mode_enabled else None,
        initial_mode=settings.pipeline_mode,
        on_mode_change=on_mode_change,
    )
```

이렇게 하면 GUI에서 모드를 바꿀 때마다 settings 객체가 업데이트되고,
다음 orchestrator_factory() 호출 시 변경된 mode가 각 서비스에 전달된다.

---

## 주의사항

- 기존 GUI의 모든 기능은 그대로 유지한다
- mode 변경은 "다음 plan/run" 부터 적용된다 (진행 중인 run에는 영향 없음)
- window title에 현재 모드를 표시하면 사용자가 혼동하지 않는다:

```python
# _on_mode_selected 안에 추가:
mode_title = "조사" if new_mode == "research" else "개발"
root.title(f"Hermes {mode_title} 파이프라인 대시보드")
```

- reset_dashboard에서도 title을 리셋한다:

```python
# reset_dashboard 안에 추가:
mode_title = "조사" if pipeline_mode_var.get() == "research" else "개발"
root.title(f"Hermes {mode_title} 파이프라인 대시보드")
```
