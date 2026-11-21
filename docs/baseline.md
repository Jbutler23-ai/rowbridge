# Prototype baseline

These are observations from one local run, not performance limits or guarantees.

Environment: Windows 11 (10.0.26200), Python 3.12.14. Linux validation is still planned. The supported source syntax is Python 3.11 or later; this run doesn't establish results for every supported interpreter.

`python -m unittest discover -s tests -v` passed all 57 tests without skips. The suite includes 12 seeded comparisons against an independent small reference join, exact decimal cases, duplicate and invalid records, record conservation, input errors, and CLI output protection.

## Example checks

`python scripts/demo.py` passed both fixture comparisons. The clean pair produced one added, one removed, one changed, and two unchanged keys. The review pair produced one added, one removed, two unchanged, one ambiguous, and one invalid key, plus one unkeyed record. It correctly returned an incomplete comparison. JSON and HTML output checks passed.

## Synthetic benchmark

```sh
python scripts/benchmark.py --records 10000 --seed 17 --json
```

The `rowbridge-corpus-v1` generator wrote 10,000 records on each side. The source files were 330,026 and 328,941 bytes. The second export reorders records and changes numeric and text formatting, as well as making deliberate content edits.

The result matched the expected key sets exactly: 1,000 added, 1,000 removed, 2,000 changed, and 7,000 unchanged. Changed field values also matched the generator's expected values. There were no invalid or ambiguous keys in this corpus; those cases are covered by the review fixture and tests.

| Measurement | Observed value |
| --- | ---: |
| Parse and compare | 1.022012 seconds |
| Peak traced Python allocations | 80,054,354 bytes |
| Compact JSON serialization | 0.062876 seconds |
| Compact JSON report | 7,289,740 bytes |

Parsing and comparison were timed with `tracemalloc` enabled. The traced peak excludes corpus generation, reference checks, and JSON serialization. It is not total process memory. Serialization was timed separately, without tracing. The CLI's indented JSON and HTML can be larger than this compact JSON output.

Full records, provenance, and unchanged entries account for much of the report size. The prototype holds both inputs and results in memory, so file size alone is a poor estimate of memory use.

## Remaining scale work

The target is one million rows per side within 512 MiB of peak process memory. It hasn't been measured and will require disk-backed imports, joins, and streamed results. Future measurements must include row width, key skew, edit rates, runtime, temporary disk use, and process memory. A runtime budget will follow those measurements.
