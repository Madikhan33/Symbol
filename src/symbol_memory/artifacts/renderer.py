"""Render indexes and human-readable markdown artifacts."""

from __future__ import annotations

from datetime import UTC, datetime

from symbol_memory.core.ids import symbol_id_sort_key
from symbol_memory.core.models import ProjectCounts, ProjectIndex, RelationPreview, SymbolRecord


def build_project_index(project_root: str, symbols_by_id: dict[str, SymbolRecord]) -> ProjectIndex:
    """Build the canonical project index payload."""

    ordered_ids = sorted(symbols_by_id, key=symbol_id_sort_key)
    counts = ProjectCounts(
        total_indexed_symbols=len(symbols_by_id),
        total_functions=sum(1 for symbol in symbols_by_id.values() if symbol.symbol_type == "function"),
        total_methods=sum(1 for symbol in symbols_by_id.values() if symbol.symbol_type == "method"),
        total_classes=sum(1 for symbol in symbols_by_id.values() if symbol.symbol_type == "class"),
    )
    name_lookup: dict[str, list[str]] = {}
    qualified_name_lookup: dict[str, list[str]] = {}

    for symbol_id in ordered_ids:
        symbol = symbols_by_id[symbol_id]
        name_lookup.setdefault(symbol.name, []).append(symbol.id)
        qualified_name_lookup.setdefault(symbol.qualified_name, []).append(symbol.id)

    return ProjectIndex(
        project_root=project_root,
        generated_at=datetime.now(tz=UTC).isoformat(),
        counts=counts,
        symbols_by_id={symbol_id: symbols_by_id[symbol_id] for symbol_id in ordered_ids},
        name_lookup=dict(sorted(name_lookup.items())),
        qualified_name_lookup=dict(sorted(qualified_name_lookup.items())),
    )


def render_symbol_card(symbol: SymbolRecord, relations: list[RelationPreview]) -> str:
    """Render a markdown card for a single symbol."""

    lines = [
        f"# Symbol {symbol.id}",
        "",
        "## Metadata",
        f"- id: {symbol.id}",
        f"- name: {symbol.name}",
        f"- qualified_name: {symbol.qualified_name}",
        f"- type: {symbol.symbol_type}",
        f"- role: {symbol.role}",
        f"- file_path: {symbol.file_path}",
        f"- module_path: {symbol.module_path}",
        f"- start_line: {symbol.start_line}",
        f"- end_line: {symbol.end_line}",
        f"- entrypoint: {str(symbol.entrypoint).lower()}",
        f"- expose: {str(symbol.expose).lower()}",
        "",
        "## Summary",
        symbol.summary,
        "",
        "## Hierarchy",
        f"- parent: {symbol.hierarchy_parent_id or 'none'}",
    ]

    if symbol.hierarchy_child_ids:
        for child_id in symbol.hierarchy_child_ids:
            lines.append(f"- child: {child_id}")
    else:
        lines.append("- child: none")

    lines.extend(["", "## Relations"])
    if relations:
        for relation in relations:
            if relation.resolved:
                lines.append(
                    f"- {relation.id} - {relation.name} - "
                    f"{relation.file_path}:{relation.start_line}-{relation.end_line}"
                )
            else:
                lines.append(f"- {relation.id} - unresolved")
    else:
        lines.append("- none")

    lines.extend(["", "## Raw Relation IDs", f"- {symbol.relation_ids}"])

    if symbol.tags:
        lines.extend(["", "## Tags"])
        for tag in symbol.tags:
            lines.append(f"- {tag}")

    if symbol.notes:
        lines.extend(["", "## Notes", symbol.notes])

    if symbol.symbol_type == "class":
        lines.extend(["", "## Methods"])
        if symbol.child_method_ids:
            for child_id in symbol.child_method_ids:
                lines.append(f"- {child_id}")
        else:
            lines.append("- none")

    if symbol.symbol_type == "method" and symbol.parent_class_name:
        lines.extend(["", "## Parent Class", symbol.parent_class_name])

    lines.append("")
    return "\n".join(lines)


def render_project_map(index: ProjectIndex) -> str:
    """Render a markdown tree of the symbol id hierarchy."""

    lines = [
        "# Project Map",
        "",
        "## Overview",
        f"- project_root: {index.project_root}",
        f"- total_indexed_symbols: {index.counts.total_indexed_symbols}",
        f"- total_functions: {index.counts.total_functions}",
        f"- total_methods: {index.counts.total_methods}",
        f"- total_classes: {index.counts.total_classes}",
        "",
        "## Output Layout",
        "- .symbol_memory/index.json",
        "- .symbol_memory/relations.json",
        "- .symbol_memory/validation_report.json",
        "- .symbol_memory/project_map.md",
        "- .symbol_memory/symbols/{id}.md",
        "",
        "## Symbol Hierarchy",
    ]

    roots = [
        symbol
        for symbol in index.symbols_by_id.values()
        if symbol.hierarchy_parent_id is None
    ]
    if roots:
        for root in sorted(roots, key=lambda item: symbol_id_sort_key(item.id)):
            _render_tree(index, root, lines, depth=0)
    else:
        lines.append("- none")

    orphans = [
        symbol
        for symbol in index.symbols_by_id.values()
        if symbol.hierarchy_parent_id is not None and symbol.hierarchy_parent_id not in index.symbols_by_id
    ]
    if orphans:
        lines.extend(["", "## Orphaned Symbols"])
        for symbol in sorted(orphans, key=lambda item: symbol_id_sort_key(item.id)):
            lines.append(
                f"- {symbol.id} - missing parent {symbol.hierarchy_parent_id} - "
                f"{symbol.file_path}:{symbol.start_line}-{symbol.end_line}"
            )

    lines.append("")
    return "\n".join(lines)


def _render_tree(index: ProjectIndex, symbol: SymbolRecord, lines: list[str], depth: int) -> None:
    indent = "  " * depth
    lines.append(
        f"{indent}- {symbol.id} - {symbol.name} - {symbol.file_path}:{symbol.start_line}-{symbol.end_line}"
    )
    for child_id in symbol.hierarchy_child_ids:
        child = index.symbols_by_id.get(child_id)
        if child is not None:
            _render_tree(index, child, lines, depth + 1)
