# Data and license

The example CSV files describe fictional inventory parts and locations. The benchmark generates synthetic records and deterministic changes. They contain no customer records, employee details, credentials, accounts, or live production data.

The prototype reads local files and writes comparison reports. It makes no network requests and needs no external service. Reports include original field values, so they contain the data supplied in the input files. Source metadata uses basenames rather than absolute paths.

Keep development fixtures and benchmarks synthetic. Future relationship and review examples should continue using fictional parts, warehouses, and stock records.

The repository is licensed under the [MIT license](../LICENSE), including its code, documentation, and example data. It has no third-party runtime dependencies. The documentation links to Python and SQLite documentation as technical references; those sources aren't copied into the repository.
