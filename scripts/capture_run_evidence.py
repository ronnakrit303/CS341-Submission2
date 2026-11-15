"""Capture actual Windows console runs, with transcripts and hashed provenance.

The capture mode runs inside a classic conhost console, launched by CLI tools.
It uses PrintWindow to read that console's pixels; it never types into a UI.
The compare and quality commands also work without Windows.
"""

import argparse
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run_metadata(run_id):
    return read(ROOT / "reports/runs" / run_id / "run.json")


def compare(first_id, second_id):
    first, second = run_metadata(first_id), run_metadata(second_id)
    assert first_id != second_id, "Run IDs must differ"
    assert first["status"] == second["status"] == "SUCCESS"
    assert first["actions"].get("processed") == first["input_files"]
    assert second["actions"].get("reused") == second["input_files"]
    keys = ("effective_config", "source_code_sha256", "raw_count", "valid_count",
            "invalid_count", "curated_rows", "curated_content_sha256", "answer")
    for key in keys:
        assert first[key] == second[key], f"Runs differ: {key}"
    snapshot = read(ROOT / "artifacts/reproducibility.json")
    assert second["curated_content_sha256"] == snapshot["curated_content_sha256"]
    print("REBUILD RUN :", first_id)
    print("CACHE RERUN :", second_id)
    print("STATUS      : SUCCESS / SUCCESS")
    print("REBUILD     :", first["actions"])
    print("RERUN       :", second["actions"])
    print(f"VALID       : {first['valid_count']:,} / {second['valid_count']:,}")
    print(f"REJECTED    : {first['invalid_count']:,} / {second['invalid_count']:,}")
    print(f"CURATED ROWS: {first['curated_rows']:,} / {second['curated_rows']:,}")
    print("FIRST CONTENT SHA-256 :", first["curated_content_sha256"])
    print("SECOND CONTENT SHA-256:", second["curated_content_sha256"])
    print("PASS: new Run ID; same configuration, code, counts and curated content")
    print("PASS: all inputs recomputed first; all inputs reused on the second run")
    print("PASS: curated content also matches the committed artifacts snapshot")


def quality(run_id):
    q = read(ROOT / "reports/runs" / run_id / "quality.json")
    assert q["status"] == "PASS" and all(c["passed"] for c in q["checks"])
    print("RUN:", run_id)
    print("QUALITY STATUS:", q["status"])
    for index, check in enumerate(q["checks"], 1):
        print(f"{index:2}. {'PASS' if check['passed'] else 'FAIL'}  {check['check']}")
    print(f"PASS: {len(q['checks'])}/{len(q['checks'])} quality gates")
    print(f"RAW: {q['raw_count']:,} | VALID: {q['valid_count']:,} | REJECTED: {q['invalid_count']:,}")


