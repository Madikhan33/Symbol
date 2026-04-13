"""Resolvers for relation previews and child symbol links."""

from __future__ import annotations

from collections import defaultdict

from symbol_memory.models import RelationPreview, SymbolRecord, ValidationIssue


def link_child_methods(symbols_by_id: dict[int, SymbolRecord]) -> None:
    """Populate child method ids for annotated class records."""

    methods_by_parent: dict[tuple[str, str], list[int]] = defaultdict(list)
    for symbol in symbols_by_id.values():
        if symbol.symbol_type == "method" and symbol.parent_class_name:
            methods_by_parent[(symbol.file_path, symbol.parent_class_name)].append(symbol.id)

    for symbol in symbols_by_id.values():
        if symbol.symbol_type == "class":
            key = (symbol.file_path, symbol.name)
            symbol.child_method_ids = sorted(methods_by_parent.get(key, []))


def build_relation_map(
    symbols_by_id: dict[int, SymbolRecord],
    issues: list[ValidationIssue],
) -> dict[int, list[RelationPreview]]:
    """Resolve raw relation ids into previews and report missing targets."""

    relation_map: dict[int, list[RelationPreview]] = {}
    for symbol_id, symbol in sorted(symbols_by_id.items()):
        previews: list[RelationPreview] = []
        for relation_id in symbol.relation_ids:
            target = symbols_by_id.get(relation_id)
            if target is None:
                message = f"Relation id {relation_id} referenced by symbol {symbol.id} does not exist"
                issues.append(
                    ValidationIssue(
                        code="missing_relation_id",
                        severity="error",
                        message=message,
                        symbol_id=symbol.id,
                        file_path=symbol.file_path,
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
