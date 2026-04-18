#!/usr/bin/env python3
"""env_utils.py -- 환경변수/Windows 사용자 환경 레지스트리 조회 유틸."""

from __future__ import annotations

import os
import sys


def get_env_value(name: str) -> str | None:
    value = os.environ.get(name)
    if value:
        return value

    if sys.platform != "win32":
        return None

    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            value, _ = winreg.QueryValueEx(key, name)
            return value or None
    except OSError:
        return None


def has_env_value(name: str) -> bool:
    return bool(get_env_value(name))
