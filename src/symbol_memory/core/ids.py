"""Validation and sorting helpers for string-based symbol ids."""

from __future__ import annotations

import re

_SYMBOL_ID_PATTERN = re.compile(r"(0|[1-9]\d*)(\.(0|[1-9]\d*))*$")


def validate_symbol_id(value: str) -> str:
    """Validate a symbol id and return its canonical string form."""

    if not isinstance(value, str):
        raise ValueError("Symbol id must be a string literal like '1' or '1.2'")
    if not value:
        raise ValueError("Symbol id must be a non-empty string literal")
    if value != value.strip():
        raise ValueError("Symbol id must not include surrounding whitespace")
    if not _SYMBOL_ID_PATTERN.fullmatch(value):
        raise ValueError("Symbol id must use numeric dot-separated segments like '1' or '1.2'")
    return value


def parse_symbol_id(value: str) -> tuple[int, ...]:
    """Parse a validated symbol id into numeric segments for sorting."""

    return tuple(int(segment) for segment in validate_symbol_id(value).split("."))


def symbol_id_sort_key(value: str) -> tuple[int, ...]:
    """Stable sort key that orders ids by numeric segments."""

    return parse_symbol_id(value)


def parent_symbol_id(value: str) -> str | None:
    """Return the direct parent id for a hierarchy id, if any."""

    parts = validate_symbol_id(value).split(".")
    if len(parts) == 1:
        return None
    return ".".join(parts[:-1])


def is_descendant_id(base: str, candidate: str) -> bool:
    """Return whether candidate is a descendant of base in the id hierarchy."""

    base_id = validate_symbol_id(base)
    candidate_id = validate_symbol_id(candidate)
    return candidate_id.startswith(f"{base_id}.")
