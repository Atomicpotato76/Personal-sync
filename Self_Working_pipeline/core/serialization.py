from __future__ import annotations

import json
import re
from typing import TypeVar

from pydantic import BaseModel

ModelT = TypeVar("ModelT", bound=BaseModel)

_FENCED_JSON_RE = re.compile(r"```(?:json)?\s*(\{[\s\S]*?\}|\[[\s\S]*?\])\s*```", re.DOTALL)


def sanitize_json_block(raw_text: str) -> str:
    text = raw_text.strip()

    # Case 1: starts with a fence — strip the fence wrapper.
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        return "\n".join(lines).strip()

    # Case 2: fence appears later (e.g. "Here is the JSON: ```json {...} ```").
    fenced_match = _FENCED_JSON_RE.search(text)
    if fenced_match:
        return fenced_match.group(1).strip()

    # Case 3: raw JSON with leading/trailing prose — slice to the outermost braces/brackets.
    first_obj = text.find("{")
    first_arr = text.find("[")
    candidates = [idx for idx in (first_obj, first_arr) if idx != -1]
    if candidates:
        start = min(candidates)
        end_obj = text.rfind("}")
        end_arr = text.rfind("]")
        end = max(end_obj, end_arr)
        if end > start:
            return text[start : end + 1].strip()

    return text


def parse_json_model(raw_text: str, model: type[ModelT]) -> ModelT:
    payload = json.loads(sanitize_json_block(raw_text))
    return model.model_validate(payload)
