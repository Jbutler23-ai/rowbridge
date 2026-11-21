import csv
import io


def schema_data():
    return {
        "version": 1,
        "keys": ["part", "site"],
        "columns": [
            {"name": "part", "type": "string"},
            {"name": "site", "type": "string", "trim": True, "casefold": True},
            {"name": "quantity", "type": "integer"},
            {"name": "unit_price", "type": "decimal"},
            {"name": "checked", "type": "date", "nullable": True, "null_values": ["NULL"]},
            {"name": "note", "type": "string", "nullable": True, "null_values": ["NULL"]},
        ],
    }


def record(part="P001", site="North", quantity="12", unit_price="1.50", checked="2024-02-29", note=""):
    return {"part": part, "site": site, "quantity": quantity, "unit_price": unit_price,
            "checked": checked, "note": note}


def csv_bytes(records, *, columns=None):
    columns = columns or [column["name"] for column in schema_data()["columns"]]
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    writer.writerows(records)
    return stream.getvalue().encode("utf-8")
