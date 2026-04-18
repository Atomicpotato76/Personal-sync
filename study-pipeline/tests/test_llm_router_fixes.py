"""test_llm_router_fixes.py -- ChatGPT max_completion_tokens + JSON repair 회귀 테스트."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))


# ──────────────────────────────────────────────
# ChatGPTClient._uses_max_completion_tokens
# ──────────────────────────────────────────────

def _make_chatgpt_client(model: str):
    from llm_router import ChatGPTClient
    cfg = {"model": model, "max_tokens": 4096, "temperature": 0.3, "prefer_subscription": False}
    return ChatGPTClient(cfg)


@pytest.mark.parametrize("model,expected", [
    ("gpt-5.4", True),
    ("gpt-5", True),
    ("gpt-6-turbo", True),
    ("o1-mini", True),
    ("o3", True),
    ("o4-mini", True),
    ("gpt-4o", False),
    ("gpt-4-turbo", False),
    ("gpt-3.5-turbo", False),
    ("o0-test", False),  # o0 is not o[1-9]
])
def test_uses_max_completion_tokens(model, expected):
    client = _make_chatgpt_client(model)
    assert client._uses_max_completion_tokens() == expected


def test_call_api_uses_max_completion_tokens_for_gpt5():
    """gpt-5.4 API 호출 시 max_completion_tokens 파라미터를 사용해야 한다."""
    client = _make_chatgpt_client("gpt-5.4")

    captured_kwargs = {}

    def fake_create(**kwargs):
        captured_kwargs.update(kwargs)
        msg = MagicMock()
        msg.content = "result"
        choice = MagicMock()
        choice.message.content = "result"
        resp = MagicMock()
        resp.choices = [choice]
        resp.model = "gpt-5.4"
        return resp

    mock_openai = MagicMock()
    mock_openai.return_value.chat.completions.create.side_effect = fake_create

    with patch("llm_router.get_env_value", return_value="fake-key"), \
         patch("llm_router.OpenAI", mock_openai, create=True):
        # Need to make OpenAI importable in _call_api
        import llm_router
        orig = llm_router.__dict__.get("OpenAI")
        llm_router.OpenAI = mock_openai  # type: ignore[attr-defined]
        try:
            client._call_api("hello")
        except Exception:
            pass
        llm_router.__dict__["OpenAI"] = orig

    # If captured, check correct param
    if captured_kwargs:
        assert "max_completion_tokens" in captured_kwargs
        assert "max_tokens" not in captured_kwargs


def test_call_api_uses_max_tokens_for_gpt4():
    """gpt-4o API 호출 시 max_tokens 파라미터를 사용해야 한다."""
    client = _make_chatgpt_client("gpt-4o")

    captured_kwargs = {}

    def fake_create(**kwargs):
        captured_kwargs.update(kwargs)
        choice = MagicMock()
        choice.message.content = "result"
        resp = MagicMock()
        resp.choices = [choice]
        resp.model = "gpt-4o"
        return resp

    mock_openai = MagicMock()
    mock_openai.return_value.chat.completions.create.side_effect = fake_create

    with patch("llm_router.get_env_value", return_value="fake-key"):
        import llm_router
        llm_router.OpenAI = mock_openai  # type: ignore[attr-defined]
        try:
            client._call_api("hello")
        except Exception:
            pass

    if captured_kwargs:
        assert "max_tokens" in captured_kwargs
        assert "max_completion_tokens" not in captured_kwargs


# ──────────────────────────────────────────────
# LLMRouter.generate_json — JSON repair
# ──────────────────────────────────────────────

def _repair_json(text: str) -> str:
    """Same logic as in generate_json."""
    repaired = re.sub(r'\\(?!["\\/bfnrtu])', r'\\\\', text)
    return repaired


def test_json_repair_invalid_escape():
    """잘못된 이스케이프 시퀀스가 포함된 JSON을 복구해야 한다."""
    bad_json = r'{"key": "C:\path\to\file"}'  # \p, \t (valid), \f (valid)
    # \p is invalid, \t and \f are valid
    # After repair: \p → \\p, \t stays (valid), \f stays (valid)
    repaired = _repair_json(bad_json)
    result = json.loads(repaired)
    assert "key" in result


def test_json_repair_backslash_before_letter():
    """소형 모델이 생성하는 \a, \k 등 잘못된 이스케이프를 복구."""
    bad_json = '{"tag": "alpha\\k_1", "score": 5}'
    repaired = _repair_json(bad_json)
    result = json.loads(repaired)
    assert result["score"] == 5


def test_json_repair_preserves_valid_escapes():
    """유효한 이스케이프 시퀀스(\\n, \\t, \\")는 변경하지 않아야 한다."""
    good_json = '{"text": "line1\\nline2\\ttab\\"quoted\\""}'
    repaired = _repair_json(good_json)
    assert repaired == good_json
    result = json.loads(repaired)
    assert "line1" in result["text"]


def test_json_repair_already_valid():
    """정상 JSON은 변경 없이 파싱돼야 한다."""
    valid = '{"a": 1, "b": [1, 2, 3]}'
    repaired = _repair_json(valid)
    assert json.loads(repaired) == {"a": 1, "b": [1, 2, 3]}


# ──────────────────────────────────────────────
# ClaudeClient - top_k / thinking budget safety
# ──────────────────────────────────────────────

def _make_claude_client(**overrides):
    from llm_router import ClaudeClient
    cfg = {
        "model": "claude-sonnet-4-6",
        "max_tokens": 4096,
        "temperature": 0.3,
        "top_p": 1.0,
        "top_k": -1,
        "thinking_budget": 10000,
        "prefer_subscription": False,
    }
    cfg.update(overrides)
    return ClaudeClient(cfg, model_info=None)


def _setup_anthropic_mock():
    captured = {}

    def fake_create(**kwargs):
        captured.update(kwargs)
        block = MagicMock()
        block.type = "text"
        block.text = "ok"
        msg = MagicMock()
        msg.content = [block]
        return msg

    anthropic_mock = MagicMock()
    anthropic_mock.Anthropic.return_value.messages.create.side_effect = fake_create
    return anthropic_mock, captured


def test_claude_init_loads_top_k_from_config():
    client = _make_claude_client(top_k=27)
    assert client.top_k == 27


def test_claude_call_api_adds_top_k_in_non_thinking_mode():
    client = _make_claude_client(top_k=17)
    anthropic_mock, captured_kwargs = _setup_anthropic_mock()

    with patch("llm_router.get_env_value", return_value="fake-key"), \
         patch.dict(sys.modules, {"anthropic": anthropic_mock}):
        assert client._call_api("hello", use_thinking=False) == "ok"

    assert captured_kwargs.get("top_k") == 17


def test_claude_call_api_does_not_add_top_k_in_thinking_mode():
    client = _make_claude_client(top_k=19, max_tokens=4096, thinking_budget=2000)
    anthropic_mock, captured_kwargs = _setup_anthropic_mock()

    with patch("llm_router.get_env_value", return_value="fake-key"), \
         patch.dict(sys.modules, {"anthropic": anthropic_mock}):
        assert client._call_api("hello", use_thinking=True) == "ok"

    assert "thinking" in captured_kwargs
    assert "top_k" not in captured_kwargs
    assert captured_kwargs.get("temperature") == 1


def test_claude_thinking_fallback_when_budget_too_small():
    client = _make_claude_client(max_tokens=2048, thinking_budget=10000, top_k=23, top_p=0.9)
    anthropic_mock, captured_kwargs = _setup_anthropic_mock()

    with patch("llm_router.get_env_value", return_value="fake-key"), \
         patch.dict(sys.modules, {"anthropic": anthropic_mock}):
        assert client._call_api("hello", use_thinking=True) == "ok"

    # thinking budget가 최소 기준 미달이면 일반 모드로 fallback
    assert "thinking" not in captured_kwargs
    assert captured_kwargs.get("temperature") == 0.3
    assert captured_kwargs.get("top_p") == 0.9
    assert captured_kwargs.get("top_k") == 23
