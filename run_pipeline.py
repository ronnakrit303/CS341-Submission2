"""Run from anywhere; paths in configuration resolve against this repository."""

import argparse
from pathlib import Path
import sys

from taxi_pipeline.config import Config
from taxi_pipeline.pipeline import run_pipeline
from taxi_pipeline.progress import STEPS, configure_terminal


def main():
    configure_terminal()
    parser = argparse.ArgumentParser(description="Reproducible NYC TLC daily taxi-count pipeline")
    parser.add_argument("--config", default="config/pipeline.json")
    parser.add_argument("--start-month", help="Inclusive YYYY-MM; default from config")
    parser.add_argument("--end-month", help="Inclusive YYYY-MM; extend this to update the period")
    parser.add_argument("--offline", action="store_true", help="Use verified local inputs; no HTTP requests")
    parser.add_argument("--refresh", action="store_true", help="Download all requested sources again to detect revisions")
    parser.add_argument("--rebuild", action="store_true", help="Recompute transforms instead of reusing partitions")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = root / config_path
    try:
        config = Config.load(config_path, root, args.start_month, args.end_month)
        run = run_pipeline(config, offline=args.offline, refresh=args.refresh, rebuild=args.rebuild)
        print(f"Status: SUCCESS | Run ID: {run['run_id']} | Valid: {run['valid_count']:,}")
        return 0
    except Exception as exc:
        if not getattr(exc, "pipeline_logged", False):
            print(f"[STEP 01/{len(STEPS):02d}] [FAILED] PREPARE - ไม่สามารถเริ่ม pipeline ได้", file=sys.stderr)
        print(f"Status: FAILED | {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
