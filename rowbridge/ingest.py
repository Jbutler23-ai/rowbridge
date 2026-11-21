"""Parse CSV bytes once and preserve the location of every data record."""

import csv
from dataclasses import dataclass
import hashlib
import io
from pathlib import Path

from .schema import RowbridgeError, Schema

MAX_FILE_BYTES = 64 * 1024 * 1024


@dataclass(frozen=True)
class Dataset:
    source: dict
    schema_sha256: str
    rows: tuple[dict, ...]
    issues: tuple[dict, ...]

    @property
    def summary(self):
        invalid = sum(bool(row["errors"]) for row in self.rows)
        return {"records": len(self.rows), "valid_records": len(self.rows) - invalid,
                "invalid_records": invalid}

    def to_dict(self):
        return {"source": self.source, "schema_sha256": self.schema_sha256,
                "rows": list(self.rows), "issues": list(self.issues), "summary": self.summary}


def load_dataset(path, schema: Schema) -> Dataset:
    path = Path(path)
    try:
        with path.open("rb") as stream:
            data = stream.read(MAX_FILE_BYTES + 1)
    except OSError as exc:
        raise RowbridgeError(f"Cannot read CSV: {exc}") from exc
    if len(data) > MAX_FILE_BYTES:
        raise RowbridgeError("CSV exceeds the prototype's 64 MiB file limit")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeError as exc:
        raise RowbridgeError("CSV must be valid UTF-8") from exc
    source = {"name": path.name, "sha256": hashlib.sha256(data).hexdigest(),
              "size_bytes": len(data)}
    reader = csv.reader(io.StringIO(text, newline=""), strict=True)
    try:
        header = next(reader, None)
        if header is None:
            raise RowbridgeError("CSV has no header")
        names = [column.name for column in schema.columns]
        if len(header) != len(set(header)):
            raise RowbridgeError("CSV contains duplicate header names")
        if set(header) != set(names):
            raise RowbridgeError("CSV header must contain exactly the schema's column names")
        rows = []
        issues = []
        previous_line = reader.line_num
        for record, cells in enumerate(reader, 1):
            row = {"record": record, "line_start": previous_line + 1,
                   "line_end": reader.line_num, "cells": cells, "raw": {}, "values": {},
                   "key": None, "errors": []}
            previous_line = reader.line_num
            if len(cells) != len(header):
                row["errors"].append({"column": None,
                                      "message": f"Expected {len(header)} cells, got {len(cells)}"})
            else:
                row["raw"] = dict(zip(header, cells))
                for column in schema.columns:
                    try:
                        value = column.convert(row["raw"][column.name])
                        if column.name in schema.keys and value == "":
                            raise RowbridgeError("Key value cannot be empty")
                        row["values"][column.name] = value
                    except RowbridgeError as exc:
                        row["errors"].append({"column": column.name, "message": str(exc)})
                if all(name in row["values"] for name in schema.keys):
                    row["key"] = [row["values"][name] for name in schema.keys]
            for error in row["errors"]:
                issues.append({"record": record, "line_start": row["line_start"],
                               "line_end": row["line_end"], **error})
            rows.append(row)
    except csv.Error as exc:
        raise RowbridgeError(f"CSV parsing failed near physical line {reader.line_num}: {exc}") from exc
    return Dataset(source, schema.digest, tuple(rows), tuple(issues))
