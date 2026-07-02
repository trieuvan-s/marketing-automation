"""twmkt — Turtle Wealth Marketing Automation (Phase 0 scaffold)."""
from .orchestrator import MarketingPipeline, PipelineConfig
from .models import Source, SourceType, ContentFormat, Stage, Decision

__version__ = "0.2.0"
__all__ = [
    "MarketingPipeline", "PipelineConfig",
    "Source", "SourceType", "ContentFormat", "Stage", "Decision",
]
