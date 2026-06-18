from __future__ import annotations

import json
from pathlib import Path


def video_fingerprint(path: str | Path) -> dict:
    video_path = Path(path).resolve()
    stat = video_path.stat()
    return {
        "path": str(video_path),
        "size_bytes": stat.st_size,
        "modified_ns": stat.st_mtime_ns,
    }


def analysis_options(
    *,
    sample_scale: int,
    max_outlier_frames: int,
    save_screenshots: bool,
) -> dict:
    return {
        "sample_scale": int(sample_scale),
        "max_outlier_frames": int(max_outlier_frames),
        "save_screenshots": bool(save_screenshots),
    }


def find_cached_report(
    video_path: str | Path,
    *,
    output_root: str | Path = "output",
    sample_scale: int,
    max_outlier_frames: int,
    save_screenshots: bool,
) -> Path | None:
    root = Path(output_root)
    if not root.exists():
        return None

    fingerprint = video_fingerprint(video_path)
    options = analysis_options(
        sample_scale=sample_scale,
        max_outlier_frames=max_outlier_frames,
        save_screenshots=save_screenshots,
    )
    candidates = sorted(root.rglob("report.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    for report_path in candidates:
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if is_cache_hit(report, fingerprint, options):
            return report_path
    return None


def is_cache_hit(report: dict, fingerprint: dict, options: dict) -> bool:
    cached_fingerprint = report.get("source_file")
    cached_options = report.get("analysis_options")
    if not cached_fingerprint or not cached_options:
        return False

    if Path(cached_fingerprint.get("path", "")).resolve() != Path(fingerprint["path"]).resolve():
        return False
    if cached_fingerprint.get("size_bytes") != fingerprint["size_bytes"]:
        return False
    if cached_fingerprint.get("modified_ns") != fingerprint["modified_ns"]:
        return False

    if cached_options.get("sample_scale") != options["sample_scale"]:
        return False
    if cached_options.get("max_outlier_frames") != options["max_outlier_frames"]:
        return False
    if options["save_screenshots"] and not cached_options.get("save_screenshots"):
        return False
    if options["save_screenshots"] and not _has_usable_screenshot_records(report):
        return False
    return True


def _has_usable_screenshot_records(report: dict) -> bool:
    screenshotable_events = [event for event in report.get("events", []) if "start_frame" in event]
    if not screenshotable_events:
        return True
    return all(event.get("screenshots") for event in screenshotable_events)