class Console:
    """Read pixels from this process's own real console window."""

    def __init__(self):
        if os.name != "nt":
            raise RuntimeError("Screenshot capture requires Windows")
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.user = ctypes.WinDLL("user32", use_last_error=True)
        self.gdi = ctypes.WinDLL("gdi32", use_last_error=True)
        # PrintWindow returns physical pixels, so use unvirtualized dimensions.
        self.user.SetProcessDPIAware()
        self.kernel.GetConsoleWindow.restype = wintypes.HWND
        self.user.IsWindowVisible.argtypes = [wintypes.HWND]
        self.hwnd = self.kernel.GetConsoleWindow()
        if not self.hwnd or not self.user.IsWindowVisible(self.hwnd):
            raise RuntimeError("Launch capture in a visible classic conhost console")
        self.kernel.SetConsoleOutputCP(65001)
        self.kernel.SetConsoleCP(65001)
        self.kernel.GetStdHandle.restype = wintypes.HANDLE
        self.stdout = self.kernel.GetStdHandle(-11)
        self.kernel.GetConsoleMode.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        self.kernel.SetConsoleMode.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        mode = wintypes.DWORD()
        self.kernel.GetConsoleMode(self.stdout, ctypes.byref(mode))
        self.kernel.SetConsoleMode(self.stdout, mode.value | 4)
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

        class Coord(ctypes.Structure):
            _fields_ = [("X", ctypes.c_short), ("Y", ctypes.c_short)]

        class Rect(ctypes.Structure):
            _fields_ = [("Left", ctypes.c_short), ("Top", ctypes.c_short),
                        ("Right", ctypes.c_short), ("Bottom", ctypes.c_short)]

        # Resize only this task-owned console; no global settings are changed.
        self.kernel.SetConsoleScreenBufferSize.argtypes = [wintypes.HANDLE, Coord]
        self.kernel.SetConsoleWindowInfo.argtypes = [wintypes.HANDLE, wintypes.BOOL, ctypes.POINTER(Rect)]
        self.kernel.GetLargestConsoleWindowSize.argtypes = [wintypes.HANDLE]
        self.kernel.GetLargestConsoleWindowSize.restype = Coord
        largest = self.kernel.GetLargestConsoleWindowSize(self.stdout)
        columns, rows = min(140, largest.X), min(54, largest.Y - 2)
        self.kernel.SetConsoleScreenBufferSize(self.stdout, Coord(columns, 8000))
        self.kernel.SetConsoleWindowInfo(self.stdout, True, ctypes.byref(Rect(0, 0, columns - 1, rows - 1)))
        self.Coord, self.Rect = Coord, Rect

    def show_end(self):
        class BufferInfo(ctypes.Structure):
            _fields_ = [("size", self.Coord), ("cursor", self.Coord),
                        ("attributes", wintypes.WORD), ("window", self.Rect),
                        ("maximum", self.Coord)]
        self.kernel.GetConsoleScreenBufferInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(BufferInfo)]
        info = BufferInfo()
        if not self.kernel.GetConsoleScreenBufferInfo(self.stdout, ctypes.byref(info)):
            raise ctypes.WinError(ctypes.get_last_error())
        height = info.window.Bottom - info.window.Top + 1
        top = max(0, info.cursor.Y - height + 2)
        visible = self.Rect(info.window.Left, top, info.window.Right, top + height - 1)
        self.kernel.SetConsoleWindowInfo(self.stdout, True, ctypes.byref(visible))

    def clear(self, title):
        self.kernel.SetConsoleTitleW(title)
        print("\x1b[2J\x1b[H", end="", flush=True)

    def screenshot(self, path):
        from PIL import Image

        self.user.GetWindowDC.argtypes = [wintypes.HWND]
        self.user.GetWindowDC.restype = wintypes.HDC
        self.user.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        self.user.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
        self.user.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
        self.gdi.CreateCompatibleDC.argtypes = [wintypes.HDC]
        self.gdi.CreateCompatibleDC.restype = wintypes.HDC
        self.gdi.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
        self.gdi.CreateCompatibleBitmap.restype = wintypes.HBITMAP
        self.gdi.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
        self.gdi.SelectObject.restype = wintypes.HGDIOBJ
        self.gdi.DeleteObject.argtypes = [wintypes.HGDIOBJ]
        self.gdi.DeleteDC.argtypes = [wintypes.HDC]
        self.gdi.GetDIBits.argtypes = [wintypes.HDC, wintypes.HBITMAP, wintypes.UINT,
                                     wintypes.UINT, ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT]

        class BitmapInfo(ctypes.Structure):
            _fields_ = [("size", wintypes.DWORD), ("width", wintypes.LONG),
                        ("height", wintypes.LONG), ("planes", wintypes.WORD),
                        ("bits", wintypes.WORD), ("compression", wintypes.DWORD),
                        ("image_size", wintypes.DWORD), ("x_pixels", wintypes.LONG),
                        ("y_pixels", wintypes.LONG), ("used", wintypes.DWORD),
                        ("important", wintypes.DWORD)]

        rect = wintypes.RECT()
        if not self.user.GetWindowRect(self.hwnd, ctypes.byref(rect)):
            raise ctypes.WinError(ctypes.get_last_error())
        width, height = rect.right - rect.left, rect.bottom - rect.top
        window_dc = self.user.GetWindowDC(self.hwnd)
        memory_dc = self.gdi.CreateCompatibleDC(window_dc)
        bitmap = self.gdi.CreateCompatibleBitmap(window_dc, width, height)
        previous = self.gdi.SelectObject(memory_dc, bitmap)
        try:
            if not self.user.PrintWindow(self.hwnd, memory_dc, 2):
                raise RuntimeError("PrintWindow could not capture the actual console")
            self.gdi.SelectObject(memory_dc, previous)
            info = BitmapInfo(ctypes.sizeof(BitmapInfo), width, height, 1, 32)
            pixels = ctypes.create_string_buffer(width * height * 4)
            if self.gdi.GetDIBits(memory_dc, bitmap, 0, height, pixels, ctypes.byref(info), 0) != height:
                raise RuntimeError("Could not read console screenshot pixels")
            image = Image.frombytes("RGB", (width, height), pixels.raw, "raw", "BGRX", 0, -1)
            if all(high - low < 4 for low, high in image.getextrema()):
                raise RuntimeError("Console capture was blank")
            image.save(path, "PNG")
        finally:
            self.gdi.SelectObject(memory_dc, previous)
            self.gdi.DeleteObject(bitmap)
            self.gdi.DeleteDC(memory_dc)
            self.user.ReleaseDC(self.hwnd, window_dc)
        return {"width": width, "height": height, "method": "Win32 PrintWindow of task-owned conhost"}


