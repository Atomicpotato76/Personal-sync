"""report_generator.py -- 세션 보고서 생성 (Claude LLM + Markdown)."""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger("pipeline")


def _collect_session_data(pipeline_dir: Path, output_dir: Path, log_dir: Path) -> dict:
    """가장 최근 세션의 데이터를 수집."""
    data = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "log_tail": "",
        "output_md": "",
        "weak_concepts": {},
        "output_files": [],
    }

    # 로그 마지막 50줄
    log_path = log_dir / "pipeline.log"
    if log_path.exists():
        lines = log_path.read_text(encoding="utf-8").splitlines()
        data["log_tail"] = "\n".join(lines[-50:])

    # 가장 최근 MD 출력
    md_dir = output_dir / "md"
    if md_dir.exists():
        md_files = sorted(md_dir.glob("*.md"), key=lambda f: f.stat().st_mtime, reverse=True)
        if md_files:
            data["output_md"] = md_files[0].read_text(encoding="utf-8")
            data["output_files"].append(str(md_files[0]))

    # weak_concepts
    wc_path = pipeline_dir / "weak_concepts.json"
    if wc_path.exists():
        try:
            data["weak_concepts"] = json.loads(wc_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    return data


def _find_source_images(
    config: dict,
    subject: str,
    cache_base: Path,
    max_images: int = 6,
) -> list[dict]:
    """캐시에서 교재/강의자료 이미지를 찾아 반환."""
    images = []
    for src_type in ["textbook", "slides"]:
        img_dir = cache_base / "images" / subject / src_type
        if not img_dir.exists():
            continue
        # 크기 순으로 상위 이미지 선택 (큰 이미지가 더 의미있을 확률 높음)
        candidates = sorted(
            img_dir.glob("*.*"),
            key=lambda f: f.stat().st_size,
            reverse=True,
        )
        for c in candidates:
            if c.suffix.lower() in {".png", ".jpg", ".jpeg"}:
                images.append({
                    "path": str(c),
                    "source": src_type,
                    "name": c.stem,
                })
                if len(images) >= max_images:
                    return images
    return images


def generate_report_content(
    config: dict,
    session_data: dict,
    subject: str | None = None,
) -> Optional[str]:
    """Claude를 사용하여 세션 보고서 내용을 생성."""
    import sys
    scripts_dir = Path(__file__).resolve().parent.parent
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    from llm_router import LLMRouter

    router = LLMRouter(config)

    output_md = session_data.get("output_md", "")
    # 토큰 절약: 내용이 너무 길면 잘라냄
    if len(output_md) > 8000:
        output_md = output_md[:8000] + "\n\n... (이하 생략)"

    weak_summary = ""
    wc = session_data.get("weak_concepts", {})
    if subject and subject in wc:
        items = wc[subject]
        weak_summary = "\n".join(
            f"- {tag}: mastery={info.get('mastery', 0):.0%}, priority={info.get('priority', '?')}"
            for tag, info in sorted(items.items(), key=lambda x: x[1].get("mastery", 0))[:15]
        )
    elif wc:
        for subj, items in wc.items():
            weak_summary += f"\n[{subj}]\n"
            for tag, info in sorted(items.items(), key=lambda x: x[1].get("mastery", 0))[:10]:
                weak_summary += f"  - {tag}: mastery={info.get('mastery', 0):.0%}\n"

    prompt = f"""당신은 대학교 학습 보고서 작성 전문가입니다.
아래 학습 세션의 데이터를 기반으로, 체계적인 학습 보고서를 Markdown 형식으로 작성하세요.

## 보고서 요구사항
1. **세션 요약**: 이번 세션에서 다룬 핵심 주제와 학습 범위
2. **핵심 개념 정리**: 주요 개념을 구조화하여 정리 (표, 리스트 활용)
3. **취약 개념 분석**: 취약 개념과 개선 방안
4. **반응식/분자식**: 관련 화학 반응식이나 분자식이 있으면 텍스트로 표기 (예: CH3OH → CH2=O + H2)
5. **학습 권장사항**: 다음 세션에서 집중해야 할 부분

## 형식
- Markdown 형식
- 헤딩은 ##, ### 사용
- 핵심 용어는 **볼드** 처리
- 이미지 삽입 위치를 `[IMAGE: 설명]` 태그로 표시 (교재/강의자료에서 크롭할 이미지)

## 세션 데이터

### 정리노트 내용:
{output_md}

### 취약 개념:
{weak_summary}

### 세션 시각: {session_data.get('timestamp', '')}

보고서를 작성하세요. [IMAGE: ...] 태그를 적절한 위치에 넣어 이미지가 필요한 부분을 표시하세요.
"""

    result = router.generate(prompt, task_type="synthesis_final")
    return result


def build_report_md(
    report_content: str,
    images: list[dict],
    output_path: Path,
) -> Path:
    """보고서를 MD 파일로 저장. [IMAGE: ...] 태그를 실제 이미지 경로로 치환."""
    # [IMAGE: ...] 태그를 이미지로 치환
    img_idx = 0
    def _replace_image(m):
        nonlocal img_idx
        if img_idx < len(images):
            img = images[img_idx]
            img_idx += 1
            rel_path = img["path"]
            source_label = "교재" if img["source"] == "textbook" else "강의자료"
            return f"![{source_label} - {img['name']}]({rel_path})"
        return m.group(0)  # 이미지 없으면 태그 유지

    content = re.sub(r"\[IMAGE:\s*([^\]]+)\]", _replace_image, report_content)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding="utf-8")
    return output_path


def generate_session_report(
    config: dict,
    output_format: str = "md",
    subject: str | None = None,
) -> Optional[Path]:
    """세션 보고서를 생성하여 파일로 저장.

    Args:
        config: 전체 config dict
        output_format: "md"
        subject: 과목 키 (None이면 전체)

    Returns:
        생성된 파일 경로 또는 None
    """
    from path_utils import get_study_paths
    paths = get_study_paths(config)

    session_data = _collect_session_data(paths.pipeline, paths.pipeline / "output", paths.logs)
    # output 디렉토리가 pipeline 밖에 있을 수 있으므로 양쪽 체크
    alt_output = Path(config.get("pipeline_dir", ".")) / "output"
    if not session_data["output_md"] and alt_output.exists():
        session_data = _collect_session_data(paths.pipeline, alt_output, paths.logs)

    if not session_data["output_md"]:
        logger.warning("보고서 생성 실패: 출력 데이터 없음")
        return None

    # LLM으로 보고서 내용 생성
    report_content = generate_report_content(config, session_data, subject)
    if not report_content:
        logger.error("보고서 생성 실패: LLM 응답 없음")
        return None

    # 이미지 수집
    cache_base = paths.cache
    images = []
    if subject:
        images = _find_source_images(config, subject, cache_base)
    else:
        for subj_key in config.get("subjects", {}):
            images.extend(_find_source_images(config, subj_key, cache_base, max_images=3))

    # 파일 생성
    now = datetime.now().strftime("%Y%m%d_%H%M")
    subj_label = subject or "all"

    report_dir = Path(config.get("pipeline_dir", ".")) / "output" / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)

    out_path = report_dir / f"report_{subj_label}_{now}.md"
    return build_report_md(report_content, images, out_path)
