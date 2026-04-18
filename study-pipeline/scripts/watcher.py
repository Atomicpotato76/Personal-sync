#!/usr/bin/env python3
"""watcher.py -- vault 필기/ 폴더를 감시하여 새 파일 생성 시 synthesize.py를 자동 호출."""

from __future__ import annotations

import io
import logging
import subprocess
import sys
import time
from collections.abc import Iterable
from pathlib import Path

if sys.stdout.encoding != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import yaml
from watchdog.events import FileSystemEventHandler, FileCreatedEvent
from watchdog.observers import Observer

from path_utils import get_study_paths, apply_env_path_overrides

# ── 경로 설정 ──────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_PATH = SCRIPT_DIR / "config.yaml"
EXCLUDED_OUTPUT_FOLDERS = frozenset({"퀴즈", "정리"})
EVENT_DEBOUNCE_SECONDS = 5.0


def load_config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return apply_env_path_overrides(yaml.safe_load(f) or {})


def setup_logging(log_dir: Path) -> logging.Logger:
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("watcher")
    logger.setLevel(logging.DEBUG)

    # 파일 핸들러
    fh = logging.FileHandler(log_dir / "watcher.log", encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(fh)

    # 콘솔 핸들러
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(ch)

    return logger


class NoteCreatedHandler(FileSystemEventHandler):
    """새 학습 파일이 생성되면 synthesize.py를 호출한다."""

    def __init__(self, config: dict, logger: logging.Logger):
        super().__init__()
        self.config = config
        self.logger = logger
        self.folder_mapping: dict = config.get("folder_mapping", {})
        paths = get_study_paths(config)
        self.vault = paths.vault
        self.notes_base = paths.notes_base
        self.excluded_folders = EXCLUDED_OUTPUT_FOLDERS
        # 최근 처리 시각 (created/modified 연속 이벤트 debounce)
        self._recent: dict[str, float] = {}

    def _cleanup_recent(self, now: float) -> None:
        cutoff = now - EVENT_DEBOUNCE_SECONDS
        stale_keys = [key for key, ts in self._recent.items() if ts < cutoff]
        for key in stale_keys:
            self._recent.pop(key, None)

    def _has_excluded_part(self, parts: Iterable[str]) -> bool:
        return any(part in self.excluded_folders for part in parts)

    def _is_target_file(self, path: Path) -> bool:
        """필기/ 하위의 Markdown 노트 파일인지 확인."""
        suffix = path.suffix.lower()
        if suffix != ".md":
            return False
        try:
            rel = path.relative_to(self.notes_base)
        except ValueError:
            return False
        # 첫 폴더가 매핑에 있어야 함
        if len(rel.parts) < 2:
            return False
        subject_folder = rel.parts[0]
        if subject_folder not in self.folder_mapping:
            return False
        if self._has_excluded_part(rel.parts[1:]):
            return False
        return True

    def _is_paper_pdf(self, path: Path) -> bool:
        """논문 PDF인지 확인 (papers/ 폴더 내 PDF)."""
        if path.suffix.lower() != ".pdf":
            return False
        try:
            rel = path.relative_to(self.notes_base)
        except ValueError:
            return False
        return any("paper" in p.lower() or "논문" in p for p in rel.parts)

    def _should_process(self, file_path: Path) -> bool:
        now = time.monotonic()
        key = str(file_path)
        self._cleanup_recent(now)
        last_seen = self._recent.get(key)
        if last_seen is not None and now - last_seen < EVENT_DEBOUNCE_SECONDS:
            return False
        self._recent[key] = now
        return True

    def _process_note(self, file_path: Path, event_name: str) -> None:
        if not self._is_target_file(file_path) and not self._is_paper_pdf(file_path):
            return
        if not self._should_process(file_path):
            self.logger.debug(f"debounce skip ({event_name}): {file_path.name}")
            return

        # 파일 쓰기 완료 대기 (Obsidian이 저장 완료할 시간)
        time.sleep(2)

        self.logger.info(f"[EVENT] {event_name}: {file_path.name}")

        # 논문 PDF는 인덱싱만 수행
        if self._is_paper_pdf(file_path):
            self._index_paper(file_path)
            return

        pretest_path = self._maybe_create_pretest(file_path)
        self._run_synthesize(file_path, pretest_path=pretest_path)

    def on_created(self, event: FileCreatedEvent) -> None:
        if event.is_directory:
            return

        file_path = Path(event.src_path).resolve()
        self._process_note(file_path, "새 파일")

    def on_modified(self, event) -> None:
        if event.is_directory:
            return

        file_path = Path(event.src_path).resolve()
        self._process_note(file_path, "수정")

    def _index_paper(self, file_path: Path) -> None:
        """논문 PDF를 marker-pdf로 파싱하여 인덱싱."""
        self.logger.info(f"[RUN] 논문 인덱싱: {file_path.name}")
        try:
            from marker_reader import convert_with_fallback
            import yaml
            config_path = SCRIPT_DIR / "config.yaml"
            with open(config_path, encoding="utf-8") as f:
                config = apply_env_path_overrides(yaml.safe_load(f) or {})
            paths = get_study_paths(config)
            cache_dir = paths.cache / "papers" / "marker_cache"
            text = convert_with_fallback(file_path, cache_dir, config=config)
            if text:
                self.logger.info(f"[OK] 논문 인덱싱 완료: {file_path.name} ({len(text)}자)")
            else:
                self.logger.warning(f"[WARN] 논문 텍스트 추출 실패: {file_path.name}")
        except Exception as e:
            self.logger.error(f"[ERROR] 논문 인덱싱 실패: {file_path.name} ({e})")

    _PRETEST_TEMPLATE = (
        "# 사전 지식 체크 — {stem}\n\n"
        "> 노트를 읽기 전에 아래 내용을 먼저 적어주세요.\n"
        "> 비워두면 사전 검사 없이 진행됩니다.\n\n"
        "## 이미 알고 있는 것\n\n"
        "(여기에 입력)\n\n"
        "## 잘 모르는 것 / 배우고 싶은 것\n\n"
        "(여기에 입력)\n"
    )
    _PRETEST_PLACEHOLDER = "(여기에 입력)"

    def _maybe_create_pretest(self, file_path: Path) -> Path | None:
        """pretest.enabled=true 시 사전 지식 stub을 생성하고 wait_sec 동안 입력 대기."""
        pretest_cfg = self.config.get("pretest", {})
        if not pretest_cfg.get("enabled", False):
            return None

        paths = get_study_paths(self.config)
        pretest_dir = paths.pipeline / "pretest"
        pretest_dir.mkdir(parents=True, exist_ok=True)

        stub_path = pretest_dir / f"{file_path.stem}_pretest.md"
        if not stub_path.exists():
            stub_content = self._PRETEST_TEMPLATE.format(stem=file_path.stem)
            stub_path.write_text(stub_content, encoding="utf-8")
            self.logger.info(
                f"[PRETEST] 사전 지식 stub 생성: {stub_path.name} "
                f"— 입력 후 저장하면 자동으로 반영됩니다"
            )

        wait_sec = int(pretest_cfg.get("wait_sec", 120))
        initial_size = len(self._PRETEST_TEMPLATE)
        deadline = time.monotonic() + wait_sec

        self.logger.info(f"[PRETEST] 최대 {wait_sec}초 대기 중... (입력 감지 시 즉시 진행)")
        while time.monotonic() < deadline:
            try:
                content = stub_path.read_text(encoding="utf-8")
                if self._PRETEST_PLACEHOLDER not in content and len(content) > initial_size // 2:
                    self.logger.info("[PRETEST] 사전 지식 입력 감지 — 진행합니다")
                    return stub_path
            except Exception:
                pass
            time.sleep(5)

        self.logger.info("[PRETEST] 대기 시간 초과 — 사전 지식 없이 진행합니다")
        # stub이 실제로 채워졌는지 마지막 확인
        try:
            content = stub_path.read_text(encoding="utf-8")
            if self._PRETEST_PLACEHOLDER not in content:
                return stub_path
        except Exception:
            pass
        return None

    def _run_synthesize(self, file_path: Path, pretest_path: Path | None = None) -> None:
        """synthesize.py를 서브프로세스로 호출."""
        synthesize_py = SCRIPT_DIR / "synthesize.py"
        if not synthesize_py.exists():
            return
        cmd = [sys.executable, str(synthesize_py), str(file_path)]
        if pretest_path is not None and pretest_path.exists():
            cmd.extend(["--pretest", str(pretest_path)])
        self.logger.info(f"[RUN] synthesize.py 호출: {file_path.name}")

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=300,
                cwd=str(SCRIPT_DIR),
            )
            if result.returncode == 0:
                self.logger.info(f"[OK] 종합 정리 완료: {file_path.name}")
                if result.stdout.strip():
                    self.logger.debug(f"stdout: {result.stdout.strip()}")
            else:
                self.logger.error(f"[ERROR] 종합 실패: {file_path.name} (exit {result.returncode})")
                if result.stderr.strip():
                    self.logger.error(f"stderr: {result.stderr.strip()}")
        except subprocess.TimeoutExpired:
            self.logger.error(f"[ERROR] 종합 타임아웃: {file_path.name} (300초)")
        except Exception as e:
            self.logger.error(f"[ERROR] 종합 실행 오류: {file_path.name} ({e})")

def main() -> None:
    config = load_config()
    paths = get_study_paths(config)
    logger = setup_logging(paths.logs)

    watch_path = paths.notes_base
    if not watch_path.exists():
        logger.error(f"감시 대상 경로 없음: {watch_path}")
        sys.exit(1)

    handler = NoteCreatedHandler(config, logger)
    observer = Observer()
    observer.schedule(handler, str(watch_path), recursive=True)
    observer.start()

    logger.info(f"[START] 감시 시작: {watch_path}")
    logger.info(f"대상 과목: {list(config.get('folder_mapping', {}).keys())}")
    logger.info("종료하려면 Ctrl+C를 누르세요.")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("[STOP] 감시 종료 요청")
        observer.stop()

    observer.join()
    logger.info("[STOP] watcher 종료")


if __name__ == "__main__":
    main()
