from __future__ import annotations

import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from symbol_memory import SymbolMemory, symbol
from symbol_memory.cli import run
from symbol_memory.core.ids import (
    is_descendant_id,
    parent_symbol_id,
    parse_symbol_id,
    symbol_id_sort_key,
    validate_symbol_id,
)
from symbol_memory.indexing import scan_project


class ValidationUpgradeTests(unittest.TestCase):
    def test_symbol_id_helpers_validate_parse_and_sort(self) -> None:
        self.assertEqual(validate_symbol_id("1.2.3"), "1.2.3")
        self.assertEqual(parse_symbol_id("1.10"), (1, 10))
        self.assertEqual(parent_symbol_id("1.2.3"), "1.2")
        self.assertIsNone(parent_symbol_id("7"))
        self.assertTrue(is_descendant_id("1", "1.2.3"))
        self.assertFalse(is_descendant_id("1", "10.2"))
        self.assertEqual(
            sorted(["1.10", "1", "2", "1.2"], key=symbol_id_sort_key),
            ["1", "1.2", "1.10", "2"],
        )

    def test_symbol_id_helpers_reject_invalid_formats(self) -> None:
        invalid_values = ["", " 1", "1 ", ".1", "1.", "1..2", "a.b", "01", "1.01"]
        for value in invalid_values:
            with self.assertRaises(ValueError, msg=value):
                validate_symbol_id(value)

    def test_symbol_decorator_preserves_object_and_keeps_string_ids(self) -> None:
        def sample() -> str:
            return "ok"

        decorated = symbol(
            "1.1",
            r=["1", "2.4"],
            role="auth",
            summary="Checks access",
            notes=None,
            tags=None,
        )(sample)

        self.assertIs(decorated, sample)
        self.assertEqual(
            decorated.__symbol_metadata__,
            {
                "id": "1.1",
                "r": ["1", "2.4"],
                "role": "auth",
                "summary": "Checks access",
                "notes": None,
                "tags": [],
                "expose": True,
                "entrypoint": False,
            },
        )

    def test_scan_accepts_string_relations_and_optional_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "module.py").write_text(
                "from symbol_memory import symbol\n\n"
                "@symbol('1', r=[], role='auth', summary='Works')\n"
                "def handler():\n"
                "    return True\n\n"
                "@symbol('1.1', r=['1'], role='auth-helper', summary='Helps')\n"
                "def helper():\n"
                "    return True\n",
                encoding="utf-8",
            )

            records, issues = scan_project(root)

        self.assertEqual([record.id for record in records], ["1", "1.1"])
        self.assertEqual(records[1].relation_ids, ["1"])
        self.assertEqual(records[1].tags, [])
        self.assertEqual(issues, [])

    def test_scan_rejects_numeric_ids_and_relations(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "broken.py").write_text(
                "from symbol_memory import symbol\n\n"
                "@symbol(1, r=[2], role='auth', summary='Broken')\n"
                "def broken():\n"
                "    return None\n",
                encoding="utf-8",
            )

            _, issues = scan_project(root)

        codes = {issue.code for issue in issues}
        self.assertIn("invalid_symbol_id_argument", codes)
        self.assertIn("invalid_symbol_relations", codes)
        self.assertTrue(all(issue.stage == "parse" for issue in issues))

    def test_scan_rejects_invalid_string_id_shapes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "broken.py").write_text(
                "from symbol_memory import symbol\n\n"
                "@symbol('1.', r=['2'], role='auth', summary='Broken id')\n"
                "def broken_a():\n"
                "    return None\n\n"
                "@symbol('2', r=['01'], role='auth', summary='Broken relation')\n"
                "def broken_b():\n"
                "    return None\n",
                encoding="utf-8",
            )

            _, issues = scan_project(root)

        self.assertIn("invalid_symbol_id_argument", {issue.code for issue in issues})
        self.assertIn("invalid_symbol_relations", {issue.code for issue in issues})

    def test_scan_reports_duplicate_ids_after_normalization(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "module.py").write_text(
                "from symbol_memory import symbol\n\n"
                "@symbol('1', r=[], role='auth', summary='First')\n"
                "def first():\n"
                "    return True\n\n"
                "@symbol('1', r=[], role='auth', summary='Second')\n"
                "def second():\n"
                "    return True\n",
                encoding="utf-8",
            )

            _, issues = scan_project(root)

        duplicate = next(issue for issue in issues if issue.code == "duplicate_symbol_id")
        self.assertEqual(duplicate.symbol_id, "1")
        self.assertEqual(duplicate.stage, "scan")

    def test_build_reports_missing_relation_with_resolve_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "module.py").write_text(
                "from symbol_memory import symbol\n\n"
                "@symbol('1', r=['9.9'], role='auth', summary='Broken link')\n"
                "def handler():\n"
                "    return True\n",
                encoding="utf-8",
            )

            report = SymbolMemory(root).build()
            card = (root / ".symbol_memory" / "symbols" / "1.md").read_text(encoding="utf-8")

        self.assertEqual(report.status, "error")
        relation_issue = next(issue for issue in report.issues if issue.code == "missing_relation_id")
        self.assertEqual(relation_issue.stage, "resolve")
        self.assertEqual(relation_issue.field, "r")
        self.assertIn("Remove '9.9' from r", relation_issue.hint)
        self.assertIn("- 9.9 - unresolved", card)

    def test_build_reports_missing_direct_parent_for_branch_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "module.py").write_text(
                "from symbol_memory import symbol\n\n"
                "@symbol('1.1', r=[], role='auth', summary='Orphan branch')\n"
                "def orphan():\n"
                "    return True\n",
                encoding="utf-8",
            )

            report = SymbolMemory(root).build()
            project_map = (root / ".symbol_memory" / "project_map.md").read_text(encoding="utf-8")
            card = (root / ".symbol_memory" / "symbols" / "1.1.md").read_text(encoding="utf-8")

        self.assertEqual(report.status, "error")
        parent_issue = next(issue for issue in report.issues if issue.code == "missing_parent_symbol_id")
        self.assertEqual(parent_issue.symbol_id, "1.1")
        self.assertIn("- parent: 1", card)
        self.assertIn("## Orphaned Symbols", project_map)

    def test_build_writes_hierarchy_into_cards_and_project_map_in_sorted_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "module.py").write_text(
                "from symbol_memory import symbol\n\n"
                "@symbol('1', r=[], role='auth', summary='Root')\n"
                "def root_symbol():\n"
                "    return True\n\n"
                "@symbol('1.10', r=[], role='auth', summary='Later child')\n"
                "def child_ten():\n"
                "    return True\n\n"
                "@symbol('1.2', r=[], role='auth', summary='Earlier child')\n"
                "def child_two():\n"
                "    return True\n",
                encoding="utf-8",
            )

            report = SymbolMemory(root).build()
            card = (root / ".symbol_memory" / "symbols" / "1.md").read_text(encoding="utf-8")
            project_map = (root / ".symbol_memory" / "project_map.md").read_text(encoding="utf-8")

        self.assertEqual(report.status, "ok")
        self.assertLess(card.index("- child: 1.2"), card.index("- child: 1.10"))
        self.assertLess(project_map.index("  - 1.2"), project_map.index("  - 1.10"))

    def test_exact_find_and_hierarchy_queries_remain_separate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "module.py").write_text(
                "from symbol_memory import symbol\n\n"
                "@symbol('1', r=['2'], role='auth', summary='Root auth')\n"
                "def auth_root():\n"
                "    return True\n\n"
                "@symbol('1.1', r=['1.2'], role='auth-helper', summary='Login helper')\n"
                "def login_helper():\n"
                "    return True\n\n"
                "@symbol('1.1.1', r=[], role='auth-helper', summary='Deep helper')\n"
                "def deep_helper():\n"
                "    return True\n\n"
                "@symbol('1.2', r=[], role='auth-helper', summary='Token helper')\n"
                "def token_helper():\n"
                "    return True\n\n"
                "@symbol('2', r=[], role='shared', summary='Shared util')\n"
                "def shared_util():\n"
                "    return True\n",
                encoding="utf-8",
            )

            memory = SymbolMemory(root)
            report = memory.build()

            exact = memory.find("1")
            branch_ids = [symbol.id for symbol in memory.list_branches("1")]
            child_ids = [symbol.id for symbol in memory.list_children("1")]
            parent = memory.get_parent("1.1.1")
            roots = [symbol.id for symbol in memory.list_roots()]

        self.assertEqual(report.status, "ok")
        self.assertEqual(exact.id, "1")
        self.assertEqual(branch_ids, ["1", "1.1", "1.1.1", "1.2"])
        self.assertEqual(child_ids, ["1.1", "1.2"])
        self.assertEqual(parent.id, "1.1")
        self.assertEqual(roots, ["1", "2"])

    def test_find_still_supports_name_and_qualified_name_queries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pkg.py").write_text(
                "from symbol_memory import symbol\n\n"
                "@symbol('1', r=[], role='auth', summary='Root auth')\n"
                "def auth_root():\n"
                "    return True\n\n"
                "@symbol('2', r=[], role='shared', summary='Shared util')\n"
                "def shared_util():\n"
                "    return True\n",
                encoding="utf-8",
            )

            memory = SymbolMemory(root)
            report = memory.build()
            by_name = memory.find("auth_root")
            by_qualified = memory.find("pkg.shared_util")
            by_substring = memory.find("shared")

        self.assertEqual(report.status, "ok")
        self.assertEqual([item.id for item in by_name], ["1"])
        self.assertEqual([item.id for item in by_qualified], ["2"])
        self.assertEqual([item.id for item in by_substring], ["2"])

    def test_validate_passes_after_build_and_detects_artifact_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            module = root / "module.py"
            module.write_text(
                "from symbol_memory import symbol\n\n"
                "@symbol('1', r=[], role='auth', summary='Root auth')\n"
                "def auth_root():\n"
                "    return True\n",
                encoding="utf-8",
            )

            memory = SymbolMemory(root)
            build_report = memory.build()
            ok_report = memory.validate()

            module.write_text(
                "from symbol_memory import symbol\n\n"
                "@symbol('1', r=[], role='auth', summary='Root auth changed')\n"
                "def auth_root():\n"
                "    return True\n",
                encoding="utf-8",
            )
            drift_report = SymbolMemory(root).validate()

        self.assertEqual(build_report.status, "ok")
        self.assertEqual(ok_report.status, "ok")
        self.assertEqual(drift_report.status, "error")
        self.assertIn("symbol_index_mismatch", {issue.code for issue in drift_report.issues})

    def test_open_symbol_returns_expected_source_slice(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "module.py").write_text(
                "from symbol_memory import symbol\n\n"
                "@symbol('1', r=[], role='auth', summary='Root auth')\n"
                "def auth_root():\n"
                "    value = True\n"
                "    return value\n",
                encoding="utf-8",
            )

            memory = SymbolMemory(root)
            report = memory.build()
            source = memory.open_symbol("1")

        self.assertEqual(report.status, "ok")
        self.assertIn("@symbol('1', r=[], role='auth', summary='Root auth')", source)
        self.assertIn("return value", source)

    def test_cli_branch_commands_and_errors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "module.py").write_text(
                "from symbol_memory import symbol\n\n"
                "@symbol('1', r=[], role='auth', summary='Root auth')\n"
                "def auth_root():\n"
                "    return True\n\n"
                "@symbol('1.1', r=[], role='auth-helper', summary='Login helper')\n"
                "def login_helper():\n"
                "    return True\n\n"
                "@symbol('2', r=[], role='shared', summary='Shared util')\n"
                "def shared_util():\n"
                "    return True\n",
                encoding="utf-8",
            )

            build_stdout = io.StringIO()
            with contextlib.redirect_stdout(build_stdout):
                build_code = run(["build", str(root)])

            branches_stdout = io.StringIO()
            with contextlib.redirect_stdout(branches_stdout):
                branches_code = run(["branches", "1", "--project-root", str(root)])

            children_stdout = io.StringIO()
            with contextlib.redirect_stdout(children_stdout):
                children_code = run(["children", "1", "--project-root", str(root)])

            roots_stdout = io.StringIO()
            with contextlib.redirect_stdout(roots_stdout):
                roots_code = run(["roots", "--project-root", str(root)])

            parent_stdout = io.StringIO()
            with contextlib.redirect_stdout(parent_stdout):
                parent_code = run(["parent", "1", "--project-root", str(root)])

            query_stderr = io.StringIO()
            with contextlib.redirect_stderr(query_stderr):
                show_code = run(["show", "9", "--project-root", str(root)])

        self.assertEqual(build_code, 0)
        self.assertEqual(branches_code, 0)
        self.assertIn("- 1 function module.auth_root", branches_stdout.getvalue())
        self.assertIn("  - 1.1 function module.login_helper", branches_stdout.getvalue())
        self.assertEqual(children_code, 0)
        self.assertIn("1.1 function module.login_helper", children_stdout.getvalue())
        self.assertEqual(roots_code, 0)
        self.assertIn("1 function module.auth_root", roots_stdout.getvalue())
        self.assertIn("2 function module.shared_util", roots_stdout.getvalue())
        self.assertEqual(parent_code, 0)
        self.assertEqual(parent_stdout.getvalue().strip(), "none")
        self.assertEqual(show_code, 1)
        self.assertIn("error: Unknown symbol card for id 9", query_stderr.getvalue())

    def test_cli_parent_and_validate_commands_cover_success_and_failure_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            module = root / "module.py"
            module.write_text(
                "from symbol_memory import symbol\n\n"
                "@symbol('1', r=[], role='auth', summary='Root auth')\n"
                "def auth_root():\n"
                "    return True\n\n"
                "@symbol('1.1', r=['1'], role='auth-helper', summary='Helper')\n"
                "def auth_helper():\n"
                "    return True\n",
                encoding="utf-8",
            )

            self.assertEqual(run(["build", str(root)]), 0)

            parent_stdout = io.StringIO()
            with contextlib.redirect_stdout(parent_stdout):
                parent_code = run(["parent", "1.1", "--project-root", str(root)])

            module.write_text(
                "from symbol_memory import symbol\n\n"
                "@symbol('1', r=[], role='auth', summary='Changed root')\n"
                "def auth_root():\n"
                "    return True\n\n"
                "@symbol('1.1', r=['1'], role='auth-helper', summary='Helper')\n"
                "def auth_helper():\n"
                "    return True\n",
                encoding="utf-8",
            )
            validate_stdout = io.StringIO()
            with contextlib.redirect_stdout(validate_stdout):
                validate_code = run(["validate", str(root)])

        self.assertEqual(parent_code, 0)
        self.assertIn("1 function module.auth_root", parent_stdout.getvalue())
        self.assertEqual(validate_code, 1)
        self.assertIn("symbol_index_mismatch", validate_stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
