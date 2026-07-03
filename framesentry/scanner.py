from __future__ import annotations

from pathlib import Path

from .analysis import AnalysisRunner, ReportBuilder, VideoContext, build_summary
from .analyzers import default_registry
from .report.html_report import write_html_report
from .report.json_report import write_json_report
from .cache import analysis_options, video_fingerprint


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
    context = VideoContext(
        video_path=video_path,
        output_dir=report_dir,
        video_id=video_path.stem,
        settings={
            "fps_normal": fps_values,
            "sample_scale": sample_scale,
            "max_outlier_frames": max_outlier_frames,
            "save_screenshots": save_screenshots,
            "source_file": video_fingerprint(video_path),
            "analysis_options": analysis_options(
                sample_scale=sample_scale,
                max_outlier_frames=max_outlier_frames,
                save_screenshots=save_screenshots,
            ),
        },
        artifact_dir=report_dir,
    )
    module_results = AnalysisRunner(default_registry()).run(context)
    report = ReportBuilder().build(context, module_results)

    if write_json:
        write_json_report(report, report_dir / "report.json")
    if write_html:
        write_html_report(report, report_dir / "report.html")
    return report
