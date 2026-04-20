#!/usr/bin/env python3
"""synthesize.py -- v3: 3-tier LLM + 에이전트 + 논문 + mem0 통합 학습 파이프라인.

10단계:
  [1/10] 소스 수집 (기존 + 논문)
  [2/10] marker-pdf 변환 (고급 PDF 파싱)
  [3/10] 에이전트: 분류 + 갭 감지 (Ollama)
  [4/10] 에이전트: 교차과목 연결 (Ollama)
  [5/10] 논문 풀텍스트 수집 + 요약 (Semantic Scholar → ChatGPT)
  [6/10] 갭 보충 콘텐츠 생성 (ChatGPT)
  [7/10] 학습 계획 생성 (ChatGPT + mem0)
  [8/10] 최종 종합 정리노트 (Claude)
  [9/10] 퀴즈 생성 (Claude)
  [10/10] 저장 (MD + PDF + mem0 업데이트)
"""

from __future__ import annotations

import io
import json
import logging
import re
import sys
from datetime import datetime
from pathlib import Path

if sys.stdout.encoding != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import yaml

import discord_notifier

from path_utils import get_study_paths, get_subject_dir, apply_env_path_overrides

SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_PATH = SCRIPT_DIR / "config.yaml"
TOTAL_STEPS = 10
PROVENANCE_EMPHASIS_RE = re.compile(r"\[(S|D|E)\]\s*(★{1,3})\s*$")
HALLUCINATED_STATE_RE = re.compile(
    r"(?im)^\s*[-*]?\s*(?:mastery|학습\s*진행률|복습\s*일정|next[_\s-]?review|study\s*progress)\s*[:=].*$"
)


def load_config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return apply_env_path_overrides(yaml.safe_load(f) or {})


