from __future__ import annotations

from .color_analysis import ColorAnalysisAnalyzer
from .frame_issues import FrameIssueAnalyzer
from .llm_subtitle_detection import LlmSubtitleDetectionAnalyzer
from .metadata import MetadataAnalyzer
from .motion_analysis import MotionAnalysisAnalyzer

__all__ = ["ColorAnalysisAnalyzer", "FrameIssueAnalyzer", "LlmSubtitleDetectionAnalyzer", "MetadataAnalyzer", "MotionAnalysisAnalyzer", "default_registry"]


def default_registry():
    from framesentry.analysis import AnalyzerRegistry

    registry = AnalyzerRegistry()
    registry.register(MetadataAnalyzer())
    registry.register(FrameIssueAnalyzer())
    registry.register(ColorAnalysisAnalyzer())
    registry.register(MotionAnalysisAnalyzer())
    registry.register(LlmSubtitleDetectionAnalyzer())
    return registry
