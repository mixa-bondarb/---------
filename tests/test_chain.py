"""Тесты механики цепи промптов на фиктивном провайдере (без внешних API)."""

from __future__ import annotations

import json

from conftest import FakeProvider

from otchettk.chain import ExpertChain
from otchettk.kb import Etalon, SafetyRecord
from otchettk.prompts import PromptLibrary
from otchettk.report import verify_findings

TK_TEXT = (
    "1. Открыть лючок 14П.\n"
    "2. Снять реле К5 с колодки.\n"
    "3. Установить его на место."
)

STRUCTURE_RESPONSE = json.dumps(
    {
        "title": "Замена реле К5",
        "conditions": None,
        "tools": [],
        "steps": [
            {"num": "1", "text": "Открыть лючок 14П.", "action_verb": "открыть",
             "object": "лючок 14П", "location": None, "parameters": None, "doc_refs": []},
            {"num": "2", "text": "Снять реле К5 с колодки.", "action_verb": "снять",
             "object": "реле К5", "location": None, "parameters": None, "doc_refs": []},
            {"num": "3", "text": "Установить его на место.", "action_verb": "установить",
             "object": None, "location": None, "parameters": None, "doc_refs": []},
        ],
        "control_marks": [],
    },
    ensure_ascii=False,
)

CONTEXT_RESPONSE = json.dumps(
    {
        "systems": ["электросистема"],
        "work_types": ["замена"],
        "critical_actions": [
            {"step": "2", "action": "снятие реле", "hazard": "работа под напряжением"}
        ],
    },
    ensure_ascii=False,
)

SEQUENCE_RESPONSE = json.dumps(
    {"findings": [{"rubric": "sequence", "severity": "major", "step": "1",
                   "quote": None, "quote_missing": True,
                   "finding": "Лючок 14П открыт и не закрыт",
                   "justification": "правило парных операций",
                   "recommendation": "Добавить операцию закрытия лючка 14П"}]},
    ensure_ascii=False,
)

VISUALIZATION_RESPONSE = json.dumps(
    {"findings": [{"rubric": "visualization", "severity": "major", "step": "3",
                   "quote": "Установить его на место.", "quote_missing": False,
                   "finding": "Неопределённое местоимение «его»",
                   "justification": "критерий 5 рубрики Р-2",
                   "recommendation": "Назвать устанавливаемый объект явно"}]},
    ensure_ascii=False,
)

SAFETY_RESPONSE = json.dumps(
    {"findings": [{"rubric": "safety", "severity": "critical", "step": "2",
                   "quote": None, "quote_missing": True,
                   "finding": "Отсутствует ключевой маркер «обесточить»",
                   "justification": "РЭ п. 2.1",
                   "recommendation": "Добавить операцию обесточивания до п. 2"}]},
    ensure_ascii=False,
)

# Стилевое замечание с несуществующей цитатой — проверка защиты от галлюцинаций
STYLE_RESPONSE = json.dumps(
    {"findings": [{"rubric": "style", "severity": "minor", "step": "1",
                   "quote": "Несуществующая цитата из карты", "quote_missing": False,
                   "finding": "Стилевое отклонение", "justification": "эталон Э-101",
                   "recommendation": "Оформить как в эталоне"}]},
    ensure_ascii=False,
)

AGGREGATE_RESPONSE = json.dumps(
    {"merged": [
        {"source_ids": ["F3", "F1"], "severity": "critical",
         "finding": "Работы в РК-2 без обесточивания; лючок 14П не закрыт",
         "justification": "РЭ п. 2.1", "recommendation": "Добавить обесточивание и закрытие лючка"},
        {"source_ids": ["F2"], "severity": "major",
         "finding": "Неопределённое местоимение", "justification": None,
         "recommendation": "Назвать объект явно"},
        {"source_ids": ["F4"], "severity": "minor",
         "finding": "Стилевое отклонение", "justification": None,
         "recommendation": "Оформить как в эталоне"},
    ]},
    ensure_ascii=False,
)

SAFETY_RECORDS = [
    SafetyRecord(id="РЭ п. 2.1", systems=["электросистема"],
                 text="Перед работами обесточить ВС.", markers=["обесточить"]),
    SafetyRecord(id="РЭ п. 2.10", systems=["общие работы"],
                 text="Зашвартовать ВС, поставить колодки.",
                 markers=["зашвартовать", "поставить колодки"]),
]

ETALONS = [
    Etalon(path=None, text="Эталонный текст", title="Э-101",
           work_type="замена", system="электросистема"),
]


def _make_chain(app_config, null_runlog, responses):
    provider = FakeProvider(responses)
    prompts = PromptLibrary(app_config.paths.prompts_dir)
    chain = ExpertChain(provider=provider, prompts=prompts, cfg=app_config, runlog=null_runlog)
    return chain, provider


