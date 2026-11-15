"""Readable terminal flow and matching text/structured evidence for each run."""

from copy import deepcopy
import json
from pathlib import Path
import sys
import time

from .download import utc_now


STEPS = (
    ("PREPARE", "เตรียมระบบและรายการข้อมูล"),
    ("LOOKUP", "รับและตรวจสอบตารางพื้นที่ Taxi Zone"),
    ("TRIPS", "รับ ตรวจสอบ และสรุปข้อมูล Trip Records"),
    ("CURATED", "เชื่อมข้อมูลพื้นที่และสร้าง Curated Output"),
    ("QUALITY", "ตรวจคุณภาพและความสอดคล้องของข้อมูล"),
    ("ANALYSIS", "วิเคราะห์ จัดอันดับ และสร้างรายงาน"),
    ("PUBLISH", "บันทึกผลสำเร็จและตำแหน่ง Output"),
)

QUALITY_CHECKS = {
    "complete_unique_input_coverage": "ข้อมูลครบทุกประเภท/เดือน และไม่มีรายการไฟล์ซ้ำ",
    "required_schemas_and_nonempty_inputs": "คอลัมน์ที่จำเป็นครบ และทุกไฟล์มีข้อมูล",
    "per_file_rejection_accounting": "แต่ละไฟล์แจกแจงเหตุผลคัดออกได้ครบโดยไม่นับซ้ำ",
    "raw_equals_valid_plus_rejected": "จำนวนข้อมูลทั้งหมด = ผ่านกฎ + คัดออก",
    "positive_valid_total": "มีข้อมูลที่ผ่านกฎสำหรับนำไปวิเคราะห์",
    "curated_equals_valid_total": "จำนวนเที่ยวใน curated ตรงกับยอดที่ผ่านกฎ",
    "zone_join_preserves_trip_count": "การเชื่อมพื้นที่ไม่ทำให้จำนวนเที่ยวเพิ่มหรือลด",
    "unique_curated_keys": "กลุ่มสรุปใน curated ไม่มี key ซ้ำ",
    "positive_curated_group_counts": "ทุกกลุ่มสรุปมีจำนวนเที่ยวมากกว่าศูนย์",
    "curated_dates_within_requested_period": "วันที่ใน curated อยู่ภายในช่วงที่กำหนด",
}


