from __future__ import annotations

from .frame_issues import FrameIssueAnalyzer
from .metadata import MetadataAnalyzer

__all__ = ["FrameIssueAnalyzer", "MetadataAnalyzer", "default_registry"]


def default_registry():
    from framesentry.analysis import AnalyzerRegistry

    registry = AnalyzerRegistry()
    registry.register(MetadataAnalyzer())
    registry.register(FrameIssueAnalyzer())
    return registry