def test_full_chain_with_retry_dedup_and_verification(app_config, null_runlog):
    responses = {
        "П-0": STRUCTURE_RESPONSE,
        # Первый ответ П-1 не проходит валидацию схемы -> перезапрос (ТЗ, п. 5.3)
        "П-1": ['{"нет_поля_systems": true}', CONTEXT_RESPONSE],
        "П-2": SEQUENCE_RESPONSE,
        "П-3": VISUALIZATION_RESPONSE,
        "П-4": SAFETY_RESPONSE,
        "П-5": STYLE_RESPONSE,
        "П-6": AGGREGATE_RESPONSE,
    }
    chain, provider = _make_chain(app_config, null_runlog, responses)
    result = chain.run(TK_TEXT, SAFETY_RECORDS, ETALONS)

    # Повтор П-1 состоялся
    p1_calls = [c for c in provider.calls if c[0] == "П-1"]
    assert p1_calls == [("П-1", 1), ("П-1", 2)]

    # Агрегация: три замечания, у объединённого — обе рубрики
    assert len(result.findings) == 3
    merged = result.findings[0]
    assert sorted(merged.rubrics) == ["safety", "sequence"]
    assert merged.severity == "critical"

    # Верификация цитат: стилевое замечание с выдуманной цитатой отброшено
    verified, rejected = verify_findings(result.findings, TK_TEXT, null_runlog)
    assert rejected == 1
    assert len(verified) == 2
    assert null_runlog.rejected[0]["reason"].startswith("цитата не найдена")

    # Сортировка по критичности: critical первым
    assert verified[0].finding.severity == "critical"

    # Замечание с существующей цитатой имеет привязку к позиции
    with_quote = [v for v in verified if not v.finding.quote_missing]
    assert with_quote and with_quote[0].char_offset is not None


def test_link_failure_goes_to_not_checked(app_config, null_runlog):
    responses = {
        "П-0": STRUCTURE_RESPONSE,
        "П-1": CONTEXT_RESPONSE,
        "П-2": SEQUENCE_RESPONSE,
        "П-3": VISUALIZATION_RESPONSE,
        "П-4": SAFETY_RESPONSE,
        "П-5": "это не JSON и после повторов тоже не JSON",
        "П-6": json.dumps({"merged": [
            {"source_ids": ["F1"], "severity": "major", "finding": "ф1",
             "justification": None, "recommendation": "р1"},
            {"source_ids": ["F2"], "severity": "major", "finding": "ф2",
             "justification": None, "recommendation": "р2"},
            {"source_ids": ["F3"], "severity": "critical", "finding": "ф3",
             "justification": None, "recommendation": "р3"},
        ]}, ensure_ascii=False),
    }
    chain, provider = _make_chain(app_config, null_runlog, responses)
    result = chain.run(TK_TEXT, SAFETY_RECORDS, ETALONS)

    # П-5 вызывалось 1 + 2 повтора (ТЗ, п. 5.3), затем зафиксировано в «Не проверялось»
    p5_calls = [c for c in provider.calls if c[0].startswith("П-5")]
    assert len(p5_calls) == 3
    assert any("П-5" in item for item in result.not_checked)
    assert len(result.findings) == 3


def test_aggregation_failure_falls_back_to_raw(app_config, null_runlog):
    responses = {
        "П-0": STRUCTURE_RESPONSE,
        "П-1": CONTEXT_RESPONSE,
        "П-2": SEQUENCE_RESPONSE,
        "П-3": VISUALIZATION_RESPONSE,
        "П-4": SAFETY_RESPONSE,
        "П-5": STYLE_RESPONSE,
        "П-6": "не JSON",
    }
    chain, _ = _make_chain(app_config, null_runlog, responses)
    result = chain.run(TK_TEXT, SAFETY_RECORDS, ETALONS)
    assert any("П-6" in item for item in result.not_checked)
    assert len(result.findings) == 4  # без дедупликации


def test_aggregation_cannot_drop_findings(app_config, null_runlog):
    """П-6 «потеряло» замечания — они возвращаются в отчёт без изменений."""
    only_f1 = json.dumps({"merged": [
        {"source_ids": ["F1"], "severity": "major", "finding": "только ф1",
         "justification": None, "recommendation": "р1"},
    ]}, ensure_ascii=False)
    responses = {
        "П-0": STRUCTURE_RESPONSE,
        "П-1": CONTEXT_RESPONSE,
        "П-2": SEQUENCE_RESPONSE,
        "П-3": VISUALIZATION_RESPONSE,
        "П-4": SAFETY_RESPONSE,
        "П-5": STYLE_RESPONSE,
        "П-6": only_f1,
    }
    chain, _ = _make_chain(app_config, null_runlog, responses)
    result = chain.run(TK_TEXT, SAFETY_RECORDS, ETALONS)
    assert len(result.findings) == 4  # 1 объединённое + 3 возвращённых
    severities = {f.severity for f in result.findings}
    assert "critical" in severities  # критическое замечание Р-3 не потеряно
