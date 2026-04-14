"""CLI interface for symbol_memory."""

from __future__ import annotations

import argparse
import sys

from pydantic import ValidationError

from symbol_memory.api.memory import SymbolMemory
from symbol_memory.cli.formatting import (
    format_branch_tree,
    format_cli_error,
    format_find_result,
    format_parent,
    format_relations,
    format_report,
    format_symbol_list,
)

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
    show_parser.add_argument("symbol_id")
    show_parser.add_argument("--output", default=None)
    show_parser.add_argument("--project-root", default=".")

    relations_parser = subparsers.add_parser("relations")
    relations_parser.add_argument("symbol_id")
    relations_parser.add_argument("--output", default=None)
    relations_parser.add_argument("--project-root", default=".")

    open_parser = subparsers.add_parser("open")
    open_parser.add_argument("symbol_id")
    open_parser.add_argument("--output", default=None)
    open_parser.add_argument("--project-root", default=".")

    list_parser = subparsers.add_parser("list")
    list_parser.add_argument("--output", default=None)
    list_parser.add_argument("--project-root", default=".")

    branches_parser = subparsers.add_parser("branches")
    branches_parser.add_argument("symbol_id")
    branches_parser.add_argument("--output", default=None)
    branches_parser.add_argument("--project-root", default=".")

    children_parser = subparsers.add_parser("children")
    children_parser.add_argument("symbol_id")
    children_parser.add_argument("--output", default=None)
    children_parser.add_argument("--project-root", default=".")

    parent_parser = subparsers.add_parser("parent")
    parent_parser.add_argument("symbol_id")
    parent_parser.add_argument("--output", default=None)
    parent_parser.add_argument("--project-root", default=".")

    roots_parser = subparsers.add_parser("roots")
    roots_parser.add_argument("--output", default=None)
    roots_parser.add_argument("--project-root", default=".")

    return parser


def _dispatch_args(args: argparse.Namespace) -> int:
    if args.command == "build":
        report = SymbolMemory().build(args.project_root, args.output)
        print(format_report(report))
        return 1 if report.status == "error" else 0
    if args.command == "validate":
        report = SymbolMemory().validate(args.project_root, args.output)
        print(format_report(report))
        return 1 if report.status == "error" else 0

    memory = SymbolMemory(project_root=args.project_root, output_dir=args.output)
    try:
        if args.command == "find":
            print(format_find_result(memory.find(args.query)))
            return 0
        if args.command == "show":
            print(memory.get_symbol_card(args.symbol_id))
            return 0
        if args.command == "relations":
            print(format_relations(memory.show_relations(args.symbol_id)))
            return 0
        if args.command == "open":
            print(memory.open_symbol(args.symbol_id))
            return 0
        if args.command == "list":
            print(format_symbol_list(memory.list_symbols()))
            return 0
        if args.command == "branches":
            print(format_branch_tree(memory.list_branches(args.symbol_id)))
            return 0
        if args.command == "children":
            print(format_symbol_list(memory.list_children(args.symbol_id)))
            return 0
        if args.command == "parent":
            print(format_parent(memory.get_parent(args.symbol_id)))
            return 0
        if args.command == "roots":
            print(format_symbol_list(memory.list_roots()))
            return 0
    except (FileNotFoundError, KeyError, OSError, UnicodeDecodeError, ValidationError, ValueError) as error:
        print(format_cli_error(error), file=sys.stderr)
        return 1
    raise ValueError(f"Unknown command {args.command}")


def _run_typer(argv: list[str] | None = None) -> int:
    app = typer.Typer(add_completion=False, no_args_is_help=True)

    @app.command("build")
    def build_command(project_root: str = ".", output: str | None = None) -> None:
        report = SymbolMemory().build(project_root, output)
        print(format_report(report))
        if report.status == "error":
            raise typer.Exit(code=1)

    @app.command("validate")
    def validate_command(project_root: str = ".", output: str | None = None) -> None:
        report = SymbolMemory().validate(project_root, output)
        print(format_report(report))
        if report.status == "error":
            raise typer.Exit(code=1)

    @app.command("find")
    def find_command(query: str, output: str | None = None, project_root: str = ".") -> None:
        memory = SymbolMemory(project_root=project_root, output_dir=output)
        _print_or_exit(lambda: format_find_result(memory.find(query)))

    @app.command("show")
    def show_command(symbol_id: str, output: str | None = None, project_root: str = ".") -> None:
        memory = SymbolMemory(project_root=project_root, output_dir=output)
        _print_or_exit(lambda: memory.get_symbol_card(symbol_id))

    @app.command("relations")
    def relations_command(symbol_id: str, output: str | None = None, project_root: str = ".") -> None:
        memory = SymbolMemory(project_root=project_root, output_dir=output)
        _print_or_exit(lambda: format_relations(memory.show_relations(symbol_id)))

    @app.command("open")
    def open_command(symbol_id: str, output: str | None = None, project_root: str = ".") -> None:
        memory = SymbolMemory(project_root=project_root, output_dir=output)
        _print_or_exit(lambda: memory.open_symbol(symbol_id))

    @app.command("list")
    def list_command(output: str | None = None, project_root: str = ".") -> None:
        memory = SymbolMemory(project_root=project_root, output_dir=output)
        _print_or_exit(lambda: format_symbol_list(memory.list_symbols()))

    @app.command("branches")
    def branches_command(symbol_id: str, output: str | None = None, project_root: str = ".") -> None:
        memory = SymbolMemory(project_root=project_root, output_dir=output)
        _print_or_exit(lambda: format_branch_tree(memory.list_branches(symbol_id)))

    @app.command("children")
    def children_command(symbol_id: str, output: str | None = None, project_root: str = ".") -> None:
        memory = SymbolMemory(project_root=project_root, output_dir=output)
        _print_or_exit(lambda: format_symbol_list(memory.list_children(symbol_id)))

    @app.command("parent")
    def parent_command(symbol_id: str, output: str | None = None, project_root: str = ".") -> None:
        memory = SymbolMemory(project_root=project_root, output_dir=output)
        _print_or_exit(lambda: format_parent(memory.get_parent(symbol_id)))

    @app.command("roots")
    def roots_command(output: str | None = None, project_root: str = ".") -> None:
        memory = SymbolMemory(project_root=project_root, output_dir=output)
        _print_or_exit(lambda: format_symbol_list(memory.list_roots()))

    try:
        app(args=argv, standalone_mode=False)
    except SystemExit as error:  # pragma: no cover - Typer controls exit flow
        return int(error.code)
    except Exception as error:  # pragma: no cover - defensive fallback
        if typer is not None and isinstance(error, typer.Exit):
            return int(error.exit_code)
        raise
    return 0


def _print_or_exit(render) -> None:
    try:
        print(render())
    except (FileNotFoundError, KeyError, OSError, UnicodeDecodeError, ValidationError, ValueError) as error:
        print(format_cli_error(error), file=sys.stderr)
        raise typer.Exit(code=1) from error
