"""Тесты генерации отчёта: сортировка, разделы, формат замечаний (ТЗ, п. 4.3)."""

from __future__ import annotations

from pathlib import Path

from otchettk.chain import Finding
from otchettk.report import build_report, verify_findings, write_reports


def _finding(fid, severity, quote, quote_missing=False, rubrics=None, step="1"):
    return Finding(
        id=fid,
        rubrics=rubrics or ["sequence"],
        severity=severity,
        step=step,
        quote=quote,
        quote_missing=quote_missing,
        finding=f"Замечание {fid}",
        justification="обоснование",
        recommendation="рекомендация",
    )


TK_TEXT = "1. Открыть лючок 12Л.\n2. Осмотреть жгуты.\n3. Закрыть лючок 12Л."


def test_sorting_and_sections(null_runlog, tmp_path):
    findings = [
        _finding("F1", "minor", "Осмотреть жгуты", step="2"),
        _finding("F2", "critical", None, quote_missing=True, rubrics=["safety"]),
        _finding("F3", "major", "Открыть лючок 12Л", step="1"),
    ]
    verified, rejected = verify_findings(findings, TK_TEXT, null_runlog)
    assert rejected == 0
    assert [v.finding.severity for v in verified] == ["critical", "major", "minor"]

    markdown, report_json = build_report(
        tk_path=Path("tk_test.docx"),
        tk_title="Тестовая работа",
        model_name="test-model",
        verified=verified,
        not_checked=["Стиль: база эталонов пуста."],
        rejected_count=rejected,
        run_dir=None,
    )
    # Обязательные разделы отчёта
    assert "## Сводка" in markdown
    assert "## Замечания" in markdown
    assert "## Не проверялось" in markdown
    assert "фрагмент отсутствует" in markdown  # замечание о пропуске
    assert "«Открыть лючок 12Л»" in markdown

    # JSON: обязательные поля каждого замечания (ТЗ, п. 4.3)
    f = report_json["findings"][0]
    for key in ("id", "rubrics", "severity", "location", "quote", "finding",
                "justification", "recommendation"):
        assert key in f
    assert f["id"] == "З-1"
    assert report_json["findings"][1]["location"]["char_offset"] is not None

    md_path, json_path = write_reports(tmp_path, "tk_test", markdown, report_json)
    assert md_path.exists() and json_path.exists()


def test_hallucinated_quote_rejected(null_runlog):
    findings = [
        _finding("F1", "major", "Этой фразы в карте нет"),
        _finding("F2", "minor", "Закрыть лючок 12Л", step="3"),
    ]
    verified, rejected = verify_findings(findings, TK_TEXT, null_runlog)
    assert rejected == 1
    assert len(verified) == 1
    assert verified[0].finding.id == "F2"


def test_empty_findings_report():
    markdown, report_json = build_report(
        tk_path=Path("tk.docx"),
        tk_title=None,
        model_name="m",
        verified=[],
        not_checked=[],
        rejected_count=0,
        run_dir=None,
    )
    assert "Замечания не выявлены." in markdown
    assert report_json["findings"] == []
