"""Render the README data flow views and the complete Mermaid graph.

Design review follows unslop by Damir Sokolovsky (@heydamir), CC BY 4.0:
https://github.com/heydamir/unslop. The diagram itself uses native SVG.
"""

from dataclasses import dataclass
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WIDTH = 880
INK = "#25313B"
SECONDARY = "#52616F"
RULE = "#7D8B99"
BLUE = "#294A65"
PALETTE = {
    "source": ("#FFFFFF", RULE, INK),
    "process": ("#FFFFFF", "#6E879B", BLUE),
    "store": ("#FFFFFF", RULE, INK),
    "quality": ("#FFFFFF", "#6E879B", BLUE),
    "failed": ("#FFFFFF", RULE, INK),
}


@dataclass(frozen=True)
class Node:
    kind: str
    tag: str
    title: str
    lines: tuple[str, ...]


# Each dataset/process is defined once. D2 and D3 recur as references in view 2.
NODES = {
    "configSource": Node("source", "", "การตั้งค่า pipeline (JSON)", ("config/pipeline.json: ช่วงเดือน แหล่งข้อมูล และโฟลเดอร์",)),
    "prepare": Node("process", "1", "เตรียมรายการข้อมูล", ("อ่าน config และช่วงเดือน", "ระบุไฟล์สำหรับขั้น 2 และ 3")),
    "zoneSource": Node("source", "", "Taxi Zone Lookup", ("CSV จาก NYC TLC", "รหัสและชื่อพื้นที่")),
    "tripSource": Node("source", "", "Trip Records", ("Parquet จาก NYC TLC", "24 ไฟล์ จาก Taxi 4 ประเภท")),
    "lookup": Node("process", "2", "ตรวจตารางพื้นที่", ("ตรวจคอลัมน์และรหัสพื้นที่", "LocationID ต้องไม่ซ้ำ")),
    "trips": Node("process", "3", "ตรวจและสรุปเที่ยวรถ", ("ตรวจ SHA-256 และกฎเวลา", "สรุปรายวัน หรือใช้ cache")),
    "zonesStore": Node("store", "D1", "พื้นที่ที่ผ่านตรวจ", ("265 รหัสในหน่วยความจำ", "Zone และ Borough")),
    "aggregateStore": Node("store", "D2", "ผลสรุปและ audit", ("data/cache/", "raw / valid / rejected")),
    "curate": Node("process", "4", "เชื่อมข้อมูลพื้นที่", ("LEFT JOIN ด้วย pickup_location_id", "เก็บพื้นที่ที่ไม่ทราบเป็น Unknown")),
    "curatedStore": Node("store", "D3", "ชุดข้อมูลพร้อมวิเคราะห์ (Curated)", ("daily_zone_counts.parquet", "วัน × ประเภท Taxi × พื้นที่รับผู้โดยสาร × ไฟล์ต้นทาง", "จำนวนเที่ยวของแต่ละกลุ่มอยู่ใน trip_count")),
    "quality": Node("quality", "5", "ตรวจคุณภาพข้อมูล", ("เทียบยอด curated กับ audit", "ต้องผ่านครบ 10 เงื่อนไข")),
    "analysis": Node("process", "6", "วิเคราะห์ผล", ("รวม trip_count เพื่อจัดอันดับ", "สร้างตารางรายเดือนและพื้นที่")),
    "publish": Node("process", "7", "บันทึกผลสำเร็จ", ("คำนวณ hash และบันทึก SUCCESS", "อัปเดต latest.json หลังสำเร็จ")),
    "failed": Node("failed", "", "FAILED", ("บันทึกข้อผิดพลาดใน log", "คงผลสำเร็จเดิม")),
    "resultStore": Node("store", "D4", "ผลวิเคราะห์", ("ตาราง CSV", "กราฟและตัวอย่าง")),
    "successStore": Node("store", "D5", "สถานะรัน", ("run.json", "latest.json")),
}


@dataclass(frozen=True)
class Box:
    x: int
    y: int
    width: int
    height: int
    title: str | None = None
    lines: tuple[str, ...] | None = None


