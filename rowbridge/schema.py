"""Explicit conversion rules shared by both sides of a comparison."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re


class RowbridgeError(ValueError):
    """An input or operation cannot be handled under the declared rules."""


_INTEGER = re.compile(r"[+-]?[0-9]+\Z")
_DECIMAL = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?\Z")
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}\Z")
_TYPES = {"string", "integer", "decimal", "date"}


def _canonical_json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":"))


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise RowbridgeError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def _constant(value):
    raise RowbridgeError(f"Invalid JSON constant: {value}")


def _name(value):
    return (isinstance(value, str) and 0 < len(value) <= 128
            and all(ord(c) >= 32 and not (127 <= ord(c) <= 159)
                    and not (0xD800 <= ord(c) <= 0xDFFF) for c in value))


@dataclass(frozen=True)
class Column:
    name: str
    type: str
    trim: bool = False
    casefold: bool = False
    nullable: bool = False
    null_values: tuple[str, ...] = ()

    def to_dict(self):
        return {"name": self.name, "type": self.type, "trim": self.trim,
                "casefold": self.casefold, "nullable": self.nullable,
                "null_values": list(self.null_values)}

    def convert(self, raw: str) -> str | None:
        if not isinstance(raw, str):
            raise RowbridgeError("Expected a string cell")
        if raw in self.null_values:
            if not self.nullable:
                raise RowbridgeError("Null is not allowed")
            return None
        value = raw.strip() if self.trim else raw
        if self.type == "string":
            return value.casefold() if self.casefold else value
        if self.type == "integer":
            if len(value) > 256 or not _INTEGER.fullmatch(value):
                raise RowbridgeError("Expected an integer (at most 256 characters)")
            return str(int(value))
        if self.type == "decimal":
            if len(value) > 256 or not _DECIMAL.fullmatch(value):
                raise RowbridgeError("Expected a finite decimal (at most 256 characters)")
            # Check the written exponent before Decimal construction; huge exponents
            # are not useful here, even if the coefficient is zero.
            exponent_text = re.split("[eE]", value)
            if len(exponent_text) == 2 and abs(int(exponent_text[1])) > 1000:
                raise RowbridgeError("Decimal exponent must be between -1000 and 1000")
            number = Decimal(value)
            if abs(number.as_tuple().exponent) > 1000:
                raise RowbridgeError("Decimal exponent must be between -1000 and 1000")
            if number.is_zero():
                return "0"
            # normalize() can round under the active Decimal context. Fixed-point
            # formatting and string trimming preserve every significant digit.
            result = format(number, "f")
            return result.rstrip("0").rstrip(".") if "." in result else result
        if self.type == "date":
            if not _DATE.fullmatch(value):
                raise RowbridgeError("Expected a date in YYYY-MM-DD format")
            try:
                date.fromisoformat(value)
            except ValueError as exc:
                raise RowbridgeError("Invalid calendar date") from exc
            return value
        raise RowbridgeError(f"Unsupported column type: {self.type}")


@dataclass(frozen=True)
class Schema:
    columns: tuple[Column, ...]
    keys: tuple[str, ...]

    def to_dict(self):
        return {"version": 1, "keys": list(self.keys),
                "columns": [column.to_dict() for column in self.columns]}

    @property
    def digest(self):
        return hashlib.sha256(_canonical_json(self.to_dict()).encode("ascii")).hexdigest()


def parse_schema(value: dict) -> Schema:
    if not isinstance(value, dict) or set(value) != {"version", "keys", "columns"}:
        raise RowbridgeError("Schema requires exactly version, keys, and columns")
    if type(value["version"]) is not int or value["version"] != 1:
        raise RowbridgeError("Only schema version 1 is supported")
    specs = value["columns"]
    if not isinstance(specs, list) or not 1 <= len(specs) <= 256:
        raise RowbridgeError("Schema needs between 1 and 256 columns")
    columns = []
    names = set()
    allowed = {"name", "type", "trim", "casefold", "nullable", "null_values"}
    for spec in specs:
        if (not isinstance(spec, dict) or not {"name", "type"} <= set(spec)
                or set(spec) - allowed):
            raise RowbridgeError("Each column needs name and type, with no unknown settings")
        name = spec["name"]
        if not _name(name) or name in names:
            raise RowbridgeError("Column names must be unique, nonempty text without control characters")
        if not isinstance(spec["type"], str) or spec["type"] not in _TYPES:
            raise RowbridgeError(f"Unsupported type for {name}")
        for setting in ("trim", "casefold", "nullable"):
            if setting in spec and type(spec[setting]) is not bool:
                raise RowbridgeError(f"{setting} must be a boolean for {name}")
        nulls = spec.get("null_values", [])
        if (not isinstance(nulls, list) or any(not isinstance(x, str) for x in nulls)
                or len(set(nulls)) != len(nulls)
                or any(any(0xD800 <= ord(c) <= 0xDFFF for c in x) for x in nulls)):
            raise RowbridgeError(f"null_values must be unique strings for {name}")
        if nulls and not spec.get("nullable", False):
            raise RowbridgeError(f"Null tokens require nullable=true for {name}")
        if spec.get("casefold", False) and spec["type"] != "string":
            raise RowbridgeError(f"casefold is only supported for string columns: {name}")
        names.add(name)
        columns.append(Column(name=name, type=spec["type"], trim=spec.get("trim", False),
                              casefold=spec.get("casefold", False),
                              nullable=spec.get("nullable", False), null_values=tuple(nulls)))
    keys = value["keys"]
    if (not isinstance(keys, list) or not keys or any(not isinstance(x, str) for x in keys)
            or len(set(keys)) != len(keys) or any(x not in names for x in keys)):
        raise RowbridgeError("keys must be a nonempty list of unique column names")
    if any(column.nullable for column in columns if column.name in keys):
        raise RowbridgeError("Key columns cannot be nullable")
    return Schema(tuple(columns), tuple(keys))


def load_schema(path) -> Schema:
    try:
        with Path(path).open("r", encoding="utf-8-sig") as stream:
            value = json.load(stream, object_pairs_hook=_object, parse_constant=_constant)
        return parse_schema(value)
    except RowbridgeError:
        raise
    except (OSError, UnicodeError, ValueError, RecursionError) as exc:
        raise RowbridgeError(f"Cannot read schema: {exc}") from exc
