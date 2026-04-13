"""CLI interface for symbol_memory."""

from __future__ import annotations

import argparse
import json

from symbol_memory.models import RelationPreview, SymbolRecord, ValidationReport
from symbol_memory.query import SymbolMemory

try:  # pragma: no cover - import path depends on environment
    import typer
except ModuleNotFoundError:  # pragma: no cover - fallback path is covered instead
    typer = None


def main(argv: list[str] | None = None) -> int:
    if typer is not None:
        return _run_typer(argv)
    return run(argv)


def run(argv: list[str] | None = None) -> int:
    parser = _build_argparse_parser()
    args = parser.parse_args(argv)
    return _dispatch_args(args)


def _build_argparse_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="symbol-memory")
    subparsers = parser.add_subparsers(dest="command", required=True)

    build_parser = subparsers.add_parser("build")
    build_parser.add_argument("project_root", nargs="?", default=".")
    build_parser.add_argument("--output", default=None)

    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("project_root", nargs="?", default=".")
    validate_parser.add_argument("--output", default=None)

    find_parser = subparsers.add_parser("find")
    find_parser.add_argument("query")
    find_parser.add_argument("--output", default=None)
    find_parser.add_argument("--project-root", default=".")

    show_parser = subparsers.add_parser("show")
    show_parser.add_argument("symbol_id", type=int)
    show_parser.add_argument("--output", default=None)
    show_parser.add_argument("--project-root", default=".")

    relations_parser = subparsers.add_parser("relations")
    relations_parser.add_argument("symbol_id", type=int)
    relations_parser.add_argument("--output", default=None)
    relations_parser.add_argument("--project-root", default=".")

    open_parser = subparsers.add_parser("open")
    open_parser.add_argument("symbol_id", type=int)
    open_parser.add_argument("--output", default=None)
    open_parser.add_argument("--project-root", default=".")

    list_parser = subparsers.add_parser("list")
    list_parser.add_argument("--output", default=None)
    list_parser.add_argument("--project-root", default=".")

    return parser


def _dispatch_args(args: argparse.Namespace) -> int:
    if args.command == "build":
        report = SymbolMemory().build(args.project_root, args.output)
        print(_format_report(report))
        return 1 if report.status == "error" else 0
    if args.command == "validate":
        report = SymbolMemory().validate(args.project_root, args.output)
        print(_format_report(report))
        return 1 if report.status == "error" else 0

    memory = SymbolMemory(project_root=args.project_root, output_dir=args.output)
    if args.command == "find":
        result = memory.find(args.query)
        print(_format_find_result(result))
        return 0
    if args.command == "show":
        print(memory.get_symbol_card(args.symbol_id))
        return 0
    if args.command == "relations":
        print(_format_relations(memory.show_relations(args.symbol_id)))
        return 0
    if args.command == "open":
        print(memory.open_symbol(args.symbol_id))
        return 0
    if args.command == "list":
        print(_format_symbol_list(memory.list_symbols()))
        return 0
    raise ValueError(f"Unknown command {args.command}")


def _run_typer(argv: list[str] | None = None) -> int:
    app = typer.Typer(add_completion=False, no_args_is_help=True)

    @app.command("build")
    def build_command(project_root: str = ".", output: str | None = None) -> None:
        report = SymbolMemory().build(project_root, output)
        print(_format_report(report))
        if report.status == "error":
            raise typer.Exit(code=1)

    @app.command("validate")
    def validate_command(project_root: str = ".", output: str | None = None) -> None:
        report = SymbolMemory().validate(project_root, output)
        print(_format_report(report))
        if report.status == "error":
            raise typer.Exit(code=1)

    @app.command("find")
    def find_command(query: str, output: str | None = None, project_root: str = ".") -> None:
        memory = SymbolMemory(project_root=project_root, output_dir=output)
        print(_format_find_result(memory.find(query)))

    @app.command("show")
    def show_command(symbol_id: int, output: str | None = None, project_root: str = ".") -> None:
        memory = SymbolMemory(project_root=project_root, output_dir=output)
        print(memory.get_symbol_card(symbol_id))

    @app.command("relations")
    def relations_command(symbol_id: int, output: str | None = None, project_root: str = ".") -> None:
        memory = SymbolMemory(project_root=project_root, output_dir=output)
        print(_format_relations(memory.show_relations(symbol_id)))

    @app.command("open")
    def open_command(symbol_id: int, output: str | None = None, project_root: str = ".") -> None:
        memory = SymbolMemory(project_root=project_root, output_dir=output)
        print(memory.open_symbol(symbol_id))

    @app.command("list")
    def list_command(output: str | None = None, project_root: str = ".") -> None:
        memory = SymbolMemory(project_root=project_root, output_dir=output)
        print(_format_symbol_list(memory.list_symbols()))

    try:
        app(args=argv or [], standalone_mode=False)
    except SystemExit as error:  # pragma: no cover - Typer controls exit flow
        return int(error.code)
    except Exception as error:  # pragma: no cover - defensive fallback
        if typer is not None and isinstance(error, typer.Exit):
            return int(error.exit_code)
        raise
    return 0


def _format_report(report: ValidationReport) -> str:
    lines = [
        f"status: {report.status}",
        f"errors: {report.error_count}",
        f"warnings: {report.warning_count}",
    ]
    for issue in report.issues:
        lines.append(f"{issue.severity}: {issue.message}")
    return "\n".join(lines)


def _format_find_result(result: SymbolRecord | list[SymbolRecord]) -> str:
    if isinstance(result, SymbolRecord):
        return json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2)
    payload = [item.model_dump(mode="json") for item in result]
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _format_relations(relations: list[RelationPreview]) -> str:
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


def _format_symbol_list(symbols: list[SymbolRecord]) -> str:
    if not symbols:
        return "[]"
    lines = []
    for symbol in symbols:
        lines.append(f"{symbol.id} {symbol.symbol_type} {symbol.qualified_name}")
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
