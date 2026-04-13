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

from symbol_memory.cli import run
from symbol_memory.decorator import symbol
from symbol_memory.query import SymbolMemory
from symbol_memory.scanner import scan_project


class ValidationUpgradeTests(unittest.TestCase):
    def test_symbol_decorator_preserves_object_and_normalizes_optional_metadata(self) -> None:
        def sample() -> str:
            return "ok"

        decorated = symbol(
            7,
            r=[],
            role="auth",
            summary="Checks access",
            notes=None,
            tags=None,
        )(sample)

        self.assertIs(decorated, sample)
        self.assertEqual(
            decorated.__symbol_metadata__,
            {
                "id": 7,
                "r": [],
                "role": "auth",
                "summary": "Checks access",
                "notes": None,
                "tags": [],
                "expose": True,
                "entrypoint": False,
            },
        )

    def test_scan_accepts_empty_relations_and_optional_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "module.py").write_text(
                "from symbol_memory import symbol\n\n"
                "@symbol(1, r=[], role='auth', summary='Works')\n"
                "def handler():\n"
                "    return True\n",
                encoding="utf-8",
            )

            records, issues = scan_project(root)

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].relation_ids, [])
        self.assertEqual(records[0].tags, [])
        self.assertEqual(issues, [])

    def test_scan_reports_multiple_precise_decorator_errors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "broken.py").write_text(
                "from symbol_memory import symbol\n\n"
                "@symbol('bad', role='', extra=1)\n"
                "def broken():\n"
                "    return None\n",
                encoding="utf-8",
            )

            _, issues = scan_project(root)

        codes = {issue.code for issue in issues}
        self.assertIn("invalid_symbol_id_argument", codes)
        self.assertIn("missing_symbol_keyword", codes)
        self.assertIn("unknown_symbol_keyword", codes)
        self.assertIn("invalid_symbol_role", codes)
        self.assertTrue(all(issue.stage == "parse" for issue in issues))
        self.assertTrue(any(issue.field == "role" for issue in issues))
        self.assertTrue(any(issue.hint for issue in issues))

    def test_build_reports_missing_relation_with_resolve_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "module.py").write_text(
                "from symbol_memory import symbol\n\n"
                "@symbol(1, r=[99], role='auth', summary='Broken link')\n"
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
        self.assertIn("Remove 99 from r", relation_issue.hint)
        self.assertIn("- 99 - unresolved", card)

    def test_cli_reports_validation_summary_and_query_errors_cleanly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "module.py").write_text(
                "from symbol_memory import symbol\n\n"
                "@symbol(1, r=[2], role='auth', summary='Broken link')\n"
                "def handler():\n"
                "    return True\n",
                encoding="utf-8",
            )

            build_stdout = io.StringIO()
            with contextlib.redirect_stdout(build_stdout):
                build_code = run(["build", str(root)])

            query_stderr = io.StringIO()
            with contextlib.redirect_stderr(query_stderr):
                list_code = run(["show", "99", "--project-root", str(root)])

        self.assertEqual(build_code, 1)
        self.assertIn("error missing_relation_id [resolve]", build_stdout.getvalue())
        self.assertIn("hint:", build_stdout.getvalue())
        self.assertEqual(list_code, 1)
        self.assertIn("error: Unknown symbol card for id 99", query_stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
