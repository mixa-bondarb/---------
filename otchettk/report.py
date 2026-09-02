"""Верификация цитат и генерация отчёта (ТЗ, п. 4.3).

Отчёт формируется в двух форматах: человекочитаемый .md и машиночитаемый .json.
Перед включением в отчёт каждая цитата программно проверяется на дословное
присутствие в тексте ТК; замечания с несуществующей цитатой отбрасываются
с записью в журнал (защита от галлюцинаций).
"""

from __future__ import annotations

import datetime as _dt
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import __version__
from .chain import Finding
from .textnorm import find_quote

SEVERITY_ORDER = {"critical": 0, "major": 1, "minor": 2, "recommendation": 3}
SEVERITY_NAMES = {
    "critical": "критическое",
    "major": "значительное",
    "minor": "незначительное",
    "recommendation": "рекомендация",
}
RUBRIC_NAMES = {
    "sequence": "Р-1 Последовательность",
    "visualization": "Р-2 Визуализируемость",
    "safety": "Р-3 Меры безопасности",
    "style": "Стиль изложения",
}


@dataclass
class VerifiedFinding:
    finding: Finding
    char_offset: int | None


def verify_findings(
    findings: list[Finding], tk_text: str, runlog
) -> tuple[list[VerifiedFinding], int]:
    """Верифицировать цитаты; вернуть (подтверждённые замечания, число отброшенных)."""
    verified: list[VerifiedFinding] = []
    rejected = 0
    for f in findings:
        if f.quote_missing or not (f.quote and f.quote.strip()):
            # Замечание об отсутствующем фрагменте: цитата не требуется (ТЗ, п. 4.3).
            f.quote = None
            f.quote_missing = True
            verified.append(VerifiedFinding(finding=f, char_offset=None))
            continue
        offset = find_quote(f.quote, tk_text)
        if offset is None:
            rejected += 1
            runlog.rejected_finding(
                f.to_dict(), reason="цитата не найдена в тексте ТК (возможная галлюцинация)"
            )
        else:
            verified.append(VerifiedFinding(finding=f, char_offset=offset))
    verified.sort(
        key=lambda v: (
            SEVERITY_ORDER.get(v.finding.severity, 99),
            v.char_offset if v.char_offset is not None else 10**9,
        )
    )
    return verified, rejected


def _summary(verified: list[VerifiedFinding]) -> dict[str, dict[str, int]]:
    summary: dict[str, dict[str, int]] = {}
    for v in verified:
        primary = v.finding.rubrics[0] if v.finding.rubrics else "style"
        row = summary.setdefault(primary, {s: 0 for s in SEVERITY_ORDER})
        row[v.finding.severity] = row.get(v.finding.severity, 0) + 1
    return summary


