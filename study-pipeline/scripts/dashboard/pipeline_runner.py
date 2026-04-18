"""pipeline_runner.py -- synthesize.py 비동기 실행 + 진행률 추적."""
from __future__ import annotations

import queue
import re
import subprocess
import sys
import threading
from pathlib import Path
from typing import Optional


class PipelineRunner:
    """synthesize.py를 비동기 실행하고 stdout을 실시간 수집."""

    def __init__(self, scripts_dir: Path):
        self.scripts_dir = scripts_dir
        self.python_exe = sys.executable
        self._process: Optional[subprocess.Popen] = None
        self._output_queue: queue.Queue[str] = queue.Queue()
        self._is_running = False
        self._return_code: Optional[int] = None
        self._all_output: list[str] = []

    @property
    def is_running(self) -> bool:
        return self._is_running

    @property
    def return_code(self) -> Optional[int]:
        return self._return_code

    @property
    def all_output(self) -> list[str]:
        return list(self._all_output)

    def start_note(self, note_path: str):
        """단일 노트 처리 시작."""
        self._start([str(self.scripts_dir / "synthesize.py"), note_path])

    def start_with_sources(
        self,
        note_paths: list[str],
        textbook: str | None = None,
        slides: str | None = None,
        subject: str | None = None,
    ):
        """필기본 여러 개 + PDF override로 처리 시작."""
        args = [str(self.scripts_dir / "synthesize.py"), "--notes"] + note_paths
        if textbook:
            args += ["--textbook", textbook]
        if slides:
            args += ["--slides", slides]
        if subject:
            args += ["--subject", subject]
        self._start(args)

    def start_chapter(self, subject: str, chapter: str):
        """챕터 통합 처리 시작."""
        self._start([
            str(self.scripts_dir / "synthesize.py"),
            "--chapter", subject, chapter,
        ])

    def start_folder(self, folder_path: str):
        """폴더 처리 시작."""
        self._start([str(self.scripts_dir / "synthesize.py"), folder_path])

    def _start(self, args: list[str]):
        if self._is_running:
            return
        self._is_running = True
        self._return_code = None
        self._all_output = []
        # 큐 비우기
        while not self._output_queue.empty():
            try:
                self._output_queue.get_nowait()
            except queue.Empty:
                break

        self._process = subprocess.Popen(
            [self.python_exe] + args,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(self.scripts_dir),
        )
        t = threading.Thread(target=self._read_output, daemon=True)
        t.start()

    def _read_output(self):
        try:
            for line in self._process.stdout:
                stripped = line.rstrip("\n")
                self._output_queue.put(stripped)
                self._all_output.append(stripped)
            self._process.wait()
            self._return_code = self._process.returncode
        except Exception as e:
            self._output_queue.put(f"[ERROR] {e}")
        finally:
            self._is_running = False

    def get_new_lines(self) -> list[str]:
        """큐에서 새 줄을 모두 꺼냄."""
        lines = []
        while not self._output_queue.empty():
            try:
                lines.append(self._output_queue.get_nowait())
            except queue.Empty:
                break
        return lines

    def stop(self):
        if self._process and self._is_running:
            self._process.kill()
            self._is_running = False

    @staticmethod
    def parse_step(line: str) -> Optional[tuple[int, int]]:
        """'[N/M]' 패턴에서 현재/전체 단계 추출."""
        m = re.search(r"\[(\d+)/(\d+)\]", line)
        if m:
            return int(m.group(1)), int(m.group(2))
        return None
