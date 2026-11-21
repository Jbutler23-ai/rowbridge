"""Measure reconciliation and verify exact expected partitions on a synthetic corpus."""

import argparse
import csv
import json
from pathlib import Path
import platform
import random
import sys
from tempfile import TemporaryDirectory
from time import perf_counter
import tracemalloc

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rowbridge.reconcile import reconcile
from rowbridge.schema import RowbridgeError, parse_schema


def positive_integer(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return number


def run_benchmark(records: int, seed: int) -> dict:
    schema = parse_schema({"version": 1, "keys": ["part", "site"], "columns": [
        {"name": "part", "type": "string"},
        {"name": "site", "type": "string", "trim": True, "casefold": True},
        {"name": "quantity", "type": "integer"},
        {"name": "weight", "type": "decimal"},
    ]})
    order = list(range(records))
    random.Random(seed).shuffle(order)
    remove_count = records // 10
    change_count = records // 5
    removed = set(order[:remove_count])
    changed = set(order[remove_count:remove_count + change_count])
    added = set(range(records, records + remove_count))
    unchanged = set(range(records)) - removed - changed

    def key(index: int) -> tuple[str, str]:
        return f"PART-{index:08d}", f"site-{index % 7}"

    def quantity(index: int) -> int:
        return (index * 37) % 1000

    def row(index: int, right: bool = False) -> list[str]:
        part, site = key(index)
        amount = quantity(index) + (3 if right and index in changed else 0)
        # Numeric spellings differ, but unchanged rows must still compare equal.
        return [part, f" {site.upper()} " if right else site, f"+{amount}" if right else f"{amount:04d}", "1.25" if right else "1.2500"]

    expected_partitions = {
        "added": {key(index) for index in added},
        "removed": {key(index) for index in removed},
        "changed": {key(index) for index in changed},
        "unchanged": {key(index) for index in unchanged},
        "ambiguous": set(),
        "invalid": set(),
    }
    with TemporaryDirectory(prefix="rowbridge-benchmark-") as temporary:
        root = Path(temporary)
        left, right = root / "before.csv", root / "after.csv"
        for path, indices, is_right in (
            (left, range(records), False),
            (right, sorted((set(range(records)) - removed) | added, reverse=True), True),
        ):
            with path.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.writer(stream, lineterminator="\n")
                writer.writerow(["part", "site", "quantity", "weight"])
                writer.writerows(row(index, is_right) for index in indices)

        tracemalloc.start()
        try:
            started = perf_counter()
            report = reconcile(left, right, schema)
            reconcile_seconds = perf_counter() - started
            _, peak_bytes = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()

        actual = {status: set() for status in expected_partitions}
        by_key = {}
        for entry in report["entries"]:
            entry_key = tuple(entry["key"])
            if entry_key in by_key:
                raise RuntimeError(f"Repeated key in reconciliation report: {entry_key}")
            by_key[entry_key] = entry
            if entry["status"] not in actual:
                raise RuntimeError(f"Unknown partition: {entry['status']}")
            actual[entry["status"]].add(entry_key)
        if not report["complete"] or actual != expected_partitions:
            raise RuntimeError("Reconciliation does not match the independently generated key partitions.")
        expected_summary = {status: len(keys) for status, keys in expected_partitions.items()}
        expected_summary.update(unkeyed_left=0, unkeyed_right=0)
        if report["summary"] != expected_summary:
            raise RuntimeError("Summary does not match the independently expected partitions.")
        for index in changed:
            expected_change = [{"column": "quantity", "before": str(quantity(index)), "after": str(quantity(index) + 3)}]
            if by_key[key(index)]["changes"] != expected_change:
                raise RuntimeError(f"Incorrect changed values for {key(index)}")
        for status in ("added", "removed", "unchanged"):
            if any(by_key[item]["changes"] for item in expected_partitions[status]):
                raise RuntimeError(f"Unexpected field changes in the {status} partition.")

        started = perf_counter()
        encoded = json.dumps(report, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
        serialization_seconds = perf_counter() - started
        return {
            "environment": {"python": platform.python_version(), "platform": platform.platform()},
            "corpus": {"generator": "rowbridge-corpus-v1", "seed": seed, "left_records": records, "right_records": records, "left_bytes": left.stat().st_size, "right_bytes": right.stat().st_size},
            "expected_partitions": expected_summary,
            "checks": {"exact_key_partitions": True, "changed_values": True, "complete": True},
            "measurements": {"parse_compare_seconds": round(reconcile_seconds, 6), "peak_traced_python_bytes": peak_bytes, "json_serialization_seconds": round(serialization_seconds, 6), "compact_json_bytes": len(encoded)},
            "measurement_scope": "Parse and compare wall time with tracemalloc enabled. Peak traced Python allocations exclude corpus generation, reference checks, and JSON serialization; this is not process RSS.",
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--records", type=positive_integer, default=10_000)
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = run_benchmark(args.records, args.seed)
        if args.json:
            print(json.dumps(result, ensure_ascii=True, indent=2))
        else:
            print(f"Python {result['environment']['python']} on {result['environment']['platform']}")
            print(f"Corpus: {args.records} rows per source, seed {args.seed}")
            print("Expected partitions: " + json.dumps(result["expected_partitions"], sort_keys=True))
            print("Exact key sets and changed values passed independent checks.")
            print(json.dumps(result["measurements"], indent=2))
            print(result["measurement_scope"])
            print("Measurements describe this local run only. Temporary sources have been removed.")
        return 0
    except (RowbridgeError, OSError, RuntimeError) as error:
        print(f"benchmark: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("benchmark: interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
