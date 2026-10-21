"""Pure validation helpers for report word-count settings and content.

The term *word count* follows the application's historical character-count
convention: count every Unicode code point except characters for which
``str.isspace()`` is true. No tokenization, language-specific segmentation, or
Markdown stripping is performed.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

DEFAULT_MIN_WORDS = 1
DEFAULT_MAX_WORDS = 1000
MAX_REPORT_WORDS = 10000


def validate_report_settings(report_settings: Any = None) -> dict[str, int]:
    """Validate and normalize ``minWords``/``maxWords`` report settings.

    Missing settings preserve the legacy generation range of 1..1000.
    Returns a fresh mapping with canonical camel-case keys. Invalid types,
    out-of-range bounds and inverted ranges raise ``ValueError``.
    """
    if report_settings is None:
        report_settings = {}
    if not isinstance(report_settings, Mapping):
        raise ValueError("reportSettings must be an object")

    def read_bound(key: str, default: int) -> int:
        value = report_settings.get(key, default)
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"reportSettings.{key} must be an integer")
        if value < 1:
            raise ValueError(f"reportSettings.{key} must be at least 1")
        if value > MAX_REPORT_WORDS:
            raise ValueError(f"reportSettings.{key} must not exceed {MAX_REPORT_WORDS}")
        return value

    minimum = read_bound("minWords", DEFAULT_MIN_WORDS)
    maximum = read_bound("maxWords", DEFAULT_MAX_WORDS)
    if maximum < minimum:
        raise ValueError("reportSettings.maxWords must be greater than or equal to minWords")
    return {"minWords": minimum, "maxWords": maximum}


def report_generation_range(report_settings: Any = None) -> tuple[int, int]:
    """Return the validated inclusive ``(minWords, maxWords)`` prompt range."""
    normalized = validate_report_settings(report_settings)
    return normalized["minWords"], normalized["maxWords"]


def report_word_count(content: str) -> int:
    """Count non-whitespace Unicode characters in report content."""
    if not isinstance(content, str):
        raise ValueError("report content must be a string")
    return sum(not character.isspace() for character in content)


def validate_report_content(
    content: str,
    settings: Any = None,
    *,
    reportSettings: Any = None,
) -> int:
    """Check content against settings and return its measured word count.

    The preferred keyword is ``settings``; ``reportSettings`` is also accepted
    as a camel-case alias for API/config callers. If omitted, legacy defaults
    (1..1000) apply. A ``ValueError`` is raised when the content is outside the
    inclusive range, allowing callers to stop before any remote submission.
    """
    if settings is not None and reportSettings is not None:
        raise ValueError("pass either settings or reportSettings, not both")
    selected_settings = reportSettings if reportSettings is not None else settings
    bounds = validate_report_settings(selected_settings)
    count = report_word_count(content)
    if count < bounds["minWords"] or count > bounds["maxWords"]:
        raise ValueError(
            f"report content word count {count} is outside the allowed range "
            f"{bounds['minWords']}..{bounds['maxWords']}"
        )
    return count
