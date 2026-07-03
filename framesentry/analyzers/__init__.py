from __future__ import annotations

from .color_analysis import ColorAnalysisAnalyzer
from .frame_issues import FrameIssueAnalyzer
from .metadata import MetadataAnalyzer

__all__ = ["ColorAnalysisAnalyzer", "FrameIssueAnalyzer", "MetadataAnalyzer", "default_registry"]


def default_registry():
    from framesentry.analysis import AnalyzerRegistry

    registry = AnalyzerRegistry()
    registry.register(MetadataAnalyzer())
    registry.register(FrameIssueAnalyzer())
    registry.register(ColorAnalysisAnalyzer())
    return registry
