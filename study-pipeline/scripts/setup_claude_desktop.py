#!/usr/bin/env python3
"""setup_claude_desktop.py -- Claude Desktop에 Study Pipeline MCP 서버 등록.

실행:
  python setup_claude_desktop.py          # 설정 추가
  python setup_claude_desktop.py --check  # 현재 상태 확인
  python setup_claude_desktop.py --remove # 설정 제거
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_YAML = SCRIPT_DIR / "config.yaml"
MCP_SERVER_PY = SCRIPT_DIR / "mcp_server.py"

# Claude Desktop 설정 파일 경로
CLAUDE_CONFIG_DIR = Path(os.environ.get("APPDATA", "")) / "Claude"
CLAUDE_CONFIG_PATH = CLAUDE_CONFIG_DIR / "claude_desktop_config.json"

SERVER_NAME = "study-pipeline"


def get_python_path() -> str:
    """현재 Python 실행 경로."""
    return sys.executable


def build_server_config() -> dict:
    """MCP 서버 등록 설정 생성."""
    return {
        "command": get_python_path(),
        "args": [str(MCP_SERVER_PY)],
        "env": {
            "STUDY_PIPELINE_CONFIG": str(CONFIG_YAML),
        },
    }


def load_claude_config() -> dict:
    """기존 Claude Desktop 설정 로드."""
    if CLAUDE_CONFIG_PATH.exists():
        with open(CLAUDE_CONFIG_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_claude_config(config: dict) -> None:
    """Claude Desktop 설정 저장 (백업 포함)."""
    CLAUDE_CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    # 기존 파일 백업
    if CLAUDE_CONFIG_PATH.exists():
        backup = CLAUDE_CONFIG_PATH.with_suffix(".json.bak")
        shutil.copy2(CLAUDE_CONFIG_PATH, backup)
        print(f"  백업: {backup}")

    with open(CLAUDE_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


def cmd_install():
    """Study Pipeline MCP 서버를 Claude Desktop에 등록."""
    print("=== Claude Desktop MCP 서버 등록 ===\n")

    # 사전 검사
    if not MCP_SERVER_PY.exists():
        print(f"[ERROR] MCP 서버 파일 없음: {MCP_SERVER_PY}")
        return

    # mcp 패키지 확인
    try:
        import mcp
        _ver = getattr(mcp, "__version__", "installed")
        print(f"  mcp 패키지: {_ver}")
    except ImportError:
        print("  [WARN] mcp 패키지 미설치. 설치 중...")
        os.system(f"{get_python_path()} -m pip install mcp")

    config = load_claude_config()
    servers = config.setdefault("mcpServers", {})

    if SERVER_NAME in servers:
        print(f"  '{SERVER_NAME}' 서버가 이미 등록되어 있습니다. 덮어쓰기합니다.")

    servers[SERVER_NAME] = build_server_config()
    save_claude_config(config)

    print(f"\n[OK] 등록 완료!")
    print(f"  설정 파일: {CLAUDE_CONFIG_PATH}")
    print(f"  서버: {SERVER_NAME}")
    print(f"  Python: {get_python_path()}")
    print(f"  MCP server: {MCP_SERVER_PY}")
    print(f"\n  → Claude Desktop을 재시작하면 적용됩니다.")
    print(f"  → 대화창에서 study_search_notes, study_get_weak_concepts 등을 사용할 수 있습니다.")
    print(f"  → Hermes 일정 관리 도구(study_get_schedule, study_plan_week, study_add_exam_or_deadline)도 함께 사용할 수 있습니다.")


def cmd_check():
    """현재 등록 상태 확인."""
    print("=== Claude Desktop MCP 설정 확인 ===\n")

    if not CLAUDE_CONFIG_PATH.exists():
        print(f"  설정 파일 없음: {CLAUDE_CONFIG_PATH}")
        print(f"  → python {Path(__file__).name} 으로 등록하세요.")
        return

    config = load_claude_config()
    servers = config.get("mcpServers", {})

    if SERVER_NAME not in servers:
        print(f"  '{SERVER_NAME}' 서버가 등록되어 있지 않습니다.")
        return

    server = servers[SERVER_NAME]
    print(f"  서버: {SERVER_NAME}")
    print(f"  command: {server.get('command', '?')}")
    print(f"  args: {server.get('args', [])}")
    print(f"  env: {json.dumps(server.get('env', {}), indent=4)}")

    # MCP 서버 파일 존재 확인
    args = server.get("args", [])
    if args:
        server_path = Path(args[0])
        print(f"\n  서버 파일 존재: {'✅' if server_path.exists() else '❌'} {server_path}")

    # 다른 등록된 서버 표시
    other = [k for k in servers if k != SERVER_NAME]
    if other:
        print(f"\n  기타 등록 서버: {', '.join(other)}")


def cmd_remove():
    """Study Pipeline MCP 서버 등록 제거."""
    print("=== Claude Desktop MCP 서버 제거 ===\n")

    if not CLAUDE_CONFIG_PATH.exists():
        print(f"  설정 파일 없음. 제거할 것이 없습니다.")
        return

    config = load_claude_config()
    servers = config.get("mcpServers", {})

    if SERVER_NAME not in servers:
        print(f"  '{SERVER_NAME}' 서버가 등록되어 있지 않습니다.")
        return

    del servers[SERVER_NAME]
    save_claude_config(config)
    print(f"  [OK] '{SERVER_NAME}' 서버 제거 완료.")
    print(f"  → Claude Desktop을 재시작하면 적용됩니다.")


def main():
    if "--check" in sys.argv:
        cmd_check()
    elif "--remove" in sys.argv:
        cmd_remove()
    else:
        cmd_install()


if __name__ == "__main__":
    main()
