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
from .progress import PipelineProgress, STEPS
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
    progress = None
    started = time.monotonic()
    metadata = {"run_id": run_id, "status": "RUNNING", "started_at_utc": utc_now(),
                "rules_version": RULES_VERSION, "effective_config": config.settings,
                "options": {"offline": offline, "refresh": refresh, "rebuild": rebuild},
                "source_code_sha256": source_fingerprint(),
                "step_total": len(STEPS),
                "versions": {"python": platform.python_version(), "duckdb": duckdb.__version__,
                             "requests": requests.__version__, "matplotlib": matplotlib.__version__}}
    manifests, audits, partitions, actions = [], [], [], Counter()

    def begin_step(number):
        progress.begin(number)
        metadata.update(current_step=number, steps=progress.snapshot())
        write_json(run_dir / "run.json", metadata)

    def complete_step(message):
        progress.complete(message)
        metadata.update(current_step=None, steps=progress.snapshot())
        write_json(run_dir / "run.json", metadata)

    try:
        run_dir.mkdir(parents=True, exist_ok=False)
        curated_dir.mkdir(parents=True, exist_ok=False)
        progress = PipelineProgress(run_dir)
        progress.header(run_id, config, offline=offline, refresh=refresh, rebuild=rebuild)
        write_json(run_dir / "run.json", metadata)
        begin_step(1)
        manifest = config.manifest()
        progress.detail(f"Manifest: {len(config.settings['taxi_types'])} taxi types x {len(config.months)} months = {len(manifest)} trip files")
        con = duckdb.connect()
        con.execute(f"SET threads = {config.settings['threads']}")
        con.execute(f"SET memory_limit = {sql_text(config.settings['memory_limit'])}")
        temp = config.data_dir / "cache" / "duckdb_temp"
        temp.mkdir(parents=True, exist_ok=True)
        con.execute(f"SET temp_directory = {sql_text(temp)}")
        downloader = Downloader(config.settings["download_attempts"], offline, refresh)
        complete_step("ระบบพร้อม รายการข้อมูลครบ และสร้าง run directory แล้ว")

        begin_step(2)
        lookup_path = config.data_dir / "raw" / "taxi_zone_lookup.csv"
        progress.detail("ตรวจ raw snapshot ของ CSV (SHA-256); ดาวน์โหลดตาม mode หากจำเป็น")
        lookup_info = downloader.fetch(config.settings["zone_lookup_url"], lookup_path)
        lookup_action = "ใช้ CSV เดิมหลังตรวจ hash ผ่าน" if lookup_info["download_action"] == "cached_verified" else "รับ CSV ใหม่แล้ว"
        progress.detail(f"{lookup_action}; ตรวจคอลัมน์และ LocationID ที่ไม่ซ้ำ", download_action=lookup_info["download_action"])
        manifests.append({"dataset": "taxi_zone_lookup", "source_file": lookup_path.name, **lookup_info})
        write_json(run_dir / "manifest.json", manifests)
        lookup_quality = load_zones(con, lookup_path)
        complete_step(f"ตารางพื้นที่ผ่านการตรวจสอบ {lookup_quality['rows']:,} unique zones")

        begin_step(3)
        progress.detail("แต่ละไฟล์: ตรวจ/รับ input -> ตรวจ cache -> คำนวณ audit และ daily aggregate เมื่อจำเป็น")
        for number, item in enumerate(manifest, 1):
            file_started = time.monotonic()
            progress.file(number, len(manifest), "INPUT", "RUNNING", f"{item['source_file']} | ตรวจ snapshot/SHA-256 หรือดาวน์โหลดตาม mode", source_file=item["source_file"])
            path = config.data_dir / "raw" / item["source_file"]
            info = downloader.fetch(item["url"], path)
            input_message = "ใช้ไฟล์เดิมหลังตรวจ SHA-256 ผ่าน" if info["download_action"] == "cached_verified" else "รับไฟล์ใหม่และบันทึก SHA-256 แล้ว"
            progress.file(number, len(manifest), "INPUT", "OK", f"{input_message} | {info['bytes'] / 1024**2:.2f} MiB", download_action=info["download_action"])
            manifests.append({"dataset": "trip_records", **{k: item[k] for k in ("taxi_type", "source_month", "source_file")}, **info})
            write_json(run_dir / "manifest.json", manifests)
            work = "คำนวณ schema checks, audit และ daily aggregate ใหม่ (--rebuild)" if rebuild else "ตรวจ aggregate cache; คำนวณ schema checks/audit/aggregate ใหม่เมื่อจำเป็น"
            progress.file(number, len(manifest), "TRANSFORM", "RUNNING", work)
            partition, audit, action = transform_file(con, path, item, config, info["sha256"], rebuild)
            actions[action] += 1
            actions[info["download_action"]] += 1
            partitions.append(partition)
            audits.append(audit)
            write_json(run_dir / "file_audit.json", audits)
            progress.file(number, len(manifest), "TRANSFORM", "OK", f"{action.upper()} | raw={audit['raw_count']:,} | valid={audit['valid_count']:,} | rejected={audit['invalid_count']:,} | {time.monotonic() - file_started:.2f}s", source_file=item["source_file"], transform_action=action, download_action=info["download_action"])
        complete_step(f"Trip files ครบ {len(audits)}/{len(manifest)} | processed={actions['processed']} | reused={actions['reused']}")

        begin_step(4)
        progress.detail("รวม daily aggregates และ LEFT JOIN ตารางพื้นที่ โดยเก็บ missing/unmapped zones ไว้")
        curated = curated_dir / "daily_zone_counts.parquet"
        curated_quality = build_curated(con, partitions, curated)
        progress.detail(f"เขียน {curated.relative_to(config.root).as_posix()}")
        complete_step(f"Curated output พร้อม: {curated_quality['curated_rows']:,} rows | {curated_quality['trip_count']:,} trip records")

        begin_step(5)
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
        for check in checks:
            progress.quality_check(check)
        for coverage in quality["zone_coverage"]:
            if coverage["zone_match_status"] != "matched":
                progress.detail(f"{coverage['taxi_type']}: {coverage['trip_count']:,} records มี zone={coverage['zone_match_status']} และยังนับรวมใน metric", status="WARN")
        progress.detail(f"คัดออกตามกฎเวลา {total_invalid:,} records | source-month mismatch={quality['diagnostics']['source_month_mismatch']:,} (diagnostic)")
        if quality["status"] != "PASS":
            raise QualityError("One or more required quality gates failed; see quality.json")
        complete_step(f"Quality PASS {len(checks)}/{len(checks)} gates | valid={total_valid:,} | rejected={total_invalid:,}")

        begin_step(6)
        progress.detail("รวมจำนวนจาก curated data เพื่อสร้างอันดับ สัดส่วน ตารางรายเดือน/พื้นที่ และกราฟ")
        answer, ranking = generate_report(con, audits, config, run_dir, curated)
        if sum(r["valid_count"] for r in ranking) != total_valid:
            raise QualityError("Ranking counts do not match audited valid count")
        for row in ranking:
            progress.detail(f"Rank {row['rank']} | {row['taxi_type']} | {row['valid_count']:,} valid records | {row['valid_share_pct']:.2f}%")
        complete_step(f"สร้างรายงานและกราฟแล้ว | Winner(s): {', '.join(answer['winners'])}")

        begin_step(7)
        progress.detail("คำนวณ checksums ของ curated output และเตรียมบันทึกสถานะรัน")
        canonical = hashlib.sha256()
        # Stream a deterministically sorted CSV for a representation-independent content hash.
        csv_path = curated_dir / "daily_zone_counts.csv"
        con.execute(f"COPY (SELECT * FROM curated ORDER BY taxi_type,source_month,pickup_date,pickup_location_id NULLS LAST) TO {sql_text(csv_path)} (FORMAT CSV, HEADER true)")
        with csv_path.open("rb") as data:
            for block in iter(lambda: data.read(8 * 1024 * 1024), b""):
                canonical.update(block)
        # Remove the temporary canonical CSV; retain Parquet and the small CSV example.
        csv_path.unlink()
        metadata.update({"status": "SUCCESS", "finished_at_utc": utc_now(),
                         "elapsed_seconds": round(time.monotonic() - started, 3),
                         "input_files": len(audits), "actions": dict(actions),
                         "raw_count": total_raw, "valid_count": total_valid, "invalid_count": total_invalid,
                         "curated_rows": curated_quality["curated_rows"],
                         "curated_sha256": sha256_file(curated),
                         "curated_content_sha256": canonical.hexdigest(), "answer": answer,
                         "current_step": None, "steps": progress.snapshot(completing=True)})
        write_json(run_dir / "run.json", metadata)
        # Only one small atomic pointer changes on success; failed runs cannot replace it.
        write_json(config.reports_dir / "latest.json", {
            "run_id": run_id, "run_dir": run_dir.relative_to(config.root).as_posix(),
            "curated_file": curated.relative_to(config.root).as_posix(),
            "sample_file": (curated_dir / "sample_daily_zone_counts.csv").relative_to(config.root).as_posix()})
        progress.complete("บันทึก SUCCESS และอัปเดต latest pointer สำเร็จ")
        progress.success(metadata, {
            "Curated": curated.relative_to(config.root).as_posix(),
            "CSV sample": (curated_dir / "sample_daily_zone_counts.csv").relative_to(config.root).as_posix(),
            "Analysis": (run_dir / "analysis.md").relative_to(config.root).as_posix(),
            "Chart": (run_dir / "taxi_usage.png").relative_to(config.root).as_posix(),
            "Quality": (run_dir / "quality.json").relative_to(config.root).as_posix(),
            "Readable log": (run_dir / "pipeline.log").relative_to(config.root).as_posix(),
            "Events": (run_dir / "events.jsonl").relative_to(config.root).as_posix(),
            "Latest": (config.reports_dir / "latest.json").relative_to(config.root).as_posix(),
        })
        return metadata
    except Exception as exc:
        metadata.update({"status": "FAILED", "finished_at_utc": utc_now(),
                         "elapsed_seconds": round(time.monotonic() - started, 3),
                         "error_type": type(exc).__name__, "error": str(exc),
                         "completed_input_files": len(audits)})
        if progress:
            progress.failed(exc)
            metadata.update(current_step=progress.current, steps=progress.snapshot())
            exc.pipeline_logged = True
        if run_dir.exists():
            write_json(run_dir / "run.json", metadata)
            if not (run_dir / "quality.json").exists():
                write_json(run_dir / "quality.json", {"status": "FAIL", "error_type": type(exc).__name__, "error": str(exc), "completed_input_files": len(audits)})
        raise
    finally:
        if con:
            con.close()
        if downloader:
            downloader.close()
        lock_path.unlink(missing_ok=True)
