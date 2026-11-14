"""Human-readable evidence generated from curated counts, not baseline constants."""

import csv
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter

from .download import read_json, write_json
from .transform import check_rows, sql_text


def write_csv(path, rows):
    if not rows:
        raise ValueError(f"Cannot export an empty table: {path}")
    with Path(path).open("w", encoding="utf-8", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=list(rows[0]))
        writer.writeheader()
        for row in rows:
            writer.writerow({k: v if not isinstance(v, list) else ";".join(v) for k, v in row.items()})


def generate_report(con, audits, config, report_dir: Path, curated_path: Path):
    ranking = check_rows(con, '''WITH totals AS (
        SELECT taxi_type, SUM(trip_count)::BIGINT AS valid_count FROM curated GROUP BY taxi_type
      ) SELECT taxi_type, valid_count,
        100.0 * valid_count / SUM(valid_count) OVER () AS valid_share_pct,
        DENSE_RANK() OVER (ORDER BY valid_count DESC) AS rank
      FROM totals ORDER BY rank, taxi_type''')
    raw = {name: {"raw_count": 0, "invalid_count": 0} for name in config.settings["taxi_types"]}
    for audit in audits:
        for field in ("raw_count", "invalid_count"):
            raw[audit["taxi_type"]][field] += audit[field]
    # Include valid=0 categories even when they produce no rows in the curated dataset.
    seen = {r["taxi_type"] for r in ranking}
    for name in sorted(set(raw) - seen):
        ranking.append({"taxi_type": name, "valid_count": 0, "valid_share_pct": 0.0})
    ranking.sort(key=lambda r: (-r["valid_count"], r["taxi_type"]))
    distinct_counts = sorted({r["valid_count"] for r in ranking}, reverse=True)
    for row in ranking:
        row["rank"] = distinct_counts.index(row["valid_count"]) + 1
        row.update(raw[row["taxi_type"]])
        row["invalid_rate_pct"] = 100 * row["invalid_count"] / row["raw_count"]
        row["raw_rank"] = 1 + sum(value > row["raw_count"] for value in {v["raw_count"] for v in raw.values()})
    write_csv(report_dir / "ranking.csv", ranking)
    monthly = check_rows(con, '''SELECT taxi_type, STRFTIME(pickup_date,'%Y-%m') AS pickup_month,
        SUM(trip_count)::BIGINT AS valid_count FROM curated GROUP BY ALL ORDER BY ALL''')
    write_csv(report_dir / "monthly_counts.csv", monthly)
    source_monthly = [dict((k, a[k]) for k in ("taxi_type", "source_month", "raw_count", "valid_count", "invalid_count")) for a in audits]
    write_csv(report_dir / "source_month_counts.csv", source_monthly)
    by_borough = check_rows(con, '''SELECT taxi_type, borough, SUM(trip_count)::BIGINT AS valid_count
        FROM curated GROUP BY ALL ORDER BY taxi_type, valid_count DESC''')
    write_csv(report_dir / "borough_counts.csv", by_borough)
    con.execute(f'''COPY (SELECT * FROM curated
        QUALIFY ROW_NUMBER() OVER (PARTITION BY taxi_type ORDER BY source_month,pickup_date,pickup_location_id NULLS LAST) <= 50
        ORDER BY taxi_type, source_month, pickup_date,pickup_location_id NULLS LAST)
        TO {sql_text(curated_path.parent / 'sample_daily_zone_counts.csv')} (FORMAT CSV, HEADER true)''')
    best = max(r["valid_count"] for r in ranking)
    winners = [r["taxi_type"] for r in ranking if r["valid_count"] == best]
    raw_best = max(v["raw_count"] for v in raw.values())
    raw_winners = sorted(name for name, values in raw.items() if values["raw_count"] == raw_best)
    period = f"{config.settings['start_month']} to {config.settings['end_month']}"
    is_h1 = config.settings["start_month"] == "2024-01" and config.settings["end_month"] == "2024-06"
    answer = {"period": period, "answers_original_question": is_h1,
              "metric": "valid trip-record count", "winners": winners,
              "winner_valid_count": best, "total_valid_count": sum(r["valid_count"] for r in ranking),
              "winner_changed_after_cleaning": sorted(winners) != raw_winners}
    write_json(report_dir / "answer.json", answer)
    text = f"# Analysis: NYC TLC taxi usage ({period})\n\n"
    text += "Question: Which taxi type was the most used in the first half of 2024?\n\n" if is_h1 else "This run uses a different period and does not by itself answer the original H1 2024 question.\n\n"
    if len(winners) == 1:
        text += f"**{winners[0]}** has the most valid trip records: **{best:,}**, or **{ranking[0]['valid_share_pct']:.2f}%** of the valid total.\n\n"
    else:
        text += f"The highest count is tied: **{', '.join(winners)}**, with **{best:,}** valid trip records each.\n\n"
    text += "| Rank | Taxi type | Raw records | Valid records | Rejected | Share |\n|---|---|---:|---:|---:|---:|\n"
    for row in ranking:
        text += f"| {row['rank']} | {row['taxi_type']} | {row['raw_count']:,} | {row['valid_count']:,} | {row['invalid_count']:,} | {row['valid_share_pct']:.2f}% |\n"
    text += "\nOne record is a published trip record; it does not represent a unique passenger, revenue, or a causal change in preferences. Missing and unmapped zones remain in the metric.\n\n"
    text += f"Winner changed after cleaning: **{answer['winner_changed_after_cleaning']}**. See `file_audit.csv` and `quality.json` for the rejection accounting and quality gates.\n"
    (report_dir / "analysis.md").write_text(text, encoding="utf-8")

    baseline_path = config.root / "baseline" / "expected_counts.json"
    if is_h1 and baseline_path.exists():
        baseline = read_json(baseline_path)
        comparison = [{"taxi_type": r["taxi_type"], "baseline_valid_count": baseline["valid_counts"][r["taxi_type"]],
                       "pipeline_valid_count": r["valid_count"],
                       "difference": r["valid_count"] - baseline["valid_counts"][r["taxi_type"]]} for r in ranking]
        write_csv(report_dir / "baseline_comparison.csv", comparison)

    colors = {"Yellow": "#c59612", "Green": "#248467", "FHV": "#4082b6", "High Volume FHV": "#7355ae"}
    data = list(reversed(ranking))
    fig, ax = plt.subplots(figsize=(10, 5), layout="constrained")
    ax.barh([r["taxi_type"] for r in data], [r["valid_count"] for r in data], color=[colors[r["taxi_type"]] for r in data])
    ax.set_title(f"Valid NYC TLC trip records, {period}", loc="left", pad=16, weight="bold")
    ax.set_xlabel("Valid trip records (millions)")
    ax.xaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{value / 1e6:g}"))
    ax.set_xlim(0, best * 1.32)
    ax.grid(axis="x", alpha=0.2)
    ax.set_axisbelow(True)
    ax.spines[["top", "right", "left"]].set_visible(False)
    for i, row in enumerate(data):
        ax.text(row["valid_count"] + best * 0.012, i, f"{row['valid_count']:,}", va="center", fontsize=10)
    fig.savefig(report_dir / "taxi_usage.png", dpi=160)
    plt.close(fig)
    return answer, ranking
