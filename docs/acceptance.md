# Acceptance checks

The prototype checks typed CSV comparison. The later milestones add resumable imports, reviewed changes, and managed storage. Passing current tests doesn't establish those future guarantees.

## Prototype

Run from the repository root:

```sh
python -m unittest discover -s tests -v
python scripts/demo.py
python scripts/benchmark.py --records 10000 --seed 17 --json
```

The checks should establish these behaviors:

| Area | Required result |
| --- | --- |
| Schema | Reject unknown fields, duplicate JSON keys, invalid options, and missing or nullable key columns. Normalize omitted defaults consistently. |
| Conversion | Preserve string identifiers and distinguish blank from null. Compare exact decimals beyond 28 digits without rounding. Handle signed zero, ISO dates, and explicit text normalization. |
| CSV | Accept reordered headers and quoted multiline fields. Reject malformed encoding, headers, syntax, and oversized inputs. Report invalid record widths and conversion failures. |
| Provenance | Hash the bytes actually parsed and preserve original values, data record numbers, and physical line ranges. |
| Comparison | Match a separate small reference join for added, removed, changed, and unchanged keys. Report duplicate keys as ambiguous, including duplicates containing invalid records. |
| Incomplete results | Keep errors visible, count unkeyed records, and mark the entire report provisional. Never silently discard an invalid or duplicate record. |
| Determinism | Produce the same report for identical bytes, basenames, and schema. Reject datasets parsed under a different schema digest. |
| CLI | Return the documented exit codes, keep stdout valid JSON, preserve existing files, and escape source values in HTML. |

The clean inventory pair has one added key, one removed key, one changed key, and two unchanged keys. The review fixture exercises ambiguity and invalid records. The demo checks both paths using temporary files.

The benchmark generates a deterministic pair of fictional exports. It checks the exact expected key partitions and changed values independently of the comparison result. Generation happens before timing. Parsing and comparison are timed together; peak traced Python allocations and serialized report size are separate measurements. Traced allocations aren't total process memory.

## Future acceptance bar

These checks belong to the [planned work](roadmap.md):

- Small generated cases match an independent reference across schema migrations, joins, relationships, and reviewed decisions.
- Restarting an interrupted import yields the same records and differences as an uninterrupted run, without duplicate records or lost provenance.
- Duplicate identities and broken references block affected changes instead of selecting an arbitrary record.
- Every approval identifies the input versions and rules it reviewed. Changing a dependency invalidates affected approvals.
- Applying a plan checks the current managed dataset revision. A stale plan makes no changes.
- Failure during application leaves the old dataset or the complete new dataset. A supported rollback restores the prior revision and its relationships.
- An incremental run produces the same result as a fresh run over the same source set. Unchanged imports don't create duplicate changes.
- Saved inputs, rules, and decisions reproduce a prior result. The UI and CLI use the same validation and application code.
- The reference and interruption suites pass on Windows and Linux.

The future scale target is one million rows on each side while staying within 512 MiB of peak process memory. It hasn't been measured. It requires disk-backed processing, bounded result iteration, and a process memory measurement that includes more than Python allocations. Record row width, duplicate distribution, edit mix, hardware, Python version, runtime, and temporary disk use with that result. Set a runtime budget after measuring representative cases.

The current 64 MiB input limit and in-memory report are prototype constraints, not evidence that the scale target has been met.
