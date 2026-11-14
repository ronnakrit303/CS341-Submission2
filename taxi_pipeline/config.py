"""Validate configuration and build the complete, explicit input manifest."""

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re


TAXI_TYPES = {"Yellow", "Green", "FHV", "High Volume FHV"}


def next_month(month: str) -> str:
    year, number = map(int, month.split("-"))
    return f"{year + (number == 12):04d}-{number % 12 + 1:02d}"


def month_range(start: str, end: str) -> list[str]:
    for value in (start, end):
        if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", value):
            raise ValueError(f"Invalid YYYY-MM value: {value}")
        datetime.strptime(value, "%Y-%m")
    if start > end:
        raise ValueError("start_month must be <= end_month")
    result = []
    current = start
    while current <= end:
        result.append(current)
        current = next_month(current)
    return result


def digest_json(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


@dataclass
class Config:
    settings: dict
    root: Path

    @classmethod
    def load(cls, path: Path, root: Path, start=None, end=None):
        settings = json.loads(path.read_text(encoding="utf-8"))
        if start:
            settings["start_month"] = start
        if end:
            settings["end_month"] = end
        config = cls(settings, root.resolve())
        config.validate()
        return config

    def validate(self):
        month_range(self.settings["start_month"], self.settings["end_month"])
        types = self.settings["taxi_types"]
        if set(types) != TAXI_TYPES:
            raise ValueError("Configure exactly Yellow, Green, FHV and High Volume FHV")
        prefixes = []
        for spec in types.values():
            for key in ("prefix", "pickup", "dropoff", "pu_location", "do_location"):
                if not isinstance(spec.get(key), str) or not spec[key]:
                    raise ValueError(f"Missing source mapping: {key}")
            if not re.fullmatch(r"[a-z0-9_]+", spec["prefix"]):
                raise ValueError("Source prefix must be a simple filename prefix")
            prefixes.append(spec["prefix"])
        if len(set(prefixes)) != len(prefixes):
            raise ValueError("Taxi prefixes must be unique")
        for key in ("trip_base_url", "zone_lookup_url"):
            if not self.settings[key].startswith(("https://", "file://")):
                raise ValueError(f"{key} must use https:// (or file:// for offline fixtures)")
        for key in ("data_dir", "reports_dir"):
            location = (self.root / self.settings[key]).resolve()
            if location == self.root or not location.is_relative_to(self.root):
                raise ValueError(f"{key} must be a subdirectory inside the workspace")
        if self.settings["data_dir"] == self.settings["reports_dir"]:
            raise ValueError("data_dir and reports_dir must differ")
        for key in ("threads", "download_attempts"):
            value = self.settings[key]
            if type(value) is not int or not 1 <= value <= 32:
                raise ValueError(f"{key} must be an integer between 1 and 32")
        if not re.fullmatch(r"[1-9]\d*(MB|GB)", self.settings["memory_limit"]):
            raise ValueError("memory_limit must look like 512MB or 2GB")

    @property
    def start(self):
        return self.settings["start_month"] + "-01"

    @property
    def stop(self):
        return next_month(self.settings["end_month"]) + "-01"

    @property
    def months(self):
        return month_range(self.settings["start_month"], self.settings["end_month"])

    @property
    def data_dir(self):
        return self.root / self.settings["data_dir"]

    @property
    def reports_dir(self):
        return self.root / self.settings["reports_dir"]

    def manifest(self):
        rows = []
        for taxi_type, spec in self.settings["taxi_types"].items():
            for month in self.months:
                filename = f"{spec['prefix']}_tripdata_{month}.parquet"
                rows.append({
                    "taxi_type": taxi_type, "source_month": month,
                    "source_file": filename,
                    "url": f"{self.settings['trip_base_url'].rstrip('/')}/{filename}",
                    "spec": spec,
                })
        return rows
