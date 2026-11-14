"""Export two comparable successful runs and their actual outputs for GitHub."""

from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from taxi_pipeline.download import read_json, sha256_file, write_json


def export(root=ROOT):
    latest = read_json(root / "reports/latest.json")
    current = read_json(root / latest["run_dir"] / "run.json")
    if current["status"] != "SUCCESS":
        raise RuntimeError("Only SUCCESS runs may be exported")
    successes = []
    for path in (root / "reports/runs").glob("*/run.json"):
        run = read_json(path)
        if (run["status"] == "SUCCESS" and run["effective_config"] == current["effective_config"]
                and run["source_code_sha256"] == current["source_code_sha256"]):
            successes.append(run)
    successes.sort(key=lambda r: (r["started_at_utc"], r["run_id"]))
    previous = next((r for r in reversed(successes) if r["run_id"] != current["run_id"]), None)
    if previous is None:
        raise RuntimeError("Run the full pipeline and an unchanged rerun before exporting")
    equivalent = all(previous[key] == current[key] for key in (
        "raw_count", "valid_count", "invalid_count", "curated_rows", "curated_content_sha256", "answer"))
    if not equivalent:
        raise RuntimeError("Selected runs differ; do not claim unchanged-rerun reproducibility")
    if current["actions"].get("reused", 0) != current["input_files"]:
        raise RuntimeError("Latest run must demonstrate reuse of every transformed input")
    dest = root / "artifacts"
    for directory in ("curated", "results", "quality", "provenance", "runs"):
        (dest / directory).mkdir(parents=True, exist_ok=True)
    run_dir = root / latest["run_dir"]
    for filename in ("ranking.csv", "monthly_counts.csv", "source_month_counts.csv", "borough_counts.csv", "answer.json", "analysis.md", "taxi_usage.png", "baseline_comparison.csv"):
        source = run_dir / filename
        if source.exists():
            shutil.copyfile(source, dest / "results" / filename)
    for filename in ("quality.json", "file_audit.csv", "file_audit.json"):
        shutil.copyfile(run_dir / filename, dest / "quality" / filename)
    shutil.copyfile(run_dir / "manifest.json", dest / "provenance/manifest.json")
    write_json(dest / "provenance/effective_config.json", current["effective_config"])
    shutil.copyfile(root / latest["curated_file"], dest / "curated/daily_zone_counts.parquet")
    shutil.copyfile(root / latest["sample_file"], dest / "curated/sample_daily_zone_counts.csv")
    for run in (previous, current):
        target = dest / "runs" / run["run_id"]
        target.mkdir(parents=True, exist_ok=True)
        for filename in ("run.json", "events.jsonl"):
            shutil.copyfile(root / "reports/runs" / run["run_id"] / filename, target / filename)
    write_json(dest / "reproducibility.json", {
        "first_run": previous["run_id"], "unchanged_rerun": current["run_id"],
        "same_counts_and_curated_content": equivalent,
        "first_run_actions": previous["actions"], "rerun_actions": current["actions"],
        "curated_content_sha256": current["curated_content_sha256"],
        "first_elapsed_seconds": previous["elapsed_seconds"], "rerun_elapsed_seconds": current["elapsed_seconds"],
        "scope": "Actual configured sources; no synthetic fixture records included"})
    notebook = next(root.glob("*_Submission_1_CS341.ipynb"), None)
    if notebook:
        write_json(dest / "provenance/baseline_notebook.json", {
            "path": notebook.name, "sha256": sha256_file(notebook),
            "purpose": "Read-only Submission 1 reference; saved outputs, not a new notebook execution"})
    (dest / "README.md").write_text(
        "# Executed pipeline evidence\n\n"
        "These are actual full-data outputs exported from the two SUCCESS runs named in `reproducibility.json`. "
        "Raw inputs are deliberately excluded; exact URLs, hashes and retrieval metadata are in `provenance/manifest.json`.\n\n"
        "- `curated/`: complete compressed daily pickup-zone fact table and a 200-row CSV example (up to 50 rows per type).\n"
        "- `quality/`: actual quality gates and all 24 source-file audits.\n"
        "- `results/`: analysis, ranking, monthly/borough totals and chart generated from curated data.\n"
        "- `runs/`: full-run and unchanged-rerun status plus chronological event logs; timestamps are UTC.\n"
        "- `provenance/`: downloaded-source manifest, effective configuration and original notebook hash.\n"
        "- `file_manifest.json`: SHA-256 and bytes for every exported evidence file except this manifest itself.\n\n"
        "The local working paths (`reports/runs/...`, `data/curated/...`) are represented by these exported directories. "
        "`python scripts/verify_artifacts.py` verifies the committed snapshot without downloading raw data.\n",
        encoding="utf-8")
    entries = []
    for path in sorted(dest.rglob("*")):
        if path.is_file() and path.name != "file_manifest.json":
            entries.append({"path": path.relative_to(dest).as_posix(), "bytes": path.stat().st_size,
                            "sha256": sha256_file(path)})
    write_json(dest / "file_manifest.json", {"files": entries})
    print(f"Exported {len(entries)} evidence files from {previous['run_id']} and {current['run_id']}")


if __name__ == "__main__":
    export()
