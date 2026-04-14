"""CLI output formatting helpers."""

from __future__ import annotations

import json

from symbol_memory.core.ids import parse_symbol_id
from symbol_memory.core.models import RelationPreview, SymbolRecord, ValidationReport


def format_report(report: ValidationReport) -> str:
    lines = [
        f"status: {report.status}",
        f"errors: {report.error_count}",
        f"warnings: {report.warning_count}",
    ]
    for issue in report.issues:
        location = ""
        if issue.file_path:
            location = issue.file_path
            if issue.line is not None:
                location = f"{location}:{issue.line}"
        prefix = f"{issue.severity} {issue.code}"
        if issue.stage:
            prefix = f"{prefix} [{issue.stage}]"
        if location:
            prefix = f"{prefix} {location}"
        lines.append(f"{prefix} {issue.message}")
        if issue.hint:
            lines.append(f"hint: {issue.hint}")
    return "\n".join(lines)


def format_find_result(result: SymbolRecord | list[SymbolRecord]) -> str:
    if isinstance(result, SymbolRecord):
        return json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2)
    payload = [item.model_dump(mode="json") for item in result]
    return json.dumps(payload, ensure_ascii=False, indent=2)


def format_relations(relations: list[RelationPreview]) -> str:
    if not relations:
        return "[]"
    lines = []
    for relation in relations:
        if relation.resolved:
            lines.append(
                f"{relation.id} -> {relation.name} -> "
                f"{relation.file_path}:{relation.start_line}-{relation.end_line}"
            )
        else:
            lines.append(f"{relation.id} -> unresolved")
    return "\n".join(lines)


def format_symbol_list(symbols: list[SymbolRecord]) -> str:
    if not symbols:
        return "[]"
    return "\n".join(format_symbol_line(symbol) for symbol in symbols)


def format_symbol_line(symbol: SymbolRecord) -> str:
    return f"{symbol.id} {symbol.symbol_type} {symbol.qualified_name}"


def format_branch_tree(symbols: list[SymbolRecord]) -> str:
    if not symbols:
        return "[]"
    root_depth = len(parse_symbol_id(symbols[0].id))
    lines = []
    for symbol in symbols:
        depth = len(parse_symbol_id(symbol.id)) - root_depth
        indent = "  " * depth
        lines.append(f"{indent}- {format_symbol_line(symbol)}")
    return "\n".join(lines)


def format_parent(symbol: SymbolRecord | None) -> str:
    if symbol is None:
        return "none"
    return format_symbol_line(symbol)


def format_cli_error(error: Exception) -> str:
    message = error.args[0] if getattr(error, "args", None) else str(error)
    return f"error: {message}"
