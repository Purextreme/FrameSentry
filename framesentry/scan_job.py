from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from threading import Lock, Thread
from typing import Any

from .analysis import AnalysisRunner, BaseAnalyzer, ModuleResult, ReportBuilder, VideoContext
from .analyzers import default_registry
from .report.json_report import write_json_report


class ScanJob:
    def __init__(self, context: VideoContext, report_path: Path) -> None:
        self._context = context
        self._report_path = report_path
        self._lock = Lock()
        self._status = "pending"
        self._modules = {
            analyzer.module_id: ModuleResult(
                module_id=analyzer.module_id,
                module_name=analyzer.module_name,
                status="pending",
                severity="info",
            ).to_dict()
            for analyzer in default_registry().analyzers()
        }
        self._report: dict[str, Any] | None = None
        self._error: str | None = None

    @classmethod
    def completed(cls, report: dict, report_path: Path, *, cache_hit: bool) -> ScanJob:
        job = cls.__new__(cls)
        job._context = None
        job._report_path = report_path
        job._lock = Lock()
        job._status = "completed"
        job._modules = deepcopy(report.get("modules", {}))
        job._report = deepcopy(report)
        job._error = None
        job._cache_hit = cache_hit
        return job

    def start(self) -> None:
        self._cache_hit = False
        Thread(target=self._run, name="framesentry-scan", daemon=True).start()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "status": self._status,
                "modules": deepcopy(self._modules),
                "report": deepcopy(self._report),
                "report_path": str(self._report_path),
                "cache_hit": self._cache_hit,
                "error": self._error,
            }

    def _run(self) -> None:
        with self._lock:
            self._status = "running"

        results: dict[str, ModuleResult] = {}
        try:
            runner = AnalysisRunner(default_registry())
            for module_id, result in runner.run_iter(self._context, on_started=self._mark_running):
                results[module_id] = result
                with self._lock:
                    self._modules[module_id] = result.to_dict()

            report = ReportBuilder().build(self._context, results)
            write_json_report(report, self._report_path)
            with self._lock:
                self._report = report
                self._status = "completed"
        except Exception as exc:
            with self._lock:
                self._error = str(exc)
                self._status = "failed"

    def _mark_running(self, analyzer: BaseAnalyzer) -> None:
        with self._lock:
            self._modules[analyzer.module_id]["status"] = "running"
