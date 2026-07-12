from __future__ import annotations

import traceback
from dataclasses import dataclass, field
from pathlib import Path
from collections.abc import Iterator
from typing import Any, Callable


VALID_STATUSES = {"pending", "running", "completed", "failed", "skipped"}
VALID_SEVERITIES = {"ok", "info", "warning", "error"}


@dataclass
class VideoContext:
    video_path: Path
    output_dir: Path
    video_id: str
    settings: dict[str, Any] = field(default_factory=dict)
    metadata: Any = None
    cache_dir: Path | None = None
    artifact_dir: Path | None = None

    def __post_init__(self) -> None:
        self.video_path = Path(self.video_path)
        self.output_dir = Path(self.output_dir)
        self.cache_dir = Path(self.cache_dir) if self.cache_dir is not None else self.output_dir / "cache"
        self.artifact_dir = Path(self.artifact_dir) if self.artifact_dir is not None else self.output_dir


@dataclass
class ModuleResult:
    module_id: str
    module_name: str
    status: str = "completed"
    severity: str = "ok"
    summary: dict[str, Any] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)
    charts: list[dict[str, Any]] = field(default_factory=list)
    tables: list[dict[str, Any]] = field(default_factory=list)
    assets: list[dict[str, Any] | str] = field(default_factory=list)
    data: dict[str, Any] = field(default_factory=dict)
    warnings: list[dict[str, Any] | str] = field(default_factory=list)
    errors: list[dict[str, Any] | str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.status not in VALID_STATUSES:
            raise ValueError(f"Invalid module status: {self.status}")
        if self.severity not in VALID_SEVERITIES:
            raise ValueError(f"Invalid module severity: {self.severity}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "module_id": self.module_id,
            "module_name": self.module_name,
            "status": self.status,
            "severity": self.severity,
            "summary": _json_safe(self.summary),
            "events": _json_safe(self.events),
            "charts": _json_safe(self.charts),
            "tables": _json_safe(self.tables),
            "assets": _json_safe(self.assets),
            "data": _json_safe(self.data),
            "warnings": _json_safe(self.warnings),
            "errors": _json_safe(self.errors),
        }


class BaseAnalyzer:
    module_id: str
    module_name: str
    enabled: bool = True

    def run(self, context: VideoContext) -> ModuleResult:
        raise NotImplementedError


class AnalyzerRegistry:
    def __init__(self) -> None:
        self._analyzers: list[BaseAnalyzer] = []

    def register(self, analyzer: BaseAnalyzer) -> None:
        self._analyzers.append(analyzer)

    def analyzers(self) -> list[BaseAnalyzer]:
        return list(self._analyzers)


class AnalysisRunner:
    def __init__(self, registry: AnalyzerRegistry) -> None:
        self.registry = registry

    def run(self, context: VideoContext) -> dict[str, ModuleResult]:
        return dict(self.run_iter(context))

    def run_iter(
        self,
        context: VideoContext,
        on_started: Callable[[BaseAnalyzer], None] | None = None,
    ) -> Iterator[tuple[str, ModuleResult]]:
        for analyzer in self.registry.analyzers():
            if on_started is not None:
                on_started(analyzer)
            if not analyzer.enabled:
                result = ModuleResult(
                    module_id=analyzer.module_id,
                    module_name=analyzer.module_name,
                    status="skipped",
                    severity="info",
                )
            else:
                try:
                    result = analyzer.run(context)
                except Exception as exc:
                    result = build_failed_result(analyzer, exc)
            yield analyzer.module_id, result


class ReportBuilder:
    def build(self, context: VideoContext, module_results: dict[str, ModuleResult]) -> dict[str, Any]:
        modules = {module_id: result.to_dict() for module_id, result in module_results.items()}
        events = _collect_events(modules)
        metadata_module = modules.get("metadata", {})
        frame_module = modules.get("frame_issues", {})
        if "source_file" in context.settings and metadata_module:
            metadata_module.setdefault("data", {})["source_file"] = context.settings["source_file"]
        if "analysis_options" in context.settings and frame_module:
            frame_module.setdefault("data", {})["analysis_options"] = context.settings["analysis_options"]
        video = (
            metadata_module.get("data", {}).get("video")
            or metadata_module.get("data", {}).get("metadata")
            or _metadata_to_report(context)
        )

        report = {
            "video": video,
            "summary": build_summary(events),
            "modules": modules,
        }
        return _json_safe(report)


def build_failed_result(analyzer: BaseAnalyzer, exc: Exception) -> ModuleResult:
    return ModuleResult(
        module_id=analyzer.module_id,
        module_name=analyzer.module_name,
        status="failed",
        severity="error",
        errors=[
            {
                "message": f"{analyzer.module_name} analyzer failed",
                "detail": str(exc),
                "traceback": traceback.format_exc(),
            }
        ],
    )


def build_summary(events: list[dict[str, Any]]) -> dict[str, int]:
    keys = {
        "metadata_warnings": "metadata_warning",
        "black_frames": "black_frame",
        "blank_frames": "blank_frame",
        "duplicate_frames": "duplicate_frame",
        "transient_outliers": "transient_outlier",
    }
    return {name: sum(1 for event in events if event.get("type") == event_type) for name, event_type in keys.items()}


def _collect_events(modules: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for module in modules.values():
        events.extend(module.get("events", []))
    return events


def _metadata_to_report(context: VideoContext) -> dict[str, Any]:
    if context.metadata is not None and hasattr(context.metadata, "to_report"):
        return context.metadata.to_report(context.video_path)
    return {"path": str(context.video_path)}


def _json_safe(value: Any) -> Any:
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    return value
