from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from rowbridge.cli import main
from tests.helpers import csv_bytes, record, schema_data


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class CommandLineTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.schema_path = self.root / "schema.json"
        self.schema_path.write_text(json.dumps(schema_data()), encoding="utf-8")
        self.left_path = self.root / "left.csv"
        self.right_path = self.root / "right.csv"
        self.left_path.write_bytes(csv_bytes([record(quantity="1")]))
        self.right_path.write_bytes(csv_bytes([record(quantity="2")]))

    def run_cli(self, command, *arguments):
        return subprocess.run(
            [sys.executable, "-m", "rowbridge", command, *map(str, arguments),
             "--schema", str(self.schema_path)],
            cwd=PROJECT_ROOT, capture_output=True, text=True, encoding="utf-8", timeout=30,
        )

    def test_validation_and_comparison_stdout_are_clean_json(self):
        validated = self.run_cli("validate", self.left_path)
        self.assertEqual(validated.returncode, 0, validated.stderr)
        self.assertEqual(validated.stderr, "")
        self.assertEqual(json.loads(validated.stdout)["summary"]["valid_records"], 1)
        compared = self.run_cli("compare", self.left_path, self.right_path)
        self.assertEqual(compared.returncode, 0, compared.stderr)
        self.assertEqual(compared.stderr, "")
        self.assertEqual(json.loads(compared.stdout)["summary"]["changed"], 1)

    def test_invalid_records_return_one_and_still_write_a_useful_report(self):
        self.left_path.write_bytes(csv_bytes([record(quantity="not-an-integer")]))
        destination = self.root / "validation.json"
        result = self.run_cli("validate", self.left_path, "--output", destination)
        self.assertEqual(result.returncode, 1, result.stderr)
        report = json.loads(destination.read_text(encoding="utf-8"))
        self.assertEqual(report["summary"]["invalid_records"], 1)
        self.assertTrue(report["issues"])
        self.assertNotIn("Traceback", result.stderr)

    def test_ambiguous_comparison_returns_one_without_discarding_rows(self):
        self.left_path.write_bytes(csv_bytes([record(), record()]))
        result = self.run_cli("compare", self.left_path, self.right_path)
        self.assertEqual(result.returncode, 1, result.stderr)
        report = json.loads(result.stdout)
        self.assertFalse(report["complete"])
        self.assertEqual(report["summary"]["ambiguous"], 1)
        self.assertEqual(len(report["entries"][0]["left"]), 2)

    def test_fatal_csv_errors_publish_no_json_or_html_files(self):
        self.left_path.write_bytes(b"invalid-utf8\xff")
        output = self.root / "report.json"
        html = self.root / "report.html"
        result = self.run_cli("compare", self.left_path, self.right_path,
                              "--output", output, "--html", html)
        self.assertEqual(result.returncode, 2)
        self.assertTrue(result.stderr.strip())
        self.assertNotIn("Traceback", result.stderr)
        self.assertFalse(output.exists())
        self.assertFalse(html.exists())
        self.assertEqual(result.stdout, "")

    def test_fatal_schema_errors_publish_no_files(self):
        self.schema_path.write_text('{"version":1,"version":1}', encoding="utf-8")
        output = self.root / "report.json"
        result = self.run_cli("validate", self.left_path, "--output", output)
        self.assertEqual(result.returncode, 2)
        self.assertFalse(output.exists())
        self.assertNotIn("Traceback", result.stderr)

    def test_existing_outputs_are_unchanged_and_preflight_prevents_partial_creation(self):
        for existing in ("json", "html"):
            with self.subTest(existing=existing):
                output = self.root / f"report-{existing}.json"
                html = self.root / f"report-{existing}.html"
                protected = output if existing == "json" else html
                other = html if existing == "json" else output
                protected.write_bytes(b"original contents")
                result = self.run_cli("compare", self.left_path, self.right_path,
                                      "--output", output, "--html", html)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(protected.read_bytes(), b"original contents")
                self.assertFalse(other.exists())

    def test_sources_and_schema_cannot_be_used_as_outputs(self):
        for protected in (self.left_path, self.right_path, self.schema_path):
            with self.subTest(protected=protected.name):
                before = protected.read_bytes()
                result = self.run_cli("compare", self.left_path, self.right_path,
                                      "--output", protected)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(protected.read_bytes(), before)

    def test_json_and_html_outputs_cannot_share_a_path(self):
        output = self.root / "combined"
        result = self.run_cli("compare", self.left_path, self.right_path,
                              "--output", output, "--html", output)
        self.assertEqual(result.returncode, 2)
        self.assertFalse(output.exists())

    def test_missing_output_parent_is_not_created(self):
        output = self.root / "missing" / "report.json"
        result = self.run_cli("compare", self.left_path, self.right_path, "--output", output)
        self.assertEqual(result.returncode, 2)
        self.assertFalse(output.parent.exists())

    def test_html_escapes_source_values_and_uses_no_external_assets(self):
        self.left_path.write_bytes(csv_bytes([record(note="<script>alert('test')</script> & text")]))
        output = self.root / "report.html"
        result = self.run_cli("compare", self.left_path, self.right_path, "--html", output)
        self.assertEqual(result.returncode, 0, result.stderr)
        text = output.read_text(encoding="utf-8")
        self.assertIn("&lt;script&gt;", text)
        self.assertNotIn("<script", text.lower())
        self.assertIn("<table", text.lower())
        self.assertNotRegex(text, r'''(?:src|href)=["']https?://''')

    def test_missing_input_returns_a_concise_fatal_error(self):
        result = self.run_cli("validate", self.root / "missing.csv")
        self.assertEqual(result.returncode, 2)
        self.assertTrue(result.stderr.strip())
        self.assertNotIn("Traceback", result.stderr)

    def test_unresolvable_output_path_returns_a_fatal_error_without_writing(self):
        output = self.root / "report.json"
        stdout, stderr = io.StringIO(), io.StringIO()
        arguments = ["compare", str(self.left_path), str(self.right_path),
                     "--schema", str(self.schema_path), "--output", str(output)]
        with patch("rowbridge.cli.Path.resolve", side_effect=RuntimeError("Symlink loop")):
            with redirect_stdout(stdout), redirect_stderr(stderr):
                exit_code = main(arguments)
        self.assertEqual(exit_code, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertTrue(stderr.getvalue().strip())
        self.assertNotIn("Traceback", stderr.getvalue())
        self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
