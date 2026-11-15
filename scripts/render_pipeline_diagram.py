"""Regenerate the README's SVG and Mermaid data flow diagrams using Python only."""

from dataclasses import dataclass
from html import escape
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PALETTE = {
    "source": ("#FFFFFF", "#68737D", "#25313B"),
    "process": ("#FFFFFF", "#486781", "#294A65"),
    "store": ("#FFFFFF", "#68737D", "#25313B"),
    "quality": ("#FFFFFF", "#486781", "#294A65"),
    "failed": ("#FFFFFF", "#68737D", "#25313B"),
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
    "zoneSource": Node("source", 56, 110, 320, 108, "", "Taxi Zone Lookup", ("CSV จาก NYC TLC", "รหัสและชื่อพื้นที่")),
    "configSource": Node("source", 480, 110, 320, 108, "", "การตั้งค่า (JSON)", ("config/pipeline.json", "เดือน แหล่งข้อมูล และโฟลเดอร์")),
    "tripSource": Node("source", 904, 110, 320, 108, "", "Trip Records", ("Parquet จาก NYC TLC", "24 ไฟล์ จาก Taxi 4 ประเภท")),
    "prepare": Node("process", 480, 260, 320, 112, "1", "เตรียมรายการข้อมูล", ("อ่าน config และช่วงเดือน", "สร้างรายการไฟล์ที่จะใช้")),
    "lookup": Node("process", 56, 426, 520, 112, "2", "ตรวจตารางพื้นที่", ("รับ/ตรวจ CSV และรหัส LocationID", "ยืนยันว่ารหัสพื้นที่ไม่ซ้ำ")),
    "trips": Node("process", 704, 426, 520, 112, "3", "ตรวจและสรุปเที่ยวรถ", ("ตรวจ SHA-256 คอลัมน์ และกฎเวลา", "สรุปรายวันใหม่ หรือใช้ cache ที่ตรงกัน")),
    "zonesStore": Node("store", 56, 598, 520, 108, "D1", "ตารางพื้นที่ (265 รหัส)", ("ตารางชั่วคราวในหน่วยความจำ", "LocationID → Zone / Borough")),
    "aggregateStore": Node("store", 704, 598, 520, 108, "D2", "ผลสรุปและ audit", ("data/cache/", "ยอดรายวันพร้อม raw / valid / rejected")),
    "curate": Node("process", 360, 762, 560, 112, "4", "เชื่อมข้อมูลพื้นที่", ("LEFT JOIN ด้วย pickup_location_id", "เก็บเที่ยวที่ไม่มีพื้นที่เป็น Unknown")),
    "curatedStore": Node("store", 56, 928, 1168, 108, "D3", "ชุดข้อมูลสรุป (Curated)", ("daily_zone_counts.parquet", "วัน × ประเภท Taxi × พื้นที่รับผู้โดยสาร × ไฟล์ต้นทาง; จำนวนเที่ยวอยู่ใน trip_count")),
    "quality": Node("quality", 56, 1100, 320, 112, "5", "ตรวจคุณภาพ", ("เทียบ curated กับ audit", "ตรวจครบ 10 เงื่อนไข")),
    "analysis": Node("process", 480, 1100, 320, 112, "6", "วิเคราะห์ผล", ("รวมยอดจาก curated", "จัดอันดับและสร้างกราฟ")),
    "publish": Node("process", 904, 1100, 320, 112, "7", "บันทึกผลสำเร็จ", ("คำนวณ content hash", "อัปเดต latest.json")),
    "failed": Node("failed", 56, 1274, 320, 108, "", "FAILED", ("บันทึกข้อผิดพลาดใน log", "คง latest.json ของรอบก่อน")),
    "resultStore": Node("store", 480, 1274, 320, 108, "D4", "ผลวิเคราะห์", ("อันดับ / รายเดือน / พื้นที่", "กราฟ และ CSV ตัวอย่าง")),
    "successStore": Node("store", 904, 1274, 320, 108, "D5", "ผลรันล่าสุดในเครื่อง", ("สถานะใน run.json", "latest.json ชี้รอบสำเร็จ")),
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
    Edge("configSource", "prepare", "M640 218 V260"),
    Edge("zoneSource", "lookup", "M216 218 V426", "CSV พื้นที่", 216, 321, 126),
    Edge("tripSource", "trips", "M1064 218 V426", "ข้อมูลเที่ยวรถ", 1064, 321, 146),
    Edge("prepare", "lookup", "M555 372 V399 H500 V426", "URL พื้นที่", 425, 408, 128),
    Edge("prepare", "trips", "M725 372 V399 H780 V426", "รายการไฟล์", 860, 408, 138),
    Edge("lookup", "zonesStore", "M316 538 V598", "lookup ผ่านตรวจ", 316, 567, 170),
    Edge("trips", "aggregateStore", "M920 538 V598", "บันทึกผลคำนวณ", 920, 567, 178),
    Edge("aggregateStore", "trips", "M1148 598 V538", "cache ตรงกัน", 1148, 567, 148),
    Edge("zonesStore", "curate", "M316 706 V734 H490 V762", "ข้อมูลพื้นที่", 400, 743, 136),
    Edge("aggregateStore", "curate", "M964 706 V734 H790 V762", "ยอดรายวัน", 885, 743, 136),
    Edge("aggregateStore", "quality", "M1224 652 H1250 V1068 H344 V1100", "raw / valid / rejected", 1030, 1068, 254),
    Edge("curate", "curatedStore", "M640 874 V928", "ข้อมูลหลังเชื่อมพื้นที่", 820, 901, 232),
    Edge("curatedStore", "quality", "M216 1036 V1100", "curated", 216, 1068, 110),
    Edge("quality", "analysis", "M376 1156 H480", "ผ่าน", 428, 1141, 74),
    Edge("quality", "failed", "M216 1212 V1274", "ไม่ผ่าน", 216, 1243, 104, True),
    Edge("analysis", "publish", "M800 1156 H904", "รายงาน", 852, 1141, 84),
    Edge("analysis", "resultStore", "M640 1212 V1274", "ตาราง / กราฟ", 640, 1243, 150),
    Edge("publish", "successStore", "M1064 1212 V1274", "สถานะรัน", 1064, 1243, 124),
]


