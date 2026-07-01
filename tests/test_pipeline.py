"""Test Phase 0 — chạy: python -m pytest (hoặc python tests/test_pipeline.py)."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from twmkt.collectors.mock import MockCollector  # noqa: E402
from twmkt.curation import normalize, extract_tickers  # noqa: E402
from twmkt.guardrails import compliance  # noqa: E402
from twmkt.knowledge.rag import Retriever, chunk_text  # noqa: E402
from twmkt.models import (  # noqa: E402
    ContentDraft, ContentFormat, Decision, Source, SourceType, Stage,
)
from twmkt.approval.gate import AutoApproveGate  # noqa: E402
from twmkt.orchestrator import MarketingPipeline  # noqa: E402


def test_dedup_removes_duplicate_doc():
    raw = MockCollector().collect(Source("x", "http://x"))
    clean = normalize(raw)
    assert len(raw) == 3
    assert len(clean) == 2


def test_ticker_extraction_filters_noise():
    tickers = extract_tickers("FPT và HPG tăng, EPS cải thiện, ROE cao, USD giảm")
    assert "FPT" in tickers and "HPG" in tickers
    assert "EPS" not in tickers and "USD" not in tickers


def test_chunking_overlaps():
    words = " ".join(str(i) for i in range(1200))
    chunks = chunk_text(words, size=500, overlap=80)
    assert len(chunks) >= 2
    assert all(chunks)


def test_rag_retrieves_relevant_doc():
    clean = normalize(MockCollector().collect(Source("x", "http://x")))
    r = Retriever()
    assert r.index(clean) > 0
    hits = r.retrieve("thép Hòa Phát sản lượng", k=1)
    assert hits and "HPG" in " ".join(hits[0].tickers) or "Hòa Phát" in hits[0].title


def test_compliance_flags_banned_claim():
    bad = ContentDraft(ContentFormat.ARTICLE, "x",
                       "Mua ngay, cam kết lợi nhuận 20%/tháng, chắc chắn lãi!")
    issues = compliance.check(bad)
    assert any("cấm" in i for i in issues)
    assert any("disclaimer" in i.lower() for i in issues)


def test_full_pipeline_publishes_when_approved():
    pipe = MarketingPipeline(MockCollector())
    st = pipe.run("FPT tăng trưởng", [Source("CafeF", "http://c", SourceType.NEWS)])
    assert st.stage is Stage.PUBLISHED
    assert len(st.drafts) == 4
    assert len(st.published) >= 1
    assert st.brief is not None


def test_research_gate_rejection_saves_tokens():
    """Cổng 1 từ chối -> KHÔNG tạo bản nháp (không gọi LLM sinh nội dung đắt)."""
    pipe = MarketingPipeline(MockCollector(), research_gate=AutoApproveGate(Decision.REJECT))
    st = pipe.run("x", [Source("c", "http://c")])
    assert st.stage is Stage.REJECTED
    assert st.drafts == [] and st.published == []


def _run_all():
    fns = [v for k, v in globals().items() if k.startswith("test_")]
    for fn in fns:
        fn(); print(f"PASS {fn.__name__}")
    print(f"\n{len(fns)} tests passed.")


if __name__ == "__main__":
    _run_all()
