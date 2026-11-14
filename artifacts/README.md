# Executed pipeline evidence

These are actual full-data outputs exported from the two SUCCESS runs named in `reproducibility.json`. Raw inputs are deliberately excluded; exact URLs, hashes and retrieval metadata are in `provenance/manifest.json`.

- `curated/`: complete compressed daily pickup-zone fact table and a 200-row CSV example (up to 50 rows per type).
- `quality/`: actual quality gates and all 24 source-file audits.
- `results/`: analysis, ranking, monthly/borough totals and chart generated from curated data.
- `runs/`: full-run and unchanged-rerun status plus chronological event logs; timestamps are UTC.
- `provenance/`: downloaded-source manifest, effective configuration and original notebook hash.
- `file_manifest.json`: SHA-256 and bytes for every exported evidence file except this manifest itself.

The local working paths (`reports/runs/...`, `data/curated/...`) are represented by these exported directories. `python scripts/verify_artifacts.py` verifies the committed snapshot without downloading raw data.
