# Architecture

The prototype has three stages: load an explicit schema, parse each CSV with provenance, then compare groups of records by their converted keys. Reporting uses the result without changing the source files.

## Schema and conversion

`schema.py` validates version 1 schemas. A schema contains `version`, `keys`, and `columns`. Unknown fields and duplicate JSON keys are errors. Columns have a name and a type, with optional `trim`, `casefold`, `nullable`, and `null_values` settings. Boolean options default to false and null tokens default to an empty list.

There must be 1 to 256 columns. Names are unique, nonempty, at most 128 characters, and contain no control characters or unpaired Unicode surrogates. Keys name one or more distinct, nonnullable columns. Column order and key order are meaningful.

| Type | Comparison representation |
| --- | --- |
| `string` | Original text, unless trimming or case folding is explicitly enabled |
| `integer` | Canonical integer text, so `+0017` and `17` compare equally |
| `decimal` | Exact fixed-point text without trailing fractional zeros; all signed zeros become `0` |
| `date` | A valid calendar date written exactly as `YYYY-MM-DD` |

Converted nonnull values are strings in the report, including numbers. Null values use JSON `null`. Raw field values are retained separately.

Null tokens match the original field exactly, before trimming or case folding. For example, a declared `NULL` token won't match ` NULL `. Null tokens require `nullable: true`. Empty text is only null if an empty null token is explicitly declared. A key cannot be null or normalize to empty text.

Case folding is allowed only for strings. Integer syntax accepts ASCII digits with an optional sign. Decimal syntax accepts plain or scientific ASCII numbers and rejects nonfinite values. Numeric input is limited to 256 characters. Both a written decimal exponent and the exponent after accounting for fractional digits are limited to an absolute value of 1000. Decimal conversion preserves digits without depending on the arithmetic context's precision.

Python's [decimal documentation](https://docs.python.org/3/library/decimal.html) explains exact construction from strings and the separate role of arithmetic precision. Rowbridge uses an explicit canonical representation so textual scale differences don't become numeric changes.

The schema digest hashes its normalized representation, including defaults. Object keys are serialized in a fixed order with ASCII escapes. Changing a column rule, column order, or key order changes that identity.

## Input and provenance

`ingest.py` reads each CSV into one bytes buffer, limited to 64 MiB. It hashes and parses those same bytes. This binds the report to the bytes read; it doesn't provide a filesystem snapshot if another program is writing the source concurrently.

The parser accepts UTF-8 with an optional byte order mark, comma separators, and standard double quotes. It uses strict CSV parsing with newline handling preserved. Python's [CSV documentation](https://docs.python.org/3/library/csv.html) covers `newline=''`, quoted fields, and the parser's field size limit. Rowbridge retains that field size limit rather than accepting arbitrarily large fields.

The header must match the schema's column names exactly, without duplicates. Column order may differ. An empty file is an error; a header-only file is valid.

Each data record keeps:

- Its one-based record number and physical start and end lines. A quoted multiline field belongs to one record.
- Original fields in `cells`, a column-name map in `raw` when the width is valid, and successfully converted values in `values`.
- Its converted composite `key`, when available.
- Column errors, including a record-level error for the wrong number of fields.

A bad non-key value can leave a usable key. A bad key leaves the record unkeyed. Records with the wrong width retain their `cells` but have no column-name map. Blank physical records are invalid records, not silently skipped rows.

Encoding, header, CSV syntax, and size failures stop the import. Record conversion errors remain in the dataset and report. Source metadata contains the basename, byte count, and SHA-256 hash. It contains no absolute path or timestamp.

## Comparison

`reconcile.py` requires both datasets to have the supplied schema's digest. It groups records by their converted key and considers the union of keys from both sources. Entries are ordered lexicographically by the tuple of key strings, not numerically.

Status is chosen in this order:

1. `ambiguous` if either side has more than one record for the key, even when those records are identical or invalid.
2. `invalid` if a remaining record has conversion errors.
3. `added` or `removed` if the key exists on only one side.
4. `changed` or `unchanged` after comparing converted values.

Every entry has a `changes` list, but only changed entries have a nonempty one. Changes follow schema column order and contain the column and its before and after values. Every entry includes its available source records, including unchanged entries.

The six status counters count key groups. `unkeyed_left` and `unkeyed_right` count records that couldn't produce a key. Full unkeyed records remain in each side's `unkeyed` list, outside the keyed entries, with their errors also included in the input issues.

`complete` is false when either input has issues or any key is ambiguous. Every entry in that report is provisional: an unkeyed record could correspond to an apparent addition or removal. A complete report means comparison finished under the declared rules, not that either source is authoritative.

Reports are deterministic for the same input bytes, basenames, and schema. Changing a basename changes source metadata even if its bytes stay the same.

## CLI and outputs

`validate` emits the parsed dataset and its conversion issues; it doesn't flag duplicate keys. `compare` checks key ambiguity, emits the comparison, and can also write a static HTML view. HTML escapes source content and uses no remote assets. It has no interactive editor.

Output paths are checked before writing and opened exclusively. Existing files aren't overwritten, and missing parent directories aren't created. A JSON report and an HTML report aren't one atomic operation; interrupted writes can leave incomplete output files.

## Planned storage boundary

The [roadmap](roadmap.md) replaces whole-file processing with disk-backed imports, indexed joins, and durable checkpoints. Review decisions will identify the exact inputs, schema, and result they approve. Changed dependencies must invalidate decisions before anything is applied.

Approved changes will target a managed SQLite dataset. Atomic application and rollback belong inside that database, with recorded dataset revisions and explicit stale-input checks. Exporting several ordinary CSV files won't carry the same transaction guarantee.

SQLite's [atomic commit documentation](https://www.sqlite.org/atomiccommit.html) describes transaction behavior and its filesystem assumptions. It is background for the planned storage work, not evidence that the current prototype implements transactions or crash recovery.
