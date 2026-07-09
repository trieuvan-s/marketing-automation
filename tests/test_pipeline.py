"""Test Phase 0 — chạy: python -m pytest (hoặc python tests/test_pipeline.py)."""
from __future__ import annotations

import os
import sys

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "src"))

from twmkt._encoding import ensure_utf8_stdio  # noqa: E402

ensure_utf8_stdio()

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
    assert s.get("crawl.limit_per_source") == 12
    assert s.get("knowledge.chunk_size") == 500
    assert s.get("gates.research.type") == "console"
    assert len(s.enabled_sources()) == 9        # 3 CafeF html + 6 nguồn rss (CafeF/CafeBiz/Vietstock)
    # whitelist trỏ sang danh sách mã đầy đủ (VN30 giữ cho test)
    assert s.get("curation.tickers_file") == "data/tickers_full.txt"


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


def test_ambiguous_tokens_do_not_mutually_validate():
    """2 mã dễ nhầm đứng gần nhau (USD ~ HCM) KHÔNG tự xác nhận -> tránh dương tính giả.
    Chỉ mã XÁC ĐỊNH đứng gần mới tạo ngữ cảnh CK."""
    cfg = CurationConfig(
        tickers={"USD", "HCM", "FPT"}, ambiguous={"USD", "HCM"},
        ambiguous_context_window=40,
    )
    # "tỷ USD cho TP.HCM": cả hai dễ nhầm, không marker -> loại sạch
    assert extract_tickers("xây hạ tầng tỷ USD cho TP.HCM", cfg) == []
    # đứng cạnh mã xác định (FPT) -> giữ
    assert extract_tickers("FPT chi 2 tỷ USD", cfg) == ["FPT", "USD"]
    # có marker CK -> giữ
    assert extract_tickers("cổ phiếu HCM của HSC", cfg) == ["HCM"]


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


def test_hook_fallback_uses_article_title_not_raw_topic():
    """Fallback bám tiêu đề BÀI (key_points[0]), KHÔNG lặp lại 'topic' thô."""
    from twmkt.models import ResearchBrief
    title = "FPT báo lãi quý 2 tăng hai chữ số"
    brief = ResearchBrief(topic="điểm tin doanh nghiệp", tickers=["FPT"],
                          thesis="x", key_points=[title, "bài khác"])
    hook = HookAgent().run(brief)   # MockLLM -> fallback
    assert title in hook.headlines[0]           # tiêu đề bài, không phải topic
    assert "điểm tin doanh nghiệp" not in hook.headlines[0]
    assert title in hook.angle


def test_hook_fallback_has_no_generic_market_prefix():
    """Fallback KHÔNG mở bằng 'thị trường:' (kiểu chung chung đã bỏ)."""
    from twmkt.models import ResearchBrief
    brief = ResearchBrief(topic="điểm tin", tickers=[], thesis="x",
                          key_points=["Giá vàng lập kỷ lục mới"])
    hook = HookAgent().run(brief)   # MockLLM -> fallback
    for h in hook.headlines:
        assert "thị trường:" not in h.lower()
    assert "thị trường:" not in hook.angle.lower()


def test_hook_parses_llm_json():
    """LLM trả JSON hợp lệ (kể cả bọc ```json) -> dùng đúng angle/headlines/cta."""
    from twmkt.models import ResearchBrief

    class JsonLLM:
        def complete(self, system, prompt):
            return ('```json\n{"angle": "Góc sắc", "headlines": ["H1 dẫn số 20%", '
                    '"H2 tò mò?", "H3 tương phản"], "audience": "NĐT cá nhân", '
                    '"emotion": "bất ngờ", "cta": "CTA riêng"}\n```')

    hook = HookAgent(JsonLLM()).run(ResearchBrief(
        topic="t", tickers=["FPT"], thesis="x", key_points=["Tiêu đề bài"]))
    assert hook.angle == "Góc sắc"
    assert hook.headlines == ["H1 dẫn số 20%", "H2 tò mò?", "H3 tương phản"]
    assert hook.cta == "CTA riêng" and hook.emotion == "bất ngờ"


def test_try_json_hardening_fence_and_prose():
    """_try_json HARDENING: bóc code fence ```json...```; và vẫn lấy được JSON dù
    model lỡ kèm lời dẫn trước/sau (dặn rồi nhưng đề phòng không tuân thủ)."""
    from twmkt.agents.hook import _try_json

    assert _try_json('```json\n{"angle": "a", "headlines": ["h1"]}\n```') == {
        "angle": "a", "headlines": ["h1"]}
    assert _try_json('```\n{"angle": "b"}\n```') == {"angle": "b"}   # fence không ghi "json"
    assert _try_json('Đây là kết quả:\n{"angle": "c"}\nHết.') == {"angle": "c"}
    assert _try_json("") is None
    assert _try_json("không phải JSON gì cả") is None


def test_hook_agent_stores_last_prompt_and_raw_for_debug():
    """HookAgent lưu last_prompt/last_raw của LẦN GỌI GẦN NHẤT (debug --debug),
    và prompt PHẢI kèm dặn 'CHỈ trả JSON' để tăng tỉ lệ model tuân thủ."""
    from twmkt.models import ResearchBrief

    class RecordingLLM:
        def complete(self, system, prompt): return "phản hồi không phải JSON"

    agent = HookAgent(RecordingLLM())
    agent.run(ResearchBrief(topic="t", tickers=["FPT"], thesis="x",
                            key_points=["Tiêu đề bài test"]))
    assert "CHỈ trả JSON" in agent.last_prompt
    assert "Tiêu đề bài test" in agent.last_prompt
    assert agent.last_raw == "phản hồi không phải JSON"


def test_researcher_prompt_anchors_on_article_titles():
    """Researcher gửi tiêu đề bài giữ lại vào prompt + dặn KHÔNG lặp topic thô."""
    from twmkt.agents.researcher import ResearcherAgent
    from twmkt.knowledge.rag import Retriever

    class RecordingLLM:
        def __init__(self): self.prompt = ""
        def complete(self, system, prompt):
            self.prompt = prompt
            return "Luận điểm cụ thể về FPT."

    docs = normalize(MockCollector().collect(Source("x", "http://x")))
    r = Retriever(); r.index(docs)
    spy = RecordingLLM()
    brief = ResearcherAgent(spy).run("kết quả kinh doanh doanh nghiệp", r)
    assert brief.thesis == "Luận điểm cụ thể về FPT."
    assert brief.key_points and brief.key_points[0] in spy.prompt   # tiêu đề bài vào prompt
    assert "KHÔNG lặp lại" in spy.prompt                            # dặn không echo topic


def test_researcher_empty_llm_falls_back_to_article_title():
    """LLM trả rỗng -> luận điểm = tiêu đề bài giữ lại (không echo topic thô)."""
    from twmkt.agents.researcher import ResearcherAgent
    from twmkt.knowledge.rag import Retriever

    class EmptyLLM:
        def complete(self, system, prompt): return "   "

    docs = normalize(MockCollector().collect(Source("x", "http://x")))
    r = Retriever(); r.index(docs)
    brief = ResearcherAgent(EmptyLLM()).run("chủ đề thô", r)
    assert brief.thesis == brief.key_points[0]
    assert brief.thesis != "chủ đề thô"


def test_llm_router_tracks_tokens_cost_and_caches():
    """LLMRouter (đã có) đo token/chi phí ước tính + cache theo (model,system,prompt)."""
    from twmkt.agents.router import LLMRouter, Tier
    from twmkt.agents.base import MockLLM as _Mock

    router = LLMRouter(_Mock(), default_tier=Tier.CHEAP)
    router.complete("hệ thống", "một prompt đủ dài để ước tính vài token")
    u = router.usage.as_dict()
    assert u["calls"] == 1 and u["in_tokens"] > 0 and u["out_tokens"] > 0
    assert u["cost_usd"] >= 0 and "claude-haiku-4-5" in u["by_model"]
    router.complete("hệ thống", "một prompt đủ dài để ước tính vài token")  # trùng -> cache
    u2 = router.usage.as_dict()
    assert u2["calls"] == 1 and u2["cache_hits"] == 1                      # không tính thêm


def test_build_research_llm_offline_and_provider():
    """factory.build_research_llm: offline -> Mock; anthropic -> Haiku; đều bọc Router."""
    from twmkt.agents.router import LLMRouter
    from twmkt.agents.base import MockLLM as _Mock, AnthropicLLM

    off = factory.build_research_llm(Settings({"llm": {"provider": "anthropic"}}), offline=True)
    assert isinstance(off, LLMRouter) and isinstance(off.base, _Mock)

    real = factory.build_research_llm(
        Settings({"llm": {"provider": "anthropic", "triage_model": "claude-haiku-4-5-20251001",
                          "budget_usd": 1.0}}),
        offline=False,
    )
    assert isinstance(real, LLMRouter) and isinstance(real.base, AnthropicLLM)
    assert real.base.model == "claude-haiku-4-5-20251001"   # tầng rẻ
    assert real.budget_usd == 1.0                            # hạn mức từ config


def test_build_hook_llm_uses_content_model_sonnet():
    """factory.build_hook_llm: HOOK = content_model (Sonnet), tier SMART; hook_model
    riêng override; offline -> Mock. Đều bọc Router."""
    from twmkt.agents.router import LLMRouter, Tier
    from twmkt.agents.base import MockLLM as _Mock, AnthropicLLM

    off = factory.build_hook_llm(Settings({"llm": {"provider": "anthropic"}}), offline=True)
    assert isinstance(off, LLMRouter) and isinstance(off.base, _Mock)

    real = factory.build_hook_llm(
        Settings({"llm": {"provider": "anthropic", "content_model": "claude-sonnet-4-6",
                          "budget_usd": 2.0}}), offline=False)
    assert isinstance(real, LLMRouter) and isinstance(real.base, AnthropicLLM)
    assert real.base.model == "claude-sonnet-4-6"   # Hook = content_model (Sonnet)
    assert real.default_tier is Tier.SMART           # định giá Sonnet
    assert real.budget_usd == 2.0
    # hook_model riêng -> override content_model
    r2 = factory.build_hook_llm(
        Settings({"llm": {"provider": "anthropic", "hook_model": "claude-opus-4-8",
                          "content_model": "claude-sonnet-4-6"}}), offline=False)
    assert r2.base.model == "claude-opus-4-8"


def test_anthropic_llm_degrades_gracefully_without_key():
    """LÙI MƯỢT: thiếu SDK/khóa -> is_available False; complete() trả rỗng, KHÔNG raise."""
    from twmkt.agents.base import AnthropicLLM

    old = os.environ.pop("ANTHROPIC_API_KEY", None)
    try:
        ok, why = AnthropicLLM.is_available()
        assert ok is False and why                       # thiếu SDK hoặc thiếu khóa
        out = AnthropicLLM(model="claude-sonnet-4-6").complete("hệ thống", "prompt")
        assert out == ""                                  # trả rỗng -> agent tự fallback ($0)
    finally:
        if old is not None:
            os.environ["ANTHROPIC_API_KEY"] = old


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
            Settings({"storage": {"type": "file", "documents_dir": tmp, "retention_days": 5}})
        )
        assert isinstance(s, FileDocumentStore) and s.retention_days == 5
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _doc(i: int) -> "object":
    from twmkt.models import CleanDocument
    return CleanDocument(source="s", url=f"http://u/{i}", title=f"Tiêu đề {i}",
                         markdown=f"Nội dung bài số {i}")


def test_file_store_day_partition_and_intraday_dedup():
    """Partition theo NGÀY + chạy nhiều lần TRONG NGÀY không tạo bản trùng (nội dung)."""
    import shutil
    import tempfile
    from pathlib import Path
    tmp = tempfile.mkdtemp()
    try:
        d1, d2 = _doc(1), _doc(2)
        s1 = FileDocumentStore(tmp, today="2026-07-04")
        assert s1.upsert([d1, d2]) == 2                 # lần 1 trong ngày: 2 mới
        s2 = FileDocumentStore(tmp, today="2026-07-04")  # chạy lại CÙNG ngày
        assert s2.upsert([d1, d2]) == 0                 # 0 mới (dedup nội dung across-run)
        day = Path(tmp) / "2026-07-04"
        assert day.is_dir() and len(list(day.glob("*.json"))) == 2   # đúng folder ngày, 2 file
        assert len(s2.all()) == 2
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_file_store_cross_day_dedup_and_retention_10():
    """Dedup CHÉO ngày còn giữ + chỉ giữ tối đa 10 folder ngày (folder cũ bị xoá)."""
    import shutil
    import tempfile
    from pathlib import Path
    tmp = tempfile.mkdtemp()
    try:
        for i in range(1, 13):                          # 12 ngày, mỗi ngày 1 bài mới
            FileDocumentStore(tmp, today=f"2026-07-{i:02d}", retention_days=10).upsert([_doc(i)])
        days = sorted(p.name for p in Path(tmp).iterdir() if p.is_dir())
        assert len(days) == 10                          # chỉ giữ 10 ngày mới nhất
        assert days[0] == "2026-07-03" and days[-1] == "2026-07-12"  # ngày 01,02 bị xoá

        s = FileDocumentStore(tmp, today="2026-07-12", retention_days=10)
        assert s.upsert([_doc(3)]) == 0                 # bài ngày 03 CÒN giữ -> dedup chéo ngày
        assert s.upsert([_doc(1)]) == 1                 # bài ngày 01 đã bị xoá -> coi là MỚI
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_crawl4ai_extracts_article_links_from_fake_listing():
    """Từ company: parsing link bài tất định trên fixture (không mạng, $0)."""
    from twmkt.collectors.crawl4ai_collector import Crawl4aiCollector
    from twmkt.collectors.sources import CAFEF_DOANH_NGHIEP

    class FakeListing:
        links = {
            "internal": [
                {"href": "https://cafef.vn/doanh-nghiep.chn", "text": "Doanh nghiệp", "title": "", "base_domain": "cafef.vn"},
                {"href": "https://cafef.vn/du-lieu/top/ceo.chn", "text": "CEO", "title": "", "base_domain": "cafef.vn"},
                {"href": "https://cafef.vn/ceo-dat-bike-trai-long-188260701104607570.chn", "text": "CEO Dat Bike", "title": "", "base_domain": "cafef.vn"},
                {"href": "/g-group-gia-nhap-duong-dua-188260630190724738.chn", "text": "G-Group", "title": "", "base_domain": "cafef.vn"},
                {"href": None, "text": "", "title": "", "base_domain": "cafef.vn"},
            ],
            "external": [
                {"href": "https://ads.example.com/banner.chn", "text": "qc", "title": "", "base_domain": "example.com"},
            ],
        }

    collector = Crawl4aiCollector(article_link_pattern=CAFEF_DOANH_NGHIEP.article_link_re)
    links = collector._extract_article_links(FakeListing(), "https://cafef.vn/doanh-nghiep.chn")
    assert len(links) == 2
    assert all(l.endswith(".chn") for l in links)
    assert not any("ads.example.com" in l for l in links)


_FAKE_LISTING_HTML = """
<html><body>
  <a href="/doanh-nghiep.chn">Trang mục</a>
  <a href="/du-lieu/top/ceo.chn">Bảng CEO</a>
  <a href="https://cafef.vn/ceo-dat-bike-trai-long-188260701104607570.chn">Bài 1</a>
  <a href="/g-group-gia-nhap-duong-dua-188260630190724738.chn">Bài 2</a>
  <a href="https://cafef.vn/ceo-dat-bike-trai-long-188260701104607570.chn">Bài 1 (trùng)</a>
  <a href="https://ads.example.com/promo-999999999999.chn">Quảng cáo ngoại miền</a>
  <a href="#top">Neo</a>
  <a>Không href</a>
</body></html>
"""

_FAKE_ARTICLE_HTML = """
<html><body>
  <h1>  FPT   báo lãi quý   tăng trưởng  </h1>
  <div class="detail-content afcbc-body">
    <div class="chisochungkhoan" style="display:none">FPT: Giá hiện tại Thay đổi Xem hồ sơ doanh nghiệp</div>
    <div id="listNewsInContent">TIN MỚI: đọc thêm bài khác</div>
    <div class="VCSortableInPreviewMode">[Ảnh minh họa quảng cáo]</div>
    <p>Công ty Cổ phần này công bố doanh thu và lợi nhuận tăng.</p>
    <p>Mảng dịch vụ CNTT nước ngoài là động lực chính.</p>
    <script>var ads = 1;</script>
  </div>
</body></html>
"""


def test_http_extract_links_filters_pattern_and_domain():
    """extract_links: chỉ giữ link bài nội miền khớp pattern, dedup, bỏ mục/ads."""
    import re as _re
    from twmkt.collectors.http_collector import extract_links

    pat = _re.compile(r"-\d{6,}\.chn$")
    links = extract_links(_FAKE_LISTING_HTML, "https://cafef.vn/doanh-nghiep.chn", pat)
    assert len(links) == 2                                   # dedup bài trùng
    assert all(l.startswith("https://cafef.vn/") for l in links)
    assert all(l.endswith(".chn") for l in links)
    assert not any("ads.example.com" in l for l in links)    # loại ngoại miền
    assert not any(l.endswith("/doanh-nghiep.chn") for l in links)  # loại trang mục


def test_http_extract_article_parses_and_strips_noise():
    """extract_article: bóc h1 + thân bài, trích mã từ box CK, loại 'TIN MỚI'/ads/
    script + chrome giá, gộp whitespace."""
    from twmkt.collectors.http_collector import extract_article

    title, body = extract_article(
        _FAKE_ARTICLE_HTML,
        title_selector="h1",
        body_selector="div.detail-content.afcbc-body",
        noise_selectors=("#listNewsInContent", ".VCSortableInPreviewMode", "script", "style"),
        ticker_box_selector=".chisochungkhoan",
    )
    assert title == "FPT báo lãi quý tăng trưởng"            # whitespace đã gộp
    assert body.startswith("Mã liên quan: FPT.")             # mã trích từ box CK
    assert "doanh thu và lợi nhuận tăng" in body
    assert "Giá hiện tại" not in body                        # chrome giá đã loại
    assert "TIN MỚI" not in body                             # box nhiễu đã loại
    assert "quảng cáo" not in body.lower()
    assert "var ads" not in body                             # script đã loại
    assert "  " not in body                                  # không còn khoảng trắng kép


def test_http_extract_article_missing_body_returns_empty():
    """Không thấy body_selector -> body rỗng (collector sẽ bỏ bài)."""
    from twmkt.collectors.http_collector import extract_article

    title, body = extract_article(
        "<html><body><h1>Tiêu đề</h1></body></html>",
        title_selector="h1",
        body_selector="div.detail-content.afcbc-body",
    )
    assert title == "Tiêu đề"
    assert body == ""


def test_build_collector_engine_http_and_crawl4ai():
    """factory.build_collector chọn engine theo config; offline -> MockCollector."""
    from twmkt.collectors.http_collector import HttpFirstCollector
    from twmkt.collectors.crawl4ai_collector import Crawl4aiCollector
    from twmkt.collectors.mock import MockCollector as _Mock

    base = {"sources": [{"key": "k", "name": "n", "url": "https://cafef.vn/x.chn",
                         "enabled": True, "title_selector": "h1"}]}

    http = factory.build_collector(Settings({**base, "crawl": {"engine": "http"}}), offline=False)
    assert isinstance(http, HttpFirstCollector)
    assert "https://cafef.vn/x.chn" in http.specs           # selector nạp từ config

    c4 = factory.build_collector(Settings({**base, "crawl": {"engine": "crawl4ai"}}), offline=False)
    assert isinstance(c4, Crawl4aiCollector)

    assert isinstance(factory.build_collector(Settings(base), offline=True), _Mock)


def test_source_stats_counts_kept_rejected_and_tickers():
    """_source_stats (run_pipeline): đếm crawled/kept/loại + mã (dedup, sorted), $0."""
    sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))
    import run_pipeline
    from twmkt.models import RawDocument, CleanDocument

    raw = [RawDocument("N", f"u{i}", "t", "m") for i in range(5)]
    kept = [
        CleanDocument(source="N", url="u1", title="t1", markdown="m1", tickers=["HPG", "FPT"]),
        CleanDocument(source="N", url="u2", title="t2", markdown="m2", tickers=["FPT"]),
    ]
    stat = run_pipeline._source_stats("N", "http://n", raw, kept)
    assert stat["crawled"] == 5 and stat["kept"] == 2 and stat["rejected"] == 3
    assert stat["tickers"] == ["FPT", "HPG"]        # gộp trùng + sắp xếp
    assert stat["name"] == "N" and stat["url"] == "http://n"


def test_full_ticker_whitelist_loads_and_includes_vn30():
    """Whitelist trỏ tickers_full.txt: nạp >1000 mã, VN30 vẫn nằm trong (giữ cho test)."""
    try:
        import yaml  # noqa: F401
    except ImportError:
        print("  (SKIP: chưa cài pyyaml)"); return
    from twmkt.config import load_settings
    from twmkt.curation.config import CurationConfig
    s = load_settings(os.path.join(REPO_ROOT, "config", "settings.yaml"))
    cfg = CurationConfig.from_settings(s)
    assert len(cfg.tickers) > 1000                  # danh sách đầy đủ
    assert {"FPT", "HPG", "VHM", "VIC"} <= cfg.tickers   # VN30 vẫn có mặt


def test_sheets_sources_from_rows_filters_enable():
    """sources_from_rows (Enable|Publisher|FeedURL|Type|Field|Interval|Priority):
    chỉ giữ hàng Enable bật, ánh xạ cột theo tên header, sắp theo Priority giảm
    dần, Type lạ/rỗng -> mặc định html, $0."""
    from twmkt.sheets_board import sources_from_rows, SOURCES_HEADER

    rows = [
        SOURCES_HEADER,  # Enable | Publisher | FeedURL | Type | Field | Interval | Priority
        ["TRUE", "CafeF - Doanh nghiệp", "https://cafef.vn/doanh-nghiep.chn", "html", "DoanhNghiep", "", "3"],
        ["FALSE", "CafeF - Vĩ mô", "https://cafef.vn/vi-mo-dau-tu.chn", "html", "ViMo", "", "9"],
        ["", "Tắt mặc định", "https://cafef.vn/x.chn", "html", "", "", "1"],
        ["yes", "CafeF - RSS Chứng khoán", "https://cafef.vn/thi-truong-chung-khoan.rss",
         "rss", "ChungKhoan", "60", "5"],
        ["TRUE", "Type lạ -> html", "https://x.com/y.chn", "atom", "", "", "0"],
        ["TRUE", "Thiếu url", "", "rss", "", "", "9"],   # không FeedURL -> bỏ
    ]
    srcs = sources_from_rows(rows)
    # bỏ hàng Enable tắt/rỗng + thiếu url; SẮP theo Priority giảm dần (5, 3, 0)
    assert [s.name for s in srcs] == ["CafeF - RSS Chứng khoán", "CafeF - Doanh nghiệp", "Type lạ -> html"]
    assert srcs[0].url == "https://cafef.vn/thi-truong-chung-khoan.rss"
    assert srcs[0].fetch_type == "rss" and srcs[0].field_hint == "ChungKhoan"
    assert srcs[0].interval_minutes == 60 and srcs[0].priority == 5
    assert srcs[1].fetch_type == "html" and srcs[1].priority == 3
    # Type "atom" lạ + URL không .rss -> engine_for suy ra html
    assert srcs[2].fetch_type == "html"
    assert sources_from_rows([]) == []                 # rỗng -> []


