#!/usr/bin/env python3
"""verifier.py -- Stage 4 coverage 검증(3단 계층 매칭).

Layer 1: substring
Layer 2: alias dictionary
Layer 3: semantic similarity (mem0 embedder 재활용, optional)
"""

from __future__ import annotations

import math
import socket
from pathlib import Path
from typing import Any

import requests
import yaml

from path_utils import resolve_path


def _chunk_text(text: str, chunk_size: int = 500) -> list[str]:
    clean = " ".join((text or "").split())
    if not clean:
        return []
    return [clean[i:i + chunk_size] for i in range(0, len(clean), chunk_size)]


def _cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def _load_topic_aliases(config: dict[str, Any]) -> dict[str, list[str]]:
    verifier_cfg = config.get("verifier", {}) if isinstance(config, dict) else {}
    alias_file = verifier_cfg.get("topic_aliases_file", "templates/topic_aliases.yaml")

    scripts_dir = Path(config.get("scripts_dir", Path(__file__).resolve().parent))
    alias_path = resolve_path(alias_file, scripts_dir)
    if not alias_path.exists():
        return {}

    with alias_path.open("r", encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle) or {}

    if not isinstance(loaded, dict):
        return {}

    normalized: dict[str, list[str]] = {}
    for topic, aliases in loaded.items():
        if isinstance(topic, str) and isinstance(aliases, list):
            normalized[topic] = [alias for alias in aliases if isinstance(alias, str)]
    return normalized


def _is_mem0_remote_chroma_healthy(config: dict[str, Any], timeout_sec: float = 0.4) -> bool:
    mem0_cfg = config.get("mem0", {}) if isinstance(config, dict) else {}
    vector_store = mem0_cfg.get("vector_store", {})
    if vector_store.get("mode", "local") != "remote":
        return True

    host = str(vector_store.get("host", "")).strip()
    port = int(vector_store.get("port", 8000))
    if not host:
        return False

    try:
        with socket.create_connection((host, port), timeout=timeout_sec):
            return True
    except OSError:
        return False


def _embedding_cosine(
    topic: str,
    corpus_chunks: list[str],
    embedder_cfg: dict[str, Any],
    timeout_sec: float = 6.0,
) -> tuple[float, str] | None:
    if not topic or not corpus_chunks:
        return None

    base_url = str(embedder_cfg.get("base_url", "")).strip()
    model = str(embedder_cfg.get("model", "")).strip()
    api_key = str(embedder_cfg.get("api_key", "")).strip() or "lm-studio"
    if not base_url or not model:
        return None

    endpoint = f"{base_url.rstrip('/')}/embeddings"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }

    try:
        topic_resp = requests.post(
            endpoint,
            json={"model": model, "input": topic},
            headers=headers,
            timeout=timeout_sec,
        )
        topic_resp.raise_for_status()
        topic_emb = topic_resp.json()["data"][0]["embedding"]

        chunk_resp = requests.post(
            endpoint,
            json={"model": model, "input": corpus_chunks},
            headers=headers,
            timeout=timeout_sec,
        )
        chunk_resp.raise_for_status()
        chunk_embeddings = [row["embedding"] for row in chunk_resp.json().get("data", [])]

        if not chunk_embeddings:
            return None

        best_score = -1.0
        best_chunk = ""
        for chunk, embedding in zip(corpus_chunks, chunk_embeddings):
            score = _cosine_similarity(topic_emb, embedding)
            if score > best_score:
                best_score = score
                best_chunk = chunk
        return best_score, best_chunk
    except Exception:
        return None


def check_coverage(
    note_text: str,
    synthesis: str,
    required_topics: list[str],
    config: dict[str, Any],
) -> dict[str, Any]:
    corpus = f"{note_text}\n\n{synthesis}".lower()
    verifier_cfg = config.get("verifier", {}) if isinstance(config, dict) else {}
    semantic_enabled = bool(verifier_cfg.get("semantic_matching", True))
    threshold = float(verifier_cfg.get("semantic_threshold", 0.75))
    aliases = _load_topic_aliases(config)

    if semantic_enabled and not _is_mem0_remote_chroma_healthy(config):
        semantic_enabled = False

    chunks = _chunk_text(f"{note_text}\n\n{synthesis}") if semantic_enabled else []
    embedder_cfg = config.get("mem0", {}).get("embedder", {}) if semantic_enabled else {}

    covered: list[dict[str, str]] = []
    missing: list[str] = []

    for topic in required_topics:
        topic_lower = topic.lower()

        if topic_lower in corpus:
            covered.append({"topic": topic, "method": "substring", "evidence": topic})
            continue

        topic_aliases = aliases.get(topic, [])
        matched_alias = next((alias for alias in topic_aliases if alias.lower() in corpus), None)
        if matched_alias:
            covered.append({
                "topic": topic,
                "method": f"alias:{matched_alias}",
                "evidence": matched_alias,
            })
            continue

        if semantic_enabled:
            semantic_result = _embedding_cosine(topic, chunks, embedder_cfg)
            if semantic_result is not None:
                score, best_chunk = semantic_result
                if score >= threshold:
                    covered.append({
                        "topic": topic,
                        "method": f"semantic:{score:.2f}",
                        "evidence": best_chunk[:200],
                    })
                    continue

        missing.append(topic)

    return {
        "coverage": {
            "pass": len(missing) == 0,
            "required_topics": required_topics,
            "covered": covered,
            "missing": missing,
            "threshold": threshold,
        }
    }