def setup_logging(log_dir: Path) -> logging.Logger:
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("pipeline")
    if not logger.handlers:
        logger.setLevel(logging.DEBUG)
        fh = logging.FileHandler(log_dir / "pipeline.log", encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
        logger.addHandler(fh)
    return logger


def detect_subject(file_path: Path, config: dict) -> str | None:
    """파일 경로에서 과목 키 감지."""
    notes_base = get_study_paths(config).notes_base
    try:
        rel = file_path.resolve().relative_to(notes_base.resolve())
    except ValueError:
        return None
    folder_mapping = config.get("folder_mapping", {})
    subject_folder = rel.parts[0]
    return folder_mapping.get(subject_folder)


def log_step(logger: logging.Logger, step_no: int, title: str) -> None:
    message = f"[{step_no}/{TOTAL_STEPS}] {title}"
    print(f"  {message}")
    logger.info(message)


def log_detail(logger: logging.Logger, message: str) -> None:
    print(f"    {message}")
    logger.info(message)


def log_warn(logger: logging.Logger, message: str) -> None:
    print(f"    [WARN] {message}")
    logger.warning(message)


def log_error(logger: logging.Logger, message: str) -> None:
    print(f"  [ERROR] {message}")
    logger.error(message)


def truncate_text(text: str, max_chars: int = 15000) -> str:
    """텍스트를 최대 길이로 잘라냄 (토큰 절약)."""
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n\n... (이하 생략, 총 {}자 중 {}자 표시)".format(len(text), max_chars)


# ══════════════════════════════════════════════════════════════
# Step 1: 소스 수집
# ══════════════════════════════════════════════════════════════

def collect_sources(note_path: Path, subject: str, config: dict) -> dict:
    """3종 소스를 수집."""
    from source_extractor import SourceAggregator
    agg = SourceAggregator(config, subject)
    return agg.aggregate_for_note(note_path)


# ══════════════════════════════════════════════════════════════
# Step 2: LLM 종합 (2-pass 또는 1-pass)
# ══════════════════════════════════════════════════════════════

def synthesize_notes(sources: dict, subject: str, config: dict) -> str | None:
    """3종 소스를 LLM에 투입하여 종합 정리노트 생성."""
    from llm_router import LLMRouter

    router = LLMRouter(config)
    subject_cfg = config["subjects"][subject]

    # 프롬프트 템플릿 로드
    template_name = subject_cfg.get("synthesis_template", "templates/synthesis_prompt.txt")
    template_path = SCRIPT_DIR / template_name
    if not template_path.exists():
        print(f"[ERROR] 종합 프롬프트 없음: {template_path}")
        return None

    template = template_path.read_text(encoding="utf-8")

    note_content = sources["note_text"]
    textbook_content = truncate_text(sources.get("textbook_text") or "(교재 텍스트 없음)", 12000)
    slides_content = truncate_text(sources.get("slides_text") or "(강의자료 없음)", 8000)

    prompt = template.format(
        note_content=note_content,
        textbook_content=textbook_content,
        slides_content=slides_content,
    )

    # 2-pass: LM Studio(초안) → Claude(심화)
    # LM Studio 사용 가능 시 2-pass, 아니면 Claude 1-pass
    if router._check_lmstudio():
        print("  → Pass 1: LM Studio 초안 생성 중...")
        draft = router.generate(prompt, task_type="draft")
        if draft:
            print(f"  → LM Studio 초안: {len(draft)}자")
            # Pass 2: Claude 심화
            deep_prompt = (
                "다음은 대학 수업의 종합 정리노트 초안입니다. "
                "이 초안을 기반으로:\n"
                "1. 메커니즘 설명을 더 상세하게 (전자 이동 수준)\n"
                "2. 기초 배경지식 보충\n"
                "3. 시험 포인트 강조\n"
                "4. 영문 화학/과학 용어 우선 적용\n"
                "5. 교수님 코멘트 보존\n"
                "으로 심화 보강해주세요. Markdown 형식 유���.\n\n"
                f"--- 초안 ---\n{draft}"
            )
            print("  → Pass 2: Claude 심화 보강 중...")
            result = router.generate(deep_prompt, task_type="synthesis_deep")
            if result:
                return result
            print("  [WARN] Claude 심화 실패, 초안 사용")
            return draft
        print("  [WARN] LM Studio 실패, Claude 1-pass로 전환")

    # Claude 1-pass
    print("  → Claude 1-pass 종합 생성 중...")
    return router.generate(prompt, task_type="synthesis_deep")


# ══════════════════════════════════════════════════════════════
# Step 3: PubMed 연동
# ══════════════════════════════════════════════════════════════

def remove_unverified_user_state(content: str) -> str:
    """LLM이 생성한 근거 없는 사용자 상태 필드를 제거."""
    cleaned_lines: list[str] = []
    for line in content.splitlines():
        if HALLUCINATED_STATE_RE.match(line):
            continue
        cleaned_lines.append(line)
    return "\n".join(cleaned_lines).strip()


def enforce_provenance_and_emphasis(content: str, config: dict) -> str:
    """주요 문단 말미에 provenance/중요도 태그를 강제."""
    output_cfg = config.get("output", {})
    defaults = output_cfg.get("emphasis_levels", {})
    default_level = str(defaults.get("default", "★★")).strip()
    if default_level not in {"★", "★★", "★★★"}:
        default_level = "★★"

    blocks = content.split("\n\n")
    updated: list[str] = []
    for block in blocks:
        stripped = block.strip()
        if not stripped:
            continue

        first_line = stripped.splitlines()[0].strip()
        structural_prefixes = ("#", "-", "*", ">", "|", "```", "---")
        if first_line.startswith(structural_prefixes):
            updated.append(stripped)
            continue

        if not PROVENANCE_EMPHASIS_RE.search(stripped):
            stripped = f"{stripped} [S] {default_level}"
        updated.append(stripped)

    return "\n\n".join(updated).strip()


def split_smoke_mode_sections(content: str) -> tuple[str, str]:
    """smoke_mode용으로 [S]/[D]/[E]를 분리하여 메인/보충 노트를 생성."""
    source_blocks: list[str] = []
    derived_blocks: list[str] = []
    enrichment_blocks: list[str] = []

    for block in content.split("\n\n"):
        stripped = block.strip()
        if not stripped:
            continue

        match = PROVENANCE_EMPHASIS_RE.search(stripped)
        if not match:
            source_blocks.append(stripped)
            continue

        label = match.group(1)
        if label == "S":
            source_blocks.append(stripped)
        elif label == "D":
            derived_blocks.append(stripped)
        else:
            enrichment_blocks.append(stripped)

    main_sections: list[str] = ["\n\n".join(source_blocks).strip()] if source_blocks else []
    if derived_blocks:
        main_sections.append("## 심화 해설\n\n" + "\n\n".join(derived_blocks).strip())

    enrichment_content = ""
    if enrichment_blocks:
        enrichment_content = "## Enrichment\n\n" + "\n\n".join(enrichment_blocks).strip()

    return "\n\n".join(section for section in main_sections if section).strip(), enrichment_content


def add_pubmed_section(synthesis_md: str, subject: str, note_text: str, config: dict) -> str:
    """PubMed 관련 논문 overview를 정리노트에 추가."""
    pubmed_cfg = config.get("pubmed", {})
    if not pubmed_cfg.get("enabled", False):
        return synthesis_md

    try:
        from pubmed_client import search_and_summarize
        pubmed_section = search_and_summarize(subject, note_text, config)
        if pubmed_section:
            synthesis_md += f"\n\n---\n\n{pubmed_section}"
    except ImportError:
        print("  [WARN] pubmed_client.py 미구현, PubMed 섹션 건너뜀")
    except Exception as e:
        print(f"  [WARN] PubMed 연동 오류: {e}")

    return synthesis_md


# ══════════════════════════════════════════════════════════════
# Step 3.5: 개념 보충 설명 (Claude API)
# ══════════════════════════════════════════════════════════════

def add_supplementary_explanations(synthesis_md: str, config: dict) -> str:
    """정리노트에서 심화 보충이 필요한 개념을 식별하고 Claude로 설명 추가."""
    from llm_router import LLMRouter
    router = LLMRouter(config)

    prompt = (
        "다음 학습 정리노트를 읽고, 학생이 이해하기 어려울 수 있는 핵심 개념 2-3개를 골라서 "
        "각각에 대한 보충 설명을 작성해주세요.\n\n"
        "규칙:\n"
        "- 각 보충 설명은 '💡 보충:' 으로 시작\n"
        "- 한국어로 작성, 영문 과학 용어는 그대로 유지\n"
        "- 각 설명은 3-5문장으로 간결하게\n"
        "- 비유나 일상 예시를 활용하여 직관적으로 설명\n"
        "- 정리노트에 이미 있는 내용을 반복하지 말고, 추가 맥락만 제공\n"
        "- 출력은 Markdown 형식, 전체를 '## 개념 보충 설명' 섹션으로 감싸줘\n\n"
        f"--- 정리노트 ---\n{synthesis_md}"
    )

    print("  → 개념 보충 설명 생성 중 (Claude)...")
    supplement = router.generate(prompt, task_type="synthesis_deep")
    if supplement:
        synthesis_md += f"\n\n---\n\n{supplement}"
        print(f"    보충 설명: {len(supplement)}자 추가")
    else:
        print("  [WARN] 보충 설명 생성 실패")

    return synthesis_md


# ══════════════════════════════════════════════════════════════
# Step 4: 출력 저장
# ══════════════════════════════════════════════════════════════

def save_synthesis_md(
    content: str,
    subject: str,
    note_name: str,
    config: dict,
) -> Path:
    """종합 정리노트를 MD로 저장."""
    paths = get_study_paths(config)
    subject_cfg = config["subjects"][subject]
    now = datetime.now()

    # frontmatter
    md = (
        "---\n"
        f"type: synthesis\n"
        f"subject: {subject}\n"
        f"source_note: {note_name}\n"
        f"generated_at: {now.isoformat(timespec='seconds')}\n"
        "---\n\n"
        f"{content}"
    )

    # output/md/ 에 저장
    md_dir = paths.output_md
    md_dir.mkdir(parents=True, exist_ok=True)
    safe_name = re.sub(r"[^\w\-]", "_", note_name.replace(".md", ""))
    filename = f"{subject}_{safe_name}.md"
    md_path = md_dir / filename
    md_path.write_text(md, encoding="utf-8")

    # vault 역주입: {과목}/정리/ 폴더
    if config.get("output", {}).get("md", {}).get("vault_inject", True):
        folder_name = subject_cfg["folder"]
        vault_dir = paths.notes_base / folder_name / "정리"
        vault_dir.mkdir(parents=True, exist_ok=True)
        vault_path = vault_dir / filename
        vault_path.write_text(md, encoding="utf-8")
        print(f"  → vault 저장: {folder_name}/정리/{filename}")

    return md_path


def save_enrichment_md(content: str, subject: str, note_name: str, config: dict) -> Path:
    """[E] 전용 보충 노트를 별도 파일로 저장."""
    paths = get_study_paths(config)
    safe_name = re.sub(r"[^\w\-]", "_", note_name.replace(".md", ""))
    filename = f"{subject}_{safe_name}_enrichment.md"
    output_path = paths.output_md / filename
    output_path.parent.mkdir(parents=True, exist_ok=True)

    now = datetime.now()
    md = (
        "---\n"
        "type: enrichment\n"
        f"subject: {subject}\n"
        f"source_note: {note_name}\n"
        f"generated_at: {now.isoformat(timespec='seconds')}\n"
        "---\n\n"
        f"{content}"
    )
    output_path.write_text(md, encoding="utf-8")
    return output_path


def save_synthesis_pdf(
    md_content: str,
    subject: str,
    note_name: str,
    images: list[dict],
    config: dict,
) -> Path | None:
    """종합 정리노트를 PDF로 저장."""
    try:
        from pdf_builder import build_pdf
        paths = get_study_paths(config)
        pdf_dir = paths.output_pdf
        pdf_dir.mkdir(parents=True, exist_ok=True)
        safe_name = re.sub(r"[^\w\-]", "_", note_name.replace(".md", ""))
        filename = f"{subject}_{safe_name}.pdf"
        pdf_path = pdf_dir / filename
        build_pdf(md_content, pdf_path, config, images=images)
        return pdf_path
    except ImportError:
        print("  [WARN] pdf_builder.py 미구현, PDF 생성 건너뜀")
        return None
    except Exception as e:
        print(f"  [WARN] PDF 생성 오류: {e}")
        return None


def collect_sources_for_note(note_path: Path, subject: str, config: dict, logger: logging.Logger) -> dict:
    """노트 기준 3종 소스를 수집하고 marker 상태를 확인."""
    sources = collect_sources(note_path, subject, config)
    log_detail(logger, f"필기: {len(sources['note_text'])}자")
    log_detail(logger, f"교재: {len(sources['textbook_text'] or '')}자")
    log_detail(logger, f"강의자료: {len(sources['slides_text'] or '')}자")
    log_detail(
        logger,
        f"이미지: 교재 {len(sources['textbook_images'])}개 + 슬라이드 {len(sources['slides_images'])}개",
    )

    try:
        from marker_reader import _is_marker_available

        if _is_marker_available():
            log_detail(logger, "marker-pdf 사용 가능 → 고품질 변환 활성")
        else:
            log_warn(logger, "marker-pdf 미설치 → 기존 pdfplumber/pymupdf 사용")
    except Exception:
        log_warn(logger, "marker 확인 건너뜀")

    return sources


def run_agents(sources: dict, subject: str, config: dict, logger: logging.Logger) -> dict:
    """분류와 갭 감지를 수행."""
    gaps: list[dict] = []
    classification = None

    try:
        import sys as _sys

        if str(SCRIPT_DIR) not in _sys.path:
            _sys.path.insert(0, str(SCRIPT_DIR))
        from agents.classifier_agent import ClassifierAgent
        from agents.gap_detector import GapDetector

        classifier = ClassifierAgent(config)
        classification = classifier.classify(sources["note_text"], subject)
        if classification:
            sections = classification.get("sections", [])
            log_detail(
                logger,
                f"분류: {len(sections)}개 섹션, 전체 난이도: {classification.get('overall_difficulty', '?')}",
            )

        detector = GapDetector(config)
        gap_result = detector.detect_gaps(
            sources["note_text"],
            subject,
            sources.get("textbook_text") or "",
            sources.get("slides_text") or "",
        )
        if gap_result:
            gaps = gap_result.get("gaps", [])
            score = gap_result.get("coverage_score", "?")
            log_detail(logger, f"갭 감지: {len(gaps)}개 (커버리지: {score})")
    except Exception as e:
        log_warn(logger, f"에이전트 실행 오류: {e}")

    return {
        "classification": classification,
        "gaps": gaps,
    }


def run_cross_subject_analysis(
    sources: dict, subject: str, config: dict, logger: logging.Logger
) -> list[dict]:
    """다른 과목과의 연결을 분석."""
    cross_connections: list[dict] = []
    try:
        from agents.cross_subject import CrossSubjectAgent, get_subject_keywords

        cross_agent = CrossSubjectAgent(config)
        other_subjects = get_subject_keywords(config)
        other_subjects.pop(subject, None)
        if other_subjects:
            cross_result = cross_agent.find_connections(
                sources["note_text"], subject, other_subjects
            )
            if cross_result:
                cross_connections = cross_result.get("connections", [])
                log_detail(logger, f"교차연결: {len(cross_connections)}개 발견")
                # 2.3: 검토 대기 큐에 저장
                if cross_connections:
                    try:
                        from memory_manager import MemoryManager
                        mem = MemoryManager(config)
                        note_name = sources.get("note_name", "unknown")
                        for conn in cross_connections:
                            conn.setdefault("current_subject", subject)
                        mem.add_pending_links(cross_connections, note_name)
                        log_detail(logger, f"교차연결 {len(cross_connections)}개 검토 대기열에 추가")
                    except Exception as link_err:
                        log_warn(logger, f"교차연결 저장 실패: {link_err}")
        else:
            log_detail(logger, "다른 과목 없음, 건너뜀")
    except Exception as e:
        log_warn(logger, f"교차과목 오류: {e}")

    return cross_connections


def _paper_relevance(note_text: str, abstract: str) -> float:
    """노트 내용과 논문 abstract의 TF cosine 유사도 계산."""
    import re
    from collections import Counter
    from math import sqrt

    def _tf(text: str) -> dict:
        words = re.findall(r'[가-힣a-zA-Z]{2,}', text.lower())
        cnt = Counter(words)
        total = max(sum(cnt.values()), 1)
        return {w: c / total for w, c in cnt.most_common(300)}

    a = _tf(note_text)
    b = _tf(abstract)
    common = set(a) & set(b)
    if not common:
        return 0.0
    dot = sum(a[w] * b[w] for w in common)
    mag = (sqrt(sum(v * v for v in a.values())) or 1.0) * (sqrt(sum(v * v for v in b.values())) or 1.0)
    return dot / mag


def run_paper_enrichment(sources: dict, subject: str, config: dict, logger: logging.Logger) -> list[dict]:
    """관련 논문을 수집하고 relevance 필터를 적용해 프롬프트에 쓸 논문만 반환."""
    papers: list[dict] = []
    try:
        from paper_fetcher import fetch_papers_for_note

        raw_papers = fetch_papers_for_note(sources["note_text"], subject, config)

        # 3.2: relevance 필터 — 유사도 0.05 미만 제외
        note_text = sources.get("note_text", "")
        relevance_threshold = config.get("papers", {}).get("relevance_threshold", 0.05)
        filtered = []
        for p in raw_papers:
            abstract = p.get("abstract") or ""
            sim = _paper_relevance(note_text, abstract) if abstract else 0.0
            p["_relevance"] = round(sim, 4)
            if sim >= relevance_threshold:
                filtered.append(p)
            else:
                log_detail(logger, f"논문 제외 (유사도 {sim:.3f} < {relevance_threshold}): {p['title'][:40]}")

        papers = filtered
        if papers:
            log_detail(logger, f"논문 수집: {len(raw_papers)}편 → 필터 후 {len(papers)}편")
            for p in papers[:3]:
                has_ft = "풀텍스트" if p.get("full_text") else "abstract만"
                log_detail(
                    logger,
                    f"[유사도 {p['_relevance']:.3f}, {p.get('citation_count', 0)} cites, {has_ft}] {p['title'][:50]}",
                )
        elif raw_papers:
            log_detail(logger, f"논문 수집: {len(raw_papers)}편이지만 relevance 기준 미달로 전부 제외됨")
    except Exception as e:
        log_warn(logger, f"논문 수집 오류: {e}")
    return papers


def build_synthesis(sources: dict, subject: str, config: dict, logger: logging.Logger) -> str | None:
    """기본 종합 정리노트를 생성하고 PubMed 섹션을 보강."""
    synthesis = synthesize_notes(sources, subject, config)
    if synthesis is None:
        return None

    log_detail(logger, f"정리노트: {len(synthesis)}자")
    return add_pubmed_section(synthesis, subject, sources["note_text"], config)


def append_analysis_sections(
    synthesis: str,
    sources: dict,
    subject: str,
    agent_results: dict,
    papers: list[dict],
    config: dict,
    logger: logging.Logger,
) -> str:
    """갭 보충, 교차과목 분석, 논문 관련성 분석을 추가."""
    try:
        from analyst import StudyAnalyst

        analyst = StudyAnalyst(config)

        gaps = agent_results.get("gaps", [])
        if gaps:
            gap_supplement = analyst.generate_gap_supplements(gaps, sources["note_text"], subject)
            if gap_supplement:
                synthesis += f"\n\n---\n\n{gap_supplement}"

        cross_connections = agent_results.get("cross_connections", [])
        if cross_connections:
            cross_section = analyst.analyze_cross_subject(cross_connections, subject)
            if cross_section:
                synthesis += f"\n\n---\n\n{cross_section}"

        if papers:
            paper_analysis = analyst.analyze_paper_relevance(papers, sources["note_text"], subject)
            if paper_analysis:
                synthesis += f"\n\n---\n\n{paper_analysis}"
    except Exception as e:
        log_warn(logger, f"ChatGPT 분석 오류: {e}")
        synthesis = add_supplementary_explanations(synthesis, config)

    return synthesis


def append_study_plan_section(
    synthesis: str,
    subject: str,
    config: dict,
    logger: logging.Logger,
) -> str:
    """약점과 복습 시점 기반 학습 계획을 추가."""
    try:
        from analyst import StudyAnalyst
        from memory_manager import MemoryManager
        from mastery_tracker import get_mastery_lines

        mem = MemoryManager(config)
        analyst = StudyAnalyst(config)

        weak = mem.get_weak_concepts(subject)
        due = mem.get_due_reviews(subject)
        stats = mem.get_study_stats(subject)
        mastery_lines = get_mastery_lines(config, subject, limit=12)
        mastery_text = "\n".join(mastery_lines)

        if not mastery_lines:
            synthesis += (
                "\n\n---\n\n"
                "## 학습 계획\n\n"
                "- ℹ️ 아직 퀴즈 기록 없음: mastery 실데이터가 비어 있습니다.\n"
                "- 현재 단계에서는 임의 mastery %/등급을 생성하지 않습니다.\n"
                "- 먼저 퀴즈를 1회 이상 풀고 채점하면 다음 실행부터 🔴/🟡/🟢 mastery 기반 계획이 생성됩니다.\n"
            )
            return synthesis

        if weak or due:
            plan = analyst.generate_study_plan(subject, weak, due, stats, mastery_text)
            if plan:
                synthesis += f"\n\n---\n\n{plan}"
    except Exception as e:
        log_warn(logger, f"학습 계획 오류: {e}")

    return synthesis


def append_quiz_sections(
    synthesis: str,
    quiz_source_note: str,
    quiz_note_name: str,
    subject: str,
    sources: dict,
    config: dict,
    logger: logging.Logger,
    pretest_text: str = "",
) -> tuple[str, bool]:
    """교재 퀴즈 섹션을 추가하고 queue용 자동 퀴즈를 생성."""
    quiz_cfg = config.get("quiz", {})

    # 3a: 교재 PDF 문제 크롭 (실패해도 graceful fallback)
    if quiz_cfg.get("prefer_textbook_problems", True):
        try:
            from quiz_cropper import crop_textbook_problems
            from textbook_quiz import _detect_chapter

            chapter = _detect_chapter(sources.get("note_text", ""), config, subject)
            crop_result = crop_textbook_problems(subject, chapter, config, logger)
            status = crop_result.get("status")
            if status == "ok":
                log_detail(logger, f"교재 문제 크롭 완료: {crop_result.get('count', 0)}건")
            else:
                reason = crop_result.get("reason", "unknown")
                log_warn(logger, f"교재 문제 크롭 fallback: status={status}, reason={reason}")
        except Exception as e:
            log_warn(logger, f"교재 문제 크롭 오류(자동 퀴즈로 fallback): {e}")

    try:
        from textbook_quiz import add_textbook_quiz_section

        synthesis = add_textbook_quiz_section(synthesis, subject, sources["note_text"], config)
    except Exception as e:
        log_warn(logger, f"교재 퀴즈 오류(자동 퀴즈는 계속 진행): {e}")

    try:
        from generate import process_content

        queue_generated = process_content(
            sources["note_text"],
            subject,
            quiz_source_note,
            config,
            logger,
            note_name=quiz_note_name,
            pretest_text=pretest_text,
        )
    except Exception as e:
        log_error(logger, f"퀴즈 생성 오류: {e}")
        return synthesis, False

    if not queue_generated:
        log_error(logger, "퀴즈 생성 실패: queue 파일이 생성되지 않았습니다.")
        return synthesis, False

    return synthesis, True


def persist_outputs(
    synthesis: str,
    subject: str,
    note_name: str,
    sources: dict,
    config: dict,
    logger: logging.Logger,
) -> tuple[Path, Path | None]:
    """MD/PDF 결과물을 저장."""
    output_cfg = config.get("output", {})
    smoke_mode = bool(output_cfg.get("smoke_mode", False))

    cleaned = remove_unverified_user_state(synthesis)
    tagged = enforce_provenance_and_emphasis(cleaned, config)

    final_main = tagged
    enrichment_content = ""
    if smoke_mode:
        final_main, enrichment_content = split_smoke_mode_sections(tagged)

    md_path = save_synthesis_md(final_main, subject, note_name, config)
    log_detail(logger, f"MD 저장: {md_path.name}")

    if smoke_mode and enrichment_content:
        enrichment_path = save_enrichment_md(enrichment_content, subject, note_name, config)
        log_detail(logger, f"Enrichment 저장: {enrichment_path.name}")

    all_images = sources["textbook_images"] + sources["slides_images"]
    pdf_path = save_synthesis_pdf(final_main, subject, note_name, all_images, config)
    if pdf_path:
        log_detail(logger, f"PDF 저장: {pdf_path.name}")

    return md_path, pdf_path


def run_stage4_verifier(
    synthesis: str,
    sources: dict,
    subject: str,
    note_name: str,
    config: dict,
    logger: logging.Logger,
) -> tuple[str, dict]:
    """Stage 4 verifier 실행 + 필요 시 수정 지시 기반 재시도."""
    from verifier import VerifierConfig, save_verification_report, verify_note_and_quiz
    from llm_router import LLMRouter

    verifier_cfg = VerifierConfig.from_config(config)
    if not verifier_cfg.enabled:
        return synthesis, {"verdict": "SKIP", "score": None, "checks": {}}

    current = synthesis
    best_report: dict = {"verdict": "FAIL", "score": 0, "checks": {}}
    logs_dir = get_study_paths(config).logs
    report_path = logs_dir / f"verification_report_{subject}_{note_name.replace('.md', '')}.json"
    router = LLMRouter(config)

    for attempt in range(verifier_cfg.max_retries + 1):
        report = verify_note_and_quiz(sources.get("note_text", ""), current, config, subject)
        report["attempt"] = attempt + 1
        best_report = report
        save_verification_report(report, report_path)
        log_detail(
            logger,
            f"[Stage 4] 검증 결과: {report.get('verdict')} ({report.get('score')}/100), attempt={attempt + 1}",
        )

        if report.get("verdict") == "PASS":
            return current, report

        if attempt >= verifier_cfg.max_retries:
            break

        fix_prompt = (
            "아래 검증 리포트를 만족하도록 정리노트/퀴즈 섹션을 수정하세요. "
            "출력은 수정된 markdown 본문만 반환.\n\n"
            f"[fix_instructions]\n{report.get('fix_instructions', '')}\n\n"
            f"[current]\n{current}"
        )
        fixed = router.generate(fix_prompt, task_type="synthesis_deep")
        if fixed and fixed.strip():
            current = fixed.strip()
            log_detail(logger, "[Stage 4] fix_instructions 반영 재생성 완료")
        else:
            log_warn(logger, "[Stage 4] 재생성 실패, 기존 결과로 다음 검증 진행")

    log_warn(logger, f"[Stage 4] 최종 FAIL, 리포트 저장: {report_path.name}")
    return current, best_report


def record_synthesis_session(
    subject: str,
    note_name: str,
    classification: dict | None,
    config: dict,
) -> None:
    """분류 결과에서 추출된 개념을 학습 이력에 기록."""
    try:
        from memory_manager import MemoryManager

        mem = MemoryManager(config)
        if classification:
            for sec in classification.get("sections", []):
                for concept in sec.get("key_concepts", []):
                    mem.record_result(
                        subject,
                        [concept],
                        "correct",
                        source_note=note_name,
                        memo="auto: 정리노트 생성 시 학습 완료",
                    )
    except Exception:
        pass


def refresh_hermes_schedule(config: dict, reason: str, logger: logging.Logger) -> None:
    """새 학습 결과를 바탕으로 Hermes 일정을 재계산."""
    try:
        from agents.hermes_agent import HermesAgent

        HermesAgent(config).refresh_from_event(reason)
        log_detail(logger, "Hermes 일정 갱신 완료")
    except Exception as e:
        log_warn(logger, f"Hermes 일정 갱신 실패: {e}")


def _parse_chapter_number(chapter: str) -> int | None:
    match = re.fullmatch(r"(?:ch(?:apter)?)?\s*(\d+)", chapter.strip(), re.IGNORECASE)
    if match:
        return int(match.group(1))
    return None


def _note_matches_chapter(note_path: Path, chapter: str, subject_cfg: dict) -> bool:
    chapter_num = _parse_chapter_number(chapter)
    if chapter_num is None:
        return False

    text = note_path.read_text(encoding="utf-8")
    chapter_patterns = [
        rf"\bch(?:apter)?\s*{chapter_num}\b",
        rf"\b{chapter_num}\s*장\b",
        rf"\b{chapter_num}\.\d+\b",
    ]
    if any(re.search(pattern, text, re.IGNORECASE) for pattern in chapter_patterns):
        return True

    chapter_pages = subject_cfg.get("textbook_chapter_pages", {}).get(f"ch{chapter_num}")
    if not chapter_pages:
        return False

    from source_extractor import parse_page_references

    page_refs = parse_page_references(text)
    referenced_pages = [page + 1 for page in page_refs.get("textbook_pages", [])]
    chapter_start, chapter_end = chapter_pages
    return any(chapter_start <= page <= chapter_end for page in referenced_pages)


def _collect_chapter_notes(note_dir: Path, chapter: str, subject_cfg: dict) -> list[Path]:
    return [
        note_path
        for note_path in sorted(note_dir.glob("*.md"))
        if _note_matches_chapter(note_path, chapter, subject_cfg)
    ]


# ══════════════════════════════════════════════════════════════
# main
# ══════════════════════════════════════════════════════════════

def _load_pretest_text(pretest_path: Path | None) -> str:
    """사전 지식 stub에서 사용자가 입력한 텍스트 추출 (placeholder 제외)."""
    if pretest_path is None or not pretest_path.exists():
        return ""
    try:
        content = pretest_path.read_text(encoding="utf-8")
        # placeholder가 남아있으면 빈 문자열로
        if "(여기에 입력)" in content:
            return ""
        return content
    except Exception:
        return ""


def process_note(note_path: Path, config: dict, logger: logging.Logger, pretest_text: str = "") -> bool:
    """단일 노트 파일에 대해 v3 10단계 파이프라인 실행."""
    if note_path.suffix.lower() != ".md":
        log_error(logger, f"synthesize.py는 Markdown 노트만 입력으로 지원합니다: {note_path}")
        return False

    subject = detect_subject(note_path, config)
    if subject is None:
        log_error(logger, f"과목 감지 실패: {note_path}")
        return False

    subject_cfg = config["subjects"].get(subject)
    if subject_cfg is None:
        log_error(logger, f"subjects에 '{subject}' 없음")
        return False

    note_name = note_path.name
    discord_notifier.pipeline_start("study-pipeline", note_name)
    print(f"\n  과목: {subject} | 파일: {note_name}")
    print(f"  {'─'*50}")

    log_step(logger, 1, "소스 수집")
    sources = collect_sources_for_note(note_path, subject, config, logger)
    sources["note_name"] = note_path.name

    # 2.3: 노트 인덱싱 (유사도 검색용)
    try:
        from memory_manager import MemoryManager
        MemoryManager(config).embed_note(str(note_path), sources["note_text"], subject)
    except Exception:
        pass

    log_step(logger, 2, "고급 PDF 파싱 확인")
    log_detail(logger, "marker 상태는 소스 수집 단계에서 확인됨")

    log_step(logger, 3, "에이전트: 분류 + 갭 감지")
    agent_results = run_agents(sources, subject, config, logger)

    log_step(logger, 4, "에이전트: 교차과목 연결")
    cross_connections = run_cross_subject_analysis(sources, subject, config, logger)
    agent_results["cross_connections"] = cross_connections

    log_step(logger, 5, "논문 수집 + PubMed 연동")
    papers = run_paper_enrichment(sources, subject, config, logger)

    log_step(logger, 6, "LLM 종합 정리")
    synthesis = build_synthesis(sources, subject, config, logger)
    if synthesis is None:
        log_error(logger, f"종합 정리 생성 실패: {note_path}")
        discord_notifier.pipeline_error("study-pipeline", "종합 정리 생성 실패", note_name)
        return False

    log_step(logger, 7, "심화 분석")
    synthesis = append_analysis_sections(
        synthesis, sources, subject, agent_results, papers, config, logger
    )

    log_step(logger, 8, "학습 계획 생성")
    synthesis = append_study_plan_section(synthesis, subject, config, logger)

    log_step(logger, 9, "교재 퀴즈 + 자동 퀴즈 생성")
    synthesis, quiz_ok = append_quiz_sections(
        synthesis,
        note_name,
        note_path.stem,
        subject,
        sources,
        config,
        logger,
        pretest_text=pretest_text,
    )

    if not quiz_ok:
        discord_notifier.pipeline_error("study-pipeline", "퀴즈 생성 실패", note_name)
        return False

    log_detail(logger, "[Stage 4] verifier 실행")
    synthesis, verification_report = run_stage4_verifier(
        synthesis, sources, subject, note_name, config, logger
    )

    log_step(logger, 10, "결과 저장")
    persist_outputs(synthesis, subject, note_name, sources, config, logger)
    record_synthesis_session(subject, note_name, agent_results.get("classification"), config)
    refresh_hermes_schedule(config, "synthesis_completed", logger)

    logger.info(f"[DONE] v3 종합 완료: {subject}/{note_name}")
    verifier_score = verification_report.get("score")
    summary = f"{len(synthesis)}자 정리노트 생성"
    if verifier_score is not None:
        summary += f" (verifier: {verifier_score}/100)"
    discord_notifier.pipeline_complete("study-pipeline", summary, note_name)
    print(f"\n  {'═'*50}")
    print(f"  ✓ 파이프라인 완료: {subject}/{note_name}")
    return True


def process_sources(
    note_paths: list[Path],
    config: dict,
    logger: logging.Logger,
    textbook_override: Path | None = None,
    slides_override: Path | None = None,
    subject_override: str | None = None,
) -> bool:
    """필기본 여러 개 + PDF override로 10단계 파이프라인 실행."""
    from source_extractor import SourceAggregator

    non_md_paths = [path for path in note_paths if path.suffix.lower() != ".md"]
    if non_md_paths:
        log_error(logger, f"노트 입력은 Markdown만 지원합니다: {non_md_paths[0]}")
        return False

    # 과목 감지
    subject = subject_override or detect_subject(note_paths[0], config)
    if subject is None:
        log_error(logger, f"과목 감지 실패: {note_paths[0]}")
        return False
    if subject not in config.get("subjects", {}):
        log_error(logger, f"subjects에 '{subject}' 없음")
        return False

    # 출력 파일명: 첫 번째 필기 이름 기준
    if len(note_paths) == 1:
        note_name = note_paths[0].name
    else:
        note_name = f"{note_paths[0].stem}_외{len(note_paths) - 1}개.md"

    print(f"\n  과목: {subject} | 필기: {len(note_paths)}개")
    if textbook_override:
        print(f"  교재 PDF: {textbook_override.name}")
    if slides_override:
        print(f"  강의자료 PDF: {slides_override.name}")
    print(f"  {'─'*50}")

    log_step(logger, 1, "소스 수집")
    agg = SourceAggregator(config, subject)
    sources = agg.aggregate_for_sources(note_paths, textbook_override, slides_override)
    log_detail(logger, f"필기: {len(sources['note_text'])}자")
    log_detail(logger, f"교재: {len(sources['textbook_text'] or '')}자")
    log_detail(logger, f"강의자료: {len(sources['slides_text'] or '')}자")

    log_step(logger, 2, "고급 PDF 파싱 확인")
    log_detail(logger, "marker 상태는 소스 수집 단계에서 확인됨")

    log_step(logger, 3, "에이전트: 분류 + 갭 감지")
    agent_results = run_agents(sources, subject, config, logger)

    log_step(logger, 4, "에이전트: 교차과목 연결")
    cross_connections = run_cross_subject_analysis(sources, subject, config, logger)
    agent_results["cross_connections"] = cross_connections

    log_step(logger, 5, "논문 수집 + PubMed 연동")
    papers = run_paper_enrichment(sources, subject, config, logger)

    log_step(logger, 6, "LLM 종합 정리")
    synthesis = build_synthesis(sources, subject, config, logger)
    if synthesis is None:
        log_error(logger, f"종합 정리 생성 실패: {note_name}")
        return False

    log_step(logger, 7, "심화 분석")
    synthesis = append_analysis_sections(
        synthesis, sources, subject, agent_results, papers, config, logger
    )

    log_step(logger, 8, "학습 계획 생성")
    synthesis = append_study_plan_section(synthesis, subject, config, logger)

    log_step(logger, 9, "교재 퀴즈 + 자동 퀴즈 생성")
    synthesis, quiz_ok = append_quiz_sections(
        synthesis,
        note_name,
        Path(note_name).stem,
        subject,
        sources,
        config,
        logger,
    )

    if not quiz_ok:
        discord_notifier.pipeline_error("study-pipeline", "퀴즈 생성 실패", note_name)
        return False

    log_detail(logger, "[Stage 4] verifier 실행")
    synthesis, verification_report = run_stage4_verifier(
        synthesis, sources, subject, note_name, config, logger
    )

    log_step(logger, 10, "결과 저장")
    persist_outputs(synthesis, subject, note_name, sources, config, logger)
    record_synthesis_session(subject, note_name, agent_results.get("classification"), config)
    refresh_hermes_schedule(config, "sources_completed", logger)

    logger.info(f"[DONE] 소스 직접 선택 완료: {subject}/{note_name}")
    verifier_score = verification_report.get("score")
    summary = "소스 직접선택 완료"
    if verifier_score is not None:
        summary += f" (verifier: {verifier_score}/100)"
    discord_notifier.pipeline_complete("study-pipeline", summary, note_name)
    print(f"\n  {'═'*50}")
    print(f"  ✓ 파이프라인 완료: {subject}/{note_name}")
    return True


def process_chapter(subject: str, chapter: str, config: dict, logger: logging.Logger) -> bool:
    """한 챕터의 모든 필기를 통합하여 종합 정리노트 생성."""
    subject_cfg = config["subjects"].get(subject)
    if not subject_cfg:
        print(f"[ERROR] 과목 '{subject}' 없음")
        return False

    subject_dir = get_subject_dir(config, subject)
    note_dir = subject_dir / "필기"
    if not note_dir.exists():
        print(f"[ERROR] 필기 폴더 없음: {note_dir}")
        return False

    # 챕터와 관련된 .md만 수집
    all_notes = _collect_chapter_notes(note_dir, chapter, subject_cfg)
    if not all_notes:
        print(f"[ERROR] 챕터 '{chapter}'와 매칭되는 필기 파일 없음")
        return False

    print(f"챕터 통합 모드: {subject}/{chapter}")
    print(f"  필기 파일: {len(all_notes)}개")
    for n in all_notes:
        print(f"    - {n.name}")

    # 3종 소스 수집 (교재 + 강의자료)
    from chapter_router import ChapterRouter
    from source_extractor import SourceAggregator

    agg = SourceAggregator(config, subject)
    chapter_num = _parse_chapter_number(chapter)
    if chapter_num is None:
        print(f"[ERROR] 챕터 키 파싱 실패: {chapter}")
        return False

    router = ChapterRouter(config, subject_cfg, agg)

    # 모든 필기 텍스트 병합 (챕터 라우팅 적용)
    combined_parts: list[str] = []
    for note in all_notes:
        text = note.read_text(encoding="utf-8")
        routed = router.extract_for_chapter(text, chapter_num)
        if not routed.text.strip():
            continue
        combined_parts.append(f"=== {note.stem} ({routed.reason}) ===\n{routed.text}")

    if not combined_parts:
        print(f"[ERROR] 챕터 '{chapter}'로 라우팅된 필기 섹션이 없음")
        return False

    combined_text = "\n\n".join(combined_parts)
    print(f"  통합 텍스트: {len(combined_text)}자")

    chapter_pages = subject_cfg.get("textbook_chapter_pages", {}).get(chapter)
    textbook_text = agg.get_textbook_text(pages=tuple(chapter_pages)) if chapter_pages else None
    slides_text = agg.get_slides_text()
    textbook_images = agg.get_textbook_images(pages=tuple(chapter_pages)) if chapter_pages else []
    slides_images = agg.get_slides_images()

    sources = {
        "note_text": combined_text,
        "textbook_text": textbook_text,
        "slides_text": slides_text,
        "page_refs": {"textbook_pages": [], "slide_pages": []},
        "textbook_images": textbook_images,
        "slides_images": slides_images,
    }

    # LLM 종합
    print("  LLM 종합 중...")
    synthesis = synthesize_notes(sources, subject, config)
    if not synthesis:
        return False

    # PubMed
    synthesis = add_pubmed_section(synthesis, subject, combined_text, config)
    # 보충 설명
    synthesis = add_supplementary_explanations(synthesis, config)
    # 교재 퀴즈
    try:
        from textbook_quiz import add_textbook_quiz_section
        synthesis = add_textbook_quiz_section(synthesis, subject, combined_text, config)
    except Exception as e:
        print(f"  [WARN] 교재 퀴즈 오류: {e}")

    # 저장
    chapter_name = f"{chapter}_통합"
    md_path = save_synthesis_md(synthesis, subject, f"{chapter_name}.md", config)
    print(f"  MD: {md_path.name}")

    all_images = textbook_images + slides_images
    pdf_path = save_synthesis_pdf(synthesis, subject, f"{chapter_name}.md", all_images, config)
    if pdf_path:
        print(f"  PDF: {pdf_path.name}")

    logger.info(f"챕터 통합 완료: {subject}/{chapter}")
    refresh_hermes_schedule(config, "chapter_completed", logger)
    return True


def _parse_flag_value(argv: list[str], flag: str) -> str | None:
    """argv에서 --flag value 형식의 값을 반환. 없으면 None."""
    if flag in argv:
        idx = argv.index(flag)
        if idx + 1 < len(argv) and not argv[idx + 1].startswith("--"):
            return argv[idx + 1]
    return None


def main() -> None:
    if len(sys.argv) < 2:
        print("사용법:")
        print('  python synthesize.py <노트파일 경로>              # 단일 노트')
        print('  python synthesize.py <폴더 경로>                  # 폴더 내 전체')
        print('  python synthesize.py --chapter <과목> <챕터>      # 챕터 통합')
        print('  python synthesize.py --notes <노트1> [노트2 ...]  # 소스 직접 지정')
        print('                       [--textbook <교재.pdf>]')
        print('                       [--slides <강의자료.pdf>]')
        print('                       [--subject <과목키>]')
        print()
        print("예시:")
        print('  python synthesize.py "../../유기화학/필기/4월 9일.md"')
        print('  python synthesize.py --chapter organic_chem ch4')
        print('  python synthesize.py --notes note1.md note2.md --textbook tb.pdf --slides sl.pdf')
        sys.exit(0)

    config = load_config()
    paths = get_study_paths(config)
    logger = setup_logging(paths.logs)

    # ── 소스 직접 지정 모드 (--notes) ──
    if "--notes" in sys.argv:
        notes_idx = sys.argv.index("--notes")
        note_args: list[str] = []
        i = notes_idx + 1
        while i < len(sys.argv) and not sys.argv[i].startswith("--"):
            note_args.append(sys.argv[i])
            i += 1

        if not note_args:
            print("[ERROR] --notes 뒤에 파일 경로가 없습니다.")
            sys.exit(1)

        note_paths = [Path(n).resolve() for n in note_args]
        for np in note_paths:
            if not np.exists():
                print(f"[ERROR] 파일 없음: {np}")
                sys.exit(1)

        tb_raw = _parse_flag_value(sys.argv, "--textbook")
        sl_raw = _parse_flag_value(sys.argv, "--slides")
        textbook_override = Path(tb_raw).resolve() if tb_raw else None
        slides_override = Path(sl_raw).resolve() if sl_raw else None
        subject_override = _parse_flag_value(sys.argv, "--subject")

        if not process_sources(note_paths, config, logger, textbook_override, slides_override, subject_override):
            sys.exit(1)
        print("\n완료!")
        return

    # ── 챕터 통합 모드 ──
    if sys.argv[1] == "--chapter":
        if len(sys.argv) < 4:
            print("사용법: python synthesize.py --chapter <과목키> <챕터키>")
            print("예시: python synthesize.py --chapter organic_chem ch4")
            sys.exit(1)
        subject = sys.argv[2]
        chapter = sys.argv[3]
        if not process_chapter(subject, chapter, config, logger):
            sys.exit(1)
        print("\n완료!")
        return

    # ── 단일 노트 / 폴더 모드 ──
    target = Path(sys.argv[1]).resolve()
    if not target.exists():
        print(f"[ERROR] 파일 없음: {target}")
        sys.exit(1)

    # 2.2: --pretest <path> 파싱 (watcher가 stub 경로를 전달할 때 사용)
    pretest_raw = _parse_flag_value(sys.argv, "--pretest")
    pretest_text = _load_pretest_text(Path(pretest_raw).resolve() if pretest_raw else None)
    if pretest_text:
        print(f"  [PRETEST] 사전 지식 사용: {len(pretest_text)}자")

    if target.is_dir():
        files = sorted(target.rglob("*.md"))
        files = [f for f in files if "퀴즈" not in str(f) and "정리" not in str(f)]
        print(f"폴더 모드: {len(files)}개 파일")
        for f in files:
            print(f"\n{'='*60}")
            print(f"[처리 중] {f.name}")
            process_note(f, config, logger, pretest_text=pretest_text)
    else:
        print(f"[처리 중] {target.name}")
        if not process_note(target, config, logger, pretest_text=pretest_text):
            sys.exit(1)

    print("\n완료!")


if __name__ == "__main__":
    main()