def capture(output):
    os.chdir(ROOT)
    output = Path(output).resolve()
    if not output.is_relative_to(ROOT / "docs/evidence"):
        raise ValueError("Capture destination must be inside docs/evidence")
    output.mkdir(parents=True, exist_ok=False)
    (output / "transcripts").mkdir()
    console = Console()
    revision = subprocess.check_output(["git", "-c", "safe.directory=" + ROOT.as_posix(), "rev-parse", "HEAD"], text=True).strip()
    session = {"started_at_utc": now(), "executor": "Codex-assisted run on the user's Windows computer",
               "repository_revision": revision, "python_executable": sys.executable,
               "capture_script_sha256": digest(__file__), "status": "RUNNING", "commands": []}
    progress = ROOT / "tmp/screenshot-evidence-progress.json"
    write(progress, {"output": str(output), **session})

    def execute(stem, arguments):
        command = "python " + subprocess.list2cmdline(arguments)
        console.clear("CS341 evidence | " + command)
        started = now()
        header = f"CS341 SUBMISSION 2 - ACTUAL EXECUTION\nWorking directory: {ROOT}\nStarted (UTC): {started}\n{ROOT}> {command}\n\n"
        print(header, end="", flush=True)
        transcript = output / "transcripts" / (stem + ".txt")
        env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"}
        with transcript.open("w", encoding="utf-8", newline="\n") as log:
            log.write(header)
            process = subprocess.Popen([sys.executable, *arguments], cwd=ROOT, env=env,
                                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                       text=True, encoding="utf-8", errors="replace")
            for line in process.stdout:
                print(line, end="", flush=True)
                log.write(line)
                log.flush()
            code = process.wait()
            finished = now()
            footer = f"\nCommand: {command}\nExit code: {code}\nFinished (UTC): {finished}\n"
            print(footer, end="", flush=True)
            log.write(footer)
        console.show_end()
        time.sleep(0.7)
        image_path = output / (stem + ".png")
        dimensions = console.screenshot(image_path)
        session["commands"].append({"command": command, "started_at_utc": started,
            "finished_at_utc": finished, "exit_code": code, "screenshot": image_path.name,
            "transcript": transcript.relative_to(output).as_posix(), **dimensions})
        write(progress, {"output": str(output), **session})
        if code:
            raise RuntimeError(f"Evidence command failed ({code}): {command}")

    try:
        execute("01-pytest", ["-m", "pytest", "-v"])
        execute("02-rebuild", ["run_pipeline.py", "--offline", "--rebuild"])
        first = read(ROOT / "reports/latest.json")["run_id"]
        execute("03-cache-rerun", ["run_pipeline.py", "--offline"])
        second = read(ROOT / "reports/latest.json")["run_id"]
        session.update(rebuild_run_id=first, cache_run_id=second)
        execute("04-quality", ["scripts/capture_run_evidence.py", "quality", second])
        execute("05-reproducibility", ["scripts/capture_run_evidence.py", "compare", first, second])
        execute("06-verify-artifacts", ["scripts/verify_artifacts.py"])
        for run_id in (first, second):
            target = output / "runs" / run_id
            target.mkdir(parents=True)
            for name in ("run.json", "quality.json", "pipeline.log", "events.jsonl"):
                shutil.copyfile(ROOT / "reports/runs" / run_id / name, target / name)
        session.update(status="SUCCESS", finished_at_utc=now())
    except Exception as exc:
        session.update(status="FAILED", finished_at_utc=now(), error=f"{type(exc).__name__}: {exc}")
        raise
    finally:
        session["files"] = [{"path": p.relative_to(output).as_posix(), "bytes": p.stat().st_size,
                              "sha256": digest(p)} for p in sorted(output.rglob("*")) if p.is_file()]
        write(output / "session.json", session)
        write(progress, {"output": str(output), **session})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="mode", required=True)
    c = sub.add_parser("capture")
    c.add_argument("output")
    c = sub.add_parser("compare")
    c.add_argument("first")
    c.add_argument("second")
    c = sub.add_parser("quality")
    c.add_argument("run_id")
    args = parser.parse_args()
    if args.mode == "capture":
        capture(args.output)
    elif args.mode == "compare":
        compare(args.first, args.second)
    else:
        quality(args.run_id)


if __name__ == "__main__":
    main()
