# Analysis: NYC TLC taxi usage (2024-01 to 2024-06)

Question: Which taxi type was the most used in the first half of 2024?

**High Volume FHV** has the most valid trip records: **120,864,668**, or **80.76%** of the valid total.

| Rank | Taxi type | Raw records | Valid records | Rejected | Share |
|---|---|---:|---:|---:|---:|
| 1 | High Volume FHV | 120,864,668 | 120,864,668 | 0 | 80.76% |
| 2 | Yellow | 20,332,093 | 20,331,754 | 339 | 13.59% |
| 3 | FHV | 8,119,228 | 8,119,228 | 0 | 5.43% |
| 4 | Green | 339,807 | 339,801 | 6 | 0.23% |

One record is a published trip record; it does not represent a unique passenger, revenue, or a causal change in preferences. Missing and unmapped zones remain in the metric.

Winner changed after cleaning: **False**. See `file_audit.csv` and `quality.json` for the rejection accounting and quality gates.
