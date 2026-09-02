"""Консольный интерфейс прототипа (ТЗ, п. 7): экспертиза <файл ТК> -> отчёт."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .chain import ExpertChain
from .config import load_config
from .kb import load_etalons, load_safety_base
from .llm import LinkError, LLMError, OpenAICompatibleProvider
from .parsing import load_document_text
from .prompts import PromptLibrary
from .report import build_report, verify_findings, write_reports
from .runlog import RunLog


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="otchettk",
        description=(
            "otchetTK — автоматизированная экспертиза технологических карт "
            "технического обслуживания авиационной техники (MVP). "
            "Вход: ТК в формате .pdf (с текстовым слоем) или .docx. "
            "Выход: отчёт с замечаниями (.md и .json)."
        ),
    )
    parser.add_argument("tk_file", help="путь к файлу технологической карты (.pdf/.docx)")
    parser.add_argument(
        "--config", default="config.yaml", help="путь к файлу конфигурации (YAML)"
    )
    parser.add_argument("--out", default=None, help="каталог для отчётов (переопределяет конфиг)")
    parser.add_argument(
        "--safety-base", default=None, help="каталог базы мер безопасности (переопределяет конфиг)"
    )
    parser.add_argument(
        "--etalons", default=None, help="каталог базы эталонных карт (переопределяет конфиг)"
    )
    parser.add_argument("--version", action="version", version=f"otchetTK {__version__}")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = make_parser().parse_args(argv)

    try:
        cfg = load_config(args.config)
    except FileNotFoundError as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 2
    if args.out:
        cfg.paths.reports_dir = Path(args.out)
    if args.safety_base:
        cfg.paths.safety_base_dir = Path(args.safety_base)
    if args.etalons:
        cfg.paths.etalons_dir = Path(args.etalons)

    tk_path = Path(args.tk_file)
    runlog = RunLog(cfg.paths.logs_dir)
    runlog.event(f"otchetTK v{__version__}: экспертиза документа {tk_path}")
    runlog.event(f"Модель: {cfg.llm.model} ({cfg.llm.base_url})")

    if not cfg.llm.api_key and "localhost" not in cfg.llm.base_url and "127.0.0.1" not in cfg.llm.base_url:
        print(
            f"Ошибка: не задан ключ API. Установите переменную окружения "
            f"{cfg.llm.api_key_env} (ключи не хранятся в репозитории — ТЗ, п. 6.1).",
            file=sys.stderr,
        )
        return 2

    try:
        tk_text = load_document_text(tk_path)
    except (FileNotFoundError, ValueError) as exc:
        print(f"Ошибка чтения ТК: {exc}", file=sys.stderr)
        return 2
    runlog.event(f"Текст ТК извлечён: {len(tk_text)} символов")

    provider = OpenAICompatibleProvider(cfg.llm, runlog=runlog)
    prompts = PromptLibrary(cfg.paths.prompts_dir)

    # Базы знаний
    safety_records, base_problems = load_safety_base(
        cfg=cfg, provider=provider, prompts=prompts, runlog=runlog
    )
    runlog.event(f"База мер безопасности: записей {len(safety_records)}")
    etalons = load_etalons(cfg.paths.etalons_dir)
    runlog.event(f"База эталонных карт: карт {len(etalons)}")

    chain = ExpertChain(provider=provider, prompts=prompts, cfg=cfg, runlog=runlog)
    try:
        result = chain.run(tk_text, safety_records, etalons)
    except (LinkError, LLMError) as exc:
        print(f"Экспертиза прервана: {exc}", file=sys.stderr)
        return 2
    result.not_checked.extend(base_problems)

    verified, rejected = verify_findings(result.findings, tk_text, runlog)
    if rejected:
        runlog.event(
            f"Верификация цитат: отброшено замечаний {rejected} (см. rejected_findings.jsonl)"
        )

    markdown, report_json = build_report(
        tk_path=tk_path,
        tk_title=result.structure.get("title"),
        model_name=f"{cfg.llm.model} ({cfg.llm.base_url})",
        verified=verified,
        not_checked=result.not_checked,
        rejected_count=rejected,
        run_dir=runlog.dir,
    )
    md_path, json_path = write_reports(cfg.paths.reports_dir, tk_path.stem, markdown, report_json)

    counts = report_json["summary"]
    totals = {s: sum(row.get(s, 0) for row in counts.values()) for s in
              ("critical", "major", "minor", "recommendation")}
    print()
    print(f"Экспертиза завершена: замечаний {len(verified)} "
          f"(критических {totals['critical']}, значительных {totals['major']}, "
          f"незначительных {totals['minor']}, рекомендаций {totals['recommendation']}).")
    print(f"Отчёт (md):   {md_path}")
    print(f"Отчёт (json): {json_path}")
    print(f"Журнал:       {runlog.dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