def configure_terminal():
    """Keep Thai logs readable on Windows consoles and when stdout is redirected."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            reconfigure(encoding="utf-8")


class PipelineProgress:
    def __init__(self, run_dir: Path):
        configure_terminal()
        self.run_dir = run_dir
        self.total = len(STEPS)
        self.current = None
        self.started = time.monotonic()
        self.step_started = None
        self.steps = [{"number": i, "name": name, "description": title, "status": "PENDING"}
                      for i, (name, title) in enumerate(STEPS, 1)]

    def write(self, text=""):
        print(text, flush=True)
        with (self.run_dir / "pipeline.log").open("a", encoding="utf-8", newline="\n") as target:
            target.write(text + "\n")

    def record(self, event, status, message, **details):
        step = self.steps[self.current - 1] if self.current else None
        record = {"at_utc": utc_now(), "stage": step["name"] if step else "PIPELINE",
                  "step": self.current, "step_total": self.total,
                  "step_name": step["description"] if step else None,
                  "event": event, "status": status, "message": message, **details}
        with (self.run_dir / "events.jsonl").open("a", encoding="utf-8", newline="\n") as target:
            target.write(json.dumps(record, ensure_ascii=False) + "\n")

    def header(self, run_id, config, *, offline, refresh, rebuild):
        mode = "OFFLINE: ใช้ snapshot ในเครื่อง ไม่ดาวน์โหลดข้อมูล"
        if not offline:
            mode = "REFRESH: ดาวน์โหลด inputs ใหม่" if refresh else "AUTO: ใช้ snapshot ที่ตรวจ hash ผ่าน หรือดาวน์โหลดเมื่อจำเป็น"
        transform = "REBUILD: คำนวณ audit/aggregate ใหม่ทุกไฟล์" if rebuild else "CACHE: ใช้ audit/aggregate เดิมเมื่อ input และกฎตรงกัน"
        self.write("=" * 76)
        self.write("NYC TAXI DATA PIPELINE")
        self.write(f"Run ID : {run_id}")
        self.write(f"Period : {config.settings['start_month']} to {config.settings['end_month']}")
        self.write(f"Mode   : {mode}")
        self.write(f"Work   : {transform}")
        self.write(f"Inputs : {len(config.manifest())} trip files (Parquet) + 1 zone lookup (CSV)")
        self.write(f"Flow   : {self.total} steps")
        for step in self.steps:
            if step["number"] > 1:
                self.write("     ↓")
            self.write(f"  {step['number']}. {step['name']} - {step['description']}")
        self.write("Status : RUNNING=กำลังทำ | OK=สำเร็จ | WARN=ข้อควรทราบ | FAILED=ล้มเหลว | SKIPPED=ไม่ได้ทำ")
        self.write("=" * 76)
        self.record("RUN_START", "RUNNING", "Pipeline started", run_id=run_id)

    def begin(self, number):
        if self.current is not None or number != sum(s["status"] == "OK" for s in self.steps) + 1:
            raise RuntimeError("Pipeline steps must begin in order")
        self.current = number
        self.step_started = time.monotonic()
        step = self.steps[number - 1]
        step.update(status="RUNNING", started_at_utc=utc_now())
        self.write()
        if number > 1:
            self.write("        ↓")
            self.write()
        self.write(f"[STEP {number:02d}/{self.total:02d}] [RUNNING] {step['name']} - {step['description']}")
        self.record("STEP_START", "RUNNING", step["description"])

    def detail(self, message, status="INFO", **details):
        self.write(f"  [{status}] {message}")
        self.record("DETAIL", status, message, **details)

    def file(self, number, total, phase, status, message, **details):
        self.write(f"  [FILE {number:02d}/{total:02d}] [{phase}] [{status}] {message}")
        self.record("FILE_" + phase, status, message, file_number=number, file_total=total, **details)

    def quality_check(self, check):
        self.detail(QUALITY_CHECKS.get(check["check"], check["check"]),
                    status="PASS" if check["passed"] else "FAIL",
                    check=check["check"], passed=check["passed"])

    def snapshot(self, completing=False):
        result = deepcopy(self.steps)
        if completing and self.current:
            result[self.current - 1].update(status="OK", finished_at_utc=utc_now(),
                                           elapsed_seconds=round(time.monotonic() - self.step_started, 3))
        return result

    def complete(self, message):
        step = self.steps[self.current - 1]
        elapsed = time.monotonic() - self.step_started
        step.update(status="OK", finished_at_utc=utc_now(), elapsed_seconds=round(elapsed, 3))
        self.write(f"[STEP {self.current:02d}/{self.total:02d}] [OK] {message} ({elapsed:.2f}s)")
        self.record("STEP_END", "OK", message, elapsed_seconds=step["elapsed_seconds"])
        self.current = None

    def table(self):
        self.write("Step  Status    Seconds  Name")
        for step in self.steps:
            seconds = f"{step['elapsed_seconds']:.2f}" if "elapsed_seconds" in step else "-"
            self.write(f"{step['number']:02d}/{self.total:02d} {step['status']:<9} {seconds:>7}  {step['name']}")

    def success(self, metadata, outputs):
        if any(step["status"] != "OK" for step in self.steps):
            raise RuntimeError("Cannot report SUCCESS before every step completes")
        self.write()
        self.write("=" * 76)
        self.write(f"[PIPELINE] [SUCCESS] สำเร็จครบ {self.total}/{self.total} ขั้นตอน")
        self.table()
        self.write(f"Run ID       : {metadata['run_id']}")
        self.write(f"Elapsed      : {metadata['elapsed_seconds']:.2f}s")
        self.write(f"Raw records  : {metadata['raw_count']:,}")
        self.write(f"Valid records: {metadata['valid_count']:,}")
        self.write(f"Rejected     : {metadata['invalid_count']:,} (คัดออกตามกฎข้อมูล ไม่ใช่ pipeline error)")
        self.write(f"Curated rows : {metadata['curated_rows']:,}")
        self.write(f"Winner(s)    : {', '.join(metadata['answer']['winners'])}")
        actions = metadata["actions"]
        self.write(f"Trip inputs  : downloaded={actions.get('downloaded', 0)} | verified local={actions.get('cached_verified', 0)}")
        self.write(f"Transforms   : processed={actions.get('processed', 0)} | reused={actions.get('reused', 0)}")
        self.write("Outputs (paths relative to project root):")
        for label, path in outputs.items():
            self.write(f"  {label:<13}: {path}")
        self.write("=" * 76)
        self.record("RUN_END", "SUCCESS", "All pipeline steps completed", completed_steps=self.total)

    def failed(self, exc):
        if self.current:
            step = self.steps[self.current - 1]
            step.update(status="FAILED", finished_at_utc=utc_now(),
                        elapsed_seconds=round(time.monotonic() - self.step_started, 3))
            self.write(f"[STEP {self.current:02d}/{self.total:02d}] [FAILED] {step['name']} - {type(exc).__name__}: {exc}")
        for step in self.steps:
            if step["status"] == "PENDING":
                step["status"] = "SKIPPED"
        self.record("RUN_END", "FAILED", str(exc), error_type=type(exc).__name__)
        self.write()
        self.write("=" * 76)
        self.write("[PIPELINE] [FAILED] หยุดทำงานเนื่องจากเกิดข้อผิดพลาด")
        self.table()
        self.write(f"Completed : {sum(s['status'] == 'OK' for s in self.steps)}/{self.total} steps")
        self.write(f"Error     : {type(exc).__name__}: {exc}")
        self.write("ขั้นตอนที่เป็น SKIPPED ยังไม่ได้ทำ และผลของรอบนี้ยังไม่ได้เผยแพร่")
        self.write("ผลสำเร็จก่อนหน้ายังคงอยู่ ดูรายละเอียดใน run.json, events.jsonl และ pipeline.log ของรอบนี้")
        self.write("=" * 76)
