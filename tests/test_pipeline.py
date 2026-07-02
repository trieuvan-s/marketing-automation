"""Test Phase 0 — chạy: python -m pytest (hoặc python tests/test_pipeline.py)."""
from __future__ import annotations

import os
import sys

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "src"))

from twmkt.collectors.mock import MockCollector  # noqa: E402
from twmkt.curation import (  # noqa: E402
    normalize, extract_tickers, is_relevant,
    FileDocumentStore, InMemoryStore,
)
from twmkt.curation.config import CurationConfig  # noqa: E402
from twmkt.guardrails import compliance  # noqa: E402
from twmkt.knowledge.rag import Retriever, chunk_text  # noqa: E402
from twmkt.models import (  # noqa: E402
    ContentDraft, ContentFormat, Decision, Source, SourceType, Stage,
)
from twmkt.agents import HookAgent, MarketingHook  # noqa: E402
from twmkt.approval.gate import AutoApproveGate, ConsoleApprovalGate  # noqa: E402
from twmkt.approval.sheets_gate import SheetsApprovalGate  # noqa: E402
from twmkt.config import Settings  # noqa: E402
from twmkt.orchestrator import MarketingPipeline, PipelineConfig  # noqa: E402
from twmkt import factory  # noqa: E402


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


# --- Config-first: load_settings đọc đúng key -------------------------------
def test_load_settings_reads_keys():
    try:
        import yaml  # noqa: F401
    except ImportError:
        print("  (SKIP: chưa cài pyyaml)"); return
    from twmkt.config import load_settings
    s = load_settings(os.path.join(REPO_ROOT, "config", "settings.yaml"))
    assert s.get("project.version") == "0.2.0"
    assert s.get("crawl.limit_per_source") == 8
    assert s.get("knowledge.chunk_size") == 500
    assert s.get("gates.research.type") == "console"
    assert len(s.enabled_sources()) >= 1


def test_settings_expands_env():
    from twmkt.config import _expand
    os.environ["TWMKT_SHEET_ID"] = "SHEET_ABC"
    data = _expand({"sheets": {"spreadsheet_id": "${TWMKT_SHEET_ID}"}})
    assert data["sheets"]["spreadsheet_id"] == "SHEET_ABC"


# --- Curation config: whitelist + mã dễ nhầm theo ngữ cảnh -------------------
def test_curation_whitelist_and_ambiguous():
    cfg = CurationConfig(
        tickers={"FPT", "HPG", "GAS"}, ambiguous={"GAS"},
        ambiguous_context_window=40,
    )
    assert extract_tickers("FPT và HPG tăng", cfg) == ["FPT", "HPG"]
    # GAS đứng một mình, không ngữ cảnh CK -> loại
    assert extract_tickers("Giá GAS thế giới tăng mạnh", cfg) == []
    # có marker 'cổ phiếu' -> giữ
    assert extract_tickers("Cổ phiếu GAS của Tổng công ty Khí", cfg) == ["GAS"]
    # đứng cạnh mã whitelist khác -> giữ
    assert extract_tickers("FPT và GAS cùng tăng", cfg) == ["FPT", "GAS"]


def test_relevance_filter_by_macro_keywords():
    cfg = CurationConfig(
        tickers={"FPT"}, macro_keywords=["lãi suất", "lạm phát", "gdp"],
        min_macro_keywords=2,
    )
    assert is_relevant("bàn về lãi suất và lạm phát", [], cfg) is True
    assert is_relevant("tin tức linh tinh", [], cfg) is False
    assert is_relevant("chỉ có 1 từ lãi suất", [], cfg) is False
    assert is_relevant("bài có mã", ["FPT"], cfg) is True   # có mã -> luôn liên quan


# --- Gate factory: đúng loại theo config (không gọi mạng) -------------------
def _settings_with_gate(gate_type: str) -> Settings:
    return Settings({
        "gates": {"research": {"type": gate_type}, "content": {"type": gate_type}},
        "sheets": {
            "spreadsheet_id": "SHEET_X", "creds_path": "secrets/sa.json",
            "research_worksheet": "R", "content_worksheet": "C",
            "poll_interval_s": 1, "timeout_s": 5, "on_timeout": "reject",
        },
    })


def test_gate_factory_console_auto_sheets():
    assert isinstance(factory.build_gate(_settings_with_gate("console"), gate="research"),
                      ConsoleApprovalGate)
    assert isinstance(factory.build_gate(_settings_with_gate("auto"), gate="content"),
                      AutoApproveGate)
    # 'sheets': kết nối lazy nên KHÔNG chạm mạng khi chỉ dựng gate.
    g = factory.build_gate(_settings_with_gate("sheets"), gate="research")
    assert isinstance(g, SheetsApprovalGate)
    assert g.worksheet == "R" and g.spreadsheet_id == "SHEET_X"


def test_gate_factory_rejects_unknown_type():
    try:
        factory.build_gate(_settings_with_gate("telepathy"), gate="research")
    except ValueError:
        return
    raise AssertionError("phải raise ValueError với gate type lạ")


