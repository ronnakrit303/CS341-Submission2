# Submission 2 พัฒนาจาก Submission 1 อย่างไร

| ส่วนงาน | Submission 1 | Submission 2 |
|---|---|---|
| รูปแบบ | Colab notebook รันตาม cell | Python modules และ CLI คำสั่งเดียว |
| พารามิเตอร์ | ช่วงเดือนและ path อยู่ใน cell; ผูก `/content` | JSON config, relative paths และ CLI overrides ใช้ Windows/Linux ได้ |
| ข้อมูล | Parquet 4 ประเภท รวม 24 ไฟล์ | ข้อมูลเดิม + Taxi Zone Lookup CSV ที่เชื่อมใช้งานจริง |
| สิ่งที่จัดเก็บ | raw ชั่วคราวและ outputs ภายใน notebook | raw snapshot local, metadata/hashes, cache, curated Parquet และตัวอย่าง CSV |
| Curated data | ตาราง audit/summary อยู่ในหน่วยความจำและ outputs | สร้าง dataset สรุปรายวันแยกพื้นที่ที่เปิดวิเคราะห์แยกจาก pipeline ได้ |
| การรันซ้ำ | มี cache การดาวน์โหลด แต่ audit คำนวณใหม่ใน notebook | ตรวจ SHA-256 ของ raw และ cache aggregate ตาม input/logic/config พร้อม run evidence ทุกครั้ง |
| ข้อมูลใหม่ | แก้ตัวแปรและตรวจ cell ที่เกี่ยวข้อง | เปลี่ยน end month/config แล้วสั่งรัน; ตรวจ requested coverage ใหม่ทุกครั้ง |
| Data quality | schema, counts และ reconciliation | คงกฎเดิม เพิ่ม unique lookup keys, join preservation, curated keys/date bounds และ persisted reports |
| เมื่อผิดพลาด | หยุด notebook ด้วย INCOMPLETE | exit code ไม่เป็นศูนย์, FAILED run log และไม่แทน latest success |
| อ่านสถานะการทำงาน | ผลแสดงตาม cell ของ notebook | แสดง flow 7 ขั้น, RUNNING/OK/FAILED/SKIPPED, ตัวนับไฟล์แยกจากขั้น, เวลา และ output paths พร้อมเก็บ pipeline.log |
| คำตอบ | กราฟและข้อความใน notebook | ranking/answer JSON/Markdown/PNG สร้างจาก curated table พร้อมเปรียบเทียบ baseline |
| การส่งงาน | notebook ไฟล์เดียว | GitHub repository: source/config/tests/docs/diagram/actual evidence |

ผลจริงจาก pipeline H1 2024 ตรงกับ saved outputs ของ Submission 1 ทุกประเภท:

| Taxi type | Baseline valid records | Pipeline valid records | ส่วนต่าง |
|---|---:|---:|---:|
| High Volume FHV | 120,864,668 | 120,864,668 | 0 |
| Yellow | 20,331,754 | 20,331,754 | 0 |
| FHV | 8,119,228 | 8,119,228 | 0 |
| Green | 339,801 | 339,801 | 0 |

รวม 149,655,451 valid records จาก 149,655,796 raw records คัดออก 345 records คำตอบยังเป็น High Volume FHV มีสัดส่วน 80.76% ของ valid records ตารางเปรียบเทียบนี้ตรวจได้จาก [`baseline_comparison.csv`](../artifacts/results/baseline_comparison.csv) และ [`file_audit.csv`](../artifacts/quality/file_audit.csv)

การเพิ่มมิติพื้นที่ไม่ทำให้ยอดรวมเปลี่ยน แต่ทำให้เห็นข้อจำกัดที่สำคัญ: FHV จำนวน 6,359,783 records ไม่มี pickup zone ที่ใช้ได้ จึงยังคงอยู่ในกลุ่ม Unknown และใน metric หลัก การวิเคราะห์ geographic distribution ของ FHV ควรอ่านร่วมกับ zone coverage ไม่ควรถือว่าเฉพาะแถวที่มีพื้นที่เป็นตัวแทนของ FHV ทั้งหมด

## ข้อจำกัดที่ยังมี

- trip-record count ไม่ใช่จำนวนผู้โดยสารไม่ซ้ำ รายได้ หรือระยะทาง และเปรียบเทียบบริการที่มีลักษณะต่างกัน
- ความถูกต้องและความครบถ้วนของข้อมูลยังขึ้นกับผู้ให้บริการที่ส่งให้ TLC; quality gates ตรวจได้เฉพาะเงื่อนไขที่กำหนด
- ไม่มี trip ID ร่วมที่เชื่อถือได้ จึงไม่ยืนยัน/ลบ duplicate candidates; ตรวจซ้ำเป็น diagnostic ของ 10,000 แถวแรกต่อไฟล์เท่านั้น
- curated table เป็น aggregate ไม่มีข้อมูลรายละเอียดรายเที่ยวสำหรับการวิเคราะห์ค่าโดยสารหรือระยะเวลา
- ข้อมูลพื้นที่หายจำนวนมากใน FHV; unknown/unmapped ยังถูกนับ และ lookup ไม่ได้ version แยกตามวันของ trip
- ขอบเขตคำตอบหลักคือ H1 2024; ผลของช่วงอื่นต้องระบุช่วงนั้นใหม่ ไม่มีการอนุมานสาเหตุหรือพฤติกรรมระยะยาว
- ต้องใช้เครือข่ายครั้งแรก พื้นที่ raw ประมาณ 3.12 GiB และพื้นที่เพิ่มสำหรับ outputs/cache; เป็น batch pipeline เครื่องเดียว ไม่มี automatic schedule
- rerun ทั่วไปใช้ local snapshot และไม่ตรวจ remote revisions จนสั่ง `--refresh`; การขยายช่วงเวลาอาจทำให้ประมวลผล cache เดิมใหม่เพื่อใช้กฎเวลาที่ถูกต้อง
- กรณีหยุด process กะทันหันอาจมี `.part` หรือ lock ค้าง; การรันถัดไปจะไม่ใช้ partial file แต่ต้องตรวจ process ก่อนปลด lock
