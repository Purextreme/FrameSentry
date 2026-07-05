from __future__ import annotations

from framesentry.analysis import BaseAnalyzer, ModuleResult, VideoContext, build_summary
from framesentry.detectors.black_frame import detect_blank_frames, detect_black_frames
from framesentry.detectors.duplicate_frame import detect_duplicate_frames, mark_periodic_duplicate_frame_warnings
from framesentry.detectors.transient_outlier import detect_transient_outliers
from framesentry.frame_reader import read_frame_metrics
from framesentry.metadata import read_metadata
from framesentry.metrics import adaptive_thresholds
from framesentry.utils.screenshots import save_event_screenshots


class FrameIssueAnalyzer(BaseAnalyzer):
    module_id = "frame_issues"
    module_name = "Frame Issues"

    def run(self, context: VideoContext) -> ModuleResult:
        metadata = context.metadata or read_metadata(context.video_path)
        context.metadata = metadata
        sample_scale = int(context.settings.get("sample_scale", 480))
        max_outlier_frames = int(context.settings.get("max_outlier_frames", 2))

        frame_metrics = read_frame_metrics(context.video_path, sample_scale=sample_scale, fps=metadata.fps)
        thresholds = adaptive_thresholds(
            [metric.pixel_diff_to_prev for metric in frame_metrics if metric.pixel_diff_to_prev is not None]
        )

        events: list[dict] = []
        events.extend(detect_black_frames(frame_metrics, metadata.fps))
        events.extend(detect_blank_frames(frame_metrics, metadata.fps))
        duplicate_events = detect_duplicate_frames(frame_metrics, metadata.fps, thresholds)
        mark_periodic_duplicate_frame_warnings(duplicate_events, metadata.fps)
        events.extend(duplicate_events)
        events.extend(
            detect_transient_outliers(
                frame_metrics,
                metadata.fps,
                thresholds,
                max_outlier_frames=max_outlier_frames,
            )
        )

        if events:
            save_event_screenshots(context.video_path, events, context.artifact_dir / "screenshots")

        return ModuleResult(
            module_id=self.module_id,
            module_name=self.module_name,
            status="completed",
            severity="warning" if events else "ok",
            summary=build_summary(events),
            events=events,
            assets=_collect_screenshot_assets(events),
            data={
                "thresholds": thresholds,
                "frame_count_analyzed": len(frame_metrics),
            },
        )


def _collect_screenshot_assets(events: list[dict]) -> list[dict]:
    assets: list[dict] = []
    for event in events:
        for label, path in event.get("screenshots", {}).items():
            assets.append(
                {
                    "type": "screenshot",
                    "label": label,
                    "path": path,
                    "event_type": event.get("type"),
                    "start_frame": event.get("start_frame"),
                }
            )
    return assets