def build_report(
    *,
    tk_path: Path,
    tk_title: str | None,
    model_name: str,
    verified: list[VerifiedFinding],
    not_checked: list[str],
    rejected_count: int,
    run_dir: Path | None,
) -> tuple[str, dict[str, Any]]:
    """Собрать отчёт; вернуть (markdown, json-объект)."""
    now = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    summary = _summary(verified)

    # ------------------------- JSON -------------------------
    json_findings = []
    for i, v in enumerate(verified, start=1):
        f = v.finding
        json_findings.append(
            {
                "id": f"З-{i}",
                "rubrics": f.rubrics,
                "severity": f.severity,
                "location": {"step": f.step, "char_offset": v.char_offset},
                "quote": f.quote if not f.quote_missing else None,
                "quote_missing": f.quote_missing,
                "finding": f.finding,
                "justification": f.justification,
                "recommendation": f.recommendation,
            }
        )
    report_json: dict[str, Any] = {
        "document": str(tk_path),
        "document_title": tk_title,
        "generated_at": now,
        "prototype": {"name": "otchetTK", "version": __version__},
        "model": model_name,
        "summary": summary,
        "findings": json_findings,
        "not_checked": not_checked,
        "rejected_findings_count": rejected_count,
        "run_log_dir": str(run_dir) if run_dir else None,
    }

    # ------------------------- Markdown -------------------------
    lines: list[str] = []
    lines.append("# Отчёт экспертизы технологической карты")
    lines.append("")
    lines.append(f"- **Документ:** {tk_path.name}")
    if tk_title:
        lines.append(f"- **Наименование работы:** {tk_title}")
    lines.append(f"- **Дата экспертизы:** {now}")
    lines.append(f"- **Прототип:** otchetTK v{__version__}")
    lines.append(f"- **Модель:** {model_name}")
    lines.append("")
    lines.append(
        "> Отчёт сформирован автоматически и является перечнем замечаний для "
        "эксперта-человека. Окончательное решение по каждому замечанию принимает эксперт."
    )
    lines.append("")
    lines.append("## Сводка")
    lines.append("")
    lines.append("| Рубрика | Критические | Значительные | Незначительные | Рекомендации |")
    lines.append("|---|---|---|---|---|")
    total = {s: 0 for s in SEVERITY_ORDER}
    for rubric in ("sequence", "visualization", "safety", "style"):
        row = summary.get(rubric)
        if row is None:
            continue
        for s in SEVERITY_ORDER:
            total[s] += row.get(s, 0)
        lines.append(
            f"| {RUBRIC_NAMES[rubric]} | {row.get('critical', 0)} | {row.get('major', 0)} "
            f"| {row.get('minor', 0)} | {row.get('recommendation', 0)} |"
        )
    lines.append(
        f"| **Итого** | **{total['critical']}** | **{total['major']}** "
        f"| **{total['minor']}** | **{total['recommendation']}** |"
    )
    lines.append("")

    lines.append("## Замечания")
    lines.append("")
    if not verified:
        lines.append("Замечания не выявлены.")
        lines.append("")
    for i, v in enumerate(verified, start=1):
        f = v.finding
        rubric_names = ", ".join(RUBRIC_NAMES.get(r, r) for r in f.rubrics)
        lines.append(
            f"### З-{i}. [{SEVERITY_NAMES.get(f.severity, f.severity)}] {rubric_names}"
        )
        lines.append("")
        location = f"пункт/шаг: {f.step}" if f.step else "пункт/шаг: не привязан"
        if v.char_offset is not None:
            location += f"; позиция в документе: символ {v.char_offset}"
        lines.append(f"- **Расположение:** {location}")
        if f.quote_missing:
            lines.append("- **Цитата:** фрагмент отсутствует (замечание о пропуске)")
        else:
            lines.append(f"- **Цитата:** «{f.quote}»")
        lines.append(f"- **Замечание:** {f.finding}")
        if f.justification:
            lines.append(f"- **Обоснование:** {f.justification}")
        lines.append(f"- **Рекомендация:** {f.recommendation}")
        lines.append("")

    lines.append("## Не проверялось")
    lines.append("")
    if not_checked:
        for item in not_checked:
            lines.append(f"- {item}")
    else:
        lines.append("- Все проверки рубрикатора выполнены в полном объёме.")
    lines.append("")
    lines.append(
        "Отсутствие замечаний по рубрике не является подтверждением качества, "
        "если рубрика указана в разделе «Не проверялось»."
    )
    lines.append("")

    lines.append("## Служебная информация")
    lines.append("")
    lines.append(
        f"- Замечаний отброшено верификацией цитат (возможные галлюцинации): {rejected_count}"
    )
    if run_dir:
        lines.append(f"- Журнал запуска: {run_dir}")
    lines.append("")

    return "\n".join(lines), report_json


def write_reports(
    out_dir: Path, base_name: str, markdown: str, report_json: dict[str, Any]
) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    md_path = out_dir / f"otchet_{base_name}_{stamp}.md"
    json_path = out_dir / f"otchet_{base_name}_{stamp}.json"
    md_path.write_text(markdown, encoding="utf-8")
    json_path.write_text(
        json.dumps(report_json, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return md_path, json_path