def svg_text(x, y, value, size=22, weight=400, fill="#25313B", anchor="start"):
    return (f'<text x="{x}" y="{y}" font-size="{size}" font-weight="{weight}" '
            f'fill="{fill}" text-anchor="{anchor}">{escape(value)}</text>')


def draw_node(node):
    fill, stroke, accent = PALETTE[node.kind]
    x, y, w, h = node.x, node.y, node.width, node.height
    parts = []
    if node.kind == "store":
        # Open-ended data store: identifier compartment and two horizontal rules.
        parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{fill}"/>')
        parts.append(f'<path d="M{x+w} {y} H{x} V{y+h} H{x+w} M{x+44} {y} V{y+h}" fill="none" stroke="{stroke}" stroke-width="1.5"/>')
        parts.append(svg_text(x + 22, y + 30, node.tag, 20, 600, accent, "middle"))
        parts.append(svg_text(x + 60, y + 32, node.title, 22, 600, accent))
        for i, line in enumerate(node.lines):
            parts.append(svg_text(x + 60, y + 65 + i * 29, line, 21))
    else:
        is_process = node.kind in ("process", "quality")
        radius = 3 if is_process else 0
        dash = ' stroke-dasharray="5 4"' if node.kind == "failed" else ""
        parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{radius}" fill="{fill}" stroke="{stroke}" stroke-width="1.5"{dash}/>')
        if is_process:
            parts.append(f'<rect x="{x+1}" y="{y+1}" width="{w-2}" height="39" fill="#EEF2F6"/>')
            parts.append(f'<path d="M{x} {y+41} H{x+w}" stroke="#BDC9D3" stroke-width="1"/>')
        heading = node.tag + ". " + node.title if node.tag else node.title
        parts.append(svg_text(x + 16, y + 32, heading, 23, 600, accent))
        for i, line in enumerate(node.lines):
            parts.append(svg_text(x + 16, y + (69 if is_process else 65) + i * 29, line))
    return "\n".join(parts)


def render_svg():
    parts = ['<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="1450" viewBox="0 0 1280 1450" role="img" aria-labelledby="diagramTitle diagramDescription">',
             '<title id="diagramTitle">NYC Taxi — Data Flow Diagram</title>',
             '<desc id="diagramDescription">ข้อมูลเที่ยวรถ Parquet และตารางพื้นที่ CSV ผ่านการตรวจและสรุปก่อน LEFT JOIN โดยเก็บพื้นที่ Unknown ผล curated และ audit ใช้ตรวจคุณภาพ จากนั้นสร้างผลวิเคราะห์และบันทึก SUCCESS หากผิดพลาดจะบันทึก FAILED และรักษาผลสำเร็จเดิม หมายเลข 1 ถึง 7 ตรงกับขั้นตอนใน log</desc>',
             '<style>text { font-family: "Leelawadee UI", Tahoma, "Noto Sans Thai", sans-serif; }</style>',
             '<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M1 1 L9 5 L1 9 Z" fill="#58636E"/></marker></defs>',
             '<rect width="1280" height="1450" fill="#FFFFFF"/>',
             svg_text(56, 41, "NYC Taxi: Data Flow Diagram", 29, 600),
             svg_text(56, 75, "มกราคม–มิถุนายน 2024  กระบวนการ 1–7 ตรงกับลำดับใน log", 20, 400, "#56616B")]
    # Edges are painted before nodes/labels so arrow routes cannot obscure text.
    for edge in EDGES:
        dash = ' stroke-dasharray="5 4"' if edge.failed else ""
        parts.append(f'<path d="{edge.path}" fill="none" stroke="#58636E" stroke-width="1.8" stroke-linejoin="miter" marker-end="url(#arrow)"{dash}/>')
    for node_id, node in NODES.items():
        parts.append(f'<g id="{node_id}" data-bounds="{node.x},{node.y},{node.width},{node.height}">')
        parts.append(draw_node(node))
        parts.append('</g>')
    for edge in EDGES:
        if not edge.label:
            continue
        parts.append(f'<rect x="{edge.label_x-edge.label_width/2}" y="{edge.label_y-13}" width="{edge.label_width}" height="26" fill="#FFFFFF"/>')
        parts.append(svg_text(edge.label_x, edge.label_y + 6, edge.label, 19, 400, "#3E4B57", "middle"))
    parts.extend([
        svg_text(56, 1428, "หากขั้นอื่นเกิดข้อผิดพลาด ระบบจะบันทึก FAILED และคงผลสำเร็จรอบก่อนเช่นกัน", 20, 400, "#56616B"),
        "</svg>"])
    return "\n".join(parts) + "\n"


def render_mermaid():
    lines = ['flowchart TD',
             '    %% Generated by scripts/render_pipeline_diagram.py; edit that file to regenerate both formats.',
             '    %% Colors and labels match docs/images/pipeline-data-flow.svg.',
             '    %% Numbered processes refer to log stages; arrows carry data, not parallel execution.']
    for node_id, node in NODES.items():
        heading = node.tag + (". " if node.kind in ("process", "quality") else " ") + node.title if node.tag else node.title
        label = "\n".join((heading, *node.lines))
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
