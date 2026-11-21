"""Read, validate, and compare CSV files without modifying the inputs."""

import argparse
import json
import os
from pathlib import Path
import sys

from .ingest import load_dataset
from .reconcile import reconcile
from .reporting import render_report
from .schema import RowbridgeError, load_schema


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rowbridge", description="Compare CSV records using explicit types and keys.")
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate", help="check a CSV file against an explicit schema")
    validate.add_argument("csv", type=Path)
    validate.add_argument("--schema", required=True, type=Path)
    validate.add_argument("--output", type=Path, help="write JSON to a new file instead of stdout")
    compare = commands.add_parser("compare", help="compare two CSV files and retain unresolved records")
    compare.add_argument("left", type=Path)
    compare.add_argument("right", type=Path)
    compare.add_argument("--schema", required=True, type=Path)
    compare.add_argument("--output", type=Path, help="write JSON to a new file instead of stdout")
    compare.add_argument("--html", type=Path, help="write a standalone report to a new file")
    return parser


def _json_text(value: object) -> str:
    return json.dumps(value, ensure_ascii=True, indent=2, allow_nan=False) + "\n"


def _normalized(path: Path) -> str:
    try:
        return os.path.normcase(str(path.resolve()))
    except (RuntimeError, OSError) as error:
        raise RowbridgeError(f"Cannot resolve output or source path: {path}: {error}") from error


def _write_outputs(outputs: list[tuple[Path, str]], inputs: list[Path]) -> None:
    paths = [_normalized(path) for path, _ in outputs]
    if len(paths) != len(set(paths)):
        raise RowbridgeError("JSON and HTML outputs must use different paths.")
    input_paths = {_normalized(path) for path in inputs}
    if any(path in input_paths for path in paths):
        raise RowbridgeError("An output cannot replace a source CSV or schema.")
    for path, _ in outputs:
        if path.exists() or path.is_symlink():
            raise RowbridgeError(f"Output already exists: {path}")
        if not path.parent.is_dir():
            raise RowbridgeError(f"Output directory does not exist: {path.parent}")
    created = []
    try:
        for path, content in outputs:
            with path.open("x", encoding="utf-8", newline="\n") as stream:
                info = os.fstat(stream.fileno())
                created.append((path, info.st_dev, info.st_ino))
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
    except BaseException:
        # Ordinary failures remove only files created by this command.
        for path, device, inode in reversed(created):
            try:
                info = path.lstat()
                if (info.st_dev, info.st_ino) == (device, inode):
                    path.unlink()
            except OSError:
                pass
        raise


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        schema = load_schema(args.schema)
        outputs = []
        if args.command == "validate":
            result = load_dataset(args.csv, schema).to_dict()
            complete = not result["issues"]
            inputs = [args.csv, args.schema]
        else:
            result = reconcile(args.left, args.right, schema)
            complete = result["complete"]
            inputs = [args.left, args.right, args.schema]
            if args.html:
                outputs.append((args.html, render_report(result)))
        if args.output:
            outputs.insert(0, (args.output, _json_text(result)))
        _write_outputs(outputs, inputs)
        if not args.output:
            sys.stdout.write(_json_text(result))
        return 0 if complete else 1
    except (RowbridgeError, OSError) as error:
        print(f"rowbridge: {error}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("rowbridge: interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
