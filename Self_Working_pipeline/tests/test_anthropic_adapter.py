from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from services.adapters.anthropic_adapter import AnthropicJsonAdapter


class TinyModel(BaseModel):
    value: str


class EnvelopeModel(BaseModel):
    result: TinyModel


def _message(*, text: str, stop_reason: str = "end_turn") -> SimpleNamespace:
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)],
        stop_reason=stop_reason,
    )


def _make_adapter(responses: list[SimpleNamespace]) -> tuple[AnthropicJsonAdapter, list[dict]]:
    calls: list[dict] = []

    class DummyClient:
        def __init__(self) -> None:
            self.messages = SimpleNamespace(create=self.create)

        def create(self, **kwargs):
            calls.append(kwargs)
            return responses[len(calls) - 1]

    adapter = AnthropicJsonAdapter(
        api_key="test-key",
        model="test-model",
        thinking_enabled=True,
        max_output_tokens=5000,
    )
    adapter.client = DummyClient()
    return adapter, calls


def test_generate_structured_retries_without_thinking_when_truncated() -> None:
    adapter, calls = _make_adapter(
        [
            _message(text='{"value": "truncated', stop_reason="max_tokens"),
            _message(text='{"value": "ok"}'),
        ]
    )

    result = adapter.generate_structured(
        system_prompt="system",
        user_prompt="user",
        response_model=TinyModel,
    )

    assert result.value == "ok"
    assert len(calls) == 2
    assert "thinking" in calls[0]
    assert "thinking" not in calls[1]
    assert calls[1]["max_tokens"] == 12000


def test_generate_structured_retries_on_validation_error() -> None:
    # First response: valid JSON but missing envelope wrapper -> ValidationError.
    # Second response: correct wrapped payload after schema reinforcement.
    adapter, calls = _make_adapter(
        [
            _message(text='{"value": "no-envelope"}'),
            _message(text='{"result": {"value": "wrapped"}}'),
        ]
    )

    envelope = adapter.generate_structured(
        system_prompt="system",
        user_prompt="user",
        response_model=EnvelopeModel,
    )

    assert envelope.result.value == "wrapped"
    assert len(calls) == 2
    # Retry should include the schema reinforcement hint.
    assert "schema validation" in calls[1]["system"]


def test_generate_structured_extracts_json_from_prose() -> None:
    prose = "Here is the JSON you requested:\n```json\n{\"value\": \"clean\"}\n```\nThanks."
    adapter, _ = _make_adapter([_message(text=prose)])

    result = adapter.generate_structured(
        system_prompt="system",
        user_prompt="user",
        response_model=TinyModel,
    )

    assert result.value == "clean"


def test_generate_structured_raises_runtime_error_after_retry_fails() -> None:
    adapter, calls = _make_adapter(
        [
            _message(text="totally not json"),
            _message(text="still not json"),
        ]
    )

    with pytest.raises(RuntimeError) as excinfo:
        adapter.generate_structured(
            system_prompt="system",
            user_prompt="user",
            response_model=TinyModel,
        )

    assert "after retry" in str(excinfo.value)
    assert len(calls) == 2
