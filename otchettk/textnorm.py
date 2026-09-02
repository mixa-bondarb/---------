"""Нормализация текста и верификация цитат.

Верификация цитат — программная защита от галлюцинаций LLM (ТЗ, п. 4.3):
каждое замечание с цитатой проверяется на дословное присутствие цитаты в тексте ТК
(с точностью до пробелов, вида кавычек/тире и буквы «ё»).
"""

from __future__ import annotations

import re

_CHAR_MAP = str.maketrans(
    {
        "\u00ab": '"',  # «
        "\u00bb": '"',  # »
        "\u201c": '"',  # “
        "\u201d": '"',  # ”
        "\u201e": '"',  # „
        "\u2019": "'",
        "\u2018": "'",
        "\u2013": "-",  # –
        "\u2014": "-",  # —
        "\u2212": "-",  # −
        "\u00a0": " ",  # неразрывный пробел
        "ё": "е",
        "Ё": "Е",
    }
)

_WS_RE = re.compile(r"\s+")


def normalize(text: str) -> str:
    """Привести текст к канонической форме для сравнения цитат."""
    return _WS_RE.sub(" ", text.translate(_CHAR_MAP)).strip()


def find_quote(quote: str, document_text: str) -> int | None:
    """Найти дословную цитату в тексте документа.

    Возвращает смещение (в символах нормализованного текста документа)
    или None, если цитата в документе отсутствует.
    """
    nq = normalize(quote)
    if not nq:
        return None
    nd = normalize(document_text)
    pos = nd.find(nq)
    if pos >= 0:
        return pos
    pos = nd.casefold().find(nq.casefold())
    return pos if pos >= 0 else None
