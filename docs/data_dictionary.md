# Data dictionary และขอบเขตข้อมูล

## Curated fact table

ไฟล์เต็มอยู่ที่ [`artifacts/curated/daily_zone_counts.parquet`](../artifacts/curated/daily_zone_counts.parquet) และมี [ตัวอย่าง CSV](../artifacts/curated/sample_daily_zone_counts.csv) สูงสุด 50 แถวต่อประเภท Taxi รวม 200 แถว ตัวอย่างเป็นแถวแรกตามลำดับที่แน่นอนของแต่ละประเภท ไม่ใช่ random sample และไม่ควรใช้ตัวอย่างนี้คำนวณคำตอบทั้งชุด

**Grain:** หนึ่งแถวคือจำนวน valid trip records ของ `pickup_date × taxi_type × pickup_location_id × source_file` ต้องรวม `source_file` ใน key เพราะอาจมี record ของวันเดียวกันอยู่ในหลายไฟล์ต้นทาง ไม่ใช่หนึ่งแถวต่อเที่ยว และตารางไม่ได้เติมกลุ่มที่มีจำนวนศูนย์

| Column | DuckDB type | ความหมาย |
|---|---|---|
| `pickup_date` | DATE | วันที่รับผู้โดยสารจาก timestamp ต้นทาง ตามเวลาที่แหล่งข้อมูลบันทึก |
| `taxi_type` | VARCHAR | Yellow, Green, FHV หรือ High Volume FHV |
| `pickup_location_id` | BIGINT nullable | รหัสพื้นที่รับผู้โดยสาร; ค่าไม่มี/แปลงไม่ได้/เศษส่วนเป็น NULL |
| `borough` | VARCHAR | เขตจาก CSV lookup; ค่าไม่พร้อมใช้แสดง Unknown |
| `zone` | VARCHAR | ชื่อ Taxi Zone; ถ้าจับคู่ไม่ได้แสดง Unknown / unmapped |
| `service_zone` | VARCHAR | กลุ่มบริการตาม lookup; ค่าไม่พร้อมใช้แสดง Unknown |
| `zone_match_status` | VARCHAR | matched, missing หรือ unmapped |
| `source_month` | VARCHAR | เดือนตามชื่อไฟล์ต้นทาง รูปแบบ YYYY-MM |
| `source_file` | VARCHAR | ชื่อไฟล์ Parquet ต้นทางสำหรับตรวจสอบย้อนกลับ |
| `trip_count` | BIGINT | จำนวน valid records ในกลุ่ม เป็นจำนวนเต็มบวก |

ตัวอย่าง query ที่รวมทุก source file อย่างถูกต้อง:

```sql
SELECT taxi_type, SUM(trip_count) AS valid_records
FROM read_parquet('artifacts/curated/daily_zone_counts.parquet')
GROUP BY taxi_type ORDER BY valid_records DESC;
```

การวิเคราะห์รายเดือนต้องใช้ `pickup_date` หากต้องการเดือนที่เกิดการเดินทางจริง ส่วน `source_month` ใช้ตรวจที่มาของไฟล์ ผลทั้งสองมุมมีแยกไว้ใน `monthly_counts.csv` และ `source_month_counts.csv`

## กฎ valid และเหตุผลคัดออก

ใช้กฎเดิมจาก Submission 1 ตามลำดับแรกที่ผิด เพื่อไม่ให้นับ invalid record เดียวซ้ำหลายเหตุผล:

1. `missing_pickup`: pickup ไม่มีค่าหรือแปลงเป็น timestamp ไม่ได้
2. `missing_dropoff`: pickup ใช้ได้ แต่ dropoff ไม่มีค่าหรือแปลงไม่ได้
3. `outside_period`: timestamp ทั้งคู่ใช้ได้ แต่ pickup อยู่นอกช่วงที่กำหนด (รวมวันเริ่ม ไม่รวมวันสิ้นสุด)
4. `negative_duration`: pickup อยู่ในช่วง แต่ dropoff ก่อน pickup

record ที่ไม่ผิดกฎเหล่านี้เป็น valid รวมถึงระยะเวลาเป็นศูนย์ ไม่บังคับให้ dropoff อยู่ก่อนวันสิ้นสุดหาก pickup อยู่ในช่วง และไม่มีการแปลง timestamp เป็น UTC โดยไม่รู้ timezone ต้นทาง การนับเวลาในข้อมูลเป็น source wall-clock; เฉพาะ timestamp ของ run logs ใช้ UTC

ระยะทางศูนย์ ค่าโดยสารติดลบ จำนวนผู้โดยสารหาย และ duplicate candidates เป็น diagnostic เท่านั้น ไม่ใช้ตัดข้อมูลออก FHV ไม่มี distance/fare/passenger ที่เทียบกันครบ จึงบันทึก diagnostic ที่ไม่มีข้อมูลเป็น NULL ไม่ใช่ศูนย์

## Audit และ lineage

`file_audit.csv/json` มีหนึ่งแถวต่อ source file: `raw_count`, `valid_count`, `invalid_count`, เหตุผลคัดออก 4 ข้อ, `reason_total`, `reconciled`, `input_sha256`, `schema_ok` และ diagnostics

- `source_month_mismatch`: valid records ที่เดือน pickup ต่างจากเดือนในชื่อไฟล์ แต่ยังอยู่ภายในช่วงวิเคราะห์ทั้งหมด
- `sample_rows` และ `duplicate_candidates`: ตรวจเพียง 10,000 แถวแรกของแต่ละไฟล์จาก pickup/dropoff/pickup-zone/dropoff-zone ไม่มี trip ID กลางจึงไม่ลบ record
- `missing_pickup_zone`: จำนวน valid records ที่ไม่มีรหัสพื้นที่ที่ใช้ได้
- `unavailable_diagnostics`: fields ที่ประเภทนั้นไม่มีให้ตรวจ

`provenance/manifest.json` ระบุ URL, bytes, SHA-256, retrieval time, ETag และ Last-Modified ของทั้ง 25 inputs (24 trip files + 1 lookup) ส่วน `file_manifest.json` เป็น checksum ของไฟล์หลักฐานใน GitHub ไม่ใช่ checksum ของข้อมูลต้นทางแทนกัน

## ผลลัพธ์อื่น

| File | ใช้ทำอะไร |
|---|---|
| `results/ranking.csv` | อันดับจาก valid counts พร้อม raw counts, rejected counts, shares และ raw rank |
| `results/monthly_counts.csv` | valid counts ตามเดือน pickup จริง |
| `results/source_month_counts.csv` | raw/valid/rejected ตามเดือนของ source file |
| `results/borough_counts.csv` | valid counts แยกประเภทและ borough รวมกลุ่ม Unknown |
| `results/baseline_comparison.csv` | เทียบจำนวนกับ outputs ที่บันทึกไว้ใน Submission 1 |
| `quality/quality.json` | quality gates ทั้งหมด, totals และ zone coverage |
| `runs/<run_id>/run.json` | สถานะ รุ่น dependencies/config/code hashes และผลของแต่ละรัน |
| `runs/<run_id>/events.jsonl` | เหตุการณ์ตามลำดับ ตั้งแต่ START จน SUCCESS หรือ FAILED |
