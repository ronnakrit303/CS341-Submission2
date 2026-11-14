import csv
import json
import os
from pathlib import Path
import subprocess
import sys
import duckdb
import pytest

from taxi_pipeline.config import month_range
from taxi_pipeline.download import Downloader, read_json
from taxi_pipeline.pipeline import run_pipeline
from taxi_pipeline.transform import QualityError, sql_text
from conftest import write_trip, write_zones


def latest(config):
    pointer = read_json(config.reports_dir / "latest.json")
    return pointer, config.root / pointer["run_dir"]


def read_csv(path):
    with path.open(encoding="utf-8", newline="") as source:
        return list(csv.DictReader(source))


def test_four_schemas_rejections_join_and_answer(fixture_config):
    config, _ = fixture_config
    result = run_pipeline(config)
    assert result["status"] == "SUCCESS"
    assert (result["raw_count"], result["valid_count"], result["invalid_count"]) == (28, 12, 16)
    pointer, directory = latest(config)
    quality = read_json(directory / "quality.json")
    assert all(check["passed"] for check in quality["checks"])
    audits = read_json(directory / "file_audit.json")
    for row in audits:
        assert [row[key] for key in ("missing_pickup", "missing_dropoff", "outside_period", "negative_duration")] == [1, 1, 1, 1]
        assert row["reason_total"] == row["invalid_count"]
    assert next(row for row in audits if row["taxi_type"] == "FHV")["negative_fare"] is None
    assert next(row for row in audits if row["taxi_type"] == "Yellow")["negative_fare"] == 3
    with duckdb.connect() as con:
        grouped = con.execute(f"SELECT zone_match_status,SUM(trip_count) FROM read_parquet({sql_text(config.root / pointer['curated_file'])}) GROUP BY ALL").fetchall()
    assert dict(grouped) == {"matched": 4, "missing": 4, "unmapped": 4}
    assert len(result["answer"]["winners"]) == 4  # Ties are explicit; winner is not hardcoded.
    assert result["answer"]["answers_original_question"] is False
    assert {row["taxi_type"] for row in read_csv(config.root / pointer["sample_file"])} == set(config.settings["taxi_types"])


def test_unchanged_offline_rerun_is_identical_without_accumulation(fixture_config):
    config, _ = fixture_config
    first = run_pipeline(config)
    second = run_pipeline(config, offline=True)
    assert second["run_id"] != first["run_id"]
    assert second["actions"] == {"reused": 4, "cached_verified": 4}
    assert second["valid_count"] == first["valid_count"]
    assert second["curated_content_sha256"] == first["curated_content_sha256"]
    assert second["curated_sha256"] == first["curated_sha256"]


def test_refresh_changed_partition_only_and_no_deduplication(fixture_config):
    config, upstream = fixture_config
    run_pipeline(config)
    item = config.manifest()[0]
    row = ("2024-01-01 10:00:00", "2024-01-01 10:10:00", 1)
    write_trip(upstream / item["source_file"], item["spec"], rows=[row, row])
    changed = run_pipeline(config, refresh=True)
    assert changed["actions"]["processed"] == 1
    assert changed["actions"]["reused"] == 3
    assert changed["valid_count"] == 11
    _, directory = latest(config)
    audit = next(a for a in read_json(directory / "file_audit.json") if a["taxi_type"] == item["taxi_type"])
    assert audit["duplicate_candidates"] == 1
    assert audit["valid_count"] == 2  # Candidate duplicates are retained.


def test_added_month_and_global_period_cache_invalidation(fixture_config):
    config, upstream = fixture_config
    first = run_pipeline(config)
    config.settings["end_month"] = "2024-02"
    for item in config.manifest():
        if item["source_month"] == "2024-02":
            write_trip(upstream / item["source_file"], item["spec"], month="2024-02")
    second = run_pipeline(config)
    assert second["input_files"] == 8
    assert second["valid_count"] == 2 * first["valid_count"]
    assert second["actions"]["processed"] == 8  # The global validity window is part of cache identity.


