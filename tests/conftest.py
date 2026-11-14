"""Small local Parquet/CSV sources exercise the real pipeline without HTTP."""

import csv
import json
from pathlib import Path

import duckdb
import pytest

from taxi_pipeline.config import Config
from taxi_pipeline.transform import sql_column, sql_text


ROOT = Path(__file__).resolve().parents[1]


def write_trip(path, spec, month="2024-01", rows=None, drop_column=None):
    start = month + "-01 10:00:00"
    end = month + "-01 10:10:00"
    if rows is None:
        rows = [(start, end, 1), (start, end, 999), (start, end, None),
                (None, None, 1), (start, None, 1),
                ("2023-12-31 10:00:00", "2023-12-31 10:10:00", 1),
                (start, month + "-01 09:00:00", 1)]
    fields = [(spec["pickup"], "VARCHAR"), (spec["dropoff"], "VARCHAR"),
              (spec["pu_location"], "DOUBLE"), (spec["do_location"], "DOUBLE")]
    optional = [spec[k] for k in ("distance", "fare", "passenger") if spec.get(k)]
    fields += [(name, "DOUBLE") for name in optional]
    with duckdb.connect() as con:
        ddl = ", ".join(f"{sql_column(name)} {dtype}" for name, dtype in fields)
        con.execute(f"CREATE TABLE trips ({ddl})")
        if rows:
            values = []
            for pickup, dropoff, pu in rows:
                extras = [{spec.get('distance'): 0.0, spec.get('fare'): -2.0, spec.get('passenger'): None}[name] for name in optional]
                values.append((pickup, dropoff, pu, 1, *extras))
            con.executemany(f"INSERT INTO trips VALUES ({','.join('?' for _ in fields)})", values)
        selection = "*" if not drop_column else "* EXCLUDE (" + sql_column(drop_column) + ")"
        con.execute(f"COPY (SELECT {selection} FROM trips) TO {sql_text(path)} (FORMAT PARQUET)")


def write_zones(path, duplicate=False):
    with path.open("w", encoding="utf-8", newline="") as target:
        writer = csv.writer(target)
        writer.writerow(["LocationID", "Borough", "Zone", "service_zone"])
        writer.writerow([1, "Manhattan", "Test zone", "Yellow Zone"])
        if duplicate:
            writer.writerow([1, "Queens", "Duplicate key", "Other"])


@pytest.fixture
def fixture_config(tmp_path):
    upstream = tmp_path / "upstream"
    upstream.mkdir()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    settings = json.loads((ROOT / "config/pipeline.json").read_text(encoding="utf-8"))
    settings.update({"start_month": "2024-01", "end_month": "2024-01",
                     "trip_base_url": upstream.as_uri(),
                     "zone_lookup_url": (upstream / "zones.csv").as_uri(),
                     "download_attempts": 1, "memory_limit": "512MB"})
    config = Config(settings, workspace)
    config.validate()
    for item in config.manifest():
        write_trip(upstream / item["source_file"], item["spec"])
    write_zones(upstream / "zones.csv")
    return config, upstream
