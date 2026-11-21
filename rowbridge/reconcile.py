"""Group canonical keys without guessing how duplicate records should match."""

from collections import defaultdict

from .ingest import Dataset, load_dataset
from .schema import RowbridgeError, Schema


def _groups(dataset):
    groups = defaultdict(list)
    for row in dataset.rows:
        if row["key"] is not None:
            groups[tuple(row["key"])].append(row)
    return groups


def _side(dataset):
    return {"source": dataset.source, **dataset.summary, "issues": list(dataset.issues),
            "unkeyed": [row for row in dataset.rows if row["key"] is None]}


def compare_datasets(left: Dataset, right: Dataset, schema: Schema) -> dict:
    if left.schema_sha256 != schema.digest or right.schema_sha256 != schema.digest:
        raise RowbridgeError("Datasets must use the same schema as the comparison")
    left_groups, right_groups = _groups(left), _groups(right)
    summary = {status: 0 for status in ("added", "removed", "changed", "unchanged", "ambiguous", "invalid")}
    summary["unkeyed_left"] = sum(row["key"] is None for row in left.rows)
    summary["unkeyed_right"] = sum(row["key"] is None for row in right.rows)
    entries = []
    for key in sorted(left_groups.keys() | right_groups.keys()):
        before, after = left_groups.get(key, []), right_groups.get(key, [])
        changes = []
        if len(before) > 1 or len(after) > 1:
            status = "ambiguous"
        elif any(row["errors"] for row in before + after):
            status = "invalid"
        elif not before:
            status = "added"
        elif not after:
            status = "removed"
        else:
            for column in schema.columns:
                old = before[0]["values"][column.name]
                new = after[0]["values"][column.name]
                if old != new:
                    changes.append({"column": column.name, "before": old, "after": new})
            status = "changed" if changes else "unchanged"
        summary[status] += 1
        entries.append({"key": list(key), "status": status, "left": before,
                        "right": after, "changes": changes})
    return {"version": 1, "schema": schema.to_dict(), "schema_sha256": schema.digest,
            "left": _side(left), "right": _side(right),
            "complete": not (left.issues or right.issues or summary["ambiguous"]),
            "summary": summary, "entries": entries}


def reconcile(left_path, right_path, schema: Schema) -> dict:
    return compare_datasets(load_dataset(left_path, schema), load_dataset(right_path, schema), schema)
