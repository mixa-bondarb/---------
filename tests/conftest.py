"""Общие фикстуры тестов.

FakeProvider позволяет тестировать всю механику цепи промптов
(валидацию, повторы, агрегацию, верификацию цитат) без обращений к внешним API.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from otchettk.config import AppConfig, LLMConfig, PathsConfig  # noqa: E402
from otchettk.llm import LLMProvider  # noqa: E402
from otchettk.runlog import NullRunLog  # noqa: E402


class FakeProvider(LLMProvider):
    """Провайдер с заранее заданными ответами.

    responses: {префикс имени звена: ответ | список ответов (по попыткам)}.
    """

    def __init__(self, responses: dict[str, str | list[str]]) -> None:
        self.responses = {k: (v if isinstance(v, list) else [v]) for k, v in responses.items()}
        self.calls: list[tuple[str, int]] = []

    def complete(self, *, system: str, user: str, link: str, attempt: int = 1) -> str:
        self.calls.append((link, attempt))
        for prefix, answers in self.responses.items():
            if link.startswith(prefix):
                index = min(attempt - 1, len(answers) - 1)
                return answers[index]
        raise AssertionError(f"Нет заготовленного ответа для звена: {link}")


@pytest.fixture
def repo_root() -> Path:
    return ROOT


@pytest.fixture
def null_runlog() -> NullRunLog:
    return NullRunLog()


@pytest.fixture
def app_config(repo_root: Path, tmp_path: Path) -> AppConfig:
    return AppConfig(
        llm=LLMConfig(parallel_rubrics=False, max_retries_validation=2),
        paths=PathsConfig(
            prompts_dir=repo_root / "prompts",
            safety_base_dir=tmp_path / "safety_base",
            etalons_dir=tmp_path / "etalons",
            reports_dir=tmp_path / "reports",
            logs_dir=tmp_path / "logs",
        ),
    )
