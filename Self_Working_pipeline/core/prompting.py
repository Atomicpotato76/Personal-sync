from __future__ import annotations

from pathlib import Path

from core.settings import Settings


def load_guidance_prompt(settings: Settings) -> str:
    path = settings.default_guidance_prompt_path
    if path is None:
        return ""
    prompt_path = Path(path)
    if not prompt_path.exists() or not prompt_path.is_file():
        return ""
    try:
        return prompt_path.read_text(encoding="utf-8").strip()
    except UnicodeDecodeError:
        return prompt_path.read_text(encoding="utf-8-sig", errors="ignore").strip()


def compose_system_prompt(base_prompt: str, guidance_prompt: str, *, section_name: str) -> str:
    if not guidance_prompt:
        return base_prompt
    return (
        f"{base_prompt}\n\n"
        f"Default guidance prompt for this repository.\n"
        f"Treat the following document as standing instruction unless it conflicts with the explicit task.\n"
        f"Focus most on the parts relevant to: {section_name}.\n\n"
        f"{guidance_prompt}"
    )
