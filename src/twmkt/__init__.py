"""twmkt — Marketing Automation (Phase 0 scaffold; brand identity lives in
config/brand.yaml, MỘT NGUỒN — KHÔNG hard-code brand ở docstring này)."""
from .orchestrator import MarketingPipeline, PipelineConfig
from .models import Source, SourceType, ContentFormat, Stage, Decision

__version__ = "0.2.0"
__all__ = [
    "MarketingPipeline", "PipelineConfig",
    "Source", "SourceType", "ContentFormat", "Stage", "Decision",
]
