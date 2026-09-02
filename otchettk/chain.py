"""Цепь промптов (ТЗ, раздел 5).

П-0 структуризация -> П-1 контекст -> [П-2 последовательность, П-3 визуализируемость,
П-4 меры безопасности, П-5 стиль — параллельно] -> П-6 агрегация/дедупликация.
Программная верификация цитат выполняется после цепи (см. report.py).
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

from .config import AppConfig
from .kb import Etalon, SafetyRecord, relevant_safety_records, select_relevant_etalons
from .llm import LLMProvider, LinkError, ask_json
from .prompts import PromptLibrary
from .runlog import RunLog
from .schemas import (
    AGGREGATE_SCHEMA,
    CONTEXT_SCHEMA,
    FINDINGS_SCHEMA,
    STRUCTURE_SCHEMA,
)

# Ограничение объёма текста эталона, передаваемого в промпт П-5.
_ETALON_EXCERPT_CHARS = 4000


@dataclass
class Finding:
    """Замечание после агрегации (до верификации цитат)."""

    id: str
    rubrics: list[str]
    severity: str
    step: str | None
    quote: str | None
    quote_missing: bool
    finding: str
    justification: str | None
    recommendation: str
    source_links: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "rubrics": self.rubrics,
            "severity": self.severity,
            "step": self.step,
            "quote": self.quote,
            "quote_missing": self.quote_missing,
            "finding": self.finding,
            "justification": self.justification,
            "recommendation": self.recommendation,
        }


@dataclass
class ChainResult:
    structure: dict[str, Any]
    context: dict[str, Any] | None
    findings: list[Finding]
    not_checked: list[str]


class ExpertChain:
    def __init__(
        self,
        *,
        provider: LLMProvider,
        prompts: PromptLibrary,
        cfg: AppConfig,
        runlog: RunLog,
    ) -> None:
        self.provider = provider
        self.prompts = prompts
        self.cfg = cfg
        self.runlog = runlog

    # ------------------------------------------------------------------
    def _ask(self, link: str, prompt_name: str, schema: dict, **variables: str) -> dict:
        return ask_json(
            provider=self.provider,
            prompts=self.prompts,
            link=link,
            prompt_name=prompt_name,
            schema=schema,
            max_retries=self.cfg.llm.max_retries_validation,
            runlog=self.runlog,
            **variables,
        )

    # ------------------------------------------------------------------
    def run(
        self,
        tk_text: str,
        safety_records: list[SafetyRecord],
        etalons: list[Etalon],
    ) -> ChainResult:
        not_checked: list[str] = []

        # П-0: структуризация (отказ фатален — без структуры проверки невозможны)
        self.runlog.event("П-0: структуризация ТК")
        structure = self._ask("П-0", "p0_structure", STRUCTURE_SCHEMA, tk_text=tk_text)
        steps_json = json.dumps(structure["steps"], ensure_ascii=False, indent=1)
        structure_json = json.dumps(structure, ensure_ascii=False, indent=1)

        # П-1: контекст работ (при отказе продолжаем с деградацией)
        context: dict[str, Any] | None = None
        try:
            self.runlog.event("П-1: определение контекста работ")
            context = self._ask("П-1", "p1_context", CONTEXT_SCHEMA, structure_json=structure_json)
        except LinkError as exc:
            not_checked.append(
                f"П-1 (контекст работ) не выполнено: {exc.reason}. Проверка Р-3 велась "
                "по всем записям базы мер безопасности, выбор эталонов — без учёта систем."
            )

        systems = (context or {}).get("systems", [])
        work_types = (context or {}).get("work_types", [])
        critical_actions = (context or {}).get("critical_actions", [])

        # Подготовка заданий рубрик П-2…П-5
        tasks: list[tuple[str, str, dict, dict[str, str]]] = [
            ("П-2 (Р-1 последовательность)", "p2_sequence", FINDINGS_SCHEMA,
             {"structure_json": structure_json}),
            ("П-3 (Р-2 визуализируемость)", "p3_visualization", FINDINGS_SCHEMA,
             {"steps_json": steps_json}),
        ]

        selected_records = relevant_safety_records(safety_records, systems)
        if not safety_records:
            not_checked.append(
                "Р-3 (меры безопасности): проверка по базе мер не выполнялась — "
                "база не загружена или пуста."
            )
        else:
            if not selected_records:
                not_checked.append(
                    "Р-3 (меры безопасности): в базе нет записей по системам "
                    f"{', '.join(systems) or '—'}; проверка велась по всем записям базы."
                )
                selected_records = safety_records
            tasks.append(
                (
                    "П-4 (Р-3 меры безопасности)",
                    "p4_safety",
                    FINDINGS_SCHEMA,
                    {
                        "structure_json": structure_json,
                        "systems": ", ".join(systems) or "не определены",
                        "critical_actions_json": json.dumps(
                            critical_actions, ensure_ascii=False
                        ),
                        "safety_records_json": json.dumps(
                            [r.to_dict() for r in selected_records],
                            ensure_ascii=False,
                            indent=1,
                        ),
                    },
                )
            )

        chosen_etalons = select_relevant_etalons(etalons, systems, work_types)
        if not chosen_etalons:
            not_checked.append(
                "Стиль: проверка по эталонным картам не выполнялась — база эталонов пуста."
            )
        else:
            excerpts = "\n\n".join(
                f"=== Эталон: {e.title} (система: {e.system or 'не указана'}; "
                f"тип работ: {e.work_type or 'не указан'}) ===\n"
                + e.text[:_ETALON_EXCERPT_CHARS]
                for e in chosen_etalons
            )
            tasks.append(
                (
                    "П-5 (стиль)",
                    "p5_style",
                    FINDINGS_SCHEMA,
                    {"structure_json": structure_json, "etalons_text": excerpts},
                )
            )

        # Выполнение рубрик (параллельно — ТЗ, п. 5.3)
        raw_findings: list[dict[str, Any]] = []

        def _run_task(task: tuple[str, str, dict, dict[str, str]]) -> list[dict[str, Any]]:
            link, prompt_name, schema, variables = task
            self.runlog.event(f"{link}: запуск проверки")
            data = self._ask(link, prompt_name, schema, **variables)
            for f in data["findings"]:
                f["_source_link"] = link
            return data["findings"]

        if self.cfg.llm.parallel_rubrics and len(tasks) > 1:
            with ThreadPoolExecutor(max_workers=len(tasks)) as pool:
                futures = {pool.submit(_run_task, t): t for t in tasks}
                for future, task in futures.items():
                    try:
                        raw_findings.extend(future.result())
                    except LinkError as exc:
                        not_checked.append(f"{task[0]} не выполнено: {exc.reason}")
        else:
            for task in tasks:
                try:
                    raw_findings.extend(_run_task(task))
                except LinkError as exc:
                    not_checked.append(f"{task[0]} не выполнено: {exc.reason}")

        # Присваиваем идентификаторы исходным замечаниям
        indexed: dict[str, dict[str, Any]] = {}
        for i, f in enumerate(raw_findings, start=1):
            indexed[f"F{i}"] = f

        findings = self._aggregate(indexed, not_checked)
        return ChainResult(
            structure=structure, context=context, findings=findings, not_checked=not_checked
        )

    # ------------------------------------------------------------------
    def _aggregate(
        self, indexed: dict[str, dict[str, Any]], not_checked: list[str]
    ) -> list[Finding]:
        """П-6: дедупликация и нормализация критичности.

        Модель работает только с идентификаторами замечаний; цитата и привязка
        берутся из первого исходного замечания, поэтому через П-6 цитаты
        не проходят и не искажаются.
        """
        if not indexed:
            return []

        def _fallback() -> list[Finding]:
            return [
                Finding(
                    id=fid,
                    rubrics=[f["rubric"]],
                    severity=f["severity"],
                    step=f.get("step"),
                    quote=f.get("quote"),
                    quote_missing=bool(f.get("quote_missing")),
                    finding=f["finding"],
                    justification=f.get("justification"),
                    recommendation=f["recommendation"],
                    source_links=[f.get("_source_link", "")],
                )
                for fid, f in indexed.items()
            ]

        compact = [
            {
                "id": fid,
                "rubric": f["rubric"],
                "severity": f["severity"],
                "step": f.get("step"),
                "quote": f.get("quote"),
                "finding": f["finding"],
            }
            for fid, f in indexed.items()
        ]
        try:
            self.runlog.event("П-6: агрегация и дедупликация замечаний")
            data = self._ask(
                "П-6",
                "p6_aggregate",
                AGGREGATE_SCHEMA,
                findings_json=json.dumps(compact, ensure_ascii=False, indent=1),
            )
        except LinkError as exc:
            not_checked.append(
                f"П-6 (агрегация) не выполнено: {exc.reason}. Замечания приведены "
                "без дедупликации."
            )
            return _fallback()

        merged: list[Finding] = []
        used: set[str] = set()
        for i, item in enumerate(data["merged"], start=1):
            source_ids = [sid for sid in item["source_ids"] if sid in indexed]
            if not source_ids:
                continue
            used.update(source_ids)
            first = indexed[source_ids[0]]
            rubrics = sorted({indexed[sid]["rubric"] for sid in source_ids})
            merged.append(
                Finding(
                    id=f"M{i}",
                    rubrics=rubrics,
                    severity=item["severity"],
                    step=first.get("step"),
                    quote=first.get("quote"),
                    quote_missing=bool(first.get("quote_missing")),
                    finding=item["finding"],
                    justification=item.get("justification") or first.get("justification"),
                    recommendation=item["recommendation"],
                    source_links=[indexed[sid].get("_source_link", "") for sid in source_ids],
                )
            )
        # Замечания, потерянные моделью при агрегации, возвращаем как есть
        # (П-6 не имеет права «снимать» замечания — ТЗ, п. 5.1: полнота важнее точности).
        for fid, f in indexed.items():
            if fid in used:
                continue
            self.runlog.event(f"П-6: замечание {fid} не вошло в агрегацию — добавлено без изменений")
            merged.append(
                Finding(
                    id=fid,
                    rubrics=[f["rubric"]],
                    severity=f["severity"],
                    step=f.get("step"),
                    quote=f.get("quote"),
                    quote_missing=bool(f.get("quote_missing")),
                    finding=f["finding"],
                    justification=f.get("justification"),
                    recommendation=f["recommendation"],
                    source_links=[f.get("_source_link", "")],
                )
            )
        return merged
