"""AST scanner that extracts explicitly annotated symbols."""

from __future__ import annotations

import ast
from collections.abc import Iterable
from pathlib import Path

from symbol_memory.models import SymbolDecoratorMetadata, SymbolRecord, ValidationIssue

IGNORED_DIR_NAMES = {
    ".git",
    ".symbol_memory",
    ".venv",
    "__pycache__",
    "node_modules",
    "venv",
}

SUPPORTED_KWARGS = {"r", "role", "summary", "notes", "tags", "expose", "entrypoint"}


def scan_project(project_root: Path) -> tuple[list[SymbolRecord], list[ValidationIssue]]:
    """Scan a project root and return symbol records with diagnostics."""

    root = project_root.resolve()
    records: list[SymbolRecord] = []
    issues: list[ValidationIssue] = []

    for file_path in sorted(_iter_python_files(root)):
        rel_path = file_path.relative_to(root).as_posix()
        try:
            source = file_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            issues.append(
                ValidationIssue(
                    code="file_decode_error",
                    severity="error",
                    message=f"Could not decode Python file {rel_path} as UTF-8",
                    file_path=rel_path,
                )
            )
            continue

        try:
            tree = ast.parse(source, filename=str(file_path))
        except SyntaxError as error:
            issues.append(
                ValidationIssue(
                    code="syntax_error",
                    severity="error",
                    message=f"Syntax error in {rel_path}: {error.msg} at line {error.lineno}",
                    file_path=rel_path,
                )
            )
            continue

        visitor = _ModuleScanner(project_root=root, file_path=file_path, tree=tree)
        visitor.visit(tree)
        records.extend(visitor.records)
        issues.extend(visitor.issues)

    issues.extend(_detect_duplicate_ids(records))
    return records, issues


def _iter_python_files(project_root: Path) -> Iterable[Path]:
    for path in project_root.rglob("*.py"):
        if any(part in IGNORED_DIR_NAMES for part in path.parts):
            continue
        yield path


def _detect_duplicate_ids(records: list[SymbolRecord]) -> list[ValidationIssue]:
    seen: dict[int, SymbolRecord] = {}
    issues: list[ValidationIssue] = []
    for record in records:
        existing = seen.get(record.id)
        if existing is None:
            seen[record.id] = record
            continue
        issues.append(
            ValidationIssue(
                code="duplicate_symbol_id",
                severity="error",
                message=(
                    f"Duplicate symbol id {record.id} found in "
                    f"{existing.file_path} and {record.file_path}"
                ),
                symbol_id=record.id,
                file_path=record.file_path,
            )
        )
    return issues