@pytest.mark.parametrize("failure", ["duplicate_lookup", "missing_schema", "empty_input"])
def test_failed_refresh_keeps_last_success(fixture_config, failure):
    config, upstream = fixture_config
    run_pipeline(config)
    previous = (config.reports_dir / "latest.json").read_bytes()
    if failure == "duplicate_lookup":
        write_zones(upstream / "zones.csv", duplicate=True)
    else:
        item = config.manifest()[0]
        write_trip(upstream / item["source_file"], item["spec"],
                   rows=[] if failure == "empty_input" else None,
                   drop_column=item["spec"]["pickup"] if failure == "missing_schema" else None)
    with pytest.raises(QualityError):
        run_pipeline(config, refresh=True)
    assert (config.reports_dir / "latest.json").read_bytes() == previous
    failed = [read_json(p) for p in (config.reports_dir / "runs").glob("*/run.json") if read_json(p)["status"] == "FAILED"]
    assert len(failed) == 1
    run = failed[0]
    assert run["steps"][run["current_step"] - 1]["status"] == "FAILED"
    assert all(step["status"] == "SKIPPED" for step in run["steps"][run["current_step"]:])
    log = (config.reports_dir / "runs" / run["run_id"] / "pipeline.log").read_text(encoding="utf-8")
    assert "[PIPELINE] [FAILED]" in log
    assert "[PIPELINE] [SUCCESS]" not in log
    assert not (config.data_dir / ".pipeline.lock").exists()


def test_all_invalid_fails_quality_gate(fixture_config):
    config, upstream = fixture_config
    for item in config.manifest():
        write_trip(upstream / item["source_file"], item["spec"], rows=[(None, None, 1)])
    with pytest.raises(QualityError):
        run_pipeline(config)
    assert not (config.reports_dir / "latest.json").exists()
    quality = read_json(next((config.reports_dir / "runs").glob("*/quality.json")))
    assert quality["status"] == "FAIL"


def test_zero_valid_types_are_kept_in_ranking(fixture_config):
    config, upstream = fixture_config
    for item in config.manifest()[:2]:
        write_trip(upstream / item["source_file"], item["spec"], rows=[(None, None, 1)])
    run_pipeline(config)
    _, directory = latest(config)
    rows = read_csv(directory / "ranking.csv")
    assert len(rows) == 4
    assert [row["rank"] for row in rows] == ["1", "1", "2", "2"]


def test_cross_source_month_validity_and_fractional_zone(fixture_config):
    config, upstream = fixture_config
    config.settings["end_month"] = "2024-02"
    for item in config.manifest():
        write_trip(upstream / item["source_file"], item["spec"],
                   rows=[("2024-02-01 10:00:00", "2024-02-01 10:10:00", 1.4)])
    run_pipeline(config)
    _, directory = latest(config)
    audits = read_json(directory / "file_audit.json")
    assert sum(a["source_month_mismatch"] for a in audits) == 4
    assert sum(a["valid_count"] for a in audits) == 8
    assert sum(a["missing_pickup_zone"] for a in audits) == 8


def test_corrupt_transformed_cache_is_recomputed(fixture_config):
    config, _ = fixture_config
    run_pipeline(config)
    partition = next((config.data_dir / "cache").glob("*/daily.parquet"))
    partition.write_bytes(b"damaged")
    second = run_pipeline(config, offline=True)
    assert second["actions"]["processed"] == 1
    assert second["actions"]["reused"] == 3


def test_corrupt_raw_snapshot_offline_fails(fixture_config):
    config, _ = fixture_config
    run_pipeline(config)
    path = config.data_dir / "raw" / config.manifest()[0]["source_file"]
    path.write_bytes(b"damaged")
    # Test HTTPS offline semantics independently of the file:// fixture exception.
    downloader = Downloader(attempts=1, offline=True)
    try:
        with pytest.raises(RuntimeError, match="Offline snapshot"):
            downloader.fetch("https://example.invalid/source.parquet", path)
    finally:
        downloader.close()


def test_lock_is_not_removed_by_competing_run(fixture_config):
    config, _ = fixture_config
    config.data_dir.mkdir()
    lock = config.data_dir / ".pipeline.lock"
    lock.write_text("another process", encoding="utf-8")
    with pytest.raises(RuntimeError, match="Another run"):
        run_pipeline(config)
    assert lock.read_text(encoding="utf-8") == "another process"


