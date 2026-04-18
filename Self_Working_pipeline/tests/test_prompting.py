from pathlib import Path

from core.prompting import compose_system_prompt, load_guidance_prompt
from core.settings import Settings


def test_load_guidance_prompt_reads_configured_file(tmp_path: Path) -> None:
    prompt_path = tmp_path / "guidance.md"
    prompt_path.write_text("# Guidance\nAlways test.\n", encoding="utf-8")
    settings = Settings(
        workspace_root=tmp_path,
        pipeline_db_path="outputs/test.db",
        anthropic_api_key="test-anthropic",
        openai_api_key="test-openai",
        default_guidance_prompt_path=prompt_path,
    )

    loaded = load_guidance_prompt(settings)

    assert "# Guidance" in loaded
    assert "Always test." in loaded


def test_compose_system_prompt_appends_guidance() -> None:
    combined = compose_system_prompt("Base prompt", "Shared guidance", section_name="testing")

    assert "Base prompt" in combined
    assert "Shared guidance" in combined
    assert "testing" in combined
