# Rowbridge

Rowbridge compares CSV exports using an explicit schema. It shows which records were added, removed, or changed, and keeps duplicate keys and invalid values visible for review.

The current prototype reads two files into memory and produces JSON and an optional static HTML report. It doesn't change either source file. The longer-term goal is to review and apply approved changes to a managed dataset, with resumable imports, relationship checks, and reproducible decisions. Those features are [planned](docs/roadmap.md).

## Run it

Python 3.11 or later is required. There are no third-party runtime dependencies and no installation step. Run these commands from the repository directory:

```sh
python -m rowbridge validate examples/inventory-before.csv --schema examples/inventory-schema.json
python -m rowbridge compare examples/inventory-before.csv examples/inventory-after.csv --schema examples/inventory-schema.json --output report.json --html report.html
```

Open `report.html` in a browser. It contains its own styles and needs no server or internet connection. Output paths must be new, and their parent directories must already exist. Omit `--output` to write JSON to standard output.

The review example contains duplicate keys and invalid values:

```sh
python -m rowbridge compare examples/inventory-before.csv examples/inventory-review.csv --schema examples/inventory-schema.json
```

This command still produces a report but exits with code `1`. All entries in an incomplete report are provisional, including apparent additions and removals.

`validate` checks the schema and record conversions. Duplicate keys are flagged by `compare`, not by `validate`.

| Exit code | Meaning |
| --- | --- |
| `0` | Validation or comparison completed without issues |
| `1` | The report contains invalid records or ambiguous keys |
| `2` | A fatal input, output, or argument error prevented completion |
| `130` | The command was interrupted |

## What it compares

A JSON schema declares the columns, types, and key columns. Keys can contain several columns, such as a part number and a warehouse. CSV columns may appear in a different order, but the header must contain exactly the declared names.

- Supported types are strings, integers, exact decimals, and ISO dates.
- Trimming, case folding, and null tokens must be declared. Empty text and null are different values.
- A string identifier such as `0017` keeps its leading zeros. A declared integer compares by its numeric value.
- Duplicate keys are ambiguous even if the records look identical. Rowbridge never picks one automatically.
- Reports retain original field values, converted values, data record numbers, physical line ranges, and input hashes.

See [the architecture](docs/architecture.md) for the conversion rules and report format.

## Current limits

Each CSV is limited to 64 MiB. Both parsed datasets and the comparison report stay in memory, so memory use can be much larger than the input files. The standard CSV parser's field size limit also applies.

Inputs must be UTF-8 CSV with comma separators and standard double quotes. A UTF-8 byte order mark is accepted. There is no automatic dialect detection, column mapping, or type inference.

The prototype has no database, resumable import, conflict editor, relationship checks, or apply command. JSON and HTML outputs aren't committed as a single transaction. A report identifies differences under the supplied rules; it doesn't establish which source is correct.

## Checks

```sh
python -m unittest discover -s tests -v
python scripts/demo.py
python scripts/benchmark.py --records 10000 --seed 17 --json
```

The demo uses temporary files. The benchmark generates fictional inventory exports, checks the expected differences, and measures parsing and comparison. Its memory measurement covers traced Python allocations, not total process memory. The future target of one million rows per side within 512 MiB of process memory hasn't been measured.

## Project notes

- [Architecture and data rules](docs/architecture.md)
- [Acceptance checks](docs/acceptance.md)
- [Measured prototype baseline](docs/baseline.md)
- [Nine-session roadmap](docs/roadmap.md)
- [Data and license](docs/data-and-license.md)

The examples and benchmarks use made-up inventory parts. The project runs offline and requires no external accounts, GPU, Docker, or platform-specific software.

Licensed under the [MIT license](LICENSE).