def test_sheets_context_row_column_order():
    """context_row header MỚI: Timestamp ĐẦU TIÊN, KHÔNG còn cột Use, Execute
    NGAY SAU Status. Source gộp báo khác; Status=PENDING, Execute rỗng mặc định."""
    from twmkt.sheets_board import context_row, CONTEXT_HEADER

    assert CONTEXT_HEADER == ["Timestamp", "Hot%", "Score", "Group", "Topic", "Context",
                             "Hook", "Source", "Status", "Execute", "tickers", "Notes"]
    row = context_row(title="Tiêu đề bài", hook_line="FPT: hook hấp dẫn",
                      source_url="http://u", score=5, hot_pct=42.5, topic="CoPhieu",
                      group="CoPhieu, ChinhSach", other_sources=["http://u2", "http://u3"],
                      tickers=["FPT", "HPG"], ts="2026-07-02T00:00:00+00:00")
    assert len(row) == len(CONTEXT_HEADER)
    d = dict(zip(CONTEXT_HEADER, row))
    assert d["Timestamp"] == "2026-07-02T00:00:00+00:00"
    assert d["Score"] == "5"
    assert d["Hot%"] == "42.5"
    assert d["Group"] == "CoPhieu, ChinhSach"
    assert d["Topic"] == "CoPhieu"
    assert d["Context"] == "Tiêu đề bài"
    assert d["Hook"] == "FPT: hook hấp dẫn"
    # Source gộp: url chính + '(+N báo)' + url báo khác xuống dòng (bỏ cột Sources)
    assert d["Source"] == "http://u\n(+2 báo)\nhttp://u2\nhttp://u3"
    assert "Publisher" not in d and "Field" not in d and "Sources" not in d and "Use" not in d
    assert d["Status"] == "PENDING"
    assert d["Execute"] == ""             # rỗng mặc định (tự chuyển RUN khi APPROVE)
    assert d["tickers"] == "FPT, HPG"
    assert d["Notes"] == ""

    row2 = context_row(title="T2", hook_line="H2", source_url="http://v", score=1,
                       hot_pct=1.0, status="APPROVE", execute="RUN")
    d2 = dict(zip(CONTEXT_HEADER, row2))
    assert d2["Status"] == "APPROVE" and d2["Execute"] == "RUN"


def test_context_row_and_content_row_default_timestamp_is_ddmmyyyy_no_time():
    """Timestamp mặc định (ts=None) PHẢI là DD/MM/YYYY, KHÔNG giờ:phút:giây —
    khác LOG.timestamp (vẫn ISO đầy đủ, không đổi)."""
    import re
    from twmkt.sheets_board import context_row, content_row, CONTEXT_HEADER, CONTENT_HEADER

    ddmmyyyy = re.compile(r"^\d{2}/\d{2}/\d{4}$")

    ctx_row = context_row(title="T", hook_line="H", source_url="http://u", score=1, hot_pct=1.0)
    assert ddmmyyyy.match(ctx_row[CONTEXT_HEADER.index("Timestamp")])

    con_row = content_row(context="C", type_="article", status="DONE", output="x")
    assert ddmmyyyy.match(con_row[CONTENT_HEADER.index("Timestamp")])


def test_build_format_requests_covers_features_and_is_deterministic():
    """Hàm thuần build_format_requests: đủ loại request + idempotent (xóa trước thêm)."""
    from twmkt.sheets_board import (
        build_format_requests, TabMeta, TABS,
        SOURCES_HEADER, CONTEXT_HEADER,
    )
    tabs = []
    for i, (name, header) in enumerate(TABS.items()):
        # CONTEXT có sẵn 1 banding + 3 conditional -> phải sinh request XÓA.
        if name == "CONTEXT":
            tabs.append(TabMeta(name, header, i, n_rows=5, banding_ids=[7],
                                cond_format_count=3))
        else:
            tabs.append(TabMeta(name, header, i, n_rows=3))
    reqs = build_format_requests(tabs)
    kinds = [next(iter(r)) for r in reqs]

    for k in ("updateSheetProperties", "updateDimensionProperties", "repeatCell",
              "updateBorders", "addBanding", "setDataValidation",
              "addConditionalFormatRule"):
        assert k in kinds, f"thiếu request {k}"
    # idempotent: banding cũ + rule cũ của CONTEXT bị xóa trước khi thêm lại
    # (CONTENT.cond_format_count=0 trong test này -> không sinh xóa cho CONTENT).
    assert kinds.count("deleteBanding") == 1
    assert kinds.count("deleteConditionalFormatRule") == 3
    # CONTEXT: Status(APPROVE/PENDING/REJECT=3) + Execute(RUN/DONE/FAILED/NEEDS_HUMAN=4,
    # Phase 4.9) + score + hot% => 3+4+1+1 = 9
    # CONTENT: "Approve(gate 2)"(APPROVE/PENDING/REJECT=3) => 9+3 = 12
    assert kinds.count("addConditionalFormatRule") == 12
    # checkbox: SOURCES.Enable + PROMPTS.Enable (Use đã xoá, KHÔNG còn checkbox CONTEXT)
    # dropdown: CONTEXT.Status + CONTEXT.Execute + CONTENT.Status + CONTENT."Approve(gate 2)"
    sd = [r["setDataValidation"] for r in reqs if "setDataValidation" in r]
    conds = [v["rule"]["condition"]["type"] for v in sd]
    assert conds.count("BOOLEAN") == 2 and conds.count("ONE_OF_LIST") == 4
    # determinism = idempotent theo cấu trúc
    assert build_format_requests(tabs) == reqs
    assert SOURCES_HEADER[0].lower() == "enable"
    low = [c.lower() for c in CONTEXT_HEADER]
    assert {"score", "hot%", "group", "context", "hook", "source", "status", "execute"} <= set(low)
    assert "use" not in low and low[0] == "timestamp"


def test_format_board_smoke_no_network():
    """format_board dựng + gửi batchUpdate qua fake spreadsheet, KHÔNG chạm mạng."""
    from twmkt.sheets_board import SheetsBoard, TABS

    class _FakeWS:
        def __init__(self, values): self._v = values
        def get_all_values(self): return self._v

    class _FakeSheet:
        def __init__(self, meta): self._meta = meta; self.last_body = None
        def fetch_sheet_metadata(self, params=None): return self._meta
        def batch_update(self, body): self.last_body = body; return {}

    sheets = []
    for i, name in enumerate(TABS):
        s = {"properties": {"sheetId": i, "title": name,
                            "gridProperties": {"rowCount": 1000}}}
        if name == "CONTEXT":     # có sẵn banding + rule -> nhánh idempotent
            s["bandedRanges"] = [{"bandedRangeId": 42}]
            s["conditionalFormats"] = [{}, {}]
        sheets.append(s)

    board = SheetsBoard(spreadsheet_id="SID", creds_path="creds")
    board._sh = _FakeSheet({"sheets": sheets})          # tránh _spreadsheet() -> mạng
    for name, header in TABS.items():
        board._ws[name] = _FakeWS([header])             # chỉ header

    n = board.format_board()
    body = board._sh.last_body
    assert n > 0 and body and len(body["requests"]) == n
    kinds = {next(iter(r)) for r in body["requests"]}
    assert {"updateSheetProperties", "repeatCell", "updateBorders", "addBanding",
            "setDataValidation", "addConditionalFormatRule", "deleteBanding",
            "deleteConditionalFormatRule"} <= kinds


def test_write_context_dedup_by_url():
    """write_context bỏ trùng theo url (cột Source): url đã có -> không ghi, trả False."""
    from twmkt.sheets_board import SheetsBoard, CONTEXT_HEADER, context_row

    class _FakeWS:
        def __init__(self, values): self._v = values; self.appended = []
        def get_all_values(self): return self._v
        def append_row(self, row, value_input_option=None):
            self.appended.append(row); self._v.append(row)

    board = SheetsBoard(spreadsheet_id="SID", creds_path="creds")
    existing_row = context_row(title="Bài cũ", hook_line="hook", source_url="http://u/1",
                               score=2, hot_pct=10.0, tickers=["FPT"], ts="ts")
    ws = _FakeWS([CONTEXT_HEADER, existing_row])
    board._ws["CONTEXT"] = ws

    assert board.write_context(title="Trùng", hook_line="h", url="http://u/1",
                               score=1) is False          # url đã có -> bỏ
    assert ws.appended == []
    assert board.write_context(title="Mới", hook_line="h", url="http://u/2",
                               score=1) is True            # url mới -> ghi
    source_idx = CONTEXT_HEADER.index("Source")
    assert len(ws.appended) == 1 and ws.appended[0][source_idx] == "http://u/2"


def test_sheets_settings_from_rows_and_priority_groups():
    """settings_from_rows/priority_groups_from_rows: đọc Key/Value từ tab SETTINGS, $0."""
    from twmkt.sheets_board import settings_from_rows, priority_groups_from_rows, SETTINGS_HEADER

    rows = [
        SETTINGS_HEADER,  # Key | Value | Notes
        ["PriorityGroups", "ChinhSach, ViMoVN", "ghi chú"],
        ["Khac", "x", ""],
    ]
    d = settings_from_rows(rows)
    assert d == {"PriorityGroups": "ChinhSach, ViMoVN", "Khac": "x"}
    assert priority_groups_from_rows(rows) == ["ChinhSach", "ViMoVN"]
    # thiếu khóa / rỗng -> default
    assert priority_groups_from_rows([SETTINGS_HEADER], default=["A", "B"]) == ["A", "B"]
    assert priority_groups_from_rows([]) == []


def test_prompt_versions_from_rows_filters_enable():
    from twmkt.sheets_board import prompt_versions_from_rows, PROMPTS_HEADER

    rows = [
        PROMPTS_HEADER,  # Name | Version | Enable
        ["analysis", "v2", "TRUE"],
        ["video", "v1", "FALSE"],
        ["infographic", "v1", "yes"],
    ]
    assert prompt_versions_from_rows(rows) == {"analysis": "v2", "infographic": "v1"}
    assert prompt_versions_from_rows([]) == {}
    assert prompt_versions_from_rows([["Name", "X"]]) == {}   # thiếu cột Version


def test_sheets_board_read_prompt_versions_via_fake_ws():
    from twmkt.sheets_board import SheetsBoard, PROMPTS_HEADER

    class _FakeWS:
        def __init__(self, values): self._v = values
        def get_all_values(self): return self._v

    board = SheetsBoard(spreadsheet_id="SID", creds_path="creds")
    board._ws["PROMPTS"] = _FakeWS([PROMPTS_HEADER, ["analysis", "v3", "TRUE"]])
    assert board.read_prompt_versions() == {"analysis": "v3"}


def test_prompts_read_file_and_resolve_overrides():
    import shutil
    import tempfile
    from twmkt.agents.prompts import read_prompt_file, resolve_prompts

    tmp = tempfile.mkdtemp()
    try:
        with open(f"{tmp}/analysis.v2.md", "w", encoding="utf-8") as f:
            f.write("Prompt bản v2 tùy chỉnh.")
        assert read_prompt_file("analysis", "v2", prompts_dir=tmp) == "Prompt bản v2 tùy chỉnh."
        assert read_prompt_file("analysis", "v9-khong-ton-tai", prompts_dir=tmp) is None

        defaults = {"analysis": "default analysis", "video": "default video"}
        out = resolve_prompts({"analysis": "v2", "video": "v9-khong-ton-tai"},
                              defaults, prompts_dir=tmp)
        assert out["analysis"] == "Prompt bản v2 tùy chỉnh."   # có file -> dùng file
        assert out["video"] == "default video"                 # thiếu file -> giữ default
        assert resolve_prompts({}, defaults, prompts_dir=tmp) == defaults
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_sheets_context_titles_reads_context_column():
    """context_titles(): đọc cột Context (đã đổi tên từ 'title') để chặn near-duplicate."""
    from twmkt.sheets_board import SheetsBoard, CONTEXT_HEADER, context_row

    class _FakeWS:
        def __init__(self, values): self._v = values
        def get_all_values(self): return self._v

    board = SheetsBoard(spreadsheet_id="SID", creds_path="creds")
    board._ws["CONTEXT"] = _FakeWS([
        CONTEXT_HEADER,
        context_row(title="Bài A", hook_line="h", source_url="http://u/1", score=1, hot_pct=0.0, ts="ts"),
        context_row(title="Bài B", hook_line="h", source_url="http://u/2", score=1, hot_pct=0.0, ts="ts"),
    ])
    assert board.context_titles() == ["Bài A", "Bài B"]


def test_sheets_sort_context_by_hot_noop_without_hot_column():
    """sort_context_by_hot: no-op an toàn khi thiếu cột Hot% hoặc chưa có dữ liệu."""
    from twmkt.sheets_board import SheetsBoard

    class _FakeWS:
        def __init__(self, values): self._v = values; self.sorted_with = None
        def get_all_values(self): return self._v
        def row_values(self, n): return self._v[0]
        def sort(self, *specs, range=None): self.sorted_with = (specs, range)

    board = SheetsBoard(spreadsheet_id="SID", creds_path="creds")
    ws = _FakeWS([["timestamp", "title"], ["ts", "x"]])   # không có cột Hot%
    board._ws["CONTEXT"] = ws
    board.sort_context_by_hot()
    assert ws.sorted_with is None                          # không gọi sort


# --- Retry quota 429 (call_with_retry/_RetryingProxy) + gate ensure_tabs -----
class _FakeQuotaResp:
    """Giả lập requests.Response cho gspread.exceptions.APIError (429)."""
    def __init__(self, status_code=429, retry_after=None):
        self.status_code = status_code
        self.headers = {"Retry-After": str(retry_after)} if retry_after else {}
        self.text = "quota"

    def json(self):
        return {"error": {"code": self.status_code, "message": "Quota exceeded",
                          "status": "RESOURCE_EXHAUSTED" if self.status_code == 429 else "ERR"}}


def test_call_with_retry_recovers_after_429_then_succeeds():
    """call_with_retry: 429 hai lần đầu -> retry (backoff giả lập, $0 thời gian
    thật) -> thành công lần 3, không raise."""
    import gspread
    from twmkt.sheets_board import call_with_retry

    calls = {"n": 0}
    sleeps: list[float] = []

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise gspread.exceptions.APIError(_FakeQuotaResp())
        return "ok"

    result = call_with_retry(flaky, max_attempts=5, sleep=sleeps.append)
    assert result == "ok" and calls["n"] == 3
    assert len(sleeps) == 2 and all(s > 0 for s in sleeps)   # 2 lần chờ trước khi thành công


def test_call_with_retry_raises_real_error_after_max_attempts():
    """Hết `max_attempts` lần mà vẫn 429 -> raise lỗi THẬT (không nuốt)."""
    import gspread
    from twmkt.sheets_board import call_with_retry

    calls = {"n": 0}

    def always_429():
        calls["n"] += 1
        raise gspread.exceptions.APIError(_FakeQuotaResp())

    try:
        call_with_retry(always_429, max_attempts=3, sleep=lambda s: None)
    except gspread.exceptions.APIError as e:
        assert e.code == 429
    else:
        raise AssertionError("phải raise lỗi thật sau khi hết lượt thử")
    assert calls["n"] == 3   # thử đúng max_attempts lần, không hơn


def test_call_with_retry_does_not_retry_non_429_errors():
    """Lỗi APIError KHÁC 429 (vd 404) -> raise NGAY, không retry (tránh chờ vô ích)."""
    import gspread
    from twmkt.sheets_board import call_with_retry

    calls = {"n": 0}

    def not_found():
        calls["n"] += 1
        raise gspread.exceptions.APIError(_FakeQuotaResp(status_code=404))

    try:
        call_with_retry(not_found, max_attempts=5, sleep=lambda s: None)
    except gspread.exceptions.APIError:
        pass
    else:
        raise AssertionError("phải raise")
    assert calls["n"] == 1   # không retry


def test_call_with_retry_prefers_retry_after_header():
    """Có header Retry-After -> chờ ĐÚNG giá trị đó (không dùng backoff mũ)."""
    import gspread
    from twmkt.sheets_board import call_with_retry

    def once_429_with_retry_after():
        if not once_429_with_retry_after.called:
            once_429_with_retry_after.called = True
            raise gspread.exceptions.APIError(_FakeQuotaResp(retry_after=7))
        return "ok"
    once_429_with_retry_after.called = False

    sleeps: list[float] = []
    assert call_with_retry(once_429_with_retry_after, max_attempts=3, sleep=sleeps.append) == "ok"
    assert sleeps == [7.0]


def test_backoff_delay_exponential_with_jitter_when_no_retry_after():
    """Không có Retry-After -> backoff mũ 2,4,8,16s + jitter tới 25%."""
    from twmkt.sheets_board import _backoff_delay_s

    assert _backoff_delay_s(1, None) - 2.0 == 0 or 2.0 <= _backoff_delay_s(1, None) <= 2.5
    d3 = _backoff_delay_s(3, None)
    assert 8.0 <= d3 <= 10.0        # base 8s (lần 3) + jitter tới 25%
    assert _backoff_delay_s(1, retry_after=5.0) == 5.0   # Retry-After thắng backoff


def test_retrying_proxy_forwards_and_retries_transparently():
    """_RetryingProxy: method gọi qua proxy y hệt object gốc, TỰ retry 429 —
    không cần sửa từng điểm gọi API. sleep tiêm được -> test $0 thời gian thật."""
    import gspread
    from twmkt.sheets_board import _RetryingProxy

    class _Target:
        title = "CONTEXT"   # thuộc tính thường -> trả nguyên, không bọc retry

        def __init__(self): self.calls = 0
        def append_row(self, row):
            self.calls += 1
            if self.calls < 2:
                raise gspread.exceptions.APIError(_FakeQuotaResp())
            return f"appended:{row}"

    target = _Target()
    proxy = _RetryingProxy(target, max_attempts=3, sleep=lambda s: None)
    assert proxy.title == "CONTEXT"                     # thuộc tính xuyên qua, không bọc
    assert proxy.append_row("x") == "appended:x"
    assert target.calls == 2                              # đã retry 1 lần rồi mới thành công


def test_ensure_tabs_skips_full_setup_when_headers_already_correct():
    """ensure_tabs(): header ĐÃ ĐÚNG hết -> KHÔNG gọi ensure/format nặng (chỉ 2
    lượt gọi rẻ: worksheets() + values_batch_get), trả về [] (không tạo tab mới)."""
    from twmkt.sheets_board import SheetsBoard, TABS

    class _FakeWSMeta:
        def __init__(self, title): self.title = title

    class _FakeSheet:
        def __init__(self):
            self.calls: list[str] = []
        def worksheets(self):
            self.calls.append("worksheets")
            return [_FakeWSMeta(name) for name in TABS]
        def values_batch_get(self, ranges):
            self.calls.append("values_batch_get")
            return {"valueRanges": [{"values": [header]} for header in TABS.values()]}
        def batch_update(self, body):   # KHÔNG được gọi (mới là điều cần chứng minh)
            self.calls.append("batch_update")
            return {}
        def fetch_sheet_metadata(self, params=None):
            self.calls.append("fetch_sheet_metadata")
            return {"sheets": []}

    board = SheetsBoard(spreadsheet_id="SID", creds_path="creds")
    fake = _FakeSheet()
    board._sh = fake   # tránh _spreadsheet() -> mạng (test trực tiếp _headers_need_setup)

    created = board.ensure_tabs()
    assert created == []
    assert fake.calls == ["worksheets", "values_batch_get"]   # đúng 2 lượt, KHÔNG format_board


def test_ensure_tabs_runs_full_setup_when_header_wrong():
    """Header SAI (hoặc thiếu tab) -> ensure_tabs() CHẠY đầy đủ (format_board
    được gọi, tức batch_update xuất hiện trong log lệnh gọi)."""
    from twmkt.sheets_board import SheetsBoard, TABS

    class _FakeWSMeta:
        def __init__(self, title): self.title = title

    class _FakeWS:
        def __init__(self, header): self._header = header; self.updated = None
        def row_values(self, n): return self._header
        def get_all_values(self): return [self._header]
        def update(self, rng, values, value_input_option=None): self.updated = values
        def append_rows(self, rows, value_input_option=None): pass
        def clear(self): pass

    class _FakeSheet:
        def __init__(self):
            self.calls: list[str] = []
            self._ws_by_name = {name: _FakeWS(["SAI"]) for name in TABS}
        def worksheets(self):
            self.calls.append("worksheets")
            return [_FakeWSMeta(name) for name in TABS]
        def values_batch_get(self, ranges):
            self.calls.append("values_batch_get")
            return {"valueRanges": [{"values": [["SAI"]]} for _ in TABS]}
        def worksheet(self, name):
            self.calls.append(f"worksheet:{name}")
            return self._ws_by_name[name]
        def fetch_sheet_metadata(self, params=None):
            self.calls.append("fetch_sheet_metadata")
            return {"sheets": [{"properties": {"sheetId": i, "title": name,
                                               "gridProperties": {"rowCount": 1000}}}
                               for i, name in enumerate(TABS)]}
        def batch_update(self, body):
            self.calls.append("batch_update")
            return {}

    board = SheetsBoard(spreadsheet_id="SID", creds_path="creds")
    fake = _FakeSheet()
    board._sh = fake

    board.ensure_tabs()
    assert "batch_update" in fake.calls   # header sai -> chạy full setup (format_board)


# --- curation/enrich.py: phân nhóm, điểm, near-duplicate ($0, không mạng) ---
def test_enrich_classify_matches_3_groups():
    """classify: khớp đúng nhóm theo từ khóa (không phân biệt hoa/thường), có mã -> CoPhieu."""
    from twmkt.curation.enrich import classify

    groups = {
        "ChinhSach": ["nghị định", "chính phủ"],
        "ViMoVN": ["lạm phát", "gdp"],
        "ViMoTheGioi": ["fed", "trung quốc"],
    }
    assert classify("Chính phủ ban hành Nghị định mới", [], groups=groups) == ["ChinhSach"]
    assert classify("Lạm phát và GDP quý 2", [], groups=groups) == ["ViMoVN"]
    assert classify("FED họp bàn lãi suất", [], groups=groups) == ["ViMoTheGioi"]
    # có mã -> luôn có nhãn CoPhieu (không phụ thuộc groups)
    assert classify("Tin thường", ["FPT"], groups=groups) == ["CoPhieu"]
    # không khớp gì, không mã -> Khac
    assert classify("Tin không liên quan gì", [], groups=groups) == ["Khac"]


def test_enrich_hotness_pct_increases_with_priority():
    """hotness_pct: cùng nội dung, thuộc nhóm ưu tiên hiện hành -> Hot% CAO HƠN."""
    from twmkt.curation.enrich import hotness_pct

    text, tickers, labels = "GDP tăng trưởng mạnh", ["FPT"], ["ViMoVN"]
    hot_no_priority = hotness_pct(text, tickers, labels, priority_groups=["ChinhSach"], macro_hits=2)
    hot_priority = hotness_pct(text, tickers, labels, priority_groups=["ViMoVN"], macro_hits=2)
    assert hot_priority > hot_no_priority
    assert 0 <= hot_no_priority <= 100 and 0 <= hot_priority <= 100


def test_enrich_in_priority_and_marketing_score():
    from twmkt.curation.enrich import in_priority, marketing_score

    assert in_priority(["ViMoVN"], ["ChinhSach", "ViMoVN"]) is True
    assert in_priority(["CoPhieu"], ["ChinhSach", "ViMoVN"]) is False
    assert in_priority([], ["ChinhSach"]) is False
    # mỗi mã +w_ticker, macro +w_macro/hit, tín hiệu "đáng lên bài" (%, kỷ lục...) +w_news
    s = marketing_score("Lợi nhuận tăng kỷ lục 50%", ["FPT", "HPG"], macro_hits=1,
                        w_ticker=3, w_macro=2, w_news=1)
    assert s == 2 * 3 + 1 * 2 + 2 * 1   # 2 mã, 1 macro hit, 2 tín hiệu (%, kỷ lục)


def test_enrich_is_near_duplicate_catches_variants_not_different_titles():
    """is_near_duplicate: bắt biến thể gần giống (dấu câu/khoảng trắng khác), không
    báo nhầm 2 tiêu đề khác nội dung."""
    from twmkt.curation.enrich import is_near_duplicate

    seen = ["FPT báo lãi quý tăng trưởng hai chữ số"]
    assert is_near_duplicate("FPT báo lãi quý, tăng trưởng hai chữ số!", seen) is True
    assert is_near_duplicate("HPG: Sản lượng thép phục hồi mạnh", seen) is False
    assert is_near_duplicate("", seen) is False
    assert is_near_duplicate("Bất kỳ", []) is False


