"""Check a clean comparison and an unresolved review using fictional inventory."""

import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rowbridge.cli import main as cli_main


def main() -> None:
    examples = ROOT / "examples"
    with TemporaryDirectory(prefix="rowbridge-demo-") as temporary:
        root = Path(temporary)
        for name, expected_exit, expected_summary in (
            ("after", 0, {"added": 1, "removed": 1, "changed": 1, "unchanged": 2, "ambiguous": 0, "invalid": 0, "unkeyed_left": 0, "unkeyed_right": 0}),
            ("review", 1, {"added": 1, "removed": 1, "changed": 0, "unchanged": 2, "ambiguous": 1, "invalid": 1, "unkeyed_left": 0, "unkeyed_right": 1}),
        ):
            output = root / f"{name}.json"
            html = root / f"{name}.html"
            status = cli_main([
                "compare", str(examples / "inventory-before.csv"), str(examples / f"inventory-{name}.csv"),
                "--schema", str(examples / "inventory-schema.json"), "--output", str(output), "--html", str(html),
            ])
            if status != expected_exit:
                raise RuntimeError(f"{name}: expected exit {expected_exit}, got {status}")
            report = json.loads(output.read_text(encoding="utf-8"))
            if report["summary"] != expected_summary:
                raise RuntimeError(f"{name}: unexpected partitions: {report['summary']}")
            if report["complete"] != (name == "after"):
                raise RuntimeError(f"{name}: incorrect completion state")
            entries = {tuple(entry["key"]): entry for entry in report["entries"]}
            if name == "after":
                expected_change = [{"column": "quantity", "before": "5", "after": "7"}]
                if entries[("P-200", "south")]["changes"] != expected_change:
                    raise RuntimeError("Typed quantity change was not preserved.")
            elif len(entries[("P-200", "south")]["right"]) != 2:
                raise RuntimeError("Duplicate source records were lost.")
            if "<table" not in html.read_text(encoding="utf-8"):
                raise RuntimeError("The HTML report is missing its record table.")
            print(f"{name}: " + json.dumps(report["summary"], sort_keys=True))
        print("Clean and unresolved comparisons matched their expected results.")
        print("Both JSON and HTML reports were checked. Temporary files are removed on exit.")


if __name__ == "__main__":
    main()
