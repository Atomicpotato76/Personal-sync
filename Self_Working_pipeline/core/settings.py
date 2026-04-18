from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    workspace_root: Path = Path.cwd()
    default_guidance_prompt_path: Path | None = Path(r"C:\Users\skyhu\Downloads\vibe-coding-prompts.md")
    discord_webhook_url: str | None = None
    discord_webhook_username: str = "Hermes Pipeline"
    planner_model: str = "claude-opus-4-6"
    executor_model: str = "gpt-4.1"
    reviewer_model: str = "claude-opus-4-6"
    supervisor_mode_enabled: bool = False
    supervisor_model_plan: str = "claude-opus-4-6"
    supervisor_model_checkpoint: str = "claude-opus-4-6"
    supervisor_model_merge: str = "claude-opus-4-6"
    supervisor_max_cycles: int = 20
    supervisor_max_same_gate_repeats: int = 3
    supervisor_max_supervisor_denials: int = 1
    supervisor_max_consecutive_failures: int = 2
    supervisor_max_plan_revisions: int = 3
    anthropic_api_key: str | None = None
    openai_api_key: str | None = None
    anthropic_thinking_enabled: bool = True
    anthropic_thinking_type: str = "adaptive"
    anthropic_thinking_budget_tokens: int = 2000
    anthropic_max_output_tokens: int = 8000
    planner_request_digest_chars: int = 4000
    pipeline_db_path: str = "outputs/pipeline.db"
    max_retries_per_workstream: int = 2
    pipeline_mode: str = "code"

    model_config = SettingsConfigDict(
        extra="ignore",
    )

    @property
    def plans_dir(self) -> Path:
        return self.workspace_root / "plans"

    @property
    def outputs_dir(self) -> Path:
        return self.workspace_root / "outputs"

    @property
    def database_path(self) -> Path:
        return self.workspace_root / self.pipeline_db_path


def get_settings() -> Settings:
    settings = Settings()
    settings.plans_dir.mkdir(parents=True, exist_ok=True)
    settings.outputs_dir.mkdir(parents=True, exist_ok=True)
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    return settings
