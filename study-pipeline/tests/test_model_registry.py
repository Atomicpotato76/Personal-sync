"""model_registry.py Claude fallback/파싱 회귀 테스트."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from model_registry import _fallback_anthropic_models, _parse_claude_model


def test_parse_claude_opus_4_7_short_id():
    info = _parse_claude_model("claude-opus-4-7")
    assert info is not None
    assert info.id == "claude-opus-4-7"
    assert info.variant == "opus"
    assert info.family == "claude-4.7"


def test_parse_claude_sonnet_4_6_short_id():
    info = _parse_claude_model("claude-sonnet-4-6")
    assert info is not None
    assert info.id == "claude-sonnet-4-6"
    assert info.variant == "sonnet"
    assert info.family == "claude-4.6"


def test_fallback_includes_opus_4_7():
    models = _fallback_anthropic_models()
    ids = [m.id for m in models]
    assert "claude-opus-4-7" in ids
