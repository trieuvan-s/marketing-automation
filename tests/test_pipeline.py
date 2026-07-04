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
    """context_row đúng thứ tự CONTEXT_HEADER; Use=FALSE, Status=PENDING mặc định;
    Publisher/Field/Topic/Sources (mô hình 3 lớp) xếp đúng cột."""
    from twmkt.sheets_board import context_row, CONTEXT_HEADER

    row = context_row(title="Tiêu đề bài", hook_line="FPT: hook hấp dẫn",
                      source_url="http://u", score=5, hot_pct=42.5,
                      publisher="CafeF - RSS Chứng khoán", field="ChungKhoan", topic="ThiTruong",
                      group="ChinhSach, ViMoVN", other_sources=["http://u2", "http://u3"],
                      tickers=["FPT", "HPG"], ts="2026-07-02T00:00:00+00:00")
    assert len(row) == len(CONTEXT_HEADER)
    d = dict(zip(CONTEXT_HEADER, row))
    assert d["Use"] == "FALSE"
    assert d["Score"] == "5"
    assert d["Hot%"] == "42.5"
    assert d["Publisher"] == "CafeF - RSS Chứng khoán"
    assert d["Field"] == "ChungKhoan"
    assert d["Topic"] == "ThiTruong"
    assert d["Group"] == "ChinhSach, ViMoVN"
    assert d["Context"] == "Tiêu đề bài"
    assert d["Hook"] == "FPT: hook hấp dẫn"
    assert d["Source"] == "http://u"
    assert d["Sources"] == "http://u2, http://u3"
    assert d["Status"] == "PENDING"
    assert d["timestamp"] == "2026-07-02T00:00:00+00:00"
    assert d["tickers"] == "FPT, HPG"
    assert d["Notes"] == ""


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
    assert kinds.count("deleteBanding") == 1
    assert kinds.count("deleteConditionalFormatRule") == 3
    # APPROVE/PENDING/REJECT (Status) + score scale + Hot% scale
    assert kinds.count("addConditionalFormatRule") == 5
    # checkbox cho SOURCES.Enable + CONTEXT.Use, dropdown cho CONTEXT.Status
    sd = [r["setDataValidation"] for r in reqs if "setDataValidation" in r]
    conds = [v["rule"]["condition"]["type"] for v in sd]
    assert conds.count("BOOLEAN") == 2 and "ONE_OF_LIST" in conds
    # determinism = idempotent theo cấu trúc
    assert build_format_requests(tabs) == reqs
    assert SOURCES_HEADER[0].lower() == "enable"
    low = [c.lower() for c in CONTEXT_HEADER]
    assert {"use", "score", "hot%", "group", "context", "hook", "source", "status"} <= set(low)


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


def test_enrich_classify_field_topic_uses_taxonomy_and_hints():
    """classify_field_topic: khớp từ khóa TAXONOMY; hint (category RSS/SOURCES.Field)
    khớp field -> ưu tiên nhưng không override tuyệt đối khi có bằng chứng khác."""
    from twmkt.curation.enrich import classify_field_topic, TaxonomyRow

    taxonomy = [
        TaxonomyRow("ChinhSach", "PhapLy", ["nghị định", "luật"]),
        TaxonomyRow("ViMo", "TrongNuoc", ["gdp", "lạm phát"]),
    ]
    assert classify_field_topic("Chính phủ ban hành Nghị định mới", taxonomy=taxonomy) == (
        "ChinhSach", "PhapLy")
    assert classify_field_topic("Không khớp từ khóa nào", taxonomy=taxonomy) == ("Khac", "")
    # hint khớp field (không phân biệt hoa/thường) -> chọn đúng field dù 0 từ khóa khớp
    assert classify_field_topic("tin chung chung", hints=["vimo"], taxonomy=taxonomy) == (
        "ViMo", "TrongNuoc")


def test_enrich_cluster_by_event_keeps_highest_priority():
    """cluster_by_event: gộp sự kiện CHÉO NGUỒN, GIỮ báo Priority cao làm đại diện
    (dù không xuất hiện đầu), url báo khác gộp vào other_urls."""
    from twmkt.curation.enrich import cluster_by_event, EventItem

    items = [
        # cụm FPT: bản Priority thấp xuất hiện TRƯỚC, bản cao xuất hiện SAU
        EventItem("FPT bao lai quy tang manh", "http://low/fpt", "CafeBiz", priority=3),
        EventItem("FPT bao lai quy tang manh nhe", "http://high/fpt", "Vietstock", priority=9),
        EventItem("FPT bao lai quy tang", "http://mid/fpt", "CafeF", priority=5),
        # cụm HPG riêng
        EventItem("HPG san luong thep phuc hoi", "http://cafef/hpg", "CafeF", priority=5),
    ]
    clusters = cluster_by_event(items, threshold=0.6)
    assert len(clusters) == 2
    fpt = next(c for c in clusters if "fpt" in c.item.title.lower())
    assert fpt.item.url == "http://high/fpt" and fpt.item.priority == 9   # GIỮ Priority cao
    assert fpt.other_urls == ["http://low/fpt", "http://mid/fpt"]         # url báo khác, giữ thứ tự
    hpg = next(c for c in clusters if "hpg" in c.item.title.lower())
    assert hpg.other_urls == []
    assert cluster_by_event([]) == []


def test_replace_context_clears_then_rewrites():
    """replace_context: XÓA vùng dữ liệu (A2:..) rồi ghi lại từ A2 (UPSERT), giữ header."""
    from twmkt.sheets_board import SheetsBoard, CONTEXT_HEADER, context_row

    class _FakeWS:
        def __init__(self, values):
            self._v = values; self.cleared = None; self.updated = None
        def get_all_values(self): return self._v
        def batch_clear(self, ranges): self.cleared = ranges
        def update(self, rng, values, value_input_option=None):
            self.updated = (rng, values, value_input_option)

    board = SheetsBoard(spreadsheet_id="X", creds_path="Y")
    old = ["FALSE"] * len(CONTEXT_HEADER)
    ws = _FakeWS([CONTEXT_HEADER, old, old])       # header + 2 dòng cũ
    board._ws["CONTEXT"] = ws

    row = context_row(title="Bài mới", hook_line="h", source_url="http://u", score=3, hot_pct=42.0)
    n = board.replace_context([row])
    assert n == 1
    assert ws.cleared == ["A2:O3"]                 # xóa 2 dòng dữ liệu cũ, GIỮ header (15 cột -> O)
    assert ws.updated[0] == "A2" and ws.updated[1] == [row]   # ghi lại từ A2


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


def _run_all():
    fns = [v for k, v in globals().items() if k.startswith("test_")]
    for fn in fns:
        fn(); print(f"PASS {fn.__name__}")
    print(f"\n{len(fns)} tests passed.")


if __name__ == "__main__":
    _run_all()
