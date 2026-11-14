"""Verify exported evidence and independently recompute its counts, offline."""

import csv
import hashlib
import json
from pathlib import Path
import sys

import duckdb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from taxi_pipeline.download import read_json, sha256_file
from taxi_pipeline.transform import sql_text


def verify(root=ROOT):
    artifacts = root / "artifacts"
    manifest = read_json(artifacts / "file_manifest.json")["files"]
    actual_paths = {p.relative_to(artifacts).as_posix() for p in artifacts.rglob("*") if p.is_file() and p.name != "file_manifest.json"}
    if actual_paths != {r["path"] for r in manifest}:
        raise RuntimeError("Evidence file list differs from file_manifest.json")
    for record in manifest:
        path = (artifacts / record["path"]).resolve()
        if not path.is_relative_to(artifacts.resolve()):
            raise RuntimeError("Invalid path in artifact manifest")
        if path.stat().st_size != record["bytes"] or sha256_file(path) != record["sha256"]:
            raise RuntimeError(f"Evidence hash/size mismatch: {record['path']}")
    with (artifacts / "results/ranking.csv").open(encoding="utf-8", newline="") as source:
        ranking = {row["taxi_type"]: int(row["valid_count"]) for row in csv.DictReader(source)}
    with duckdb.connect() as con:
        path = artifacts / "curated/daily_zone_counts.parquet"
        con.execute(f"CREATE VIEW curated AS SELECT * FROM read_parquet({sql_text(path)})")
        observed = dict(con.execute("SELECT taxi_type, SUM(trip_count)::BIGINT FROM curated GROUP BY taxi_type").fetchall())
        # Zero-valid types are retained in ranking but have no curated groups.
        if {name: observed.get(name, 0) for name in ranking} != ranking:
            raise RuntimeError("Ranking differs from actual curated counts")
        duplicates = con.execute("SELECT COUNT(*) - COUNT(DISTINCT (pickup_date,taxi_type,pickup_location_id,source_file)) FROM curated").fetchone()[0]
        if duplicates:
            raise RuntimeError("Curated keys are not unique")
        per_file = dict(con.execute("SELECT source_file,SUM(trip_count)::BIGINT FROM curated GROUP BY source_file").fetchall())
        # Compute the same canonical CSV stream that the producing run hashed.
        import io
        expected_csv = con.execute("SELECT * FROM curated ORDER BY taxi_type,source_month,pickup_date,pickup_location_id NULLS LAST").fetchall()
        columns = [d[0] for d in con.description]
        buffer = io.StringIO(newline="")
        writer = csv.writer(buffer, lineterminator="\n")
        writer.writerow(columns)
        writer.writerows(expected_csv)
        canonical_hash = hashlib.sha256(buffer.getvalue().encode("utf-8")).hexdigest()
    audits = read_json(artifacts / "quality/file_audit.json")
    for audit in audits:
        if per_file.get(audit["source_file"], 0) != audit["valid_count"]:
            raise RuntimeError(f"Curated source count differs from audit: {audit['source_file']}")
    quality = read_json(artifacts / "quality/quality.json")
    if quality["status"] != "PASS" or not all(c["passed"] for c in quality["checks"]):
        raise RuntimeError("Snapshot is not a quality-gated success")
    if sum(ranking.values()) != quality["valid_count"]:
        raise RuntimeError("Quality totals differ from curated counts")
    repeat = read_json(artifacts / "reproducibility.json")
    first = read_json(artifacts / "runs" / repeat["first_run"] / "run.json")
    second = read_json(artifacts / "runs" / repeat["unchanged_rerun"] / "run.json")
    if not (first["status"] == second["status"] == "SUCCESS"
            and first["curated_content_sha256"] == second["curated_content_sha256"]
            and first["valid_count"] == second["valid_count"]
            and second["actions"].get("reused") == second["input_files"]):
        raise RuntimeError("Run evidence does not demonstrate an unchanged rerun")
    if sha256_file(artifacts / "curated/daily_zone_counts.parquet") != second["curated_sha256"]:
        raise RuntimeError("Snapshot Parquet differs from successful run")
    if canonical_hash != second["curated_content_sha256"]:
        raise RuntimeError("Curated content differs from canonical content hash")
    print(f"PASS: {len(manifest)} artifact hashes; {len(audits)} source audits; {sum(ranking.values()):,} valid trip records; unchanged rerun verified")


if __name__ == "__main__":
    try:
        verify()
    except Exception as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1)
