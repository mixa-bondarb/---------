"""Базы знаний (ТЗ, пп. 3.2–3.3).

1. База мер безопасности: неструктурированные .pdf/.docx в каталоге safety_base_dir.
   Каждый документ парсится звеном П-Б в структурированные записи; результат
   кэшируется по хэшу файла (повторные запуски не тратят обращения к LLM).
   Пополнение — добавлением файлов, без изменения кода.

2. База эталонных карт: документы в каталоге etalons_dir + необязательный
   файл метаданных <имя>.meta.json (тип работ, система, дата добавления).
   Пополнение — добавлением файлов, без изменения кода.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

from .config import AppConfig
from .llm import LLMProvider, LinkError, ask_json
from .parsing import SUPPORTED_EXTENSIONS, load_document_text
from .prompts import PromptLibrary
from .runlog import RunLog
from .schemas import SAFETY_BASE_SCHEMA

# Слова-основы для «общих» мер, применимых к любым работам.
_GENERIC_SYSTEM_HINTS = ("общ",)


@dataclass
class SafetyRecord:
    id: str
    systems: list[str]
    text: str
    markers: list[str] = field(default_factory=list)
    source: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "systems": self.systems,
            "text": self.text,
            "markers": self.markers,
        }


@dataclass
class Etalon:
    path: Path
    text: str
    title: str = ""
    work_type: str = ""
    system: str = ""
    added: str = ""


def _base_files(directory: Path) -> list[Path]:
    if not directory.is_dir():
        return []
    files = [
        p
        for p in sorted(directory.iterdir())
        if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS
    ]
    return files


def load_safety_base(
    *,
    cfg: AppConfig,
    provider: LLMProvider,
    prompts: PromptLibrary,
    runlog: RunLog,
) -> tuple[list[SafetyRecord], list[str]]:
    """Загрузить и структурировать базу мер безопасности.

    Возвращает (записи, список проблем для раздела «Не проверялось»).
    """
    directory = cfg.paths.safety_base_dir
    files = _base_files(directory)
    problems: list[str] = []
    if not files:
        problems.append(
            f"База мер безопасности пуста: в каталоге {directory} нет документов "
            "(.pdf/.docx). Проверка Р-3 по базе не выполнялась."
        )
        return [], problems

    cache_dir = directory / ".cache"
    records: list[SafetyRecord] = []
    for path in files:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()[:24]
        cache_file = cache_dir / f"{path.stem}.{digest}.json"
        if cache_file.exists():
            data = json.loads(cache_file.read_text(encoding="utf-8"))
            runlog.event(f"П-Б: {path.name} — использован кэш структуризации")
        else:
            try:
                text = load_document_text(path)
                data = ask_json(
                    provider=provider,
                    prompts=prompts,
                    link=f"П-Б ({path.name})",
                    prompt_name="pb_safety_base",
                    schema=SAFETY_BASE_SCHEMA,
                    max_retries=cfg.llm.max_retries_validation,
                    runlog=runlog,
                    base_text=text,
                )
            except (LinkError, ValueError, FileNotFoundError) as exc:
                problems.append(
                    f"Документ базы мер безопасности не обработан: {path.name} ({exc})"
                )
                continue
            cache_dir.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            runlog.event(f"П-Б: {path.name} — структурировано записей: {len(data['records'])}")
        for rec in data["records"]:
            records.append(
                SafetyRecord(
                    id=rec["id"],
                    systems=[s.strip().lower() for s in rec.get("systems", [])],
                    text=rec["text"],
                    markers=[m.strip().lower() for m in rec.get("markers", [])],
                    source=path.name,
                )
            )
    if not records and not problems:
        problems.append("База мер безопасности не содержит ни одной записи.")
    return records, problems


def _system_matches(record_system: str, tk_system: str) -> bool:
    a, b = record_system.strip().lower(), tk_system.strip().lower()
    if not a or not b:
        return False
    return a in b or b in a


def relevant_safety_records(
    records: list[SafetyRecord], systems: list[str]
) -> list[SafetyRecord]:
    """Отобрать записи по затронутым системам; «общие» меры включаются всегда."""
    if not systems:
        return list(records)
    selected: list[SafetyRecord] = []
    for rec in records:
        generic = any(
            hint in s for s in rec.systems for hint in _GENERIC_SYSTEM_HINTS
        )
        matched = any(
            _system_matches(rs, ts) for rs in rec.systems for ts in systems
        )
        if generic or matched:
            selected.append(rec)
    return selected


def load_etalons(directory: Path) -> list[Etalon]:
    etalons: list[Etalon] = []
    for path in _base_files(directory):
        meta_path = path.with_name(path.stem + ".meta.json")
        meta: dict = {}
        if meta_path.exists():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        etalons.append(
            Etalon(
                path=path,
                text=load_document_text(path),
                title=meta.get("title", path.stem),
                work_type=str(meta.get("work_type", "")),
                system=str(meta.get("system", "")),
                added=str(meta.get("added", "")),
            )
        )
    return etalons


def select_relevant_etalons(
    etalons: list[Etalon],
    systems: list[str],
    work_types: list[str],
    max_count: int = 2,
) -> list[Etalon]:
    """Выбор релевантных эталонов по метаданным (ТЗ, п. 3.3 — MVP-механизм)."""

    def score(e: Etalon) -> int:
        s = 0
        if any(_system_matches(e.system, ts) for ts in systems):
            s += 2
        if any(
            wt.strip() and wt.strip().lower() in e.work_type.lower()
            or e.work_type.strip() and e.work_type.strip().lower() in wt.lower()
            for wt in work_types
        ):
            s += 1
        return s

    ranked = sorted(etalons, key=score, reverse=True)
    return ranked[:max_count]
