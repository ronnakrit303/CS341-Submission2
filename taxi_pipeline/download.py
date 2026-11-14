"""Atomic downloads and verified local snapshots. No implicit upstream refresh."""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import time
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname

import requests


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_file(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(8 * 1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".part")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


class Downloader:
    def __init__(self, attempts=3, offline=False, refresh=False):
        if offline and refresh:
            raise ValueError("--offline and --refresh cannot be used together")
        self.attempts, self.offline, self.refresh = attempts, offline, refresh
        self.session = requests.Session()
        self.session.headers["User-Agent"] = "CS341-NYC-Taxi-Pipeline/1.0 (academic project)"

    def close(self):
        self.session.close()

    def fetch(self, url: str, target: Path):
        target.parent.mkdir(parents=True, exist_ok=True)
        metadata_path = target.with_name(target.name + ".metadata.json")
        if not self.refresh and target.exists() and metadata_path.exists():
            metadata = read_json(metadata_path)
            if (metadata.get("url") == url and target.stat().st_size > 0
                    and target.stat().st_size == metadata.get("bytes")
                    and sha256_file(target) == metadata.get("sha256")):
                return {**metadata, "download_action": "cached_verified"}
        if self.offline and urlparse(url).scheme != "file":
            raise RuntimeError(f"Offline snapshot missing or hash mismatch: {target.name}")

        temporary = target.with_name(target.name + ".part")
        for attempt in range(1, self.attempts + 1):
            try:
                temporary.unlink(missing_ok=True)
                parsed = urlparse(url)
                if parsed.scheme == "file":
                    local = Path(url2pathname(unquote(parsed.path)))
                    # Local sources are useful for deterministic, network-free integration tests.
                    if parsed.netloc:
                        raise ValueError("Network file:// hosts are unsupported")
                    shutil.copyfile(local, temporary)
                    remote = {"etag": None, "last_modified": None}
                else:
                    with self.session.get(url, stream=True, timeout=(30, 180)) as response:
                        response.raise_for_status()
                        remote = {"etag": response.headers.get("ETag"),
                                  "last_modified": response.headers.get("Last-Modified")}
                        with temporary.open("wb") as output:
                            for chunk in response.iter_content(8 * 1024 * 1024):
                                if chunk:
                                    output.write(chunk)
                        declared = response.headers.get("Content-Length")
                        if declared and not response.headers.get("Content-Encoding"):
                            if temporary.stat().st_size != int(declared):
                                raise RuntimeError("Downloaded size differs from Content-Length")
                if temporary.stat().st_size == 0:
                    raise RuntimeError("Downloaded an empty file")
                metadata = {"url": url, "bytes": temporary.stat().st_size,
                            "sha256": sha256_file(temporary), "retrieved_at_utc": utc_now(), **remote}
                temporary.replace(target)
                write_json(metadata_path, metadata)
                return {**metadata, "download_action": "downloaded"}
            except Exception:
                temporary.unlink(missing_ok=True)
                if attempt == self.attempts:
                    raise
                time.sleep(attempt)