@pytest.mark.parametrize("start,end", [("2024-13", "2024-14"), ("2024-2", "2024-06"), ("2024-06", "2024-01")])
def test_invalid_months_rejected(start, end):
    with pytest.raises(ValueError):
        month_range(start, end)


def test_configuration_cannot_write_outside_workspace(fixture_config):
    config, _ = fixture_config
    config.settings["data_dir"] = "../outside"
    with pytest.raises(ValueError, match="inside the workspace"):
        config.validate()


def test_download_failure_does_not_replace_previous_snapshot(tmp_path):
    path = tmp_path / "cached.parquet"
    path.write_bytes(b"previous snapshot")
    downloader = Downloader(attempts=1, refresh=True)
    with pytest.raises(FileNotFoundError):
        downloader.fetch((tmp_path / "absent.parquet").as_uri(), path)
    assert path.read_bytes() == b"previous snapshot"
    assert not path.with_name(path.name + ".part").exists()
    downloader.close()


def test_exported_snapshot_is_independently_verifiable_and_tampering_fails(fixture_config):
    from scripts.export_evidence import export
    from scripts.verify_artifacts import verify
    config, _ = fixture_config
    run_pipeline(config)
    run_pipeline(config, offline=True)
    export(config.root)
    verify(config.root)
    target = config.root / "artifacts/results/ranking.csv"
    target.write_text("tampered", encoding="utf-8")
    with pytest.raises(RuntimeError, match="hash/size mismatch"):
        verify(config.root)


def test_readable_log_reports_complete_ordered_flow_and_cache_actions(fixture_config, capsys):
    config, _ = fixture_config
    run_pipeline(config)
    capsys.readouterr()
    result = run_pipeline(config, offline=True)
    output = capsys.readouterr().out
    _, directory = latest(config)
    assert (directory / "pipeline.log").read_text(encoding="utf-8") == output
    events = [json.loads(line) for line in (directory / "events.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [e["step"] for e in events if e["event"] == "STEP_START"] == list(range(1, 8))
    assert [e["step"] for e in events if e["event"] == "STEP_END"] == list(range(1, 8))
    assert all(e["step_total"] == 7 for e in events)
    assert events[-1]["status"] == "SUCCESS"
    assert "[STEP 03/07] [RUNNING] TRIPS" in output
    assert "[FILE 04/04] [TRANSFORM] [OK] REUSED" in output
    assert "[PIPELINE] [SUCCESS]" in output
    assert "Quality" in output and "Chart" in output and "Readable log" in output
    assert len(result["steps"]) == 7 and all(step["status"] == "OK" for step in result["steps"])


def test_publish_failure_never_logs_success_or_updates_latest(fixture_config, monkeypatch, capsys):
    import taxi_pipeline.pipeline as pipeline
    config, _ = fixture_config
    run_pipeline(config)
    previous = (config.reports_dir / "latest.json").read_bytes()
    capsys.readouterr()
    original = pipeline.write_json

    def fail_latest(path, value):
        if path == config.reports_dir / "latest.json":
            raise OSError("Simulated publication failure")
        return original(path, value)

    monkeypatch.setattr(pipeline, "write_json", fail_latest)
    with pytest.raises(OSError, match="publication failure"):
        run_pipeline(config, offline=True)
    output = capsys.readouterr().out
    assert "[STEP 07/07] [FAILED] PUBLISH" in output
    assert "[PIPELINE] [SUCCESS]" not in output
    assert (config.reports_dir / "latest.json").read_bytes() == previous
    failed = [read_json(p) for p in (config.reports_dir / "runs").glob("*/run.json") if read_json(p)["status"] == "FAILED"]
    assert failed[0]["steps"][-1]["status"] == "FAILED"


def test_cli_preflight_error_is_utf8_even_when_redirected_with_ascii_encoding():
    root = Path(__file__).resolve().parents[1]
    env = {**os.environ, "PYTHONIOENCODING": "ascii"}
    result = subprocess.run([sys.executable, str(root / "run_pipeline.py"), "--start-month", "2024-13"],
                            cwd=root, env=env, capture_output=True, timeout=30)
    assert result.returncode == 1
    error = result.stderr.decode("utf-8")
    assert "[STEP 01/07] [FAILED] PREPARE" in error
    assert "ไม่สามารถเริ่ม pipeline ได้" in error
    assert "UnicodeEncodeError" not in error
