"""Тесты баз знаний: структуризация базы мер (П-Б) с кэшем, отбор записей и эталонов."""

from __future__ import annotations

import json
from pathlib import Path

from conftest import FakeProvider

from otchettk.kb import (
    Etalon,
    load_etalons,
    load_safety_base,
    relevant_safety_records,
    select_relevant_etalons,
    SafetyRecord,
)
from otchettk.prompts import PromptLibrary

PB_RESPONSE = json.dumps(
    {
        "records": [
            {"id": "РЭ п. 2.1", "systems": ["электросистема"],
             "text": "Обесточить ВС перед работами.", "markers": ["обесточить"]},
            {"id": "РЭ п. 2.4", "systems": ["гидросистема"],
             "text": "Стравить давление перед разгерметизацией.",
             "markers": ["стравить давление"]},
            {"id": "РЭ п. 2.10", "systems": ["общие работы"],
             "text": "Зашвартовать ВС, поставить колодки.",
             "markers": ["зашвартовать", "поставить колодки"]},
        ]
    },
    ensure_ascii=False,
)


def test_safety_base_load_with_cache(app_config, null_runlog):
    base_dir = app_config.paths.safety_base_dir
    base_dir.mkdir(parents=True)
    (base_dir / "re_mery.txt").write_text("2.1 ... 2.4 ... 2.10 ...", encoding="utf-8")

    provider = FakeProvider({"П-Б": PB_RESPONSE})
    prompts = PromptLibrary(app_config.paths.prompts_dir)

    records, problems = load_safety_base(
        cfg=app_config, provider=provider, prompts=prompts, runlog=null_runlog
    )
    assert not problems
    assert len(records) == 3
    assert records[0].markers == ["обесточить"]
    first_call_count = len(provider.calls)
    assert first_call_count == 1

    # Повторная загрузка — из кэша, без обращений к LLM (ТЗ, п. 3.2: пополняемая база)
    records2, _ = load_safety_base(
        cfg=app_config, provider=provider, prompts=prompts, runlog=null_runlog
    )
    assert len(records2) == 3
    assert len(provider.calls) == first_call_count


def test_safety_base_empty_dir(app_config, null_runlog):
    app_config.paths.safety_base_dir.mkdir(parents=True)
    provider = FakeProvider({})
    prompts = PromptLibrary(app_config.paths.prompts_dir)
    records, problems = load_safety_base(
        cfg=app_config, provider=provider, prompts=prompts, runlog=null_runlog
    )
    assert records == []
    assert problems and "пуста" in problems[0]


def test_relevant_records_filter():
    records = [
        SafetyRecord(id="2.1", systems=["электросистема"], text="", markers=[]),
        SafetyRecord(id="2.4", systems=["гидросистема"], text="", markers=[]),
        SafetyRecord(id="2.10", systems=["общие работы"], text="", markers=[]),
    ]
    selected = relevant_safety_records(records, ["Электросистема"])
    ids = {r.id for r in selected}
    assert ids == {"2.1", "2.10"}  # своя система + общие меры

    # Без определённых систем — все записи
    assert len(relevant_safety_records(records, [])) == 3


def test_etalon_selection_by_metadata():
    etalons = [
        Etalon(path=None, text="", title="Э-101", work_type="осмотр", system="электросистема"),
        Etalon(path=None, text="", title="Э-102", work_type="проверка", system="гидросистема"),
    ]
    chosen = select_relevant_etalons(etalons, ["гидросистема"], ["проверка"], max_count=1)
    assert chosen[0].title == "Э-102"


def test_load_etalons_from_repo_data(repo_root):
    etalons = load_etalons(repo_root / "data" / "etalons")
    assert len(etalons) >= 2
    by_system = {e.system for e in etalons}
    assert "электросистема" in by_system and "гидросистема" in by_system
    assert all(e.text for e in etalons)
