from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass
class CachedReport:
    report_path: Path
    report: dict


def video_fingerprint(path: str | Path) -> dict:
    video_path = Path(path).resolve()
    stat = video_path.stat()
    return {
        "path": str(video_path),
        "size_bytes": stat.st_size,
        "modified_ns": stat.st_mtime_ns,
    }


class ReportCacheManager:
    def __init__(self, output_root: str | Path = "output") -> None:
        self.output_root = Path(output_root)

    def find(self, video_path: str | Path) -> CachedReport | None:
        if not self.output_root.exists():
            return None

        fingerprint = video_fingerprint(video_path)
        candidates = sorted(
            self.output_root.rglob("report.json"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        for report_path in candidates:
            try:
                report = json.loads(report_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if is_same_video_report(report, fingerprint):
                return CachedReport(report_path=report_path, report=report)
        return None


def is_same_video_report(report: dict, fingerprint: dict) -> bool:
    cached_fingerprint = report.get("modules", {}).get("metadata", {}).get("data", {}).get("source_file")
    if not cached_fingerprint:
        return False

    if Path(cached_fingerprint.get("path", "")).resolve() != Path(fingerprint["path"]).resolve():
        return False
    if cached_fingerprint.get("size_bytes") != fingerprint["size_bytes"]:
        return False
    if cached_fingerprint.get("modified_ns") != fingerprint["modified_ns"]:
        return False
    return True
