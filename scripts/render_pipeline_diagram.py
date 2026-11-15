"""Regenerate the approved SVG and equivalent Mermaid data flow diagram.

The README embeds the approved PNG to preserve the chosen fonts on GitHub.
This script uses only the Python standard library and regenerates SVG/Mermaid;
after a visual edit, export the SVG to PNG separately to refresh the README.
Design workflow: unslop by Damir Sokolovsky (@heydamir), CC BY 4.0.
https://github.com/heydamir/unslop
"""

from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
W, H = 1280, 1544
BG = "#111417"
SURFACE = "#191F24"
TEXT = "#E5EBF0"
SECONDARY = "#C1CBD4"
MUTED = "#A4B0BB"
BLUE = "#489EC0"
GREEN = "#69A992"
AMBER = "#D4AB67"
RED = "#D27B80"
EDGE = "#8A98A4"
parts = []
nodes = []
edges = []


def text(x, y, value, size=19, fill=SECONDARY, weight=400, anchor="start"):
    return (f'<text x="{x}" y="{y}" font-size="{size}" fill="{fill}" '
            f'font-weight="{weight}" text-anchor="{anchor}">{escape(value)}</text>')


def box(key, x, y, w, h, title, lines, kind="process"):
    color = {"process": BLUE, "source": "#667481", "quality": AMBER, "failed": RED, "evidence": GREEN}[kind]
    dash = ' stroke-dasharray="5 5"' if kind == "quality" else ""
    radius = 12 if kind in ("process", "quality", "failed") else 4
    nodes.append({"id": key, "bounds": [x, y, w, h], "kind": kind, "title": title, "lines": lines})
    parts.append(f'<g id="{key}" data-node="true" data-bounds="{x},{y},{w},{h}">')
    parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{radius}" fill="{SURFACE}" stroke="{color}" stroke-width="1.5"{dash}/>')
    parts.append(text(x+20, y+33, title, 21, TEXT, 600))
    for i, line in enumerate(lines):
        parts.append(text(x+20, y+65+i*27, line))
    parts.append('</g>')


def cylinder(key, x, y, w, h, title, lines):
    ry = 15
    nodes.append({"id": key, "bounds": [x, y, w, h], "kind": "data", "title": title, "lines": lines})
    parts.append(f'<g id="{key}" data-node="true" data-bounds="{x},{y},{w},{h}">')
    parts.append(f'<path d="M{x} {y+ry} A{w/2} {ry} 0 0 1 {x+w} {y+ry} V{y+h-ry} A{w/2} {ry} 0 0 1 {x} {y+h-ry} Z" fill="{SURFACE}" stroke="{GREEN}" stroke-width="1.5"/>')
    parts.append(f'<ellipse cx="{x+w/2}" cy="{y+ry}" rx="{w/2}" ry="{ry}" fill="{SURFACE}" stroke="{GREEN}" stroke-width="1.5"/>')
    parts.append(text(x+w/2, y+49, title, 21, TEXT, 600, "middle"))
    for i, line in enumerate(lines):
        parts.append(text(x+w/2, y+78+i*27, line, 19, SECONDARY, 400, "middle"))
    parts.append('</g>')


def edge(source, target, path, caption="", color=EDGE, failed=False):
    edges.append((source, target, caption, failed))
    dash = ' stroke-dasharray="5 5"' if failed else ""
    marker = "redArrow" if failed else "arrow"
    parts.append(f'<path class="edge" d="{path}" fill="none" stroke="{color}" stroke-width="1.6" stroke-linejoin="round" marker-end="url(#{marker})"{dash}/>')


def label(x, y, value, width, color=MUTED, size=17):
    parts.append(f'<g class="edge-label"><rect x="{x-width/2}" y="{y-16}" width="{width}" height="29" rx="3" fill="{BG}"/>')
    parts.append(text(x, y+5, value, size, color, 400, "middle"))
    parts.append('</g>')


