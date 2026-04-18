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
        schema_dict = response_model.model_json_schema()
        content = self._call(
            first_system,
            user_prompt,
            use_response_format=True,
            response_schema=schema_dict,
        )
        try:
            return parse_json_model(content, response_model)
        except (json.JSONDecodeError, ValidationError) as primary_error:
            reinforced_system = self._reinforce_schema_prompt(first_system, primary_error)
            retry_content = self._call(
                reinforced_system,
                user_prompt,
                use_response_format=True,
                response_schema=schema_dict,
            )
            try:
                return parse_json_model(retry_content, response_model)
            except (json.JSONDecodeError, ValidationError) as retry_error:
                raise RuntimeError(
                    "OpenAI adapter could not produce schema-valid JSON after retry. "
                    f"primary_error={type(primary_error).__name__}: {primary_error}. "
                    f"retry_error={type(retry_error).__name__}: {retry_error}. "
                    f"raw_preview={retry_content[:400]!r}"
                ) from retry_error

    def _call(
        self,
        system_content: str,
        user_prompt: str,
        *,
        use_response_format: bool,
        response_schema: dict | None = None,
    ) -> str:
        kwargs: dict = {
            "model": self.model,
            "instructions": system_content,
            "input": user_prompt,
            "tools": [{"type": "web_search"}],
        }
        if use_response_format:
            schema_name = "executor_output"
            kwargs["text"] = {
                "format": {
                    "type": "json_schema",
                    "name": schema_name,
                    "strict": False,
                    "schema": response_schema or {"type": "object"},
                }
            }
        try:
            response = self.client.responses.create(**kwargs)
        except TypeError:
            # Some SDK/model combos may reject text.format — fall back cleanly.
            kwargs.pop("text", None)
            response = self.client.responses.create(**kwargs)
        return response.output_text or ""

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


OpenAIAdapter = OpenAIJsonAdapter
