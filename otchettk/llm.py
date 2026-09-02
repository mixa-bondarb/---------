"""Слой абстракции LLM-провайдера (ТЗ, раздел 6).

Единый интерфейс: «текст промпта + параметры -> текстовый ответ».
Реализация OpenAICompatibleProvider работает с любым OpenAI-совместимым API:
внешние сервисы (OpenAI, OpenRouter и т. п.) и локальные серверы инференса
(Ollama, vLLM, llama.cpp-server). Переключение — только конфигурацией.
"""

from __future__ import annotations

import json
import time
from abc import ABC, abstractmethod
from typing import Any

import httpx
import jsonschema

from .config import LLMConfig
from .prompts import PromptLibrary
from .runlog import RunLog

SYSTEM_PROMPT = (
    "Ты — эксперт по качеству эксплуатационной (технологической) документации "
    "на авиационную технику. Работай только с предоставленным текстом, ничего не выдумывай. "
    "Все цитаты приводи дословно, как в исходном тексте. "
    "Отвечай строго одним JSON-объектом без каких-либо пояснений до или после него."
)


class LLMError(Exception):
    """Ошибка обращения к LLM (сеть, провайдер)."""


class LinkError(Exception):
    """Звено цепи промптов не выполнено после всех повторов."""

    def __init__(self, link: str, reason: str) -> None:
        super().__init__(f"{link}: {reason}")
        self.link = link
        self.reason = reason


class LLMProvider(ABC):
    """Абстрактный провайдер. Логика проверок не зависит от реализации."""

    @abstractmethod
    def complete(self, *, system: str, user: str, link: str, attempt: int = 1) -> str:
        """Выполнить один запрос и вернуть текст ответа модели."""


class OpenAICompatibleProvider(LLMProvider):
    """Провайдер для любого OpenAI-совместимого API (/chat/completions)."""

    _NETWORK_RETRIES = 2

    def __init__(self, cfg: LLMConfig, runlog: RunLog | None = None) -> None:
        self.cfg = cfg
        self.runlog = runlog

    def complete(self, *, system: str, user: str, link: str, attempt: int = 1) -> str:
        payload: dict[str, Any] = {
            "model": self.cfg.model,
            "temperature": self.cfg.temperature,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        if self.cfg.seed is not None:
            payload["seed"] = self.cfg.seed
        headers = {"Content-Type": "application/json"}
        if self.cfg.api_key:
            headers["Authorization"] = f"Bearer {self.cfg.api_key}"
        url = f"{self.cfg.base_url}/chat/completions"

        last_error: Exception | None = None
        for net_try in range(1 + self._NETWORK_RETRIES):
            start = time.monotonic()
            try:
                response = httpx.post(
                    url, json=payload, headers=headers, timeout=self.cfg.timeout_s
                )
                response.raise_for_status()
                data = response.json()
                text = data["choices"][0]["message"]["content"]
                if self.runlog:
                    self.runlog.llm_call(
                        link=link,
                        attempt=attempt,
                        request=payload,
                        response_text=text,
                        duration_s=time.monotonic() - start,
                    )
                return text
            except (httpx.HTTPError, KeyError, ValueError) as exc:
                last_error = exc
                if self.runlog:
                    self.runlog.llm_call(
                        link=link,
                        attempt=attempt,
                        request=payload,
                        response_text=None,
                        duration_s=time.monotonic() - start,
                        error=f"{type(exc).__name__}: {exc}",
                    )
                if net_try < self._NETWORK_RETRIES:
                    time.sleep(2**net_try)
        raise LLMError(f"Запрос к LLM не выполнен ({link}): {last_error}") from last_error


def extract_json(text: str) -> dict[str, Any]:
    """Извлечь JSON-объект из ответа модели (допускаются ограждения ```json)."""
    candidate = text.strip()
    if "```" in candidate:
        # Берём содержимое первого ограждённого блока.
        parts = candidate.split("```")
        if len(parts) >= 3:
            candidate = parts[1]
            if candidate.lstrip().lower().startswith("json"):
                candidate = candidate.lstrip()[4:]
    candidate = candidate.strip()
    try:
        obj = json.loads(candidate)
    except json.JSONDecodeError:
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("В ответе модели не найден JSON-объект")
        obj = json.loads(candidate[start : end + 1])
    if not isinstance(obj, dict):
        raise ValueError("Ответ модели не является JSON-объектом")
    return obj


def ask_json(
    *,
    provider: LLMProvider,
    prompts: PromptLibrary,
    link: str,
    prompt_name: str,
    schema: dict[str, Any],
    max_retries: int,
    runlog: RunLog | None = None,
    **variables: str,
) -> dict[str, Any]:
    """Выполнить звено цепи: промпт -> JSON -> валидация схемы.

    Ответ, не прошедший валидацию, перезапрашивается (не более max_retries повторов),
    затем звено фиксируется как невыполненное (ТЗ, п. 5.3).
    """
    user_prompt = prompts.render(prompt_name, **variables)
    last_reason = ""
    for attempt in range(1, 2 + max_retries):
        try:
            text = provider.complete(
                system=SYSTEM_PROMPT, user=user_prompt, link=link, attempt=attempt
            )
        except LLMError as exc:
            raise LinkError(link, str(exc)) from exc
        try:
            data = extract_json(text)
            jsonschema.validate(data, schema)
            return data
        except (ValueError, json.JSONDecodeError, jsonschema.ValidationError) as exc:
            last_reason = f"{type(exc).__name__}: {str(exc)[:500]}"
            if runlog:
                runlog.event(f"{link}: ответ не прошёл валидацию (попытка {attempt}): {last_reason}")
            user_prompt = (
                prompts.render(prompt_name, **variables)
                + "\n\nВНИМАНИЕ: предыдущий ответ не прошёл проверку структуры: "
                + last_reason
                + "\nВерни строго один JSON-объект точно по требуемой схеме, без пояснений."
            )
    raise LinkError(link, f"ответ не прошёл валидацию после {1 + max_retries} попыток: {last_reason}")
