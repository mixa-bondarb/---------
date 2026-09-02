"""Библиотека шаблонов промптов.

Шаблоны хранятся в файлах каталога prompts/ и подлежат версионированию
вместе с кодом (ТЗ, п. 5.3, критерий приёмки 7). Подстановка переменных —
через маркеры {{имя}}, чтобы фигурные скобки JSON-примеров в шаблонах
не конфликтовали с подстановкой.
"""

from __future__ import annotations

import re
from pathlib import Path

_PLACEHOLDER_RE = re.compile(r"\{\{(\w+)\}\}")


class PromptLibrary:
    def __init__(self, prompts_dir: str | Path) -> None:
        self.dir = Path(prompts_dir)
        if not self.dir.is_dir():
            raise FileNotFoundError(f"Каталог промптов не найден: {self.dir}")

    def render(self, name: str, **variables: str) -> str:
        path = self.dir / f"{name}.md"
        if not path.exists():
            raise FileNotFoundError(f"Шаблон промпта не найден: {path}")
        template = path.read_text(encoding="utf-8")

        def _sub(match: re.Match[str]) -> str:
            key = match.group(1)
            if key not in variables:
                raise KeyError(f"В шаблоне {name} не заполнена переменная {{{{{key}}}}}")
            return str(variables[key])

        return _PLACEHOLDER_RE.sub(_sub, template)
