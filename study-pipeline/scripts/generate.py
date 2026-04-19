#!/usr/bin/env python3
"""generate.py -- 노트 파일에서 퀴즈를 생성하여 queue/에 저장."""

from __future__ import annotations

import hashlib
import io
import json
import logging
import re
import sys
from datetime import datetime
from pathlib import Path

# Windows 콘솔 UTF-8 출력 보장
if sys.stdout.encoding != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
if sys.stdin.encoding != "utf-8":
    sys.stdin = io.TextIOWrapper(sys.stdin.buffer, encoding="utf-8", errors="replace")

import yaml

from path_utils import get_study_paths, apply_env_path_overrides

# ── 경로 설정 ──────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_PATH = SCRIPT_DIR / "config.yaml"
GENERATED_DIR_NAMES = {"퀴즈", "정리", "__pycache__", ".git", ".obsidian"}

# ── 로깅 ──────────────────────────────────────────────────
def setup_logging(log_dir: Path) -> logging.Logger:
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("pipeline")
    logger.setLevel(logging.DEBUG)
    log_path = (log_dir / "pipeline.log").resolve()
    for handler in logger.handlers:
        if isinstance(handler, logging.FileHandler) and Path(handler.baseFilename).resolve() == log_path:
            return logger
    fh = logging.FileHandler(log_dir / "pipeline.log", encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(fh)
    return logger

# ── config 로드 ────────────────────────────────────────────
def load_config() -> dict:
    if not CONFIG_PATH.exists():
        print(f"[ERROR] config.yaml을 찾을 수 없습니다: {CONFIG_PATH}")
        sys.exit(1)
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return apply_env_path_overrides(yaml.safe_load(f) or {})

# ── 텍스트 추출 ────────────────────────────────────────────
def extract_text(file_path: Path) -> str | None:
    """파일에서 텍스트를 추출한다. 실패 시 None 반환.

    PDF: pdfplumber 1순위 (PPT→PDF 한글 띄어쓰기 우수), pymupdf fallback.
    """
    suffix = file_path.suffix.lower()
    if suffix == ".md":
        return file_path.read_text(encoding="utf-8")
    elif suffix == ".pdf":
        text = None
        # 1순위: pdfplumber
        try:
            import pdfplumber
            with pdfplumber.open(str(file_path)) as pdf:
                text = "\n".join(
                    page.extract_text() or "" for page in pdf.pages
                )
        except Exception:
            pass

        # 2순위: pymupdf (fallback)
        if not text or len(text.strip()) < 100:
            try:
                import fitz
                doc = fitz.open(str(file_path))
                text = "\n".join(page.get_text() for page in doc)
                doc.close()
            except ImportError:
                print("[ERROR] pymupdf가 설치되지 않았습니다: pip install pymupdf")
                return None
            except Exception as e:
                print(f"[ERROR] PDF 읽기 실패 ({file_path.name}): {e}")
                return None

        if len(text.strip()) < 100:
            print(f"[WARN] 스캔 PDF로 추정, 텍스트 추출 불가: {file_path.name}")
            return None
        return text
    else:
        print(f"[ERROR] 지원하지 않는 파일 형식: {suffix}")
        return None

# ── 과목 감지 ──────────────────────────────────────────────
def detect_subject(file_path: Path, config: dict) -> str | None:
    """파일 경로에서 과목 키를 감지한다."""
    notes_base = get_study_paths(config).notes_base

    try:
        rel = file_path.resolve().relative_to(notes_base.resolve())
    except ValueError:
        print(f"[ERROR] 파일이 notes_dir 하위에 있지 않습니다: {file_path}")
        return None

    # 첫 번째 디렉토리가 과목 폴더
    subject_folder = rel.parts[0]
    folder_mapping: dict = config.get("folder_mapping", {})

    if subject_folder not in folder_mapping:
        print(f"[ERROR] folder_mapping에 없는 폴더: '{subject_folder}'")
        return None

    return folder_mapping[subject_folder]

# ── 생성물 ID ──────────────────────────────────────────────
def make_item_id(subject: str, note_name: str, content: str) -> str:
    h = hashlib.md5(content.encode("utf-8")).hexdigest()[:6]
    safe_name = re.sub(r"[^\w\-]", "_", note_name)
    return f"{subject}_{safe_name}_{h}"

# ── 프롬프트 빌드 ─────────────────────────────────────────
def load_negative_examples(config: dict, subject: str, max_n: int = 5) -> list[str]:
    """품질이 낮거나 retired된 문항 예시를 로드 (부정 예시로 주입)."""
    paths = get_study_paths(config)
    negatives: list[str] = []
    for search_dir in (paths.queue, paths.approved):
        if not search_dir.exists():
            continue
        for jf in search_dir.glob("*.json"):
            try:
                with open(jf, encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                continue
            if data.get("subject") != subject:
                continue
            for item in data.get("items", []):
                if item.get("retired"):
                    negatives.append(item.get("question", ""))
                elif (item.get("item_quality") or item.get("review", {}).get("item_quality") or 5) <= 2:
                    negatives.append(item.get("question", ""))
                if len(negatives) >= max_n:
                    return [q for q in negatives if q]
    return [q for q in negatives if q]


def build_prompt(template_path: Path, subject_cfg: dict, note_content: str, pretest_text: str = "", negative_examples: list[str] | None = None) -> str:
    template = template_path.read_text(encoding="utf-8")
    output_types = ", ".join(subject_cfg.get("output_types", []))
    items_per_note = subject_cfg.get("items_per_note", 2)
    prompt = template.format(
        items_per_note=items_per_note,
        output_types=output_types,
        note_content=note_content,
    )
    if pretest_text:
        prompt += (
            "\n\n---\n"
            "## 학습자 사전 지식 (pretest)\n\n"
            f"{pretest_text}\n\n"
            "위 사전 지식에서 언급되지 않은 개념은 pretest_gap=true로 표시하여 "
            "퀴즈 우선순위를 높여주세요.\n"
        )
    if negative_examples:
        neg_text = "\n".join(f"- {q}" for q in negative_examples)
        prompt += (
            "\n\n---\n"
            "## 피해야 할 문항 유형 (부정 예시)\n\n"
            "아래와 유사하거나 중복되는 문항은 생성하지 마세요:\n\n"
            f"{neg_text}\n"
        )
    return prompt

# ── API 호출 ──────────────────────────────────────────────
def call_api(prompt: str, config: dict) -> dict | None:
    """LLMRouter를 통해 JSON 응답을 생성한다."""
    from llm_router import LLMRouter

    router = LLMRouter(config)
    data = router.generate_json(prompt, task_type="quiz_generate")
    if data is None:
        print("[ERROR] LLM JSON 생성 실패")
    return data


def process_content(
    text: str,
    subject: str,
    source_note: str,
    config: dict,
    logger: logging.Logger,
    note_name: str | None = None,
    pretest_text: str = "",
) -> bool:
    """이미 확보한 텍스트를 기준으로 퀴즈를 생성한다."""
    subject_cfg = config["subjects"].get(subject)
    if subject_cfg is None:
        print(f"[ERROR] subjects에 '{subject}' 설정이 없습니다.")
        return False

    paths = get_study_paths(config)
    queue_dir = paths.queue

    template_path = SCRIPT_DIR / subject_cfg["template"]
    if not template_path.exists():
        print(f"[ERROR] 템플릿 없음: {template_path}")
        return False

    negative_examples = load_negative_examples(config, subject)
    prompt = build_prompt(template_path, subject_cfg, text, pretest_text=pretest_text, negative_examples=negative_examples or None)

    print("  → LLM 호출 중...")
    data = call_api(prompt, config)
    if data is None:
        logger.error(f"API 실패: {source_note}")
        return False

    items = data.get("items", [])
    if not items:
        print("  [WARN] 생성된 항목이 없습니다.")
        return False

    # 2.2: pretest_gap 마킹 — 사전 지식에서 언급되지 않은 concept_tags
    if pretest_text:
        pretest_lower = pretest_text.lower()
        for item in items:
            tags = item.get("concept_tags", [])
            gap = any(tag.lower() not in pretest_lower for tag in tags)
            item.setdefault("pretest_gap", gap)

    note_key = note_name or Path(source_note).stem
    item_id = make_item_id(subject, note_key, text)
    save_results(items, item_id, subject, source_note, queue_dir, config)

    gap_count = sum(1 for it in items if it.get("pretest_gap"))
    gap_note = f" (사전 지식 갭 {gap_count}개)" if pretest_text else ""
    print(f"  → 생성 완료: {len(items)}개 항목 → queue/{item_id}{gap_note}")
    logger.info(f"생성: {item_id} ({len(items)}개) from {source_note}")
    return True

# ── 결과 저장 ──────────────────────────────────────────────
def save_results(
    items: list[dict],
    item_id: str,
    subject: str,
    source_note: str,
    queue_dir: Path,
    config: dict | None = None,
) -> None:
    """JSON + Markdown 쌍으로 queue/에 저장. config가 있으면 vault 퀴즈 폴더에도 저장."""
    now = datetime.now().isoformat(timespec="seconds")

    # ── JSON 파일 ──
    json_data = {
        "id": item_id,
        "subject": subject,
        "source_note": source_note,
        "generated_at": now,
        "status": "queue",
        "items": [],
    }

    for i, item in enumerate(items):
        json_data["items"].append({
            "index": i,
            "type": item.get("type", ""),
            "question": item.get("question", ""),
            "expected_answer_keys": item.get("expected_answer_keys", []),
            "difficulty": item.get("difficulty", "medium"),
            "concept_tags": item.get("concept_tags", []),
            "source_section": item.get("source_section", ""),
            "pretest_gap": item.get("pretest_gap", False),
            "item_quality": None,
            "retired": False,
            "review": {
                "result": None,
                "memo": None,
                "reviewed_at": None,
                "item_quality": None,
            },
        })

    queue_dir.mkdir(parents=True, exist_ok=True)

    json_path = queue_dir / f"{item_id}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(json_data, f, ensure_ascii=False, indent=2)

    # ── Markdown 파일 ──
    tags_all = set()
    for item in items:
        tags_all.update(item.get("concept_tags", []))

    md_lines = [
        "---",
        f"id: {item_id}",
        f"subject: {subject}",
        "status: queue",
        f"tags: [{', '.join(sorted(tags_all))}]",
        f"generated_at: {now}",
        f"source_note: {source_note}",
        "---",
        "",
        f"# Quiz — {source_note}",
        "",
    ]

    for i, item in enumerate(items):
        q_num = i + 1
        md_lines.append(f"## Q{q_num}. [{item.get('difficulty', '?')}] {item.get('type', '')}")
        md_lines.append("")
        md_lines.append(item.get("question", ""))
        md_lines.append("")
        md_lines.append("### My Answer")
        md_lines.append("")
        md_lines.append("")
        md_lines.append("")
        md_lines.append("### Expected Answer Keys")
        md_lines.append("")
        for key in item.get("expected_answer_keys", []):
            md_lines.append(f"- {key}")
        md_lines.append("")
        md_lines.append(f"- [ ] correct")
        md_lines.append(f"- [ ] wrong")
        md_lines.append(f"- [ ] partial")
        md_lines.append("")
        tags = ", ".join(item.get("concept_tags", []))
        md_lines.append(f"> concept_tags: {tags}")
        md_lines.append("")
        md_lines.append("---")
        md_lines.append("")

    md_content = "\n".join(md_lines)

    md_path = queue_dir / f"{item_id}.md"
    md_path.write_text(md_content, encoding="utf-8")

    # ── vault 역주입: 과목/퀴즈/ 폴더에도 .md 저장 ──
    if config is not None:
        subject_cfg = config.get("subjects", {}).get(subject)
        if subject_cfg:
            paths = get_study_paths(config)
            folder_name = subject_cfg["folder"]
            quiz_dir = paths.notes_base / folder_name / "퀴즈"
            quiz_dir.mkdir(parents=True, exist_ok=True)
            vault_md_path = quiz_dir / f"{item_id}.md"
            vault_md_path.write_text(md_content, encoding="utf-8")


def _is_generated_file(file_path: Path) -> bool:
    return any(part in GENERATED_DIR_NAMES for part in file_path.parts)

# ── 파일 수집 (폴더 모드) ─────────────────────────────────
def collect_files(target: Path) -> list[Path]:
    """폴더일 경우 .md/.pdf를 재귀 수집, 파일이면 [파일] 반환."""
    if target.is_file():
        if _is_generated_file(target):
            return []
        return [target]
    files = []
    for ext in ("*.md", "*.pdf"):
        for path in target.rglob(ext):
            if _is_generated_file(path):
                continue
            files.append(path)
    return sorted(files)

# ── 단일 파일 처리 ────────────────────────────────────────
def process_file(file_path: Path, config: dict, logger: logging.Logger) -> bool:
    """단일 파일을 처리한다. 성공 시 True."""
    if _is_generated_file(file_path):
        print(f"[WARN] Skip generated file: {file_path}")
        return False

    # 과목 감지
    subject = detect_subject(file_path, config)
    if subject is None:
        return False

    print(f"  과목: {subject} | 파일: {file_path.name} | 타입: {file_path.suffix}")

    # 텍스트 추출
    text = extract_text(file_path)
    if text is None:
        return False

    return process_content(
        text,
        subject,
        file_path.name,
        config,
        logger,
        note_name=file_path.stem,
    )

# ── main ──────────────────────────────────────────────────
def main() -> None:
    if len(sys.argv) < 2:
        print("사용법: python generate.py <노트파일 또는 폴더 경로>")
        print()
        print("예시:")
        print('  python generate.py "../../3학년 1학기/중간고사/유기화학/필기/ch04_alkenes.md"')
        print('  python generate.py "../../3학년 1학기/중간고사/유기화학/pdf/ch04_lecture.pdf"')
        print('  python generate.py "../../3학년 1학기/중간고사/유기화학/"')
        sys.exit(0)

    config = load_config()
    paths = get_study_paths(config)
    logger = setup_logging(paths.logs)

    target = Path(sys.argv[1]).resolve()
    if not target.exists():
        print(f"[ERROR] 경로를 찾을 수 없습니다: {target}")
        sys.exit(1)

    # queue 디렉토리 확인
    queue_dir = paths.queue
    queue_dir.mkdir(parents=True, exist_ok=True)

    files = collect_files(target)
    if not files:
        print("[ERROR] 처리할 .md/.pdf 파일이 없습니다.")
        sys.exit(1)

    # 폴더 모드: 파일 목록 출력 + 확인
    if target.is_dir():
        print(f"폴더 모드: {len(files)}개 파일 발견")
        for f in files:
            print(f"  - {f.name}")
        answer = input("\n처리를 시작하시겠습니까? (y/n): ").strip().lower()
        if answer != "y":
            print("취소되었습니다.")
            sys.exit(0)

    print()
    success = 0
    fail = 0
    for file_path in files:
        print(f"[처리 중] {file_path.name}")
        if process_file(file_path, config, logger):
            success += 1
        else:
            fail += 1
        print()

    print(f"완료: 성공 {success}개, 실패 {fail}개")


if __name__ == "__main__":
    main()
