from otchettk.textnorm import find_quote, normalize


def test_normalize_collapses_whitespace_and_chars():
    assert normalize("Открыть  лючок\n12Л — осмотреть") == 'Открыть лючок 12Л - осмотреть'
    assert normalize("«АККУМ.»") == '"АККУМ."'
    assert normalize("ёмкость Ёж") == "емкость Еж"


def test_find_quote_exact():
    doc = "1. Открыть лючок 12Л.\n2. Осмотреть жгуты."
    assert find_quote("Открыть лючок 12Л", doc) is not None


def test_find_quote_tolerates_formatting():
    # PDF-извлечение даёт двойные пробелы и другие кавычки/тире
    doc = "Выключатель  «НАСОС»  —  в  положении  ОТКЛ."
    assert find_quote('Выключатель "НАСОС" - в положении ОТКЛ.', doc) is not None


def test_find_quote_rejects_absent():
    doc = "1. Открыть лючок 12Л."
    assert find_quote("Стравить давление в гидросистеме", doc) is None


def test_find_quote_empty():
    assert find_quote("", "текст") is None
    assert find_quote("   ", "текст") is None
