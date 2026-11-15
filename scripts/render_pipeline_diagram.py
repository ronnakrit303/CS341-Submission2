"""Regenerate the README's SVG and Mermaid data flow diagrams using Python only."""

from dataclasses import dataclass
from html import escape
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PALETTE = {
    "source": ("#EAF3FF", "#719DD5", "#194E87"),
    "process": ("#F2EEFC", "#A590CE", "#54378A"),
    "store": ("#EAF6F2", "#6FAE9D", "#205F51"),
    "quality": ("#FFF5DC", "#C69B42", "#725013"),
    "failed": ("#FFF0F0", "#D78D92", "#962E38"),
}


@dataclass(frozen=True)
class Node:
    kind: str
    x: int
    y: int
    width: int
    height: int
    tag: str
    title: str
    lines: tuple[str, ...]


NODES = {
    "zoneSource": Node("source", 64, 210, 360, 165, "ข้อมูลต้นทาง / CSV", "Taxi Zone Lookup", ("รหัสและชื่อพื้นที่", "NYC TLC / 1 ไฟล์")),
    "configSource": Node("source", 500, 210, 360, 165, "การตั้งค่า / JSON", "pipeline.json", ("ช่วงเดือน แหล่งข้อมูล", "และโฟลเดอร์ที่ใช้เก็บผล")),
    "tripSource": Node("source", 936, 210, 360, 165, "ข้อมูลต้นทาง / PARQUET", "Trip Records", ("Taxi 4 ประเภท × 6 เดือน", "NYC TLC / 24 ไฟล์")),
    "prepare": Node("process", 500, 425, 360, 165, "01 / 07 · PREPARE", "เตรียมรายการข้อมูล", ("อ่าน config และช่วงเดือน", "สร้างรายการไฟล์ที่จะใช้")),
    "lookup": Node("process", 64, 655, 560, 165, "02 / 07 · LOOKUP", "ตรวจตารางพื้นที่", ("รับ/ตรวจ CSV และรหัส LocationID", "ยืนยันว่ารหัสพื้นที่ไม่ซ้ำ")),
    "trips": Node("process", 736, 655, 560, 165, "03 / 07 · TRIPS", "ตรวจและสรุปข้อมูลเที่ยวรถ", ("ตรวจ SHA-256 คอลัมน์ และกฎเวลา", "คำนวณรายวันใหม่ หรือใช้ cache ที่ตรงกัน")),
    "zonesStore": Node("store", 64, 885, 560, 130, "D1", "ตารางพื้นที่พร้อมเชื่อม", ("ตารางในหน่วยความจำ / 265 พื้นที่", "LocationID → ชื่อ Zone และ Borough")),
    "aggregateStore": Node("store", 736, 885, 560, 130, "D2", "ผลสรุปและ audit รายไฟล์", ("data/cache/ — ยอดรายวันและผลตรวจ", "เก็บ raw / valid / rejected ไว้เทียบยอด")),
    "curate": Node("process", 390, 1085, 580, 165, "04 / 07 · CURATED", "เชื่อมข้อมูลพื้นที่", ("LEFT JOIN ด้วย pickup_location_id", "เก็บเที่ยวที่ไม่มีพื้นที่เป็น Unknown")),
    "curatedStore": Node("store", 64, 1315, 1232, 135, "D3", "Curated / ชุดข้อมูลสรุป", ("daily_zone_counts.parquet — วัน × ประเภท Taxi × พื้นที่ × ไฟล์ต้นทาง", "153,662 กลุ่ม / รวม trip_count ได้ 149,655,451 เที่ยว")),
    "quality": Node("quality", 64, 1530, 360, 165, "05 / 07 · QUALITY", "ตรวจคุณภาพ", ("เทียบ curated กับ audit", "ต้องผ่านครบ 10 เงื่อนไข")),
    "analysis": Node("process", 500, 1530, 360, 165, "06 / 07 · ANALYSIS", "วิเคราะห์ผล", ("รวมยอดจาก curated", "จัดอันดับและสร้างกราฟ")),
    "publish": Node("process", 936, 1530, 360, 165, "07 / 07 · PUBLISH", "บันทึกผลสำเร็จ", ("คำนวณ content hash", "อัปเดต latest.json")),
    "failed": Node("failed", 64, 1770, 360, 140, "FAIL / ข้อผิดพลาด", "FAILED — หยุดรอบนี้", ("เก็บ log และผลสำเร็จเดิม", "ไม่เปลี่ยน latest.json")),
    "resultStore": Node("store", 500, 1770, 360, 140, "D4", "ผลวิเคราะห์", ("อันดับ / รายเดือน / พื้นที่", "กราฟ และ CSV ตัวอย่าง")),
    "successStore": Node("store", 936, 1770, 360, 140, "D5", "ผลที่เผยแพร่ในเครื่อง", ("SUCCESS และ run.json", "latest.json ชี้ไปยังรอบนี้")),
}


