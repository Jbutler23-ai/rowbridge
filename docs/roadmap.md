# Roadmap

The current version validates and compares two CSV files in memory. The work below turns that comparison into a repeatable review and update workflow for a managed dataset. These nine sessions describe remaining work, not completed features.

## 1. Versioned schemas and source mappings

Add source-specific column mappings and explicit migrations between schema versions. Keep the original field values and the conversion path for each record. A change to key normalization must expose collisions rather than merge records silently.

Check: reference cases cover renamed columns, added required fields, type changes, and key collisions. Replaying a saved migration gives the same result; unsupported changes fail before data is applied.

## 2. Disk-backed import and resumable joins

Store imported records and key indexes in SQLite. Read, compare, and emit results in bounded batches. Checkpoints must identify the source bytes and schema so a changed file can't resume an old import accidentally.

Check: interrupt imports at each checkpoint boundary and resume them. Their record counts, provenance, and differences must match a fresh run exactly, including quoted multiline records and duplicates across batch boundaries.

## 3. Relationships across files

Declare references between datasets, such as a stock record's part and warehouse. Distinguish missing targets from duplicate target keys. Define the order in which related inserts and removals can be accepted.

Check: fixtures cover missing parents, ambiguous parents, composite references, and a parent removed while children remain. No accepted change can leave a declared relationship unresolved.

## 4. Review decisions and stale approvals

Record acceptance, rejection, and manual resolutions against exact input, schema, and comparison versions. Preserve unresolved conflicts. When an input or rule changes, explain which decisions are stale and why.

Check: edits to an approved record or its referenced parent invalidate the affected approval. Unrelated changes preserve decisions only when their dependencies are unchanged. A duplicate group can't be resolved by choosing its first row implicitly.

## 5. Transactional application and rollback

Apply approved changes to a managed SQLite dataset. Check its expected revision and all constraints inside the transaction. Record enough history for a supported rollback; source CSV files remain inputs.

Check: stale plans make no changes. Inject failures before, during, and after application. Reopening the database yields either the old revision or the complete new revision. Rolling back a supported revision restores its records and relationships. Multiple exported CSV files carry no atomicity promise.

## 6. Incremental imports across a source set

Track files as a versioned source set. Reuse unchanged imports and recompute affected comparisons and relationships after additions, removals, or replacements. Coordinate this with checkpoint recovery and stale decision handling.

Check: incremental and clean runs agree on the same final sources. Reimporting unchanged files creates no duplicate records or changes. Removing a source exposes affected references and approvals.

## 7. Offline review interface

Build a local review interface with bundled HTML, CSS, and JavaScript and a Python service on localhost. Show differences, source records, relationship errors, and the effect of a proposed resolution. Use the same engine as the CLI.

Check: review, save, reopen, and apply a synthetic case without internet access. UI and CLI results agree. Stale data is rejected even when an old review screen is still open, and source text is displayed as text.

## 8. Reproducible history and explanations

Save run manifests linking input versions, schema migrations, decisions, and managed dataset revisions. Explain why a value or classification changed between runs. Define what must be retained to replay a result and report missing inputs explicitly.

Check: replay a saved run and compare its canonical result to the original. Trace an applied value back to its source and decision. A changed rule or missing artifact produces a concrete explanation rather than a guessed result.

## 9. Reference, interruption, and performance suite

Expand the independent reference suite with generated schemas, composite keys, duplicate groups, relationship graphs, and decision histories. Run interruption checks and the same correctness suite on Windows and Linux.

The unmeasured scale target is one million rows per side within 512 MiB of peak process memory. Benchmark narrow and wide rows, skewed keys, and different edit rates. Report runtime and temporary disk use as well as memory, and set the runtime budget from measured results. The current `tracemalloc` benchmark doesn't establish this process memory target.

Check: large runs match known key partitions and sampled full reference cases; no rows disappear at batch boundaries. A performance result only passes if its correctness checks pass too.

## Scope

Rowbridge stays focused on local structured data. The plan doesn't include cloud connectors, production accounts, fuzzy identity matching, automatic type guessing, encryption, or a general database administration tool. Examples and benchmarks use fictional inventory data.
