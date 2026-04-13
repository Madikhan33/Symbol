"""High-level build, validation, and query facade."""

from __future__ import annotations

from pathlib import Path

from symbol_memory.models import ProjectIndex, RelationPreview, ValidationIssue, ValidationReport
from symbol_memory.resolver import build_relation_map, link_child_methods
from symbol_memory.scanner import scan_project
from symbol_memory.storage import (
    build_project_index,
    compare_artifacts,
    default_output_dir,
    load_index,
    load_relations,
    render_project_map,
    render_symbol_card,
    write_artifacts,
)


class SymbolMemory:
    """Facade for building and querying symbol memory artifacts."""

    def __init__(self, project_root: str | Path | None = None, output_dir: str | Path | None = None) -> None:
        self.project_root: Path | None = Path(project_root).resolve() if project_root else None
        if output_dir is not None:
            self.output_dir: Path | None = Path(output_dir).resolve()
        elif self.project_root is not None:
            self.output_dir = default_output_dir(self.project_root)
        else:
            self.output_dir = None
        self._index_cache: ProjectIndex | None = None
        self._relations_cache: dict[int, list[RelationPreview]] | None = None

    def build(
        self,
        project_root: str | Path | None = None,
        output_dir: str | Path | None = None,
    ) -> ValidationReport:
        project_root_path, output_dir_path = self._set_paths(project_root, output_dir)
        bundle = self._compile_bundle(project_root_path)
        report = ValidationReport.from_issues(bundle["issues"])
        write_artifacts(
            output_dir_path,
            bundle["index"],
            bundle["relations"],
            report,
            bundle["cards"],
            bundle["project_map"],
        )

        consistency_issues = compare_artifacts(
            output_dir_path,
            bundle["index"],
            bundle["relations"],
            bundle["cards"],
            bundle["project_map"],
        )
        if consistency_issues:
            final_issues = list(bundle["issues"]) + consistency_issues
            report = ValidationReport.from_issues(final_issues)
            write_artifacts(
                output_dir_path,
                bundle["index"],
                bundle["relations"],
                report,
                bundle["cards"],
                bundle["project_map"],
            )

        self._index_cache = bundle["index"]
        self._relations_cache = bundle["relations"]
        return report

    def validate(
        self,
        project_root: str | Path | None = None,
        output_dir: str | Path | None = None,
    ) -> ValidationReport:
        project_root_path, output_dir_path = self._set_paths(project_root, output_dir)
        bundle = self._compile_bundle(project_root_path)
        comparison_issues = compare_artifacts(
            output_dir_path,
            bundle["index"],
            bundle["relations"],
            bundle["cards"],
            bundle["project_map"],
        )
        return ValidationReport.from_issues(list(bundle["issues"]) + comparison_issues)

    def find(self, query: int | str):
        index = self._load_index()
        if isinstance(query, int):
            return self.get_symbol(query)
        query_str = query.strip()
        if query_str.isdigit():
            return self.get_symbol(int(query_str))

        exact_ids = index.qualified_name_lookup.get(query_str) or index.name_lookup.get(query_str)
        if exact_ids:
            return [index.symbols_by_id[symbol_id] for symbol_id in exact_ids]

        lowered = query_str.casefold()
        matches = [
            symbol
            for symbol in index.symbols_by_id.values()
            if lowered in symbol.name.casefold() or lowered in symbol.qualified_name.casefold()
        ]
        matches.sort(key=lambda symbol: symbol.id)
        return matches[:20]

    def get_symbol(self, symbol_id: int):
        index = self._load_index()
        try:
            return index.symbols_by_id[symbol_id]
        except KeyError as error:
            raise KeyError(f"Unknown symbol id {symbol_id}") from error

    def get_symbol_card(self, symbol_id: int) -> str:
        output_dir = self._require_output_dir()
        path = output_dir / "symbols" / f"{symbol_id}.md"
        if not path.exists():
            raise KeyError(f"Unknown symbol card for id {symbol_id}")
        return path.read_text(encoding="utf-8")

    def show_relations(self, symbol_id: int) -> list[RelationPreview]:
        relations = self._load_relations()
        try:
            return relations[symbol_id]
        except KeyError as error:
            raise KeyError(f"Unknown symbol id {symbol_id}") from error

    def preview_relation(self, symbol_id: int) -> RelationPreview:
        symbol = self.get_symbol(symbol_id)
        return RelationPreview(
            id=symbol.id,
            resolved=True,
            name=symbol.name,
            role=symbol.role,
            summary=symbol.summary,
            file_path=symbol.file_path,
            start_line=symbol.start_line,
            end_line=symbol.end_line,
        )

    def open_symbol(self, symbol_id: int) -> str:
        symbol = self.get_symbol(symbol_id)
        return self.open_file_range(symbol.file_path, symbol.start_line, symbol.end_line)

    def open_file_range(self, path: str | Path, start: int, end: int) -> str:
        if start <= 0 or end < start:
            raise ValueError("Invalid file range")
        project_root = self._require_project_root()
        file_path = Path(path)
        resolved_path = file_path if file_path.is_absolute() else project_root / file_path
        lines = resolved_path.read_text(encoding="utf-8").splitlines()
        selected = lines[start - 1 : end]
        return "\n".join(selected)

    def list_symbols(self):
        index = self._load_index()
        return [index.symbols_by_id[symbol_id] for symbol_id in sorted(index.symbols_by_id)]

    def _compile_bundle(self, project_root: Path) -> dict[str, object]:
        records, issues = scan_project(project_root)
        symbols_by_id = {record.id: record for record in records}

        for symbol in symbols_by_id.values():
            file_path = project_root / symbol.file_path
            if not file_path.exists():
                issues.append(
                    ValidationIssue(
                        code="missing_symbol_file",
                        severity="error",
                        message=f"Resolved file path does not exist for symbol {symbol.id}: {symbol.file_path}",
                        symbol_id=symbol.id,
                        file_path=symbol.file_path,
                    )
                )
            if symbol.start_line > symbol.end_line:
                issues.append(
                    ValidationIssue(
                        code="invalid_symbol_line_range",
                        severity="error",
                        message=(
                            f"Invalid line range for symbol {symbol.id}: "
                            f"{symbol.start_line}>{symbol.end_line}"
                        ),
                        symbol_id=symbol.id,
                        file_path=symbol.file_path,
                    )
                )

        link_child_methods(symbols_by_id)
        relations = build_relation_map(symbols_by_id, issues)
        index = build_project_index(project_root, symbols_by_id)
        cards = {
            symbol_id: render_symbol_card(symbol, relations.get(symbol_id, []))
            for symbol_id, symbol in sorted(symbols_by_id.items())
        }
        project_map = render_project_map(index)
        return {
            "index": index,
            "relations": relations,
            "cards": cards,
            "project_map": project_map,
            "issues": issues,
        }

    def _load_index(self) -> ProjectIndex:
        if self._index_cache is None:
            self._index_cache = load_index(self._require_output_dir())
        return self._index_cache

    def _load_relations(self) -> dict[int, list[RelationPreview]]:
        if self._relations_cache is None:
            self._relations_cache = load_relations(self._require_output_dir())
        return self._relations_cache

    def _set_paths(
        self,
        project_root: str | Path | None,
        output_dir: str | Path | None,
    ) -> tuple[Path, Path]:
        if project_root is not None:
            self.project_root = Path(project_root).resolve()
        if self.project_root is None:
            raise ValueError("project_root must be provided")

        if output_dir is not None:
            self.output_dir = Path(output_dir).resolve()
        elif self.output_dir is None:
            self.output_dir = default_output_dir(self.project_root)

        self._index_cache = None
        self._relations_cache = None
        return self.project_root, self.output_dir

    def _require_project_root(self) -> Path:
        if self.project_root is None:
            raise ValueError("project_root is not set")
        return self.project_root

    def _require_output_dir(self) -> Path:
        if self.output_dir is None:
            raise ValueError("output_dir is not set")
        return self.output_dir