@dataclass(frozen=True)
class Edge:
    source: str
    target: str
    path: str
    label: str = ""
    label_x: int = 0
    label_y: int = 0
    label_width: int = 0
    failed: bool = False


EDGES = [
    Edge("configSource", "prepare", "M680 375 V425"),
    Edge("zoneSource", "lookup", "M244 375 V655", "CSV พื้นที่", 244, 500, 170),
    Edge("tripSource", "trips", "M1116 375 V655", "ข้อมูลเที่ยวรถ", 1116, 500, 210),
    Edge("prepare", "lookup", "M590 590 V615 H544 V655", "URL พื้นที่", 450, 632, 160),
    Edge("prepare", "trips", "M770 590 V615 H816 V655", "รายการ 24 ไฟล์", 965, 632, 240),
    Edge("lookup", "zonesStore", "M344 820 V885", "lookup ผ่านตรวจ", 344, 853, 230),
    Edge("trips", "aggregateStore", "M960 820 V885", "บันทึกผลคำนวณ", 960, 853, 260),
    Edge("aggregateStore", "trips", "M1210 885 V820", "cache ตรงกัน", 1210, 853, 170),
    Edge("zonesStore", "curate", "M344 1015 V1045 H525 V1085", "ชื่อพื้นที่", 421, 1046, 160),
    Edge("aggregateStore", "curate", "M1016 1015 V1045 H835 V1085", "ยอดเที่ยวรายวัน", 939, 1046, 225),
    Edge("aggregateStore", "quality", "M1296 950 H1326 V1490 H388 V1530", "audit: raw / valid / rejected", 1032, 1490, 370),
    Edge("curate", "curatedStore", "M680 1250 V1315", "จำนวนเที่ยวหลัง join", 874, 1283, 280),
    Edge("curatedStore", "quality", "M244 1450 V1530", "curated", 244, 1490, 140),
    Edge("quality", "analysis", "M424 1612 H500", "PASS", 462, 1593, 78),
    Edge("quality", "failed", "M244 1695 V1770", "FAIL", 244, 1733, 90, True),
    Edge("analysis", "publish", "M860 1612 H936", "รายงาน", 898, 1593, 104),
    Edge("analysis", "resultStore", "M680 1695 V1770", "ตาราง / กราฟ", 680, 1733, 200),
    Edge("publish", "successStore", "M1116 1695 V1770", "SUCCESS", 1116, 1733, 150),
]


def svg_text(x, y, value, size=24, weight=400, fill="#26364B", anchor="start"):
    return (f'<text x="{x}" y="{y}" font-size="{size}" font-weight="{weight}" '
            f'fill="{fill}" text-anchor="{anchor}">{escape(value)}</text>')


def draw_node(node):
    fill, stroke, accent = PALETTE[node.kind]
    x, y, w, h = node.x, node.y, node.width, node.height
    parts = []
    if node.kind == "store":
        # A cylinder distinguishes stored data from processing, including in grayscale.
        parts.append(f'<path d="M{x} {y+14} A{w/2} 14 0 0 1 {x+w} {y+14} V{y+h-14} A{w/2} 14 0 0 1 {x} {y+h-14} Z" fill="{fill}" stroke="{stroke}" stroke-width="2"/>')
        parts.append(f'<path d="M{x} {y+14} A{w/2} 14 0 0 0 {x+w} {y+14}" fill="none" stroke="{stroke}" stroke-width="2"/>')
        parts.append(svg_text(x + 25, y + 49, node.tag + " | " + node.title, 26, 700, accent))
        for i, line in enumerate(node.lines):
            parts.append(svg_text(x + 25, y + 84 + i * 33, line))
    else:
        radius = 4 if node.kind == "source" else 18
        parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{radius}" fill="{fill}" stroke="{stroke}" stroke-width="2"/>')
        compact = node.kind == "failed"
        parts.append(svg_text(x + 24, y + 29, node.tag, 19, 700, accent))
        parts.append(svg_text(x + 24, y + (64 if compact else 70), node.title, 26 if compact else 29, 700, accent))
        for i, line in enumerate(node.lines):
            parts.append(svg_text(x + 24, y + (96 if compact else 109) + i * (32 if compact else 34), line, 23 if compact else 24))
    return "\n".join(parts)


