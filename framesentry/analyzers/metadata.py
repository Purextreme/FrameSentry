from __future__ import annotations

from framesentry.analysis import BaseAnalyzer, ModuleResult, VideoContext
from framesentry.metadata import inspect_metadata, read_metadata


class MetadataAnalyzer(BaseAnalyzer):
    module_id = "metadata"
    module_name = "Metadata"

    def run(self, context: VideoContext) -> ModuleResult:
        fps_normal = context.settings.get("fps_normal", set())
        metadata = read_metadata(context.video_path)
        context.metadata = metadata
        events = inspect_metadata(metadata, fps_normal=fps_normal)
        video = metadata.to_report(context.video_path)
        severity = _severity_from_events(events)

        return ModuleResult(
            module_id=self.module_id,
            module_name=self.module_name,
            status="completed",
            severity=severity,
            summary={
                "metadata_warnings": len(events),
                "width": metadata.width,
                "height": metadata.height,
                "fps": metadata.fps,
            },
            events=events,
            data={
                "video": video,
                "metadata": video,
            },
        )


def _severity_from_events(events: list[dict]) -> str:
    severities = {event.get("severity") for event in events}
    if "error" in severities:
        return "error"
    if "warning" in severities:
        return "warning"
    if "info" in severities:
        return "info"
    return "ok"
