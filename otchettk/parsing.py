"""Извлечение текста из входных документов (ТЗ, пп. 3.1–3.3).

Форматы MVP: неструктурированный .pdf (с текстовым слоем) и .docx.
Дополнительно принимаются .txt и .md (удобно для отладки и тестов).
Формирование структуры из извлечённого текста выполняет звено П-0 цепи промптов.
"""

from __future__ import annotations

from pathlib import Path

SUPPORTED_EXTENSIONS = (".pdf", ".docx", ".txt", ".md")


def _docx_text(path: Path) -> str:
    from docx import Document

    doc = Document(str(path))
    parts: list[str] = []
    # Обходим тело документа по порядку, чтобы абзацы и таблицы
    # не перемешивались (важно для верификации цитат по смещению).
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    for child in doc.element.body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            text = Paragraph(child, doc).text
            if text.strip():
                parts.append(text)
        elif tag == "tbl":
            table = Table(child, doc)
            for row in table.rows:
                cells = [c.text.strip() for c in row.cells]
                line = " | ".join(c for c in cells if c)
                if line:
                    parts.append(line)
    return "\n".join(parts)


def _pdf_text(path: Path) -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    pages = [(page.extract_text() or "") for page in reader.pages]
    text = "\n".join(pages).strip()
    if not text:
        raise ValueError(
            f"Из PDF не извлечён текст: {path.name}. Вероятно, документ является сканом "
            "без текстового слоя; распознавание (OCR) в MVP не входит (ТЗ, раздел 9)."
        )
    return text


def load_document_text(path: str | Path) -> str:
    """Извлечь текст документа. Поддерживаются .pdf, .docx, .txt, .md."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Файл не найден: {p}")
    ext = p.suffix.lower()
    if ext == ".docx":
        return _docx_text(p)
    if ext == ".pdf":
        return _pdf_text(p)
    if ext in (".txt", ".md"):
        return p.read_text(encoding="utf-8")
    raise ValueError(
        f"Неподдерживаемый формат: {ext}. Поддерживаются: {', '.join(SUPPORTED_EXTENSIONS)}"
    )
