"""Generate a concise README data flow diagram and matching Mermaid source.

Design review follows unslop by Damir Sokolovsky (@heydamir), CC BY 4.0:
https://github.com/heydamir/unslop. No external renderer is required.
"""

from dataclasses import dataclass
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WIDTH, HEIGHT = 800, 1560
INK = "#253344"
MUTED = "#526170"
BLUE = "#315C7E"
RULE = "#7D8D9B"


@dataclass(frozen=True)
class Node:
    kind: str
    x: int
    y: int
    width: int
    height: int
    title: str
    lines: tuple[str, ...]


# This is an overview: steps 1–3 share one process, with all seven log stages
# explained individually in the README table. Cache and audit are not extra
# stages; they are explained below the figure instead of adding return routes.
NODES = {
    "trips": Node("source", 32, 128, 344, 128, "ข้อมูลเที่ยวรถ", ("Trip Records (Parquet)", "24 ไฟล์ จาก Taxi 4 ประเภท")),
    "zones": Node("source", 424, 128, 344, 128, "ข้อมูลพื้นที่", ("Taxi Zone Lookup (CSV)", "265 รหัสพื้นที่")),
    "prepare": Node("process", 96, 312, 608, 144, "1–3. รับและเตรียมข้อมูล", ("อ่าน config ตรวจไฟล์และคอลัมน์ที่ต้องใช้", "ตรวจพื้นที่และกฎเวลา แล้วสรุปเที่ยวรถรายวัน")),
    "join": Node("process", 96, 504, 608, 136, "4. เชื่อมข้อมูลพื้นที่", ("LEFT JOIN ด้วยรหัสพื้นที่รับผู้โดยสาร", "เที่ยวที่ไม่ทราบพื้นที่ยังนับรวมเป็น Unknown")),
    "curated": Node("data", 96, 688, 608, 160, "ชุดข้อมูลพร้อมวิเคราะห์ (Curated)", ("daily_zone_counts.parquet", "สรุปรายวัน × ประเภท Taxi × พื้นที่ × ไฟล์ต้นทาง", "จำนวนเที่ยวของแต่ละกลุ่มอยู่ใน trip_count")),
    "quality": Node("process", 96, 896, 608, 136, "5. ตรวจคุณภาพ 10 เงื่อนไข", ("เทียบยอด curated กับ audit", "ไม่ผ่าน: บันทึก FAILED และเก็บผลสำเร็จเดิม")),
    "analysis": Node("process", 96, 1080, 608, 112, "6. วิเคราะห์ผล", ("รวม trip_count เพื่อจัดอันดับและสร้างกราฟ",)),
    "publish": Node("process", 96, 1240, 608, 112, "7. บันทึกผลสำเร็จ", ("บันทึก SUCCESS และอัปเดต latest.json",)),
    "outputs": Node("output", 96, 1400, 608, 128, "ผลลัพธ์ที่ตรวจสอบได้", ("อันดับ / รายเดือน / พื้นที่ / กราฟ", "run.json / pipeline.log / content hash")),
}


@dataclass(frozen=True)
class Edge:
    source: str
    target: str
    path: str


EDGES = (
    Edge("trips", "prepare", "M204 256 V280 H400 V312"),
    Edge("zones", "prepare", "M596 256 V280 H400 V312"),
    Edge("prepare", "join", "M400 456 V504"),
    Edge("join", "curated", "M400 640 V688"),
    Edge("curated", "quality", "M400 848 V896"),
    Edge("quality", "analysis", "M400 1032 V1080"),
    Edge("analysis", "publish", "M400 1192 V1240"),
    Edge("publish", "outputs", "M400 1352 V1400"),
)


def text(x, y, value, size=22, weight=400, color=INK, **attributes):
    extra = " ".join(f'{key.replace("_", "-")}="{escape(str(value), quote=True)}"' for key, value in attributes.items())
    return (f'<text x="{x}" y="{y}" font-size="{size}" font-weight="{weight}" '
            f'fill="{color}" {extra}>{escape(value)}</text>')


