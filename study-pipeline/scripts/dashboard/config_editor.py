"""config_editor.py -- config.yaml 안전한 읽기/쓰기/백업."""
from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

from ruamel.yaml import YAML


_yaml = YAML()
_yaml.preserve_quotes = True
_yaml.width = 120


def load_config(config_path: Path) -> dict:
    """config.yaml을 dict로 로드 (ruamel로 주석 보존 구조체)."""
    with open(config_path, encoding="utf-8") as f:
        return _yaml.load(f)


def save_config(config_path: Path, data: dict, backup: bool = True) -> str | None:
    """config.yaml 저장. 백업 생성 후 저장. 오류 시 메시지 반환."""
    try:
        # 필수 키 검증
        for key in ("vault_path", "llm", "subjects"):
            if key not in data:
                return f"필수 키 누락: {key}"

        # 백업
        if backup:
            backup_dir = config_path.parent / "config_backups"
            backup_dir.mkdir(exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = backup_dir / f"config_{ts}.yaml"
            shutil.copy2(config_path, backup_path)
            _cleanup_old_backups(backup_dir, keep=10)

        # 저장
        with open(config_path, "w", encoding="utf-8") as f:
            _yaml.dump(data, f)
        return None  # 성공
    except Exception as e:
        return f"저장 실패: {e}"


def list_backups(config_path: Path) -> list[dict]:
    """백업 목록 반환."""
    backup_dir = config_path.parent / "config_backups"
    if not backup_dir.exists():
        return []
    backups = []
    for f in sorted(backup_dir.glob("config_*.yaml"), reverse=True):
        stat = f.stat()
        backups.append({
            "name": f.name,
            "path": str(f),
            "size": stat.st_size,
            "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
        })
    return backups


def restore_backup(backup_path: Path, config_path: Path) -> str | None:
    """백업에서 복원."""
    try:
        shutil.copy2(backup_path, config_path)
        return None
    except Exception as e:
        return f"복원 실패: {e}"


def _cleanup_old_backups(backup_dir: Path, keep: int = 10):
    files = sorted(backup_dir.glob("config_*.yaml"))
    while len(files) > keep:
        files.pop(0).unlink()