@dataclass(frozen=True)
class Edge:
    source: str
    target: str
    path: str
    label: str = ""
    label_x: int = 0
    label_y: int = 0
    anchor: str = "start"
    failed: bool = False


@dataclass(frozen=True)
class View:
    slug: str
    title: str
    subtitle: str
    height: int
    boxes: dict[str, Box]
    edges: tuple[Edge, ...]
    notes: tuple[str, ...] = ()


PREPARATION = View(
    "prepare", "NYC Taxi: รับและเตรียมข้อมูล",
    "ขั้น 1–4 สำหรับข้อมูลมกราคม–มิถุนายน 2024", 1536,
    {
        "configSource": Box(32, 112, 816, 96),
        "prepare": Box(208, 256, 464, 112),
        "zoneSource": Box(32, 432, 384, 112),
        "tripSource": Box(464, 432, 384, 112),
        "lookup": Box(32, 608, 384, 144),
        "trips": Box(464, 608, 384, 144),
        "zonesStore": Box(32, 824, 384, 144),
        "aggregateStore": Box(464, 824, 384, 144),
        "curate": Box(208, 1056, 464, 144),
        "curatedStore": Box(32, 1272, 816, 160),
    },
    (
        Edge("configSource", "prepare", "M440 208 V256"),
        Edge("prepare", "lookup", "M256 368 V420 H432 V680 H416", "URL พื้นที่", 280, 408),
        Edge("prepare", "trips", "M624 368 V420 H448 V680 H464", "รายการไฟล์", 600, 408, "end"),
        Edge("zoneSource", "lookup", "M224 544 V608", "CSV", 240, 588),
        Edge("tripSource", "trips", "M656 544 V608", "Parquet", 672, 588),
        Edge("lookup", "zonesStore", "M224 752 V824", "ผ่านตรวจ", 240, 796),
        Edge("trips", "aggregateStore", "M560 752 V824", "บันทึก", 576, 796),
        Edge("aggregateStore", "trips", "M784 824 V752", "ใช้ซ้ำ", 768, 796, "end"),
        Edge("zonesStore", "curate", "M224 968 V1012 H304 V1056", "ข้อมูลพื้นที่", 80, 1000),
        Edge("aggregateStore", "curate", "M656 968 V1012 H576 V1056", "ยอดรายวัน", 680, 1000),
        Edge("curate", "curatedStore", "M440 1200 V1272", "สรุปหลังเชื่อมพื้นที่", 456, 1244),
    ),
    ("ใช้ cache เมื่อ hash ของข้อมูล การตั้งค่า และ logic ตรงกัน", "D3 ส่งต่อไปตรวจคุณภาพในภาพถัดไป ส่วน audit มาจาก D2"),
)

RESULTS = View(
    "results", "ตรวจคุณภาพและสร้างผลลัพธ์",
    "ขั้น 5–7 รับ curated และ audit จากภาพก่อนหน้า", 1080,
    {
        "curatedStore": Box(32, 112, 480, 136, "Curated จากขั้น 4", ("daily_zone_counts.parquet", "จำนวนเที่ยวอยู่ใน trip_count")),
        "aggregateStore": Box(592, 112, 256, 136, "Audit จากขั้น 3", ("raw / valid", "rejected")),
        "quality": Box(32, 336, 480, 144),
        "failed": Box(592, 336, 256, 144, lines=("บันทึก log", "คงผลสำเร็จเดิม")),
        "analysis": Box(32, 576, 480, 144),
        "resultStore": Box(592, 576, 256, 144),
        "publish": Box(32, 832, 480, 144),
        "successStore": Box(592, 832, 256, 144),
    },
    (
        Edge("curatedStore", "quality", "M272 248 V336", "curated", 288, 300),
        Edge("aggregateStore", "quality", "M720 248 V292 H448 V336", "raw / valid / rejected", 568, 280, "middle"),
        Edge("quality", "analysis", "M272 480 V576", "ผ่านตรวจ", 288, 536),
        Edge("quality", "failed", "M512 408 H592", "ไม่ผ่าน", 552, 392, "middle", True),
        Edge("analysis", "resultStore", "M512 648 H592"),
        Edge("analysis", "publish", "M272 720 V832", "ผลวิเคราะห์", 288, 784),
        Edge("publish", "successStore", "M512 904 H592"),
    ),
    ("หากขั้นใดผิดพลาด ระบบบันทึก FAILED และคง latest.json ของรอบก่อน",),
)
VIEWS = (PREPARATION, RESULTS)
EDGES = tuple(edge for view in VIEWS for edge in view.edges)


