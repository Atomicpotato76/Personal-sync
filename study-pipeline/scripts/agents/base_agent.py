#!/usr/bin/env python3
"""base_agent.py -- Ollama 기반 에이전트 기본 클래스."""

from __future__ import annotations

import json
import logging
from typing import Optional

logger = logging.getLogger("pipeline")


class BaseAgent:
    """Ollama를 사용하는 에이전트의 기본 클래스.

    각 에이전트는:
    - system 프롬프트를 갖는다
    - JSON 구조화된 출력을 강제한다
    - fallback으로 ChatGPT/Claude를 사용할 수 있다
    """

    agent_name: str = "base"
    system_prompt: str = "You are a helpful assistant."
    task_type: str = "classify"  # llm_router의 task_type

    def __init__(self, config: dict):
        self.config = config
        self._init_router()

    def _init_router(self):
        import sys
        from pathlib import Path
        scripts_dir = Path(__file__).resolve().parent.parent
        if str(scripts_dir) not in sys.path:
            sys.path.insert(0, str(scripts_dir))
        from llm_router import LLMRouter
        self.router = LLMRouter(self.config)

    def run(self, input_data: dict) -> Optional[dict]:
        """에이전트 실행. 서브클래스에서 오버라이드."""
        prompt = self.build_prompt(input_data)
        if not prompt:
            return None
        return self._call_llm_json(prompt)

    def build_prompt(self, input_data: dict) -> Optional[str]:
        """프롬프트 생성. 서브클래스에서 오버라이드."""
        raise NotImplementedError

    def _call_llm(self, prompt: str) -> Optional[str]:
        """LLM 호출 (텍스트 응답)."""
        return self.router.generate(
            prompt=prompt,
            task_type=self.task_type,
            system=self.system_prompt,
        )

    def _call_llm_json(self, prompt: str) -> Optional[dict]:
        """LLM 호출 (JSON 파싱)."""
        return self.router.generate_json(
            prompt=prompt,
            task_type=self.task_type,
            system=self.system_prompt,
        )
