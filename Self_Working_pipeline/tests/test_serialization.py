import pytest
from pydantic import BaseModel

from core.serialization import parse_json_model, sanitize_json_block


class Envelope(BaseModel):
    name: str
    value: int


def test_sanitize_strips_outer_fence() -> None:
    raw = "```json\n{\"name\": \"a\", \"value\": 1}\n```"
    assert sanitize_json_block(raw) == '{"name": "a", "value": 1}'


def test_sanitize_extracts_fenced_block_after_prose() -> None:
    raw = "Here is the JSON:\n```json\n{\"name\": \"a\", \"value\": 2}\n```\nHope this helps."
    assert sanitize_json_block(raw) == '{"name": "a", "value": 2}'


def test_sanitize_slices_to_outermost_braces_when_unfenced() -> None:
    raw = "Sure! The answer is {\"name\": \"a\", \"value\": 3} — let me know."
    assert sanitize_json_block(raw) == '{"name": "a", "value": 3}'


def test_sanitize_returns_raw_when_no_json_found() -> None:
    raw = "this is just text"
    assert sanitize_json_block(raw) == "this is just text"


def test_parse_json_model_with_prose_prefix() -> None:
    raw = "Result: ```json\n{\"name\": \"x\", \"value\": 7}\n```"
    parsed = parse_json_model(raw, Envelope)
    assert parsed.name == "x"
    assert parsed.value == 7


def test_parse_json_model_raises_on_invalid_payload() -> None:
    with pytest.raises(Exception):
        parse_json_model("not json at all", Envelope)
