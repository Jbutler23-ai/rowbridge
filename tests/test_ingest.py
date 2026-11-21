import csv
import hashlib
from pathlib import Path
import tempfile
import unittest

from rowbridge.ingest import load_dataset
from rowbridge.schema import RowbridgeError, parse_schema
from tests.helpers import csv_bytes, record, schema_data


class IngestTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.path = self.root / "inventory.csv"
        self.schema = parse_schema(schema_data())

    def load(self, content):
        self.path.write_bytes(content)
        return load_dataset(self.path, self.schema)

    def test_valid_row_preserves_raw_values_and_records_typed_values(self):
        original = record(site=" NORTH ", quantity="+00012", unit_price="1.5000", checked="NULL")
        dataset = self.load(csv_bytes([original]))
        row = dataset.rows[0]
        self.assertEqual(row["raw"], original)
        self.assertEqual(row["values"], {
            "part": "P001", "site": "north", "quantity": "12", "unit_price": "1.5",
            "checked": None, "note": "",
        })
        self.assertEqual(row["key"], ["P001", "north"])
        self.assertEqual(row["record"], 1)
        self.assertEqual((row["line_start"], row["line_end"]), (2, 2))
        self.assertEqual(dataset.to_dict()["summary"],
                         {"records": 1, "valid_records": 1, "invalid_records": 0})

    def test_source_hash_covers_exact_original_bytes_including_bom(self):
        contents = b"\xef\xbb\xbf" + csv_bytes([record()])
        dataset = self.load(contents)
        self.assertEqual(dataset.source, {
            "name": self.path.name, "sha256": hashlib.sha256(contents).hexdigest(),
            "size_bytes": len(contents),
        })
        self.assertEqual(dataset.schema_sha256, self.schema.digest)
        self.assertEqual(dataset.rows[0]["key"], ["P001", "north"])

    def test_later_source_changes_do_not_change_a_loaded_dataset(self):
        contents = csv_bytes([record(quantity="1")])
        dataset = self.load(contents)
        self.path.write_bytes(csv_bytes([record(quantity="999")]))
        self.assertEqual(dataset.rows[0]["values"]["quantity"], "1")
        self.assertEqual(dataset.source["sha256"], hashlib.sha256(contents).hexdigest())
        self.assertEqual(load_dataset(self.path, self.schema).rows[0]["values"]["quantity"], "999")

    def test_column_reordering_is_allowed_but_headers_must_match_exactly(self):
        columns = [column["name"] for column in schema_data()["columns"]]
        original = record(note="comma, and quote \"")
        normal = self.load(csv_bytes([original]))
        reordered = self.load(csv_bytes([original], columns=list(reversed(columns))))
        self.assertEqual(normal.rows[0]["values"], reordered.rows[0]["values"])
        self.assertEqual(normal.rows[0]["key"], reordered.rows[0]["key"])
        for header in ("part,part,quantity,unit_price,checked,note\n",
                       "part,site,quantity,unit_price,checked\n",
                       "part,site,quantity,unit_price,checked,note,extra\n",
                       " part,site,quantity,unit_price,checked,note\n"):
            with self.subTest(header=header):
                with self.assertRaises(RowbridgeError):
                    self.load(header.encode("utf-8"))

    def test_header_only_file_is_valid_but_empty_file_is_fatal(self):
        dataset = self.load(csv_bytes([]))
        self.assertEqual(dataset.rows, ())
        self.assertEqual(dataset.issues, ())
        self.assertEqual(dataset.to_dict()["summary"],
                         {"records": 0, "valid_records": 0, "invalid_records": 0})
        with self.assertRaises(RowbridgeError):
            self.load(b"")

    def test_multiline_cells_report_physical_line_spans(self):
        dataset = self.load(csv_bytes([
            record(part="P001", note="first line\nsecond line"),
            record(part="P002", note="one line"),
            record(part="P003", note="another\nmultiline\nvalue"),
        ]))
        self.assertEqual([(row["record"], row["line_start"], row["line_end"])
                          for row in dataset.rows], [(1, 2, 3), (2, 4, 4), (3, 5, 7)])
        self.assertEqual(dataset.rows[0]["values"]["note"], "first line\nsecond line")

    def test_invalid_nonkey_values_retain_a_known_key_and_all_errors(self):
        dataset = self.load(csv_bytes([record(quantity="not-an-int", checked="2023-02-29")]))
        row = dataset.rows[0]
        self.assertEqual(row["key"], ["P001", "north"])
        self.assertNotIn("quantity", row["values"])
        self.assertNotIn("checked", row["values"])
        self.assertEqual({error["column"] for error in row["errors"]}, {"quantity", "checked"})
        self.assertEqual(len(dataset.issues), 2)
        for issue in dataset.issues:
            self.assertEqual((issue["record"], issue["line_start"], issue["line_end"]), (1, 2, 2))
        self.assertEqual(dataset.to_dict()["summary"]["invalid_records"], 1)

    def test_empty_or_normalized_empty_keys_are_invalid_and_unkeyed(self):
        dataset = self.load(csv_bytes([record(part=""), record(part="P002", site="   ")]))
        self.assertTrue(all(row["key"] is None for row in dataset.rows))
        self.assertEqual(dataset.to_dict()["summary"]["invalid_records"], 2)
        self.assertTrue(all(row["errors"] for row in dataset.rows))

    def test_wrong_row_width_and_blank_lines_are_retained_as_invalid_records(self):
        header = csv_bytes([])
        content = header + b"P001,north\n\nP002,north,1,1.0,NULL,note,extra\n"
        dataset = self.load(content)
        self.assertEqual(len(dataset.rows), 3)
        self.assertEqual(dataset.to_dict()["summary"],
                         {"records": 3, "valid_records": 0, "invalid_records": 3})
        for index, row in enumerate(dataset.rows, 1):
            self.assertEqual(row["record"], index)
            self.assertEqual(row["raw"], {})
            self.assertEqual(row["values"], {})
            self.assertIsNone(row["key"])
            self.assertTrue(row["errors"])

    def test_null_and_empty_string_remain_distinct(self):
        dataset = self.load(csv_bytes([record(part="P001", note="NULL"), record(part="P002", note="")]))
        self.assertIsNone(dataset.rows[0]["values"]["note"])
        self.assertEqual(dataset.rows[1]["values"]["note"], "")
        self.assertEqual(dataset.issues, ())

    def test_malformed_csv_and_invalid_utf8_are_fatal(self):
        header = csv_bytes([])
        contents = [header + b'P001,north,1,1.0,NULL,"unterminated\n',
                    header + b'P001,north,1,1.0,NULL,"quoted"trailing\n',
                    header + b"P001,north,1,1.0,NULL,\xff\n"]
        for content in contents:
            with self.subTest(content=content[-30:]):
                with self.assertRaises(RowbridgeError):
                    self.load(content)

    def test_csv_field_overflow_is_fatal_instead_of_truncated(self):
        contents = csv_bytes([record(note="x" * (csv.field_size_limit() + 1))])
        with self.assertRaises(RowbridgeError):
            self.load(contents)

    def test_oversized_input_is_rejected(self):
        with self.path.open("wb") as handle:
            handle.truncate(64 * 1024 * 1024 + 1)
        with self.assertRaises(RowbridgeError):
            load_dataset(self.path, self.schema)


if __name__ == "__main__":
    unittest.main()
