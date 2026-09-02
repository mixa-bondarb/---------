"""Журналирование запуска (ТЗ, п. 5.3 и п. 7).

На каждый запуск создаётся каталог logs/run_<метка времени>/ с файлами:
- run.log                — события запуска;
- llm_calls.jsonl        — все запросы и ответы LLM (для отладки и научной валидации);
- rejected_findings.jsonl — замечания, отброшенные верификацией цитат.
"""

from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path
from threading import Lock
from typing import Any


class RunLog:
    def __init__(self, logs_dir: str | Path, echo: bool = True) -> None:
        stamp = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        self.dir = Path(logs_dir) / f"run_{stamp}"
        self.dir.mkdir(parents=True, exist_ok=True)
        self._echo = echo
        self._lock = Lock()

    def _append(self, filename: str, line: str) -> None:
        with self._lock:
            with open(self.dir / filename, "a", encoding="utf-8") as f:
                f.write(line + "\n")

    def event(self, message: str) -> None:
        stamp = _dt.datetime.now().strftime("%H:%M:%S")
        self._append("run.log", f"[{stamp}] {message}")
        if self._echo:
            print(f"[{stamp}] {message}")

    def llm_call(
        self,
        *,
        link: str,
        attempt: int,
        request: dict[str, Any],
        response_text: str | None,
        duration_s: float,
        error: str | None = None,
    ) -> None:
        record = {
            "ts": _dt.datetime.now().isoformat(timespec="seconds"),
            "link": link,
            "attempt": attempt,
            "duration_s": round(duration_s, 2),
            "request": request,
            "response": response_text,
            "error": error,
        }
        self._append("llm_calls.jsonl", json.dumps(record, ensure_ascii=False))

    def rejected_finding(self, finding: dict[str, Any], reason: str) -> None:
        record = {
            "ts": _dt.datetime.now().isoformat(timespec="seconds"),
            "reason": reason,
            "finding": finding,
        }
        self._append("rejected_findings.jsonl", json.dumps(record, ensure_ascii=False))


class NullRunLog(RunLog):
    """Журнал-заглушка для тестов: ничего не пишет на диск."""

    def __init__(self) -> None:  # noqa: D401 - переопределение без создания каталога
        self._echo = False
        self._lock = Lock()
        self.rejected: list[dict[str, Any]] = []
        self.events: list[str] = []

    def _append(self, filename: str, line: str) -> None:
        pass

    def event(self, message: str) -> None:
        self.events.append(message)

    def rejected_finding(self, finding: dict[str, Any], reason: str) -> None:
        self.rejected.append({"reason": reason, "finding": finding})
