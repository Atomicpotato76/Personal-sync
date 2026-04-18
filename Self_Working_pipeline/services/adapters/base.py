from __future__ import annotations

from abc import ABC, abstractmethod

from pydantic import BaseModel


class JsonModelAdapter(ABC):
    @abstractmethod
    def generate_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type[BaseModel],
    ) -> BaseModel:
        raise NotImplementedError
