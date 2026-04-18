from __future__ import annotations

import json
from typing import Any

from openai import OpenAI
from pydantic import BaseModel, ValidationError

from core.serialization import parse_json_model
from services.adapters.base import JsonModelAdapter
from services.tools.pubmed_tool import check_reference_genome, fetch_abstract, search_pubmed


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
        tools = [
            {"type": "web_search"},
            {"type": "code_interpreter"},
            {
                "type": "function",
                "name": "search_pubmed",
                "description": "Search PubMed for papers and return metadata such as PMID, title, authors, journal, year, and DOI.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query for PubMed."},
                        "max_results": {
                            "type": "integer",
                            "description": "Maximum number of results to return.",
                            "default": 10,
                            "minimum": 1,
                            "maximum": 100,
                        },
                    },
                    "required": ["query"],
                    "additionalProperties": False,
                },
            },
            {
                "type": "function",
                "name": "fetch_abstract",
                "description": "Fetch the abstract text for a PubMed record by PMID.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "pmid": {"type": "string", "description": "PubMed ID (PMID)."}
                    },
                    "required": ["pmid"],
                    "additionalProperties": False,
                },
            },
            {
                "type": "function",
                "name": "check_reference_genome",
                "description": "Check whether an organism has a reference/representative genome in NCBI Assembly and return assembly stats.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "organism": {
                            "type": "string",
                            "description": "Organism name, e.g., Escherichia coli.",
                        }
                    },
                    "required": ["organism"],
                    "additionalProperties": False,
                },
            },
        ]

        kwargs: dict[str, Any] = {
            "model": self.model,
            "instructions": system_content,
            "input": user_prompt,
            "tools": tools,
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

        response, text_rejected = self._create_response(kwargs)

        while True:
            function_calls = self._extract_function_calls(response)
            if not function_calls:
                break

            function_outputs: list[dict[str, str]] = []
            for function_call in function_calls:
                function_outputs.append(self._execute_function_call(function_call))

            follow_up_kwargs: dict[str, Any] = {
                "model": self.model,
                "previous_response_id": response.id,
                "input": function_outputs,
                "tools": tools,
            }
            if use_response_format and not text_rejected:
                follow_up_kwargs["text"] = kwargs.get("text")

            response, text_rejected = self._create_response(follow_up_kwargs)

        return response.output_text or ""

    def _create_response(self, payload: dict[str, Any]) -> tuple[Any, bool]:
        try:
            response = self.client.responses.create(**payload)
            return response, False
        except TypeError:
            # Some SDK/model combos may reject text.format — fall back cleanly.
            fallback_payload = dict(payload)
            fallback_payload.pop("text", None)
            response = self.client.responses.create(**fallback_payload)
            return response, True

    @staticmethod
    def _extract_function_calls(response: Any) -> list[Any]:
        calls: list[Any] = []
        for item in getattr(response, "output", []) or []:
            if getattr(item, "type", None) == "function_call":
                calls.append(item)
        return calls

    @staticmethod
    def _execute_function_call(function_call: Any) -> dict[str, str]:
        call_name = getattr(function_call, "name", "")
        raw_arguments = getattr(function_call, "arguments", "{}") or "{}"
        call_id = getattr(function_call, "call_id", "")

        try:
            arguments = json.loads(raw_arguments)
        except json.JSONDecodeError as exc:
            result: Any = {"error": f"Invalid JSON arguments: {exc}"}
        else:
            try:
                if call_name == "search_pubmed":
                    result = search_pubmed(
                        query=str(arguments["query"]),
                        max_results=int(arguments.get("max_results", 10)),
                    )
                elif call_name == "fetch_abstract":
                    result = fetch_abstract(pmid=str(arguments["pmid"]))
                elif call_name == "check_reference_genome":
                    result = check_reference_genome(organism=str(arguments["organism"]))
                else:
                    result = {"error": f"Unknown function: {call_name}"}
            except Exception as exc:  # noqa: BLE001 - tool errors should be returned to the model.
                result = {"error": str(exc), "function": call_name}

        if isinstance(result, str):
            output = result
        else:
            output = json.dumps(result, ensure_ascii=False)

        return {
            "type": "function_call_output",
            "call_id": call_id,
            "output": output,
        }

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
