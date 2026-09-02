from pathlib import Path

import pytest

from otchettk.parsing import load_document_text
from otchettk.textnorm import find_quote

DATA = Path(__file__).resolve().parent.parent / "data"


def test_docx_extraction():
    text = load_document_text(DATA / "test_cards" / "tk_101_correct.docx")
    assert "ТЕХНОЛОГИЧЕСКАЯ КАРТА № 101" in text
    assert "Закрыть лючок 12Л" in text


def test_pdf_extraction_with_quote_verification():
    text = load_document_text(DATA / "test_cards" / "tk_103_defects.pdf")
    assert "ТЕХНОЛОГИЧЕСКАЯ КАРТА № 103" in text
    # Верификация цитат должна работать на PDF-извлечении (лишние пробелы и пр.)
    assert find_quote(
        "Обеспечить доступ к фильтру тонкой очистки основной гидросистемы", text
    ) is not None


def test_safety_base_docx():
    text = load_document_text(DATA / "safety_base" / "re_razdel2_mery.docx")
    assert "2.4. Гидросистема" in text
    assert "стравить давление" in text


def test_unsupported_format(tmp_path):
    bad = tmp_path / "tk.rtf"
    bad.write_text("x")
    with pytest.raises(ValueError):
        load_document_text(bad)


def test_missing_file():
    with pytest.raises(FileNotFoundError):
        load_document_text(DATA / "нет_такого_файла.docx")
