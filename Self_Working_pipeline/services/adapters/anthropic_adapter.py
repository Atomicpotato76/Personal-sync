from __future__ import annotations

import json

from anthropic import Anthropic
from pydantic import BaseModel, ValidationError

from core.serialization import parse_json_model
from services.adapters.base import JsonModelAdapter


class AnthropicJsonAdapter(JsonModelAdapter):
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        thinking_enabled: bool = False,
        thinking_type: str = "adaptive",
        thinking_budget_tokens: int = 0,
        max_output_tokens: int = 8000,
    ) -> None:
        self.client = Anthropic(api_key=api_key)
        self.model = model
        self.thinking_enabled = thinking_enabled
        self.thinking_type = thinking_type
        self.thinking_budget_tokens = thinking_budget_tokens
        self.max_output_tokens = max_output_tokens

    def _build_request_kwargs(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        schema: str,
        thinking_enabled: bool,
        max_tokens: int,
    ) -> dict:
        request_kwargs = {
            "model": self.model,
            "max_tokens": max_tokens,
            "system": (
                f"{system_prompt}\n"
                "Return only valid JSON that matches the schema.\n"
                f"JSON Schema:\n{schema}"
            ),
            "messages": [{"role": "user", "content": user_prompt}],
        }
        if thinking_enabled:
            thinking = {"type": self.thinking_type}
            if self.thinking_type != "adaptive":
                thinking["budget_tokens"] = self.thinking_budget_tokens
            request_kwargs["thinking"] = thinking
        return request_kwargs

    def generate_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type[BaseModel],
    ) -> BaseModel:
        schema = json.dumps(response_model.model_json_schema(), indent=2)
        request_kwargs = self._build_request_kwargs(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            schema=schema,
            thinking_enabled=self.thinking_enabled,
            max_tokens=self.max_output_tokens,
        )
        message = self.client.messages.create(**request_kwargs)
        text_parts = [block.text for block in message.content if getattr(block, "type", "") == "text"]
        raw_text = "\n".join(text_parts)
        try:
            return parse_json_model(raw_text, response_model)
        except (json.JSONDecodeError, ValidationError) as primary_error:
            stop_reason = getattr(message, "stop_reason", None)
            # Retry once with thinking off and a bigger output budget.
            # Triggers:
            #   - max_tokens truncation
            #   - schema mismatch (ValidationError): model returned unwrapped payload
            #   - bad JSON that survived the sanitizer
            retry_kwargs = self._build_request_kwargs(
                system_prompt=self._reinforce_schema_prompt(system_prompt, primary_error),
                user_prompt=user_prompt,
                schema=schema,
                thinking_enabled=False,
                max_tokens=max(self.max_output_tokens, 12000),
            )
            try:
                retry_message = self.client.messages.create(**retry_kwargs)
            except Exception:
                raise primary_error
            retry_text_parts = [
                block.text for block in retry_message.content if getattr(block, "type", "") == "text"
            ]
            retry_raw = "\n".join(retry_text_parts)
            try:
                return parse_json_model(retry_raw, response_model)
            except (json.JSONDecodeError, ValidationError) as retry_error:
                raise RuntimeError(
                    "Anthropic adapter could not produce schema-valid JSON after retry. "
                    f"stop_reason={stop_reason!r}. "
                    f"primary_error={type(primary_error).__name__}: {primary_error}. "
                    f"retry_error={type(retry_error).__name__}: {retry_error}. "
                    f"raw_preview={retry_raw[:400]!r}"
                ) from retry_error

    @staticmethod
    def _reinforce_schema_prompt(system_prompt: str, error: Exception) -> str:
        hint = (
            "Previous attempt failed schema validation. "
            "Return ONLY a single JSON object that conforms to the schema above. "
            "Do not include prose, markdown fences, or extra top-level keys. "
            "If the schema has an envelope wrapper (e.g. {\"report\": {...}} or {\"result\": {...}}), "
            "you MUST include that wrapper."
        )
        return f"{system_prompt}\n\n{hint}\nLast error: {type(error).__name__}: {str(error)[:240]}"
