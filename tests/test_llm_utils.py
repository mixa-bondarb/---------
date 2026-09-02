"""Тесты извлечения JSON из ответов модели и библиотеки промптов."""

from __future__ import annotations

import pytest

from otchettk.llm import extract_json
from otchettk.prompts import PromptLibrary


def test_extract_plain_json():
    assert extract_json('{"a": 1}') == {"a": 1}


def test_extract_fenced_json():
    text = 'Вот ответ:\n```json\n{"findings": []}\n```\nконец'
    assert extract_json(text) == {"findings": []}


def test_extract_json_with_prefix_text():
    text = 'Результат анализа: {"systems": ["электросистема"]} — готово.'
    assert extract_json(text) == {"systems": ["электросистема"]}


def test_extract_json_failure():
    with pytest.raises(ValueError):
        extract_json("никакого JSON здесь нет")


def test_prompt_render(repo_root):
    lib = PromptLibrary(repo_root / "prompts")
    rendered = lib.render("p0_structure", tk_text="ТЕКСТ_КАРТЫ")
    assert "ТЕКСТ_КАРТЫ" in rendered
    assert "{{" not in rendered


def test_prompt_missing_variable(repo_root):
    lib = PromptLibrary(repo_root / "prompts")
    with pytest.raises(KeyError):
        lib.render("p0_structure")


def test_all_prompt_templates_exist(repo_root):
    names = [
        "p0_structure", "p1_context", "p2_sequence", "p3_visualization",
        "p4_safety", "p5_style", "p6_aggregate", "pb_safety_base",
    ]
    for name in names:
        assert (repo_root / "prompts" / f"{name}.md").exists(), name