def render_svg():
    parts.clear()
    nodes.clear()
    edges.clear()
    parts.extend([
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-labelledby="title description">',
        '<title id="title">NYC Taxi — Data Flow Diagram</title>',
        '<desc id="description">NYC TLC Parquet trip records and CSV taxi zones are validated, aggregated and joined. Ten quality gates reconcile curated counts with source audits. Passed data produces analysis and a locally published successful run; failed runs preserve the previous success.</desc>',
        '<style>text{font-family:"Leelawadee UI","Segoe UI",Tahoma,sans-serif;font-variant-numeric:tabular-nums} .edge{vector-effect:non-scaling-stroke}</style>',
        '<defs>',
        f'<marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M1 1 L9 5 L1 9 Z" fill="{EDGE}"/></marker>',
        f'<marker id="redArrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M1 1 L9 5 L1 9 Z" fill="{RED}"/></marker>',
        '</defs>',
        f'<rect width="{W}" height="{H}" fill="{BG}"/>',
        text(56, 56, 'NYC Taxi: Data Flow Diagram', 29, TEXT, 600),
        text(56, 90, 'มกราคม–มิถุนายน 2024  •  4 ประเภทรถ × 6 เดือน  •  หมายเลข 01–07 ตรงกับขั้นตอนใน log', 18, MUTED),
    ])

    # Routes are deliberately orthogonal. Data arrows do not imply parallel execution.
    edge('configSource', 'prepare', 'M640 240 V296', '')
    edge('zoneSource', 'lookup', 'M216 240 V472', 'ตารางพื้นที่')
    edge('tripSource', 'trips', 'M1064 240 V472', 'ข้อมูลเที่ยวรถ')
    edge('prepare', 'lookup', 'M528 408 V440 H440 V472', 'URL พื้นที่')
    edge('prepare', 'trips', 'M752 408 V440 H840 V472', 'รายการไฟล์')
    edge('lookup', 'curate', 'M296 600 V652 H480 V704', 'lookup ผ่านตรวจ')
    edge('trips', 'curate', 'M984 600 V652 H800 V704', 'ยอดรายวัน')
    edge('curate', 'curatedStore', 'M640 824 V872', 'ข้อมูลหลังเชื่อมพื้นที่')
    edge('curatedStore', 'quality', 'M640 1004 V1048 H216 V1104', 'curated')
    edge('trips', 'quality', 'M1224 552 H1252 V1072 H312 V1104', 'audit: raw / valid / rejected')
    edge('quality', 'analysis', 'M376 1164 H480', 'PASS')
    edge('analysis', 'publish', 'M800 1164 H904', 'รายงาน')
    edge('quality', 'failed', 'M216 1224 V1304', 'FAIL', color=RED, failed=True)
    edge('analysis', 'analysisStore', 'M640 1224 V1284', 'ตาราง / กราฟ')
    edge('publish', 'runEvidence', 'M1064 1224 V1304', 'สถานะรัน')

    box('zoneSource', 56, 136, 320, 104, 'Taxi Zone Lookup', ('CSV จาก NYC TLC', 'รหัสพื้นที่ ชื่อพื้นที่ และ Borough'), 'source')
    box('configSource', 480, 136, 320, 104, 'Pipeline config (JSON)', ('config/pipeline.json', 'ช่วงเดือน แหล่งข้อมูล และโฟลเดอร์'), 'source')
    box('tripSource', 904, 136, 320, 104, 'Trip Records', ('Parquet จาก NYC TLC', '24 ไฟล์ จาก Taxi 4 ประเภท'), 'source')

    box('prepare', 480, 296, 320, 112, '01 · PREPARE', ('อ่าน config และช่วงเดือน', 'เตรียมรายการไฟล์ของรอบรัน'))
    box('lookup', 56, 472, 480, 128, '02 · LOOKUP', ('รับและตรวจตารางพื้นที่ CSV', 'ยืนยัน 265 รหัสไม่ซ้ำ เก็บ lookup ในหน่วยความจำ'))
    box('trips', 744, 472, 480, 128, '03 · TRIPS', ('ตรวจ SHA-256, schema และกฎเวลา', 'สรุปรายวัน หรือใช้ cache ที่ตรงกัน'))
    box('curate', 400, 704, 480, 120, '04 · CURATED', ('LEFT JOIN ยอดรายวันกับพื้นที่รับผู้โดยสาร', 'คงเที่ยวที่ไม่ทราบพื้นที่เป็น Unknown'))

    cylinder('curatedStore', 400, 872, 480, 132, 'Curated Parquet', ('daily_zone_counts.parquet  •  trip_count', 'วัน × ประเภทรถ × พื้นที่ × ไฟล์ต้นทาง'))

    box('quality', 56, 1104, 320, 120, '05 · QUALITY', ('ตรวจคุณภาพ 10 เงื่อนไข', 'เทียบยอด curated กับ audit'), 'quality')
    box('analysis', 480, 1104, 320, 120, '06 · ANALYSIS', ('รวมยอดและจัดอันดับ Taxi', 'สร้างตารางและกราฟ'))
    box('publish', 904, 1104, 320, 120, '07 · PUBLISH', ('บันทึก SUCCESS และ content hash', 'อัปเดต latest.json ในเครื่อง'))

    box('failed', 56, 1304, 320, 104, 'FAILED', ('บันทึกข้อผิดพลาดใน log', 'คงผลสำเร็จของรอบก่อน'), 'failed')
    cylinder('analysisStore', 480, 1284, 320, 124, 'Analysis results', ('อันดับ / รายเดือน / พื้นที่', 'CSV และกราฟ'))
    box('runEvidence', 904, 1304, 320, 104, 'Run logs & evidence', ('run.json / pipeline.log', 'latest.json ชี้รอบสำเร็จ'), 'evidence')

    label(216, 356, 'ตารางพื้นที่', 112)
    label(1064, 356, 'ข้อมูลเที่ยวรถ', 134)
    label(416, 420, 'URL พื้นที่', 118)
    label(884, 420, 'รายการไฟล์', 120)
    label(398, 630, 'lookup ผ่านตรวจ', 152)
    label(888, 630, 'ยอดรายวัน', 122)
    label(806, 848, 'ข้อมูลหลังเชื่อมพื้นที่', 190)
    label(390, 1048, 'curated', 86)
    label(1020, 1072, 'audit: raw / valid / rejected', 242)
    label(428, 1144, 'PASS', 64, GREEN)
    label(852, 1144, 'รายงาน', 86)
    label(216, 1266, 'FAIL', 64, RED)
    label(640, 1252, 'ตาราง / กราฟ', 132)
    label(1064, 1266, 'สถานะรัน', 104)

    # Minimal legend: colors encode function; shapes and text carry the same meaning.
    parts.append(f'<path d="M56 1448 H1224" stroke="#36404A" stroke-width="1"/>')
    for x, color, title in [(56, BLUE, 'ขั้นตอน'), (232, GREEN, 'ชุดข้อมูล / ผลลัพธ์'), (512, AMBER, 'จุดตรวจคุณภาพ'), (772, RED, 'เส้นทางผิดพลาด')]:
        parts.append(f'<path d="M{x} 1477 H{x+24}" stroke="{color}" stroke-width="2"/>')
        parts.append(text(x+36, 1483, title, 17, MUTED))
    parts.append(text(56, 1520, 'หากขั้นใดผิดพลาด ระบบบันทึก FAILED และเก็บผลสำเร็จเดิมไว้  •  PUBLISH คือบันทึกผลในเครื่อง', 17, MUTED))
    parts.append('</svg>')

    return "\n".join(parts) + "\n"


