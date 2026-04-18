from __future__ import annotations

import json

from openai import OpenAI
from pydantic import BaseModel, ValidationError

from core.serialization import parse_json_model
from services.adapters.base import JsonModelAdapter


class OpenAIJsonAdapter(JsonModelAdapter):
    def __init__(self, *, api_key: str, model: str) -> None:
        self.client = OpenAI(api_key=api_key)
        self.model = model

    def generate_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type[BaseModel],
    ) -> BaseModel:
        schema = json.dumps(response_model.model_json_schema(), indent=2)
        first_system = (
            f"{system_prompt}\n"
            "Return only valid JSON that matches the schema.\n"
            f"JSON Schema:\n{schema}"
        )
        content = self._call(first_system, user_prompt, use_response_format=True)
        try:
            return parse_json_model(content, response_model)
        except (json.JSONDecodeError, ValidationError) as primary_error:
            reinforced_system = self._reinforce_schema_prompt(first_system, primary_error)
            retry_content = self._call(reinforced_system, user_prompt, use_response_format=True)
            try:
                return parse_json_model(retry_content, response_model)
            except (json.JSONDecodeError, ValidationError) as retry_error:
                raise RuntimeError(
                    "OpenAI adapter could not produce schema-valid JSON after retry. "
                    f"primary_error={type(primary_error).__name__}: {primary_error}. "
                    f"retry_error={type(retry_error).__name__}: {retry_error}. "
                    f"raw_preview={retry_content[:400]!r}"
                ) from retry_error

    def _call(self, system_content: str, user_prompt: str, *, use_response_format: bool) -> str:
        kwargs: dict = {
            "model": self.model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": system_content},
                {"role": "user", "content": user_prompt},
            ],
        }
        if use_response_format:
            # Forces the model into JSON mode; silently ignored by older models, which is fine
            # since our sanitizer handles fenced/prose output too.
            kwargs["response_format"] = {"type": "json_object"}
        try:
            response = self.client.chat.completions.create(**kwargs)
        except TypeError:
            # Some SDK/model combos reject response_format — fall back cleanly.
            kwargs.pop("response_format", None)
            response = self.client.chat.completions.create(**kwargs)
        return response.choices[0].message.content or ""

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
