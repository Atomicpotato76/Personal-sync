from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


SECRET_PATTERNS: dict[str, re.Pattern[str]] = {
    "openai_like": re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    "anthropic_like": re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}\b"),
}

DEFAULT_EXCLUDES = {
    ".git",
    ".pytest_cache",
    "__pycache__",
    "build",
    "dist",
    "outputs",
    "plans",
}


@dataclass(slots=True)
class SecretFinding:
    path: str
    pattern_name: str
    line_number: int
    preview: str


def _is_excluded(path: Path, root: Path) -> bool:
    try:
        relative = path.relative_to(root)
    except ValueError:
        return True
    return any(part in DEFAULT_EXCLUDES for part in relative.parts)


def scan_for_secrets(root: Path) -> list[SecretFinding]:
    findings: list[SecretFinding] = []
    for path in root.rglob("*"):
        if not path.is_file() or _is_excluded(path, root):
            continue
        if path.name == ".env.example":
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (UnicodeDecodeError, OSError):
            continue
        for index, line in enumerate(lines, start=1):
            for name, pattern in SECRET_PATTERNS.items():
                if pattern.search(line):
                    findings.append(
                        SecretFinding(
                            path=str(path.relative_to(root).as_posix()),
                            pattern_name=name,
                            line_number=index,
                            preview=line[:120],
                        )
                    )
    return findings
