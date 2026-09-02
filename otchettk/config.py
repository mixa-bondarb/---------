"""Конфигурация прототипа.

Все параметры (LLM-провайдер, модель, пути к базам знаний) задаются в YAML-файле.
Смена провайдера (внешний API <-> локальный OpenAI-совместимый сервер) выполняется
только изменением конфигурации, без изменения кода (ТЗ, п. 6.2, критерий приёмки 5).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class LLMConfig:
    base_url: str = "https://api.openai.com/v1"
    model: str = "gpt-4o-mini"
    api_key_env: str = "OPENAI_API_KEY"
    temperature: float = 0.0
    seed: int | None = 0
    timeout_s: float = 180.0
    max_retries_validation: int = 2
    parallel_rubrics: bool = True

    @property
    def api_key(self) -> str | None:
        # Ключ берётся только из переменной окружения (ТЗ, п. 6.1: ключи не хранятся в репозитории).
        return os.environ.get(self.api_key_env) or None


@dataclass
class PathsConfig:
    prompts_dir: Path = Path("prompts")
    safety_base_dir: Path = Path("data/safety_base")
    etalons_dir: Path = Path("data/etalons")
    reports_dir: Path = Path("reports")
    logs_dir: Path = Path("logs")


@dataclass
class AppConfig:
    llm: LLMConfig = field(default_factory=LLMConfig)
    paths: PathsConfig = field(default_factory=PathsConfig)


def load_config(path: str | Path = "config.yaml") -> AppConfig:
    """Загрузить конфигурацию из YAML. Относительные пути в разделе paths
    разрешаются относительно каталога, в котором лежит файл конфигурации."""
    cfg_path = Path(path)
    if not cfg_path.exists():
        raise FileNotFoundError(f"Файл конфигурации не найден: {cfg_path}")
    raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}

    llm_raw = raw.get("llm", {}) or {}
    llm = LLMConfig(
        base_url=str(llm_raw.get("base_url", LLMConfig.base_url)).rstrip("/"),
        model=llm_raw.get("model", LLMConfig.model),
        api_key_env=llm_raw.get("api_key_env", LLMConfig.api_key_env),
        temperature=float(llm_raw.get("temperature", LLMConfig.temperature)),
        seed=llm_raw.get("seed", LLMConfig.seed),
        timeout_s=float(llm_raw.get("timeout_s", LLMConfig.timeout_s)),
        max_retries_validation=int(
            llm_raw.get("max_retries_validation", LLMConfig.max_retries_validation)
        ),
        parallel_rubrics=bool(llm_raw.get("parallel_rubrics", LLMConfig.parallel_rubrics)),
    )

    base_dir = cfg_path.resolve().parent

    def _resolve(value: str | Path) -> Path:
        p = Path(value)
        return p if p.is_absolute() else base_dir / p

    paths_raw = raw.get("paths", {}) or {}
    defaults = PathsConfig()
    paths = PathsConfig(
        prompts_dir=_resolve(paths_raw.get("prompts_dir", defaults.prompts_dir)),
        safety_base_dir=_resolve(paths_raw.get("safety_base_dir", defaults.safety_base_dir)),
        etalons_dir=_resolve(paths_raw.get("etalons_dir", defaults.etalons_dir)),
        reports_dir=_resolve(paths_raw.get("reports_dir", defaults.reports_dir)),
        logs_dir=_resolve(paths_raw.get("logs_dir", defaults.logs_dir)),
    )
    return AppConfig(llm=llm, paths=paths)
