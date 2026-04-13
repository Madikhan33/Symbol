"""Storage, rendering, and artifact comparison helpers."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from pydantic import TypeAdapter

from symbol_memory.models import (
    ProjectCounts,
    ProjectIndex,
    RelationPreview,
    ValidationIssue,
)

RELATION_MAP_ADAPTER = TypeAdapter(dict[int, list[RelationPreview]])


def default_output_dir(project_root: Path) -> Path:
    return project_root / ".symbol_memory"


def build_project_index(project_root: Path, symbols_by_id: dict[int, "SymbolRecord"]) -> ProjectIndex:
    from symbol_memory.models import SymbolRecord

    counts = ProjectCounts(
        total_indexed_symbols=len(symbols_by_id),
        total_functions=sum(1 for symbol in symbols_by_id.values() if symbol.symbol_type == "function"),
        total_methods=sum(1 for symbol in symbols_by_id.values() if symbol.symbol_type == "method"),
        total_classes=sum(1 for symbol in symbols_by_id.values() if symbol.symbol_type == "class"),
    )
    name_lookup: dict[str, list[int]] = {}
    qualified_name_lookup: dict[str, list[int]] = {}

    for symbol in sorted(symbols_by_id.values(), key=lambda item: item.id):
        name_lookup.setdefault(symbol.name, []).append(symbol.id)
        qualified_name_lookup.setdefault(symbol.qualified_name, []).append(symbol.id)

    return ProjectIndex(
        project_root=str(project_root.resolve()),
        generated_at=datetime.now(tz=UTC).isoformat(),
        counts=counts,
        symbols_by_id=dict(sorted(symbols_by_id.items())),
        name_lookup=dict(sorted(name_lookup.items())),
        qualified_name_lookup=dict(sorted(qualified_name_lookup.items())),
    )


def render_symbol_card(symbol: "SymbolRecord", relations: list[RelationPreview]) -> str:
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
        "## Relations",
    ]

    if relations:
        for relation in relations:
            if relation.resolved:
                lines.append(
                    f"- {relation.id} — {relation.name} — "
                    f"{relation.file_path}:{relation.start_line}-{relation.end_line}"
                )
            else:
                lines.append(f"- {relation.id} — unresolved")
    else:
        lines.append("- none")

    lines.extend(
        [
            "",
            "## Raw Relation IDs",
            f"- {symbol.relation_ids}",
        ]
    )

    if symbol.tags:
        lines.extend(["", "## Tags"])
        for tag in symbol.tags:
            lines.append(f"- {tag}")

    if symbol.notes:
        lines.extend(["", "## Notes", symbol.notes])

    if symbol.symbol_type == "class" and symbol.child_method_ids:
        lines.extend(["", "## Children"])
        for child_id in symbol.child_method_ids:
            lines.append(f"- {child_id}")

    if symbol.symbol_type == "method" and symbol.parent_class_name:
        lines.extend(["", "## Parent Class", symbol.parent_class_name])

    lines.append("")
    return "\n".join(lines)


def render_project_map(index: ProjectIndex) -> str:
    top_level = [
        symbol
        for symbol in index.symbols_by_id.values()
        if symbol.symbol_type in {"function", "class"}
    ]
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
        "## Top-Level Annotated Symbols",
    ]
    if top_level:
        for symbol in sorted(top_level, key=lambda item: item.id):
            lines.append(
                f"- {symbol.id} — {symbol.name} — {symbol.file_path}:{symbol.start_line}-{symbol.end_line}"
            )
    else:
        lines.append("- none")
    lines.append("")
    return "\n".join(lines)


def write_artifacts(
    output_dir: Path,
    index: ProjectIndex,
    relations: dict[int, list[RelationPreview]],
    report: "ValidationReport",
    cards: dict[int, str],
    project_map: str,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    symbols_dir = output_dir / "symbols"
    symbols_dir.mkdir(parents=True, exist_ok=True)

    existing_cards = {path.name for path in symbols_dir.glob("*.md")}
    expected_cards = {f"{symbol_id}.md" for symbol_id in cards}
    for stale_card in existing_cards - expected_cards:
        (symbols_dir / stale_card).unlink()

    _write_text(output_dir / "project_map.md", project_map)
    _write_json(output_dir / "index.json", index.model_dump(mode="json"))
    _write_json(
        output_dir / "relations.json",
        RELATION_MAP_ADAPTER.dump_python(relations, mode="json"),
    )
    _write_json(output_dir / "validation_report.json", report.model_dump(mode="json"))

    for symbol_id, content in cards.items():
        _write_text(symbols_dir / f"{symbol_id}.md", content)


def load_index(output_dir: Path) -> ProjectIndex:
    return ProjectIndex.model_validate_json((output_dir / "index.json").read_text(encoding="utf-8"))


def load_relations(output_dir: Path) -> dict[int, list[RelationPreview]]:
    return RELATION_MAP_ADAPTER.validate_json((output_dir / "relations.json").read_text(encoding="utf-8"))


def compare_artifacts(
    output_dir: Path,
    expected_index: ProjectIndex,
    expected_relations: dict[int, list[RelationPreview]],
    expected_cards: dict[int, str],
    expected_project_map: str,
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    index_path = output_dir / "index.json"
    relations_path = output_dir / "relations.json"
    report_path = output_dir / "validation_report.json"
    project_map_path = output_dir / "project_map.md"
    symbols_dir = output_dir / "symbols"

    if not output_dir.exists():
        return [
            ValidationIssue(
                code="missing_output_dir",
                severity="error",
                message=f"Output directory does not exist: {output_dir}",
            )
        ]

    missing_paths = [
        path
        for path in (index_path, relations_path, report_path, project_map_path)
        if not path.exists()
    ]
    for path in missing_paths:
        issues.append(
            ValidationIssue(
                code="missing_artifact",
                severity="error",
                message=f"Missing artifact: {path.name}",
            )
        )
    if missing_paths:
        return issues

    try:
        actual_index = load_index(output_dir)
    except Exception as error:  # noqa: BLE001
        issues.append(
            ValidationIssue(
                code="invalid_index_json",
                severity="error",
                message=f"Could not load index.json: {error}",
            )
        )
        return issues

    try:
        actual_relations = load_relations(output_dir)
    except Exception as error:  # noqa: BLE001
        issues.append(
            ValidationIssue(
                code="invalid_relations_json",
                severity="error",
                message=f"Could not load relations.json: {error}",
            )
        )
        actual_relations = {}

    actual_ids = set(actual_index.symbols_by_id)
    expected_ids = set(expected_index.symbols_by_id)
    for missing_id in sorted(expected_ids - actual_ids):
        issues.append(
            ValidationIssue(
                code="missing_symbol_in_index",
                severity="error",
                message=f"Symbol {missing_id} is missing from index.json",
                symbol_id=missing_id,
            )
        )
    for extra_id in sorted(actual_ids - expected_ids):
        issues.append(
            ValidationIssue(
                code="unexpected_symbol_in_index",
                severity="error",
                message=f"Unexpected symbol {extra_id} found in index.json",
                symbol_id=extra_id,
            )
        )

    for symbol_id in sorted(actual_ids & expected_ids):
        actual_symbol = actual_index.symbols_by_id[symbol_id]
        expected_symbol = expected_index.symbols_by_id[symbol_id]
        if (
            actual_symbol.start_line != expected_symbol.start_line
            or actual_symbol.end_line != expected_symbol.end_line
        ):
            issues.append(
                ValidationIssue(
                    code="symbol_moved",
                    severity="error",
                    message=(
                        f"Symbol {symbol_id} moved from lines "
                        f"{actual_symbol.start_line}-{actual_symbol.end_line} to "
                        f"{expected_symbol.start_line}-{expected_symbol.end_line}"
                    ),
                    symbol_id=symbol_id,
                    file_path=expected_symbol.file_path,
                )
            )
            continue
        if actual_symbol != expected_symbol:
            issues.append(
                ValidationIssue(
                    code="symbol_index_mismatch",
                    severity="error",
                    message=f"Symbol {symbol_id} does not match current source metadata",
                    symbol_id=symbol_id,
                    file_path=expected_symbol.file_path,
                )
            )

    if actual_index.counts != expected_index.counts:
        issues.append(
            ValidationIssue(
                code="index_count_mismatch",
                severity="error",
                message="Index counts do not match current source scan",
            )
        )

    if actual_index.name_lookup != expected_index.name_lookup:
        issues.append(
            ValidationIssue(
                code="name_lookup_mismatch",
                severity="error",
                message="index.json name_lookup does not match current source scan",
            )
        )

    if actual_index.qualified_name_lookup != expected_index.qualified_name_lookup:
        issues.append(
            ValidationIssue(
                code="qualified_name_lookup_mismatch",
                severity="error",
                message="index.json qualified_name_lookup does not match current source scan",
            )
        )

    if actual_relations != expected_relations:
        issues.append(
            ValidationIssue(
                code="relations_mismatch",
                severity="error",
                message="relations.json does not match current source scan",
            )
        )

    actual_project_map = project_map_path.read_text(encoding="utf-8")
    if actual_project_map != expected_project_map:
        issues.append(
            ValidationIssue(
                code="project_map_mismatch",
                severity="error",
                message="project_map.md does not match current source scan",
            )
        )

    for symbol_id, expected_card in expected_cards.items():
        card_path = symbols_dir / f"{symbol_id}.md"
        if not card_path.exists():
            issues.append(
                ValidationIssue(
                    code="missing_symbol_card",
                    severity="error",
                    message=f"Missing symbol card for {symbol_id}",
                    symbol_id=symbol_id,
                )
            )
            continue
        actual_card = card_path.read_text(encoding="utf-8")
        if actual_card != expected_card:
            issues.append(
                ValidationIssue(
                    code="symbol_card_mismatch",
                    severity="error",
                    message=f"Markdown card for symbol {symbol_id} does not match index data",
                    symbol_id=symbol_id,
                )
            )

    return issues


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _write_text(path: Path, payload: str) -> None:
    path.write_text(payload, encoding="utf-8")
