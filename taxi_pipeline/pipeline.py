"""Orchestrate download -> audit -> curate -> quality -> analysis -> publish."""

from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import time
from uuid import uuid4

import duckdb
import matplotlib
import requests

from . import RULES_VERSION
from .config import Config
from .download import Downloader, sha256_file, utc_now, write_json
from .report import generate_report, write_csv
from .transform import QualityError, build_curated, load_zones, sql_text, transform_file


def source_fingerprint():
    package = Path(__file__).parent
    files = [package.parent / "run_pipeline.py", *sorted(package.glob("*.py"))]
    return {p.name: sha256_file(p) for p in files}


def run_pipeline(config: Config, *, offline=False, refresh=False, rebuild=False):
    config.validate()
    if offline and refresh:
        raise ValueError("--offline and --refresh cannot be used together")
    config.data_dir.mkdir(parents=True, exist_ok=True)
    lock_path = config.data_dir / ".pipeline.lock"
    try:
        lock_fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise RuntimeError("Another run owns data/.pipeline.lock. If a process crashed, verify it stopped before removing the lock.") from None
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
    os.write(lock_fd, json.dumps({"pid": os.getpid(), "run_id": run_id}).encode())
    os.close(lock_fd)
    run_dir = config.reports_dir / "runs" / run_id
    curated_dir = config.data_dir / "curated" / run_id
    con = None
    downloader = None
    started = time.monotonic()
    metadata = {"run_id": run_id, "status": "RUNNING", "started_at_utc": utc_now(),
                "rules_version": RULES_VERSION, "effective_config": config.settings,
                "options": {"offline": offline, "refresh": refresh, "rebuild": rebuild},
                "source_code_sha256": source_fingerprint(),
                "versions": {"python": platform.python_version(), "duckdb": duckdb.__version__,
                             "requests": requests.__version__, "matplotlib": matplotlib.__version__}}
    manifests, audits, partitions, actions = [], [], [], Counter()

    def event(stage, message, **details):
        record = {"at_utc": utc_now(), "stage": stage, "message": message, **details}
        with (run_dir / "events.jsonl").open("a", encoding="utf-8") as log:
            log.write(json.dumps(record, ensure_ascii=False) + "\n")
        print(f"[{stage}] {message}", flush=True)

    try:
        run_dir.mkdir(parents=True, exist_ok=False)
        curated_dir.mkdir(parents=True, exist_ok=False)
        write_json(run_dir / "run.json", metadata)
        event("START", f"Run {run_id}: {config.settings['start_month']} to {config.settings['end_month']}")
        con = duckdb.connect()
        con.execute(f"SET threads = {config.settings['threads']}")
        con.execute(f"SET memory_limit = {sql_text(config.settings['memory_limit'])}")
        temp = config.data_dir / "cache" / "duckdb_temp"
        temp.mkdir(parents=True, exist_ok=True)
        con.execute(f"SET temp_directory = {sql_text(temp)}")
        downloader = Downloader(config.settings["download_attempts"], offline, refresh)
        lookup_path = config.data_dir / "raw" / "taxi_zone_lookup.csv"
        lookup_info = downloader.fetch(config.settings["zone_lookup_url"], lookup_path)
        manifests.append({"dataset": "taxi_zone_lookup", "source_file": lookup_path.name, **lookup_info})
        write_json(run_dir / "manifest.json", manifests)
        lookup_quality = load_zones(con, lookup_path)
        event("LOOKUP", f"Validated {lookup_quality['rows']} unique taxi zones", download_action=lookup_info["download_action"])

        manifest = config.manifest()
        for number, item in enumerate(manifest, 1):
            event("INPUT", f"[{number}/{len(manifest)}] {item['source_file']}")
            path = config.data_dir / "raw" / item["source_file"]
            info = downloader.fetch(item["url"], path)
            manifests.append({"dataset": "trip_records", **{k: item[k] for k in ("taxi_type", "source_month", "source_file")}, **info})
            write_json(run_dir / "manifest.json", manifests)
            partition, audit, action = transform_file(con, path, item, config, info["sha256"], rebuild)
            actions[action] += 1
            actions[info["download_action"]] += 1
            partitions.append(partition)
            audits.append(audit)
            write_json(run_dir / "file_audit.json", audits)
            event("TRANSFORM", f"{action}: {audit['raw_count']:,} raw -> {audit['valid_count']:,} valid", source_file=item["source_file"], download_action=info["download_action"])

        curated = curated_dir / "daily_zone_counts.parquet"
        curated_quality = build_curated(con, partitions, curated)
        total_raw = sum(a["raw_count"] for a in audits)
        total_valid = sum(a["valid_count"] for a in audits)
        total_invalid = sum(a["invalid_count"] for a in audits)
        keys = [(a["taxi_type"], a["source_month"]) for a in audits]
        min_date, max_date = con.execute("SELECT MIN(pickup_date), MAX(pickup_date) FROM curated").fetchone()
        checks = [
            {"check": "complete_unique_input_coverage", "passed": len(audits) == len(manifest) == len(set(keys)), "expected_files": len(manifest), "observed_files": len(audits)},
            {"check": "required_schemas_and_nonempty_inputs", "passed": all(a["schema_ok"] and a["raw_count"] > 0 for a in audits)},
            {"check": "per_file_rejection_accounting", "passed": all(a["reconciled"] for a in audits)},
            {"check": "raw_equals_valid_plus_rejected", "passed": total_raw == total_valid + total_invalid},
            {"check": "positive_valid_total", "passed": total_valid > 0},
            {"check": "curated_equals_valid_total", "passed": curated_quality["trip_count"] == total_valid},
            {"check": "zone_join_preserves_trip_count", "passed": curated_quality["join_count_preserved"]},
            {"check": "unique_curated_keys", "passed": curated_quality["duplicate_keys"] == 0},
            {"check": "positive_curated_group_counts", "passed": curated_quality["nonpositive_groups"] == 0},
            {"check": "curated_dates_within_requested_period", "passed": min_date is not None and str(min_date) >= config.start and str(max_date) < config.stop},
        ]
        quality = {"status": "PASS" if all(c["passed"] for c in checks) else "FAIL", "checks": checks,
                   "raw_count": total_raw, "valid_count": total_valid, "invalid_count": total_invalid,
                   "lookup": lookup_quality, **curated_quality,
                   "diagnostics": {"source_month_mismatch": sum(a["source_month_mismatch"] for a in audits),
                                   "duplicate_candidates_in_first_10000_rows_per_file": sum(a["duplicate_candidates"] for a in audits),
                                   "diagnostics_do_not_reject_records": True}}
        write_json(run_dir / "quality.json", quality)
        write_csv(run_dir / "file_audit.csv", audits)
        if quality["status"] != "PASS":
            raise QualityError("One or more required quality gates failed; see quality.json")
        event("QUALITY", f"PASS: {len(checks)} gates; {total_valid:,} valid records; {total_invalid:,} rejected")
        answer, ranking = generate_report(con, audits, config, run_dir, curated)
        if sum(r["valid_count"] for r in ranking) != total_valid:
            raise QualityError("Ranking counts do not match audited valid count")
        canonical = hashlib.sha256()
        # Stream a deterministically sorted CSV for a representation-independent content hash.
        csv_path = curated_dir / "daily_zone_counts.csv"
        con.execute(f"COPY (SELECT * FROM curated ORDER BY taxi_type,source_month,pickup_date,pickup_location_id NULLS LAST) TO {sql_text(csv_path)} (FORMAT CSV, HEADER true)")
        with csv_path.open("rb") as data:
            for block in iter(lambda: data.read(8 * 1024 * 1024), b""):
                canonical.update(block)
        # Full CSV remains local; the compressed Parquet and 200-row CSV sample are the deliverables.
        csv_path.unlink()
        metadata.update({"status": "SUCCESS", "finished_at_utc": utc_now(),
                         "elapsed_seconds": round(time.monotonic() - started, 3),
                         "input_files": len(audits), "actions": dict(actions),
                         "raw_count": total_raw, "valid_count": total_valid, "invalid_count": total_invalid,
                         "curated_rows": curated_quality["curated_rows"],
                         "curated_sha256": sha256_file(curated),
                         "curated_content_sha256": canonical.hexdigest(), "answer": answer})
        event("SUCCESS", f"Winner(s): {', '.join(answer['winners'])}; curated rows: {curated_quality['curated_rows']:,}")
        write_json(run_dir / "run.json", metadata)
        # Only one small atomic pointer changes on success; failed runs cannot replace it.
        write_json(config.reports_dir / "latest.json", {
            "run_id": run_id, "run_dir": run_dir.relative_to(config.root).as_posix(),
            "curated_file": curated.relative_to(config.root).as_posix(),
            "sample_file": (curated_dir / "sample_daily_zone_counts.csv").relative_to(config.root).as_posix()})
        return metadata
    except Exception as exc:
        metadata.update({"status": "FAILED", "finished_at_utc": utc_now(),
                         "elapsed_seconds": round(time.monotonic() - started, 3),
                         "error_type": type(exc).__name__, "error": str(exc),
                         "completed_input_files": len(audits)})
        if run_dir.exists():
            write_json(run_dir / "run.json", metadata)
            if not (run_dir / "quality.json").exists():
                write_json(run_dir / "quality.json", {"status": "FAIL", "error_type": type(exc).__name__, "error": str(exc), "completed_input_files": len(audits)})
            event("FAILED", f"{type(exc).__name__}: {exc}")
        raise
    finally:
        if con:
            con.close()
        if downloader:
            downloader.close()
        lock_path.unlink(missing_ok=True)