def svg_text(x, y, value, size=22, weight=400, fill=INK, anchor="start", **attributes):
    extra = " ".join(f'{key.replace("_", "-")}="{escape(str(value), quote=True)}"' for key, value in attributes.items())
    return (f'<text x="{x}" y="{y}" font-size="{size}" font-weight="{weight}" '
            f'fill="{fill}" text-anchor="{anchor}" {extra}>{escape(value)}</text>')


def draw_node(node_id, node, box):
    fill, stroke, accent = PALETTE[node.kind]
    x, y, w, h = box.x, box.y, box.width, box.height
    title = box.title if box.title is not None else node.title
    lines = box.lines if box.lines is not None else node.lines
    parts = []
    if node.kind == "store":
        if node_id == "curatedStore":
            fill = "#EEF3F8"
        parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{fill}"/>')
        parts.append(f'<path d="M{x+w} {y} H{x} V{y+h} H{x+w} M{x+44} {y} V{y+h}" fill="none" stroke="{stroke}" stroke-width="1.5"/>')
        parts.append(svg_text(x + 22, y + 36, node.tag, 22, 600, accent, "middle"))
        parts.append(svg_text(x + 64, y + 36, title, 24, 600, accent))
        for i, line in enumerate(lines):
            parts.append(svg_text(x + 64, y + 72 + i * 32, line))
    else:
        process = node.kind in ("process", "quality")
        radius = 4 if process else 0
        dash = ' stroke-dasharray="6 4"' if node.kind == "failed" else ""
        parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{radius}" fill="{fill}" stroke="{stroke}" stroke-width="1.5"{dash}/>')
        if process:
            parts.append(f'<path d="M{x+1} {y+48} H{x+w-1}" stroke="#D7DEE5" stroke-width="1"/>')
        heading = f"{node.tag}. {title}" if node.tag else title
        parts.append(svg_text(x + 20, y + 36, heading, 24, 600, accent))
        # The compact PREPARE box has a slightly tighter baseline rhythm.
        base, leading = (72, 28) if h == 112 else (80, 32)
        if not process:
            base, leading = 68, 28
        for i, line in enumerate(lines):
            parts.append(svg_text(x + 20, y + base + i * leading, line))
    return "\n".join(parts)


def render_view(view):
    parts = [svg_text(32, 44, view.title, 32, 600), svg_text(32, 80, view.subtitle, 22, fill=SECONDARY)]
    for edge in view.edges:
        dash = ' stroke-dasharray="6 4"' if edge.failed else ""
        parts.append(f'<path data-edge="{edge.source}:{edge.target}" d="{edge.path}" fill="none" stroke="#657787" stroke-width="1.8" stroke-linejoin="round" marker-end="url(#arrow)"{dash}/>')
    for node_id, box in view.boxes.items():
        parts.append(f'<g id="{view.slug}-{node_id}" data-bounds="{box.x},{box.y},{box.width},{box.height}">')
        parts.append(draw_node(node_id, NODES[node_id], box))
        parts.append('</g>')
    for edge in view.edges:
        if edge.label:
            parts.append(svg_text(edge.label_x, edge.label_y, edge.label, 20, fill=SECONDARY, anchor=edge.anchor, data_edge_label=f"{edge.source}:{edge.target}"))
    for i, note in enumerate(view.notes):
        y = view.height - 24 - (len(view.notes) - 1 - i) * 32
        parts.append(svg_text(32, y, note, 21, fill=SECONDARY, data_note="true"))
    return "\n".join(parts)


