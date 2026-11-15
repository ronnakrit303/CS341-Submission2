"""DuckDB transforms and quality gates; no full trip DataFrame is created."""

from pathlib import Path

from . import RULES_VERSION
from .config import digest_json
from .download import atomic_replace, read_json, sha256_file, write_json


class QualityError(RuntimeError):
    """A required data contract failed; the run must not publish results."""


def sql_text(value):
    return "'" + str(value).replace("'", "''") + "'"


def sql_column(value):
    return '"' + str(value).replace('"', '""') + '"'


def one_row(con, query):
    cursor = con.execute(query)
    return dict(zip([column[0] for column in cursor.description], cursor.fetchone()))


def check_rows(con, query):
    return [dict(zip([d[0] for d in con.description], row)) for row in con.execute(query).fetchall()]


def load_zones(con, path: Path):
    """Require one dimension row per zone; left joins can then preserve counts."""
    con.execute(f"CREATE OR REPLACE TEMP TABLE zone_source AS SELECT * FROM read_csv({sql_text(path)}, all_varchar=true)")
    columns = {row[0] for row in con.execute("DESCRIBE zone_source").fetchall()}
    required = {"LocationID", "Borough", "Zone", "service_zone"}
    if not required <= columns:
        raise QualityError(f"Zone CSV missing columns: {sorted(required - columns)}")
    result = one_row(con, '''
        SELECT COUNT(*) AS rows,
          COUNT(*) FILTER (WHERE TRY_CAST(LocationID AS INTEGER) IS NULL
            OR TRY_CAST(LocationID AS DOUBLE) != TRY_CAST(LocationID AS INTEGER)) AS invalid_keys,
          COUNT(DISTINCT TRY_CAST(LocationID AS INTEGER)) AS unique_keys,
          COUNT(*) FILTER (WHERE NULLIF(TRIM(Zone), '') IS NULL) AS empty_zone_names
        FROM zone_source
    ''')
    if (result["rows"] == 0 or result["invalid_keys"] or result["empty_zone_names"]
            or result["unique_keys"] != result["rows"]):
        raise QualityError(f"Zone lookup must have unique non-null integer keys and zone names: {result}")
    con.execute('''CREATE OR REPLACE TEMP TABLE zones AS
        SELECT CAST(LocationID AS INTEGER) AS pickup_location_id,
          COALESCE(NULLIF(TRIM(Borough), ''), 'Unknown') AS borough,
          Zone AS zone, COALESCE(NULLIF(TRIM(service_zone), ''), 'Unknown') AS service_zone
        FROM zone_source''')
    return result


