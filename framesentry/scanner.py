from __future__ import annotations

from pathlib import Path

from .analysis import AnalysisRunner, ReportBuilder, VideoContext
from .analyzers.color_analysis import DEFAULT_COLOR_SAMPLE_LIMIT
from .analyzers import default_registry
from .report.json_report import write_json_report
from .cache import ReportCacheManager, video_fingerprint


RUNTIME_CACHE_KEY = "_framesentry_runtime"


def parse_fps_list(raw: str) -> set[float]:
    values: set[float] = set()
    for item in raw.split(","):
        item = item.strip()
        if item:
            values.add(float(item))
    return values


def analysis_options(
    *,
    sample_scale: int,
    max_outlier_frames: int,
) -> dict:
    return {
        "sample_scale": int(sample_scale),
        "max_outlier_frames": int(max_outlier_frames),
        "save_screenshots": True,
    }


def scan_video(
    input_path: str | Path,
    output_dir: str | Path,
    *,
    sample_scale: int = 480,
    max_outlier_frames: int = 2,
    fps_normal: str | set[float] = "25,30,50,60",
    use_cache: bool = True,
    cache_root: str | Path = "output",
) -> dict:
    video_path = Path(input_path)
    report_dir = Path(output_dir)
    report_dir.mkdir(parents=True, exist_ok=True)

    if use_cache:
        cached = ReportCacheManager(cache_root).find(video_path)
        if cached:
            report = dict(cached.report)
            report[RUNTIME_CACHE_KEY] = {
                "cache_hit": True,
                "report_path": str(cached.report_path),
            }
            return report

    fps_values = parse_fps_list(fps_normal) if isinstance(fps_normal, str) else fps_normal
    context = VideoContext(
        video_path=video_path,
        output_dir=report_dir,
        video_id=video_path.stem,
        settings={
            "fps_normal": fps_values,
            "sample_scale": sample_scale,
            "max_outlier_frames": max_outlier_frames,
            "save_screenshots": True,
            "color_sample_limit": DEFAULT_COLOR_SAMPLE_LIMIT,
            "source_file": video_fingerprint(video_path),
            "analysis_options": analysis_options(
                sample_scale=sample_scale,
                max_outlier_frames=max_outlier_frames,
            ),
        },
        artifact_dir=report_dir,
    )
    module_results = AnalysisRunner(default_registry()).run(context)
    report = ReportBuilder().build(context, module_results)

    report_path = report_dir / "report.json"
    write_json_report(report, report_path)
    report[RUNTIME_CACHE_KEY] = {
        "cache_hit": False,
        "report_path": str(report_path),
    }
    return report