def draw_node(node_id, node):
    x, y, w, h = node.x, node.y, node.width, node.height
    process = node.kind == "process"
    fill = "#EAF1F7" if node.kind == "data" else "#F5F7F9" if node.kind in ("source", "output") else "#FFFFFF"
    stroke = BLUE if node.kind == "data" else RULE
    radius = 10 if process else 0
    parts = [f'<g id="{node_id}" data-bounds="{x},{y},{w},{h}">',
             f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{radius}" fill="{fill}" stroke="{stroke}" stroke-width="1.5"/>']
    heading_size = 24 if node.kind == "source" else 26
    heading_color = BLUE if process or node.kind == "data" else INK
    parts.append(text(x + 24, y + 40, node.title, heading_size, 600, heading_color))
    for i, line in enumerate(node.lines):
        size = 20 if node.kind in ("source", "output") or (node.kind == "data" and i > 0) else 22
        # The failed outcome is part of the quality gate, not another stage.
        color = MUTED if node_id == "quality" and i == 1 else INK
        parts.append(text(x + 24, y + 80 + i * 28, line, size, color=color))
    parts.append('</g>')
    return "\n".join(parts)


def render_svg():
    description = "ภาพรวมข้อมูล NYC TLC: เที่ยวรถ Parquet และตารางพื้นที่ CSV เข้าสู่ขั้น 1–3 รับและตรวจข้อมูล ขั้น 4 เชื่อมพื้นที่เป็น curated Parquet ขั้น 5 ตรวจคุณภาพ 10 เงื่อนไข หากผ่านจึงไปขั้น 6 วิเคราะห์และขั้น 7 บันทึกผลสำเร็จ หากผิดพลาดจะบันทึก FAILED และเก็บผลสำเร็จเดิม จำนวนเที่ยวรวมจาก trip_count"
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}" role="img" aria-labelledby="diagramTitle diagramDescription">',
             '<title id="diagramTitle">NYC Taxi: Data Flow Diagram</title>',
             f'<desc id="diagramDescription">{escape(description)}</desc>',
             '<style>text { font-family: "Leelawadee UI", Tahoma, "Noto Sans Thai", sans-serif; font-variant-numeric: tabular-nums; }</style>',
             '<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto"><path d="M1 1 L9 5 L1 9 Z" fill="#526D84"/></marker></defs>',
             f'<rect width="{WIDTH}" height="{HEIGHT}" fill="#FFFFFF"/>',
             text(32, 48, "NYC Taxi: Data Flow Diagram", 32, 600),
             text(32, 84, "ข้อมูล NYC TLC มกราคม–มิถุนายน 2024", 22, color=MUTED)]
    for edge in EDGES:
        parts.append(f'<path data-edge="{edge.source}:{edge.target}" d="{edge.path}" fill="none" stroke="#526D84" stroke-width="2" stroke-linejoin="round" marker-end="url(#arrow)"/>')
    for node_id, node in NODES.items():
        parts.append(draw_node(node_id, node))
    parts.append(text(416, 1064, "ผ่านตรวจ", 18, color=MUTED, data_edge_label="quality:analysis"))
    parts.append('</svg>')
    return "\n".join(parts) + "\n"


def render_mermaid():
    lines = ['flowchart TD',
             '    %% Generated by scripts/render_pipeline_diagram.py.',
             '    %% Overview: steps 1–3 share one process; see the README for all seven log stages.',
             '    %% A failed quality gate stops the main flow; other errors also retain the prior success.']
    for node_id, node in NODES.items():
        label = '<br/>'.join((node.title, *node.lines))
        shape = f'("{label}")' if node.kind == "process" else f'["{label}"]'
        lines.append(f'    {node_id}{shape}:::{node.kind}')
    for edge in EDGES:
        label = '|"ผ่านตรวจ"|' if edge.source == "quality" else ''
        lines.append(f'    {edge.source} -->{label} {edge.target}')
    lines.extend([
        f'    classDef source fill:#F5F7F9,stroke:{RULE},color:{INK},stroke-width:1.5px',
        f'    classDef process fill:#FFFFFF,stroke:{RULE},color:{INK},stroke-width:1.5px',
        f'    classDef data fill:#EAF1F7,stroke:{BLUE},color:{INK},stroke-width:1.5px',
        f'    classDef output fill:#F5F7F9,stroke:{RULE},color:{INK},stroke-width:1.5px',
    ])
    return "\n".join(lines) + "\n"


def main():
    image_path = ROOT / 'docs/images/pipeline-data-flow.svg'
    image_path.parent.mkdir(parents=True, exist_ok=True)
    image_path.write_text(render_svg(), encoding='utf-8', newline='\n')
    (ROOT / 'docs/pipeline.mmd').write_text(render_mermaid(), encoding='utf-8', newline='\n')
    print('Generated docs/images/pipeline-data-flow.svg and docs/pipeline.mmd')


if __name__ == '__main__':
    main()
