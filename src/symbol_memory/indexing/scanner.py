"""AST scanner that extracts explicitly annotated symbols."""

from __future__ import annotations

import ast
from collections.abc import Iterable
from pathlib import Path

from pydantic import ValidationError

from symbol_memory.core.ids import validate_symbol_id
from symbol_memory.core.models import SymbolDecoratorMetadata, SymbolRecord, ValidationIssue

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
                _issue(
                    stage="scan",
                    code="file_decode_error",
                    severity="error",
                    message=f"Could not decode Python file '{rel_path}' as UTF-8.",
                    file_path=rel_path,
                    hint="Re-save the file as UTF-8 before rebuilding symbol memory.",
                )
            )
            continue

        try:
            tree = ast.parse(source, filename=str(file_path))
        except SyntaxError as error:
            issues.append(
                _issue(
                    stage="scan",
                    code="syntax_error",
                    severity="error",
                    message=f"Python syntax error: {error.msg}.",
                    file_path=rel_path,
                    line=error.lineno,
                    column=error.offset,
                    hint="Fix the Python syntax error before rebuilding symbol memory.",
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
    seen: dict[str, SymbolRecord] = {}
    issues: list[ValidationIssue] = []
    for record in records:
        existing = seen.get(record.id)
        if existing is None:
            seen[record.id] = record
            continue
        issues.append(
            _issue(
                stage="scan",
                code="duplicate_symbol_id",
                severity="error",
                message=(
                    f"Duplicate symbol id {record.id} is declared in "
                    f"'{existing.file_path}' and '{record.file_path}'."
                ),
                symbol_id=record.id,
                file_path=record.file_path,
                line=record.start_line,
                field="id",
                hint="Choose a unique string id for one of the conflicting symbols.",
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
                _issue(
                    stage="scan",
                    code=decorator_match.code,
                    severity="error",
                    message=decorator_match.message,
                    file_path=self.relative_file_path,
                    line=_line_from_node(decorator_match.node) or node.lineno,
                    column=_column_from_node(decorator_match.node),
                    hint=decorator_match.hint,
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
                hierarchy_parent_id=None,
                hierarchy_child_ids=[],
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
            f"Nested symbols are not supported in v1: '{node.name}' cannot be indexed here."
        )
        code = "nested_symbol_not_supported"
        hint = "Move the annotated symbol to module scope or to a top-level class method."
        if decorator_match.kind != "supported":
            message = decorator_match.message
            code = decorator_match.code
            hint = decorator_match.hint
        self.issues.append(
            _issue(
                stage="scan",
                code=code,
                severity="error",
                message=message,
                file_path=self.relative_file_path,
                line=node.lineno,
                column=_column_from_node(node),
                hint=hint,
            )
        )


class _DecoratorMatch:
    def __init__(
        self,
        *,
        kind: str,
        code: str = "",
        message: str = "",
        hint: str | None = None,
        decorator: ast.Call | None = None,
        node: ast.AST | None = None,
    ) -> None:
        self.kind = kind
        self.code = code
        self.message = message
        self.hint = hint
        self.decorator = decorator
        self.node = node


def _find_symbol_decorator(
    decorators: list[ast.expr],
    symbol_aliases: set[str],
) -> _DecoratorMatch:
    for decorator in decorators:
        if isinstance(decorator, ast.Call):
            if _is_supported_symbol_func(decorator.func):
                return _DecoratorMatch(kind="supported", decorator=decorator, node=decorator)
            if isinstance(decorator.func, ast.Name) and decorator.func.id in symbol_aliases:
                return _DecoratorMatch(
                    kind="unsupported_alias",
                    code="unsupported_symbol_alias",
                    message=(
                        f"Unsupported symbol decorator alias '{decorator.func.id}'. "
                        "Use @symbol(...) or @module.symbol(...)."
                    ),
                    hint="Import the decorator as 'symbol' or call it through a module attribute.",
                    node=decorator,
                )
        elif _is_supported_symbol_func(decorator):
            return _DecoratorMatch(
                kind="invalid_form",
                code="invalid_symbol_decorator_form",
                message="Invalid symbol decorator usage. Use @symbol(...).",
                hint="Add parentheses and the required arguments, for example @symbol('1', r=['2'], role='...', summary='...').",
                node=decorator,
            )
        elif isinstance(decorator, ast.Name) and decorator.id in symbol_aliases:
            return _DecoratorMatch(
                kind="unsupported_alias",
                code="unsupported_symbol_alias",
                message=(
                    f"Unsupported symbol decorator alias '{decorator.id}'. "
                    "Use @symbol(...) or @module.symbol(...)."
                ),
                hint="Import the decorator as 'symbol' or call it through a module attribute.",
                node=decorator,
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
            _issue(
                stage="parse",
                code="invalid_symbol_decorator_form",
                severity="error",
                message="Invalid symbol decorator usage. Use @symbol(...).",
                file_path=relative_file_path,
                hint="Add parentheses and the required arguments.",
            )
        )
        return None, issues

    id_value: str | None = None
    if not decorator.args:
        issues.append(
            _issue(
                stage="parse",
                code="missing_symbol_id_argument",
                severity="error",
                message="Symbol decorator requires a string id as the first positional argument.",
                file_path=relative_file_path,
                line=decorator.lineno,
                column=_column_from_node(decorator),
                field="id",
                hint="Pass a quoted id such as '1' or '1.2' as the first positional argument.",
            )
        )
    else:
        if len(decorator.args) > 1:
            issues.append(
                _issue(
                    stage="parse",
                    code="too_many_symbol_arguments",
                    severity="error",
                    message="Symbol decorator accepts exactly one positional argument.",
                    file_path=relative_file_path,
                    line=decorator.lineno,
                    column=_column_from_node(decorator),
                    field="id",
                    hint="Move all metadata except the id into keyword arguments.",
                )
            )
        try:
            id_value = _literal_symbol_id(decorator.args[0])
        except ValueError as error:
            issues.append(
                _issue(
                    stage="parse",
                    code="invalid_symbol_id_argument",
                    severity="error",
                    message=str(error),
                    file_path=relative_file_path,
                    line=_line_from_node(decorator.args[0]) or decorator.lineno,
                    column=_column_from_node(decorator.args[0]),
                    field="id",
                    hint="Use a quoted string id such as '1' or '1.2'.",
                )
            )

    kwargs: dict[str, ast.expr] = {}
    for keyword in decorator.keywords:
        if keyword.arg is None:
            issues.append(
                _issue(
                    stage="parse",
                    code="invalid_symbol_keyword_unpacking",
                    severity="error",
                    message="Keyword unpacking is not supported in symbol decorators.",
                    file_path=relative_file_path,
                    line=_line_from_node(keyword.value) or decorator.lineno,
                    column=_column_from_node(keyword.value),
                    hint="Write each supported keyword explicitly.",
                )
            )
            continue
        if keyword.arg in kwargs:
            issues.append(
                _issue(
                    stage="parse",
                    code="duplicate_symbol_keyword",
                    severity="error",
                    message=f"Duplicate symbol decorator keyword '{keyword.arg}'.",
                    file_path=relative_file_path,
                    line=decorator.lineno,
                    column=_column_from_node(keyword.value),
                    field=keyword.arg,
                    hint=f"Keep a single '{keyword.arg}=' entry in the decorator.",
                )
            )
            continue
        if keyword.arg not in SUPPORTED_KWARGS:
            issues.append(
                _issue(
                    stage="parse",
                    code="unknown_symbol_keyword",
                    severity="error",
                    message=f"Unknown symbol decorator keyword '{keyword.arg}'.",
                    file_path=relative_file_path,
                    line=decorator.lineno,
                    column=_column_from_node(keyword.value),
                    field=keyword.arg,
                    hint=f"Remove '{keyword.arg}' or replace it with one of: {', '.join(sorted(SUPPORTED_KWARGS))}.",
                )
            )
            continue
        kwargs[keyword.arg] = keyword.value

    for field_name in ("r", "role", "summary"):
        if field_name not in kwargs:
            issues.append(
                _issue(
                    stage="parse",
                    code="missing_symbol_keyword",
                    severity="error",
                    message=f"Missing required symbol decorator keyword '{field_name}'.",
                    file_path=relative_file_path,
                    line=decorator.lineno,
                    column=_column_from_node(decorator),
                    field=field_name,
                    hint=f"Add '{field_name}=...' to the decorator.",
                )
            )

    parsed_values: dict[str, object] = {}
    parsed_values["r"] = _parse_metadata_field(
        issues,
        relative_file_path=relative_file_path,
        field_name="r",
        node=kwargs.get("r"),
        parser=_literal_symbol_id_list,
        code="invalid_symbol_relations",
        hint="Use a list of quoted ids such as r=[] or r=['2', '1.2'].",
    )
    parsed_values["role"] = _parse_metadata_field(
        issues,
        relative_file_path=relative_file_path,
        field_name="role",
        node=kwargs.get("role"),
        parser=_literal_string,
        code="invalid_symbol_role",
        hint="Use a non-empty string literal such as role='auth'.",
    )
    parsed_values["summary"] = _parse_metadata_field(
        issues,
        relative_file_path=relative_file_path,
        field_name="summary",
        node=kwargs.get("summary"),
        parser=_literal_string,
        code="invalid_symbol_summary",
        hint="Use a non-empty string literal such as summary='Validates access token'.",
    )
    parsed_values["notes"] = _parse_metadata_field(
        issues,
        relative_file_path=relative_file_path,
        field_name="notes",
        node=kwargs.get("notes"),
        parser=_literal_optional_string,
        code="invalid_symbol_notes",
        hint="Use a string literal or None for notes.",
        default=None,
    )
    parsed_values["tags"] = _parse_metadata_field(
        issues,
        relative_file_path=relative_file_path,
        field_name="tags",
        node=kwargs.get("tags"),
        parser=_literal_optional_string_list,
        code="invalid_symbol_tags",
        hint="Use a list of non-empty string literals or omit tags entirely.",
        default=[],
    )
    parsed_values["expose"] = _parse_metadata_field(
        issues,
        relative_file_path=relative_file_path,
        field_name="expose",
        node=kwargs.get("expose"),
        parser=_literal_bool,
        code="invalid_symbol_expose",
        hint="Use a boolean literal: expose=True or expose=False.",
        default=True,
    )
    parsed_values["entrypoint"] = _parse_metadata_field(
        issues,
        relative_file_path=relative_file_path,
        field_name="entrypoint",
        node=kwargs.get("entrypoint"),
        parser=_literal_bool,
        code="invalid_symbol_entrypoint",
        hint="Use a boolean literal: entrypoint=True or entrypoint=False.",
        default=False,
    )

    if issues or id_value is None:
        return None, issues

    try:
        metadata = SymbolDecoratorMetadata(
            id=id_value,
            r=parsed_values["r"],
            role=parsed_values["role"],
            summary=parsed_values["summary"],
            notes=parsed_values["notes"],
            tags=parsed_values["tags"],
            expose=parsed_values["expose"],
            entrypoint=parsed_values["entrypoint"],
        )
    except ValidationError as error:
        issues.append(
            _issue(
                stage="parse",
                code="invalid_symbol_metadata",
                severity="error",
                message=str(error),
                file_path=relative_file_path,
                line=decorator.lineno,
                column=_column_from_node(decorator),
                hint="Fix the decorator metadata so it matches the public symbol() contract.",
            )
        )
        return None, issues

    return metadata, issues


def _parse_metadata_field(
    issues: list[ValidationIssue],
    *,
    relative_file_path: str,
    field_name: str,
    node: ast.AST | None,
    parser,
    code: str,
    hint: str,
    default: object | None = None,
) -> object | None:
    if node is None:
        return default
    try:
        value = parser(node)
    except ValueError as error:
        issues.append(
            _issue(
                stage="parse",
                code=code,
                severity="error",
                message=str(error),
                file_path=relative_file_path,
                line=_line_from_node(node),
                column=_column_from_node(node),
                field=field_name,
                hint=hint,
            )
        )
        return default
    return value if value is not None else default


def _literal_symbol_id(node: ast.AST) -> str:
    value = _literal_eval(node, "Symbol id must be a string literal like '1' or '1.2'")
    if not isinstance(value, str):
        raise ValueError("Symbol id must be a string literal like '1' or '1.2'")
    return validate_symbol_id(value)


def _literal_symbol_id_list(node: ast.AST) -> list[str]:
    value = _literal_eval(node, "Symbol relations must be a list of quoted string ids")
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError("Symbol relations must be a list of quoted string ids")
    return [validate_symbol_id(item) for item in value]


def _literal_string(node: ast.AST) -> str:
    value = _literal_eval(node, "Symbol string fields must be non-empty string literals")
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Symbol string fields must be non-empty string literals")
    return value


def _literal_optional_string(node: ast.AST) -> str | None:
    value = _literal_eval(node, "Optional symbol string fields must be string literals or None")
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Optional symbol string fields must be string literals or None")
    return value


def _literal_optional_string_list(node: ast.AST) -> list[str] | None:
    value = _literal_eval(node, "Symbol tags must be a list of non-empty string literals")
    if value is None:
        return None
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValueError("Symbol tags must be a list of non-empty string literals")
    return value


def _literal_bool(node: ast.AST) -> bool:
    value = _literal_eval(node, "Boolean symbol fields must be boolean literals")
    if not isinstance(value, bool):
        raise ValueError("Boolean symbol fields must be boolean literals")
    return value


def _literal_eval(node: ast.AST, error_message: str) -> object:
    try:
        return ast.literal_eval(node)
    except (ValueError, SyntaxError):
        raise ValueError(error_message) from None


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


def _issue(
    *,
    stage: str,
    code: str,
    severity: str,
    message: str,
    symbol_id: str | None = None,
    file_path: str | None = None,
    line: int | None = None,
    column: int | None = None,
    field: str | None = None,
    hint: str | None = None,
) -> ValidationIssue:
    return ValidationIssue(
        stage=stage,
        code=code,
        severity=severity,
        message=message,
        symbol_id=symbol_id,
        file_path=file_path,
        line=line,
        column=column,
        field=field,
        hint=hint,
    )


def _line_from_node(node: ast.AST | None) -> int | None:
    if node is None:
        return None
    return getattr(node, "lineno", None)


def _column_from_node(node: ast.AST | None) -> int | None:
    if node is None:
        return None
    column = getattr(node, "col_offset", None)
    return None if column is None else column + 1
