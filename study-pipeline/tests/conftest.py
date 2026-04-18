"""conftest.py -- pytest fixtures for study-pipeline tests."""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# scripts/ 폴더를 import 경로에 추가
SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


@pytest.fixture
def tmp_pipeline(tmp_path):
    """최소 파이프라인 디렉토리 구조를 tmp_path 아래에 생성."""
    (tmp_path / "cache").mkdir()
    (tmp_path / "queue").mkdir()
    (tmp_path / "approved").mkdir()
    (tmp_path / "rejected").mkdir()
    (tmp_path / "notes").mkdir()
    return tmp_path


@pytest.fixture
def config(tmp_pipeline):
    """tmp 디렉토리를 가리키는 최소 config dict."""
    return {
        "vault_path": str(tmp_pipeline),
        "notes_dir": "notes",
        "pipeline_dir": str(tmp_pipeline),
        "scripts_dir": str(tmp_pipeline),
        "folder_mapping": {
            "유기화학": "organic_chem",
        },
        "subjects": {
            "organic_chem": {
                "folder": "유기화학",
            }
        },
        "mem0": {"enabled": False},
        "llm": {},
        "output": {"md": {"vault_inject": False}},
    }


@pytest.fixture
def mock_llm_router():
    """LLMRouter를 대체하는 MagicMock."""
    router = MagicMock()
    router.generate.return_value = "mock LLM response"
    router.generate_json.return_value = {}
    return router