# --- Mô hình thu thập 3 lớp: RSS (tầng 1) + Field/Topic + dedup chéo nguồn ---
_RSS_FIXTURE = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
<title>Kênh mẫu</title>
<item>
  <title>FPT báo lãi quý tăng trưởng hai chữ số</title>
  <link>https://cafef.vn/fpt-bao-lai-quy-188260703000001.chn</link>
  <description>&lt;a href="x"&gt;&lt;img src="y"&gt;&lt;/a&gt; Doanh thu và lợi nhuận đều tăng.</description>
  <category>Chứng khoán</category>
  <pubDate>Fri, 03 Jul 2026 16:12:00 +0700</pubDate>
</item>
<item>
  <title>HPG: Sản lượng thép phục hồi</title>
  <link>https://cafef.vn/hpg-san-luong-188260703000002.chn</link>
  <description>Sản lượng tiêu thụ thép tăng nhờ nhu cầu xây dựng.</description>
  <pubDate>Fri, 03 Jul 26 09:00:00 +0700</pubDate>
</item>
<item>
  <title>Thiếu link -> bị bỏ</title>
  <description>Không có link.</description>
</item>
</channel></rss>"""


def test_rss_parse_rss_fixture():
    """parse_rss: trích title/link/summary (bỏ thẻ HTML)/category/pubDate; bỏ
    item thiếu <link>; XML hỏng -> [] (không raise). $0, không mạng."""
    from twmkt.collectors.rss_collector import parse_rss

    items = parse_rss(_RSS_FIXTURE)
    assert len(items) == 2                              # item thiếu link bị bỏ
    a, b = items
    assert a.title == "FPT báo lãi quý tăng trưởng hai chữ số"
    assert a.link == "https://cafef.vn/fpt-bao-lai-quy-188260703000001.chn"
    assert a.summary == "Doanh thu và lợi nhuận đều tăng."   # đã bỏ thẻ <a>/<img>
    assert a.category == "Chứng khoán"
    assert a.published_at is not None and a.published_at.year == 2026
    assert b.category == ""                              # item không có <category>
    assert parse_rss("<not><valid xml") == []             # XML hỏng -> [] không raise
    assert parse_rss("") == []


def test_rss_collector_collect_maps_items_to_raw_documents():
    """RssCollector.collect: parse_rss -> RawDocument (markdown=summary, CHƯA
    fetch full bài), category_hint mang gợi ý Field. Ghi đè _fetch (thay _run_all
    không hỗ trợ fixture pytest) -> $0, không mạng."""
    from twmkt.collectors.rss_collector import RssCollector
    from twmkt.models import Source, SourceType

    c = RssCollector()
    c._fetch = lambda url: _RSS_FIXTURE   # ghi đè instance -> không cần mạng
    src = Source("CafeF - RSS Chứng khoán", "https://cafef.vn/x.rss", SourceType.NEWS, fetch_type="rss")
    docs = c.collect(src, limit=10)
    assert len(docs) == 2
    assert docs[0].source == "CafeF - RSS Chứng khoán"
    assert docs[0].markdown == "Doanh thu và lợi nhuận đều tăng."   # summary, KHÔNG phải full bài
    assert docs[0].category_hint == "Chứng khoán"
    assert c.collect(src, limit=1)[0] == docs[0]         # limit áp dụng đúng


def test_http_collector_fetch_and_extract_reuses_extract_article():
    """_fetch_and_extract (dùng chung bởi collect() và fetch_one()): tra spec
    theo source.url, gọi extract_article, dựng RawDocument. respect_robots=False
    + fake client -> $0, không mạng thật."""
    from twmkt.collectors.http_collector import HttpFirstCollector, SourceSpec
    from twmkt.models import Source, SourceType
    import re

    html = ('<html><body><h1>Tiêu đề bài</h1>'
           '<div class="detail-content afcbc-body"><p>Nội dung đầy đủ.</p></div>'
           '</body></html>')

    class _FakeResp:
        status_code = 200
        text = html

    class _FakeClient:
        def get(self, url): return _FakeResp()

    spec = SourceSpec(article_url_re=re.compile(r".chn$"))
    c = HttpFirstCollector(specs={"https://cafef.vn/x.rss": spec}, respect_robots=False)
    src = Source("CafeF - RSS X", "https://cafef.vn/x.rss", SourceType.NEWS, fetch_type="rss")
    doc = c._fetch_and_extract(_FakeClient(), src, spec, "https://cafef.vn/bai-that-123456.chn")
    assert doc is not None
    assert doc.title == "Tiêu đề bài"
    assert doc.markdown == "Nội dung đầy đủ."
    assert doc.url == "https://cafef.vn/bai-that-123456.chn"
    assert doc.source == "CafeF - RSS X"


def test_enrich_cluster_by_event_keeps_highest_priority():
    """cluster_by_event (item = dict): gộp sự kiện CHÉO NGUỒN, GIỮ báo Priority cao
    làm 'rep' (dù không xuất hiện đầu), url báo khác gộp vào 'sources'."""
    from twmkt.curation.enrich import cluster_by_event

    items = [
        # cụm FPT: bản Priority thấp xuất hiện TRƯỚC, bản cao xuất hiện SAU
        {"title": "FPT bao lai quy tang manh", "url": "http://low/fpt",
         "publisher": "CafeBiz", "priority": 3},
        {"title": "FPT bao lai quy tang manh nhe", "url": "http://high/fpt",
         "publisher": "Vietstock", "priority": 9},
        {"title": "FPT bao lai quy tang", "url": "http://mid/fpt",
         "publisher": "CafeF", "priority": 5},
        {"title": "HPG san luong thep phuc hoi", "url": "http://cafef/hpg",
         "publisher": "CafeF", "priority": 5},
    ]
    clusters = cluster_by_event(items, threshold=0.6)
    assert len(clusters) == 2
    fpt = next(c for c in clusters if "fpt" in c["rep"]["title"].lower())
    assert fpt["rep"]["url"] == "http://high/fpt" and fpt["rep"]["priority"] == 9  # GIỮ Priority cao
    assert set(fpt["sources"]) == {"http://low/fpt", "http://mid/fpt"}             # url báo khác
    hpg = next(c for c in clusters if "hpg" in c["rep"]["title"].lower())
    assert hpg["sources"] == []
    assert cluster_by_event([]) == []


class _FakeContextWS:
    """Fake worksheet CONTEXT dùng chung cho các test upsert/execute bên dưới."""
    def __init__(self, values):
        self._v = values
        self.appended: list[list[str]] = []
        self.batch_updates: list[list[dict]] = []

    def get_all_values(self): return self._v
    def row_values(self, n): return self._v[n - 1] if n - 1 < len(self._v) else []

    def append_rows(self, rows, value_input_option=None):
        self.appended.extend(rows)
        self._v.extend(rows)

    def batch_update(self, data, value_input_option=None):
        import re
        self.batch_updates.append(list(data))
        for item in data:
            m = re.match(r"([A-Z]+)(\d+)", item["range"])
            col_i = 0
            for ch in m.group(1):
                col_i = col_i * 26 + (ord(ch) - 64)
            col_i -= 1
            row_n = int(m.group(2))
            while len(self._v[row_n - 1]) <= col_i:
                self._v[row_n - 1].append("")
            self._v[row_n - 1][col_i] = item["values"][0][0]


def test_upsert_context_rows_skips_existing_url_appends_new():
    """upsert_context_rows: url ĐÃ CÓ -> bỏ qua HOÀN TOÀN (dòng cũ y nguyên,
    không tạo dòng trùng); url CHƯA CÓ -> append. Trả số dòng MỚI (không tính
    dòng bị bỏ qua)."""
    from twmkt.sheets_board import SheetsBoard, CONTEXT_HEADER, context_row

    board = SheetsBoard(spreadsheet_id="X", creds_path="Y")
    existing = context_row(title="Đã duyệt", hook_line="h", source_url="http://u/1",
                           score=5, hot_pct=10.0, status="APPROVE", execute="RUN")
    ws = _FakeContextWS([CONTEXT_HEADER, list(existing)])
    board._ws["CONTEXT"] = ws

    dup = context_row(title="Crawl lại — url trùng", hook_line="h2", source_url="http://u/1",
                      score=99, hot_pct=99.0)   # điểm/nội dung KHÁC nhưng CÙNG url
    new = context_row(title="Bài mới", hook_line="h3", source_url="http://u/2",
                      score=2, hot_pct=2.0)
    written = board.upsert_context_rows([dup, new])

    assert written == [new]                     # trả CHÍNH dòng mới (không phải chỉ đếm)
    assert len(written) == 1                    # chỉ 1 dòng MỚI được ghi
    assert len(ws._v) == 3                       # header + 1 cũ + 1 mới (KHÔNG trùng)
    assert ws._v[1] == list(existing)             # dòng cũ (APPROVE/RUN) Y NGUYÊN, không bị đè
    assert ws.appended == [new]                    # CHỈ dòng thật sự mới được append


def test_upsert_context_rows_called_twice_no_duplicate():
    """Gọi upsert_context_rows 2 LẦN với CÙNG 1 dòng (mô phỏng crawl lại) ->
    lần 2 KHÔNG tạo thêm dòng nào."""
    from twmkt.sheets_board import SheetsBoard, CONTEXT_HEADER, context_row

    board = SheetsBoard(spreadsheet_id="X", creds_path="Y")
    ws = _FakeContextWS([list(CONTEXT_HEADER)])
    board._ws["CONTEXT"] = ws

    row = context_row(title="Bài A", hook_line="h", source_url="http://u/1", score=1, hot_pct=1.0)
    r1 = board.upsert_context_rows([row])
    r2 = board.upsert_context_rows([row])          # "crawl lại" cùng url
    assert len(r1) == 1 and len(r2) == 0
    assert len(ws._v) == 2                          # header + đúng 1 dòng, KHÔNG trùng


def test_sync_approve_execute_flags_sets_run_only_for_empty_execute():
    """sync_approve_execute_flags: Status=APPROVE + Execute rỗng -> RUN. Dòng đã
    RUN/DONE hoặc Status khác APPROVE -> giữ nguyên (idempotent)."""
    from twmkt.sheets_board import SheetsBoard, CONTEXT_HEADER, context_row

    board = SheetsBoard(spreadsheet_id="X", creds_path="Y")
    fresh = context_row(title="Vừa duyệt", hook_line="h", source_url="http://u/1",
                        score=1, hot_pct=1.0, status="APPROVE", execute="")
    already_run = context_row(title="Đang chờ", hook_line="h", source_url="http://u/2",
                              score=1, hot_pct=1.0, status="APPROVE", execute="RUN")
    already_done = context_row(title="Đã xong", hook_line="h", source_url="http://u/3",
                               score=1, hot_pct=1.0, status="APPROVE", execute="DONE")
    pending = context_row(title="Chưa duyệt", hook_line="h", source_url="http://u/4",
                          score=1, hot_pct=1.0, status="PENDING", execute="")
    ws = _FakeContextWS([list(CONTEXT_HEADER), list(fresh), list(already_run),
                         list(already_done), list(pending)])
    board._ws["CONTEXT"] = ws

    changed = board.sync_approve_execute_flags()
    assert changed == 1                             # CHỈ dòng "fresh" đổi
    i_ex = [h.lower() for h in CONTEXT_HEADER].index("execute")
    assert ws._v[1][i_ex] == "RUN"                   # fresh -> RUN
    assert ws._v[2][i_ex] == "RUN"                   # already_run -> giữ nguyên
    assert ws._v[3][i_ex] == "DONE"                  # already_done -> giữ nguyên
    assert ws._v[4][i_ex] == ""                      # pending (chưa duyệt) -> vẫn rỗng

    assert board.sync_approve_execute_flags() == 0   # gọi lại -> idempotent, 0 thay đổi


def test_mark_execute_done_sets_done_for_given_rows_only():
    """mark_execute_done: CHỈ đặt DONE cho đúng số dòng truyền vào; rỗng -> no-op."""
    from twmkt.sheets_board import SheetsBoard, CONTEXT_HEADER, context_row

    board = SheetsBoard(spreadsheet_id="X", creds_path="Y")
    r1 = context_row(title="A", hook_line="h", source_url="http://u/1", score=1,
                     hot_pct=1.0, status="APPROVE", execute="RUN")
    r2 = context_row(title="B", hook_line="h", source_url="http://u/2", score=1,
                     hot_pct=1.0, status="APPROVE", execute="RUN")
    ws = _FakeContextWS([list(CONTEXT_HEADER), list(r1), list(r2)])
    board._ws["CONTEXT"] = ws

    board.mark_execute_done([2])   # chỉ dòng 2 (r1)
    i_ex = [h.lower() for h in CONTEXT_HEADER].index("execute")
    assert ws._v[1][i_ex] == "DONE"
    assert ws._v[2][i_ex] == "RUN"                   # dòng 3 (r2) KHÔNG bị đụng

    board.mark_execute_done([])    # rỗng -> no-op, không lỗi
    assert ws.batch_updates and len(ws.batch_updates) == 1   # không gọi thêm batch_update


def test_set_execute_values_writes_different_status_per_row():
    """Phase 4.9: set_execute_values ghi GIÁ TRỊ RIÊNG mỗi dòng trong CÙNG 1
    lượt (vd 1 dòng DONE, 1 dòng FAILED, 1 dòng NEEDS_HUMAN) — khác
    mark_execute_done() chỉ ghi 1 giá trị đồng loạt."""
    from twmkt.sheets_board import SheetsBoard, CONTEXT_HEADER, context_row

    board = SheetsBoard(spreadsheet_id="X", creds_path="Y")
    rows = [context_row(title=t, hook_line="h", source_url=f"http://u/{i}", score=1,
                        hot_pct=1.0, status="APPROVE", execute="RUN")
           for i, t in enumerate(("A", "B", "C"))]
    ws = _FakeContextWS([list(CONTEXT_HEADER), *[list(r) for r in rows]])
    board._ws["CONTEXT"] = ws

    board.set_execute_values({2: "DONE", 3: "FAILED", 4: "NEEDS_HUMAN"})
    i_ex = [h.lower() for h in CONTEXT_HEADER].index("execute")
    assert ws._v[1][i_ex] == "DONE"
    assert ws._v[2][i_ex] == "FAILED"
    assert ws._v[3][i_ex] == "NEEDS_HUMAN"

    board.set_execute_values({})   # rỗng -> no-op
    assert len(ws.batch_updates) == 1


def test_approved_context_from_rows_captures_execute_and_row_number():
    """approved_context_from_rows: CHỈ lấy Status=APPROVE, kèm execute + số dòng
    1-based (dùng để mark_execute_done đúng dòng)."""
    from twmkt.sheets_board import approved_context_from_rows, CONTEXT_HEADER, context_row

    rows = [
        CONTEXT_HEADER,
        context_row(title="Không duyệt", hook_line="h", source_url="http://u/1",
                   score=1, hot_pct=1.0, status="PENDING"),
        context_row(title="Duyệt rồi", hook_line="h", source_url="http://u/2",
                   score=1, hot_pct=1.0, status="APPROVE", execute="RUN"),
    ]
    out = approved_context_from_rows(rows)
    assert len(out) == 1
    assert out[0]["context"] == "Duyệt rồi"
    assert out[0]["execute"] == "RUN"
    assert out[0]["row"] == 3                        # dòng 3 trên Sheet (1=header, 2=PENDING, 3=APPROVE)


def test_migrate_rows_preserves_data_across_header_change():
    """migrate_rows: header đổi (Use xoá, Timestamp lên đầu, Execute thêm mới) ->
    dữ liệu THEO TÊN cột được giữ nguyên, cột mới lấy default, cột mất rớt tự nhiên."""
    from twmkt.sheets_board import migrate_rows

    old_header = ["Use", "Score", "Hot%", "Group", "Topic", "Context", "Hook",
                 "Source", "Status", "timestamp", "tickers", "Notes"]
    new_header = ["Timestamp", "Hot%", "Score", "Group", "Topic", "Context", "Hook",
                 "Source", "Status", "Execute", "tickers", "Notes"]
    old_row = ["FALSE", "5", "42.0", "ChinhSach", "TienTe", "Bài cũ", "hook cũ",
              "http://u", "APPROVE", "2026-01-01T00:00:00+00:00", "FPT", "ghi chú"]
    [new_row] = migrate_rows(old_header, new_header, [old_row], defaults={"Execute": ""})

    d = dict(zip(new_header, new_row))
    assert d["Timestamp"] == "2026-01-01T00:00:00+00:00"   # map đúng theo tên (đổi vị trí)
    assert d["Score"] == "5" and d["Hot%"] == "42.0"
    assert d["Context"] == "Bài cũ" and d["Hook"] == "hook cũ"
    assert d["Source"] == "http://u" and d["Status"] == "APPROVE"   # GIỮ NGUYÊN — không mất
    assert d["Execute"] == ""              # cột MỚI -> default
    assert d["tickers"] == "FPT" and d["Notes"] == "ghi chú"
    assert "Use" not in d                   # cột bị xoá -> rớt tự nhiên, không lỗi

    # Không truyền defaults -> cột mới rỗng "" (an toàn, không KeyError).
    [new_row2] = migrate_rows(old_header, new_header, [old_row])
    assert dict(zip(new_header, new_row2))["Execute"] == ""


def test_group_content_rows_groups_by_context_preserves_order():
    """group_content_rows: nhóm theo Context, GIỮ thứ tự xuất hiện trong nhóm;
    hàng Context rỗng bị bỏ qua."""
    from twmkt.sheets_board import group_content_rows, CONTENT_HEADER, content_row

    a1 = content_row(context="A", type_="article", status="DONE", output="x")
    a2 = content_row(context="A", type_="video_script", status="DONE", output="x")
    b1 = content_row(context="B", type_="infographic", status="DONE", output="x")
    empty = content_row(context="", type_="article", status="DONE", output="x")
    groups = group_content_rows(CONTENT_HEADER, [a1, b1, a2, empty])
    assert list(groups.keys()) == ["A", "B"]
    assert groups["A"] == [a1, a2]
    assert groups["B"] == [b1]


def test_regroup_content_rows_makes_same_context_contiguous():
    """regroup_content_rows: hàng CÙNG Context bị xen kẽ -> sắp lại LIỀN KỀ, giữ
    thứ tự xuất hiện đầu tiên giữa các Context và thứ tự bên trong mỗi Context."""
    from twmkt.sheets_board import regroup_content_rows, CONTENT_HEADER, content_row

    a1 = content_row(context="A", type_="infographic", status="DONE", output="x")
    b1 = content_row(context="B", type_="infographic", status="DONE", output="x")
    a2 = content_row(context="A", type_="article", status="DONE", output="x")
    a3 = content_row(context="A", type_="video_script", status="DONE", output="x")
    out = regroup_content_rows(CONTENT_HEADER, [a1, b1, a2, a3])
    assert out == [a1, a2, a3, b1]   # A liền kề (giữ thứ tự trong-nhóm), B sau


def test_content_merge_ranges_threshold_is_2_types_not_full_3():
    """content_merge_ranges: ngưỡng merge là >= 2 loại KHÁC NHAU liền kề (KHÔNG
    còn bắt buộc đủ cả 3) — Context 3 loại VÀ Context chỉ 2 loại đều được merge;
    Context chỉ 1 loại (dù nhiều dòng) thì KHÔNG."""
    from twmkt.sheets_board import content_merge_ranges, CONTENT_HEADER, content_row

    a_info = content_row(context="A", type_="infographic", status="DONE", output="x")
    a_art = content_row(context="A", type_="article", status="DONE", output="x")
    a_vid = content_row(context="A", type_="video_script", status="DONE", output="x")
    b_info = content_row(context="B", type_="infographic", status="DONE", output="x")
    b_art = content_row(context="B", type_="article", status="DONE", output="x")   # chỉ 2/3 loại -> VẪN merge
    c_info = content_row(context="C", type_="infographic", status="DONE", output="x")
    rows = [a_info, a_art, a_vid, b_info, b_art, c_info]
    ranges = content_merge_ranges(CONTENT_HEADER, rows)
    assert ranges == [(1, 4), (4, 6)]   # A (3 loại) VÀ B (2 loại) đều merge; C (1 loại) không có dải


def test_regroup_and_merge_content_reorders_and_sends_merge_requests():
    """regroup_and_merge_content: sắp lại CONTENT (Context liền kề) + gửi
    unmerge-toàn-vùng rồi mergeCells cho các chủ đề đủ 3 loại (2 cột: Timestamp,
    Context -> 2 dải merge + 2 repeatCell căn giữa, kèm 1 unmergeCells)."""
    from twmkt.sheets_board import SheetsBoard, CONTENT_HEADER, content_row

    a_info = content_row(context="A", type_="infographic", status="DONE", output="x")
    b_info = content_row(context="B", type_="infographic", status="DONE", output="x")
    a_art = content_row(context="A", type_="article", status="DONE", output="x")
    a_vid = content_row(context="A", type_="video_script", status="DONE", output="x")

    class _FakeContentWS:
        id = 7
        def __init__(self, values):
            self._v = values
            self.updated: list[tuple[str, list]] = []
        def get_all_values(self): return self._v
        def update(self, rng, values, value_input_option=None):
            self.updated.append((rng, values))
            self._v = [self._v[0]] + [list(r) for r in values]

    class _FakeSheet:
        def __init__(self): self.last_body = None
        def batch_update(self, body): self.last_body = body; return {}

    ws = _FakeContentWS([list(CONTENT_HEADER), list(a_info), list(b_info),
                         list(a_art), list(a_vid)])
    board = SheetsBoard(spreadsheet_id="X", creds_path="Y")
    board._ws["CONTENT"] = ws
    board._sh = _FakeSheet()

    n = board.regroup_and_merge_content()
    assert n == 1                                    # 1 chủ đề (A) đủ 3 loại
    assert ws._v[1:] == [a_info, a_art, a_vid, b_info]   # A liền kề (thứ tự trong-nhóm giữ), B sau

    reqs = board._sh.last_body["requests"]
    assert reqs[0] == {"unmergeCells": {"range": {
        "sheetId": 7, "startRowIndex": 1, "endRowIndex": 5,
        "startColumnIndex": 0, "endColumnIndex": len(CONTENT_HEADER)}}}
    merges = [r["mergeCells"] for r in reqs if "mergeCells" in r]
    assert len(merges) == 2                          # Timestamp + Context, 1 dải mỗi cột
    for m in merges:
        assert m["mergeType"] == "MERGE_COLUMNS"
        assert m["range"]["startRowIndex"] == 1 and m["range"]["endRowIndex"] == 4
    cols = {m["range"]["startColumnIndex"] for m in merges}
    i_ts = [h.lower() for h in CONTENT_HEADER].index("timestamp")
    i_ctx = [h.lower() for h in CONTENT_HEADER].index("context")
    assert cols == {i_ts, i_ctx}


def test_regroup_and_merge_content_noop_when_no_full_group():
    """Không chủ đề nào đủ 3 loại -> 0 dải merge, vẫn unmerge (idempotent, an
    toàn gọi lại nhiều lần) nhưng KHÔNG có request mergeCells nào."""
    from twmkt.sheets_board import SheetsBoard, CONTENT_HEADER, content_row

    a_info = content_row(context="A", type_="infographic", status="DONE", output="x")

    class _FakeContentWS:
        id = 1
        def get_all_values(self): return [list(CONTENT_HEADER), list(a_info)]
        def update(self, rng, values, value_input_option=None):
            raise AssertionError("không cần ghi lại khi thứ tự đã đúng")

    class _FakeSheet:
        def __init__(self): self.last_body = None
        def batch_update(self, body): self.last_body = body; return {}

    board = SheetsBoard(spreadsheet_id="X", creds_path="Y")
    board._ws["CONTENT"] = _FakeContentWS()
    board._sh = _FakeSheet()

    n = board.regroup_and_merge_content()
    assert n == 0
    reqs = board._sh.last_body["requests"]
    assert len(reqs) == 1 and "unmergeCells" in reqs[0]


# --- Lập lịch tự động ------------------------------------------------------
def test_schedule_parse_hhmm_and_config():
    from twmkt.schedule import parse_hhmm, ScheduleConfig

    assert parse_hhmm("08:30") == (8, 30) and parse_hhmm("0:00") == (0, 0)
    for bad in ("24:00", "8:60", "abc", "8"):
        try:
            parse_hhmm(bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"parse_hhmm phải lỗi với {bad!r}")

    cfg = ScheduleConfig.from_settings(Settings({"schedule": {
        "enabled": True, "mode": "daily", "at_times": ["08:30", "16:00"],
        "timezone": "Asia/Ho_Chi_Minh", "interval_minutes": 45, "max_runs": 2,
        "job": "run_pipeline",
    }}))
    assert cfg.enabled and cfg.mode == "daily"
    assert cfg.at_times == [(8, 30), (16, 0)] and cfg.job == "run_pipeline"
    # mode lạ -> ValueError
    try:
        ScheduleConfig(mode="hourly")
    except ValueError:
        pass
    else:
        raise AssertionError("mode không hợp lệ phải raise")


def test_schedule_config_section_isolated():
    """2 lịch (crawl + draft) đọc 2 section riêng trong CÙNG settings, không đụng nhau."""
    from twmkt.schedule import ScheduleConfig

    settings = Settings({
        "schedule": {"enabled": True, "interval_minutes": 60, "job": "review_to_sheet"},
        "schedule_draft": {"enabled": True, "interval_minutes": 30, "job": "produce_draft"},
    })
    crawl = ScheduleConfig.from_settings(settings)
    draft = ScheduleConfig.from_settings(settings, section="schedule_draft")
    assert crawl.interval_minutes == 60 and crawl.job == "review_to_sheet"
    assert draft.interval_minutes == 30 and draft.job == "produce_draft"

    # section vắng mặt -> dùng default (enabled=False), KHÔNG lỗi
    missing = ScheduleConfig.from_settings(settings, section="schedule_other")
    assert missing.enabled is False


def test_next_run_at_interval_and_daily():
    from datetime import datetime, timezone
    from twmkt.schedule import ScheduleConfig, next_run_at

    utc = timezone.utc
    itv = ScheduleConfig(mode="interval", interval_minutes=60)
    t0 = datetime(2026, 7, 3, 8, 0, tzinfo=utc)
    assert next_run_at(t0, itv) == datetime(2026, 7, 3, 9, 0, tzinfo=utc)

    daily = ScheduleConfig(mode="daily", at_times=[(8, 30), (16, 0)])
    # trước cả 2 mốc -> 08:30 hôm nay
    assert next_run_at(datetime(2026, 7, 3, 7, 0, tzinfo=utc), daily) == \
        datetime(2026, 7, 3, 8, 30, tzinfo=utc)
    # giữa 2 mốc -> 16:00 hôm nay
    assert next_run_at(datetime(2026, 7, 3, 9, 0, tzinfo=utc), daily) == \
        datetime(2026, 7, 3, 16, 0, tzinfo=utc)
    # sau cả 2 mốc -> 08:30 NGÀY MAI
    assert next_run_at(datetime(2026, 7, 3, 17, 0, tzinfo=utc), daily) == \
        datetime(2026, 7, 4, 8, 30, tzinfo=utc)


def test_scheduler_loop_uses_fake_clock_no_wait():
    from datetime import datetime, timedelta, timezone
    from twmkt.schedule import ScheduleConfig, Scheduler

    class _Clock:
        def __init__(self, start): self.t = start
        def now(self): return self.t
        def sleep(self, s): self.t += timedelta(seconds=s)

    utc = timezone.utc
    t0 = datetime(2026, 7, 3, 8, 0, tzinfo=utc)
    clock = _Clock(t0)
    calls: list[datetime] = []
    cfg = ScheduleConfig(mode="interval", interval_minutes=30, run_on_start=True,
                         max_runs=3, jitter_s=0.0)
    sched = Scheduler(lambda: calls.append(clock.now()) or "ok", cfg,
                      now_fn=clock.now, sleep_fn=clock.sleep,
                      jitter_fn=lambda a, b: 0.0, log=lambda *a: None)
    n = sched.run()
    assert n == 3
    assert calls == [t0, t0 + timedelta(minutes=30), t0 + timedelta(minutes=60)]


def test_scheduler_survives_job_error():
    from datetime import datetime, timedelta, timezone
    from twmkt.schedule import ScheduleConfig, Scheduler

    class _Clock:
        def __init__(self, start): self.t = start
        def now(self): return self.t
        def sleep(self, s): self.t += timedelta(seconds=s)

    clock = _Clock(datetime(2026, 7, 3, 8, 0, tzinfo=timezone.utc))
    n_calls = {"i": 0}

    def flaky():
        n_calls["i"] += 1
        if n_calls["i"] == 2:
            raise RuntimeError("boom")   # 1 lần lỗi KHÔNG được làm chết scheduler
        return "ok"

    cfg = ScheduleConfig(mode="interval", interval_minutes=10, run_on_start=True,
                         max_runs=3, jitter_s=0.0)
    sched = Scheduler(flaky, cfg, now_fn=clock.now, sleep_fn=clock.sleep,
                      jitter_fn=lambda a, b: 0.0, log=lambda *a: None)
    assert sched.run() == 3 and n_calls["i"] == 3


# --- SOURCES hardening + dispatch collector theo fetch_type -----------------
def test_engine_for_rss_vs_html():
    from twmkt.sheets_board import engine_for
    assert engine_for("https://cafef.vn/x.rss", "") == "rss"
    assert engine_for("https://cafebiz.vn/rss/vi-mo.rss", "") == "rss"
    assert engine_for("https://x.host/rss/foo", "") == "rss"      # '/rss' trong path
    assert engine_for("https://cafef.vn/doanh-nghiep.chn", "") == "html"
    # Type khai rõ thắng suy luận từ URL
    assert engine_for("https://x.chn", "rss") == "rss"
    assert engine_for("https://x.rss", "html") == "html"


def test_sources_from_rows_hardening_skips_bad_url():
    from twmkt.sheets_board import sources_from_rows, SOURCES_HEADER
    rows = [
        SOURCES_HEADER,  # Enable|Publisher|FeedURL|Type|Field|Interval|Priority
        ["TRUE", "CafeF RSS", "https://cafef.vn/x.rss", "", "ChungKhoan", "", "4"],
        ["TRUE", "CafeF HTML", "https://cafef.vn/doanh-nghiep.chn", "html", "DN", "", "5"],
        ["TRUE", "Rác", "not-a-url", "", "", "", ""],          # thiếu scheme -> BỎ
        ["FALSE", "Tắt", "https://x.rss", "rss", "", "", ""],  # Enable off -> BỎ
    ]
    srcs = sources_from_rows(rows)
    # chỉ 2 nguồn hợp lệ, sắp theo Priority giảm dần (html=5 trước rss=4)
    assert [s.name for s in srcs] == ["CafeF HTML", "CafeF RSS"]
    assert srcs[0].fetch_type == "html" and srcs[1].fetch_type == "rss"


def test_sources_from_rows_tolerates_old_header():
    """Header cũ (Name/url) vẫn map được (khoan dung), engine_for suy fetch_type."""
    from twmkt.sheets_board import sources_from_rows
    old = [
        ["Enable", "key", "Name", "url", "type"],
        ["TRUE", "dn", "CafeF DN", "https://cafef.vn/doanh-nghiep.chn", "html"],
        ["yes", "rss", "CafeF RSS", "https://cafef.vn/x.rss", ""],
    ]
    srcs = sources_from_rows(old)
    got = {s.name: s.fetch_type for s in srcs}
    assert got == {"CafeF DN": "html", "CafeF RSS": "rss"}


def test_build_collector_dispatch_by_fetch_type():
    from twmkt.collectors.http_collector import HttpFirstCollector
    from twmkt.collectors.mock import MockCollector
    from twmkt.collectors.rss_collector import RssCollector
    s = Settings({"crawl": {"engine": "http"}})
    rss_src = Source("a", "https://x.rss", fetch_type="rss")
    html_src = Source("b", "https://x.chn", fetch_type="html")
    # dispatch theo từng nguồn
    assert isinstance(factory.build_collector_for_source(rss_src, s), RssCollector)
    assert isinstance(factory.build_collector_for_source(html_src, s), HttpFirstCollector)
    # build_collector với source -> cũng dispatch (không còn mặc định html)
    assert isinstance(factory.build_collector(s, offline=False, source=rss_src), RssCollector)
    assert isinstance(factory.build_collector(s, offline=False, source=html_src), HttpFirstCollector)
    # offline luôn Mock (bất kể fetch_type)
    assert isinstance(factory.build_collector(s, offline=True, source=rss_src), MockCollector)


# --- Giai đoạn Production (cổng 2): APPROVED -> sản phẩm -> CONTENT ----------
def test_production_agents_produce_three_types_clean():
    """3 agent sản xuất -> article/video/infographic; article+video có disclaimer
    nên qua compliance ($0 với MockLLM)."""
    from twmkt.agents.production import all_production_agents, ProductionBrief
    from twmkt.agents.base import MockLLM
    from twmkt.models import ContentFormat
    from twmkt.guardrails import compliance

    brief = ProductionBrief(title="FPT lãi quý 2 tăng 40%", hook="FPT: lãi kỷ lục",
                            tickers=["FPT"], group="CoPhieu", topic="CoPhieu",
                            url="http://u", evidence="Doanh thu và lợi nhuận tăng.")
    drafts = [compliance.apply(a.run(brief)) for a in all_production_agents(MockLLM())]
    assert {d.fmt for d in drafts} == {
        ContentFormat.ARTICLE, ContentFormat.VIDEO_SCRIPT, ContentFormat.INFOGRAPHIC}
    assert all(d.is_clean for d in drafts)   # disclaimer/footer đầy đủ


def test_production_agent_graceful_empty_llm():
    """LÙI MƯỢT: LLM trả rỗng (thiếu khóa) -> khung tất định, vẫn có disclaimer."""
    from twmkt.agents.production import AnalysisWriterAgent, ProductionBrief
    from twmkt.guardrails import compliance

    class EmptyLLM:
        def complete(self, system, prompt): return ""

    d = compliance.apply(AnalysisWriterAgent(EmptyLLM()).run(
        ProductionBrief(title="Tiêu đề bài", hook="Hook X", tickers=["HPG"],
                        evidence="Dữ kiện quan trọng.")))
    assert d.is_clean and "Tiêu đề bài" in d.body
    assert "tự chịu trách nhiệm" in d.body.lower()


def test_domain_of_extracts_netloc():
    from twmkt.agents.production import domain_of
    assert domain_of("https://cafef.vn/abc-123.chn") == "cafef.vn"
    assert domain_of("https://www.vietstock.vn/x.htm") == "vietstock.vn"
    assert domain_of("") == "" and domain_of("khong-phai-url") == ""


def test_unsupported_numbers_flags_hallucinated_figures():
    from twmkt.agents.production import unsupported_numbers
    evidence = "Doanh thu tăng 40% trong quý 2, đạt 1.200 tỷ đồng."
    assert unsupported_numbers("Lãi tăng 40% so với cùng kỳ.", evidence) == []
    bad = unsupported_numbers("Lợi nhuận tăng 999% - kỷ lục chưa từng có.", evidence)
    assert bad and "999%" in bad[0]


def test_unsupported_numbers_accepts_vietnamese_comma_decimal_matching_evidence_period():
    """Phase 4.6 (phát hiện qua validate generalization): evidence kiểu quốc tế
    dùng dấu CHẤM thập phân ("12.61%" — dữ liệu bảng/HOSE); Writer viết đúng
    chuẩn tiếng Việt bằng dấu PHẨY ("12,61%") — PHẢI được chấp nhận (cùng 1 con
    số), KHÔNG báo nhầm "bịa số"."""
    from twmkt.agents.production import unsupported_numbers
    evidence = "Trong quý 2, Chứng khoán VPS dẫn đầu với thị phần 12.61%, giảm so với 15.32%."
    assert unsupported_numbers("VPS dẫn đầu với 12,61% thị phần, giảm so với 15,32%.", evidence) == []
    # Số THẬT SỰ không có trong evidence (dù chuẩn hoá dấu) vẫn phải bị bắt.
    bad = unsupported_numbers("Thị phần lên tới 88,88%.", evidence)
    assert bad and "88,88%" in bad[0]


def test_apply_guardrails_flags_error_on_hallucination():
    from twmkt.agents.production import apply_guardrails
    from twmkt.models import ContentDraft, ContentFormat

    evidence = "Doanh thu tăng 40% trong quý 2."
    clean = ContentDraft(fmt=ContentFormat.ARTICLE, title="t",
                         body="Doanh thu tăng 40%.\n\n_Nội dung chỉ mang tính thông tin, "
                              "không phải khuyến nghị đầu tư. Nhà đầu tư tự chịu trách nhiệm._")
    apply_guardrails(clean, evidence)
    assert clean.is_clean

    bad = ContentDraft(fmt=ContentFormat.ARTICLE, title="t",
                       body="Doanh thu tăng 500%.\n\n_Nội dung chỉ mang tính thông tin, "
                            "không phải khuyến nghị đầu tư. Nhà đầu tư tự chịu trách nhiệm._")
    apply_guardrails(bad, evidence)
    assert not bad.is_clean
    assert any("500%" in issue for issue in bad.compliance_issues)


def test_apply_guardrails_checks_background_too():
    """apply_guardrails: số liệu có trong `background` (bối cảnh Claude Code tự
    research) cũng được coi là hợp lệ, không chỉ evidence gốc."""
    from twmkt.agents.production import apply_guardrails
    from twmkt.models import ContentDraft, ContentFormat

    evidence = "Doanh thu tăng 40% trong quý 2."
    background = "Cổ phiếu giảm sàn 6,97% xuống 58.700 đồng/cổ phiếu."
    d = ContentDraft(fmt=ContentFormat.ARTICLE, title="t",
                     body="Doanh thu tăng 40%. Cổ phiếu giảm sàn 6,97%.\n\n"
                          "_Nội dung chỉ mang tính thông tin, không phải khuyến nghị đầu tư. "
                          "Nhà đầu tư tự chịu trách nhiệm._")
    apply_guardrails(d, evidence, background)
    assert d.is_clean   # 6,97% chỉ có trong background, không phải evidence -> vẫn PASS

    d2 = ContentDraft(fmt=ContentFormat.ARTICLE, title="t", body="Lãi tăng 999%.")
    apply_guardrails(d2, evidence, background)
    assert not d2.is_clean   # 999% không có ở cả 2 nguồn -> vẫn bị chặn


def test_build_content_llm_model_override_sonnet_opus():
    from twmkt import factory
    from twmkt.config import Settings
    from twmkt.agents.base import AnthropicLLM

    base_settings = Settings({"llm": {"provider": "anthropic", "content_model": "claude-sonnet-4-6"}})
    r_opus = factory.build_content_llm(base_settings, model="opus")
    assert isinstance(r_opus.base, AnthropicLLM) and r_opus.base.model == "claude-opus-4-8"
    r_sonnet = factory.build_content_llm(base_settings, model="sonnet")
    assert r_sonnet.base.model == "claude-sonnet-4-6"
    r_default = factory.build_content_llm(base_settings)
    assert r_default.base.model == "claude-sonnet-4-6"   # không truyền model -> giữ settings.yaml


# --- LLM adapter mới (Phase 1 v3): make_llm/step_model + ClaudeCodeLLM -------
def test_make_llm_mode_mock_returns_mockllm():
    from twmkt import factory
    from twmkt.agents.base import MockLLM

    llm = factory.make_llm(Settings({"llm": {"mode": "mock"}}))
    assert isinstance(llm, MockLLM)


def test_make_llm_mode_missing_defaults_to_mock():
    from twmkt import factory
    from twmkt.agents.base import MockLLM

    assert isinstance(factory.make_llm(Settings({})), MockLLM)


def test_make_llm_mode_claude_code_returns_claudecodellm():
    from twmkt import factory
    from twmkt.agents.base import ClaudeCodeLLM

    llm = factory.make_llm(Settings({"llm": {"mode": "claude_code"}}))
    assert isinstance(llm, ClaudeCodeLLM)


def test_make_llm_mode_api_does_not_crash_without_key():
    """Thiếu ANTHROPIC_API_KEY -> make_llm() vẫn dựng được (kiểm tra key hoãn tới
    complete(), không phải constructor) -> KHÔNG raise."""
    from twmkt import factory
    from twmkt.agents.base import AnthropicLLM

    llm = factory.make_llm(Settings({"llm": {"mode": "api", "content_model": "claude-sonnet-4-6"}}))
    assert isinstance(llm, AnthropicLLM) and llm.model == "claude-sonnet-4-6"


def test_make_llm_mode_unknown_raises_value_error():
    from twmkt import factory

    try:
        factory.make_llm(Settings({"llm": {"mode": "bogus"}}))
    except ValueError:
        pass
    else:
        raise AssertionError("mode lạ phải raise ValueError")


def test_step_model_reads_dotted_key_and_defaults_none():
    from twmkt import factory

    settings = Settings({"llm": {"step_models": {"writer": "claude-sonnet-4-6"}}})
    assert factory.step_model(settings, "writer") == "claude-sonnet-4-6"
    assert factory.step_model(settings, "brief") is None   # chưa khai -> None, không lỗi


def test_llmclient_complete_old_2arg_call_sites_still_work():
    """Mọi call site CŨ (Agent._ask, agents/router.py) gọi complete(system, prompt)
    KHÔNG kèm `model` — phải chạy y nguyên trên cả 3 backend (chữ ký mở rộng
    keyword-only, không phá tương thích)."""
    from twmkt.agents.base import Agent, AnthropicLLM, ClaudeCodeLLM, MockLLM
    from twmkt.agents.router import LLMRouter

    assert MockLLM().complete("sys", "prompt") != ""
    assert AnthropicLLM().complete("sys", "prompt") == ""   # thiếu key -> lùi mượt, KHÔNG raise
    cc = ClaudeCodeLLM(run_fn=lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError()))
    assert cc.complete("sys", "prompt") == ""                # thiếu binary -> lùi mượt

    # Agent._ask KHÔNG đổi -> vẫn gọi complete(sys, prompt) 2 tham số, kể cả qua LLMRouter
    # (LLMRouter.complete KHÔNG có tham số model -> nếu Agent lỡ truyền sẽ TypeError).
    agent = Agent(LLMRouter(MockLLM()))
    assert agent._ask("hỏi gì đó").startswith("[MOCK::")


def test_claude_code_llm_parses_result_field_from_json():
    from twmkt.agents.base import ClaudeCodeLLM
    import json as _json

    seen_cmd = {}

    def fake_run(cmd, **kwargs):
        seen_cmd["cmd"] = cmd
        return _FakeProc(0, _json.dumps({"is_error": False, "result": "OK"}), "")

    llm = ClaudeCodeLLM(run_fn=fake_run)
    out = llm.complete("bạn là trợ lý", "trả lời OK", model="claude-haiku-4-5-20251001")
    assert out == "OK"
    assert seen_cmd["cmd"][:3] == ["claude", "-p", "bạn là trợ lý\n\ntrả lời OK"]
    assert "--model" in seen_cmd["cmd"] and "claude-haiku-4-5-20251001" in seen_cmd["cmd"]


def test_claude_code_llm_handles_is_error_nonzero_exit_and_bad_json():
    from twmkt.agents.base import ClaudeCodeLLM
    import json as _json

    assert ClaudeCodeLLM(run_fn=lambda *a, **k: _FakeProc(
        0, _json.dumps({"is_error": True, "result": "lỗi"}), "")).complete("s", "p") == ""
    assert ClaudeCodeLLM(run_fn=lambda *a, **k: _FakeProc(1, "", "boom")).complete("s", "p") == ""
    assert ClaudeCodeLLM(run_fn=lambda *a, **k: _FakeProc(0, "khong-phai-json", "")).complete("s", "p") == ""


# --- Phase 1.5 hardening: timeout config, fail_loud, alias model -------------
def test_make_llm_claude_code_reads_timeout_from_settings():
    from twmkt import factory

    custom = factory.make_llm(Settings({"llm": {"mode": "claude_code",
                                                 "claude_code": {"timeout_s": 7}}}))
    assert custom.timeout_s == 7.0
    default = factory.make_llm(Settings({"llm": {"mode": "claude_code"}}))
    assert default.timeout_s == 120.0


def test_is_fail_loud_step_default_writer_only():
    from twmkt import factory

    assert factory.is_fail_loud_step(Settings({}), "writer") is True
    assert factory.is_fail_loud_step(Settings({}), "brief") is False
    assert factory.is_fail_loud_step(Settings({}), "router") is False
    custom = Settings({"llm": {"fail_loud_steps": ["writer", "router"]}})
    assert factory.is_fail_loud_step(custom, "router") is True
    assert factory.is_fail_loud_step(custom, "brief") is False


def test_anthropic_llm_alias_map_haiku_sonnet_opus():
    from twmkt.agents.base import AnthropicLLM

    assert AnthropicLLM._ALIASES["haiku"] == "claude-haiku-4-5-20251001"
    assert AnthropicLLM._ALIASES["sonnet"] == "claude-sonnet-4-6"
    assert AnthropicLLM._ALIASES["opus"] == "claude-opus-4-8"


def test_claude_code_llm_passes_alias_straight_through_no_mapping():
    """ClaudeCodeLLM KHÔNG map alias (khác AnthropicLLM) — CLI `claude` tự nhận
    haiku|sonnet|opus qua --model."""
    from twmkt.agents.base import ClaudeCodeLLM
    import json as _json

    seen = {}

    def fake_run(cmd, **kwargs):
        seen["cmd"] = cmd
        return _FakeProc(0, _json.dumps({"is_error": False, "result": "OK"}), "")

    ClaudeCodeLLM(run_fn=fake_run).complete("s", "p", model="sonnet")
    i = seen["cmd"].index("--model")
    assert seen["cmd"][i + 1] == "sonnet"   # nguyên văn alias, không đổi thành id


def test_fail_loud_true_raises_llm_call_error_on_failure():
    from twmkt.agents.base import AnthropicLLM, ClaudeCodeLLM, LLMCallError, MockLLM

    # AnthropicLLM: thiếu SDK/key -> fail_loud=False trả "" (như cũ), fail_loud=True raise.
    a = AnthropicLLM()
    assert a.complete("s", "p") == ""
    try:
        AnthropicLLM().complete("s", "p", fail_loud=True)
    except LLMCallError:
        pass
    else:
        raise AssertionError("fail_loud=True phải raise LLMCallError khi AnthropicLLM lỗi")

    # ClaudeCodeLLM: thiếu binary -> fail_loud=False trả "", fail_loud=True raise.
    def raise_fnf(*a, **k):
        raise FileNotFoundError()

    cc = ClaudeCodeLLM(run_fn=raise_fnf)
    assert cc.complete("s", "p") == ""
    try:
        ClaudeCodeLLM(run_fn=raise_fnf).complete("s", "p", fail_loud=True)
    except LLMCallError:
        pass
    else:
        raise AssertionError("fail_loud=True phải raise LLMCallError khi ClaudeCodeLLM lỗi")

    # is_error=true cũng phải raise khi fail_loud=True.
    import json as _json

    def fake_is_error(*a, **k):
        return _FakeProc(0, _json.dumps({"is_error": True, "result": "lỗi"}), "")

    try:
        ClaudeCodeLLM(run_fn=fake_is_error).complete("s", "p", fail_loud=True)
    except LLMCallError:
        pass
    else:
        raise AssertionError("fail_loud=True phải raise khi is_error=true")

    # MockLLM không bao giờ lỗi -> fail_loud không có tác dụng, không raise.
    assert MockLLM().complete("s", "p", fail_loud=True) != ""


class _FakeProc:
    def __init__(self, returncode, stdout, stderr):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_is_fully_produced_requires_all_three_types():
    """_is_fully_produced: CHỈ True khi CẢ 3 loại (infographic/article/video_script)
    đã có trong CONTENT (`seen`) — tín hiệu đặt Execute=DONE."""
    sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))
    import produce_from_sheet as pfs

    seen = {("Bài A", "infographic"), ("Bài A", "article")}
    assert pfs._is_fully_produced("Bài A", seen) is False   # thiếu video_script
    seen.add(("Bài A", "video_script"))
    assert pfs._is_fully_produced("Bài A", seen) is True
    assert pfs._is_fully_produced("Bài B", seen) is False   # chưa có gì


def test_produce_execute_filter_excludes_done_prevents_duplicate_content():
    """Mô phỏng ĐÚNG bộ lọc run()/run_draft() dùng: chỉ giữ execute=='RUN' —
    dòng đã DONE (chạy production lần trước) bị loại -> chạy lại KHÔNG xử lý lại,
    không sinh CONTENT trùng."""
    from twmkt.sheets_board import approved_context_from_rows, CONTEXT_HEADER, context_row

    rows = [
        CONTEXT_HEADER,
        context_row(title="Đã sản xuất xong", hook_line="h", source_url="http://u/1",
                   score=1, hot_pct=1.0, status="APPROVE", execute="DONE"),
        context_row(title="Chờ sản xuất", hook_line="h", source_url="http://u/2",
                   score=1, hot_pct=1.0, status="APPROVE", execute="RUN"),
        context_row(title="Vừa duyệt chưa sync", hook_line="h", source_url="http://u/3",
                   score=1, hot_pct=1.0, status="APPROVE", execute=""),
    ]
    approved = [a for a in approved_context_from_rows(rows) if a["execute"] == "RUN"]
    assert [a["context"] for a in approved] == ["Chờ sản xuất"]   # DONE + rỗng đều bị loại


def test_run_execute_filter_phase49_includes_failed_excludes_needs_human():
    """Phase 4.9: run() (đường gọi API thật) lọc execute in ('RUN','FAILED') —
    FAILED (lỗi tạm thời của article) TỰ ĐỘNG tái chạy; DONE/NEEDS_HUMAN/rỗng
    bị loại (NEEDS_HUMAN chờ người chủ động reset, xem sheets_board.py)."""
    from twmkt.sheets_board import approved_context_from_rows, CONTEXT_HEADER, context_row

    rows = [
        CONTEXT_HEADER,
        context_row(title="Đã xong", hook_line="h", source_url="http://u/1",
                   score=1, hot_pct=1.0, status="APPROVE", execute="DONE"),
        context_row(title="Chờ sản xuất", hook_line="h", source_url="http://u/2",
                   score=1, hot_pct=1.0, status="APPROVE", execute="RUN"),
        context_row(title="Vừa duyệt chưa sync", hook_line="h", source_url="http://u/3",
                   score=1, hot_pct=1.0, status="APPROVE", execute=""),
        context_row(title="Lỗi tạm thời lần trước", hook_line="h", source_url="http://u/4",
                   score=1, hot_pct=1.0, status="APPROVE", execute="FAILED"),
        context_row(title="Đang chờ người", hook_line="h", source_url="http://u/5",
                   score=1, hot_pct=1.0, status="APPROVE", execute="NEEDS_HUMAN"),
    ]
    approved = [a for a in approved_context_from_rows(rows) if a["execute"] in ("RUN", "FAILED")]
    assert {a["context"] for a in approved} == {"Chờ sản xuất", "Lỗi tạm thời lần trước"}


# --- Phase 4.9: cầu nối run_writer_with_retry vào produce_from_sheet.run() ---
# Fakes dùng CHUNG cho 3 kịch bản outcome (DONE/FAILED/NEEDS_HUMAN) — monkeypatch
# _open_board/make_notifier/factory.make_llm/factory.build_writer_llm/load_settings
# của MODULE produce_from_sheet -> chạy run() THẬT (không phải mô phỏng rời rạc),
# $0 tuyệt đối (không gọi mạng/CLI thật), khôi phục nguyên trạng sau mỗi test.
class _FakeProduceBoard:
    def __init__(self, approved_rows):
        self._approved = approved_rows
        self.execute_updates: dict[int, str] = {}
        self.appended_content: list[list[str]] = []
        self.merged_called = False

    def log(self, *a, **kw):
        pass

    def sync_approve_execute_flags(self):
        return 0

    def read_approved_context(self):
        return self._approved

    def read_prompt_versions(self):
        return {}

    def read_sources(self):
        return []

    def existing_content_keys(self):
        return set()

    def append_content_rows(self, rows):
        self.appended_content.extend(rows)
        return len(rows)

    def set_execute_values(self, status_by_row):
        self.execute_updates.update(status_by_row)

    def mark_execute_done(self, rows):
        self.set_execute_values({r: "DONE" for r in rows})

    def regroup_and_merge_content(self):
        self.merged_called = True
        return 0


class _FakeProduceNotifier:
    def __init__(self):
        self.events: list[tuple[str, dict]] = []

    def notify(self, event, **ctx):
        self.events.append((event, ctx))
        return True


class _EmptyRouteLLM:
    """route_llm giả cho brief+router (Phase 4.9 test) — trả rỗng cho CẢ 2 bước
    -> facts=[] (lùi mượt), router fallback S1+H3 (không quan trọng ở test này,
    trọng tâm là outcome CỦA WRITER)."""

    def complete(self, *a, **kw):
        return ""


def _run_produce_scenario(writer_llm, approved_row: dict):
    """Chạy produce_from_sheet.run() THẬT với board/notifier/route_llm/writer_llm
    giả lập qua monkeypatch — trả (result, board, notifier). Khôi phục mọi
    monkeypatch trong finally (không rò rỉ sang test khác)."""
    import tempfile
    from pathlib import Path
    sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))
    import produce_from_sheet as pfs
    from twmkt.config import Settings, load_settings as real_load_settings

    base = real_load_settings()
    data = dict(base.raw)
    data["router"] = {"decisions_path": str(Path(tempfile.mkdtemp()) / "router_decisions.json")}
    test_settings = Settings(data)

    board = _FakeProduceBoard([approved_row])
    notifier = _FakeProduceNotifier()

    orig = {
        "load_settings": pfs.load_settings, "_open_board": pfs._open_board,
        "make_notifier": pfs.make_notifier, "make_llm": pfs.factory.make_llm,
        "build_writer_llm": pfs.factory.build_writer_llm,
    }
    pfs.load_settings = lambda *a, **kw: test_settings
    pfs._open_board = lambda settings, **kw: board
    pfs.make_notifier = lambda settings: notifier
    pfs.factory.make_llm = lambda settings: _EmptyRouteLLM()
    pfs.factory.build_writer_llm = lambda settings: writer_llm
    try:
        result = pfs.run(limit=5)
    finally:
        pfs.load_settings = orig["load_settings"]
        pfs._open_board = orig["_open_board"]
        pfs.make_notifier = orig["make_notifier"]
        pfs.factory.make_llm = orig["make_llm"]
        pfs.factory.build_writer_llm = orig["build_writer_llm"]
    return result, board, notifier


def _approved_row(context: str, row: int) -> dict:
    return {"context": context, "hook": "hook gợi ý", "source": "", "tickers": [],
           "group": "", "topic": "", "execute": "RUN", "row": row}


def test_run_article_done_writes_content_marks_execute_done_and_notifies():
    """outcome=DONE: ghi CONTENT (article), Execute=DONE, notify start+draft_changed
    (+ gate2_done vì written>0). Dùng writer_llm trả JSON sạch (_clean_writer_json)."""
    class _CleanWriterLLM:
        def complete(self, system, prompt, *, model=None, fail_loud=False):
            return _clean_writer_json()

    result, board, notifier = _run_produce_scenario(
        _CleanWriterLLM(), _approved_row("Bài test 4.9 DONE", row=2))

    assert board.execute_updates.get(2) == "DONE"
    article_rows = [r for r in board.appended_content if r[2] == "article"]  # Context|Type|Status|...
    assert len(article_rows) == 1 and article_rows[0][3] == "DONE"           # Status
    events = [e for e, _ in notifier.events]
    article_events = [e for e, ctx in notifier.events if ctx.get("type") == "article"]
    assert "start" in events and "gate2_done" in events
    assert "draft_changed" in article_events and "error" not in article_events


def test_run_article_failed_marks_execute_failed_no_content_no_draft_changed():
    """outcome=FAILED (lỗi hạ tầng, hết retry): KHÔNG ghi CONTENT rác, Execute=
    FAILED (tái chạy được), notify start + retry/failed (adapter Phase 4.5) +
    error (type=article, Phase 4.9), KHÔNG draft_changed cho article (video/
    infographic vẫn xử lý bình thường qua đường cũ nên CÓ THỂ tự draft_changed
    RIÊNG — chỉ kiểm phạm vi type=article, không kiểm toàn cục)."""
    class _AlwaysRaiseLLM:
        def complete(self, system, prompt, *, model=None, fail_loud=False):
            from twmkt.agents.base import LLMCallError
            raise LLMCallError("lỗi giả lập hạ tầng")

    result, board, notifier = _run_produce_scenario(
        _AlwaysRaiseLLM(), _approved_row("Bài test 4.9 FAILED", row=3))

    assert board.execute_updates.get(3) == "FAILED"
    assert not any(r[2] == "article" for r in board.appended_content)
    events = [e for e, _ in notifier.events]
    article_events = [e for e, ctx in notifier.events if ctx.get("type") == "article"]
    assert "start" in events and "retry" in events and "failed" in events
    assert "error" in article_events and "draft_changed" not in article_events


def test_run_article_needs_human_marks_execute_needs_human_writes_error_content():
    """outcome=NEEDS_HUMAN (guardrail reject số bịa): VẪN ghi CONTENT (Status=
    ERROR, để người xem lý do), Execute=NEEDS_HUMAN (chờ người), notify error."""
    import json as _json

    class _HallucinatingLLM:
        def complete(self, system, prompt, *, model=None, fail_loud=False):
            return _json.dumps({
                "title": "Bài bịa số", "sapo": "Tóm tắt.",
                "sections": [{"heading": "Bối cảnh", "content": "Lợi nhuận tăng 999% so với cùng kỳ."}],
                "disclaimer": "Nội dung chỉ mang tính thông tin, không phải khuyến nghị đầu tư. "
                              "Nhà đầu tư tự chịu trách nhiệm với quyết định của mình.",
                "sources": [],
            }, ensure_ascii=False)

    result, board, notifier = _run_produce_scenario(
        _HallucinatingLLM(), _approved_row("Bài test 4.9 NEEDS_HUMAN", row=4))

    assert board.execute_updates.get(4) == "NEEDS_HUMAN"
    article_rows = [r for r in board.appended_content if r[2] == "article"]
    assert len(article_rows) == 1 and article_rows[0][3] == "ERROR"
    events = [e for e, _ in notifier.events]
    article_events = [e for e, ctx in notifier.events if ctx.get("type") == "article"]
    assert "start" in events and "needs_human" in events   # adapter Phase 4.5
    assert "error" in article_events and "draft_changed" not in article_events


def test_run_article_idempotent_skips_writer_when_already_in_content():
    """Idempotent: (context,'article') ĐÃ có trong CONTENT (existing_content_keys)
    -> KHÔNG gọi writer_llm lần nào (PoisonLLM raise nếu bị gọi), skip hoàn toàn."""
    sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))
    import produce_from_sheet as pfs

    class _PoisonWriterLLM:
        def complete(self, *a, **kw):
            raise AssertionError("KHÔNG được gọi writer khi article đã có trong CONTENT")

    class _BoardWithExistingArticle(_FakeProduceBoard):
        def existing_content_keys(self):
            return {("Bài đã có article", "article")}

    import tempfile
    from pathlib import Path
    from twmkt.config import Settings, load_settings as real_load_settings

    base = real_load_settings()
    data = dict(base.raw)
    data["router"] = {"decisions_path": str(Path(tempfile.mkdtemp()) / "router_decisions.json")}
    test_settings = Settings(data)
    board = _BoardWithExistingArticle([_approved_row("Bài đã có article", row=2)])
    notifier = _FakeProduceNotifier()

    orig = {
        "load_settings": pfs.load_settings, "_open_board": pfs._open_board,
        "make_notifier": pfs.make_notifier, "make_llm": pfs.factory.make_llm,
        "build_writer_llm": pfs.factory.build_writer_llm,
    }
    pfs.load_settings = lambda *a, **kw: test_settings
    pfs._open_board = lambda settings, **kw: board
    pfs.make_notifier = lambda settings: notifier
    pfs.factory.make_llm = lambda settings: _EmptyRouteLLM()
    pfs.factory.build_writer_llm = lambda settings: _PoisonWriterLLM()
    try:
        pfs.run(limit=5)   # KHÔNG raise -> PoisonLLM không hề bị gọi
    finally:
        pfs.load_settings = orig["load_settings"]
        pfs._open_board = orig["_open_board"]
        pfs.make_notifier = orig["make_notifier"]
        pfs.factory.make_llm = orig["make_llm"]
        pfs.factory.build_writer_llm = orig["build_writer_llm"]

    # article KHÔNG được ghi lại (đã có sẵn, PoisonLLM chứng minh KHÔNG bị gọi).
    assert not any(r[2] == "article" for r in board.appended_content)
    # video/infographic vẫn được xử lý bình thường (existing_content_keys chỉ có
    # article) -> lượt này sinh đủ CẢ 3 loại (article đã có từ trước + video/
    # infographic mới) -> Execute=DONE ĐÚNG theo logic cũ (_is_fully_produced),
    # KHÔNG phải vì writer chạy lại.
    assert board.execute_updates.get(2) == "DONE"


def test_prompt_md_requires_research_before_writing():
    """_prompt_md: PHẢI yêu cầu research bối cảnh mở rộng (WebSearch) trước khi
    viết, và hướng dẫn ghi vào <slug>.background.txt (theo yêu cầu 'signature')."""
    sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))
    import produce_from_sheet as pfs

    md = pfs._prompt_md("slug-x", "article", "USER PROMPT")
    assert "research" in md.lower() or "Research" in md
    assert "slug-x.background.txt" in md
    assert "WebSearch" in md or "WebFetch" in md


def test_analysis_agent_parses_llm_json_schema():
    """AnalysisWriterAgent: LLM trả JSON đúng schema -> body dựng từ sections thật,
    kèm 'Nguồn: <domain>' TẤT ĐỊNH (không phụ thuộc LLM có nhớ ghi)."""
    from twmkt.agents.production import AnalysisWriterAgent, ProductionBrief
    import json as _json

    class JsonLLM:
        def complete(self, system, prompt):
            return _json.dumps({
                "title": "FPT lãi kỷ lục", "sapo": "Tóm tắt ngắn.",
                "sections": [{"heading": "Bối cảnh", "content": "Doanh thu tăng 40%."}],
                "disclaimer": "Nội dung chỉ mang tính thông tin, không phải khuyến nghị "
                              "đầu tư. Nhà đầu tư tự chịu trách nhiệm với quyết định của mình.",
                "sources": ["http://other"],
            }, ensure_ascii=False)

    brief = ProductionBrief(title="FPT báo lãi", hook="FPT: lãi kỷ lục", tickers=["FPT"],
                            url="https://cafef.vn/fpt.chn", evidence="Doanh thu tăng 40%.")
    d = AnalysisWriterAgent(JsonLLM()).run(brief)
    assert d.title == "FPT lãi kỷ lục"
    assert "Bối cảnh" in d.body and "Doanh thu tăng 40%." in d.body
    assert "Nguồn: cafef.vn" in d.body
    assert "Xem thêm: http://other" in d.body


def test_video_agent_parses_llm_json_schema():
    from twmkt.agents.production import VideoScriptAgent, ProductionBrief
    import json as _json

    class JsonLLM:
        def complete(self, system, prompt):
            return _json.dumps({
                "title": "HPG hook", "duration_sec": 45,
                "scenes": [{"t": "0-3s", "voiceover": "HPG lãi tăng mạnh",
                           "on_screen_text": "HPG +40%", "visual_hint": "biểu đồ"}],
                "cta": "CTA riêng", "disclaimer": "Nội dung chỉ mang tính thông tin.",
            }, ensure_ascii=False)

    brief = ProductionBrief(title="HPG báo lãi", tickers=["HPG"], evidence="x")
    d = VideoScriptAgent(JsonLLM()).run(brief)
    assert "HPG lãi tăng mạnh" in d.body and "HPG +40%" in d.body and "biểu đồ" in d.body
    assert "CTA riêng" in d.body


def test_infographic_agent_extracts_stats_from_evidence_deterministic():
    from twmkt.agents.production import InfographicSpecAgent, ProductionBrief
    import json as _json

    agent = InfographicSpecAgent(None)   # KHÔNG cần llm -> tất định
    assert agent.uses_llm is False
    brief = ProductionBrief(title="t", hook="h", tickers=["FPT"],
                            url="https://cafef.vn/x.chn",
                            evidence="Doanh thu tăng 40%, đạt 1.200 tỷ đồng, kỷ lục.")
    d = agent.run(brief)
    spec = _json.loads(d.body)
    assert spec["footer"]["source"] == "cafef.vn"
    assert len(spec["stats"]) >= 2
    assert all(s["value"].lower() in brief.evidence.lower() for s in spec["stats"])


# --- Phase 2: Research/Brief -> facts[] có nhãn (agents/brief.py) -----------
_SSI_EVIDENCE = (
    "Trong báo cáo chiến lược nửa cuối 2026, SSI Research đồng thời đưa ra hai thông điệp "
    "tưởng như trái ngược. Một mặt cảnh báo lạm phát có xu hướng tăng và nhập siêu đang mở "
    "rộng, trong khi GDP 6 tháng đầu năm tăng tới 8,18%, mức cao nhất nhiều năm. "
    "Tuy nhiên SSI vẫn lựa chọn 8 cổ phiếu có triển vọng tích cực. "
    "Hòa Phát hưởng lợi từ Dung Quất 2 và phòng vệ thương mại HRC."
)


def test_verify_fact_in_evidence_finds_sentence_or_none():
    from twmkt.agents.brief import verify_fact_in_evidence

    evidence = "Doanh thu tăng 40%. Lợi nhuận đạt 1.200 tỷ đồng."
    assert verify_fact_in_evidence("40%", evidence) == "Doanh thu tăng 40%."
    assert verify_fact_in_evidence("99%", evidence) is None   # không có -> None
    assert verify_fact_in_evidence("", evidence) is None


def test_verify_fact_in_evidence_rejects_short_value_lodged_inside_longer_number():
    """Bug thật phát hiện qua round-trip: value NGẮN ("8") KHÔNG được khớp nhầm
    vào bên trong 1 số dài hơn ("8,18%") — phải đợi tới câu có "8" ĐỨNG RIÊNG."""
    from twmkt.agents.brief import verify_fact_in_evidence

    evidence = ("GDP 6 tháng đầu năm tăng tới 8,18%, mức cao nhất nhiều năm. "
                "Tuy nhiên SSI vẫn lựa chọn 8 cổ phiếu có triển vọng tích cực.")
    sent = verify_fact_in_evidence("8", evidence)
    assert sent is not None and sent.startswith("Tuy nhiên")   # KHÔNG phải câu GDP
    assert verify_fact_in_evidence("8,18%", evidence).startswith("GDP")


def test_facts_from_llm_output_reassembles_value_when_llm_splits_unit():
    """Bug thật phát hiện qua round-trip: LLM đôi khi tách unit RIÊNG
    ("value":"8,18","unit":"%") thay vì dính liền ("8,18%"). value trơ "8,18"
    đứng ngay trước "%" sẽ bị luật biên chặn (đúng, tránh khớp nhầm phần thập
    phân) -> phải thử ghép lại "value+unit" trước khi kết luận bịa."""
    from twmkt.agents.brief import facts_from_llm_output
    import json as _json

    raw = _json.dumps({"facts": [
        {"value": "8,18", "label": "GDP 6 tháng đầu năm 2026", "unit": "%", "raw": "8,18%"},
    ]}, ensure_ascii=False)
    facts = facts_from_llm_output(raw, _SSI_EVIDENCE)
    assert len(facts) == 1
    assert facts[0].value == "8,18" and facts[0].unit == "%"
    assert "8,18%" in facts[0].source


def test_facts_from_llm_output_labels_meaningful_and_drops_hallucinated():
    """Bài SSI: nhãn phải CÓ NGHĨA (không còn 'Số liệu N'); fact bịa (value
    không có trong evidence) PHẢI bị loại."""
    from twmkt.agents.brief import facts_from_llm_output
    import json as _json

    raw = _json.dumps({"facts": [
        {"value": "8,18%", "label": "GDP 6 tháng đầu năm 2026", "unit": "%", "raw": "8,18%"},
        {"value": "8 cổ phiếu", "label": "Số cổ phiếu SSI khuyến nghị triển vọng tích cực", "unit": None,
         "raw": "8 cổ phiếu"},
        {"value": "15%", "label": "Biên lợi nhuận bịa (không có trong bài)", "unit": "%", "raw": "15%"},
    ]}, ensure_ascii=False)

    facts = facts_from_llm_output(raw, _SSI_EVIDENCE)
    values = {f.value for f in facts}
    assert values == {"8,18%", "8 cổ phiếu"}          # "15%" bịa -> loại
    assert not any(f.label.startswith("Số liệu") for f in facts)   # KHÔNG còn nhãn vô nghĩa
    gdp = next(f for f in facts if f.value == "8,18%")
    assert gdp.label == "GDP 6 tháng đầu năm 2026" and gdp.unit == "%"
    assert "8,18%" in gdp.source and "GDP" in gdp.source   # source = câu evidence gốc


def test_facts_from_llm_output_empty_or_bad_json_returns_empty_list():
    from twmkt.agents.brief import facts_from_llm_output

    assert facts_from_llm_output("", _SSI_EVIDENCE) == []
    assert facts_from_llm_output("không phải JSON", _SSI_EVIDENCE) == []
    assert facts_from_llm_output('{"facts": []}', _SSI_EVIDENCE) == []


def test_run_brief_passes_model_and_verifies_output():
    """Dùng fake LLM (không gọi CLI/API thật) mô phỏng haiku trả JSON — kiểm
    model truyền đúng qua step_model + facts verify được."""
    from twmkt.agents.brief import run_brief
    import json as _json

    class _FakeBriefLLM:
        def complete(self, system, prompt, *, model=None, fail_loud=False):
            assert model == "haiku" and fail_loud is False
            return _json.dumps({"facts": [
                {"value": "8,18%", "label": "GDP 6 tháng đầu năm 2026", "unit": "%", "raw": "8,18%"}]})

    facts = run_brief(_FakeBriefLLM(), _SSI_EVIDENCE, model="haiku")
    assert len(facts) == 1
    assert facts[0].value == "8,18%" and facts[0].label == "GDP 6 tháng đầu năm 2026"


def test_run_brief_degrades_to_empty_list_on_mockllm_or_empty_output():
    """Bước 'brief' là bước PHỤ -> KHÔNG fail_loud -> lỗi/rỗng LÙI MƯỢT về []."""
    from twmkt.agents.brief import run_brief
    from twmkt.agents.base import MockLLM

    assert run_brief(MockLLM(), _SSI_EVIDENCE) == []   # MockLLM không trả JSON thật -> []

    class _EmptyLLM:
        def complete(self, *a, **k):
            return ""

    assert run_brief(_EmptyLLM(), _SSI_EVIDENCE) == []


def test_production_brief_facts_field_defaults_empty_and_independent_per_instance():
    from twmkt.agents.production import ProductionBrief
    from twmkt.models import Fact

    b1 = ProductionBrief(title="a")
    b2 = ProductionBrief(title="b")
    assert b1.facts == [] and b2.facts == []
    b1.facts.append(Fact(value="1%", label="x"))
    assert b2.facts == []   # default_factory -> KHÔNG chia sẻ list giữa instance


# --- Phase 2.5: siết recall brief (taxonomy fact mở rộng + Fact.kind) -------
def test_fact_kind_defaults_to_other_and_kinds_constant():
    from twmkt.models import FACT_KINDS, Fact

    assert Fact(value="1%", label="x").kind == "other"
    assert set(FACT_KINDS) == {"percent", "money", "count", "growth",
                               "date", "ranking", "target", "other"}


def test_facts_from_llm_output_parses_kind_and_falls_back_to_other():
    from twmkt.agents.brief import facts_from_llm_output
    import json as _json

    raw = _json.dumps({"facts": [
        {"value": "8", "label": "Số cổ phiếu SSI khuyến nghị", "unit": None, "kind": "count",
         "raw": "8 cổ phiếu"},
        {"value": "8,18%", "label": "GDP 6T/2026", "kind": "percent", "raw": "8,18%"},
        {"value": "8 cổ phiếu", "label": "Nhãn không kind hợp lệ", "kind": "khong-ton-tai",
         "raw": "8 cổ phiếu"},
    ]}, ensure_ascii=False)
    facts = facts_from_llm_output(raw, _SSI_EVIDENCE)
    by_value = {f.value: f for f in facts}
    assert by_value["8"].kind == "count"
    assert by_value["8,18%"].kind == "percent"
    assert by_value["8 cổ phiếu"].kind == "other"   # kind lạ -> "other", KHÔNG loại fact


def test_facts_from_llm_output_attributes_count_fact_to_correct_sentence_not_percent():
    """Yêu cầu Phase 2.5: evidence có CẢ '8 cổ phiếu' lẫn '8,18%' -> fact
    value='8' kind=count PHẢI gán source về câu '8 cổ phiếu', KHÔNG về câu
    '8,18%' (dù cả 2 câu đều chứa ký tự '8')."""
    from twmkt.agents.brief import facts_from_llm_output
    import json as _json

    raw = _json.dumps({"facts": [
        {"value": "8", "label": "Số cổ phiếu SSI khuyến nghị", "unit": None, "kind": "count",
         "raw": "8 cổ phiếu"},
    ]}, ensure_ascii=False)
    facts = facts_from_llm_output(raw, _SSI_EVIDENCE)
    assert len(facts) == 1
    assert facts[0].kind == "count"
    assert facts[0].source.startswith("Tuy nhiên SSI vẫn lựa chọn 8 cổ phiếu")
    assert "8,18%" not in facts[0].source


# --- Phase 4.8 Mục C: số CANONICAL (agents/_numeric.py + guardrail) ---------
def test_parse_vn_decimal_handles_vn_and_international_and_mixed_separators():
    from twmkt.agents._numeric import parse_vn_decimal

    assert parse_vn_decimal("8,18") == 8.18            # chỉ ',' -> thập phân (VN)
    assert parse_vn_decimal("1.200") == 1200            # chỉ '.', 3 chữ số sau -> nghìn (VN)
    assert parse_vn_decimal("12.61") == 12.61           # chỉ '.', 2 chữ số sau -> thập phân (fix 1)
    assert parse_vn_decimal("4.072,69") == 4072.69       # cả 2 dấu, ',' sau cùng -> thập phân (VN)
    assert parse_vn_decimal("4,072.69") == 4072.69       # cả 2 dấu, '.' sau cùng -> thập phân (quốc tế)
    assert parse_vn_decimal("600") == 600
    assert parse_vn_decimal("") is None
    assert parse_vn_decimal("abc") is None


def test_parse_magnitude_token_scales_by_unit_word():
    from twmkt.agents._numeric import parse_magnitude_token

    assert parse_magnitude_token("600 tỷ") == 600e9
    assert parse_magnitude_token("585tỷ đồng") == 585e9
    assert parse_magnitude_token("1.200 tỷ đồng") == 1200e9
    assert parse_magnitude_token("2 nghìn tỷ") == 2e12
    assert parse_magnitude_token("94 triệuUSD") == 94e6
    assert parse_magnitude_token("12,61%") == 12.61
    assert parse_magnitude_token("12.61%") == 12.61     # fix 1: cùng giá trị dù khác dấu thập phân
    assert parse_magnitude_token("") is None


def test_has_approx_word_detects_common_hedge_words():
    from twmkt.agents._numeric import has_approx_word

    assert has_approx_word("bán ròng gần 600 tỷ đồng") is True
    assert has_approx_word("khoảng 40% nhu cầu") is True
    assert has_approx_word("đúng 585 tỷ đồng") is False
    assert has_approx_word("") is False


def test_facts_from_llm_output_computes_canonical_value_and_approx_flag():
    """Mục C: Brief (AI) trả thêm raw/approx; CODE (KHÔNG phải AI) tính
    canonical_value từ value+unit đã verify."""
    from twmkt.agents.brief import facts_from_llm_output
    import json as _json

    evidence = "Khối ngoại bán ròng toàn thị trường 585 tỷ đồng trong phiên hôm nay."
    raw = _json.dumps({"facts": [
        {"value": "585", "label": "Khối ngoại bán ròng toàn thị trường", "unit": "tỷ đồng",
         "kind": "money", "raw": "585 tỷ đồng", "approx": False},
    ]}, ensure_ascii=False)
    facts = facts_from_llm_output(raw, evidence)
    assert len(facts) == 1
    f = facts[0]
    assert f.raw == "585 tỷ đồng"
    assert f.canonical_value == 585e9
    assert f.approx is False


def test_facts_from_llm_output_drops_fact_when_raw_not_substring_of_evidence():
    """(test 4, Mục C) raw KHÔNG phải substring THẬT của evidence -> LOẠI fact
    NGAY, dù value/unit riêng lẻ có verify được (chống AI paraphrase/bịa cụm)."""
    from twmkt.agents.brief import facts_from_llm_output
    import json as _json

    evidence = "Khối ngoại bán ròng toàn thị trường 585 tỷ đồng trong phiên hôm nay."
    raw = _json.dumps({"facts": [
        {"value": "585", "label": "Khối ngoại bán ròng", "unit": "tỷ đồng",
         "raw": "khoảng 585 tỷ đồng chẵn"},   # cụm bịa, KHÔNG xuất hiện y hệt trong evidence
    ]}, ensure_ascii=False)
    assert facts_from_llm_output(raw, evidence) == []


def test_facts_from_llm_output_approx_flag_true_when_raw_has_hedge_word_even_if_ai_forgets():
    """approx = cờ AI trả HOẶC code tự dò trong raw (an toàn kép, không tin mù AI)."""
    from twmkt.agents.brief import facts_from_llm_output
    import json as _json

    evidence = "Nhu cầu điện tại Havana chỉ được đáp ứng khoảng 1% trong ngày sự cố."
    raw = _json.dumps({"facts": [
        {"value": "1", "label": "Phần trăm nhu cầu điện đáp ứng tại Havana", "unit": "%",
         "raw": "khoảng 1%", "approx": False},   # AI QUÊN đánh dấu approx=True
    ]}, ensure_ascii=False)
    facts = facts_from_llm_output(raw, evidence)
    assert len(facts) == 1 and facts[0].approx is True   # code tự dò "khoảng" -> ép True


def test_fact_new_fields_default_backward_compatible():
    from twmkt.models import Fact

    f = Fact(value="1%", label="x")
    assert f.raw == "" and f.canonical_value is None and f.approx is False


# --- Phase 4.8 Mục C: guardrail canonical (agents/production.py) -----------
def _fact(canonical, approx=False):
    from twmkt.models import Fact
    return Fact(value="x", label="y", canonical_value=canonical, approx=approx)


def test_unsupported_numbers_accepts_approx_rounding_within_tolerance_when_body_hedges():
    """(test 1, Mục C) 'gần 600 tỷ' trong bài, evidence chỉ có '585 tỷ' -> fact
    canonical=585e9 + số trong bài đi kèm từ xấp xỉ ('gần') -> is_clean (KHÔNG
    chặn oan, đúng bug false-positive Phase 4.7 'khối ngoại')."""
    from twmkt.agents.production import unsupported_numbers

    body = "Khối ngoại bán ròng gần 600 tỷ đồng trong phiên hôm nay."
    evidence = "Khối ngoại bán ròng 585 tỷ đồng trong phiên hôm nay."
    facts = [_fact(585e9)]
    assert unsupported_numbers(body, evidence, facts) == []


def test_unsupported_numbers_still_flags_exact_decimal_mismatch_without_hedge_word():
    """(test 5, Mục C) '855 tỷ' khi evidence/canonical chỉ có 585 tỷ (lệch
    ~46%, KHÔNG có từ xấp xỉ) -> vẫn bị chặn, KHÔNG nhầm là làm tròn hợp lý."""
    from twmkt.agents.production import unsupported_numbers

    body = "Khối ngoại bán ròng 855 tỷ đồng trong phiên hôm nay."
    evidence = "Khối ngoại bán ròng 585 tỷ đồng trong phiên hôm nay."
    facts = [_fact(585e9)]
    bad = unsupported_numbers(body, evidence, facts)
    assert any("855" in b for b in bad)


def test_unsupported_numbers_flags_number_with_no_matching_canonical_fact():
    """(test 3, Mục C) '999 tỷ' bịa hoàn toàn, không khớp evidence lẫn canonical
    nào trong facts[] -> vẫn bị chặn (guardrail chặn số bịa tuyệt đối)."""
    from twmkt.agents.production import unsupported_numbers

    body = "Lợi nhuận tăng vọt lên 999 tỷ đồng."
    evidence = "Khối ngoại bán ròng 585 tỷ đồng trong phiên hôm nay."
    facts = [_fact(585e9)]
    bad = unsupported_numbers(body, evidence, facts)
    assert any("999" in b for b in bad)


def test_unsupported_numbers_decimal_separator_regression_still_clean_with_facts_param():
    """(test 2, Mục C) Không regress fix 1: '12,61%' viết trong bài, evidence
    '12.61%' -> vẫn is_clean dù giờ có truyền thêm `facts` (tham số optional)."""
    from twmkt.agents.production import unsupported_numbers

    body = "Tỷ suất lợi nhuận đạt 12,61% trong quý này."
    evidence = "Tỷ suất lợi nhuận đạt 12.61% trong quý này (dữ liệu bảng HOSE)."
    assert unsupported_numbers(body, evidence, facts=[]) == []
    assert unsupported_numbers(body, evidence) == []   # facts mặc định None -> vẫn hoạt động như cũ


def test_unsupported_numbers_exact_tolerance_zero_rejects_rounding_without_hedge_word():
    """Số trong bài KHÔNG đi kèm từ xấp xỉ -> dung sai mặc định = 0 (khớp
    CHÍNH XÁC), dù lệch nhỏ (600 vs 585, ~2.6%) vẫn bị chặn — 5% CHỈ áp dụng
    khi có từ xấp xỉ ngay trước số (khác test 1 ở trên)."""
    from twmkt.agents.production import unsupported_numbers

    body = "Khối ngoại bán ròng 600 tỷ đồng trong phiên hôm nay."   # KHÔNG có "gần"/"khoảng"
    evidence = "Khối ngoại bán ròng 585 tỷ đồng trong phiên hôm nay."
    facts = [_fact(585e9)]
    bad = unsupported_numbers(body, evidence, facts)
    assert any("600" in b for b in bad)


def test_apply_guardrails_threads_facts_and_tolerance_end_to_end():
    from twmkt.agents.production import apply_guardrails
    from twmkt.models import ContentDraft, ContentFormat

    body = ("# Bài test\n\nKhối ngoại bán ròng gần 600 tỷ đồng.\n\n"
            "_Nội dung chỉ mang tính thông tin, không phải khuyến nghị đầu tư._")
    draft = ContentDraft(fmt=ContentFormat.ARTICLE, title="t", body=body)
    evidence = "Khối ngoại bán ròng 585 tỷ đồng trong phiên hôm nay."
    draft = apply_guardrails(draft, evidence, "", [_fact(585e9)])
    assert draft.is_clean, draft.compliance_issues


# --- Phase 3: StructureRouter (agents/structure_router.py) ------------------
def test_route_from_llm_output_valid_schema_parses_correctly():
    from twmkt.agents.structure_router import route_from_llm_output
    import json as _json

    raw = _json.dumps({
        "content_type": "article", "structure": "S3", "hook": "H1",
        "secondary_structure": None,
        "rationale": "Nhiều dữ kiện rời dồn về 1 xu hướng chung ở cuối bài.",
        "signals": {"has_genuine_paradox": False, "drivers": ["A", "B"], "has_central_thesis": False},
    }, ensure_ascii=False)
    d = route_from_llm_output(raw)
    assert d.content_type == "article" and d.structure == "S3" and d.hook == "H1"
    assert d.secondary_structure is None and d.fallback is False
    assert d.signals == {"has_genuine_paradox": False, "residual_tension": None,
                         "drivers": ["A", "B"], "driver_count": 2, "has_central_thesis": False}
    assert "xu hướng" in d.rationale


def test_route_from_llm_output_bad_json_falls_back_to_s1_h3():
    from twmkt.agents.structure_router import route_from_llm_output

    for bad in ("", "không phải JSON", "```\nvăn bản thường\n```"):
        d = route_from_llm_output(bad)
        assert d.structure == "S1" and d.hook == "H3" and d.fallback is True


def test_route_from_llm_output_rejects_s5_without_genuine_paradox():
    """Luật: S5 CẤM làm mặc định/không chắc — has_genuine_paradox=false thì
    dù LLM có chọn S5, code PHẢI ép fallback (không tin mù prompt)."""
    from twmkt.agents.structure_router import route_from_llm_output
    import json as _json

    raw = _json.dumps({
        "content_type": "article", "structure": "S5", "hook": "H1",
        "secondary_structure": None, "rationale": "Có vẻ nghịch lý.",
        "signals": {"has_genuine_paradox": False, "drivers": [], "has_central_thesis": True},
    }, ensure_ascii=False)
    d = route_from_llm_output(raw)
    assert d.structure != "S5"
    assert d.structure == "S1" and d.hook == "H3" and d.fallback is True


def test_route_from_llm_output_allows_s5_when_genuine_paradox_true():
    """S5 hợp lệ khi has_genuine_paradox=true KÈM residual_tension (Phase 3.6 —
    thiếu residual_tension thì claim paradox không đứng vững, xem test khác)."""
    from twmkt.agents.structure_router import route_from_llm_output
    import json as _json

    raw = _json.dumps({
        "content_type": "article", "structure": "S5", "hook": "H1",
        "secondary_structure": None, "rationale": "2 tín hiệu thật sự mâu thuẫn.",
        "signals": {"has_genuine_paradox": True,
                   "residual_tension": "Vẫn không rõ ai sẽ đỡ khi rủi ro thành hiện thực.",
                   "drivers": [], "has_central_thesis": True},
    }, ensure_ascii=False)
    d = route_from_llm_output(raw)
    assert d.structure == "S5" and d.fallback is False
    assert d.signals["residual_tension"] == "Vẫn không rõ ai sẽ đỡ khi rủi ro thành hiện thực."


def test_route_from_llm_output_paradox_claim_without_residual_tension_forced_false():
    """Phase 3.6: has_genuine_paradox=true mà residual_tension=null -> claim
    KHÔNG hợp lệ, CODE tự ép về false (kể cả khi structure không phải S5, vẫn
    phải ép — bất hợp lệ là bất hợp lệ, không phụ thuộc structure nào)."""
    from twmkt.agents.structure_router import route_from_llm_output
    import json as _json

    raw = _json.dumps({
        "content_type": "article", "structure": "S1", "hook": "H3",
        "secondary_structure": None, "rationale": "Luận điểm gọn, không còn vướng gì.",
        "signals": {"has_genuine_paradox": True, "residual_tension": None,
                   "drivers": [], "has_central_thesis": True},
    }, ensure_ascii=False)
    d = route_from_llm_output(raw)
    assert d.signals["has_genuine_paradox"] is False
    assert d.signals["residual_tension"] is None
    assert d.fallback is False   # S1 không cần paradox -> không cần fallback cả quyết định


def test_route_from_llm_output_s5_with_paradox_but_no_residual_tension_falls_back():
    """Phase 3.6, mục (i): input 'mâu thuẫn đã tan hết' (LLM claim S5+paradox
    nhưng residual_tension=null) -> KHÔNG được ra S5 — code ép has_genuine_
    paradox=false TRƯỚC, rồi ràng buộc S5-cần-paradox-thật fallback như thường."""
    from twmkt.agents.structure_router import route_from_llm_output
    import json as _json

    raw = _json.dumps({
        "content_type": "article", "structure": "S5", "hook": "H1",
        "secondary_structure": None,
        "rationale": "Nghe có vẻ mâu thuẫn nhưng giải thích xong thì gọn, không còn gì vướng.",
        "signals": {"has_genuine_paradox": True, "residual_tension": None,
                   "drivers": [], "has_central_thesis": True},
    }, ensure_ascii=False)
    d = route_from_llm_output(raw)
    assert d.structure != "S5"
    assert d.structure == "S1" and d.hook == "H3" and d.fallback is True


def test_route_from_llm_output_forces_s5_when_paradox_effective_even_if_llm_chose_other_structure():
    """Phase 4.8-B2: reproduce đúng ca "tự mâu thuẫn" phát hiện qua probe Ví dụ
    A ở báo cáo Phase 4.8 — LLM báo has_genuine_paradox=true KÈM residual_tension
    hợp lệ (paradox EFFECTIVE=True) nhưng lại tự chọn structure="S1" (rationale
    "khép sạch"). CODE PHẢI ép structure=S5, GHI ĐÈ lựa chọn tự mâu thuẫn của
    LLM (chiều NGƯỢC LẠI của luật S5 cũ, trước 4.8-B2 còn thiếu)."""
    from twmkt.agents.structure_router import route_from_llm_output
    import json as _json

    raw = _json.dumps({
        "content_type": "article", "structure": "S1", "hook": "H2",
        "secondary_structure": None,
        "rationale": "Logic khép lại sạch thành 1 thuyết minh nhân quả, không phải nghịch lý mở.",
        "signals": {"has_genuine_paradox": True,
                   "residual_tension": "Rủi ro hệ thống dồn về vài người vay lớn nhất, ai đỡ nếu vỡ.",
                   "drivers": [], "has_central_thesis": True},
    }, ensure_ascii=False)
    d = route_from_llm_output(raw)
    assert d.structure == "S5"                 # ÉP, KHÔNG rơi S1 như LLM tự chọn
    assert d.fallback is False                  # đây là ép-thành-công, không phải fallback lỗi
    assert d.signals["has_genuine_paradox"] is True
    assert d.signals["residual_tension"] is not None
    assert d.hook == "H2"                        # hook giữ nguyên, không bị ép theo structure


def test_route_from_llm_output_paradox_normalized_false_does_not_force_s5():
    """Đối chứng: paradox=true nhưng residual_tension=null -> chuẩn hoá EFFECTIVE
    =false (RÀNG BUỘC #3 cũ) -> luật ép S5 mới (RÀNG BUỘC #4) KHÔNG kích hoạt,
    structure giữ NGUYÊN lựa chọn gốc của LLM (S3, không bị kéo về S1 lẫn S5)."""
    from twmkt.agents.structure_router import route_from_llm_output
    import json as _json

    raw = _json.dumps({
        "content_type": "article", "structure": "S3", "hook": "H1",
        "secondary_structure": None, "rationale": "Dữ kiện rời dồn về 1 xu hướng chung.",
        "signals": {"has_genuine_paradox": True, "residual_tension": None,
                   "drivers": [], "has_central_thesis": False},
    }, ensure_ascii=False)
    d = route_from_llm_output(raw)
    assert d.signals["has_genuine_paradox"] is False   # ép chuẩn hoá về false (như trước 4.8-B2)
    assert d.structure == "S3"                          # KHÔNG bị ép S5 (luật #4 không kích hoạt)
    assert d.fallback is False


def test_route_from_llm_output_no_paradox_keeps_llm_chosen_structure_regression():
    """Regression: paradox=false (thật, không lai) -> S1-S4 do LLM chọn giữ
    NGUYÊN, luật ép S5 mới không đụng vào các chủ đề khép-sạch bình thường."""
    from twmkt.agents.structure_router import route_from_llm_output
    import json as _json

    raw = _json.dumps({
        "content_type": "article", "structure": "S4", "hook": "H1",
        "secondary_structure": None, "rationale": "Nhiều driver độc lập song hành.",
        "signals": {"has_genuine_paradox": False,
                   "drivers": ["A", "B", "C"], "has_central_thesis": False},
    }, ensure_ascii=False)
    d = route_from_llm_output(raw)
    assert d.structure == "S4" and d.fallback is False


def test_get_or_route_freezes_forced_s5_decision_no_second_llm_call():
    """Tích hợp với Mục A (route-once): quyết định S5 bị-ép-đúng cũng được đóng
    băng bình thường — gọi get_or_route() lần 2 (mô phỏng video/infographic
    cùng chủ đề) đọc lại ĐÚNG S5 đã ép, KHÔNG gọi router lần 2."""
    from twmkt.agents.route_once import RouterDecisionStore, get_or_route
    from twmkt.agents.production import ProductionBrief
    import json as _json, tempfile
    from pathlib import Path

    class _ContradictoryParadoxLLM:
        def __init__(self):
            self.calls = 0

        def complete(self, system, prompt, *, model=None, fail_loud=False, temperature=None):
            self.calls += 1
            return _json.dumps({
                "content_type": "article", "structure": "S1", "hook": "H2",
                "secondary_structure": None,
                "rationale": "Logic khép lại sạch.",
                "signals": {"has_genuine_paradox": True,
                           "residual_tension": "Ai đỡ nếu rủi ro thành hiện thực.",
                           "drivers": [], "has_central_thesis": True},
            }, ensure_ascii=False)

    llm = _ContradictoryParadoxLLM()
    store = RouterDecisionStore(Path(tempfile.mkdtemp()) / "router_decisions.json")
    brief = ProductionBrief(title="Chủ đề nghịch lý thật")

    d1 = get_or_route(llm, brief, store=store, key="k-forced-s5")
    d2 = get_or_route(llm, brief, store=store, key="k-forced-s5")

    assert llm.calls == 1                # route-once vẫn giữ, không gọi lần 2
    assert d1.structure == d2.structure == "S5"


def test_route_from_llm_output_drivers_list_of_4_forces_secondary_s4():
    """Phase 3.5: drivers=[a,b,c,d] (4 tên) -> driver_count TÍNH BẰNG CODE =4 ->
    code TỰ ÉP secondary_structure=S4, KỂ CẢ khi LLM không tự điền (None) —
    không tin mù LLM tự nhớ set secondary_structure."""
    from twmkt.agents.structure_router import route_from_llm_output
    import json as _json

    raw = _json.dumps({
        "content_type": "article", "structure": "S1", "hook": "H3",
        "secondary_structure": None,   # LLM KHÔNG tự điền -> code vẫn phải ép S4
        "rationale": "Luận điểm trung tâm rõ, kèm 1 đoạn liệt kê 4 driver độc lập.",
        "signals": {"has_genuine_paradox": False,
                   "drivers": ["Hòa Phát", "Masan", "MB", "HDBank"],
                   "has_central_thesis": True},
    }, ensure_ascii=False)
    d = route_from_llm_output(raw)
    assert d.structure == "S1" and d.secondary_structure == "S4"
    assert d.signals["drivers"] == ["Hòa Phát", "Masan", "MB", "HDBank"]
    assert d.signals["driver_count"] == 4
    assert d.fallback is False


def test_route_from_llm_output_driver_count_never_diverges_from_drivers_list():
    """driver_count PHẢI luôn = len(drivers) — field "driver_count" rời LLM lỡ
    trả kèm (SAI, không khớp len(drivers)) bị BỎ QUA hoàn toàn, không tin mù."""
    from twmkt.agents.structure_router import route_from_llm_output
    import json as _json

    raw = _json.dumps({
        "content_type": "article", "structure": "S2", "hook": "H2",
        "secondary_structure": None, "rationale": "...",
        "signals": {"has_genuine_paradox": False, "drivers": ["A", "B"],
                   "driver_count": 99,   # SAI, lệch len(drivers) -> phải bị bỏ qua
                   "has_central_thesis": True},
    }, ensure_ascii=False)
    d = route_from_llm_output(raw)
    assert d.signals["driver_count"] == 2          # = len(drivers), KHÔNG phải 99 (field lạ bị bỏ qua)
    assert d.secondary_structure is None            # count=2 <3 -> KHÔNG ép S4


def test_route_from_llm_output_invalid_secondary_dropped_not_fallback():
    """secondary_structure lạ -> bỏ giá trị đó (None), KHÔNG fallback cả quyết
    định (field phụ, không đáng huỷ toàn bộ). driver_count=1 (<3) -> KHÔNG ép S4."""
    from twmkt.agents.structure_router import route_from_llm_output
    import json as _json

    raw = _json.dumps({
        "content_type": "article", "structure": "S2", "hook": "H2",
        "secondary_structure": "S9-khong-ton-tai", "rationale": "...",
        "signals": {"has_genuine_paradox": False, "drivers": ["A"], "has_central_thesis": True},
    }, ensure_ascii=False)
    d = route_from_llm_output(raw)
    assert d.structure == "S2" and d.secondary_structure is None and d.fallback is False


def test_route_from_llm_output_s4_rule_skipped_when_structure_already_s4():
    """structure chính ĐÃ LÀ S4 -> luật ép secondary=S4 KHÔNG áp dụng (S4 đã là
    khung chính, secondary_structure giữ nguyên giá trị LLM tự điền/None)."""
    from twmkt.agents.structure_router import route_from_llm_output
    import json as _json

    raw = _json.dumps({
        "content_type": "article", "structure": "S4", "hook": "H2",
        "secondary_structure": None, "rationale": "Cả bài là song hành nhiều driver.",
        "signals": {"has_genuine_paradox": False,
                   "drivers": ["A", "B", "C", "D", "E"], "has_central_thesis": False},
    }, ensure_ascii=False)
    d = route_from_llm_output(raw)
    assert d.structure == "S4" and d.secondary_structure is None
    assert d.signals["driver_count"] == 5


def test_run_route_with_mockllm_falls_back_gracefully():
    from twmkt.agents.base import MockLLM
    from twmkt.agents.structure_router import run_route
    from twmkt.agents.production import ProductionBrief

    brief = ProductionBrief(title="Bài test router")
    d = run_route(MockLLM(), brief)
    assert d.structure == "S1" and d.hook == "H3" and d.fallback is True


def test_build_router_prompt_includes_facts_kind_and_classification():
    from twmkt.agents.structure_router import build_router_prompt
    from twmkt.agents.production import ProductionBrief
    from twmkt.models import Fact

    brief = ProductionBrief(title="SSI 8 cổ phiếu", hook="hook gợi ý", group="ChungKhoan",
                            topic="SSI", facts=[Fact(value="8,18", label="GDP 6T/2026",
                                                     unit="%", kind="percent", source="...")])
    prompt = build_router_prompt(brief, classification={"hotness_pct": 87})
    assert "GDP 6T/2026" in prompt and "[percent]" in prompt
    assert "hotness_pct" in prompt and "87" in prompt


# --- Phase 4.8 Mục A: route-once + đóng băng (agents/route_once.py) --------
class _RouterJsonLLM:
    """Fake LLM router trả JSON hợp lệ tất định — đếm số lần complete() được
    gọi để chứng minh route-once KHÔNG gọi router lần 2 khi đã đóng băng."""

    def __init__(self, structure: str = "S3", hook: str = "H1"):
        self.calls = 0
        self._structure = structure
        self._hook = hook

    def complete(self, system, prompt, *, model=None, fail_loud=False, temperature=None):
        self.calls += 1
        import json as _json
        return _json.dumps({
            "content_type": "article", "structure": self._structure, "hook": self._hook,
            "secondary_structure": None, "rationale": "Test rationale nhất quán.",
            "signals": {"has_genuine_paradox": False, "drivers": [], "has_central_thesis": True},
        }, ensure_ascii=False)


def _tmp_decisions_path():
    import tempfile
    from pathlib import Path
    return Path(tempfile.mkdtemp()) / "router_decisions.json"


def test_get_or_route_calls_router_exactly_once_then_freezes():
    """(1) Cùng key gọi get_or_route() 2 LẦN -> run_route() CHỈ gọi LLM ĐÚNG 1
    LẦN (lần 2 đọc từ store) -> cùng 1 quyết định (khác với 4.7: gọi router 2
    lần trực tiếp ra 2 kết quả khác nhau do temperature no-op)."""
    from twmkt.agents.route_once import RouterDecisionStore, get_or_route
    from twmkt.agents.production import ProductionBrief

    llm = _RouterJsonLLM(structure="S3", hook="H1")
    store = RouterDecisionStore(_tmp_decisions_path())
    brief = ProductionBrief(title="Chủ đề test route-once")

    d1 = get_or_route(llm, brief, store=store, key="k1")
    d2 = get_or_route(llm, brief, store=store, key="k1")

    assert llm.calls == 1                       # KHÔNG gọi router lần 2
    assert d1.structure == d2.structure == "S3"
    assert d1.hook == d2.hook == "H1"
    assert d1.rationale == d2.rationale
    assert d1.signals == d2.signals


def test_get_or_route_second_content_type_reuses_frozen_decision_no_llm_call():
    """(2) video/infographic của CÙNG chủ đề (cùng key) đọc ĐÚNG RouterDecision
    article đã route trước đó — LLM route lần 2 (mô phỏng gọi từ agent khác)
    KHÔNG được đụng tới (PoisonLLM raise nếu bị gọi)."""
    from twmkt.agents.route_once import RouterDecisionStore, get_or_route
    from twmkt.agents.production import ProductionBrief

    class PoisonLLM:
        def complete(self, *a, **kw):
            raise AssertionError("KHÔNG được gọi router lần 2 khi đã đóng băng (vi phạm route-once)")

    store = RouterDecisionStore(_tmp_decisions_path())
    brief = ProductionBrief(title="Chủ đề test route-once")

    article_llm = _RouterJsonLLM(structure="S3", hook="H1")
    d_article = get_or_route(article_llm, brief, store=store, key="cung-chu-de")
    assert article_llm.calls == 1

    d_video = get_or_route(PoisonLLM(), brief, store=store, key="cung-chu-de")
    d_infographic = get_or_route(PoisonLLM(), brief, store=store, key="cung-chu-de")

    assert d_video.structure == d_infographic.structure == d_article.structure == "S3"
    assert d_video.hook == d_infographic.hook == d_article.hook


def test_router_decision_store_persists_across_instances():
    """(3) File JSON bền qua nhiều instance/tiến trình khác nhau (không chỉ
    cache trong bộ nhớ 1 process) — RouterDecisionStore MỚI trỏ cùng path đọc
    lại được quyết định instance TRƯỚC đã ghi."""
    from twmkt.agents.route_once import RouterDecisionStore, get_or_route
    from twmkt.agents.production import ProductionBrief

    path = _tmp_decisions_path()
    llm = _RouterJsonLLM(structure="S4", hook="H2")
    brief = ProductionBrief(title="Chủ đề bền vững")
    get_or_route(llm, brief, store=RouterDecisionStore(path), key="k-persist")

    store2 = RouterDecisionStore(path)   # instance MỚI, cùng file
    cached = store2.get("k-persist")
    assert cached is not None and cached.structure == "S4" and cached.hook == "H2"


def test_reroute_clears_frozen_decision_then_router_called_again():
    """(4) Cửa RE-ROUTE thủ công: store.clear(key) xoá quyết định đóng băng ->
    get_or_route() SAU ĐÓ gọi router lại (KHÔNG tự động, phải xoá tay trước)."""
    from twmkt.agents.route_once import RouterDecisionStore, get_or_route
    from twmkt.agents.production import ProductionBrief

    store = RouterDecisionStore(_tmp_decisions_path())
    brief = ProductionBrief(title="Chủ đề cần route lại")

    llm1 = _RouterJsonLLM(structure="S1", hook="H3")
    get_or_route(llm1, brief, store=store, key="k-reroute")
    assert llm1.calls == 1

    cleared = store.clear("k-reroute")
    assert cleared is True
    assert store.get("k-reroute") is None

    llm2 = _RouterJsonLLM(structure="S4", hook="H1")
    d2 = get_or_route(llm2, brief, store=store, key="k-reroute")
    assert llm2.calls == 1              # router ĐƯỢC gọi lại sau khi xoá
    assert d2.structure == "S4"


def test_router_decision_store_clear_returns_false_when_key_missing():
    from twmkt.agents.route_once import RouterDecisionStore

    store = RouterDecisionStore(_tmp_decisions_path())
    assert store.clear("khong-ton-tai") is False


# --- Render Infographic (src/twmkt/render, $0 tất định) --------------------
def test_brand_kit_from_settings_reads_overrides_and_defaults():
    from twmkt.render import brand_kit_from_settings

    kit = brand_kit_from_settings(Settings({}))
    assert kit["width"] == 1080 and kit["primary"] == "#E7C873"

    kit2 = brand_kit_from_settings(Settings({"render": {"infographic": {
        "primary": "#FF0000", "width": 800,
    }}}))
    assert kit2["primary"] == "#FF0000" and kit2["width"] == 800
    assert kit2["bg"] == "#0B1B2B"   # key không khai -> vẫn dùng mặc định


def test_render_infographic_svg_contains_headline_stats_and_disclaimer():
    from twmkt.agents.production import InfographicSpecAgent, ProductionBrief
    from twmkt.render import brand_kit_from_settings, render_infographic_svg
    import json as _json
    import xml.dom.minidom as minidom

    brief = ProductionBrief(title="PNJ tăng 40%", hook="PNJ: kỷ lục doanh thu",
                            tickers=["PNJ"], url="https://cafef.vn/x.chn",
                            evidence="Doanh thu tăng 40%, đạt 1.200 tỷ đồng, kỷ lục.")
    spec = _json.loads(InfographicSpecAgent(None).run(brief).body)
    brand = brand_kit_from_settings(Settings({}))
    svg = render_infographic_svg(spec, brand)

    assert svg.startswith("<svg ")
    minidom.parseString(svg)   # phải là XML hợp lệ, không lỗi parse
    assert "PNJ" in svg
    assert spec["stats"][0]["value"] in svg
    assert "không phải khuyến nghị đầu tư" in svg
    assert brand["primary"] in svg


def test_render_infographic_svg_handles_empty_stats_and_missing_footer():
    from twmkt.render import render_infographic_svg
    import xml.dom.minidom as minidom

    svg = render_infographic_svg({"headline": "Chỉ tiêu đề", "tickers": []})
    minidom.parseString(svg)
    assert "Chỉ tiêu đề" in svg


def test_all_production_agents_applies_prompt_overrides_by_name():
    from twmkt.agents.production import all_production_agents

    agents = all_production_agents(None, prompt_overrides={
        "analysis": "PROMPT ANALYSIS TÙY CHỈNH", "video": "", "khong-ton-tai": "x"})
    by_role = {a.role: a for a in agents}
    assert by_role["AnalysisWriter"].system == "PROMPT ANALYSIS TÙY CHỈNH"
    # video rỗng -> KHÔNG override (giữ default); infographic không có key -> giữ default
    assert by_role["VideoScripter"].system != ""
    assert "TẤT ĐỊNH" in by_role["InfographicDesigner"].system


def _voice_settings(**overrides):
    from twmkt.config import Settings

    data = {
        "voice": {
            "enabled": True,
            "examples_path": os.path.join(REPO_ROOT, "docs", "voice_examples.md"),
        }
    }
    data["voice"].update(overrides)
    return Settings(data)


class _FakeDecision:
    """Duck-type RouterDecision (agents/structure_router.py) — assemble_voice()
    chỉ cần .structure/.secondary_structure/.hook/.content_type, KHÔNG import
    RouterDecision thật (tránh vòng import, xem agents/voice.py docstring)."""
    def __init__(self, structure="S1", secondary_structure=None, hook="H3",
                content_type="article"):
        self.structure = structure
        self.secondary_structure = secondary_structure
        self.hook = hook
        self.content_type = content_type


def test_assemble_voice_always_includes_universal_sections():
    """assemble_voice: LUÔN có mặt §1 (Luật giọng) + Menu hook/Luật chuyển ý (§2b)
    + Luật kết chung (§2c) + Nên/Tránh (§3), bất kể decision nào."""
    from twmkt.agents.voice import assemble_voice

    out = assemble_voice(_FakeDecision(), settings=_voice_settings())
    assert "Luật giọng (bất biến)" in out
    assert "Luật chuyển ý mượt" in out
    assert "Luật kết chung" in out
    assert "Nên / Tránh" in out


def test_assemble_voice_selects_primary_and_secondary_structure_blocks():
    """Đúng ca SSI (S1 + khung phụ S4): assemble_voice PHẢI có khối S1 VÀ khối
    S4, nhưng KHÔNG có khối S2/S3/S5 (chỉ nối đúng 2 khung router chọn, không
    nhồi cả 5)."""
    from twmkt.agents.voice import assemble_voice

    out = assemble_voice(_FakeDecision(structure="S1", secondary_structure="S4"),
                         settings=_voice_settings())
    assert "S1 · Tổng" in out
    assert "S4 · Song hành" in out
    assert "S2 · Diễn dịch" not in out
    assert "S3 · Quy nạp" not in out
    assert "S5 · Phản đề" not in out


def test_assemble_voice_no_secondary_only_includes_primary_block():
    from twmkt.agents.voice import assemble_voice

    out = assemble_voice(_FakeDecision(structure="S5", secondary_structure=None),
                         settings=_voice_settings())
    assert "S5 · Phản đề" in out
    assert "S1 · Tổng" not in out and "S4 · Song hành" not in out


def test_assemble_voice_picks_anchor_by_structure_map():
    """Anchor mặc định theo khung CHÍNH (§0 voice_examples.md): S1->D, S5->A,
    S2->B — CHỈ đúng 1 ví dụ, không lẫn ví dụ khác."""
    from twmkt.agents.voice import assemble_voice

    out_s1 = assemble_voice(_FakeDecision(structure="S1"), settings=_voice_settings())
    assert "### Ví dụ D" in out_s1 and "### Ví dụ A" not in out_s1 and "### Ví dụ B" not in out_s1

    out_s5 = assemble_voice(_FakeDecision(structure="S5"), settings=_voice_settings())
    assert "### Ví dụ A" in out_s5 and "### Ví dụ D" not in out_s5

    out_s2 = assemble_voice(_FakeDecision(structure="S2"), settings=_voice_settings())
    assert "### Ví dụ B" in out_s2 and "### Ví dụ D" not in out_s2


def test_assemble_voice_filters_hook_menu_to_chosen_pattern():
    """§2b Menu hook PHẢI thu hẹp còn ĐÚNG 1 bullet khớp decision.hook — 2 bullet
    còn lại KHÔNG xuất hiện, nhưng "Luật hook"/"Luật chuyển ý mượt" vẫn giữ nguyên."""
    from twmkt.agents.voice import assemble_voice

    out = assemble_voice(_FakeDecision(hook="H1"), settings=_voice_settings())
    assert "H1 · Ngã ba" in out
    assert "H2 · Chi tiết bị bỏ qua" not in out
    assert "H3 · Sự thật + câu hỏi trực diện" not in out
    assert "Luật hook:" in out
    assert "Luật chuyển ý mượt" in out


def test_assemble_voice_disabled_returns_empty():
    from twmkt.agents.voice import assemble_voice

    out = assemble_voice(_FakeDecision(), settings=_voice_settings(enabled=False))
    assert out == ""

    from twmkt.config import Settings
    out2 = assemble_voice(_FakeDecision(), settings=Settings({}))   # thiếu key -> mặc định false
    assert out2 == ""


def test_assemble_voice_missing_file_degrades_to_empty_no_crash():
    from twmkt.agents.voice import assemble_voice

    out = assemble_voice(_FakeDecision(), settings=_voice_settings(examples_path="khong/ton/tai.md"))
    assert out == ""


def test_assemble_voice_none_decision_uses_safe_default_s1_h3_d():
    """decision=None (chưa chạy router, vd đường LEGACY --draft) -> fallback AN
    TOÀN cùng nghĩa StructureRouter._fallback(): S1 + H3 + Ví dụ D."""
    from twmkt.agents.voice import assemble_voice

    out = assemble_voice(None, settings=_voice_settings())
    assert "S1 · Tổng" in out
    assert "H3 · Sự thật + câu hỏi trực diện" in out
    assert "### Ví dụ D" in out


def test_assemble_voice_unknown_structure_falls_back_to_whole_section2():
    """structure lạ (không tồn tại trong menu §2) -> KHÔNG tìm được khối -> dùng
    NGUYÊN §2 (degrade an toàn, không rỗng/không crash)."""
    from twmkt.agents.voice import assemble_voice

    out = assemble_voice(_FakeDecision(structure="S9"), settings=_voice_settings())
    assert out != ""
    assert "S1 · Tổng" in out and "S5 · Phản đề" in out   # NGUYÊN §2 -> có đủ cả 5 khung


# --- Phase 4: Writer (agents/writer.py) --------------------------------------
def test_build_writer_system_includes_persona_and_voice():
    from twmkt.agents.writer import build_writer_system
    from twmkt.agents.production import AnalysisWriterAgent

    system = build_writer_system(_FakeDecision(structure="S1", secondary_structure="S4", hook="H1"))
    assert AnalysisWriterAgent.system in system      # persona/schema JSON dùng CHUNG
    assert "VOICE-LOCK" in system
    assert "S1 · Tổng" in system and "S4 · Song hành" in system
    assert "H1 · Ngã ba" in system


def test_run_writer_parses_llm_json_and_renders_body():
    """run_writer: LLM trả JSON đúng schema -> body dựng từ sections thật (dùng
    LẠI analysis_fields_from_data/render_analysis — CHƯA qua guardrail, caller
    tự gọi apply_guardrails() sau, xem docstring module)."""
    from twmkt.agents.writer import run_writer
    from twmkt.agents.production import ProductionBrief
    import json as _json

    class JsonLLM:
        def complete(self, system, prompt, *, model=None, fail_loud=False):
            return _json.dumps({
                "title": "SSI 8 cổ phiếu — bài viết thật",
                "sapo": "Tóm tắt.",
                "sections": [{"heading": "Bối cảnh", "content": "GDP tăng 8,18%."}],
                "disclaimer": "Nội dung chỉ mang tính thông tin, không phải khuyến nghị "
                              "đầu tư. Nhà đầu tư tự chịu trách nhiệm với quyết định của mình.",
                "sources": [],
            }, ensure_ascii=False)

    brief = ProductionBrief(title="SSI 8 cổ phiếu", hook="SSI: 8 cổ phiếu", tickers=["SSI"],
                            url="https://cafef.vn/ssi.chn", evidence="GDP tăng 8,18%.")
    draft = run_writer(JsonLLM(), brief, _FakeDecision(structure="S1", secondary_structure="S4"))
    assert draft.title == "SSI 8 cổ phiếu — bài viết thật"
    assert "Bối cảnh" in draft.body and "GDP tăng 8,18%." in draft.body


def test_run_writer_defaults_to_fail_loud_true():
    """Writer là bước QUAN TRỌNG -> fail_loud=True MẶC ĐỊNH (khác brief/router) —
    xác nhận complete() nhận đúng fail_loud=True khi KHÔNG truyền tham số."""
    from twmkt.agents.writer import run_writer
    from twmkt.agents.production import ProductionBrief

    seen = {}

    class SpyLLM:
        def complete(self, system, prompt, *, model=None, fail_loud=False):
            seen["fail_loud"] = fail_loud
            seen["model"] = model
            return ""   # rỗng -> lùi mượt tất định ở tầng schema (không liên quan fail_loud ở đây)

    brief = ProductionBrief(title="Bài test", evidence="Dữ kiện.")
    run_writer(SpyLLM(), brief, model="sonnet")
    assert seen["fail_loud"] is True
    assert seen["model"] == "sonnet"


# --- Phase 4.5: Writer retry (agents/writer.run_writer_with_retry) ----------
def _clean_writer_json() -> str:
    import json as _json
    return _json.dumps({
        "title": "Bài sạch", "sapo": "Tóm tắt.",
        "sections": [{"heading": "Bối cảnh", "content": "Doanh thu tăng nhẹ."}],
        "disclaimer": "Nội dung chỉ mang tính thông tin, không phải khuyến nghị đầu tư. "
                      "Nhà đầu tư tự chịu trách nhiệm với quyết định của mình.",
        "sources": [],
    }, ensure_ascii=False)


def _writer_retry_settings(**overrides):
    from twmkt.config import Settings
    data = {"writer": {"max_retries": 1, "retry_backoff_s": 3, "timeout_s": 120}}
    data["writer"].update(overrides)
    return Settings(data)


class _FlakyLLM:
    """Raise LLMCallError `fail_times` lần đầu, sau đó trả `then_json`."""
    def __init__(self, fail_times: int, then_json: str):
        from twmkt.agents.base import LLMCallError
        self._LLMCallError = LLMCallError
        self.fail_times = fail_times
        self.then_json = then_json
        self.calls = 0

    def complete(self, system, prompt, *, model=None, fail_loud=False):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self._LLMCallError(f"lỗi giả lập lần {self.calls}")
        return self.then_json


def test_run_writer_with_retry_timeout_once_then_success_no_failed():
    """(i) fake timeout 1 lần rồi thành công -> 1 retry, ra nội dung, KHÔNG FAILED."""
    from twmkt.agents.writer import run_writer_with_retry, WriterOutcome
    from twmkt.agents.production import ProductionBrief

    llm = _FlakyLLM(fail_times=1, then_json=_clean_writer_json())
    brief = ProductionBrief(title="Bài test", evidence="Doanh thu tăng nhẹ.")
    r = run_writer_with_retry(llm, brief, settings=_writer_retry_settings(), sleep=lambda s: None)
    assert r.outcome == WriterOutcome.DONE
    assert r.attempts == 2          # lần 1 lỗi (không tính là attempt thành công), lần 2 mới ra bài
    assert llm.calls == 2
    assert r.draft is not None and r.draft.is_clean


def test_run_writer_with_retry_exceeds_max_retries_marks_failed_and_rerunnable():
    """(ii) timeout vượt max_retries -> FAILED (KHÔNG trả nội dung rỗng coi như
    thật); gọi lại lần sau (cùng state/key) PHẢI tái chạy được (không bị skip
    như DONE)."""
    from twmkt.agents.writer import run_writer_with_retry, WriterOutcome
    from twmkt.agents.production import ProductionBrief

    llm = _FlakyLLM(fail_times=99, then_json=_clean_writer_json())   # luôn lỗi
    brief = ProductionBrief(title="Bài test", evidence="Doanh thu tăng nhẹ.")
    state: dict[str, str] = {}
    r1 = run_writer_with_retry(llm, brief, settings=_writer_retry_settings(),
                               state=state, key="k1", sleep=lambda s: None)
    assert r1.outcome == WriterOutcome.FAILED
    assert r1.draft is None                      # KHÔNG có nội dung "" coi như thật
    assert r1.attempts == 2                       # max_retries=1 -> tối đa 2 lượt gọi
    assert state["k1"] == "FAILED"
    assert llm.calls == 2

    # Tái chạy: FAILED KHÔNG bị skip (khác DONE) -> llm.complete() được gọi lại.
    r2 = run_writer_with_retry(llm, brief, settings=_writer_retry_settings(),
                               state=state, key="k1", sleep=lambda s: None)
    assert llm.calls == 4                          # 2 lượt gọi thêm ở lần chạy lại
    assert r2.outcome == WriterOutcome.FAILED       # llm vẫn luôn lỗi trong test này


def test_run_writer_with_retry_guardrail_reject_no_retry_needs_human():
    """(iii) guardrail reject (số bịa, không có trong evidence) -> NEEDS_HUMAN
    NGAY, KHÔNG retry (llm.complete() chỉ gọi ĐÚNG 1 lần)."""
    from twmkt.agents.writer import run_writer_with_retry, WriterOutcome
    from twmkt.agents.production import ProductionBrief
    import json as _json

    class RejectLLM:
        def __init__(self):
            self.calls = 0

        def complete(self, system, prompt, *, model=None, fail_loud=False):
            self.calls += 1
            return _json.dumps({
                "title": "Bài vi phạm", "sapo": "Tóm tắt.",
                "sections": [{"heading": "Bối cảnh", "content": "Lợi nhuận tăng 999% so với cùng kỳ."}],
                "disclaimer": "Nội dung chỉ mang tính thông tin, không phải khuyến nghị đầu tư. "
                              "Nhà đầu tư tự chịu trách nhiệm với quyết định của mình.",
                "sources": [],
            }, ensure_ascii=False)

    llm = RejectLLM()
    brief = ProductionBrief(title="Bài test", evidence="Doanh thu tăng nhẹ.")   # KHÔNG có "999%"
    r = run_writer_with_retry(llm, brief, settings=_writer_retry_settings(), sleep=lambda s: None)
    assert r.outcome == WriterOutcome.NEEDS_HUMAN
    assert llm.calls == 1              # KHÔNG retry cho lỗi vĩnh viễn
    assert "999%" in r.reason


def test_run_writer_with_retry_done_is_idempotent_skips_rerun():
    """(iv) idempotent: state[key]=="DONE" -> SKIP hoàn toàn, KHÔNG gọi llm lần
    nào (dùng LLM sẽ raise nếu bị gọi để chứng minh không hề đụng tới)."""
    from twmkt.agents.writer import run_writer_with_retry, WriterOutcome
    from twmkt.agents.production import ProductionBrief

    class PoisonLLM:
        def complete(self, *a, **kw):
            raise AssertionError("KHÔNG được gọi LLM khi state đã DONE (vi phạm idempotent)")

    brief = ProductionBrief(title="Bài test", evidence="Doanh thu tăng nhẹ.")
    state = {"k1": "DONE"}
    r = run_writer_with_retry(PoisonLLM(), brief, settings=_writer_retry_settings(),
                              state=state, key="k1", sleep=lambda s: None)
    assert r.outcome == WriterOutcome.DONE
    assert r.attempts == 0
    assert state["k1"] == "DONE"


def test_run_writer_with_retry_calls_notify_hook_at_retry_failed_needs_human():
    """notify(event, info) PHẢI được gọi tại đúng 3 điểm: retry, failed, needs_human."""
    from twmkt.agents.writer import run_writer_with_retry
    from twmkt.agents.production import ProductionBrief
    import json as _json

    events: list[str] = []

    def notify(event, info):
        events.append(event)

    # retry -> failed (luôn lỗi)
    llm_fail = _FlakyLLM(fail_times=99, then_json=_clean_writer_json())
    brief = ProductionBrief(title="Bài test", evidence="Doanh thu tăng nhẹ.")
    run_writer_with_retry(llm_fail, brief, settings=_writer_retry_settings(),
                          notify=notify, sleep=lambda s: None)
    assert events.count("retry") == 2 and events.count("failed") == 1

    # needs_human (guardrail reject)
    events.clear()

    class RejectLLM:
        def complete(self, system, prompt, *, model=None, fail_loud=False):
            return _json.dumps({
                "title": "X", "sapo": "Y",
                "sections": [{"heading": "Z", "content": "Lãi tăng 999%."}],
                "disclaimer": "Nội dung chỉ mang tính thông tin, không phải khuyến nghị đầu tư. "
                              "Nhà đầu tư tự chịu trách nhiệm với quyết định của mình.",
                "sources": [],
            }, ensure_ascii=False)

    run_writer_with_retry(RejectLLM(), brief, settings=_writer_retry_settings(),
                          notify=notify, sleep=lambda s: None)
    assert events == ["needs_human"]


def test_prompts_v1_files_match_code_defaults_no_drift():
    """prompts/{analysis,video}.v1.md PHẢI khớp y hệt default nội bộ trong code —
    seed PROMPTS (Enable=TRUE, v1) không được đổi hành vi ngay từ đầu."""
    from twmkt.agents.production import AnalysisWriterAgent, VideoScriptAgent
    from twmkt.agents.prompts import read_prompt_file

    assert read_prompt_file("analysis", "v1", prompts_dir="prompts") == AnalysisWriterAgent.system
    assert read_prompt_file("video", "v1", prompts_dir="prompts") == VideoScriptAgent.system


def test_match_source_by_domain_and_fetch_full_evidence_fallback():
    """match_source_by_domain khớp theo TÊN MIỀN (không cần đúng path); fetch lỗi/
    rỗng -> fallback (KHÔNG crash, KHÔNG gọi mạng thật trong test)."""
    sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))
    import produce_from_sheet as pfs
    from twmkt.models import Source, RawDocument

    sources = [Source("CafeF - DN", "https://cafef.vn/doanh-nghiep.chn"),
              Source("Vietstock", "https://vietstock.vn/co-phieu.htm")]
    m = pfs.match_source_by_domain("https://cafef.vn/abc-123.chn", sources)
    assert m is not None and m.name == "CafeF - DN"
    assert pfs.match_source_by_domain("https://khong-co-trong-list.vn/x", sources) is None
    assert pfs.match_source_by_domain("", sources) is None

    class _FakeCollectorOk:
        def fetch_one(self, source, url):
            return RawDocument(source="s", url=url, title="t", markdown="Thân bài thật.")

    class _FakeCollectorNone:
        def fetch_one(self, source, url):
            return None

    class _FakeCollectorRaises:
        def fetch_one(self, source, url):
            raise RuntimeError("mạng lỗi")

    ev = pfs.fetch_full_evidence(_FakeCollectorOk(), sources, "https://cafef.vn/abc.chn", "fallback")
    assert ev == "Thân bài thật."
    assert pfs.fetch_full_evidence(_FakeCollectorNone(), sources, "https://cafef.vn/x.chn", "fallback") == "fallback"
    assert pfs.fetch_full_evidence(_FakeCollectorRaises(), sources, "https://cafef.vn/x.chn", "fallback") == "fallback"
    assert pfs.fetch_full_evidence(_FakeCollectorOk(), sources, "", "fallback") == "fallback"


def test_prompt_md_includes_system_user_and_ingest_instruction():
    """_prompt_md: gói đủ system + user prompt + schema + hướng dẫn --ingest, để
    Claude Code (không gọi API) đọc và viết đúng JSON schema."""
    sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))
    import produce_from_sheet as pfs
    from twmkt.agents.production import AnalysisWriterAgent

    md = pfs._prompt_md("slug-x", "article", "USER PROMPT NỘI DUNG")
    assert AnalysisWriterAgent.system in md
    assert "USER PROMPT NỘI DUNG" in md
    assert "slug-x.article.json" in md
    assert "--ingest" in md
    assert "sections" in md   # schema hint


def test_draft_to_content_draft_matches_llm_path():
    """draft_to_content_draft (JSON Claude Code tự viết) phải cho kết quả GIỐNG
    HỆT đường gọi qua AnthropicLLM thật (cùng schema/render/guardrail — chỉ khác
    'ai điền JSON'), và vẫn lùi mượt tất định khi data rỗng."""
    from twmkt.agents.production import ProductionBrief
    import produce_from_sheet as pfs

    brief = ProductionBrief(title="FPT báo lãi", hook="FPT: lãi kỷ lục", tickers=["FPT"],
                            url="https://cafef.vn/fpt.chn", evidence="Doanh thu tăng 40%.")
    data = {"title": "FPT lãi kỷ lục", "sapo": "Tóm tắt.",
            "sections": [{"heading": "Bối cảnh", "content": "Doanh thu tăng 40%."}],
            "disclaimer": "Nội dung chỉ mang tính thông tin, không phải khuyến nghị đầu tư. "
                         "Nhà đầu tư tự chịu trách nhiệm với quyết định của mình.",
            "sources": []}
    d = pfs.draft_to_content_draft("article", data, brief)
    assert d.title == "FPT lãi kỷ lục" and "Nguồn: cafef.vn" in d.body and d.is_clean

    # data rỗng (Claude Code chưa viết được / lỗi parse) -> lùi mượt tất định.
    d2 = pfs.draft_to_content_draft("video", {}, brief)
    assert d2.is_clean and brief.title in d2.body


def test_approved_context_from_rows_filters_and_maps():
    """approved_context_from_rows: chỉ giữ Status=APPROVE (khớp dropdown thật:
    PENDING|APPROVE|REJECT), lấy url chính từ ô Source gộp."""
    from twmkt.sheets_board import approved_context_from_rows, CONTEXT_HEADER, context_row

    r1 = context_row(title="Bài A", hook_line="Hook A", source_url="http://a", score=5,
                     hot_pct=50.0, topic="CoPhieu", group="CoPhieu, ChinhSach",
                     other_sources=["http://a2"], tickers=["FPT", "HPG"], status="APPROVE")
    r2 = context_row(title="Bài B", hook_line="Hook B", source_url="http://b", score=1,
                     hot_pct=10.0, status="PENDING")
    got = approved_context_from_rows([CONTEXT_HEADER, r1, r2])
    assert len(got) == 1
    a = got[0]
    assert a["context"] == "Bài A" and a["hook"] == "Hook A"
    assert a["source"] == "http://a"                     # url chính (dòng đầu ô Source gộp)
    assert a["tickers"] == ["FPT", "HPG"] and a["topic"] == "CoPhieu"
    assert approved_context_from_rows([CONTEXT_HEADER]) == []   # 0 approved


def test_content_row_shape():
    from twmkt.sheets_board import content_row, CONTENT_HEADER
    assert CONTENT_HEADER == ["Timestamp", "Context", "Type", "Status", "Output",
                             "Notes", "Approve(gate 2)"]
    row = content_row(context="Bài A", type_="article", status="DONE",
                      output="nội dung", notes="ok", ts="ts")
    d = dict(zip(CONTENT_HEADER, row))
    assert d == {"Timestamp": "ts", "Context": "Bài A", "Type": "article", "Status": "DONE",
                 "Output": "nội dung", "Notes": "ok", "Approve(gate 2)": "PENDING"}
    row2 = content_row(context="Bài B", type_="video_script", status="ERROR",
                       output="x", approve="APPROVE", ts="ts2")
    d2 = dict(zip(CONTENT_HEADER, row2))
    assert d2["Approve(gate 2)"] == "APPROVE"


def test_build_content_llm_sonnet_router():
    from twmkt.agents.router import LLMRouter, Tier
    from twmkt.agents.base import MockLLM as _Mock, AnthropicLLM

    off = factory.build_content_llm(Settings({"llm": {"provider": "anthropic"}}), offline=True)
    assert isinstance(off, LLMRouter) and isinstance(off.base, _Mock)
    real = factory.build_content_llm(
        Settings({"llm": {"provider": "anthropic", "content_model": "claude-sonnet-4-6"}}),
        offline=False)
    assert isinstance(real.base, AnthropicLLM) and real.base.model == "claude-sonnet-4-6"
    assert real.default_tier is Tier.SMART


def test_build_writer_llm_reads_writer_timeout_s_not_shared_claude_code_timeout():
    """factory.build_writer_llm: mode=claude_code -> ClaudeCodeLLM.timeout_s lấy
    từ writer.timeout_s (KHÔNG dùng chung llm.claude_code.timeout_s)."""
    from twmkt.agents.base import ClaudeCodeLLM, MockLLM as _Mock

    llm = factory.build_writer_llm(Settings({
        "llm": {"mode": "claude_code", "claude_code": {"timeout_s": 999}},
        "writer": {"timeout_s": 45},
    }))
    assert isinstance(llm, ClaudeCodeLLM) and llm.timeout_s == 45.0

    mock_llm = factory.build_writer_llm(Settings({"llm": {"mode": "mock"}}))
    assert isinstance(mock_llm, _Mock)


# --- PHASE TELE: Telegram Notifier (src/twmkt/utils/telegram_notifier.py) ---
class _FakeTgResp:
    def __init__(self, status_code, json_data, text=""):
        self.status_code = status_code
        self._json = json_data
        self.text = text

    def json(self):
        return self._json


def test_format_message_escapes_html_special_chars():
    """HTML escape đúng khi ctx chứa <, >, & — tránh vỡ parse_mode=HTML."""
    from twmkt.utils.telegram_notifier import format_message

    msg = format_message("start", {"topic": "A & B <script>alert('x')</script>"})
    assert "&amp;" in msg
    assert "&lt;script&gt;" in msg
    assert "<script>" not in msg
    assert "⏳" in msg   # emoji đúng event


def test_format_message_maps_writer_retry_events_to_error_emoji():
    """Phase 4.6+4.7: failed/needs_human (lỗi CUỐI, event thật run_writer_with_
    retry bắn ra, Phase 4.5) PHẢI dùng emoji 🚨; retry (còn đang thử lại, độ khẩn
    thấp hơn) dùng ⚠️ riêng — cả 3 trước đây rơi vào "ℹ️" mặc định."""
    from twmkt.utils.telegram_notifier import format_message

    for event in ("failed", "needs_human"):
        msg = format_message(event, {"reason": "x"})
        assert "🚨" in msg, f"event={event!r} thiếu emoji 🚨"
        assert "ℹ️" not in msg

    retry_msg = format_message("retry", {"reason": "x"})
    assert "⚠️" in retry_msg and "🚨" not in retry_msg and "ℹ️" not in retry_msg


def test_null_notifier_is_noop_returns_false():
    from twmkt.utils.telegram_notifier import NullNotifier

    assert NullNotifier().notify("start", topic="x") is False


def test_telegram_notifier_non_blocking_on_network_error():
    """Non-blocking: mock lỗi network -> notify trả False, KHÔNG raise."""
    import httpx
    from twmkt.utils.telegram_notifier import TelegramNotifier

    original_post = httpx.post

    def _boom(*a, **kw):
        raise ConnectionError("mạng lỗi giả lập")

    httpx.post = _boom
    try:
        n = TelegramNotifier(bot_token="x", chat_id="y")
        ok = n.notify("error", topic="test lỗi mạng")
        assert ok is False
    finally:
        httpx.post = original_post


def test_telegram_notifier_non_blocking_on_http_error_status():
    import httpx
    from twmkt.utils.telegram_notifier import TelegramNotifier

    original_post = httpx.post
    httpx.post = lambda *a, **kw: _FakeTgResp(500, {}, text="Internal Server Error")
    try:
        n = TelegramNotifier(bot_token="x", chat_id="y")
        assert n.notify("error", topic="x") is False
    finally:
        httpx.post = original_post


def test_telegram_notifier_non_blocking_on_ok_false():
    import httpx
    from twmkt.utils.telegram_notifier import TelegramNotifier

    original_post = httpx.post
    httpx.post = lambda *a, **kw: _FakeTgResp(200, {"ok": False, "description": "chat not found"})
    try:
        n = TelegramNotifier(bot_token="x", chat_id="y")
        assert n.notify("error", topic="x") is False
    finally:
        httpx.post = original_post


def test_telegram_notifier_success_returns_true():
    import httpx
    from twmkt.utils.telegram_notifier import TelegramNotifier

    original_post = httpx.post
    seen = {}

    def _fake_post(url, *, json=None, timeout=None):
        seen["url"] = url
        seen["json"] = json
        seen["timeout"] = timeout
        return _FakeTgResp(200, {"ok": True, "result": {}})

    httpx.post = _fake_post
    try:
        n = TelegramNotifier(bot_token="123:abc", chat_id="999", timeout_s=7)
        assert n.notify("gate2_done", written=3) is True
        assert "123:abc" in seen["url"] and "sendMessage" in seen["url"]
        assert seen["json"]["chat_id"] == "999" and seen["timeout"] == 7
    finally:
        httpx.post = original_post


def test_make_notifier_selects_null_when_disabled():
    from twmkt.utils.telegram_notifier import make_notifier, NullNotifier

    s = Settings({"notifications": {"telegram": {"enabled": False}}})
    assert isinstance(make_notifier(s), NullNotifier)


def test_make_notifier_selects_null_when_env_unexpanded():
    """ENV chưa set -> os.path.expandvars GIỮ NGUYÊN "${VAR}" (không trả rỗng)
    -> make_notifier PHẢI nhận diện đây là "thiếu cấu hình" -> NullNotifier."""
    from twmkt.utils.telegram_notifier import make_notifier, NullNotifier

    s = Settings({"notifications": {"telegram": {
        "enabled": True, "bot_token": "${TELEGRAM_BOT_TOKEN}", "chat_id": "${TELEGRAM_CHAT_ID}"}}})
    assert isinstance(make_notifier(s), NullNotifier)


def test_make_notifier_selects_telegram_when_configured():
    from twmkt.utils.telegram_notifier import make_notifier, TelegramNotifier

    s = Settings({"notifications": {"telegram": {
        "enabled": True, "bot_token": "123:abc", "chat_id": "999",
        "parse_mode": "HTML", "timeout_s": 7}}})
    n = make_notifier(s)
    assert isinstance(n, TelegramNotifier)
    assert n.bot_token == "123:abc" and n.chat_id == "999" and n.timeout_s == 7.0


# --- Banner "LLM active" (lùi mượt CÓ CẢNH BÁO — không im lặng) -------------
def test_llm_status_banner_mock_when_provider_not_anthropic():
    st = factory.llm_status(Settings({"llm": {"provider": "mock"}}))
    assert st.use_llm is False
    assert "provider" in st.reason.lower() or "mock" in st.reason.lower()
    assert st.banner == "LLM active: MOCK ($0 fallback) — lý do: llm.provider='mock' (không phải anthropic)"


def test_llm_status_banner_mock_when_anthropic_unavailable():
    """provider=anthropic nhưng thiếu SDK/khóa -> banner MOCK kèm LÝ DO rõ (không im lặng)."""
    old = os.environ.pop("ANTHROPIC_API_KEY", None)
    try:
        st = factory.llm_status(Settings({"llm": {"provider": "anthropic"}}))
        assert st.use_llm is False and st.reason
        assert st.banner.startswith("LLM active: MOCK ($0 fallback) — lý do:")
    finally:
        if old is not None:
            os.environ["ANTHROPIC_API_KEY"] = old


def test_llm_status_banner_active_when_key_present():
    """Có SDK (đã cài trong môi trường test) + ANTHROPIC_API_KEY -> banner 'anthropic'
    với đúng hook_model/researcher_model từ config (không gọi mạng)."""
    old = os.environ.get("ANTHROPIC_API_KEY")
    os.environ["ANTHROPIC_API_KEY"] = "sk-test-fake"
    try:
        st = factory.llm_status(Settings({"llm": {
            "provider": "anthropic", "triage_model": "claude-haiku-4-5-20251001",
            "hook_model": "claude-sonnet-4-6",
        }}))
        assert st.use_llm is True
        assert st.banner == ("LLM active: anthropic (hook=claude-sonnet-4-6, "
                             "researcher=claude-haiku-4-5-20251001)")
    finally:
        if old is None:
            os.environ.pop("ANTHROPIC_API_KEY", None)
        else:
            os.environ["ANTHROPIC_API_KEY"] = old


def test_model_engine_label_maps_haiku_sonnet_mock():
    assert factory.model_engine_label("claude-haiku-4-5-20251001", use_llm=True) == "haiku"
    assert factory.model_engine_label("claude-sonnet-4-6", use_llm=True) == "sonnet"
    assert factory.model_engine_label("claude-opus-4-8", use_llm=True) == "opus"
    assert factory.model_engine_label("claude-sonnet-4-6", use_llm=False) == "mock"


def test_sheets_log_header_has_engine_column():
    from twmkt.sheets_board import LOG_HEADER
    assert LOG_HEADER == ["timestamp", "level", "message", "engine"]


def test_sheets_board_log_writes_engine_column():
    from twmkt.sheets_board import SheetsBoard

    class _FakeWS:
        def __init__(self): self.appended = []
        def append_row(self, row, value_input_option=None): self.appended.append(row)

    board = SheetsBoard(spreadsheet_id="X", creds_path="Y")
    ws = _FakeWS()
    board._ws["LOG"] = ws
    board.log("INFO", "test message", engine="haiku")
    assert ws.appended[0][1:] == ["INFO", "test message", "haiku"]
    board.log("WARN", "no engine")
    assert ws.appended[1][1:] == ["WARN", "no engine", ""]


# --- secrets/.env bền qua python-dotenv (config-first, override=False) ------
def test_load_dotenv_sets_env_without_overriding_shell():
    import shutil
    import tempfile
    from twmkt.config import _load_dotenv

    tmp = tempfile.mkdtemp()
    env_path = os.path.join(tmp, ".env")
    with open(env_path, "w", encoding="utf-8") as f:
        f.write("ANTHROPIC_API_KEY=from-dotenv\nOTHER_TWMKT_VAR=xyz\n")

    saved = {k: os.environ.get(k) for k in ("TWMKT_DOTENV", "ANTHROPIC_API_KEY", "OTHER_TWMKT_VAR")}
    try:
        os.environ["TWMKT_DOTENV"] = env_path
        os.environ.pop("ANTHROPIC_API_KEY", None)
        os.environ.pop("OTHER_TWMKT_VAR", None)
        _load_dotenv()
        assert os.environ.get("ANTHROPIC_API_KEY") == "from-dotenv"
        assert os.environ.get("OTHER_TWMKT_VAR") == "xyz"

        # override=False: biến đã có sẵn trong shell PHẢI thắng file .env
        os.environ["ANTHROPIC_API_KEY"] = "from-shell"
        _load_dotenv()
        assert os.environ.get("ANTHROPIC_API_KEY") == "from-shell"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def test_load_dotenv_missing_file_is_noop():
    import tempfile
    from twmkt.config import _load_dotenv

    old = os.environ.get("TWMKT_DOTENV")
    try:
        os.environ["TWMKT_DOTENV"] = os.path.join(tempfile.mkdtemp(), "khong-ton-tai.env")
        _load_dotenv()   # không raise dù file không tồn tại
    finally:
        if old is None:
            os.environ.pop("TWMKT_DOTENV", None)
        else:
            os.environ["TWMKT_DOTENV"] = old


# --- power_on.py: lock file tự chặn 2 tiến trình cùng máy ($0, không mạng) --
def test_power_on_lock_parses_and_detects_dead_pid():
    """parse_lock_content + is_pid_alive: parse "host:pid" đúng/hỏng; PID không
    tồn tại -> False; PID hiện tại (chính tiến trình test) -> True."""
    sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))
    import power_on as po

    assert po.parse_lock_content("myhost:1234") == ("myhost", 1234)
    assert po.parse_lock_content("hỏng-không-dấu-hai-chấm") is None
    assert po.parse_lock_content("host:khong-phai-so") is None
    assert po.is_pid_alive(999999) is False       # PID gần như chắc chắn không tồn tại
    assert po.is_pid_alive(os.getpid()) is True    # chính tiến trình test đang chạy


def test_power_on_acquire_lock_blocks_same_host_alive_pid():
    """acquire_lock: lock cùng host + PID CÒN SỐNG (chính tiến trình test) ->
    raise SystemExit (chặn chạy trùng); PID CHẾT -> dọn sạch, không raise."""
    import socket
    import tempfile
    from pathlib import Path
    sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))
    import power_on as po

    tmp = Path(tempfile.mkdtemp()) / "power_on.lock"
    tmp.write_text(f"{socket.gethostname()}:{os.getpid()}", encoding="utf-8")
    try:
        po.acquire_lock(tmp)
    except SystemExit:
        pass
    else:
        raise AssertionError("phải chặn khi PID cùng host còn sống")

    tmp.write_text(f"{socket.gethostname()}:999999", encoding="utf-8")  # PID chết
    po.acquire_lock(tmp)   # không raise -> dọn lock cũ, ghi lock mới
    assert tmp.read_text(encoding="utf-8") == f"{socket.gethostname()}:{os.getpid()}"
    po.release_lock(tmp)
    assert not tmp.exists()


def test_power_on_acquire_lock_warns_but_allows_different_host():
    """acquire_lock: lock do máy KHÁC ghi -> chỉ in cảnh báo, KHÔNG raise (không
    thể tự chặn liên-máy từ 1 file cục bộ)."""
    import tempfile
    from pathlib import Path
    sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))
    import power_on as po

    tmp = Path(tempfile.mkdtemp()) / "power_on.lock"
    tmp.write_text("mot-may-khac:123", encoding="utf-8")
    po.acquire_lock(tmp)   # không raise
    po.release_lock(tmp)


# xfail: test biết trước ĐANG đỏ vì 1 phần việc CHƯA làm (không phải regression
# mới) — ghi rõ lý do + phase sẽ fix, để suite chạy XANH sạch mà không che giấu
# nợ kỹ thuật. Nếu ai lỡ fix xong mà quên bỏ khỏi danh sách này -> in XPASS (cảnh
# báo, không fail) để dễ nhận ra và dọn lại.
_XFAIL: dict[str, str] = {}   # trống — Phase 4 đã fix xfail duy nhất còn lại (voice-lock động)


def _run_all():
    fns = [v for k, v in globals().items() if k.startswith("test_")]
    xfail = passed = 0
    for fn in fns:
        name = fn.__name__
        if name in _XFAIL:
            try:
                fn()
            except Exception:
                print(f"XFAIL {name} ({_XFAIL[name]})")
                xfail += 1
            else:
                print(f"XPASS {name} — ĐÃ pass, xoá khỏi _XFAIL trong test_pipeline.py")
                passed += 1
            continue
        fn()
        print(f"PASS {name}")
        passed += 1
    print(f"\n{passed} tests passed, {xfail} xfail (nợ kỹ thuật đã biết) / {len(fns)} tổng.")


if __name__ == "__main__":
    _run_all()