# --- LLM factory: chọn theo provider (không gọi API) ------------------------
def test_build_llm_by_provider():
    from twmkt.agents.base import MockLLM, AnthropicLLM
    assert isinstance(factory.build_llm(Settings({"llm": {"provider": "mock"}})), MockLLM)
    # anthropic chỉ *dựng* client, không gọi API (import SDK cũng lazy trong complete)
    assert isinstance(factory.build_llm(Settings({"llm": {"provider": "anthropic"}})),
                      AnthropicLLM)


# --- Pipeline dựng-từ-config vẫn chạy offline, $0 token ----------------------
def test_config_built_pipeline_runs_offline():
    settings = Settings({
        "llm": {"provider": "mock"},
        "gates": {"research": {"type": "auto"}, "content": {"type": "auto"}},
        "knowledge": {"embedder": "hashing", "chunk_size": 500, "top_k": 5},
        "crawl": {"limit_per_source": 8},
        "curation": {
            "tickers_file": os.path.join(REPO_ROOT, "data", "tickers.txt"),
            "ambiguous_file": os.path.join(REPO_ROOT, "data", "tickers_ambiguous.txt"),
            "relevance": {
                "keywords_file": os.path.join(REPO_ROOT, "data", "keywords_macro.txt"),
                "min_macro_keywords": 2,
            },
        },
    })
    pipe = factory.build_pipeline(settings)   # offline -> MockCollector
    assert pipe.config.collect_limit == 8
    assert pipe.config.curation and "FPT" in pipe.config.curation.tickers
    st = pipe.run("FPT tăng trưởng", [Source("CafeF", "http://c", SourceType.NEWS)])
    assert st.stage is Stage.PUBLISHED
    assert len(st.drafts) == 4 and len(st.published) >= 1


# --- Bước Hook: ráp góc marketing vào pipeline ------------------------------
def test_pipeline_sets_hook_after_run():
    pipe = MarketingPipeline(MockCollector())   # mặc định hook bật
    st = pipe.run("FPT tăng trưởng", [Source("CafeF", "http://c", SourceType.NEWS)])
    assert st.stage is Stage.PUBLISHED
    assert isinstance(st.hook, MarketingHook)
    assert st.hook.headlines and all(st.hook.headlines)   # fallback tất định, không rỗng
    assert st.hook.cta


def test_hook_disabled_skips_step():
    pipe = MarketingPipeline(MockCollector(), config=PipelineConfig(hook_enabled=False))
    st = pipe.run("FPT tăng trưởng", [Source("CafeF", "http://c", SourceType.NEWS)])
    assert st.hook is None
    assert st.stage is Stage.PUBLISHED       # tắt hook không phá pipeline
    assert len(st.drafts) == 4


def test_hook_feeds_producers_title_and_cta():
    """Có hook -> ArticleWriter dùng headline làm tiêu đề, cta của hook làm CTA."""
    pipe = MarketingPipeline(MockCollector())
    st = pipe.run("FPT tăng trưởng", [Source("CafeF", "http://c", SourceType.NEWS)])
    article = next(d for d in st.drafts if d.fmt is ContentFormat.ARTICLE)
    assert article.title == st.hook.headlines[0]
    assert st.hook.cta in article.body


def test_hook_agent_offline_fallback_is_deterministic():
    """MockLLM không trả JSON -> HookAgent rơi về fallback tất định, $0 token."""
    from twmkt.models import ResearchBrief
    brief = ResearchBrief(topic="FPT tăng trưởng", tickers=["FPT"],
                          thesis="Luận điểm mẫu", key_points=["a", "b"])
    hook = HookAgent().run(brief)   # MockLLM mặc định
    assert isinstance(hook, MarketingHook)
    assert len(hook.headlines) == 3 and "FPT" in hook.headlines[0]


# --- Lưu trữ: FileDocumentStore persist + dedup across-run ------------------
def test_file_store_dedup_across_runs():
    import shutil
    import tempfile
    tmp = tempfile.mkdtemp()
    try:
        docs = normalize(MockCollector().collect(Source("x", "http://x")))
        assert len(docs) == 2
        s1 = FileDocumentStore(tmp)
        assert s1.upsert(docs) == 2          # lần 1: tất cả mới
        s2 = FileDocumentStore(tmp)          # store MỚI, cùng thư mục -> đọc lại từ đĩa
        assert s2.upsert(docs) == 0          # lần 2: 0 mới (persist across-run theo url)
        assert len(s2.all()) == 2
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_build_store_by_type():
    import shutil
    import tempfile
    assert isinstance(
        factory.build_store(Settings({"storage": {"type": "memory"}})), InMemoryStore
    )
    tmp = tempfile.mkdtemp()
    try:
        s = factory.build_store(
            Settings({"storage": {"type": "file", "documents_dir": tmp}})
        )
        assert isinstance(s, FileDocumentStore)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _run_all():
    fns = [v for k, v in globals().items() if k.startswith("test_")]
    for fn in fns:
        fn(); print(f"PASS {fn.__name__}")
    print(f"\n{len(fns)} tests passed.")


if __name__ == "__main__":
    _run_all()