def transform_file(con, source: Path, item: dict, config, input_hash: str, rebuild=False):
    """Return a cached, pre-join daily aggregate and file-level audit."""
    signature = {"rules_version": RULES_VERSION, "transform_code_sha256": sha256_file(Path(__file__)), "input_sha256": input_hash,
                 "start": config.start, "stop": config.stop,
                 "taxi_type": item["taxi_type"], "source_file": item["source_file"], "spec": item["spec"]}
    key = digest_json(signature)
    directory = config.data_dir / "cache" / key
    aggregate = directory / "daily.parquet"
    receipt = directory / "receipt.json"
    if not rebuild and aggregate.exists() and receipt.exists():
        cached = read_json(receipt)
        if cached.get("signature") == signature and sha256_file(aggregate) == cached.get("aggregate_sha256"):
            return aggregate, cached["audit"], "reused"

    spec = item["spec"]
    columns = {r[0] for r in con.execute(f"DESCRIBE SELECT * FROM read_parquet({sql_text(source)})").fetchall()}
    required = {spec[k] for k in ("pickup", "dropoff", "pu_location", "do_location")}
    if not required <= columns:
        raise QualityError(f"{item['source_file']} missing required columns: {sorted(required - columns)}")

    def cast(key, dtype):
        name = spec.get(key)
        return f"TRY_CAST({sql_column(name)} AS {dtype})" if name and name in columns else f"NULL::{dtype}"

    # Fractional/overflow location values become NULL rather than rounding into a real zone.
    location = cast("pu_location", "BIGINT")
    numeric_location = cast("pu_location", "DOUBLE")
    con.execute(f'''CREATE OR REPLACE TEMP VIEW normalized AS
        SELECT {cast('pickup', 'TIMESTAMP')} AS pickup,
          {cast('dropoff', 'TIMESTAMP')} AS dropoff,
          CASE WHEN {numeric_location} = {location} THEN {location} ELSE NULL END AS pickup_location_id,
          {cast('do_location', 'VARCHAR')} AS dropoff_location,
          {cast('distance', 'DOUBLE')} AS distance,
          {cast('fare', 'DOUBLE')} AS fare,
          {cast('passenger', 'DOUBLE')} AS passenger
        FROM read_parquet({sql_text(source)})''')
    con.execute(f'''CREATE OR REPLACE TEMP VIEW classified AS
        SELECT *, CASE
          WHEN pickup IS NULL THEN 'missing_pickup'
          WHEN dropoff IS NULL THEN 'missing_dropoff'
          WHEN pickup < TIMESTAMP {sql_text(config.start)}
            OR pickup >= TIMESTAMP {sql_text(config.stop)} THEN 'outside_period'
          WHEN dropoff < pickup THEN 'negative_duration'
          ELSE NULL END AS rejection_reason
        FROM normalized''')
    # COUNT(*) FILTER returns integer 0 even for an empty input.
    audit = one_row(con, f'''SELECT COUNT(*) AS raw_count,
        COUNT(*) FILTER (WHERE rejection_reason IS NULL) AS valid_count,
        COUNT(*) FILTER (WHERE rejection_reason IS NOT NULL) AS invalid_count,
        COUNT(*) FILTER (WHERE rejection_reason = 'missing_pickup') AS missing_pickup,
        COUNT(*) FILTER (WHERE rejection_reason = 'missing_dropoff') AS missing_dropoff,
        COUNT(*) FILTER (WHERE rejection_reason = 'outside_period') AS outside_period,
        COUNT(*) FILTER (WHERE rejection_reason = 'negative_duration') AS negative_duration,
        COUNT(*) FILTER (WHERE rejection_reason IS NULL AND distance = 0) AS zero_distance,
        COUNT(*) FILTER (WHERE rejection_reason IS NULL AND fare < 0) AS negative_fare,
        COUNT(*) FILTER (WHERE rejection_reason IS NULL AND passenger IS NULL) AS missing_passenger,
        COUNT(*) FILTER (WHERE rejection_reason IS NULL AND pickup_location_id IS NULL) AS missing_pickup_zone,
        COUNT(*) FILTER (WHERE rejection_reason IS NULL AND STRFTIME(pickup, '%Y-%m') <> {sql_text(item['source_month'])}) AS source_month_mismatch
        FROM classified''')
    for name, field in (("zero_distance", "distance"), ("negative_fare", "fare"), ("missing_passenger", "passenger")):
        if not spec.get(field) or spec[field] not in columns:
            audit[name] = None  # Not available is different from an observed count of zero.
    duplicate = one_row(con, '''SELECT COUNT(*) AS sample_rows,
        COUNT(*) - COUNT(DISTINCT (pickup, dropoff, pickup_location_id, dropoff_location)) AS duplicate_candidates
        FROM (SELECT * FROM normalized LIMIT 10000)''')
    audit.update(duplicate)
    audit.update({k: item[k] for k in ("taxi_type", "source_month", "source_file")})
    audit["input_sha256"] = input_hash
    audit["schema_ok"] = True
    audit["unavailable_diagnostics"] = [k for k in ("distance", "fare", "passenger") if not spec.get(k) or spec[k] not in columns]
    audit["reason_total"] = sum(audit[k] for k in ("missing_pickup", "missing_dropoff", "outside_period", "negative_duration"))
    audit["reconciled"] = audit["raw_count"] == audit["valid_count"] + audit["invalid_count"] and audit["invalid_count"] == audit["reason_total"]
    if audit["raw_count"] <= 0 or not audit["reconciled"]:
        raise QualityError(f"Empty input or inconsistent audit: {item['source_file']}")
    directory.mkdir(parents=True, exist_ok=True)
    temporary = aggregate.with_suffix(".parquet.part")
    con.execute(f'''COPY (
        SELECT CAST(pickup AS DATE) AS pickup_date,
          {sql_text(item['taxi_type'])} AS taxi_type,
          pickup_location_id,
          {sql_text(item['source_month'])} AS source_month,
          {sql_text(item['source_file'])} AS source_file,
          COUNT(*)::BIGINT AS trip_count
        FROM classified WHERE rejection_reason IS NULL
        GROUP BY pickup_date, pickup_location_id
        ORDER BY pickup_date, pickup_location_id NULLS LAST
        ) TO {sql_text(temporary)} (FORMAT PARQUET, COMPRESSION ZSTD)''')
    atomic_replace(temporary, aggregate)
    aggregate_count = con.execute(f"SELECT COALESCE(SUM(trip_count), 0) FROM read_parquet({sql_text(aggregate)})").fetchone()[0]
    if aggregate_count != audit["valid_count"]:
        raise QualityError(f"Aggregate count does not match audit: {item['source_file']}")
    write_json(receipt, {"signature": signature, "audit": audit, "aggregate_sha256": sha256_file(aggregate)})
    return aggregate, audit, "processed"


