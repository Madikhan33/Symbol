"""Resolvers for relation previews, class child links, and hierarchy links."""

from __future__ import annotations

from collections import defaultdict

from symbol_memory.core.ids import parent_symbol_id, symbol_id_sort_key
from symbol_memory.core.models import RelationPreview, SymbolRecord, ValidationIssue


def link_child_methods(symbols_by_id: dict[str, SymbolRecord]) -> None:
    """Populate child method ids for annotated class records."""

    methods_by_parent: dict[tuple[str, str], list[str]] = defaultdict(list)
    for symbol in symbols_by_id.values():
        symbol.child_method_ids = []
        if symbol.symbol_type == "method" and symbol.parent_class_name:
            methods_by_parent[(symbol.file_path, symbol.parent_class_name)].append(symbol.id)

    for symbol in symbols_by_id.values():
        if symbol.symbol_type == "class":
            key = (symbol.file_path, symbol.name)
            symbol.child_method_ids = sorted(
                methods_by_parent.get(key, []),
                key=symbol_id_sort_key,
            )


def assign_hierarchy(symbols_by_id: dict[str, SymbolRecord], issues: list[ValidationIssue]) -> None:
    """Populate direct parent/child ids using dotted symbol ids."""

    for symbol in symbols_by_id.values():
        symbol.hierarchy_parent_id = None
        symbol.hierarchy_child_ids = []

    for symbol in sorted(symbols_by_id.values(), key=lambda item: symbol_id_sort_key(item.id)):
        parent_id = parent_symbol_id(symbol.id)
        if parent_id is None:
            continue
        symbol.hierarchy_parent_id = parent_id
        parent = symbols_by_id.get(parent_id)
        if parent is None:
            issues.append(
                ValidationIssue(
                    stage="resolve",
                    code="missing_parent_symbol_id",
                    severity="error",
                    message=f"Symbol {symbol.id} requires direct parent {parent_id}, but it does not exist",
                    symbol_id=symbol.id,
                    file_path=symbol.file_path,
                    line=symbol.start_line,
                    field="id",
                    hint=f"Add a symbol with id {parent_id} or rename {symbol.id} so its direct parent exists.",
                )
            )
            continue
        parent.hierarchy_child_ids.append(symbol.id)

    for symbol in symbols_by_id.values():
        symbol.hierarchy_child_ids = sorted(set(symbol.hierarchy_child_ids), key=symbol_id_sort_key)


def build_relation_map(
    symbols_by_id: dict[str, SymbolRecord],
    issues: list[ValidationIssue],
) -> dict[str, list[RelationPreview]]:
    """Resolve raw relation ids into previews and report missing targets."""

    relation_map: dict[str, list[RelationPreview]] = {}
    for symbol_id in sorted(symbols_by_id, key=symbol_id_sort_key):
        symbol = symbols_by_id[symbol_id]
        previews: list[RelationPreview] = []
        for relation_id in symbol.relation_ids:
            target = symbols_by_id.get(relation_id)
            if target is None:
                message = f"Relation id {relation_id} referenced by symbol {symbol.id} does not exist"
                issues.append(
                    ValidationIssue(
                        stage="resolve",
                        code="missing_relation_id",
                        severity="error",
                        message=message,
                        symbol_id=symbol.id,
                        file_path=symbol.file_path,
                        line=symbol.start_line,
                        field="r",
                        hint=f"Remove '{relation_id}' from r or add a symbol with id '{relation_id}'.",
                    )
                )
                previews.append(
                    RelationPreview(
                        id=relation_id,
                        resolved=False,
                        message=message,
                    )
                )
                continue
            previews.append(
                RelationPreview(
                    id=target.id,
                    resolved=True,
                    name=target.name,
                    role=target.role,
                    summary=target.summary,
                    file_path=target.file_path,
                    start_line=target.start_line,
                    end_line=target.end_line,
                )
            )
        relation_map[symbol_id] = previews
    return relation_map
