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
W, H = 1280, 1776
BG = "#FFFFFF"
SURFACE = "#FFFFFF"
TEXT = "#263341"
SECONDARY = "#374654"
MUTED = "#586674"
BLUE = "#2B789A"
GREEN = "#2D7C62"
AMBER = "#9C702B"
RED = "#B64C57"
EDGE = "#697784"
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


def caption(source, target, x, y, width, color=MUTED):
    value = next(value for start, end, value, _ in edges
                 if start == source and end == target)
    label(x, y, value, width, color)


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

    # Stage numbers show execution order; arrows describe data passed between stages.
    edge('configSource', 'prepare', 'M640 280 V336', '')
    edge('zoneSource', 'lookup', 'M216 280 V552', 'ข้อมูลพื้นที่')
    edge('tripSource', 'trips', 'M1064 280 V552', 'ข้อมูลการเดินทาง')
    edge('prepare', 'lookup', 'M528 480 V520 H440 V552', 'URL ของข้อมูลพื้นที่')
    edge('prepare', 'trips', 'M752 480 V520 H840 V552', 'ไฟล์ที่ต้องประมวลผล')
    edge('lookup', 'curate', 'M296 696 V744 H480 V792', 'ข้อมูลพื้นที่ที่ผ่านการตรวจสอบ')
    edge('trips', 'curate', 'M984 696 V744 H800 V792', 'จำนวนเที่ยวรายวัน')
    edge('curate', 'curatedStore', 'M640 912 V960', 'ข้อมูลที่เชื่อมกับพื้นที่แล้ว')
    edge('curatedStore', 'quality', 'M640 1092 V1136 H216 V1200', 'ข้อมูลที่จัดเตรียมแล้ว')
    edge('trips', 'quality', 'M1224 624 H1252 V1168 H312 V1200', 'Audit: raw / valid / rejected')
    edge('quality', 'analysis', 'M376 1288 H480', 'PASS')
    edge('analysis', 'publish', 'M800 1288 H904', 'ผลการวิเคราะห์')
    edge('quality', 'failed', 'M216 1376 V1480', 'FAIL', color=RED, failed=True)
    edge('analysis', 'analysisStore', 'M640 1376 V1480', 'ตารางและกราฟ')
    edge('publish', 'runEvidence', 'M1064 1376 V1480', 'สถานะการรัน')

    box('zoneSource', 56, 136, 320, 144, 'Taxi Zone Lookup', ('ไฟล์ CSV จาก NYC TLC', 'ประกอบด้วยรหัสพื้นที่', 'ชื่อพื้นที่ และ Borough'), 'source')
    box('configSource', 480, 136, 320, 144, 'Pipeline Config (JSON)', ('config/pipeline.json', 'กำหนดช่วงเวลา แหล่งข้อมูล', 'และตำแหน่งจัดเก็บไฟล์'), 'source')
    box('tripSource', 904, 136, 320, 144, 'Trip Records', ('ข้อมูลการเดินทางรูปแบบ Parquet', 'จาก NYC TLC', 'รวม 24 ไฟล์ จาก Taxi 4 ประเภท'), 'source')
    box('prepare', 480, 336, 320, 144, '01 · PREPARE', ('อ่านไฟล์ config และช่วงเวลาที่กำหนด', 'เตรียมรายการไฟล์สำหรับ', 'การประมวลผล'))
    box('lookup', 56, 552, 480, 144, '02 · LOOKUP', ('โหลดและตรวจสอบข้อมูลพื้นที่จากไฟล์ CSV', 'ตรวจสอบรหัสพื้นที่ทั้ง 265 รหัสว่าไม่ซ้ำกัน', 'เก็บข้อมูลไว้ในหน่วยความจำเพื่อใช้งานต่อ'))
    box('trips', 744, 552, 480, 144, '03 · TRIPS', ('ตรวจสอบ SHA-256 โครงสร้างข้อมูล และเงื่อนไขด้านเวลา', 'สรุปจำนวนเที่ยวรายวัน หรือใช้ผลเดิมจาก cache', 'หากข้อมูลตรงกัน'))
    box('curate', 400, 792, 480, 120, '04 · CURATED', ('เชื่อมข้อมูลเที่ยวรายวันกับพื้นที่รับผู้โดยสารด้วย LEFT JOIN', 'เก็บเที่ยวที่ไม่ทราบพื้นที่ไว้ในกลุ่ม Unknown'))
    cylinder('curatedStore', 360, 960, 560, 132, 'Curated Parquet', ('daily_zone_counts.parquet · trip_count', 'สรุปจำนวนเที่ยวแยกตามวัน ประเภท Taxi พื้นที่ และไฟล์ต้นทาง'))
    box('quality', 56, 1200, 320, 176, '05 · QUALITY', ('ตรวจสอบคุณภาพข้อมูล', 'ตามเงื่อนไขทั้ง 10 ข้อ', 'เปรียบเทียบยอดข้อมูลที่สรุปแล้ว', 'กับผลการตรวจสอบใน audit'), 'quality')
    box('analysis', 480, 1200, 320, 176, '06 · ANALYSIS', ('สรุปจำนวนเที่ยวและจัดอันดับ Taxi', 'แต่ละประเภท', 'สร้างตารางและกราฟ', 'แสดงผลการวิเคราะห์'))
    box('publish', 904, 1200, 320, 176, '07 · PUBLISH', ('บันทึกสถานะ SUCCESS', 'พร้อม content hash', 'อัปเดต latest.json ให้ชี้ไปยัง', 'รอบที่สำเร็จล่าสุด'))
    box('failed', 56, 1480, 320, 156, 'FAILED', ('บันทึกรายละเอียดข้อผิดพลาดลงใน log', 'เก็บผลลัพธ์จากรอบที่สำเร็จก่อนหน้าไว้'), 'failed')
    cylinder('analysisStore', 480, 1480, 320, 156, 'Analysis Results', ('ผลการจัดอันดับ จำนวนเที่ยวรายเดือน', 'และข้อมูลแยกตามพื้นที่', 'ผลลัพธ์ในรูปแบบ CSV และกราฟ'))
    box('runEvidence', 904, 1480, 320, 156, 'Run Logs & Evidence', ('ไฟล์ run.json และ pipeline.log', 'latest.json สำหรับอ้างอิง', 'ผลการรันล่าสุดที่สำเร็จ'), 'evidence')

    caption('zoneSource', 'lookup', 216, 410, 94)
    caption('tripSource', 'trips', 1064, 410, 136)
    caption('prepare', 'lookup', 396, 500, 154)
    caption('prepare', 'trips', 920, 500, 156)
    caption('lookup', 'curate', 432, 722, 218)
    caption('trips', 'curate', 884, 722, 142)
    caption('curate', 'curatedStore', 862, 936, 184)
    caption('curatedStore', 'quality', 414, 1136, 156)
    caption('trips', 'quality', 1020, 1168, 226)
    caption('quality', 'analysis', 428, 1268, 64, GREEN)
    caption('analysis', 'publish', 852, 1268, 102)
    caption('quality', 'failed', 216, 1428, 64, RED)
    caption('analysis', 'analysisStore', 640, 1428, 122)
    caption('publish', 'runEvidence', 1064, 1428, 110)

    # Minimal legend: colors encode function; shapes and text carry the same meaning.
    parts.append(f'<path d="M56 1680 H1224" stroke="#D7DFE5" stroke-width="1"/>')
    for x, color, title in [(56, BLUE, 'ขั้นตอน'), (232, GREEN, 'ชุดข้อมูล / ผลลัพธ์'), (512, AMBER, 'จุดตรวจคุณภาพ'), (772, RED, 'เส้นทางผิดพลาด')]:
        parts.append(f'<path d="M{x} 1709 H{x+24}" stroke="{color}" stroke-width="2"/>')
        parts.append(text(x+36, 1715, title, 17, MUTED))
    parts.append(text(56, 1752, 'หากขั้นใดผิดพลาด ระบบบันทึก FAILED และเก็บผลสำเร็จเดิมไว้  •  PUBLISH คือบันทึกผลในเครื่อง', 17, MUTED))
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