def build_curated(con, partitions, output: Path):
    paths = ", ".join(sql_text(p) for p in partitions)
    con.execute(f"CREATE OR REPLACE TEMP VIEW daily_base AS SELECT * FROM read_parquet([{paths}])")
    before = con.execute("SELECT COALESCE(SUM(trip_count),0) FROM daily_base").fetchone()[0]
    output.parent.mkdir(parents=True, exist_ok=True)
    con.execute(f'''COPY (
        SELECT d.pickup_date, d.taxi_type, d.pickup_location_id,
          COALESCE(z.borough, 'Unknown') AS borough,
          COALESCE(z.zone, 'Unknown / unmapped') AS zone,
          COALESCE(z.service_zone, 'Unknown') AS service_zone,
          CASE WHEN d.pickup_location_id IS NULL THEN 'missing'
            WHEN z.pickup_location_id IS NULL THEN 'unmapped'
            ELSE 'matched' END AS zone_match_status,
          d.source_month, d.source_file, d.trip_count
        FROM daily_base d LEFT JOIN zones z USING (pickup_location_id)
        ORDER BY d.taxi_type, d.source_month, d.pickup_date, d.pickup_location_id NULLS LAST
        ) TO {sql_text(output)} (FORMAT PARQUET, COMPRESSION ZSTD)''')
    con.execute(f"CREATE OR REPLACE TEMP VIEW curated AS SELECT * FROM read_parquet({sql_text(output)})")
    result = one_row(con, '''SELECT COUNT(*) AS curated_rows,
        COALESCE(SUM(trip_count),0)::BIGINT AS trip_count,
        COUNT(*) FILTER (WHERE trip_count <= 0) AS nonpositive_groups,
        COUNT(*) - COUNT(DISTINCT (pickup_date,taxi_type,pickup_location_id,source_file)) AS duplicate_keys
        FROM curated''')
    if result["trip_count"] != before or result["nonpositive_groups"] or result["duplicate_keys"]:
        raise QualityError(f"Curated join/uniqueness/count preservation failed: {result}")
    result["join_count_preserved"] = True
    result["zone_coverage"] = check_rows(con, '''SELECT taxi_type, zone_match_status,
        SUM(trip_count)::BIGINT AS trip_count FROM curated GROUP BY ALL ORDER BY ALL''')
    return result
