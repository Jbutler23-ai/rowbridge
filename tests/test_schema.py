from copy import deepcopy
from decimal import localcontext
import json
from pathlib import Path
import tempfile
import unittest

from rowbridge.schema import RowbridgeError, load_schema, parse_schema
from tests.helpers import schema_data


def column(column_type, **options):
    schema = parse_schema({
        "version": 1, "keys": ["key"],
        "columns": [{"name": "key", "type": "string"},
                    {"name": "value", "type": column_type, **options}],
    })
    return schema.columns[1]


class SchemaTests(unittest.TestCase):
    def test_schema_round_trip_and_normalized_defaults_have_the_same_digest(self):
        original = schema_data()
        schema = parse_schema(original)
        self.assertEqual(parse_schema(schema.to_dict()).digest, schema.digest)
        explicit = deepcopy(original)
        for item in explicit["columns"]:
            for field, default in (("trim", False), ("casefold", False), ("nullable", False),
                                   ("null_values", [])):
                item.setdefault(field, default)
        self.assertEqual(parse_schema(explicit).digest, schema.digest)
        self.assertEqual(len(schema.digest), 64)

    def test_column_order_and_key_order_are_meaningful(self):
        original = schema_data()
        digest = parse_schema(original).digest
        reordered_columns = deepcopy(original)
        reordered_columns["columns"].reverse()
        reordered_keys = deepcopy(original)
        reordered_keys["keys"].reverse()
        self.assertNotEqual(parse_schema(reordered_columns).digest, digest)
        self.assertNotEqual(parse_schema(reordered_keys).digest, digest)

    def test_schema_rejects_unknown_missing_and_duplicate_definitions(self):
        cases = []
        extra = schema_data()
        extra["unknown"] = True
        cases.append(extra)
        extra_column = schema_data()
        extra_column["columns"][0]["unknown"] = True
        cases.append(extra_column)
        missing = schema_data()
        del missing["columns"][0]["type"]
        cases.append(missing)
        duplicate = schema_data()
        duplicate["columns"].append(deepcopy(duplicate["columns"][0]))
        cases.append(duplicate)
        for index, data in enumerate(cases):
            with self.subTest(case=index):
                with self.assertRaises(RowbridgeError):
                    parse_schema(data)

    def test_schema_version_requires_integer_one(self):
        for version in (True, 1.0, "1", 0, 2, None):
            with self.subTest(version=version):
                data = schema_data()
                data["version"] = version
                with self.assertRaises(RowbridgeError):
                    parse_schema(data)

    def test_keys_must_exist_be_unique_and_nonnullable(self):
        for keys in ([], ["missing"], ["part", "part"], ["note"]):
            with self.subTest(keys=keys):
                data = schema_data()
                data["keys"] = keys
                with self.assertRaises(RowbridgeError):
                    parse_schema(data)

    def test_wrong_boolean_types_and_unknown_column_types_are_rejected(self):
        for flag in ("trim", "casefold", "nullable"):
            for value in (0, 1, "true", None, []):
                with self.subTest(flag=flag, value=value):
                    with self.assertRaises(RowbridgeError):
                        column("string", **{flag: value})
        with self.assertRaises(RowbridgeError):
            column("float")
        with self.assertRaises(RowbridgeError):
            column("integer", casefold=True)
        with self.assertRaises(RowbridgeError):
            column("string", null_values=["NULL"])

    def test_names_reject_empty_control_surrogate_and_overlong_values(self):
        for name in ("", "with\nnewline", "with\x00nul", "with\x7fdel", "\ud800", "a" * 129):
            with self.subTest(name=repr(name)):
                data = schema_data()
                data["columns"][2]["name"] = name
                with self.assertRaises(RowbridgeError):
                    parse_schema(data)

    def test_column_count_is_bounded(self):
        for count in (0, 257):
            with self.subTest(count=count):
                data = {"version": 1, "keys": ["column0"],
                        "columns": [{"name": f"column{index}", "type": "string"}
                                    for index in range(count)]}
                with self.assertRaises(RowbridgeError):
                    parse_schema(data)

    def test_strings_preserve_content_unless_normalization_is_requested(self):
        original = "  Straße \n"
        self.assertEqual(column("string").convert(original), original)
        self.assertEqual(column("string", trim=True, casefold=True).convert(original), "strasse")

    def test_null_tokens_are_exact_and_checked_before_normalization(self):
        converter = column("string", nullable=True, null_values=["NULL"], trim=True, casefold=True)
        self.assertIsNone(converter.convert("NULL"))
        self.assertEqual(converter.convert(" NULL "), "null")
        self.assertEqual(converter.convert("null"), "null")
        self.assertEqual(converter.convert(""), "")
        self.assertIsNone(column("string", nullable=True, null_values=[""]).convert(""))

    def test_integers_are_canonical_ascii_values(self):
        converter = column("integer")
        for raw, expected in (("00012", "12"), ("+12", "12"), ("-00012", "-12"), ("-0", "0")):
            with self.subTest(raw=raw):
                self.assertEqual(converter.convert(raw), expected)
        for invalid in ("", "1.0", "1e2", "1_000", " 1", "1 ", "١", "１", "9" * 257):
            with self.subTest(invalid=invalid):
                with self.assertRaises(RowbridgeError):
                    converter.convert(invalid)

    def test_decimal_conversion_is_exact_beyond_context_precision(self):
        raw = "123456789012345678901234567890.1234567890123456789000"
        expected = "123456789012345678901234567890.1234567890123456789"
        converter = column("decimal")
        with localcontext() as context:
            context.prec = 3
            self.assertEqual(converter.convert(raw), expected)
            self.assertEqual(converter.convert("1.000e-30"), "0." + "0" * 29 + "1")
            self.assertEqual(converter.convert("00012.3400"), "12.34")

    def test_decimal_exponents_and_signed_zero_are_bounded_and_canonical(self):
        converter = column("decimal")
        self.assertEqual(converter.convert("-0.000e+1000"), "0")
        self.assertEqual(converter.convert("+0"), "0")
        self.assertEqual(converter.convert("1e1000"), "1" + "0" * 1000)
        self.assertEqual(converter.convert("1e-1000"), "0." + "0" * 999 + "1")
        for invalid in ("1e1001", "1e-1001", "NaN", "Infinity", "-Inf", "1_000", "１.2",
                        "9" * 257, " 1.2", "1.2 "):
            with self.subTest(invalid=invalid):
                with self.assertRaises(RowbridgeError):
                    converter.convert(invalid)

    def test_dates_require_full_iso_format_and_valid_calendar_days(self):
        converter = column("date")
        self.assertEqual(converter.convert("2024-02-29"), "2024-02-29")
        for invalid in ("2023-02-29", "2024-13-01", "2024-00-10", "2024-2-9", "20240229",
                        "2024-02-29T00:00:00", " 2024-02-29", "0000-01-01"):
            with self.subTest(invalid=invalid):
                with self.assertRaises(RowbridgeError):
                    converter.convert(invalid)

    def test_schema_loader_rejects_duplicate_fields_and_nonfinite_constants(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "schema.json"
            texts = ['{"version":1,"version":1}', '{"columns":[{"name":"a","name":"b"}]}',
                     '{"value":NaN}', '{"value":Infinity}',
                     '{"value":' + "9" * 5000 + '}', "[" * 1100 + "0" + "]" * 1100]
            for text in texts:
                with self.subTest(text=text):
                    path.write_text(text, encoding="utf-8")
                    with self.assertRaises(RowbridgeError):
                        load_schema(path)

    def test_schema_loader_accepts_utf8_bom(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "schema.json"
            path.write_text(json.dumps(schema_data()), encoding="utf-8-sig")
            self.assertEqual(load_schema(path).digest, parse_schema(schema_data()).digest)


if __name__ == "__main__":
    unittest.main()