def render_svg(views=VIEWS):
    height = sum(view.height for view in views)
    descriptions = {
        "prepare": "ขั้น 1–4 รับการตั้งค่า JSON ข้อมูลเที่ยวรถ Parquet และตารางพื้นที่ CSV ตรวจและสรุปก่อน LEFT JOIN โดยเก็บพื้นที่ Unknown ได้ D3 curated และ D2 audit เพื่อส่งต่อไปตรวจคุณภาพ",
        "results": "ขั้น 5–7 รับ D3 curated และ D2 audit จากช่วงเตรียมข้อมูล ตรวจคุณภาพ 10 เงื่อนไข สร้างผลวิเคราะห์ และบันทึก SUCCESS หากขั้นใดผิดพลาดจะบันทึก FAILED และรักษาผลสำเร็จเดิม",
    }
    description = " ".join(descriptions[view.slug] for view in views)
    description += " หมายเลขตรงกับขั้นตอนใน log รหัส D2 และ D3 ที่อ้างถึงในสองภาพคือข้อมูลเดียวกัน"
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{height}" viewBox="0 0 {WIDTH} {height}" role="img" aria-labelledby="diagramTitle diagramDescription">',
             '<title id="diagramTitle">NYC Taxi: Data Flow Diagram</title>',
             f'<desc id="diagramDescription">{escape(description)}</desc>',
             '<style>text { font-family: "Leelawadee UI", Tahoma, "Noto Sans Thai", sans-serif; font-variant-numeric: tabular-nums; }</style>',
             '<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M1 1 L9 5 L1 9 Z" fill="#657787"/></marker></defs>',
             f'<rect width="{WIDTH}" height="{height}" fill="#FFFFFF"/>']
    offset = 0
    for view in views:
        parts.append(f'<g data-view="{view.slug}" transform="translate(0 {offset})">')
        parts.append(render_view(view))
        parts.append('</g>')
        offset += view.height
    parts.append('</svg>')
    return "\n".join(parts) + "\n"


def render_mermaid():
    lines = ['flowchart TD',
             '    %% Generated by scripts/render_pipeline_diagram.py.',
             '    %% Canonical graph for the two README views. D2 and D3 are shared data stores.',
             '    %% Numbers match log stages; arrows show data dependencies, not parallel execution.']
    for node_id, node in NODES.items():
        heading = f"{node.tag}{'.' if node.kind in ('process', 'quality') else ''} {node.title}".strip()
        label = '<br/>'.join((heading, *node.lines))
        shape = f'[("{label}")]' if node.kind == "store" else f'("{label}")' if node.kind in ("process", "quality") else f'["{label}"]'
        lines.append(f'    {node_id}{shape}:::{node.kind}')
    for edge in EDGES:
        arrow = "-.->" if edge.failed else "-->"
        label = f'|"{edge.label}"|' if edge.label else ""
        lines.append(f'    {edge.source} {arrow}{label} {edge.target}')
    for kind, (fill, stroke, accent) in PALETTE.items():
        lines.append(f'    classDef {kind} fill:{fill},stroke:{stroke},color:{accent},stroke-width:1.5px')
    lines.extend([f'    classDef curated fill:#EEF3F8,stroke:{RULE},color:#25313B,stroke-width:1.5px', '    class curatedStore curated'])
    return "\n".join(lines) + "\n"


def main():
    image_dir = ROOT / "docs/images"
    image_dir.mkdir(parents=True, exist_ok=True)
    (image_dir / "pipeline-data-flow.svg").write_text(render_svg(), encoding="utf-8", newline="\n")
    for view in VIEWS:
        (image_dir / f"pipeline-data-flow-{view.slug}.svg").write_text(render_svg((view,)), encoding="utf-8", newline="\n")
    (ROOT / "docs/pipeline.mmd").write_text(render_mermaid(), encoding="utf-8", newline="\n")
    print("Generated two README SVG views, the complete SVG and docs/pipeline.mmd")


if __name__ == "__main__":
    main()