class _ModuleScanner(ast.NodeVisitor):
    def __init__(self, project_root: Path, file_path: Path, tree: ast.Module) -> None:
        self.project_root = project_root
        self.file_path = file_path
        self.relative_file_path = file_path.relative_to(project_root).as_posix()
        self.module_path = _module_path_for_file(project_root, file_path)
        self.records: list[SymbolRecord] = []
        self.issues: list[ValidationIssue] = []
        self.symbol_aliases = _collect_symbol_aliases(tree)
        self.class_stack: list[str] = []
        self.function_depth = 0

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        is_top_level = not self.class_stack and self.function_depth == 0
        if is_top_level:
            self._process_symbol_node(node, symbol_type="class", parent_class_name=None)
        else:
            self._report_nested_if_needed(node)

        self.class_stack.append(node.name)
        previous_function_depth = self.function_depth
        self.function_depth = 0
        for child in node.body:
            self.visit(child)
        self.function_depth = previous_function_depth
        self.class_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function_like(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function_like(node)

    def _visit_function_like(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        is_top_level = not self.class_stack and self.function_depth == 0
        is_method = len(self.class_stack) == 1 and self.function_depth == 0
        if is_top_level:
            self._process_symbol_node(node, symbol_type="function", parent_class_name=None)
        elif is_method:
            self._process_symbol_node(
                node,
                symbol_type="method",
                parent_class_name=self.class_stack[-1],
            )
        else:
            self._report_nested_if_needed(node)

        self.function_depth += 1
        for child in node.body:
            self.visit(child)
        self.function_depth -= 1

    def _process_symbol_node(
        self,
        node: ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef,
        *,
        symbol_type: str,
        parent_class_name: str | None,
    ) -> None:
        decorator_match = _find_symbol_decorator(node.decorator_list, self.symbol_aliases)
        if decorator_match.kind == "none":
            return
        if decorator_match.kind != "supported":
            self.issues.append(
                ValidationIssue(
                    code=decorator_match.code,
                    severity="error",
                    message=decorator_match.message,
                    file_path=self.relative_file_path,
                )
            )
            return

        metadata, metadata_issues = _parse_symbol_decorator(
            decorator_match.decorator,
            self.relative_file_path,
        )
        self.issues.extend(metadata_issues)
        if metadata is None:
            return

        start_line = min(
            [getattr(dec, "lineno", node.lineno) for dec in node.decorator_list] or [node.lineno]
        )
        end_line = getattr(node, "end_lineno", node.lineno)
        qualified_name = _qualified_name(
            module_path=self.module_path,
            class_stack=self.class_stack,
            symbol_name=node.name,
            symbol_type=symbol_type,
        )

        self.records.append(
            SymbolRecord(
                id=metadata.id,
                name=node.name,
                qualified_name=qualified_name,
                symbol_type=symbol_type,
                role=metadata.role,
                summary=metadata.summary,
                relation_ids=metadata.r,
                notes=metadata.notes,
                tags=metadata.tags,
                expose=metadata.expose,
                entrypoint=metadata.entrypoint,
                file_path=self.relative_file_path,
                start_line=start_line,
                end_line=end_line,
                module_path=self.module_path,
                parent_class_name=parent_class_name,
                child_method_ids=[],
            )
        )

    def _report_nested_if_needed(
        self,
        node: ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef,
    ) -> None:
        decorator_match = _find_symbol_decorator(node.decorator_list, self.symbol_aliases)
        if decorator_match.kind == "none":
            return
        message = (
            f"Nested symbols are not supported in v1: {node.name} in "
            f"{self.relative_file_path} at line {node.lineno}"
        )
        code = "nested_symbol_not_supported"
        if decorator_match.kind != "supported":
            message = decorator_match.message
            code = decorator_match.code
        self.issues.append(
            ValidationIssue(
                code=code,
                severity="error",
                message=message,
                file_path=self.relative_file_path,
            )
        )


class _DecoratorMatch:
    def __init__(
        self,
        *,
        kind: str,
        code: str = "",
        message: str = "",
        decorator: ast.Call | None = None,
    ) -> None:
        self.kind = kind
        self.code = code
        self.message = message
        self.decorator = decorator


def _find_symbol_decorator(
    decorators: list[ast.expr],
    symbol_aliases: set[str],
) -> _DecoratorMatch:
    for decorator in decorators:
        if isinstance(decorator, ast.Call):
            if _is_supported_symbol_func(decorator.func):
                return _DecoratorMatch(kind="supported", decorator=decorator)
            if isinstance(decorator.func, ast.Name) and decorator.func.id in symbol_aliases:
                return _DecoratorMatch(
                    kind="unsupported_alias",
                    code="unsupported_symbol_alias",
                    message=(
                        f"Unsupported symbol decorator alias '{decorator.func.id}'. "
                        "Use @symbol(...) or @module.symbol(...)."
                    ),
                )
        elif _is_supported_symbol_func(decorator):
            return _DecoratorMatch(
                kind="invalid_form",
                code="invalid_symbol_decorator_form",
                message="Invalid symbol decorator usage. Use @symbol(...).",
            )
        elif isinstance(decorator, ast.Name) and decorator.id in symbol_aliases:
            return _DecoratorMatch(
                kind="unsupported_alias",
                code="unsupported_symbol_alias",
                message=(
                    f"Unsupported symbol decorator alias '{decorator.id}'. "
                    "Use @symbol(...) or @module.symbol(...)."
                ),
            )
    return _DecoratorMatch(kind="none")


def _collect_symbol_aliases(tree: ast.Module) -> set[str]:
    aliases: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.ImportFrom):
            for imported in node.names:
                if imported.name == "symbol" and imported.asname:
                    aliases.add(imported.asname)
    return aliases


def _is_supported_symbol_func(expr: ast.expr) -> bool:
    if isinstance(expr, ast.Name):
        return expr.id == "symbol"
    if isinstance(expr, ast.Attribute):
        return expr.attr == "symbol"
    return False


def _parse_symbol_decorator(
    decorator: ast.Call | None,
    relative_file_path: str,
) -> tuple[SymbolDecoratorMetadata | None, list[ValidationIssue]]:
    issues: list[ValidationIssue] = []
    if decorator is None:
        issues.append(
            ValidationIssue(
                code="invalid_symbol_decorator_form",
                severity="error",
                message="Invalid symbol decorator usage. Use @symbol(...).",
                file_path=relative_file_path,
            )
        )
        return None, issues

    if len(decorator.args) != 1:
        issues.append(
            ValidationIssue(
                code="invalid_symbol_id_argument",
                severity="error",
                message=(
                    "Symbol decorator requires exactly one positional argument for the numeric id "
                    f"in {relative_file_path} at line {decorator.lineno}"
                ),
                file_path=relative_file_path,
            )
        )
        return None, issues

    try:
        id_value = _literal_int(decorator.args[0])
    except ValueError as error:
        issues.append(
            ValidationIssue(
                code="invalid_symbol_id_argument",
                severity="error",
                message=f"{error} in {relative_file_path} at line {decorator.lineno}",
                file_path=relative_file_path,
            )
        )
        return None, issues

    kwargs: dict[str, object] = {}
    for keyword in decorator.keywords:
        if keyword.arg is None:
            issues.append(
                ValidationIssue(
                    code="invalid_symbol_keyword",
                    severity="error",
                    message=(
                        f"Keyword unpacking is not supported in symbol decorators "
                        f"({relative_file_path}:{decorator.lineno})"
                    ),
                    file_path=relative_file_path,
                )
            )
            return None, issues
        if keyword.arg in kwargs:
            issues.append(
                ValidationIssue(
                    code="duplicate_symbol_keyword",
                    severity="error",
                    message=(
                        f"Duplicate keyword '{keyword.arg}' in symbol decorator "
                        f"({relative_file_path}:{decorator.lineno})"
                    ),
                    file_path=relative_file_path,
                )
            )
            return None, issues
        if keyword.arg not in SUPPORTED_KWARGS:
            issues.append(
                ValidationIssue(
                    code="unknown_symbol_keyword",
                    severity="error",
                    message=(
                        f"Unknown symbol decorator keyword '{keyword.arg}' "
                        f"({relative_file_path}:{decorator.lineno})"
                    ),
                    file_path=relative_file_path,
                )
            )
            return None, issues
        kwargs[keyword.arg] = keyword.value

    missing = [name for name in ("r", "role", "summary") if name not in kwargs]
    if missing:
        issues.append(
            ValidationIssue(
                code="missing_symbol_keyword",
                severity="error",
                message=(
                    f"Missing required symbol decorator keyword(s) {', '.join(missing)} "
                    f"({relative_file_path}:{decorator.lineno})"
                ),
                file_path=relative_file_path,
            )
        )
        return None, issues

    try:
        metadata = SymbolDecoratorMetadata(
            id=id_value,
            r=_literal_int_list(kwargs["r"]),
            role=_literal_string(kwargs["role"]),
            summary=_literal_string(kwargs["summary"]),
            notes=_literal_optional_string(kwargs.get("notes")),
            tags=_literal_optional_string_list(kwargs.get("tags")) or [],
            expose=_literal_bool(kwargs.get("expose", ast.Constant(value=True))),
            entrypoint=_literal_bool(kwargs.get("entrypoint", ast.Constant(value=False))),
        )
    except ValueError as error:
        issues.append(
            ValidationIssue(
                code="invalid_symbol_metadata",
                severity="error",
                message=f"{error} in {relative_file_path} at line {decorator.lineno}",
                file_path=relative_file_path,
            )
        )
        return None, issues

    return metadata, issues


def _literal_int(node: ast.AST) -> int:
    value = ast.literal_eval(node)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("Symbol id must be an integer literal")
    return value


def _literal_int_list(node: object) -> list[int]:
    assert isinstance(node, ast.AST)
    value = ast.literal_eval(node)
    if not isinstance(value, list) or any(isinstance(item, bool) or not isinstance(item, int) for item in value):
        raise ValueError("Symbol relations must be a list of integer literals")
    return value


def _literal_string(node: object) -> str:
    assert isinstance(node, ast.AST)
    value = ast.literal_eval(node)
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Symbol string fields must be non-empty string literals")
    return value


def _literal_optional_string(node: object | None) -> str | None:
    if node is None:
        return None
    assert isinstance(node, ast.AST)
    value = ast.literal_eval(node)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Optional symbol string fields must be string literals or None")
    return value


def _literal_optional_string_list(node: object | None) -> list[str] | None:
    if node is None:
        return None
    assert isinstance(node, ast.AST)
    value = ast.literal_eval(node)
    if value is None:
        return None
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValueError("Symbol tags must be a list of non-empty string literals")
    return value


def _literal_bool(node: object) -> bool:
    assert isinstance(node, ast.AST)
    value = ast.literal_eval(node)
    if not isinstance(value, bool):
        raise ValueError("Boolean symbol fields must be boolean literals")
    return value


def _module_path_for_file(project_root: Path, file_path: Path) -> str:
    rel = file_path.relative_to(project_root).with_suffix("")
    parts = list(rel.parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _qualified_name(
    *,
    module_path: str,
    class_stack: list[str],
    symbol_name: str,
    symbol_type: str,
) -> str:
    parts: list[str] = []
    if module_path:
        parts.append(module_path)
    if symbol_type == "method" and class_stack:
        parts.extend(class_stack)
    parts.append(symbol_name)
    return ".".join(parts)
