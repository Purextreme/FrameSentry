from __future__ import annotations

from .color_analysis import ColorAnalysisAnalyzer
from .frame_issues import FrameIssueAnalyzer
from .metadata import MetadataAnalyzer
from .motion_analysis import MotionAnalysisAnalyzer
from .subtitle_analysis import SubtitleAnalysisAnalyzer

__all__ = ["ColorAnalysisAnalyzer", "FrameIssueAnalyzer", "MetadataAnalyzer", "MotionAnalysisAnalyzer", "SubtitleAnalysisAnalyzer", "default_registry"]


def default_registry():
    from framesentry.analysis import AnalyzerRegistry

    registry = AnalyzerRegistry()
    registry.register(MetadataAnalyzer())
    registry.register(FrameIssueAnalyzer())
    registry.register(ColorAnalysisAnalyzer())
    registry.register(MotionAnalysisAnalyzer())
    registry.register(SubtitleAnalysisAnalyzer())
    return registry