def render_svg():
    parts = ['<svg xmlns="http://www.w3.org/2000/svg" width="1360" height="2010" viewBox="0 0 1360 2010" role="img" aria-labelledby="diagramTitle diagramDescription">',
             '<title id="diagramTitle">NYC Taxi — Data Flow Diagram</title>',
             '<desc id="diagramDescription">ข้อมูลเที่ยวรถ Parquet และตารางพื้นที่ CSV ผ่านการตรวจและสรุปก่อน LEFT JOIN โดยเก็บพื้นที่ Unknown ผล curated และ audit ใช้ตรวจคุณภาพ จากนั้นสร้างผลวิเคราะห์และบันทึก SUCCESS หากผิดพลาดจะบันทึก FAILED และรักษาผลสำเร็จเดิม หมายเลข 01 ถึง 07 ตรงกับขั้นตอนใน log</desc>',
             '<style>text { font-family: Tahoma, "Leelawadee UI", "Noto Sans Thai", sans-serif; }</style>',
             '<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse"><path d="M1 1 L9 5 L1 9 Z" fill="#52657D"/></marker><marker id="errorArrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto"><path d="M1 1 L9 5 L1 9 Z" fill="#AC4451"/></marker></defs>',
             '<rect width="1360" height="2010" fill="#FFFFFF"/>',
             svg_text(64, 48, "CS341 / SUBMISSION 2 / H1 2024", 20, 700, "#62738A"),
             svg_text(64, 101, "NYC Taxi — Data Flow Diagram", 43, 700, "#14243A"),
             svg_text(64, 142, "หมายเลข 01–07 ตรงกับ log · ลูกศรแสดงข้อมูลที่ส่งต่อระหว่างส่วน", 25, 400, "#526278")]
    for x, kind, label in [(64, "source", "ข้อมูลต้นทาง"), (319, "process", "ประมวลผล"), (565, "store", "ข้อมูลที่จัดเก็บ"), (855, "quality", "ตรวจคุณภาพ"), (1120, "failed", "ข้อผิดพลาด")]:
        fill, stroke, accent = PALETTE[kind]
        parts.append(f'<rect x="{x}" y="169" width="19" height="19" rx="3" fill="{fill}" stroke="{stroke}" stroke-width="2"/>')
        parts.append(svg_text(x + 29, 186, label, 22, 400, accent))
    # Edges are painted before nodes/labels so arrow routes cannot obscure text.
    for edge in EDGES:
        stroke, marker = ("#AC4451", "errorArrow") if edge.failed else ("#52657D", "arrow")
        dash = ' stroke-dasharray="8 6"' if edge.failed else ""
        parts.append(f'<path d="{edge.path}" fill="none" stroke="{stroke}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" marker-end="url(#{marker})"{dash}/>')
    for node_id, node in NODES.items():
        parts.append(f'<g id="{node_id}" data-bounds="{node.x},{node.y},{node.width},{node.height}">')
        parts.append(draw_node(node))
        parts.append('</g>')
    for edge in EDGES:
        if not edge.label:
            continue
        parts.append(f'<rect x="{edge.label_x-edge.label_width/2}" y="{edge.label_y-17}" width="{edge.label_width}" height="31" rx="7" fill="#FFFFFF"/>')
        parts.append(svg_text(edge.label_x, edge.label_y + 6, edge.label, 21, 700 if edge.label in ("PASS", "FAIL") else 400,
                              "#962E38" if edge.failed else "#34465E", "middle"))
    parts.extend([
        svg_text(64, 1952, "หากขั้นใดผิดพลาด: บันทึก FAILED และคงผลสำเร็จก่อนหน้าไว้", 23, 700, "#962E38"),
        svg_text(64, 1988, "ส่งหลักฐานขึ้น GitHub แยกภายหลัง: export_evidence.py → ตรวจ PASS → commit / push", 22, 400, "#526278"),
        "</svg>"])
    return "\n".join(parts) + "\n"


def render_mermaid():
    lines = ['flowchart TD',
             '    %% Generated by scripts/render_pipeline_diagram.py; edit that file to regenerate both formats.',
             '    %% Colors and labels match docs/images/pipeline-data-flow.svg.',
             '    %% Numbered processes refer to log stages; arrows carry data, not parallel execution.']
    for node_id, node in NODES.items():
        label = "\n".join((node.tag + " — " + node.title, *node.lines))
        shape = f'[("{label}")]' if node.kind == "store" else f'("{label}")' if node.kind in ("process", "quality") else f'["{label}"]'
        lines.append(f'    {node_id}{shape}:::{node.kind}')
    for edge in EDGES:
        arrow = "-.->" if edge.failed else "-->"
        label = f'|"{edge.label}"|' if edge.label else ""
        lines.append(f'    {edge.source} {arrow}{label} {edge.target}')
    for kind, (fill, stroke, accent) in PALETTE.items():
        lines.append(f'    classDef {kind} fill:{fill},stroke:{stroke},color:{accent},stroke-width:2px')
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    image_path = ROOT / "docs/images/pipeline-data-flow.svg"
    image_path.parent.mkdir(parents=True, exist_ok=True)
    image_path.write_text(render_svg(), encoding="utf-8", newline="\n")
    (ROOT / "docs/pipeline.mmd").write_text(render_mermaid(), encoding="utf-8", newline="\n")
    print("Generated docs/images/pipeline-data-flow.svg and docs/pipeline.mmd")
