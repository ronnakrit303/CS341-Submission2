# การออกแบบ pipeline และเหตุผล

## 1. ใช้ DuckDB อ่าน Parquet โดยตรง และเก็บ curated เป็น daily aggregate

baseline ใช้ DuckDB อยู่แล้ว จึงพัฒนาต่อโดยอ่านเฉพาะคอลัมน์ที่จำเป็นและ aggregate ภายในฐานข้อมูล ไม่มีการโหลดข้อมูลดิบประมาณ 149.7 ล้านแถวเข้า Pandas พร้อมกัน ผลลัพธ์พร้อมใช้คือจำนวนเที่ยวรายวันแยกประเภท Taxi และ pickup zone ซึ่งตอบโจทย์หลักและต่อยอดวิเคราะห์พื้นที่ได้ ใช้ทุก valid record มาสรุป ไม่ใช่ sample ของ raw data ข้อแลกเปลี่ยนคือ curated table ไม่มีรายละเอียดรายเที่ยวสำหรับวิเคราะห์การกระจายของค่าโดยสารหรือระยะเวลา ถ้าต้องการต้องกลับไปสร้างชุดข้อมูลใหม่จาก raw snapshot

## 2. คง metric และกฎเวลาเดิมเพื่อเทียบ baseline ได้

นิยาม most used เป็น valid trip-record count เพราะใช้ร่วมกันได้ทั้งสี่ประเภท และแยก unknown locations ออกจากกฎเวลา การเพิ่ม zone lookup มีไว้ enrich การวิเคราะห์ ไม่ควรเปลี่ยนจำนวนเที่ยวที่ใช้ตอบคำถามเดิม ระยะทางศูนย์/ค่าโดยสารติดลบและ duplicate candidates ยังเป็น diagnostic เหมือนเดิม ไม่มีหลักฐานเพียงพอที่จะถือว่า record เหล่านี้ไม่ใช่เที่ยวจริง

## 3. LEFT JOIN lookup ที่ผ่านการตรวจ unique key

เชื่อม Parquet trip data กับ CSV lookup ด้วย pickup location ID หลังสรุปข้อมูลแล้ว ตรวจว่า lookup มีคอลัมน์ครบ มีข้อมูล และ LocationID เป็นจำนวนเต็มไม่ซ้ำและไม่เป็น NULL ก่อน join ใช้ LEFT JOIN เพื่อเก็บ missing/unmapped zones ไว้ทั้งหมด และยืนยันว่าผลรวมก่อน/หลัง join เท่าเดิม ถ้าใช้ inner join จะทำให้ข้อมูลที่ไม่มี zone หายไป โดยเฉพาะ FHV จึงไม่เหมาะกับ metric นี้

สอง datasets นี้มีรูปแบบและ schema ต่างกัน แต่เผยแพร่โดย NYC TLC เหมือนกัน งานนี้ไม่ได้อ้างว่าใช้ผู้เผยแพร่ข้อมูลอิสระหลายหน่วยงาน ไม่เพิ่มข้อมูลที่ไม่เกี่ยวข้องเพียงเพื่อให้มีหลายแหล่ง

## 4. Cache ตาม content และกฎ พร้อมแยก refresh จาก rerun

raw snapshot มี SHA-256 และ metadata การดาวน์โหลด ทุกครั้งที่ reuse จะตรวจ bytes/hash ใหม่ ไม่ยอมรับเพียงว่าไฟล์มีอยู่ Cache ของ aggregate ผูกกับ raw hash, transform-code hash, rules version, ชื่อประเภท/ไฟล์ และช่วงเวลา ถ้า input หรือ logic เปลี่ยนจะประมวลผลใหม่ ส่วน CSV lookup ถูกตรวจและ join ใหม่ทุกรัน จึงใช้ lookup ที่เปลี่ยนได้โดยไม่ต้อง aggregate trip file ซ้ำ

การรันธรรมดาหรือ `--offline` ใช้ snapshot เดิม; `--refresh` ดาวน์โหลดใหม่เพื่อตรวจ upstream revisions; `--rebuild` ข้าม transform cache การเพิ่ม end month ทำให้ช่วง valid เปลี่ยน จึง revalidate/reaggregate ไฟล์เดิมด้วยเพื่อความถูกต้อง ไม่ได้อ้างว่ารองรับ append-only แบบประมวลผลเฉพาะเดือนใหม่ทุกกรณี

## 5. Run directory แยกกันและ publish ผ่าน pointer เดียว

แต่ละรันสร้าง curated/output ใน directory ของ run ID ที่ไม่ซ้ำ พร้อมสถานะ RUNNING/SUCCESS/FAILED และ JSONL event log จะเขียน `reports/latest.json` ด้วย atomic replace เฉพาะหลังผ่าน quality และสร้างผลวิเคราะห์ครบแล้ว ผู้ใช้ต้องอ่าน latest pointer เพื่อเลือกผลที่ใช้งานได้ ไม่ควรเลือก directory ใหม่ที่สุดเอง เมื่อ run ล้มเหลวจะเก็บ partial evidence ไว้ตรวจ แต่ไม่เปลี่ยน pointer ของผลสำเร็จก่อนหน้า

ใช้ lock file ป้องกันสอง process เขียน data directory พร้อมกัน การดาวน์โหลดใช้ `.part` ก่อน replace และ retry สูงสุดตาม config เพื่อไม่ให้ partial download กลายเป็น raw input ที่ยอมรับแล้ว ถ้า process ถูก kill อาจเหลือ lock; ต้องตรวจว่าไม่มี run ทำงานก่อนลบ lock ด้วยตนเอง

## ขอบเขตของ reproducibility

reproducibility ในงานนี้หมายถึง snapshot ของ inputs, config และ transform logic เดียวกันให้ valid counts และเนื้อหา curated เดิม พร้อมแสดงสองรันจริงที่ content hash เท่ากัน ไม่ได้หมายความว่า upstream จะไม่แก้ไขไฟล์ หรือเครื่อง/เวอร์ชันอื่นจะสร้างไบต์ Parquet เหมือนกันเสมอ จึงเก็บทั้ง checksum ของไฟล์และ canonical sorted-content checksum รวมถึง pinned dependencies และเวอร์ชันที่ใช้จริง

ระบบเป็น batch CLI เครื่องเดียว ไม่มี scheduler/service ถาวรหรือ distributed execution CI ใช้ข้อมูลทดสอบเล็กและไม่ดาวน์โหลดหลาย GB ทุก push ส่วน full-data execution มีหลักฐานแยกอยู่ใน `artifacts/runs/`