def render_mermaid():
    if not nodes:
        render_svg()
    lines = [
        "flowchart TD",
        "    %% Generated by scripts/render_pipeline_diagram.py.",
        "    %% Same nodes and data relationships as the approved PNG/SVG.",
        "    %% Stage numbers show execution order; branches show data flow.",
    ]
    for node in nodes:
        label = "<br/>".join((node["title"], *node["lines"]))
        shape = f'[("{label}")]' if node["kind"] == "data" else f'("{label}")' if node["kind"] in ("process", "quality", "failed") else f'["{label}"]'
        lines.append(f'    {node["id"]}{shape}:::{node["kind"]}')
    for source, target, caption, failed in edges:
        arrow = "-.->" if failed else "-->"
        label = f'|"{caption}"|' if caption else ""
        lines.append(f"    {source} {arrow}{label} {target}")
    colors = {"source": "#667481", "process": BLUE, "data": GREEN,
              "evidence": GREEN, "quality": AMBER, "failed": RED}
    for kind, stroke in colors.items():
        dash = ",stroke-dasharray:5 5" if kind == "quality" else ""
        lines.append(f"    classDef {kind} fill:{SURFACE},stroke:{stroke},color:{TEXT},stroke-width:1.5px{dash}")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    image_path = ROOT / "docs/images/pipeline-data-flow.svg"
    image_path.parent.mkdir(parents=True, exist_ok=True)
    image_path.write_text(render_svg(), encoding="utf-8", newline="\n")
    (ROOT / "docs/pipeline.mmd").write_text(render_mermaid(), encoding="utf-8", newline="\n")
    print("Generated docs/images/pipeline-data-flow.svg and docs/pipeline.mmd")
    print("README PNG is the approved raster export; export an updated PNG after visual edits.")
