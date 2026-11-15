"""Regression coverage for Windows locks during atomic output publication."""

import ctypes
from ctypes import wintypes
from pathlib import Path
import sys

import pytest

from taxi_pipeline import download
from taxi_pipeline.download import read_json, write_json
from taxi_pipeline.pipeline import run_pipeline


def windows_lock_error(code=5):
    error = PermissionError("Simulated Windows file lock")
    error.winerror = code
    return error


@pytest.mark.parametrize("code", [5, 32, 33])
def test_json_write_retries_windows_lock_and_keeps_previous_file(tmp_path, monkeypatch, code):
    target = tmp_path / "audit.json"
    write_json(target, {"version": "previous"})
    original = Path.replace
    attempts, delays = [], []

    def locked_replace(source, destination):
        attempts.append(source)
        assert read_json(target) == {"version": "previous"}
        assert read_json(source) == {"version": "new"}
        if len(attempts) <= 2:
            raise windows_lock_error(code)
        return original(source, destination)

    monkeypatch.setattr(Path, "replace", locked_replace)
    monkeypatch.setattr(download.time, "sleep", delays.append)
    write_json(target, {"version": "new"})
    assert len(attempts) == 3 and delays == [0.05, 0.1]
    assert read_json(target) == {"version": "new"}
    assert not target.with_name("audit.json.part").exists()


def test_persistent_windows_lock_is_bounded_and_keeps_previous_file(tmp_path, monkeypatch):
    target = tmp_path / "audit.json"
    write_json(target, {"version": "previous"})
    attempts, delays = [], []

    def locked_replace(source, destination):
        attempts.append(source)
        raise windows_lock_error()

    monkeypatch.setattr(Path, "replace", locked_replace)
    monkeypatch.setattr(download.time, "sleep", delays.append)
    with pytest.raises(PermissionError, match="Windows file lock"):
        write_json(target, {"version": "new"})
    assert len(attempts) == 7
    assert delays == [0.05, 0.1, 0.2, 0.4, 0.8, 1.6]
    assert read_json(target) == {"version": "previous"}
    assert read_json(target.with_name("audit.json.part")) == {"version": "new"}


@pytest.mark.parametrize("error", [PermissionError("Denied"), FileNotFoundError("Missing")])
def test_unrelated_errors_are_not_retried(tmp_path, monkeypatch, error):
    delays = []

    def fail(source, destination):
        raise error

    monkeypatch.setattr(Path, "replace", fail)
    monkeypatch.setattr(download.time, "sleep", delays.append)
    with pytest.raises(type(error)) as caught:
        write_json(tmp_path / "audit.json", {"version": "new"})
    assert caught.value is error
    assert delays == []


@pytest.mark.skipif(sys.platform != "win32", reason="Requires Windows sharing modes")
def test_json_write_recovers_after_real_windows_file_lock(tmp_path, monkeypatch):
    target = tmp_path / "audit.json"
    write_json(target, {"version": "previous"})
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                  wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    # Permit reads/writes, but hold back FILE_SHARE_DELETE so replacement fails.
    handle = kernel.CreateFileW(str(target), 0x80000000, 0x1 | 0x2, None, 3, 0x80, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    delays = []

    def release_lock(delay):
        nonlocal handle
        delays.append(delay)
        assert read_json(target) == {"version": "previous"}
        assert kernel.CloseHandle(handle)
        handle = None

    monkeypatch.setattr(download.time, "sleep", release_lock)
    try:
        write_json(target, {"version": "new"})
    finally:
        if handle is not None:
            kernel.CloseHandle(handle)
    assert delays == [0.05]
    assert read_json(target) == {"version": "new"}


@pytest.mark.parametrize("persistent", [False, True])
def test_audit_file_lock_recovery_and_failed_run_publication(fixture_config, monkeypatch, persistent):
    config, _ = fixture_config
    first = run_pipeline(config)
    pointer = config.reports_dir / "latest.json"
    previous = pointer.read_bytes()
    original = Path.replace
    attempts, delays = [], []

    def locked_audit(source, destination):
        if source.name == "file_audit.json.part":
            attempts.append(source)
            if persistent or len(attempts) <= 2:
                raise windows_lock_error()
        return original(source, destination)

    monkeypatch.setattr(Path, "replace", locked_audit)
    monkeypatch.setattr(download.time, "sleep", delays.append)
    if persistent:
        with pytest.raises(PermissionError, match="Windows file lock"):
            run_pipeline(config, offline=True)
        assert len(attempts) == 7
        assert pointer.read_bytes() == previous
        failed = [read_json(p) for p in (config.reports_dir / "runs").glob("*/run.json")
                  if read_json(p)["status"] == "FAILED"]
        assert len(failed) == 1 and failed[0]["current_step"] == 3
        assert [step["status"] for step in failed[0]["steps"]] == [
            "OK", "OK", "FAILED", "SKIPPED", "SKIPPED", "SKIPPED", "SKIPPED"]
    else:
        second = run_pipeline(config, offline=True)
        assert second["status"] == "SUCCESS"
        assert second["actions"] == {"reused": 4, "cached_verified": 4}
        assert second["curated_content_sha256"] == first["curated_content_sha256"]
        assert read_json(pointer)["run_id"] == second["run_id"]
        assert delays == [0.05, 0.1]
    assert not (config.data_dir / ".pipeline.lock").exists()
