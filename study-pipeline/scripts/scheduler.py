#!/usr/bin/env python3
"""scheduler.py -- Windows Task Scheduler에 매일 밤 자동 실행 등록.

서브커맨드:
  register   - 매일 22:00 자동 실행 작업 등록
  unregister - 등록된 작업 삭제
  run-now    - 즉시 실행 (오늘 수정된 파일만)
  status     - 등록 상태 확인
"""

from __future__ import annotations

import io
import os
import subprocess
import sys
from datetime import datetime, date
from pathlib import Path

if sys.stdout.encoding != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import yaml

from path_utils import get_study_paths

# ── 경로 설정 ──────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_PATH = SCRIPT_DIR / "config.yaml"
SYNTHESIZE_PY = SCRIPT_DIR / "synthesize.py"
TASK_NAME = "ObsidianQuizPipeline"
EXCLUDED_OUTPUT_FOLDERS = frozenset({"퀴즈", "정리"})


def load_config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


# ── 오늘 수정된 파일 수집 ──────────────────────────────────
def collect_today_files(config: dict) -> list[Path]:
    """notes_dir 하위에서 오늘 수정된 .md 파일만 수집."""
    notes_base = get_study_paths(config).notes_base
    folder_mapping: dict = config.get("folder_mapping", {})
    today = date.today()

    files = []
    for subject_folder in folder_mapping:
        subject_dir = notes_base / subject_folder
        if not subject_dir.exists():
            continue
        for md_file in subject_dir.rglob("*.md"):
            # pipeline이 다시 써 넣는 산출물 폴더는 제외
            rel_parts = md_file.relative_to(subject_dir).parts
            if any(part in EXCLUDED_OUTPUT_FOLDERS for part in rel_parts):
                continue
            mtime = datetime.fromtimestamp(md_file.stat().st_mtime).date()
            if mtime == today:
                files.append(md_file)

    return sorted(files)


# ── 오늘 수정된 파일 처리 ──────────────────────────────────
def run_today(config: dict) -> None:
    """오늘 수정된 파일에 대해 synthesize.py를 실행."""
    files = collect_today_files(config)
    if not files:
        print("오늘 수정된 파일이 없습니다.")
        return

    print(f"오늘 수정된 파일: {len(files)}개")
    for f in files:
        print(f"  - {f.name}")
    print()

    success = 0
    fail = 0
    for file_path in files:
        print(f"[처리 중] {file_path.name}")
        cmd = [sys.executable, str(SYNTHESIZE_PY), str(file_path)]
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=120,
                cwd=str(SCRIPT_DIR),
            )
            if result.returncode == 0:
                print("  [OK] 성공")
                success += 1
            else:
                print(f"  [ERROR] 실패 (exit {result.returncode})")
                if result.stdout.strip():
                    print(f"  stdout: {result.stdout.strip()}")
                fail += 1
        except subprocess.TimeoutExpired:
            print("  [ERROR] 타임아웃")
            fail += 1
        except Exception as e:
            print(f"  [ERROR] 오류: {e}")
            fail += 1
        print()

    print(f"완료: 성공 {success}개, 실패 {fail}개")


# ── 배치 스크립트 생성 ─────────────────────────────────────
def create_batch_script() -> Path:
    """scheduler가 호출할 .bat 파일을 생성."""
    bat_path = SCRIPT_DIR / "run_daily.bat"
    python_exe = sys.executable

    # 환경변수에서 API 키를 가져오는 배치 스크립트
    bat_content = f"""@echo off
chcp 65001 >nul
cd /d "{SCRIPT_DIR}"
"{python_exe}" "{SCRIPT_DIR / 'scheduler.py'}" run-now
"""
    bat_path.write_text(bat_content, encoding="utf-8")
    return bat_path


# ── register ───────────────────────────────────────────────
def cmd_register() -> None:
    """Windows Task Scheduler에 매일 22:00 작업 등록."""
    bat_path = create_batch_script()

    # 기존 작업 삭제 (무시)
    subprocess.run(
        ["schtasks", "/delete", "/tn", TASK_NAME, "/f"],
        capture_output=True,
    )

    # 새 작업 등록
    result = subprocess.run(
        [
            "schtasks", "/create",
            "/tn", TASK_NAME,
            "/tr", str(bat_path),
            "/sc", "daily",
            "/st", "22:00",
            "/f",
        ],
        capture_output=True,
        text=True,
        encoding="cp949",
        errors="replace",
    )

    if result.returncode == 0:
        print(f"작업 등록 완료: {TASK_NAME}")
        print(f"  스케줄: 매일 22:00")
        print(f"  배치 파일: {bat_path}")
        print(f"  확인: schtasks /query /tn {TASK_NAME}")
    else:
        print(f"[ERROR] 작업 등록 실패:")
        print(result.stderr or result.stdout)


# ── unregister ─────────────────────────────────────────────
def cmd_unregister() -> None:
    """등록된 작업 삭제."""
    result = subprocess.run(
        ["schtasks", "/delete", "/tn", TASK_NAME, "/f"],
        capture_output=True,
        text=True,
        encoding="cp949",
        errors="replace",
    )
    if result.returncode == 0:
        print(f"작업 삭제 완료: {TASK_NAME}")
    else:
        print(f"작업이 존재하지 않거나 삭제 실패:")
        print(result.stderr or result.stdout)


# ── status ─────────────────────────────────────────────────
def cmd_status() -> None:
    """등록 상태 확인."""
    result = subprocess.run(
        ["schtasks", "/query", "/tn", TASK_NAME, "/v", "/fo", "list"],
        capture_output=True,
        text=True,
        encoding="cp949",
        errors="replace",
    )
    if result.returncode == 0:
        print(result.stdout)
    else:
        print(f"작업 '{TASK_NAME}'이(가) 등록되어 있지 않습니다.")


# ── main ──────────────────────────────────────────────────
def main() -> None:
    if len(sys.argv) < 2:
        print("사용법:")
        print("  python scheduler.py register   - 매일 22:00 자동 실행 등록")
        print("  python scheduler.py unregister - 등록된 작업 삭제")
        print("  python scheduler.py run-now    - 즉시 실행 (오늘 수정 파일만)")
        print("  python scheduler.py status     - 등록 상태 확인")
        sys.exit(0)

    cmd = sys.argv[1]
    config = load_config()

    if cmd == "register":
        cmd_register()
    elif cmd == "unregister":
        cmd_unregister()
    elif cmd == "run-now":
        run_today(config)
    elif cmd == "status":
        cmd_status()
    else:
        print(f"[ERROR] 알 수 없는 명령: {cmd}")
        sys.exit(1)


if __name__ == "__main__":
    main()
