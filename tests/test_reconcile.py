from copy import deepcopy
import json
from pathlib import Path
import random
import tempfile
import unittest

from rowbridge.ingest import load_dataset
from rowbridge.reconcile import compare_datasets, reconcile
from rowbridge.schema import RowbridgeError, parse_schema
from tests.helpers import csv_bytes, record, schema_data


class ReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.left_path = self.root / "left.csv"
        self.right_path = self.root / "right.csv"
        self.schema = parse_schema(schema_data())

    def compare(self, left, right):
        self.left_path.write_bytes(csv_bytes(left))
        self.right_path.write_bytes(csv_bytes(right))
        return reconcile(self.left_path, self.right_path, self.schema)

    def assert_all_rows_accounted_for(self, report):
        for side in ("left", "right"):
            represented = [row for entry in report["entries"] for row in entry[side]]
            represented += report[side]["unkeyed"]
            expected_records = list(range(1, report[side]["records"] + 1))
            self.assertEqual(sorted(row["record"] for row in represented), expected_records)
            self.assertEqual(len(represented), report[side]["records"])
            self.assertEqual(len(report[side]["unkeyed"]), report["summary"][f"unkeyed_{side}"])

    def test_known_added_removed_changed_and_unchanged_partitions(self):
        report = self.compare(
            [record(part="remove"), record(part="change", quantity="1"), record(part="same")],
            [record(part="add"), record(part="change", quantity="2"), record(part="same")],
        )
        self.assertTrue(report["complete"])
        self.assertEqual(report["summary"], {
            "added": 1, "removed": 1, "changed": 1, "unchanged": 1, "ambiguous": 0,
            "invalid": 0, "unkeyed_left": 0, "unkeyed_right": 0,
        })
        entries = {entry["key"][0]: entry for entry in report["entries"]}
        self.assertEqual(entries["change"]["changes"],
                         [{"column": "quantity", "before": "1", "after": "2"}])
        for key in ("add", "remove", "same"):
            self.assertEqual(entries[key]["changes"], [])
        self.assert_all_rows_accounted_for(report)

    def test_comparison_uses_typed_values_instead_of_raw_spelling(self):
        report = self.compare([record(site=" NORTH ", quantity="+00012", unit_price="1.5000")],
                              [record(site="north", quantity="12", unit_price="15e-1")])
        self.assertEqual(report["summary"]["unchanged"], 1)
        self.assertEqual(report["entries"][0]["changes"], [])
        self.assertTrue(report["complete"])

    def test_string_keys_do_not_guess_numeric_equivalence(self):
        report = self.compare([record(part="001")], [record(part="1")])
        self.assertEqual(report["summary"]["added"], 1)
        self.assertEqual(report["summary"]["removed"], 1)
        self.assertEqual(report["summary"]["unchanged"], 0)

    def test_null_and_blank_produce_a_real_change(self):
        report = self.compare([record(note="NULL")], [record(note="")])
        self.assertEqual(report["entries"][0]["changes"],
                         [{"column": "note", "before": None, "after": ""}])

    def test_decimal_difference_beyond_twenty_eight_digits_is_not_rounded_away(self):
        before = "123456789012345678901234567890.1234567891"
        after = "123456789012345678901234567890.1234567892"
        report = self.compare([record(unit_price=before)], [record(unit_price=after)])
        self.assertEqual(report["summary"]["changed"], 1)
        self.assertEqual(report["entries"][0]["changes"],
                         [{"column": "unit_price", "before": before, "after": after}])

    def test_identical_duplicate_rows_are_ambiguous_not_arbitrarily_matched(self):
        report = self.compare([record(), record()], [record()])
        entry = report["entries"][0]
        self.assertEqual(entry["status"], "ambiguous")
        self.assertEqual(len(entry["left"]), 2)
        self.assertEqual(entry["changes"], [])
        self.assertFalse(report["complete"])
        self.assertEqual(report["left"]["issues"], [])
        self.assert_all_rows_accounted_for(report)

    def test_ambiguity_takes_precedence_over_invalid_values(self):
        report = self.compare([record(), record(quantity="bad")], [record(quantity="different-bad")])
        self.assertEqual(report["entries"][0]["status"], "ambiguous")
        self.assertEqual(report["summary"]["invalid"], 0)
        self.assertFalse(report["complete"])
        self.assert_all_rows_accounted_for(report)

    def test_invalid_known_key_is_never_misclassified_as_added_or_removed(self):
        cases = [([], [record(quantity="bad")]), ([record(quantity="bad")], []),
                 ([record()], [record(quantity="bad")])]
        for left, right in cases:
            with self.subTest(left=left, right=right):
                report = self.compare(left, right)
                self.assertEqual(report["entries"][0]["status"], "invalid")
                self.assertEqual(report["summary"]["added"], 0)
                self.assertEqual(report["summary"]["removed"], 0)
                self.assertFalse(report["complete"])
                self.assert_all_rows_accounted_for(report)

    def test_unkeyed_rows_are_preserved_outside_keyed_entries(self):
        self.left_path.write_bytes(csv_bytes([record(part=""), record(part="same")]) + b"too,few\n")
        self.right_path.write_bytes(csv_bytes([record(part="same"), record(part="other", site=" ")]))
        report = reconcile(self.left_path, self.right_path, self.schema)
        self.assertEqual(report["summary"]["unkeyed_left"], 2)
        self.assertEqual(report["summary"]["unkeyed_right"], 1)
        self.assertEqual(len(report["entries"]), 1)
        self.assertEqual(report["entries"][0]["status"], "unchanged")
        self.assertFalse(report["complete"])
        self.assert_all_rows_accounted_for(report)
        malformed = report["left"]["unkeyed"][1]
        self.assertEqual(malformed["cells"], ["too", "few"])

    def test_typed_key_normalization_can_reveal_duplicates(self):
        data = schema_data()
        data["columns"][0]["type"] = "integer"
        self.schema = parse_schema(data)
        report = self.compare([record(part="0012", site=" NORTH "), record(part="+12", site="north")],
                              [record(part="12", site="North")])
        self.assertEqual(len(report["entries"]), 1)
        self.assertEqual(report["entries"][0]["key"], ["12", "north"])
        self.assertEqual(report["entries"][0]["status"], "ambiguous")
        self.assert_all_rows_accounted_for(report)

    def test_keys_are_compared_as_tuples_and_sorted_lexicographically(self):
        rows = [record(part="a", site="bc"), record(part="ab", site="c"),
                record(part="2"), record(part="10")]
        report = self.compare(rows, list(reversed(rows)))
        self.assertEqual([entry["key"] for entry in report["entries"]],
                         [["10", "north"], ["2", "north"], ["a", "bc"], ["ab", "c"]])
        self.assertEqual(report["summary"]["unchanged"], 4)

    def test_changes_follow_schema_column_order(self):
        report = self.compare([record(quantity="1", unit_price="1", checked="NULL", note="old")],
                              [record(quantity="2", unit_price="2", checked="2024-02-29", note="new")])
        self.assertEqual([change["column"] for change in report["entries"][0]["changes"]],
                         ["quantity", "unit_price", "checked", "note"])

    def test_stale_or_different_schema_digests_are_rejected(self):
        self.left_path.write_bytes(csv_bytes([record()]))
        self.right_path.write_bytes(csv_bytes([record()]))
        changed = schema_data()
        changed["columns"][1]["casefold"] = False
        other_schema = parse_schema(changed)
        left = load_dataset(self.left_path, self.schema)
        right = load_dataset(self.right_path, other_schema)
        with self.assertRaises(RowbridgeError):
            compare_datasets(left, right, self.schema)
        with self.assertRaises(RowbridgeError):
            compare_datasets(left, left, other_schema)

    def test_reports_are_deterministic_and_do_not_include_absolute_paths(self):
        self.left_path.write_bytes(csv_bytes([record(quantity="1")]))
        self.right_path.write_bytes(csv_bytes([record(quantity="2")]))
        first = reconcile(self.left_path, self.right_path, self.schema)
        elsewhere = self.root / "elsewhere"
        elsewhere.mkdir()
        copied_left, copied_right = elsewhere / "left.csv", elsewhere / "right.csv"
        copied_left.write_bytes(self.left_path.read_bytes())
        copied_right.write_bytes(self.right_path.read_bytes())
        self.assertEqual(first, reconcile(copied_left, copied_right, self.schema))
        self.assertNotIn(str(self.root), json.dumps(first))

    def test_two_header_only_inputs_make_a_complete_empty_comparison(self):
        report = self.compare([], [])
        self.assertTrue(report["complete"])
        self.assertEqual(report["entries"], [])
        self.assertTrue(all(value == 0 for value in report["summary"].values()))
        self.assert_all_rows_accounted_for(report)

    def test_seeded_small_inputs_match_an_independent_reference_join(self):
        for seed in range(12):
            randomizer = random.Random(seed)
            left_values = {f"P{index:03}": randomizer.randint(-20, 100) for index in range(30)}
            removed = set(randomizer.sample(sorted(left_values), 5))
            remaining = sorted(set(left_values) - removed)
            edited = set(randomizer.sample(remaining, 7))
            right_values = {key: value + (3 if key in edited else 0)
                            for key, value in left_values.items() if key not in removed}
            additions = {f"P{index:03}": randomizer.randint(-20, 100) for index in range(30, 35)}
            right_values.update(additions)
            left_rows = [record(part=key, quantity=f"{value:+05d}", unit_price="1.500")
                         for key, value in left_values.items()]
            right_rows = [record(part=key, quantity=str(value), unit_price="15e-1")
                          for key, value in right_values.items()]
            randomizer.shuffle(left_rows)
            randomizer.shuffle(right_rows)
            report = self.compare(left_rows, right_rows)
            expected = {}
            for key in set(left_values) | set(right_values):
                if key not in left_values:
                    expected[key] = "added"
                elif key not in right_values:
                    expected[key] = "removed"
                elif left_values[key] != right_values[key]:
                    expected[key] = "changed"
                else:
                    expected[key] = "unchanged"
            with self.subTest(seed=seed):
                actual = {entry["key"][0]: entry["status"] for entry in report["entries"]}
                self.assertEqual(actual, expected)
                self.assertTrue(report["complete"])
                self.assert_all_rows_accounted_for(report)
                for entry in report["entries"]:
                    if entry["status"] == "changed":
                        key = entry["key"][0]
                        self.assertEqual(entry["changes"], [{"column": "quantity",
                                                             "before": str(left_values[key]),
                                                             "after": str(right_values[key])}])


if __name__ == "__main__":
    unittest.main()
