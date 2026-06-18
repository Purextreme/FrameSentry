from __future__ import annotations

from pathlib import Path

from .detectors.black_frame import detect_blank_frames, detect_black_frames
from .detectors.duplicate_frame import detect_duplicate_frames
from .detectors.transient_outlier import detect_transient_outliers
from .frame_reader import read_frame_metrics
from .metadata import inspect_metadata, read_metadata
from .metrics import adaptive_thresholds
from .report.html_report import write_html_report
from .report.json_report import write_json_report
from .cache import analysis_options, video_fingerprint
from .utils.screenshots import save_event_screenshots


def parse_fps_list(raw: str) -> set[float]:
    values: set[float] = set()
    for item in raw.split(","):
        item = item.strip()
        if item:
            values.add(float(item))
    return values


def scan_video(
    input_path: str | Path,
    output_dir: str | Path,
    *,
    sample_scale: int = 480,
    max_outlier_frames: int = 2,
    fps_normal: str | set[float] = "25,30,50,60",
    save_screenshots: bool = False,
    write_json: bool = True,
    write_html: bool = True,
) -> dict:
    video_path = Path(input_path)
    report_dir = Path(output_dir)
    report_dir.mkdir(parents=True, exist_ok=True)

    fps_values = parse_fps_list(fps_normal) if isinstance(fps_normal, str) else fps_normal
    metadata = read_metadata(video_path)
    events = inspect_metadata(metadata, fps_normal=fps_values)

    frame_metrics = read_frame_metrics(video_path, sample_scale=sample_scale, fps=metadata.fps)
    thresholds = adaptive_thresholds([metric.pixel_diff_to_prev for metric in frame_metrics if metric.pixel_diff_to_prev is not None])

    events.extend(detect_black_frames(frame_metrics, metadata.fps))
    events.extend(detect_blank_frames(frame_metrics, metadata.fps))
    events.extend(detect_duplicate_frames(frame_metrics, metadata.fps, thresholds))
    events.extend(
        detect_transient_outliers(
            frame_metrics,
            metadata.fps,
            thresholds,
            max_outlier_frames=max_outlier_frames,
        )
    )

    if save_screenshots:
        save_event_screenshots(video_path, events, report_dir / "screenshots")

    report = {
        "video": metadata.to_report(video_path),
        "source_file": video_fingerprint(video_path),
        "analysis_options": analysis_options(
            sample_scale=sample_scale,
            max_outlier_frames=max_outlier_frames,
            save_screenshots=save_screenshots,
        ),
        "summary": build_summary(events),
        "thresholds": thresholds,
        "events": events,
    }

    if write_json:
        write_json_report(report, report_dir / "report.json")
    if write_html:
        write_html_report(report, report_dir / "report.html")
    return report


def build_summary(events: list[dict]) -> dict[str, int]:
    keys = {
        "metadata_warnings": "metadata_warning",
        "black_frames": "black_frame",
        "blank_frames": "blank_frame",
        "duplicate_frames": "duplicate_frame",
        "transient_outliers": "transient_outlier",
    }
    return {name: sum(1 for event in events if event.get("type") == event_type) for name, event_type in keys.items()}
