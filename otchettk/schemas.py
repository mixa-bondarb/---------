"""JSON-схемы ответов звеньев цепи промптов (ТЗ, п. 5.3).

Каждое звено обязано вернуть ответ, проходящий валидацию по своей схеме;
иначе выполняется перезапрос (не более 2 повторов).
"""

from __future__ import annotations

RUBRICS = ["sequence", "visualization", "safety", "style"]
SEVERITIES = ["critical", "major", "minor", "recommendation"]

_NULLABLE_STR = {"type": ["string", "null"]}
_STR_ARRAY = {"type": "array", "items": {"type": "string"}}

# П-0: структуризация ТК
STRUCTURE_SCHEMA = {
    "type": "object",
    "required": ["title", "steps"],
    "properties": {
        "title": _NULLABLE_STR,
        "conditions": _NULLABLE_STR,
        "tools": _STR_ARRAY,
        "steps": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "required": ["num", "text"],
                "properties": {
                    "num": {"type": "string"},
                    "text": {"type": "string"},
                    "action_verb": _NULLABLE_STR,
                    "object": _NULLABLE_STR,
                    "location": _NULLABLE_STR,
                    "parameters": _NULLABLE_STR,
                    "doc_refs": _STR_ARRAY,
                },
            },
        },
        "control_marks": _STR_ARRAY,
    },
}

# П-1: определение контекста работ
CONTEXT_SCHEMA = {
    "type": "object",
    "required": ["systems"],
    "properties": {
        "systems": _STR_ARRAY,
        "work_types": _STR_ARRAY,
        "critical_actions": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["action"],
                "properties": {
                    "step": _NULLABLE_STR,
                    "action": {"type": "string"},
                    "hazard": _NULLABLE_STR,
                },
            },
        },
    },
}

# Единый формат замечания для звеньев П-2…П-5
_FINDING_SCHEMA = {
    "type": "object",
    "required": ["rubric", "severity", "quote_missing", "finding", "recommendation"],
    "properties": {
        "rubric": {"enum": RUBRICS},
        "severity": {"enum": SEVERITIES},
        "step": _NULLABLE_STR,
        "quote": _NULLABLE_STR,
        "quote_missing": {"type": "boolean"},
        "finding": {"type": "string"},
        "justification": _NULLABLE_STR,
        "recommendation": {"type": "string"},
    },
}

FINDINGS_SCHEMA = {
    "type": "object",
    "required": ["findings"],
    "properties": {"findings": {"type": "array", "items": _FINDING_SCHEMA}},
}

# П-6: агрегация и дедупликация. Модель оперирует идентификаторами исходных
# замечаний (source_ids) — цитаты через это звено не проходят и не искажаются.
AGGREGATE_SCHEMA = {
    "type": "object",
    "required": ["merged"],
    "properties": {
        "merged": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["source_ids", "severity", "finding", "recommendation"],
                "properties": {
                    "source_ids": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                    "severity": {"enum": SEVERITIES},
                    "finding": {"type": "string"},
                    "justification": _NULLABLE_STR,
                    "recommendation": {"type": "string"},
                },
            },
        }
    },
}

# П-Б: структуризация базы мер безопасности из неструктурированного документа
SAFETY_BASE_SCHEMA = {
    "type": "object",
    "required": ["records"],
    "properties": {
        "records": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "required": ["id", "systems", "text"],
                "properties": {
                    "id": {"type": "string"},
                    "systems": _STR_ARRAY,
                    "text": {"type": "string"},
                    "markers": _STR_ARRAY,
                },
            },
        }
    },
}
