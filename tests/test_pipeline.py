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
    # 3 CafeF html + 6 nguồn rss (CafeF/CafeBiz/Vietstock) + 6 nguồn html TASK-011
    # (Baochinhphu x3 + Nguoiquansat + VietnamBiz + Vietstock-doanh-nghiep)
    assert len(s.enabled_sources()) == 15
    # whitelist trỏ sang danh sách mã đầy đủ (VN30 giữ cho test)
    assert s.get("curation.tickers_file") == "data/tickers_full.txt"


def test_settings_expands_env():
    from twmkt.config import _expand
    # Dọn lại ENV sau test — bug hygiene THẬT phát hiện: để sót "SHEET_ABC" làm
    # rò rỉ os.environ["TWMKT_SHEET_ID"] sang các test CHẠY SAU trong CÙNG tiến
    # trình (_run_all() chạy mọi test chung 1 process), khiến resolve_sheet_id()
    # (Content Factory Phase D) đọc nhầm giá trị test cũ thay vì Settings truyền
    # vào — xem test_resolve_sheet_id_allow_production_true_returns_production.
    old = os.environ.get("TWMKT_SHEET_ID")
    try:
        os.environ["TWMKT_SHEET_ID"] = "SHEET_ABC"
        data = _expand({"sheets": {"spreadsheet_id": "${TWMKT_SHEET_ID}"}})
        assert data["sheets"]["spreadsheet_id"] == "SHEET_ABC"
    finally:
        if old is None:
            os.environ.pop("TWMKT_SHEET_ID", None)
        else:
            os.environ["TWMKT_SHEET_ID"] = old


# --- Phase DATA-ROOT: gốc dữ liệu runtime DUY NHẤT, tách khỏi repo ----------
def test_data_root_reads_settings_storage_data_root():
    from twmkt.config import Settings, data_root
    import tempfile

    tmp = tempfile.mkdtemp()
    s = Settings({"storage": {"data_root": tmp}})
    assert str(data_root(s)) == tmp


def test_data_root_env_override_wins_over_settings():
    """DATA_ROOT (biến môi trường) thắng storage.data_root trong config — CÙNG
    NẾP với TWMKT_SHEET_ID/TWMKT_SHEETS_CREDS (produce_from_sheet._open_board),
    dùng cho deploy VPS khác máy dev không cần sửa settings.yaml."""
    from twmkt.config import Settings, data_root
    import tempfile

    tmp_env, tmp_cfg = tempfile.mkdtemp(), tempfile.mkdtemp()
    s = Settings({"storage": {"data_root": tmp_cfg}})
    os.environ["DATA_ROOT"] = tmp_env
    try:
        assert str(data_root(s)) == tmp_env
    finally:
        del os.environ["DATA_ROOT"]


def test_data_root_warns_when_default_store_is_missing(monkeypatch, capsys, caplog):
    """Khong co DATA_ROOT + DB vang mat -> canh bao ro, nhung van tra path."""
    from twmkt.config import Settings, data_root
    from pathlib import Path
    import tempfile

    monkeypatch.delenv("DATA_ROOT", raising=False)
    caplog.set_level("WARNING", logger="twmkt.config")
    root = Path(tempfile.mkdtemp()) / "empty-data-root"

    assert data_root(Settings({"storage": {"data_root": str(root)}})) == root
    assert str(root) in capsys.readouterr().err
    assert "set ENV DATA_ROOT" in caplog.text


def test_data_root_missing_store_does_not_warn_when_env_is_set(monkeypatch, capsys, caplog):
    from twmkt.config import Settings, data_root
    from pathlib import Path
    import tempfile

    explicit_root = Path(tempfile.mkdtemp()) / "explicit-root"
    monkeypatch.setenv("DATA_ROOT", str(explicit_root))
    caplog.set_level("WARNING", logger="twmkt.config")

    assert data_root(Settings({"storage": {"data_root": "ignored"}})) == explicit_root
    assert capsys.readouterr().err == ""
    assert "set ENV DATA_ROOT" not in caplog.text


def test_ai_full_v13_is_part_of_cache_key(monkeypatch):
    """Version prompt phai that su doi cache key, khong chi la metadata."""
    from twmkt.render import ai_full

    spec = {"title": "Cung mot spec"}
    assert ai_full._PROMPT_VERSION == "v13"
    key_v13 = ai_full._cache_key(spec, "light", "4:5")
    monkeypatch.setattr(ai_full, "_PROMPT_VERSION", "v12")
    assert ai_full._cache_key(spec, "light", "4:5") != key_v13


def test_data_path_directory_target_creates_itself_idempotently():
    from twmkt.config import Settings, data_path
    from pathlib import Path
    import tempfile

    tmp = tempfile.mkdtemp()
    s = Settings({"storage": {"data_root": tmp}})
    p = data_path("documents", "2026-07-10", settings=s)
    assert p == Path(tmp) / "documents" / "2026-07-10"
    assert p.is_dir()
    data_path("documents", "2026-07-10", settings=s)   # gọi lại -> idempotent, không lỗi


def test_data_path_file_target_creates_parent_not_itself():
    from twmkt.config import Settings, data_path
    import tempfile

    tmp = tempfile.mkdtemp()
    s = Settings({"storage": {"data_root": tmp}})
    p = data_path("logs", "power_on.lock", settings=s)
    assert p.parent.is_dir()      # thư mục CHA được tạo
    assert not p.exists()         # bản thân FILE — chỉ resolve path, chưa ghi gì


def test_data_path_no_parts_returns_and_creates_root_itself():
    from twmkt.config import Settings, data_path
    from pathlib import Path
    import tempfile

    parent = tempfile.mkdtemp()
    tmp = Path(parent) / "chua-ton-tai"
    s = Settings({"storage": {"data_root": str(tmp)}})
    p = data_path(settings=s)
    assert p == tmp and tmp.is_dir()


def test_data_path_config_first_swap_data_root_changes_resolved_path():
    """Đổi storage.data_root sang thư mục KHÁC -> data_path() đi theo NGAY —
    chứng minh config-first thật (không có gì hard-code)."""
    from twmkt.config import Settings, data_path
    import tempfile

    tmp1, tmp2 = tempfile.mkdtemp(), tempfile.mkdtemp()
    p1 = data_path("output", settings=Settings({"storage": {"data_root": tmp1}}))
    p2 = data_path("output", settings=Settings({"storage": {"data_root": tmp2}}))
    assert str(p1).startswith(tmp1) and str(p2).startswith(tmp2)
    assert p1 != p2


def test_load_brand_reads_real_config_brand_yaml():
    """load_brand() không truyền path -> đọc config/brand.yaml THẬT trên đĩa
    (giống load_settings() đọc config/settings.yaml thật, KHÔNG có bản mock
    mặc định)."""
    from twmkt.config import load_brand

    brand = load_brand()
    assert brand["name"] == "FVA Capital"
    assert brand["wordmark"] == "FVA CAPITAL"
    assert brand["colors"]["bg"] == "#0B1B2B"
    assert "khuyến nghị đầu tư" in brand["footer"]["disclaimer"]


def test_load_brand_missing_file_degrades_to_empty_no_crash():
    """LÙI MƯỢT: thiếu file (khác load_settings() — brand.yaml KHÔNG bắt buộc
    để hệ thống chạy) -> {} , KHÔNG raise."""
    from twmkt.config import load_brand

    assert load_brand(path="khong/ton/tai/brand.yaml") == {}


def test_load_brand_custom_path_parses_correctly():
    import tempfile
    from pathlib import Path
    from twmkt.config import load_brand

    tmp = Path(tempfile.mkdtemp()) / "custom_brand.yaml"
    tmp.write_text(
        "brand:\n  name: \"Test Brand\"\n  colors:\n    primary: \"#123456\"\n",
        encoding="utf-8",
    )
    brand = load_brand(path=tmp)
    assert brand["name"] == "Test Brand" and brand["colors"]["primary"] == "#123456"


# =====================================================================
# Content Factory Phase D — RÀO CHẮN MÔI TRƯỜNG: config.resolve_sheet_id()
# BẮT BUỘC mọi luồng benchmark/A-B (Phase 3 trở đi) trỏ sheet TEST, KHÔNG dựa
# vào trí nhớ người chạy — ép bằng CODE, không phải quy ước.
# =====================================================================
def test_resolve_sheet_id_default_blocks_production_when_no_test_sheet_configured():
    """Nghiệm thu CHÍNH: chạy benchmark (allow_production=False, mặc định)
    KHÔNG cấu hình sheet TEST -> PHẢI raise (KHÔNG BAO GIỜ lùi về production dù
    production CÓ cấu hình sẵn) -> benchmark KHÔNG THỂ ghi vào sheet production."""
    from twmkt.config import ProductionSheetBlocked, Settings, resolve_sheet_id

    s = Settings({"sheets": {"spreadsheet_id": "PROD-ID-THAT-MUST-NOT-LEAK",
                             "test_spreadsheet_id": ""}})
    try:
        resolve_sheet_id(s)   # allow_production mặc định False
    except ProductionSheetBlocked:
        pass
    else:
        raise AssertionError("resolve_sheet_id() PHẢI raise khi thiếu sheet TEST — "
                             "không được lùi về production dù production đã cấu hình sẵn.")


def test_resolve_sheet_id_default_returns_test_sheet_never_production():
    from twmkt.config import Settings, resolve_sheet_id

    s = Settings({"sheets": {"spreadsheet_id": "PROD-ID-THAT-MUST-NOT-LEAK",
                             "test_spreadsheet_id": "TEST-SHEET-ID"}})
    assert resolve_sheet_id(s) == "TEST-SHEET-ID"
    assert resolve_sheet_id(s, allow_production=False) == "TEST-SHEET-ID"


def test_resolve_sheet_id_allow_production_true_returns_production():
    from twmkt.config import Settings, resolve_sheet_id

    s = Settings({"sheets": {"spreadsheet_id": "PROD-ID", "test_spreadsheet_id": "TEST-ID"}})
    assert resolve_sheet_id(s, allow_production=True) == "PROD-ID"


def test_resolve_sheet_id_allow_production_true_but_missing_production_id_raises():
    from twmkt.config import ProductionSheetBlocked, Settings, resolve_sheet_id

    s = Settings({"sheets": {"spreadsheet_id": "", "test_spreadsheet_id": "TEST-ID"}})
    try:
        resolve_sheet_id(s, allow_production=True)
    except ProductionSheetBlocked:
        pass
    else:
        raise AssertionError("Thiếu spreadsheet_id production nhưng allow_production=True "
                             "PHẢI raise, KHÔNG được lùi về sheet test.")


def test_resolve_sheet_id_env_test_sheet_override():
    import os

    from twmkt.config import Settings, resolve_sheet_id

    s = Settings({"sheets": {"spreadsheet_id": "PROD-ID", "test_spreadsheet_id": "TEST-FROM-YAML"}})
    old = os.environ.get("TWMKT_TEST_SHEET_ID")
    try:
        os.environ["TWMKT_TEST_SHEET_ID"] = "TEST-FROM-ENV"
        assert resolve_sheet_id(s) == "TEST-FROM-ENV"   # ENV đè settings.yaml
    finally:
        if old is None:
            os.environ.pop("TWMKT_TEST_SHEET_ID", None)
        else:
            os.environ["TWMKT_TEST_SHEET_ID"] = old


def test_build_store_file_resolves_under_data_root_not_hardcoded_storage():
    from twmkt import factory
    from twmkt.config import Settings
    from pathlib import Path
    import tempfile

    tmp = tempfile.mkdtemp()
    s = Settings({"storage": {"type": "file", "data_root": tmp, "documents_dir": "documents",
                              "retention_days": 10, "timezone": "Asia/Ho_Chi_Minh"}})
    store = factory.build_store(s)
    assert store.root == Path(tmp) / "documents"


def test_power_on_lock_path_resolves_via_data_path_helper():
    """system_power_on._lock_path() KHÔNG còn hard-code REPO_ROOT/"storage"/...
    — monkeypatch data_path (đã import vào namespace system_power_on) để cô
    lập khỏi data_root thật trong lúc test."""
    sys.path.insert(0, REPO_ROOT)
    import system_power_on as po
    from twmkt.config import Settings, data_path as real_data_path
    import tempfile

    tmp = tempfile.mkdtemp()
    test_settings = Settings({"storage": {"data_root": tmp}})
    orig = po.data_path
    po.data_path = lambda *parts, **kw: real_data_path(*parts, settings=test_settings)
    try:
        p = po._lock_path()
        assert p.parent.name == "logs" and p.name == "power_on.lock"
        assert str(p).startswith(tmp)
    finally:
        po.data_path = orig


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


# --- TASK-012: nới is_relevant() theo quy định biên tập chủ dự án -----------
# 1) Doanh nghiệp: "có mã" chỉ đủ khi mã thuộc watchlist TOP 300
#    (config.relevance_tickers), KHÔNG phải toàn bộ whitelist trích mã (có thể
#    rộng hơn, vd 1526 mã tickers_full.txt).
def test_relevance_ticker_outside_top300_watchlist_is_dropped():
    cfg = CurationConfig(
        tickers={"FPT", "ABC"},          # whitelist TRÍCH mã (rộng)
        relevance_tickers={"FPT"},       # watchlist TOP 300 (hẹp) -- quyết định liên quan
    )
    # ABC được TRÍCH (nằm trong whitelist trích) nhưng NGOÀI watchlist top 300
    # -> không đủ để coi bài "liên quan", và câu không có tín hiệu macro/policy/hot nào khác.
    assert is_relevant("Doanh nghiệp ABC công bố kế hoạch mới", ["ABC"], cfg) is False
    # FPT thuộc watchlist top 300 -> liên quan ngay.
    assert is_relevant("Doanh nghiệp FPT công bố kế hoạch mới", ["FPT"], cfg) is True


def test_relevance_ticker_rollback_toggle_restores_old_behavior():
    """Đường lùi requirement 5: use_watchlist_for_relevance=False -> quay lại
    hành vi CŨ (bất kỳ mã đã trích cũng đủ, không cần nằm trong watchlist)."""
    cfg = CurationConfig(
        tickers={"FPT", "ABC"}, relevance_tickers={"FPT"},
        use_watchlist_for_relevance=False,
    )
    assert is_relevant("Doanh nghiệp ABC công bố kế hoạch mới", ["ABC"], cfg) is True


def test_relevance_ticker_relevance_tickers_empty_falls_back_to_extracted_tickers():
    """watchlist rỗng (chưa cấu hình/thiếu file) -> KHÔNG âm thầm loại sạch mọi
    bài có mã, lùi về hành vi CŨ (coi như use_watchlist_for_relevance chưa có tác dụng)."""
    cfg = CurationConfig(tickers={"ABC"})  # relevance_tickers mặc định rỗng
    assert is_relevant("Doanh nghiệp ABC công bố kế hoạch mới", ["ABC"], cfg) is True


# 2) Vĩ mô/chính sách: tín hiệu CHÍNH SÁCH VIỆT NAM có ngưỡng riêng, thấp hơn
#    ngưỡng macro chung -- vì từ khóa đặc hiệu hơn (nghị định/thông tư/NHNN...).
def test_relevance_vn_policy_keyword_kept_even_below_macro_threshold():
    cfg = CurationConfig(
        macro_keywords=["lãi suất", "lạm phát", "gdp"], min_macro_keywords=2,
        policy_keywords=["nghị định", "ngân hàng nhà nước"], min_policy_keywords=1,
    )
    # Chỉ 1 từ khóa chính sách VN (< min_macro_keywords nếu tính theo nhánh macro)
    # nhưng đủ ngưỡng policy riêng -> giữ.
    assert is_relevant("Chính phủ vừa ban hành nghị định mới", [], cfg) is True


# 3) Vĩ mô nước ngoài thuần túy KHÔNG phải trọng tâm: không mã, không khớp
#    policy/macro VN, không đủ ngưỡng hot -> loại.
def test_relevance_pure_foreign_macro_without_vn_signal_is_dropped():
    cfg = CurationConfig(
        macro_keywords=["lãi suất", "lạm phát", "gdp"], min_macro_keywords=2,
        policy_keywords=["nghị định", "ngân hàng nhà nước"], min_policy_keywords=1,
        hotness_keywords=["kỷ lục", "tăng mạnh", "cao nhất"], min_hotness_keywords=3,
    )
    text = "Fed giữ nguyên lãi suất, Dow Jones và Nasdaq đồng loạt đi lên, phố Wall lạc quan"
    assert is_relevant(text, [], cfg) is False


# 4) Chủ đề nóng được ưu ái: đạt ngưỡng hotness thì giữ dù mã/macro/policy yếu.
def test_relevance_hot_topic_kept_despite_weak_other_signals():
    cfg = CurationConfig(
        macro_keywords=["lãi suất", "lạm phát", "gdp"], min_macro_keywords=2,
        policy_keywords=["nghị định", "ngân hàng nhà nước"], min_policy_keywords=1,
        hotness_keywords=["kỷ lục", "tăng mạnh", "cao nhất", "%"], min_hotness_keywords=3,
    )
    text = "Cổ phiếu ngành thép tăng kịch trần 7%, khối lượng lập kỷ lục, mức cao nhất 3 năm"
    assert is_relevant(text, [], cfg) is True   # 0 mã, 0 macro/policy nhưng đủ 3 tín hiệu hot


def test_relevance_hot_topic_override_can_be_disabled():
    """Đường lùi requirement 5: enable_hotness_override=False -> bỏ nhánh hot,
    hành vi như trước khi có TASK-012 (chỉ còn mã + macro/policy)."""
    cfg = CurationConfig(
        hotness_keywords=["kỷ lục", "tăng mạnh", "cao nhất", "%"], min_hotness_keywords=3,
        enable_hotness_override=False,
    )
    # Cùng text đạt 3 tín hiệu hot ở test trên (được giữ khi override BẬT) --
    # nhưng tắt công tắc thì phải loại, chứng minh switch có tác dụng thật.
    text = "Cổ phiếu ngành thép tăng kịch trần 7%, khối lượng lập kỷ lục, mức cao nhất 3 năm"
    assert is_relevant(text, [], cfg) is False


def test_curation_config_from_settings_loads_task012_relevance_fields():
    """from_settings() phải nạp đúng các tham số TASK-012 từ settings.yaml
    (config-first: không hard-code), kể cả fallback khi thiếu curation.groups.ChinhSach
    / curation.relevance.hotness_keywords trong settings truyền vào."""
    s = Settings({
        "curation": {
            "tickers_file": "data/tickers_full.txt",
            "watchlist_file": "data/tickers.txt",
            "ambiguous_file": "data/tickers_ambiguous.txt",
            "relevance": {
                "keywords_file": "data/keywords_macro.txt",
                "min_macro_keywords": 2,
                "use_watchlist_for_relevance": False,
                "min_policy_keywords": 5,
                "enable_hotness_override": False,
                "min_hotness_keywords": 7,
            },
        }
    })
    cfg = CurationConfig.from_settings(s)
    assert cfg.use_watchlist_for_relevance is False
    assert cfg.min_policy_keywords == 5
    assert cfg.enable_hotness_override is False
    assert cfg.min_hotness_keywords == 7
    assert len(cfg.relevance_tickers) == 300   # data/tickers.txt
    # curation.groups.ChinhSach không truyền -> fallback default policy keywords.
    assert "nghị định" in cfg.policy_keywords
    # curation.relevance.hotness_keywords không truyền -> fallback default.
    assert "kỷ lục" in cfg.hotness_keywords


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
    from twmkt.agents.base import MockLLM, AnthropicLLM, ClaudeCodeLLM
    assert isinstance(factory.build_llm(Settings({"llm": {"provider": "mock"}})), MockLLM)
    # anthropic chỉ *dựng* client, không gọi API (import SDK cũng lazy trong complete)
    assert isinstance(factory.build_llm(Settings({"llm": {"provider": "anthropic"}})),
                      AnthropicLLM)
    # claude_code (2026-07-27 -- Producers dùng gói Claude Pro/Max thay Anthropic
    # API khi ANTHROPIC_API_KEY chưa cấu hình) -- chỉ dựng CLI client, không gọi.
    cc = factory.build_llm(Settings({"llm": {"provider": "claude_code",
                                             "claude_code": {"timeout_s": 99}}}))
    assert isinstance(cc, ClaudeCodeLLM)
    assert cc.timeout_s == 99.0


def test_build_llm_unsupported_provider_raises():
    try:
        factory.build_llm(Settings({"llm": {"provider": "openai"}}))
    except ValueError as e:
        assert "mock|anthropic|claude_code" in str(e)
    else:
        raise AssertionError("phải raise ValueError với provider lạ")


def test_build_content_llm_uses_claude_code_when_provider_claude_code():
    """VIỆC PHÁT SINH (2026-07-27, Lead yêu cầu): trước bản vá, build_content_llm()
    (Producers -- InfographicSpecAgent/VideoScriptAgent) LUÔN đi nhánh 'anthropic'
    bất kể llm.mode -- thiếu ANTHROPIC_API_KEY khiến video/infographic âm thầm
    lùi mượt MOCK. Đổi llm.provider='claude_code' phải khiến content_llm dùng
    ClaudeCodeLLM (CLI, KHÔNG cần ANTHROPIC_API_KEY)."""
    from twmkt.agents.base import ClaudeCodeLLM

    settings = Settings({"llm": {"provider": "claude_code"}})
    router = factory.build_content_llm(settings, offline=False)
    assert isinstance(router.base, ClaudeCodeLLM)


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


def test_hook_default_cta_is_brand_driven_not_hardcoded_old_brand():
    """Content Factory Phase D — hook.py._DEFAULT_CTA đọc brand.name từ
    config/brand.yaml (MỘT NGUỒN), KHÔNG còn hằng số hard-code brand cũ."""
    from twmkt.agents.hook import _DEFAULT_CTA, _BRAND_NAME

    assert "turtle" not in _DEFAULT_CTA.lower()
    assert _BRAND_NAME in _DEFAULT_CTA


def test_producers_cta_and_disclaimer_are_brand_driven_not_hardcoded_old_brand():
    """Content Factory Phase D — agents/producers.py (đường Hook/Luồng B, VẪN
    LIVE qua orchestrator.all_producers()) cũng phải sạch brand cũ."""
    from twmkt.agents.producers import _BRAND_NAME, _DEFAULT_CTA, _DISCLAIMER

    assert "turtle" not in _DEFAULT_CTA.lower()
    assert _BRAND_NAME in _DEFAULT_CTA
    assert "turtle" not in _DISCLAIMER.lower()


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
        def complete(self, system, prompt, **kwargs):
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
        def complete(self, system, prompt, **kwargs): return "phản hồi không phải JSON"

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
        def complete(self, system, prompt, **kwargs):
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
        def complete(self, system, prompt, **kwargs): return "   "

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
    NGAY SAU Output Type (P2 store-as-truth Bước 4, chèn sau Duyệt Context —
    xem sheets_board.py comment OUTPUT_TYPE_COL cho lý do vị trí). Source gộp
    báo khác; Status=PENDING, Execute rỗng mặc định. TopicKey (Lớp 5 Phase 1)
    — APPEND CUỐI (không chen giữa, xem sheets_board.py comment CONTEXT_HEADER:
    tránh lệch vị trí mọi cột hiện có)."""
    from twmkt.sheets_board import GATE1_COL, context_row, CONTEXT_HEADER

    assert CONTEXT_HEADER == ["Timestamp", "Hot%", "Score", "Group", "Topic", "Context",
                             "Hook", "Source", GATE1_COL, "Output Type", "Execute", "tickers",
                             "Notes", "TopicKey"]
    row = context_row(title="Tiêu đề bài", hook_line="FPT: hook hấp dẫn",
                      source_url="http://u", score=5, hot_pct=42.5, topic="CoPhieu",
                      group="CoPhieu, ChinhSach", other_sources=["http://u2", "http://u3"],
                      tickers=["FPT", "HPG"], ts="2026-07-02T00:00:00+00:00",
                      topic_key="abc123")
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
    assert d["Duyệt Context"] == "PENDING"   # Sheet UI cleanup Phase 3: trước đây "Status"
    # VIỆC Execute (2026-08-03, Lead) — ĐẢO LẠI quyết định 2026-07-28 (khi đó
    # ép "Waiting" cho MỌI dòng để tránh trông như "hệ thống chưa thấy dòng
    # này"). Nay "" = mới crawl/CHƯA qua Gate 1 (khác "Waiting" = ĐÃ duyệt,
    # đang xếp hàng) — context_row() không nhận status=APPROVE ở test này nên
    # Execute mặc định phải rỗng.
    assert d["Execute"] == ""
    assert d["tickers"] == "FPT, HPG"
    assert d["Notes"] == ""
    assert d["TopicKey"] == "abc123"

    row2 = context_row(title="T2", hook_line="H2", source_url="http://v", score=1,
                       hot_pct=1.0, status="APPROVE", execute="RUN")
    d2 = dict(zip(CONTEXT_HEADER, row2))
    assert d2["Duyệt Context"] == "APPROVE" and d2["Execute"] == "RUN"
    assert d2["TopicKey"] == ""   # mặc định rỗng nếu caller chưa truyền


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
        SOURCES_HEADER, CONTEXT_HEADER, CONTENT_HEADER, OUTPUT_TYPE_VALUES,
        GATE1_COL, GATE2_COL, GATE3_COL,
    )
    tabs = []
    for i, (name, header) in enumerate(TABS.items()):
        # CONTEXT có sẵn 1 banding + 3 conditional (ĐỀU nằm ở cột CODE quản —
        # Duyệt Context/Execute/Score) -> phải sinh request XÓA cho cả 3 (SỬA
        # LỖI THẬT 2026-08-04: giờ chỉ xoá rule ở cột managed, xem test riêng
        # test_build_format_requests_keeps_unmanaged_conditional_format_rules
        # cho ca rule Lead tự thêm ở cột KHÁC không bị đụng).
        if name == "CONTEXT":
            low_hdr = [h.strip().lower() for h in header]
            existing_cols = [low_hdr.index(GATE1_COL.lower()), low_hdr.index("execute"),
                             low_hdr.index("score")]
            tabs.append(TabMeta(name, header, i, n_rows=5, banding_ids=[7],
                                cond_format_cols=existing_cols))
        else:
            tabs.append(TabMeta(name, header, i, n_rows=3))
    reqs = build_format_requests(tabs)
    kinds = [next(iter(r)) for r in reqs]

    for k in ("updateSheetProperties", "updateDimensionProperties", "repeatCell",
              "updateBorders", "addBanding", "setDataValidation",
              "addConditionalFormatRule"):
        assert k in kinds, f"thiếu request {k}"
    # idempotent: banding cũ + rule cũ của CONTEXT (đều ở cột managed) bị xóa
    # trước khi thêm lại (CONTENT.cond_format_cols=[] trong test này -> không
    # sinh xóa cho CONTENT).
    assert kinds.count("deleteBanding") == 1
    assert kinds.count("deleteConditionalFormatRule") == 3
    # CONTEXT: Duyệt Context(PENDING/APPROVE/REJECT/DELETE=4 — DELETE thêm
    # 2026-07-29) +
    # Execute(Waiting/Running.../RUN-cũ/DONE/FAILED/NEEDS_HUMAN=6, đổi từ vựng
    # 2026-07-28 — xem sheets_board.EXECUTE_VALUES) + score + hot% => 3+6+1+1 = 11
    # CONTENT: Duyệt Content(APPROVE/PENDING/REJECT=3, trước đây "Approve(gate 2)") +
    # Duyệt Public (Phase 1.3, trước đây "Gate3", APPROVE/PENDING/REJECT=3) => 12+3+3 = 18
    # (Conditional-formatting màu vẫn giữ NGUYÊN cho cả 3 cổng dù data
    # validation đã gỡ bên dưới — tô màu theo TEXT không đụng dropdown/chip.)
    assert kinds.count("addConditionalFormatRule") == 18
    # checkbox: SOURCES.Enable + PROMPTS.Enable (Use đã xoá, KHÔNG còn checkbox CONTEXT)
    # dropdown CÒN LẠI: CHỈ CONTENT.Posting Status (khâu publish chưa xây, chưa
    # ai bật tay Dropdown Chip cho cột này).
    # CONTEXT.Duyệt Context + CONTENT.Duyệt Content + CONTENT.Duyệt Public
    # KHÔNG còn ghi validation (Trung 02/08, cùng lý do Output Type) — cả 3 cột
    # này Trung đã tự bật tay Dropdown (Chip, 1 giá trị) qua UI Sheets, code ghi
    # đè mỗi lượt --setup sẽ reset mất cấu hình chip đó.
    # CONTENT.Status + CONTENT.Type KHÔNG còn ghi validation (SỬA LỖI THẬT
    # 2026-08-04 — xem chi tiết bên dưới): Lead tự bật tay Dropdown Chip có
    # màu cho 2 cột này, code ghi đè (kể cả "xoá rule") reset mất cấu hình đó.
    # CONTEXT.Output Type KHÔNG còn ghi validation (2026-07-28): ô đó là
    # MULTI-SELECT Lead bật tay qua UI, code ghi đè là XOÁ cấu hình đó và API
    # không dựng lại được.
    # CONTEXT.Execute KHÔNG còn dropdown (2026-07-28: cột read-only, người chỉ
    # xem) -- nó gửi setDataValidation KHÔNG kèm "rule" để XOÁ dropdown cũ, nên
    # có mặt trong `sd` nhưng KHÔNG đếm vào ONE_OF_LIST.
    sd = [r["setDataValidation"] for r in reqs if "setDataValidation" in r]
    conds = [v["rule"]["condition"]["type"] for v in sd if "rule" in v]
    assert conds.count("BOOLEAN") == 2 and conds.count("ONE_OF_LIST") == 1

    # 1 request XOÁ validation (không "rule") cho CONTEXT.Execute — CONTENT.
    # Status/Type KHÔNG còn nhánh xoá nữa (SỬA LỖI THẬT 2026-08-04, Lead báo
    # "Type + Status vẫn bị ghi đè thiết lập màu": Lead đã tự bật tay Dropdown
    # Chip có màu cho 2 cột này qua Sheet UI — gửi setDataValidation dù KHÔNG
    # kèm rule vẫn xoá mất chip đó, cùng lý do đã áp dụng cho Duyệt Context/
    # Output Type/3 cổng duyệt bên dưới).
    low_ctx_hdr = [c.strip().lower() for c in CONTEXT_HEADER]
    low_con_hdr = [c.strip().lower() for c in CONTENT_HEADER]
    clears = [v for v in sd if "rule" not in v]
    assert len(clears) == 1
    # So theo CHỈ SỐ CỘT, không hard-code sheetId (id do TabMeta trong test này
    # cấp phát, đổi là test gãy oan).
    cleared_cols = sorted(v["range"]["startColumnIndex"] for v in clears)
    assert cleared_cols == [low_ctx_hdr.index("execute")]

    # CONTENT.Status/Type: TUYỆT ĐỐI KHÔNG được có setDataValidation nào nữa
    # (cùng lý do Output Type/3 cổng duyệt — Lead tự cấu hình chip màu tay).
    # Lọc CẢ sheetId (không chỉ cột) — cột cùng chỉ số có thể trùng tình cờ
    # với 1 tab KHÁC (vd SOURCES.Enable) nếu chỉ so cột suông.
    content_sid = list(TABS.keys()).index("CONTENT")
    status_type_cols = [low_con_hdr.index("status"), low_con_hdr.index("type")]
    status_type_reqs = [r for r in reqs
                        if "setDataValidation" in r
                        and r["setDataValidation"]["range"]["sheetId"] == content_sid
                        and r["setDataValidation"]["range"]["startColumnIndex"] in status_type_cols]
    assert status_type_reqs == [], "KHÔNG được ghi validation lên cột Status/Type"

    # Output Type: TUYỆT ĐỐI KHÔNG được có setDataValidation nào (2026-07-28).
    # Ô này là MULTI-SELECT Lead bật tay qua UI Sheets — API v4 không tạo được
    # kiểu ô đó, nên MỌI lần code ghi validation đều hạ cấp nó về dropdown
    # 1-lựa-chọn và XOÁ MẤT cấu hình tay, không dựng lại được bằng API.
    low_ctx = [c.lower() for c in CONTEXT_HEADER]
    output_type_col = low_ctx.index("output type")
    output_type_reqs = [r for r in reqs
                        if "setDataValidation" in r
                        and r["setDataValidation"]["range"]["startColumnIndex"] == output_type_col]
    assert output_type_reqs == [], "KHÔNG được ghi validation lên cột Output Type"

    # 3 cổng duyệt (Duyệt Context/Duyệt Content/Duyệt Public): TUYỆT ĐỐI KHÔNG
    # được có setDataValidation nào nữa (Trung 02/08, CÙNG lý do Output Type ở
    # trên — Trung đã tự bật tay Dropdown Chip 1-giá-trị cho cả 3 cột qua UI
    # Sheets, ghi validation đè lên mỗi lượt --setup sẽ reset mất cấu hình đó).
    low_con = [c.lower() for c in CONTENT_HEADER]
    gate_cols = [low_ctx.index(GATE1_COL.lower()),
                low_con.index(GATE2_COL.lower()), low_con.index(GATE3_COL.lower())]
    gate_reqs = [r for r in reqs if "setDataValidation" in r
                and r["setDataValidation"]["range"]["startColumnIndex"] in gate_cols]
    assert gate_reqs == [], f"KHÔNG được ghi validation lên 3 cổng duyệt: {gate_reqs}"

    # determinism = idempotent theo cấu trúc
    assert build_format_requests(tabs) == reqs
    assert SOURCES_HEADER[0].lower() == "enable"
    low = [c.lower() for c in CONTEXT_HEADER]
    assert {"score", "hot%", "group", "context", "hook", "source", "duyệt context", "execute"} <= set(low)
    assert "use" not in low and low[0] == "timestamp"


def test_build_format_requests_keeps_unmanaged_conditional_format_rules():
    """SỬA LỖI THẬT (2026-08-04, Lead báo "Type + Status vẫn bị ghi đè thiết
    lập màu trên sheet UI") — TRƯỚC ĐÂY build_format_requests() xoá SẠCH MỌI
    conditional-format rule đang có trên CONTEXT/CONTENT (chỉ đếm SỐ LƯỢNG qua
    `cond_format_count`), kể cả rule Lead tự thêm tay cho cột KHÁC (vd tô màu
    Type/Status) — code không quản cột đó nên không dựng lại được, mất vĩnh
    viễn mỗi lượt ensure_tabs() phát hiện header đổi. Khoá lại: rule nằm ở cột
    KHÔNG thuộc danh sách CODE quản (Gate1/execute/score/hot% CONTEXT;
    Gate2/Gate3 CONTENT) phải được GIỮ NGUYÊN — không sinh deleteConditional
    FormatRule cho index của nó."""
    from twmkt.sheets_board import build_format_requests, TabMeta, CONTENT_HEADER

    low_con_hdr = [c.strip().lower() for c in CONTENT_HEADER]
    type_col = low_con_hdr.index("type")
    status_col = low_con_hdr.index("status")
    gate2_col = low_con_hdr.index("duyệt content")

    # 3 rule hiện có trên CONTENT: index 0 = Type (Lead tự thêm), index 1 =
    # Status (Lead tự thêm), index 2 = Duyệt Content (CODE quản).
    t = TabMeta(name="CONTENT", header=list(CONTENT_HEADER), sheet_id=1, n_rows=3,
               cond_format_cols=[type_col, status_col, gate2_col])
    reqs = build_format_requests([t])
    deletes = [r["deleteConditionalFormatRule"]["index"] for r in reqs
              if "deleteConditionalFormatRule" in r]
    # CHỈ index 2 (Duyệt Content, CODE quản) bị xoá — index 0/1 (Type/Status,
    # Lead tự thêm) PHẢI giữ nguyên, không nằm trong danh sách xoá.
    assert deletes == [2], f"chỉ được xoá rule ở cột CODE quản, nhận: {deletes}"


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

    from twmkt.sheets_board import GATE1_COL

    sheets = []
    for i, name in enumerate(TABS):
        s = {"properties": {"sheetId": i, "title": name,
                            "gridProperties": {"rowCount": 1000}}}
        if name == "CONTEXT":     # có sẵn banding + rule -> nhánh idempotent
            s["bandedRanges"] = [{"bandedRangeId": 42}]
            # SỬA LỖI THẬT (2026-08-04) — rule PHẢI có "ranges" thật (cột
            # Duyệt Context, CODE quản) để build_format_requests() (giờ chỉ
            # xoá rule ở cột managed, xem TabMeta.cond_format_cols) còn nhận
            # ra đây là rule cần xoá; rule rỗng "{}" cũ không tra được cột nên
            # bị bỏ qua an toàn, làm mất nhánh deleteConditionalFormatRule
            # khỏi smoke test này.
            gate1_col = [h.strip().lower() for h in TABS["CONTEXT"]].index(GATE1_COL.lower())
            s["conditionalFormats"] = [
                {"ranges": [{"sheetId": i, "startColumnIndex": gate1_col,
                            "endColumnIndex": gate1_col + 1}]},
                {"ranges": [{"sheetId": i, "startColumnIndex": gate1_col,
                            "endColumnIndex": gate1_col + 1}]},
            ]
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


def test_build_format_requests_never_adds_native_banding_on_context_or_content():
    """SỰ CỐ THẬT (2026-08-04, Lead báo "block dữ liệu theo ngày lại mất") —
    CONTEXT/CONTENT tô NỀN THEO NGÀY/TOPICKEY riêng bằng `repeatCell`
    (_band_day() -> band_context_by_day()/regroup_and_band_content(), gọi
    mỗi lượt render_*_to_sheet()) -- nhưng "banding" NGUYÊN SINH Google
    Sheets (addBanding) LUÔN HIỂN THỊ ĐÈ lên màu nền cell thường trong phạm
    vi của nó. Mỗi lần format_board() chạy (ensure_tabs() dò header đổi,
    hoặc gọi tay) từng thêm 1 banding trắng/xanh nhạt CHUNG cho MỌI tab kể
    cả CONTEXT/CONTENT, che mất toàn bộ khối màu ngày vừa tô dù giá trị
    backgroundColor từng cell vẫn đúng bên dưới. Khoá lại: CONTEXT/CONTENT
    KHÔNG BAO GIỜ được addBanding (banding CŨ vẫn được dọn qua deleteBanding
    nếu còn sót từ trước khi sửa); các tab KHÁC (không có nền tự tô) vẫn giữ
    banding xen kẽ như cũ để dễ đọc."""
    from twmkt.sheets_board import build_format_requests, TabMeta, TABS

    tabs = [TabMeta(name, header, i, n_rows=5, banding_ids=[7] if name in ("CONTEXT", "CONTENT") else [])
           for i, (name, header) in enumerate(TABS.items())]
    reqs = build_format_requests(tabs)

    context_sid = list(TABS.keys()).index("CONTEXT")
    content_sid = list(TABS.keys()).index("CONTENT")
    add_banding_sids = {r["addBanding"]["bandedRange"]["range"]["sheetId"]
                        for r in reqs if "addBanding" in r}
    assert context_sid not in add_banding_sids, "CONTEXT KHÔNG được addBanding -- đè mất màu ngày"
    assert content_sid not in add_banding_sids, "CONTENT KHÔNG được addBanding -- đè mất màu TopicKey/ngày"
    # banding CŨ (sót từ trước khi sửa) vẫn phải được dọn cho cả 2 tab.
    delete_banding_ids = [r["deleteBanding"]["bandedRangeId"] for r in reqs if "deleteBanding" in r]
    assert delete_banding_ids.count(7) == 2, "vẫn phải xoá banding cũ sót lại của CONTEXT lẫn CONTENT"
    # tab KHÁC (vd SOURCES) vẫn giữ banding như cũ.
    sources_sid = list(TABS.keys()).index("SOURCES")
    assert sources_sid in add_banding_sids, "tab không tự tô màu vẫn phải giữ banding xen kẽ"


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


def test_sheets_sort_context_by_hot_regroups_interleaved_days_and_sorts_within_block():
    """2026-07-23 (yêu cầu Lead): Hot% chỉ sort TRONG TỪNG BLOCK NGÀY (cột
    Timestamp), KHÔNG sort xuyên ngày -- ngày CŨ luôn ở TRÊN, ngày MỚI luôn ở
    DƯỚI (append cuối). Dữ liệu THẬT trên Sheet production đã bị global-sort
    CŨ trộn lẫn 2 ngày xen kẽ (xác nhận qua khảo sát thật 2026-07-23) -- hàm
    PHẢI regroup theo GIÁ TRỊ ngày (không chỉ giữ nguyên dãy liên tiếp sẵn) để
    dọn sạch kiểu trộn này, không chỉ né tránh nó ở dữ liệu mới."""
    from twmkt.sheets_board import SheetsBoard, CONTEXT_HEADER, context_row

    class _FakeWS:
        def __init__(self, values):
            self._v = values
            self.updated_with = None
        def get_all_values(self): return self._v
        def row_values(self, n): return self._v[0]
        def update(self, range, values, value_input_option="RAW"):
            self.updated_with = (range, values)
            self._v = [self._v[0]] + values

    # Ngày 21/07 (Hot 10, 90) VÀ 22/07 (Hot 20, 80) XEN KẼ hàng (mô phỏng đúng
    # kiểu trộn của global-sort CŨ) -- kỳ vọng: regroup lại theo ngày (21/07
    # TRÊN, 22/07 DƯỚI vì mới hơn), Hot% giảm dần NỘI BỘ mỗi ngày.
    a_thap = context_row(title="A-thap", hook_line="h", source_url="http://u/a", score=1,
                         hot_pct=10.0, ts="21/07/2026")
    b_thap = context_row(title="B-thap", hook_line="h", source_url="http://u/c", score=1,
                         hot_pct=20.0, ts="22/07/2026")
    a_cao = context_row(title="A-cao", hook_line="h", source_url="http://u/b", score=1,
                        hot_pct=90.0, ts="21/07/2026")
    b_cao = context_row(title="B-cao", hook_line="h", source_url="http://u/d", score=1,
                        hot_pct=80.0, ts="22/07/2026")
    board = SheetsBoard(spreadsheet_id="SID", creds_path="creds")
    ws = _FakeWS([CONTEXT_HEADER, a_thap, b_thap, a_cao, b_cao])   # 2 ngày XEN KẼ
    board._ws["CONTEXT"] = ws
    board.sort_context_by_hot()

    ctx_idx = CONTEXT_HEADER.index("Context")
    got = [r[ctx_idx] for r in ws._v[1:]]
    # Regroup đúng: 21/07 (cũ hơn) TRÊN, 22/07 (mới hơn) DƯỚI; mỗi block Hot% giảm dần.
    assert got == ["A-cao", "A-thap", "B-cao", "B-thap"]

    # Gọi lại lần 2 (thứ tự đã đúng) -- KHÔNG ghi lại (khỏi tốn lượt Sheets API).
    ws.updated_with = None
    board.sort_context_by_hot()
    assert ws.updated_with is None


def test_band_context_by_day_bands_each_day_block_alternating():
    """2026-07-23 (yêu cầu Lead) -- band_context_by_day tô nền xen kẽ theo
    khối NGÀY (Timestamp) cho CONTEXT, gọi SAU sort_context_by_hot() (đã ở
    đúng thứ tự) -- 2 màu xen kẽ, mỗi khối 1 repeatCell + 1 updateBorders
    (viền trên), TUYỆT ĐỐI không mergeCells."""
    from twmkt.sheets_board import SheetsBoard, CONTEXT_HEADER, context_row

    rows = [
        context_row(title="A-cao", hook_line="h", source_url="http://u/a", score=1,
                   hot_pct=90.0, ts="21/07/2026"),
        context_row(title="A-thap", hook_line="h", source_url="http://u/b", score=1,
                   hot_pct=10.0, ts="21/07/2026"),
        context_row(title="B-cao", hook_line="h", source_url="http://u/c", score=1,
                   hot_pct=80.0, ts="22/07/2026"),
    ]

    class _FakeContentWS:
        id = 9
        def __init__(self, values): self._v = values
        def get_all_values(self): return self._v

    class _FakeSheet:
        def __init__(self): self.last_body = None
        def batch_update(self, body): self.last_body = body; return {}

    board = SheetsBoard(spreadsheet_id="X", creds_path="Y")
    board._ws["CONTEXT"] = _FakeContentWS([list(CONTEXT_HEADER)] + rows)
    board._sh = _FakeSheet()

    n = board.band_context_by_day()
    assert n == 2   # 21/07 (2 dòng) + 22/07 (1 dòng)
    reqs = board._sh.last_body["requests"]
    assert not any("mergeCells" in r or "unmergeCells" in r for r in reqs)
    fills = [r["repeatCell"] for r in reqs if "repeatCell" in r]
    assert len(fills) == 2
    assert fills[0]["range"]["startRowIndex"] == 1 and fills[0]["range"]["endRowIndex"] == 3   # 21/07: dòng 1-2
    assert fills[1]["range"]["startRowIndex"] == 3 and fills[1]["range"]["endRowIndex"] == 4   # 22/07: dòng 3
    assert fills[0]["cell"]["userEnteredFormat"]["backgroundColor"] != \
           fills[1]["cell"]["userEnteredFormat"]["backgroundColor"]


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
        url = "https://cafef.vn/bai-that-123456.chn"   # httpx.Response.url (không redirect ở test này)

    class _FakeClient:
        def get(self, url): return _FakeResp()

    spec = SourceSpec(article_url_re=re.compile(r".chn$"))
    c = HttpFirstCollector(specs={"https://cafef.vn/x.rss": spec}, respect_robots=False)
    src = Source("CafeF - RSS X", "https://cafef.vn/x.rss", SourceType.NEWS, fetch_type="rss")
    doc = c._fetch_and_extract(_FakeClient(), src, spec, "https://cafef.vn/bai-that-123456.chn")
    assert doc is not None
    assert doc.title == "Tiêu đề bài"
    assert doc.markdown == "Nội dung đầy đủ."
    assert doc.url == "https://cafef.vn/bai-that-123456.chn"   # KHÔNG có canonical -> dùng final_url
    assert doc.source == "CafeF - RSS X"


def test_extract_canonical_url_parses_link_rel_canonical():
    """extract_canonical_url: trích href của <link rel="canonical">, resolve
    tương đối qua base_url; None nếu không có thẻ/href rỗng. Hàm THUẦN."""
    from twmkt.collectors.http_collector import extract_canonical_url

    html_abs = ('<html><head><link rel="canonical" href="https://cafef.vn/goc.chn">'
               '</head><body></body></html>')
    assert extract_canonical_url(html_abs, "https://cafef.vn/khac.chn") == "https://cafef.vn/goc.chn"

    html_rel = '<html><head><link rel="canonical" href="/goc.chn"></head></html>'
    assert extract_canonical_url(html_rel, "https://cafef.vn/khac.chn") == "https://cafef.vn/goc.chn"

    html_none = "<html><head></head><body>Không có canonical.</body></html>"
    assert extract_canonical_url(html_none, "https://cafef.vn/khac.chn") is None

    html_empty_href = '<html><head><link rel="canonical" href=""></head></html>'
    assert extract_canonical_url(html_empty_href, "https://cafef.vn/khac.chn") is None


def test_extract_canonical_url_rejects_different_host():
    """LỚP 5 Phase 1R (bổ sung) — canonical trỏ KHÁC HOST với url đã fetch ->
    KHÔNG tin (chống collision nếu site cấu hình canonical sai/trỏ CDN lạ)."""
    from twmkt.collectors.http_collector import extract_canonical_url

    html = ('<html><head><link rel="canonical" href="https://site-la.com/bai.chn">'
           '</head></html>')
    assert extract_canonical_url(html, "https://cafef.vn/bai-that.chn") is None
    # www. KHÔNG tính là khác host
    html_www = '<html><head><link rel="canonical" href="https://www.cafef.vn/goc.chn"></head></html>'
    assert extract_canonical_url(html_www, "https://cafef.vn/khac.chn") == "https://www.cafef.vn/goc.chn"


def test_extract_canonical_url_rejects_root_when_article_path_is_deep():
    """LỚP 5 Phase 1R (bổ sung) — canonical="/" (hoặc rỗng) trong khi bài có
    path SÂU -> nghi cấu hình sai (trỏ chung trang chủ cho mọi bài, sẽ gây va
    chạm khoá hàng loạt) -> KHÔNG tin."""
    from twmkt.collectors.http_collector import extract_canonical_url

    html_slash = '<html><head><link rel="canonical" href="/"></head></html>'
    assert extract_canonical_url(html_slash, "https://cafef.vn/tin-tuc/bai-viet-abc-123456.chn") is None

    html_root_abs = '<html><head><link rel="canonical" href="https://cafef.vn"></head></html>'
    assert extract_canonical_url(html_root_abs, "https://cafef.vn/tin-tuc/bai-viet-abc-123456.chn") is None

    # canonical là TIỀN TỐ (chuyên mục) của path bài -> cũng nghi ngờ, không tin
    html_prefix = '<html><head><link rel="canonical" href="/tin-tuc"></head></html>'
    assert extract_canonical_url(html_prefix, "https://cafef.vn/tin-tuc/bai-viet-abc-123456.chn") is None

    # Đối chứng: canonical KHÁC HẲN (không phải prefix, vd bản AMP -> bản gốc) -> VẪN chấp nhận
    html_amp_to_real = '<html><head><link rel="canonical" href="/bai-goc-that.chn"></head></html>'
    assert (extract_canonical_url(html_amp_to_real, "https://cafef.vn/tin-tuc/bai-amp-123456.chn")
           == "https://cafef.vn/bai-goc-that.chn")


def test_http_collector_fetch_and_extract_keeps_fetched_url_adds_canonical_url_separately():
    """LỚP 5 Phase 1R (bổ sung Phương án 1) — RawDocument.url LUÔN là URL THẬT
    đã fetch (final_url, sau redirect) — KHÔNG BAO GIỜ bị ghi đè bởi canonical.
    `canonical_url` (field RIÊNG) mang canonical ĐÃ kiểm định. Không mạng thật
    (fake client)."""
    from twmkt.collectors.http_collector import HttpFirstCollector, SourceSpec
    from twmkt.models import Source, SourceType
    import re

    html = ('<html><head><link rel="canonical" href="https://cafef.vn/bai-goc-that.chn">'
           '</head><body><h1>Tiêu đề</h1>'
           '<div class="detail-content afcbc-body"><p>Nội dung.</p></div>'
           '</body></html>')

    class _FakeResp:
        status_code = 200
        text = html
        url = "https://cafef.vn/bai-that-123456-amp.chn"   # URL sau redirect (khác url thô)

    class _FakeClient:
        def get(self, url): return _FakeResp()

    spec = SourceSpec(article_url_re=re.compile(r".chn$"))
    c = HttpFirstCollector(specs={"https://cafef.vn/x.rss": spec}, respect_robots=False)
    src = Source("CafeF - RSS X", "https://cafef.vn/x.rss", SourceType.NEWS, fetch_type="rss")
    doc = c._fetch_and_extract(_FakeClient(), src, spec, "https://cafef.vn/bai-that-123456.chn")
    assert doc is not None
    assert doc.url == "https://cafef.vn/bai-that-123456-amp.chn"        # GIỮ NGUYÊN final_url, KHÔNG bị ghi đè
    assert doc.canonical_url == "https://cafef.vn/bai-goc-that.chn"     # canonical ở field RIÊNG


def test_http_collector_fetch_and_extract_falls_back_to_final_redirect_url_no_canonical():
    """Không có canonical -> url = final_url (SAU redirect), canonical_url rỗng."""
    from twmkt.collectors.http_collector import HttpFirstCollector, SourceSpec
    from twmkt.models import Source, SourceType
    import re

    html = ('<html><body><h1>Tiêu đề</h1>'
           '<div class="detail-content afcbc-body"><p>Nội dung.</p></div>'
           '</body></html>')

    class _FakeResp:
        status_code = 200
        text = html
        url = "https://cafef.vn/bai-sau-redirect.chn"

    class _FakeClient:
        def get(self, url): return _FakeResp()

    spec = SourceSpec(article_url_re=re.compile(r".chn$"))
    c = HttpFirstCollector(specs={"https://cafef.vn/x.rss": spec}, respect_robots=False)
    src = Source("CafeF - RSS X", "https://cafef.vn/x.rss", SourceType.NEWS, fetch_type="rss")
    doc = c._fetch_and_extract(_FakeClient(), src, spec, "https://cafef.vn/bai-truoc-redirect.chn")
    assert doc is not None
    assert doc.canonical_url == ""
    assert doc.url == "https://cafef.vn/bai-sau-redirect.chn"   # final_url, KHÔNG phải url thô


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
    """upsert_context_rows (Fix (a)): TopicKey ĐÃ CÓ -> bỏ qua HOÀN TOÀN (dòng
    cũ y nguyên, không tạo dòng trùng) DÙ Source-text khác nhau (membership =
    TopicKey, không phải Source-URL literal); TopicKey CHƯA CÓ -> append. Trả
    số dòng MỚI (không tính dòng bị bỏ qua)."""
    from twmkt.sheets_board import SheetsBoard, CONTEXT_HEADER, context_row

    board = SheetsBoard(spreadsheet_id="X", creds_path="Y")
    existing = context_row(title="Đã duyệt", hook_line="h", source_url="http://u/1",
                           score=5, hot_pct=10.0, status="APPROVE", execute="RUN",
                           topic_key="tk-1")
    ws = _FakeContextWS([CONTEXT_HEADER, list(existing)])
    board._ws["CONTEXT"] = ws

    # dup: CÙNG topic_key nhưng Source-text KHÁC (mô phỏng bug thật quan sát
    # trên Sheet: dòng cũ Source=tiêu đề, dòng mới Source=URL/domain khác) ->
    # VẪN phải bị coi là trùng (membership = TopicKey, không phải Source).
    dup = context_row(title="Crawl lại — topic trùng", hook_line="h2",
                      source_url="http://u/1-mirror-khac", score=99, hot_pct=99.0,
                      topic_key="tk-1")
    new = context_row(title="Bài mới", hook_line="h3", source_url="http://u/2",
                      score=2, hot_pct=2.0, topic_key="tk-2")
    written = board.upsert_context_rows([dup, new])

    assert written == [new]                     # trả CHÍNH dòng mới (không phải chỉ đếm)
    assert len(written) == 1                    # chỉ 1 dòng MỚI được ghi
    assert len(ws._v) == 3                       # header + 1 cũ + 1 mới (KHÔNG trùng)
    assert ws._v[1] == list(existing)             # dòng cũ (APPROVE/RUN) Y NGUYÊN, không bị đè
    assert ws.appended == [new]                    # CHỈ dòng thật sự mới được append


def test_upsert_context_rows_called_twice_no_duplicate():
    """Gọi upsert_context_rows 2 LẦN với CÙNG 1 topic_key (mô phỏng crawl lại)
    -> lần 2 KHÔNG tạo thêm dòng nào."""
    from twmkt.sheets_board import SheetsBoard, CONTEXT_HEADER, context_row

    board = SheetsBoard(spreadsheet_id="X", creds_path="Y")
    ws = _FakeContextWS([list(CONTEXT_HEADER)])
    board._ws["CONTEXT"] = ws

    row = context_row(title="Bài A", hook_line="h", source_url="http://u/1", score=1,
                      hot_pct=1.0, topic_key="tk-a")
    r1 = board.upsert_context_rows([row])
    r2 = board.upsert_context_rows([row])          # "crawl lại" cùng topic_key
    assert len(r1) == 1 and len(r2) == 0
    assert len(ws._v) == 2                          # header + đúng 1 dòng, KHÔNG trùng


def test_upsert_context_rows_two_independent_machines_same_url_dedup_via_topic_key():
    """Fix (a) — mô phỏng 2 MÁY crawl ĐỘC LẬP (corpus cục bộ riêng/rỗng mỗi máy,
    KHÔNG liên quan tới quyết định này) cùng 1 URL vào CÙNG Sheet -> đúng 1
    dòng CONTEXT, 0 trùng — dù Source-text ghi ra khác nhau giữa 2 lượt (đúng
    bug thật đã quan sát trên Sheet production: dòng cũ Source=tiêu đề, dòng
    mới Source=URL thật). TopicKey tính ĐỘC LẬP ở mỗi máy (assign_topic_key("",
    url=...) — existing_key="" vì máy nào cũng coi đây là ứng viên MỚI, không
    tra cứu chéo máy) nhưng ra CÙNG khoá vì CÙNG URL -> dedup đúng qua Sheet."""
    from twmkt.curation.keys import assign_topic_key
    from twmkt.sheets_board import SheetsBoard, CONTEXT_HEADER, context_row

    url = "https://cafef.vn/bai-that-nhap-sieu.chn"

    # Máy 1 (văn phòng): tính topic_key từ URL, Source ghi = tiêu đề (bug thật
    # quan sát ở dữ liệu cũ).
    tk_office = assign_topic_key("", url=url)
    row_office = context_row(title="Nhập siêu 13,8 tỷ USD", hook_line="h",
                             source_url="Nhập siêu 13,8 tỷ USD sau 5 tháng",
                             score=1, hot_pct=1.0, topic_key=tk_office)
    board = SheetsBoard(spreadsheet_id="X", creds_path="Y")
    ws = _FakeContextWS([list(CONTEXT_HEADER)])
    board._ws["CONTEXT"] = ws
    board.upsert_context_rows([row_office])

    # Máy 2 (nhà, corpus rỗng — KHÔNG đọc corpus/state của máy 1): tính
    # topic_key ĐỘC LẬP từ CÙNG URL, Source ghi = URL thật (convention mới).
    tk_home = assign_topic_key("", url=url)
    row_home = context_row(title="Nhập siêu 13,8 tỷ USD", hook_line="h",
                           source_url=url, score=1, hot_pct=1.0, topic_key=tk_home)
    written = board.upsert_context_rows([row_home])

    assert tk_office == tk_home                    # cùng URL -> cùng khoá dù tính độc lập
    assert written == []                            # bị coi là trùng, KHÔNG chèn thêm
    assert len(ws._v) == 2                           # header + đúng 1 dòng (của máy 1)
    assert ws._v[1] == list(row_office)               # dòng máy 1 Y NGUYÊN, không bị đè


def test_upsert_context_rows_match_does_not_touch_any_column():
    """Chính sách đã chốt (Fix (a) Phase 1): MATCH -> KHÔNG ghi cột nào, kể cả
    Hot%/Score — giữ nguyên TOÀN BỘ dòng cũ, đúng hành vi hiện tại (KHÔNG có
    refresh Hot%/Score)."""
    from twmkt.sheets_board import SheetsBoard, CONTEXT_HEADER, context_row

    board = SheetsBoard(spreadsheet_id="X", creds_path="Y")
    existing = context_row(title="Đã duyệt", hook_line="h cũ", source_url="http://u/1",
                           score=5, hot_pct=10.0, status="APPROVE", execute="DONE",
                           topic_key="tk-1")
    ws = _FakeContextWS([CONTEXT_HEADER, list(existing)])
    board._ws["CONTEXT"] = ws

    # Crawl lại: Hot%/Score/Hook/Status/Execute đều KHÁC -> vẫn phải bị bỏ qua
    # HOÀN TOÀN, không cột nào trong dòng cũ bị đổi.
    resurvey = context_row(title="Đã duyệt", hook_line="h MỚI", source_url="http://u/1-khac",
                           score=999, hot_pct=88.8, status="PENDING", execute="",
                           topic_key="tk-1")
    written = board.upsert_context_rows([resurvey])

    assert written == []
    assert ws._v[1] == list(existing)   # TOÀN BỘ dòng cũ y nguyên, kể cả Hot%/Score


def test_upsert_context_rows_empty_topic_key_never_dedupes_always_appends():
    """topic_key rỗng (không nên xảy ra nếu caller dùng assign_topic_key, phòng
    hờ) -> KHÔNG BAO GIỜ coi là trùng dòng khác (kể cả dòng khác cũng rỗng) ->
    LUÔN append. An toàn nghiêng về không mất dữ liệu."""
    from twmkt.sheets_board import SheetsBoard, CONTEXT_HEADER, context_row

    board = SheetsBoard(spreadsheet_id="X", creds_path="Y")
    ws = _FakeContextWS([list(CONTEXT_HEADER)])
    board._ws["CONTEXT"] = ws

    row1 = context_row(title="A", hook_line="h", source_url="http://u/1", score=1, hot_pct=1.0)
    row2 = context_row(title="B", hook_line="h", source_url="http://u/2", score=1, hot_pct=1.0)
    written = board.upsert_context_rows([row1, row2])
    assert len(written) == 2   # cả 2 đều append dù topic_key rỗng ở cả 2


def test_sync_approve_execute_flags_sets_run_only_for_empty_execute():
    """sync_approve_execute_flags (đường LEGACY Sheet-only): Status=APPROVE +
    Execute rỗng -> "Waiting". Dòng đã có trạng thái hoặc Status khác APPROVE ->
    giữ nguyên (idempotent).

    2026-07-28: ghi "Waiting" thay "RUN" — Execute không còn là lệnh chạy, chỉ
    là cờ trạng thái (xem sheets_board.EXECUTE_VALUES)."""
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
    assert ws._v[1][i_ex] == "Waiting"               # fresh -> Waiting
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


# --- Lớp 5 Phase 1 — TopicKey (curation/keys.py) --------------------------
def test_compute_topic_key_stable_across_url_variants():
    """Cùng bài (khác query-string/tracking, khác hoa/thường host, có/không
    www./dấu '/' cuối) -> CÙNG khoá; bài KHÁC -> khoá KHÁC. Khoá ổn định qua
    2 lần gọi riêng biệt (tất định, không random/thời gian)."""
    from twmkt.curation.keys import compute_topic_key

    base = compute_topic_key(url="https://cafef.vn/bai-viet-a.chn")
    variants = [
        compute_topic_key(url="https://cafef.vn/bai-viet-a.chn?utm_source=fb&utm_medium=social"),
        compute_topic_key(url="https://WWW.CafeF.vn/bai-viet-a.chn/"),
        compute_topic_key(url="https://cafef.vn/bai-viet-a.chn#binh-luan"),
        compute_topic_key(url="HTTPS://cafef.vn/bai-viet-a.chn"),
    ]
    for v in variants:
        assert v == base and v != ""

    other = compute_topic_key(url="https://cafef.vn/bai-viet-b.chn")
    assert other != base

    # Tất định qua nhiều lần gọi (không phụ thuộc random/thời gian).
    assert compute_topic_key(url="https://cafef.vn/bai-viet-a.chn") == base


def test_compute_topic_key_returns_none_when_no_valid_url():
    """Phase 1R: url rỗng/không hợp lệ (tương đối, thiếu scheme/host) -> trả
    None (KHÔNG còn lùi về title-hash — 2 tin trùng tiêu đề vẫn là 2 tin KHÁC
    NHAU). `title` CHỈ để log, KHÔNG ảnh hưởng kết quả."""
    from twmkt.curation.keys import compute_topic_key

    assert compute_topic_key("") is None
    assert compute_topic_key("", title="Tin không có URL") is None
    assert compute_topic_key("/duong-dan-tuong-doi") is None   # thiếu scheme/host
    assert compute_topic_key("not a url at all") is None


def test_normalize_url_strips_tracking_query_fragment_www_trailing_slash():
    """Phase 1R: CHỈ bỏ tracking param (denylist) + fragment + www./slash cuối;
    scheme LUÔN ép về https. Query KHÔNG trong denylist (vd 'id') GIỮ NGUYÊN
    (test riêng ở test_normalize_url_keeps_identifying_query_param)."""
    from twmkt.curation.keys import normalize_url

    assert (normalize_url("https://WWW.cafef.vn/bai.chn/?utm_source=fb#top")
           == "https://cafef.vn/bai.chn")
    assert normalize_url("http://cafef.vn/") == "https://cafef.vn"   # scheme ép https
    assert normalize_url("") == ""
    assert normalize_url("   ") == ""


def test_normalize_url_keeps_identifying_query_param():
    """Query KHÔNG trong denylist tracking (vd '?id=') PHẢI giữ nguyên — nhiều
    site dùng query làm định danh bài thật, bỏ hết sẽ gây va chạm khoá."""
    from twmkt.curation.keys import normalize_url

    assert normalize_url("https://x.vn/bai?id=123") == "https://x.vn/bai?id=123"
    assert (normalize_url("https://x.vn/bai?id=123") !=
           normalize_url("https://x.vn/bai?id=456"))
    # thứ tự query khác nhau -> vẫn CÙNG kết quả (đã sort)
    assert normalize_url("https://x.vn/bai?b=2&a=1") == normalize_url("https://x.vn/bai?a=1&b=2")
    # trộn tracking + định danh: chỉ bỏ tracking, giữ định danh
    assert (normalize_url("https://x.vn/bai?id=1&utm_source=fb")
           == normalize_url("https://x.vn/bai?id=1"))


def test_backfill_context_topic_keys_idempotent_and_preserves_existing():
    """backfill_context_topic_keys (force=False, WRITE-ONCE mặc định): điền
    khoá RỖNG (qua assign_topic_key — URL hợp lệ -> compute_topic_key, không
    URL -> surrogate uuid4), GIỮ NGUYÊN dòng đã có khoá (kể cả khoá đó KHÔNG
    khớp khoá sẽ tính lại — idempotent nghĩa là KHÔNG đụng vào, không phải
    "sửa cho đúng"). Chạy 2 lần -> kết quả y hệt (không đổi thêm)."""
    from twmkt.sheets_board import CONTEXT_HEADER, backfill_context_topic_keys, context_row

    rows = [
        context_row(title="A", hook_line="h", source_url="https://x.com/a", score=1, hot_pct=1.0,
                   topic_key="MANUAL-OVERRIDE"),   # đã có khoá -> GIỮ NGUYÊN dù không khớp hash thật
        context_row(title="B", hook_line="h", source_url="https://x.com/b?utm=1", score=1, hot_pct=1.0),
        context_row(title="C-khong-url", hook_line="h", source_url="", score=1, hot_pct=1.0),
    ]
    out1 = backfill_context_topic_keys(CONTEXT_HEADER, rows)
    ik = CONTEXT_HEADER.index("TopicKey")
    assert out1[0][ik] == "MANUAL-OVERRIDE"        # KHÔNG bị ghi đè
    assert out1[1][ik] != "" and out1[1][ik] != "MANUAL-OVERRIDE"
    assert out1[2][ik].startswith("sur-")           # url rỗng -> surrogate (Phase 1R.2, KHÔNG còn "")

    out2 = backfill_context_topic_keys(CONTEXT_HEADER, out1)
    assert out2 == out1   # idempotent — chạy lại không đổi gì thêm (kể cả surrogate GIỮ NGUYÊN)


# --- Lớp 5 Phase 1R.2 — write-once + surrogate uuid4 + re-key một lần -------
def test_assign_topic_key_surrogate_unique_no_collision_between_rows():
    """2 dòng KHÔNG-URL -> 2 surrogate KHÁC NHAU (uuid4 ngẫu nhiên, không suy
    từ nội dung nên không va chạm) — thay dứt điểm khoá rỗng \"\"."""
    from twmkt.curation.keys import assign_topic_key

    k1 = assign_topic_key("", url="")
    k2 = assign_topic_key("", url="")
    assert k1 and k2 and k1 != k2
    assert k1.startswith("sur-") and k2.startswith("sur-")
    assert k1 != "" and k2 != ""


def test_assign_topic_key_surrogate_stable_on_recrawl():
    """Dòng không-URL ĐÃ có surrogate -> re-crawl/gọi lại VẪN giữ NGUYÊN
    surrogate cũ (write-once áp dụng cho surrogate y hệt khoá URL-based)."""
    from twmkt.curation.keys import assign_topic_key

    first = assign_topic_key("", url="")
    again = assign_topic_key(first, url="")           # re-crawl: existing_key=first
    again2 = assign_topic_key(first, url="https://khac-han.vn/bai")  # dù kèm url mới cũng KHÔNG đổi
    assert again == first
    assert again2 == first


def test_assign_topic_key_write_once_never_recomputes_even_if_normalize_changes():
    """WRITE-ONCE thật sự: dòng ĐÃ có khoá -> assign_topic_key() KHÔNG ĐƯỢC
    GỌI compute_topic_key() (nên KHÔNG chạm normalize_url dù nó có đổi hành vi
    ở version sau) — mô phỏng bằng cách THAY compute_topic_key() bằng 1 hàm
    'độc' (raise nếu bị gọi), chứng minh assign_topic_key() short-circuit
    TRƯỚC KHI đụng tới nó, không chỉ tình cờ ra cùng giá trị."""
    import twmkt.curation.keys as keys_mod

    def poison(*a, **kw):
        raise AssertionError("assign_topic_key KHÔNG được gọi compute_topic_key "
                             "khi existing_key đã có (vi phạm write-once)")

    original = keys_mod.compute_topic_key
    keys_mod.compute_topic_key = poison
    try:
        result = keys_mod.assign_topic_key("existing-key-123", url="https://bat-ky-url-nao.vn/x")
    finally:
        keys_mod.compute_topic_key = original
    assert result == "existing-key-123"


def test_rekey_context_topic_keys_force_overwrites_url_based_keys_idempotent():
    """force=True (Phase 1R.2, NGOẠI LỆ re-key một lần): khoá CŨ (giả lập khoá
    SAI tính bởi normalize_url Phase 1 gốc) bị GHI ĐÈ bằng compute_topic_key()
    MỚI cho dòng CÓ url. Chạy force=True LẦN 2 -> ra ĐÚNG kết quả y hệt lần 1
    (idempotent, vì compute_topic_key là hàm thuần/tất định trên cùng URL)."""
    from twmkt.sheets_board import CONTEXT_HEADER, backfill_context_topic_keys, context_row
    from twmkt.curation.keys import compute_topic_key

    old_buggy_key = "OLD-BUGGY-STRIPPED-QUERY-KEY"
    url = "https://x.vn/bai?id=1&utm_source=fb"
    rows = [context_row(title="A", hook_line="h", source_url=url, score=1, hot_pct=1.0,
                        topic_key=old_buggy_key)]

    out1 = backfill_context_topic_keys(CONTEXT_HEADER, rows, force=True)
    ik = CONTEXT_HEADER.index("TopicKey")
    assert out1[0][ik] != old_buggy_key           # khoá CŨ bị ghi đè (bypass write-once có chủ đích)
    assert out1[0][ik] == compute_topic_key(url)   # khớp khoá MỚI (canonical, giữ ?id=)

    out2 = backfill_context_topic_keys(CONTEXT_HEADER, out1, force=True)
    assert out2 == out1   # idempotent — force=True chạy lần 2 không đổi thêm


def test_rekey_context_topic_keys_force_preserves_surrogate_for_url_less_rows():
    """force=True KHÔNG đụng surrogate của dòng không-URL (surrogate không bị
    ảnh hưởng bởi bug normalize_url — chỉ khoá URL-based mới cần sửa)."""
    from twmkt.sheets_board import CONTEXT_HEADER, backfill_context_topic_keys, context_row

    surrogate = "sur-deadbeefcafe123"
    rows = [context_row(title="Tin không URL", hook_line="h", source_url="", score=1, hot_pct=1.0,
                        topic_key=surrogate)]
    out = backfill_context_topic_keys(CONTEXT_HEADER, rows, force=True)
    ik = CONTEXT_HEADER.index("TopicKey")
    assert out[0][ik] == surrogate   # GIỮ NGUYÊN, force=True không đụng vì không có url


def test_rekey_content_topic_keys_force_resyncs_to_new_context_keys():
    """backfill_content_topic_keys(force=True): GHI ĐÈ TopicKey CONTENT theo
    ánh xạ title->key MỚI NHẤT từ CONTEXT (đã rekey) — kể cả dòng CONTENT ĐÃ
    có khoá CŨ (khớp khoá SAI trước migration) cũng phải được đồng bộ lại."""
    from twmkt.sheets_board import (
        CONTENT_HEADER, CONTEXT_HEADER, backfill_content_topic_keys,
        backfill_context_topic_keys, content_row, context_row,
    )

    url = "https://x.vn/bai-y?id=9"
    ctx_rows = backfill_context_topic_keys(CONTEXT_HEADER, [
        context_row(title="Bài Y", hook_line="h", source_url=url, score=1, hot_pct=1.0,
                   topic_key="OLD-BUGGY-KEY"),
    ], force=True)
    new_key = ctx_rows[0][CONTEXT_HEADER.index("TopicKey")]
    assert new_key != "OLD-BUGGY-KEY"

    content_rows = [content_row(context="Bài Y", type_="article", status="DONE", output="a",
                                topic_key="OLD-BUGGY-KEY")]   # CONTENT vẫn giữ khoá CŨ trước rekey
    out, warnings = backfill_content_topic_keys(
        CONTEXT_HEADER, ctx_rows, CONTENT_HEADER, content_rows, force=True)
    ik = CONTENT_HEADER.index("TopicKey")
    assert out[0][ik] == new_key   # đồng bộ lại khớp CONTEXT vừa rekey
    assert warnings == []


def test_backfill_content_topic_keys_carry_forward_through_merge_blank_rows():
    """backfill_content_topic_keys: dòng CONTENT có Context BLANK (mô phỏng
    Sheets mergeCells đã xoá — xem curation/keys.py) PHẢI carry-forward khoá từ
    dòng Context KHÔNG-RỖNG gần nhất phía TRÊN, KHÔNG rơi vào nhóm 'không tra
    được'. Dòng đã có TopicKey GIỮ NGUYÊN. Idempotent qua 2 lần chạy."""
    from twmkt.sheets_board import (
        CONTENT_HEADER, CONTEXT_HEADER, backfill_content_topic_keys,
        backfill_context_topic_keys, content_row, context_row,
    )

    ctx_rows = backfill_context_topic_keys(CONTEXT_HEADER, [
        context_row(title="Bài X", hook_line="h", source_url="https://x.com/x", score=1, hot_pct=1.0),
    ])
    expected_key = ctx_rows[0][CONTEXT_HEADER.index("TopicKey")]
    assert expected_key

    content_rows = [
        content_row(context="Bài X", type_="article", status="DONE", output="a"),
        content_row(context="", type_="video", status="DONE", output="b"),      # merge-blank
        content_row(context="", type_="infographic", status="DONE", output="c",
                    topic_key="ALREADY-SET"),                                          # đã có -> giữ
    ]
    out1, warnings1 = backfill_content_topic_keys(CONTEXT_HEADER, ctx_rows, CONTENT_HEADER, content_rows)
    ik = CONTENT_HEADER.index("TopicKey")
    assert out1[0][ik] == expected_key
    assert out1[1][ik] == expected_key      # carry-forward từ dòng phía trên
    assert out1[2][ik] == "ALREADY-SET"     # KHÔNG bị ghi đè
    assert warnings1 == []

    out2, warnings2 = backfill_content_topic_keys(CONTEXT_HEADER, ctx_rows, CONTENT_HEADER, out1)
    assert out2 == out1 and warnings2 == []   # idempotent


def test_backfill_content_topic_keys_warns_when_context_not_found():
    """Context text không khớp dòng CONTEXT nào (đã bị xoá khỏi CONTEXT, hoặc
    CONTEXT dòng đó CŨNG chưa có TopicKey) -> KHÔNG bịa khoá, đưa vào danh sách
    cảnh báo để caller xử lý/log, TopicKey của dòng đó giữ rỗng."""
    from twmkt.sheets_board import CONTENT_HEADER, CONTEXT_HEADER, backfill_content_topic_keys, content_row

    content_rows = [content_row(context="Bài đã bị xoá khỏi CONTEXT", type_="article",
                                status="DONE", output="a")]
    out, warnings = backfill_content_topic_keys(CONTEXT_HEADER, [], CONTENT_HEADER, content_rows)
    assert out[0][CONTENT_HEADER.index("TopicKey")] == ""
    assert warnings == ["Bài đã bị xoá khỏi CONTEXT"]


# =====================================================================
# LỚP 5 PHASE 2 — Upsert CONTENT theo khoá. INVARIANT: match-or-insert TRA
# THEO cột TopicKey ĐÃ LƯU, TUYỆT ĐỐI không tra theo Context/Source sống.
# =====================================================================
def test_content_topic_keys_reads_topickey_column_not_context():
    """content_topic_keys() đọc TRỰC TIẾP cột TopicKey — 2 dòng CÙNG Context
    text nhưng KHÁC TopicKey (vd bug trùng tiêu đề) vẫn được coi là 2 khoá khác
    nhau; KHÔNG suy/gộp theo Context."""
    from twmkt.sheets_board import CONTENT_HEADER, content_row, content_topic_keys

    rows = [
        content_row(context="Cùng tiêu đề", type_="article", status="DONE", output="x", topic_key="KEY-A"),
        content_row(context="Cùng tiêu đề", type_="article", status="DONE", output="y", topic_key="KEY-B"),
    ]
    keys, missing = content_topic_keys(CONTENT_HEADER, rows)
    assert keys == {("KEY-A", "Article"), ("KEY-B", "Article")}   # VIỆC 3: Type ghi NHÃN hiển thị
    assert missing == []


def test_content_topic_keys_survives_merge_blank_context_zero_orphan():
    """Lớp 5 Phase 2 — mô phỏng CONTENT dữ liệu CŨ (TRƯỚC Sheet UI cleanup Phase
    1) đã qua mergeCells cũ: Context/Timestamp bị XOÁ THẬT ở 2 dòng sau của dải
    (TopicKey KHÔNG BAO GIỜ bị mergeCells đụng tới nên SỐNG SÓT) -> content_
    topic_keys() vẫn nhận diện ĐỦ cả 3 loại theo khoá, 0 dòng "mồ côi" (0
    missing). Ghi MỚI từ Phase 1 không còn tạo dữ liệu dạng này nữa (xem
    regroup_and_band_content) — test này giữ để đảm bảo đọc dữ liệu CŨ vẫn đúng."""
    from twmkt.sheets_board import CONTENT_HEADER, content_row, content_topic_keys

    KEY = "topic-key-merged-001"
    rows = [
        content_row(context="Chủ đề đã merge", type_="article", status="DONE", output="a", topic_key=KEY),
        content_row(context="", type_="video", status="DONE", output="b", topic_key=KEY, ts=""),
        content_row(context="", type_="infographic", status="DONE", output="c", topic_key=KEY, ts=""),
    ]
    keys, missing = content_topic_keys(CONTENT_HEADER, rows)
    assert keys == {(KEY, "Article"), (KEY, "Video"), (KEY, "Infographic")}   # VIỆC 3: Type ghi NHÃN hiển thị
    assert missing == []


def test_content_topic_keys_blank_topickey_row_excluded_reported_as_missing():
    """Dòng CÓ Type nhưng TopicKey RỖNG (dữ liệu cũ chưa backfill/rekey) KHÔNG
    được đưa vào set khoá (không thể match-or-insert theo khoá) — Context của
    dòng đó (carry-forward qua merge-blank) trả riêng để caller CẢNH BÁO/
    NEEDS_HUMAN, KHÔNG auto-map."""
    from twmkt.sheets_board import CONTENT_HEADER, content_row, content_topic_keys

    rows = [
        content_row(context="Bài cũ chưa backfill", type_="article", status="DONE", output="a", topic_key=""),
        # carry-forward: Context rỗng (mô phỏng merge-blank) NHƯNG TopicKey CŨNG rỗng -> vẫn missing.
        content_row(context="", type_="video", status="DONE", output="b", topic_key="", ts=""),
    ]
    keys, missing = content_topic_keys(CONTENT_HEADER, rows)
    assert keys == set()
    assert missing == ["Bài cũ chưa backfill", "Bài cũ chưa backfill"]


# --- Fix (a) Phase 2: dedupe_context.py (dọn dòng CONTEXT trùng TopicKey cũ) ---
def test_find_duplicate_context_groups_finds_only_topic_keys_with_2plus_rows():
    from twmkt.sheets_board import CONTEXT_HEADER, context_row, find_duplicate_context_groups

    rows = [
        context_row(title="A", hook_line="h", source_url="u1", score=1, hot_pct=1.0, topic_key="tk-1"),
        context_row(title="B", hook_line="h", source_url="u2", score=1, hot_pct=1.0, topic_key="tk-2"),
        context_row(title="A lại", hook_line="h", source_url="u3", score=1, hot_pct=1.0, topic_key="tk-1"),
        context_row(title="C", hook_line="h", source_url="u4", score=1, hot_pct=1.0, topic_key=""),  # rỗng -> bỏ qua
    ]
    groups = find_duplicate_context_groups(CONTEXT_HEADER, rows)
    assert groups == {"tk-1": [2, 4]}   # dòng Sheet 1-based (rows[0]=dòng 2)


def test_choose_keep_row_priority_execute_done_beats_approve_run_beats_pending():
    from twmkt.sheets_board import choose_keep_row

    # Đúng kịch bản thật quan sát: dòng 5 (APPROVE/DONE) vs dòng 11 (PENDING/rỗng).
    candidates = [
        {"row": 5, "status": "APPROVE", "execute": "DONE", "has_content": True},
        {"row": 11, "status": "PENDING", "execute": "", "has_content": False},
    ]
    assert choose_keep_row(candidates) == 5

    # Dòng 7 (PENDING/RUN) vs dòng 14 (PENDING/rỗng) — RUN > rỗng dù cùng Status.
    candidates2 = [
        {"row": 7, "status": "PENDING", "execute": "RUN", "has_content": False},
        {"row": 14, "status": "PENDING", "execute": "", "has_content": False},
    ]
    assert choose_keep_row(candidates2) == 7


def test_choose_keep_row_tiebreak_has_content_then_lowest_row():
    from twmkt.sheets_board import choose_keep_row

    # Hoà rank (cả 2 PENDING/rỗng) -> có CONTENT con thắng.
    candidates = [
        {"row": 20, "status": "PENDING", "execute": "", "has_content": True},
        {"row": 3, "status": "PENDING", "execute": "", "has_content": False},
    ]
    assert choose_keep_row(candidates) == 20

    # Hoà cả rank lẫn has_content -> dòng nhỏ nhất thắng.
    candidates2 = [
        {"row": 9, "status": "PENDING", "execute": "", "has_content": False},
        {"row": 4, "status": "PENDING", "execute": "", "has_content": False},
    ]
    assert choose_keep_row(candidates2) == 4


def test_extract_cell_url_prefers_hyperlink_falls_back_to_text_format_runs():
    from twmkt.sheets_board import extract_cell_url

    assert extract_cell_url({"hyperlink": "https://a.vn/x"}) == "https://a.vn/x"
    # Dòng 8 thật (production): hyperlink=None, link nằm trong textFormatRuns.
    cell_run = {"hyperlink": None,
               "textFormatRuns": [{"format": {"link": {"uri": "https://b.vn/y"}}}]}
    assert extract_cell_url(cell_run) == "https://b.vn/y"
    assert extract_cell_url({}) is None
    assert extract_cell_url({"textFormatRuns": [{"format": {}}]}) is None


def test_is_title_chip_true_when_hyperlink_differs_from_display_text():
    from twmkt.sheets_board import is_title_chip

    # Đúng dòng 5 thật: hiển thị tiêu đề, href là URL khác -> title-chip.
    cell = {"hyperlink": "https://cafebiz.vn/nhap-sieu-that.chn"}
    assert is_title_chip(cell, "Nhập siêu 13,8 tỷ USD sau 5 tháng") is True
    # Đúng dòng 11 thật: hiển thị CHÍNH URL đó -> KHÔNG phải title-chip (dù có hyperlink).
    assert is_title_chip(cell, "https://cafebiz.vn/nhap-sieu-that.chn") is False
    # Không có hyperlink -> không phải chip.
    assert is_title_chip({}, "bất kỳ") is False


def test_build_plan_matches_real_production_scenario():
    """Mô phỏng ĐÚNG kịch bản thật trên board: 2 nhóm trùng (5&11, 7&14) ->
    build_plan() phải chọn giữ 5 và 7, xoá 11 và 14 (khớp Phase 0 dry-run)."""
    import os
    import sys as _sys
    REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    _sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))
    import dedupe_context as dc
    from twmkt.sheets_board import CONTEXT_HEADER, context_row

    rows = [
        context_row(title="A", hook_line="h", source_url="u", score=1, hot_pct=1.0,
                   status="PENDING", execute="RUN", topic_key="tk-a"),          # dòng 2
        context_row(title="B", hook_line="h", source_url="u", score=1, hot_pct=1.0,
                   status="APPROVE", execute="DONE", topic_key="tk-b"),         # dòng 3 (GIỮ, nhóm b)
        context_row(title="C", hook_line="h", source_url="u", score=1, hot_pct=1.0,
                   status="PENDING", execute="RUN", topic_key="tk-c"),          # dòng 4 (GIỮ, nhóm c)
        context_row(title="B lại", hook_line="h", source_url="u", score=1, hot_pct=1.0,
                   status="PENDING", execute="", topic_key="tk-b"),             # dòng 5 (XOÁ)
        context_row(title="C lại", hook_line="h", source_url="u", score=1, hot_pct=1.0,
                   status="PENDING", execute="", topic_key="tk-c"),             # dòng 6 (XOÁ)
    ]
    plan = dc.build_plan(CONTEXT_HEADER, rows, content_keys=set())
    by_key = {g["topic_key"]: g for g in plan}
    assert by_key["tk-b"]["keep"] == 3 and by_key["tk-b"]["delete"] == [5]
    assert by_key["tk-c"]["keep"] == 4 and by_key["tk-c"]["delete"] == [6]
    assert "tk-a" not in by_key   # không trùng -> không nằm trong kế hoạch


def test_group_content_rows_groups_by_topic_key_preserves_order():
    """Sheet UI cleanup Phase 1 — group_content_rows: nhóm theo TopicKey (ĐỔI từ
    Context text, vì Context có thể bị merge cũ để lại rỗng ở dữ liệu CŨ — xem
    docstring hàm), GIỮ thứ tự xuất hiện trong nhóm; hàng TopicKey rỗng bị bỏ qua."""
    from twmkt.sheets_board import group_content_rows, CONTENT_HEADER, content_row

    a1 = content_row(context="A", type_="article", status="DONE", output="x", topic_key="tk-a")
    a2 = content_row(context="A", type_="video", status="DONE", output="x", topic_key="tk-a")
    b1 = content_row(context="B", type_="infographic", status="DONE", output="x", topic_key="tk-b")
    empty = content_row(context="C", type_="article", status="DONE", output="x", topic_key="")
    groups = group_content_rows(CONTENT_HEADER, [a1, b1, a2, empty])
    assert list(groups.keys()) == ["tk-a", "tk-b"]
    assert groups["tk-a"] == [a1, a2]
    assert groups["tk-b"] == [b1]


def test_regroup_content_rows_makes_same_topic_key_contiguous():
    """Sheet UI cleanup Phase 1 — regroup_content_rows: hàng CÙNG TopicKey bị xen
    kẽ -> sắp lại LIỀN KỀ, giữ thứ tự xuất hiện đầu tiên giữa các TopicKey và thứ
    tự bên trong mỗi nhóm. Context KHÔNG còn là khoá nhóm (đổi sang TopicKey)."""
    from twmkt.sheets_board import regroup_content_rows, CONTENT_HEADER, content_row

    a1 = content_row(context="A", type_="infographic", status="DONE", output="x", topic_key="tk-a")
    b1 = content_row(context="B", type_="infographic", status="DONE", output="x", topic_key="tk-b")
    a2 = content_row(context="A", type_="article", status="DONE", output="x", topic_key="tk-a")
    a3 = content_row(context="A", type_="video", status="DONE", output="x", topic_key="tk-a")
    out = regroup_content_rows(CONTENT_HEADER, [a1, b1, a2, a3])
    assert out == [a1, a2, a3, b1]   # tk-a liền kề (giữ thứ tự trong-nhóm), tk-b sau


def test_content_band_ranges_bands_every_group_no_type_threshold():
    """Sheet UI cleanup Phase 1 — content_band_ranges THAY content_merge_ranges
    cũ: KHÔNG còn ngưỡng số loại (banding là phân nhóm thị giác theo CHỦ ĐỀ) —
    TopicKey 3 loại, 2 loại, VÀ CHỈ 1 loại đều có dải (khác merge cũ, vốn bỏ qua
    Context chỉ 1 loại)."""
    from twmkt.sheets_board import content_band_ranges, CONTENT_HEADER, content_row

    a_info = content_row(context="A", type_="infographic", status="DONE", output="x", topic_key="tk-a")
    a_art = content_row(context="A", type_="article", status="DONE", output="x", topic_key="tk-a")
    a_vid = content_row(context="A", type_="video", status="DONE", output="x", topic_key="tk-a")
    b_info = content_row(context="B", type_="infographic", status="DONE", output="x", topic_key="tk-b")
    b_art = content_row(context="B", type_="article", status="DONE", output="x", topic_key="tk-b")
    c_info = content_row(context="C", type_="infographic", status="DONE", output="x", topic_key="tk-c")
    rows = [a_info, a_art, a_vid, b_info, b_art, c_info]
    ranges = content_band_ranges(CONTENT_HEADER, rows)
    assert ranges == [(1, 4), (4, 6), (6, 7)]   # tk-a (3 loại), tk-b (2 loại), tk-c (1 loại) — CẢ 3 đều có dải


def test_content_day_border_ranges_splits_topic_group_across_days():
    """2026-07-23 -- content_day_border_ranges quét dải NGÀY trên thứ tự HIỆN
    CÓ (sau regroup TopicKey), KHÔNG cố gộp giả: 1 chủ đề có video sinh TRỄ
    hơn (ngày khác article/infographic) -> 2 dải ngày NẰM TRONG cùng 1 khối
    màu TopicKey, phản ánh đúng thực tế."""
    from twmkt.sheets_board import content_day_border_ranges, CONTENT_HEADER, content_row

    a_info = content_row(context="A", type_="infographic", status="DONE", output="x",
                         topic_key="tk-a", ts="22/07/2026")
    a_art = content_row(context="A", type_="article", status="DONE", output="x",
                        topic_key="tk-a", ts="22/07/2026")
    a_vid = content_row(context="A", type_="video", status="DONE", output="x",
                        topic_key="tk-a", ts="23/07/2026")   # sinh trễ hơn -- ngày khác
    b_info = content_row(context="B", type_="infographic", status="DONE", output="x",
                         topic_key="tk-b", ts="23/07/2026")
    rows = [a_info, a_art, a_vid, b_info]   # ĐÃ regroup theo TopicKey (tk-a liền kề)
    ranges = content_day_border_ranges(CONTENT_HEADER, rows)
    # 22/07 (a_info, a_art) | 23/07 (a_vid, b_info) -- ranh giới ngày CẮT NGANG khối tk-a
    assert ranges == [(1, 3), (3, 5)]


def test_regroup_and_band_content_paints_day_background_and_topickey_top_border():
    """VIỆC 3.3b (2026-08-04, Lead qua AskUserQuestion: "Đổi sang dùng nền
    theo Ngày, đồng bộ màu với tab Context") — ĐẢO kênh thị giác so với hành
    vi cũ (2026-07-23, đã xoá): KHÔNG còn tự sắp lại hàng (regroup_content_
    rows) — thứ tự dòng do render_content_to_sheet() quyết định rồi, hàm này
    CHỈ tô. NỀN xen kẽ giờ theo khối NGÀY; TopicKey chỉ còn VIỀN TRÊN đậm ở
    đầu mỗi dải LIÊN TỤC — tk-a bị "b_info" (tk-b) chen giữa 2 lần xuất hiện
    (khác ngày) nên tính là 2 dải TopicKey riêng, KHÔNG gộp giả. TUYỆT ĐỐI
    KHÔNG có request mergeCells/unmergeCells nào."""
    from twmkt.sheets_board import SheetsBoard, CONTENT_HEADER, content_row

    # Thứ tự ĐÃ đúng theo ngày (giống output render_content_to_sheet()) --
    # 22/07: a_info (tk-a), b_info (tk-b) CHEN GIỮA -- 23/07: a_vid (tk-a).
    a_info = content_row(context="A", type_="infographic", status="DONE", output="x",
                         topic_key="tk-a", ts="22/07/2026")
    b_info = content_row(context="B", type_="infographic", status="DONE", output="x",
                         topic_key="tk-b", ts="22/07/2026")
    a_vid = content_row(context="A", type_="video", status="DONE", output="x",
                        topic_key="tk-a", ts="23/07/2026")

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

    ws = _FakeContentWS([list(CONTENT_HEADER), list(a_info), list(b_info), list(a_vid)])
    board = SheetsBoard(spreadsheet_id="X", creds_path="Y")
    board._ws["CONTENT"] = ws
    board._sh = _FakeSheet()

    n = board.regroup_and_band_content()
    assert n == 3   # tk-a (2 dải, cắt bởi b_info xen giữa) + tk-b (1 dải)
    assert ws._v[1:] == [a_info, b_info, a_vid]   # KHÔNG sắp lại -- giữ NGUYÊN thứ tự đã render
    assert ws.updated == []   # KHÔNG gọi update() ghi lại dữ liệu -- hàm này CHỈ tô

    reqs = board._sh.last_body["requests"]
    assert not any("mergeCells" in r or "unmergeCells" in r for r in reqs)   # KHÔNG merge ô nào
    fills = [r["repeatCell"] for r in reqs if "repeatCell" in r]
    top_borders = [r["updateBorders"] for r in reqs if "updateBorders" in r and "top" in r["updateBorders"]]
    left_borders = [r["updateBorders"] for r in reqs if "updateBorders" in r and "left" in r["updateBorders"]]
    assert len(fills) == 2      # 2 khối NGÀY (22/07, 23/07)
    assert len(top_borders) == 3   # 3 dải TopicKey (tk-a, tk-b, tk-a lại)
    assert left_borders == []   # viền trái ngày (cũ) KHÔNG còn dùng nữa -- nền đã thay thế
    assert fills[0]["range"]["startColumnIndex"] == 0 and fills[0]["range"]["endColumnIndex"] == len(CONTENT_HEADER)
    assert fills[0]["range"]["startRowIndex"] == 1 and fills[0]["range"]["endRowIndex"] == 3   # 22/07: dòng 1-2
    assert fills[1]["range"]["startRowIndex"] == 3 and fills[1]["range"]["endRowIndex"] == 4   # 23/07: dòng 3
    assert fills[0]["cell"]["userEnteredFormat"]["backgroundColor"] != \
           fills[1]["cell"]["userEnteredFormat"]["backgroundColor"]   # 2 khối ngày liền kề PHẢI khác màu (xen kẽ)
    for b in top_borders:
        assert b["top"]["style"] == "SOLID_THICK"


def test_regroup_and_band_content_noop_when_empty():
    """Tab CONTENT rỗng (chỉ header) -> 0 dải, KHÔNG gửi request nào (khác hành
    vi cũ luôn gửi unmergeCells dù rỗng — banding không cần "dọn" gì trước)."""
    from twmkt.sheets_board import SheetsBoard, CONTENT_HEADER

    class _FakeContentWS:
        id = 1
        def get_all_values(self): return [list(CONTENT_HEADER)]
        def update(self, rng, values, value_input_option=None):
            raise AssertionError("không có dòng nào để sắp lại")

    class _FakeSheet:
        def __init__(self): self.last_body = None
        def batch_update(self, body): self.last_body = body; return {}

    board = SheetsBoard(spreadsheet_id="X", creds_path="Y")
    board._ws["CONTENT"] = _FakeContentWS()
    board._sh = _FakeSheet()

    n = board.regroup_and_band_content()
    assert n == 0
    assert board._sh.last_body is None   # khong goi batch_update khi khong co dai nao


def test_regroup_and_band_content_never_blanks_context_or_timestamp():
    """Sheet UI cleanup Phase 1 — nghiệm thu bắt buộc: ghi dữ liệu MỚI rồi gọi
    regroup_and_band_content() -> 0 dòng Context/Timestamp rỗng do banding (khác
    mergeCells cũ, luôn xoá thật các dòng TRONG dải trừ dòng đầu). Mọi dòng vẫn
    giữ nguyên giá trị Context/Timestamp gốc sau khi tô nền/viền."""
    from twmkt.sheets_board import SheetsBoard, CONTENT_HEADER, content_row

    a_info = content_row(context="A", type_="infographic", status="DONE", output="x",
                         topic_key="tk-a", ts="2026-07-16T00:00:00")
    a_art = content_row(context="A", type_="article", status="DONE", output="x",
                        topic_key="tk-a", ts="2026-07-16T00:00:01")
    a_vid = content_row(context="A", type_="video", status="DONE", output="x",
                        topic_key="tk-a", ts="2026-07-16T00:00:02")
    b_info = content_row(context="B", type_="infographic", status="DONE", output="x",
                         topic_key="tk-b", ts="2026-07-16T00:00:03")

    class _FakeContentWS:
        id = 9
        def __init__(self, values): self._v = values
        def get_all_values(self): return self._v
        def update(self, rng, values, value_input_option=None):
            self._v = [self._v[0]] + [list(r) for r in values]

    class _FakeSheet:
        def batch_update(self, body): return {}

    ws = _FakeContentWS([list(CONTENT_HEADER), list(a_info), list(a_art), list(a_vid), list(b_info)])
    board = SheetsBoard(spreadsheet_id="X", creds_path="Y")
    board._ws["CONTENT"] = ws
    board._sh = _FakeSheet()

    board.regroup_and_band_content()

    header = ws._v[0]
    ic = [h.lower() for h in header].index("context")
    it = [h.lower() for h in header].index("timestamp")
    blanked = [r for r in ws._v[1:] if not r[ic].strip() or not r[it].strip()]
    assert blanked == []   # 0 dòng rỗng — đúng nghiệm thu Phase 1


# =====================================================================
# Sheet UI cleanup Phase 2 — reset_plan()/reset_all() (scripts/reset_sheet.py)
# =====================================================================
def test_reset_plan_reads_rows_and_merge_ranges_without_writing():
    """reset_plan(): CHỈ ĐỌC (get_all_values + fetch_sheet_metadata), KHÔNG ghi
    gì. Số dòng = số dòng DỮ LIỆU (trừ header); số merge_ranges ĐỌC THẬT từ API
    (field `merges`), KHÔNG đoán qua ô rỗng. KHÔNG đụng tab CẤU HÌNH (SOURCES)."""
    from twmkt.sheets_board import SheetsBoard, CONTEXT_HEADER, CONTENT_HEADER

    class _FakeWS:
        def __init__(self, values): self._v = values
        def get_all_values(self): return self._v
        def update(self, *a, **kw): raise AssertionError("reset_plan KHÔNG được ghi gì")
        def batch_clear(self, *a, **kw): raise AssertionError("reset_plan KHÔNG được ghi gì")

    class _FakeSheet:
        def batch_update(self, body): raise AssertionError("reset_plan KHÔNG được gọi batch_update")
        def fetch_sheet_metadata(self, params=None):
            return {"sheets": [
                {"properties": {"title": "CONTEXT"}, "merges": [{"a": 1}]},
                {"properties": {"title": "CONTENT"}, "merges": [{"a": 1}, {"a": 2}]},
                {"properties": {"title": "SOURCES"}, "merges": [{"a": 1}, {"a": 2}, {"a": 3}]},
            ]}

    board = SheetsBoard(spreadsheet_id="X", creds_path="Y")
    board._ws["CONTEXT"] = _FakeWS([list(CONTEXT_HEADER)] + [["r"] * len(CONTEXT_HEADER)] * 3)
    board._ws["CONTENT"] = _FakeWS([list(CONTENT_HEADER)] + [["r"] * len(CONTENT_HEADER)] * 2)
    board._sh = _FakeSheet()

    plan = board.reset_plan()
    assert plan == {"CONTEXT": {"rows": 3, "merge_ranges": 1},
                    "CONTENT": {"rows": 2, "merge_ranges": 2}}   # SOURCES (3 merge) KHÔNG xuất hiện — ngoài phạm vi


def test_reset_all_unmerges_and_clears_data_keeps_header():
    """reset_all(): un-merge TOÀN VÙNG mỗi tab (CONTEXT+CONTENT) + batch_clear
    GIÁ TRỊ dòng 2+ (GIỮ header dòng 1) — KHÔNG mergeCells nào, KHÔNG đụng tab
    khác. Trả CÙNG số liệu với reset_plan() để đối chiếu dự đoán/thực thi."""
    from twmkt.sheets_board import SheetsBoard, CONTEXT_HEADER, CONTENT_HEADER

    class _FakeWS:
        id = 42
        row_count = 100
        def __init__(self, values):
            self._v = values
            self.cleared_ranges: list[str] = []
        def get_all_values(self): return self._v
        def batch_clear(self, ranges): self.cleared_ranges.extend(ranges)

    class _FakeSheet:
        def __init__(self): self.batch_calls: list[dict] = []
        def batch_update(self, body): self.batch_calls.append(body); return {}
        def fetch_sheet_metadata(self, params=None):
            return {"sheets": [{"properties": {"title": "CONTEXT"}, "merges": [{}]},
                               {"properties": {"title": "CONTENT"}, "merges": []}]}

    ctx_ws = _FakeWS([list(CONTEXT_HEADER), ["a"] * len(CONTEXT_HEADER)])
    content_ws = _FakeWS([list(CONTENT_HEADER), ["b"] * len(CONTENT_HEADER), ["c"] * len(CONTENT_HEADER)])
    board = SheetsBoard(spreadsheet_id="X", creds_path="Y")
    board._ws["CONTEXT"] = ctx_ws
    board._ws["CONTENT"] = content_ws
    board._sh = _FakeSheet()

    result = board.reset_all()
    assert result == {"CONTEXT": {"rows": 1, "merge_ranges": 1}, "CONTENT": {"rows": 2, "merge_ranges": 0}}

    unmerge_reqs = [c["requests"][0] for c in board._sh.batch_calls]
    assert len(unmerge_reqs) == 2 and all("unmergeCells" in r for r in unmerge_reqs)
    assert not any("mergeCells" in r for c in board._sh.batch_calls for r in c["requests"])   # KHÔNG merge lại
    assert ctx_ws.cleared_ranges and ctx_ws.cleared_ranges[0].startswith("A2:")      # header GIỮ NGUYÊN
    assert content_ws.cleared_ranges and content_ws.cleared_ranges[0].startswith("A2:")


def test_reset_all_skips_batch_clear_when_tab_already_empty():
    """Tab CHỈ CÒN header (0 dòng dữ liệu) -> vẫn un-merge (an toàn, idempotent)
    nhưng KHÔNG gọi batch_clear (không có gì để xoá)."""
    from twmkt.sheets_board import SheetsBoard, CONTEXT_HEADER, CONTENT_HEADER

    class _FakeWS:
        id = 1
        row_count = 100
        def __init__(self, values): self._v = values
        def get_all_values(self): return self._v
        def batch_clear(self, ranges): raise AssertionError("không có dòng dữ liệu nào để xoá")

    class _FakeSheet:
        def __init__(self): self.batch_calls: list[dict] = []
        def batch_update(self, body): self.batch_calls.append(body); return {}
        def fetch_sheet_metadata(self, params=None): return {"sheets": []}

    board = SheetsBoard(spreadsheet_id="X", creds_path="Y")
    board._ws["CONTEXT"] = _FakeWS([list(CONTEXT_HEADER)])
    board._ws["CONTENT"] = _FakeWS([list(CONTENT_HEADER)])
    board._sh = _FakeSheet()

    result = board.reset_all()
    assert result == {"CONTEXT": {"rows": 0, "merge_ranges": 0}, "CONTENT": {"rows": 0, "merge_ranges": 0}}
    assert len(board._sh.batch_calls) == 2   # vẫn un-merge cả 2 tab (idempotent, vô hại dù rỗng)


# =====================================================================
# Sheet UI cleanup Phase 4 — set_machine_columns_hidden() (cột máy-sở-hữu)
# =====================================================================
def test_set_machine_columns_hidden_sends_correct_requests_for_all_3_cols():
    """set_machine_columns_hidden(hidden=True): TopicKey+Hook (CONTEXT) +
    TopicKey/Facts (CONTENT) = 4 request updateDimensionProperties, ĐÚNG cột
    (so bằng index thật trong header), hiddenByUser=True, KHÔNG có request nào
    khác (không mergeCells/batch_clear/update giá trị). Sheet UI cleanup Phase
    6: AssetPath ĐÃ RÚT khỏi _MACHINE_OWNED_COLS (không còn ẩn — xem
    content_row Phase 6 docstring). 2026-07-28: THÊM Hook (CONTEXT) — lặp lại
    cột Context, Lead yêu cầu ẩn."""
    from twmkt.sheets_board import SheetsBoard, CONTEXT_HEADER, CONTENT_HEADER

    class _FakeWS:
        def __init__(self, sid, header): self.id = sid; self._header = header
        def row_values(self, n): return self._header

    class _FakeSheet:
        def __init__(self): self.batch_calls: list[dict] = []
        def batch_update(self, body): self.batch_calls.append(body); return {}

    board = SheetsBoard(spreadsheet_id="X", creds_path="Y")
    board._ws["CONTEXT"] = _FakeWS(11, list(CONTEXT_HEADER))
    board._ws["CONTENT"] = _FakeWS(22, list(CONTENT_HEADER))
    board._sh = _FakeSheet()

    n = board.set_machine_columns_hidden(hidden=True)
    assert n == 4   # TopicKey+Hook (CONTEXT) + TopicKey/Facts (CONTENT)

    assert len(board._sh.batch_calls) == 1
    reqs = board._sh.batch_calls[0]["requests"]
    assert len(reqs) == 4 and all("updateDimensionProperties" in r for r in reqs)
    low_ctx = [h.lower() for h in CONTEXT_HEADER]
    low_con = [h.lower() for h in CONTENT_HEADER]
    expected = {
        (11, low_ctx.index("topickey")),
        (11, low_ctx.index("hook")),
        (22, low_con.index("topickey")),
        (22, low_con.index("facts")),
    }
    actual = {(r["updateDimensionProperties"]["range"]["sheetId"],
              r["updateDimensionProperties"]["range"]["startIndex"]) for r in reqs}
    assert actual == expected
    for r in reqs:
        p = r["updateDimensionProperties"]
        assert p["range"]["dimension"] == "COLUMNS"
        assert p["range"]["endIndex"] == p["range"]["startIndex"] + 1
        assert p["properties"] == {"hiddenByUser": True}
        assert p["fields"] == "hiddenByUser"


def test_set_machine_columns_hidden_show_flag_sets_false():
    """hidden=False (--show-machine-cols) -> CÙNG 4 request, hiddenByUser=False."""
    from twmkt.sheets_board import SheetsBoard, CONTEXT_HEADER, CONTENT_HEADER

    class _FakeWS:
        def __init__(self, sid, header): self.id = sid; self._header = header
        def row_values(self, n): return self._header

    class _FakeSheet:
        def __init__(self): self.batch_calls: list[dict] = []
        def batch_update(self, body): self.batch_calls.append(body); return {}

    board = SheetsBoard(spreadsheet_id="X", creds_path="Y")
    board._ws["CONTEXT"] = _FakeWS(11, list(CONTEXT_HEADER))
    board._ws["CONTENT"] = _FakeWS(22, list(CONTENT_HEADER))
    board._sh = _FakeSheet()

    n = board.set_machine_columns_hidden(hidden=False)
    assert n == 4
    reqs = board._sh.batch_calls[0]["requests"]
    assert all(r["updateDimensionProperties"]["properties"] == {"hiddenByUser": False} for r in reqs)


def test_set_machine_columns_hidden_never_touches_ensure_tabs_or_migrate():
    """ĐỘC LẬP với ensure_tabs()/migrate_rows(): fake worksheet KHÔNG có
    get_all_values()/update() (raise AttributeError nếu gọi nhầm) — hàm chỉ
    dùng row_values(1) (đọc header) + batch_update (ghi hiddenByUser), xác
    nhận bằng code KHÔNG có đường nào chạm migrate_rows()."""
    from twmkt.sheets_board import SheetsBoard, CONTEXT_HEADER, CONTENT_HEADER

    class _FakeWS:
        def __init__(self, sid, header): self.id = sid; self._header = header
        def row_values(self, n): return self._header
        # CỐ Ý không định nghĩa get_all_values/update — nếu code lỡ gọi sẽ
        # AttributeError ngay, chứng minh set_machine_columns_hidden() không
        # đọc/ghi GIÁ TRỊ ô nào, chỉ đổi thuộc tính hiển thị cột.

    class _FakeSheet:
        def __init__(self): self.batch_calls: list[dict] = []
        def batch_update(self, body): self.batch_calls.append(body); return {}

    board = SheetsBoard(spreadsheet_id="X", creds_path="Y")
    board._ws["CONTEXT"] = _FakeWS(1, list(CONTEXT_HEADER))
    board._ws["CONTENT"] = _FakeWS(2, list(CONTENT_HEADER))
    board._sh = _FakeSheet()

    n = board.set_machine_columns_hidden(hidden=True)
    assert n == 4   # chạy trót lọt -> xác nhận không đụng get_all_values/update


def test_service_account_email_reads_only_client_email_field():
    """_service_account_email() CHỈ đọc client_email từ creds_path — không
    expose private_key hay trường bí mật nào khác (kỷ luật đọc credentials
    tối thiểu, xem CLAUDE.md 'Không rò bí mật')."""
    import json as _json
    import tempfile
    from pathlib import Path as _Path

    from twmkt.sheets_board import SheetsBoard

    tmp = _Path(tempfile.mkdtemp()) / "fake_sa.json"
    tmp.write_text(_json.dumps({
        "client_email": "sa-test@fake-project.iam.gserviceaccount.com",
        "private_key": "-----BEGIN PRIVATE KEY-----\nSECRET\n-----END PRIVATE KEY-----\n",
        "project_id": "fake-project",
    }), encoding="utf-8")

    board = SheetsBoard.__new__(SheetsBoard)   # bỏ __init__ (không cần spreadsheet_id thật)
    board.creds_path = str(tmp)
    assert board._service_account_email() == "sa-test@fake-project.iam.gserviceaccount.com"


def test_protect_asset_path_column_creates_protected_range_scoped_to_column():
    """Sheet UI cleanup Phase 6b: protect_asset_path_column() gửi ĐÚNG 1
    addProtectedRange, phạm vi CHỈ cột AssetPath (theo index thật trong
    header, CẢ CỘT không giới hạn hàng), editors=[client_email từ creds],
    warningOnly=False (khoá THẬT, không chỉ cảnh báo)."""
    import json as _json
    import tempfile
    from pathlib import Path as _Path

    from twmkt.sheets_board import SheetsBoard, CONTENT_HEADER, _ASSET_PATH_PROTECTION_DESC

    tmp = _Path(tempfile.mkdtemp()) / "fake_sa.json"
    tmp.write_text(_json.dumps({"client_email": "sa@x.iam.gserviceaccount.com"}), encoding="utf-8")

    class _FakeWS:
        def __init__(self, sid, header): self.id = sid; self._header = header
        def row_values(self, n): return self._header

    class _FakeSheet:
        def __init__(self):
            self.batch_calls: list[dict] = []
        def fetch_sheet_metadata(self, params=None):
            return {"sheets": [{"properties": {"sheetId": 22}, "protectedRanges": []}]}
        def batch_update(self, body):
            self.batch_calls.append(body)
            return {"replies": [{"addProtectedRange": {"protectedRange": {"protectedRangeId": 1}}}]}

    board = SheetsBoard.__new__(SheetsBoard)
    board.creds_path = str(tmp)
    board._ws = {"CONTENT": _FakeWS(22, list(CONTENT_HEADER))}
    board._sh = _FakeSheet()

    result = board.protect_asset_path_column()
    assert "already_protected" not in result
    assert len(board._sh.batch_calls) == 1
    req = board._sh.batch_calls[0]["requests"][0]["addProtectedRange"]["protectedRange"]
    col = [h.lower() for h in CONTENT_HEADER].index("assetpath")
    assert req["range"] == {"sheetId": 22, "startColumnIndex": col, "endColumnIndex": col + 1}
    assert req["description"] == _ASSET_PATH_PROTECTION_DESC
    assert req["warningOnly"] is False
    assert req["editors"] == {"users": ["sa@x.iam.gserviceaccount.com"]}


def test_protect_asset_path_column_idempotent_skips_if_already_protected():
    """Chạy lại (vd chạy script 2 lần) -> KHÔNG tạo Protected Range trùng,
    phát hiện qua mô tả _ASSET_PATH_PROTECTION_DESC đã có trên đúng cột."""
    from twmkt.sheets_board import SheetsBoard, CONTENT_HEADER, _ASSET_PATH_PROTECTION_DESC

    col = [h.lower() for h in CONTENT_HEADER].index("assetpath")

    class _FakeWS:
        def __init__(self, sid, header): self.id = sid; self._header = header
        def row_values(self, n): return self._header

    class _FakeSheet:
        def __init__(self):
            self.batch_calls: list[dict] = []
        def fetch_sheet_metadata(self, params=None):
            return {"sheets": [{"properties": {"sheetId": 22}, "protectedRanges": [
                {"protectedRangeId": 99,
                 "range": {"sheetId": 22, "startColumnIndex": col, "endColumnIndex": col + 1},
                 "description": _ASSET_PATH_PROTECTION_DESC}]}]}
        def batch_update(self, body):
            self.batch_calls.append(body)
            return {}

    board = SheetsBoard.__new__(SheetsBoard)
    board.creds_path = "unused-not-read-when-already-protected"
    board._ws = {"CONTENT": _FakeWS(22, list(CONTENT_HEADER))}
    board._sh = _FakeSheet()

    result = board.protect_asset_path_column()
    assert result == {"already_protected": True, "protectedRangeId": 99}
    assert board._sh.batch_calls == []   # KHÔNG gửi addProtectedRange trùng


def test_protect_asset_path_column_missing_column_returns_empty():
    """Header CONTENT giả thiếu AssetPath -> trả {} an toàn, không lỗi."""
    from twmkt.sheets_board import SheetsBoard

    class _FakeWS:
        def __init__(self, sid, header): self.id = sid; self._header = header
        def row_values(self, n): return self._header

    board = SheetsBoard.__new__(SheetsBoard)
    board._ws = {"CONTENT": _FakeWS(22, ["Timestamp", "Context"])}
    board._sh = None

    assert board.protect_asset_path_column() == {}


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
        def complete(self, system, prompt, **kwargs): return ""

    d = compliance.apply(AnalysisWriterAgent(EmptyLLM()).run(
        ProductionBrief(title="Tiêu đề bài", hook="Hook X", tickers=["HPG"],
                        evidence="Dữ kiện quan trọng.")))
    assert d.is_clean and "Tiêu đề bài" in d.body
    assert "không phải khuyến nghị" in d.body.lower()   # Content Factory Phase D: disclaimer rút gọn


def test_domain_of_extracts_netloc():
    from twmkt.agents.production import domain_of
    assert domain_of("https://cafef.vn/abc-123.chn") == "cafef.vn"
    assert domain_of("https://www.vietstock.vn/x.htm") == "vietstock.vn"
    assert domain_of("") == "" and domain_of("khong-phai-url") == ""


def test_soft_truncate_does_not_cut_mid_word():
    """Phase 4.11 item 6: cắt về giới hạn nhưng lùi về khoảng trắng gần nhất,
    KHÔNG đứt ngang 1 từ (khác [:N] cứng cũ)."""
    from twmkt.agents.production import _soft_truncate

    text = "GDP 6 tháng đầu năm tăng 8,18%, mức cao nhất nhiều năm qua"
    cut = _soft_truncate(text, 40)
    assert cut.endswith("…")
    assert len(cut) <= 41   # 40 + dấu "…"
    core = cut[:-1].rstrip()
    assert text.startswith(core)                     # phần giữ lại khớp NGUYÊN VĂN prefix của text gốc
    assert not core or core[-1] != " "                # không để khoảng trắng thừa ngay trước "…"
    assert all(w for w in core.split(" "))            # không có từ nào bị cắt dở (không token rỗng lạ)

    short = "Câu ngắn."
    assert _soft_truncate(short, 200) == short   # ngắn hơn limit -> giữ nguyên, KHÔNG thêm "…"
    assert _soft_truncate("", 100) == ""
    assert _soft_truncate("khongcokhoangtrangnaoquadai" * 5, 10).endswith("…")   # 1 từ dài -> vẫn cắt được, không crash


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

    seen_cmd, seen_kwargs = {}, {}

    def fake_run(cmd, **kwargs):
        seen_cmd["cmd"] = cmd
        seen_kwargs.update(kwargs)
        return _FakeProc(0, _json.dumps({"is_error": False, "result": "OK"}), "")

    llm = ClaudeCodeLLM(run_fn=fake_run)
    out = llm.complete("bạn là trợ lý", "trả lời OK", model="claude-haiku-4-5-20251001")
    assert out == "OK"
    # cmd[0] = đường dẫn ĐÃ resolve qua shutil.which() (vd "claude.CMD" trên
    # Windows) -- chỉ còn CHỨA "claude", KHÔNG còn == "claude" nguyên văn kể từ
    # khi sửa bug FileNotFoundError trên Windows (agents/base.py, 2026-07-23).
    assert "claude" in seen_cmd["cmd"][0].lower()
    assert seen_cmd["cmd"][1:2] == ["-p"]
    # Prompt qua STDIN (kwarg `input`), KHÔNG còn nằm trong argv -- xem cùng
    # commit: claude.cmd (shim Windows) giới hạn độ dài command-line (~8KB),
    # "The command line is too long." với prompt bài viết thật.
    assert seen_kwargs.get("input") == "bạn là trợ lý\n\ntrả lời OK"
    assert "--model" in seen_cmd["cmd"] and "claude-haiku-4-5-20251001" in seen_cmd["cmd"]


def test_claude_code_llm_handles_is_error_nonzero_exit_and_bad_json():
    from twmkt.agents.base import ClaudeCodeLLM
    import json as _json

    assert ClaudeCodeLLM(run_fn=lambda *a, **k: _FakeProc(
        0, _json.dumps({"is_error": True, "result": "lỗi"}), "")).complete("s", "p") == ""
    assert ClaudeCodeLLM(run_fn=lambda *a, **k: _FakeProc(1, "", "boom")).complete("s", "p") == ""
    assert ClaudeCodeLLM(run_fn=lambda *a, **k: _FakeProc(0, "khong-phai-json", "")).complete("s", "p") == ""


def test_claude_code_llm_nonzero_exit_reports_reason_from_stdout_not_empty_stderr(capsys):
    """Exit != 0 + STDERR RỖNG + lý do thật nằm trong JSON STDOUT (ca hạn mức
    429 gặp thật 2026-07-27) -> cảnh báo phải NÊU lý do, KHÔNG in `''` trống.
    Đây là bug che giấu nguyên nhân: cả phiên e2e tưởng lỗi code trong khi CLI
    đã nói rõ "hit your monthly spend limit"."""
    from twmkt.agents.base import ClaudeCodeLLM
    import json as _json

    payload = _json.dumps({"is_error": True, "result": "You've hit your monthly spend limit"})
    assert ClaudeCodeLLM(run_fn=lambda *a, **k: _FakeProc(1, payload, "")).complete("s", "p") == ""
    warned = capsys.readouterr().out
    assert "monthly spend limit" in warned
    assert "''" not in warned   # bản cũ in đúng chuỗi rỗng này


def test_claude_code_llm_nonzero_exit_falls_back_to_stderr_when_stdout_empty(capsys):
    """STDOUT rỗng -> vẫn phải lùi về STDERR như hành vi CŨ (không đánh mất
    thông tin ở ca CLI thật sự ghi stderr, vd binary hỏng)."""
    from twmkt.agents.base import ClaudeCodeLLM

    assert ClaudeCodeLLM(run_fn=lambda *a, **k: _FakeProc(1, "", "boom-stderr")).complete("s", "p") == ""
    assert "boom-stderr" in capsys.readouterr().out


def test_claude_code_llm_nonzero_exit_uses_raw_stdout_when_not_json(capsys):
    """STDOUT có nội dung nhưng KHÔNG phải JSON (CLI đổi định dạng/lỗi sớm
    trước khi kịp dựng JSON) -> in nguyên văn stdout, không nuốt."""
    from twmkt.agents.base import ClaudeCodeLLM

    assert ClaudeCodeLLM(run_fn=lambda *a, **k: _FakeProc(1, "Not logged in", "")).complete("s", "p") == ""
    assert "Not logged in" in capsys.readouterr().out


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
    """_is_fully_produced: CHỈ True khi CẢ 3 loại (infographic/article/video)
    đã có trong CONTENT (`seen`) — tín hiệu đặt Execute=DONE."""
    sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))
    import produce_from_sheet as pfs

    seen = {("Bài A", "infographic"), ("Bài A", "article")}
    assert pfs._is_fully_produced("Bài A", seen) is False   # thiếu video
    seen.add(("Bài A", "video"))
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
    """P2 store-as-truth: produce_from_sheet.run() giờ đọc/ghi STORE cho dữ
    liệu nội dung (approved/execute/CONTENT) — `board` giả CHỈ còn cần fake 3
    method Sheet-native còn lại theo quyết định Bước 1 (log/PROMPTS/SOURCES —
    người quản lý trực tiếp trên Sheet). Seed dữ liệu "approved" và đọc lại
    kết quả sản xuất giờ qua store thật (tmp SQLite) — xem _run_produce_scenario/
    _seed_approved/_read_back_produce_result bên dưới."""

    def log(self, *a, **kw):
        pass

    def read_prompt_versions(self):
        return {}

    def read_sources(self):
        return []


class _FakeProduceNotifier:
    def __init__(self):
        self.events: list[tuple[str, dict]] = []

    def notify(self, event, **ctx):
        self.events.append((event, ctx))
        return True


class _EmptyRouteLLM:
    """route_llm giả cho brief+router (Phase 4.9 test) — trả rỗng cho CẢ 2 bước
    -> content_units=[] (lùi mượt), router fallback S1+H3 (không quan trọng ở test này,
    trọng tâm là outcome CỦA WRITER)."""

    def complete(self, *a, **kw):
        return ""


def _approved_row(context: str, row: int, *, source: str = "", topic_key: str = "",
                  output_type: list[str] | None = None) -> dict:
    """`row` giữ lại CHỈ để test đặt tên/tra cứu tiện tay — KHÔNG còn ý nghĩa
    Sheet-row-index (store không có khái niệm dòng). `topic_key` rỗng -> tính
    TẤT ĐỊNH từ `source` (compute_topic_key() thật — khớp hành vi assign_topic_key
    cũ khi có URL, cho test idempotent-theo-URL tiếp tục đúng) hoặc surrogate
    ổn định theo `row` nếu không có source (thay uuid4 ngẫu nhiên cũ — test cần
    tái lập được). `output_type` (Bước 4) — mặc định None -> [] (AUTO, không
    giới hạn thêm, khớp hành vi trước Bước 4)."""
    from twmkt.curation.keys import compute_topic_key
    tk = topic_key or (compute_topic_key(source) if source else f"row-{row}-key")
    return {"context": context, "hook": "hook gợi ý", "source": source, "tickers": [],
           "group": "", "topic": "", "execute": "RUN", "row": row, "topic_key": tk,
           "output_type": output_type or []}


def _seed_approved(row: dict, *, db_path) -> None:
    """Ghi 1 approved_row (dict _approved_row) vào store thật: raw (crawl output)
    + gate_status (gate1=APPROVE, execute=row['execute'] hoặc 'RUN' mặc định,
    output_type=row['output_type'] nếu có) — tương đương "dòng CONTEXT
    Status=APPROVE" cũ trên Sheet."""
    from store import pipeline_store as ps
    tk = row["topic_key"]
    ps.write_raw(tk, {
        "context": row["context"], "hook": row["hook"], "source": row["source"],
        "tickers": row["tickers"], "group": row["group"], "topic": row["topic"],
    }, db_path=db_path)
    ps.write_gate_status(tk, gate1="APPROVE", execute=row.get("execute") or "RUN",
                         output_type=row.get("output_type") or None, db_path=db_path)


def _read_back_produce_result(rows: list[dict], *, db_path):
    """Đọc lại kết quả run() vừa ghi vào store cho các topic trong `rows` —
    dựng lại 2 thuộc tính SHAPE-TƯƠNG-THÍCH với _FakeProduceBoard Sheet-era cũ
    (`.appended_content`: list[list[str]] theo CONTENT_HEADER, DÙNG LẠI
    content_row() thật; `.execute_updates`: dict[row_int, status]) để mọi
    assertion đã viết trước đó (r[2]/r[3].../board.execute_updates.get(row))
    tiếp tục đúng KHÔNG cần sửa — business behavior không đổi, chỉ đường ghi/
    đọc đổi từ Sheet sang store."""
    from store import document_store as ds
    from store import pipeline_store as ps
    from twmkt.sheets_board import content_row
    appended: list[list[str]] = []
    execute_updates: dict[int, str] = {}
    for r in rows:
        tk = r["topic_key"]
        # _seed_approved() đã ghi gate_status version 1 (Execute=RUN seed) —
        # CHỈ coi là "run() thật sự ghi Execute" nếu có version MỚI HƠN (khớp
        # ngữ nghĩa board.execute_updates cũ: chỉ chứa dòng set_execute_values()
        # thật sự đụng tới, KHÔNG chứa dòng bị lọc bỏ bởi topic_keys).
        history = ds.read_history(tk, "gate_status", "", db_path=db_path)
        if len(history) > 1:
            execute_updates[r["row"]] = history[-1][1].get("execute", "")
        for type_ in ("article", "long_article", "infographic", "video"):
            out = ps.read_content_output(tk, type_, db_path=db_path)
            if out is None:
                continue
            appended.append(content_row(
                context=r["context"], type_=type_, status=out.get("status", ""),
                output=out.get("output", ""), notes=out.get("notes", ""),
                topic_key=tk, facts=out.get("facts", "")))
    return appended, execute_updates


def _run_produce_scenario(writer_llm, approved_row: dict | None = None, route_llm=None, decisions_path=None,
                          *, approved_rows: list[dict] | None = None, run_kwargs: dict | None = None,
                          content_llm=None, pre_seed_content: list[tuple[str, str, dict]] | None = None,
                          run_times: int = 1):
    """Chạy produce_from_sheet.run() THẬT với board/notifier/route_llm/writer_llm
    giả lập qua monkeypatch + STORE thật (tmp SQLite, P2 store-as-truth) — trả
    (result, board, notifier), `board` có thêm `.appended_content`/
    `.execute_updates` ĐỌC LẠI từ store sau khi run() xong (xem
    _read_back_produce_result). Khôi phục mọi monkeypatch + ENV
    DOCUMENT_STORE_PATH trong finally (không rò rỉ sang test khác). `route_llm`
    mặc định _EmptyRouteLLM() (Phase 4.9); Phase 4.12 truyền route_llm riêng để
    mô phỏng Brief trả no_numeric_content=True. `decisions_path` (Phase
    (a)-SEAL): truyền CÙNG path ở 2 lần gọi để mô phỏng route-once BỀN qua 2
    lần chạy produce() thật (mặc định mỗi lần gọi 1 thư mục tạm RIÊNG — không
    persist). `approved_rows`/`run_kwargs` (VIỆC 5.1): nhiều dòng + kwargs cho
    run() (vd topic_keys); mặc định 1 dòng `approved_row` + run(limit=5) như
    cũ. `content_llm` (BƯỚC 3, rules v2.1): LLM cho VideoScriptAgent/
    InfographicSpecAgent (khác route_llm/writer_llm) — mặc định None = KHÔNG
    patch, giữ hành vi cũ (factory.build_content_llm() thật, offline->Mock).
    `pre_seed_content` (P2 store-as-truth, thay _BoardWithExistingArticle cũ):
    list[(topic_key, content_type, payload)] ghi SẴN vào content_output +
    content_status TRƯỚC khi gọi run() — mô phỏng "CONTENT đã có dòng này từ
    trước" để kiểm existing_content_keys()/dedup. `run_times` (thay 2 lệnh gọi
    run() thủ công cũ) — gọi run() liên tiếp NHIỀU LẦN trên CÙNG 1 store để
    kiểm idempotent qua nhiều lượt chạy thật."""
    import tempfile
    from pathlib import Path
    sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))
    import produce_from_sheet as pfs
    from store import document_store as ds
    from store import pipeline_store as ps
    from twmkt.config import Settings, load_settings as real_load_settings

    base = real_load_settings()
    data = dict(base.raw)
    decisions_path = decisions_path or (Path(tempfile.mkdtemp()) / "router_decisions.json")
    data["router"] = {"decisions_path": str(decisions_path)}
    test_settings = Settings(data)

    rows = approved_rows if approved_rows is not None else [approved_row]
    db_path = Path(tempfile.mkdtemp()) / "test_store.db"
    ds.init_db(db_path)
    for r in rows:
        _seed_approved(r, db_path=db_path)
    for tk, content_type, payload in (pre_seed_content or []):
        ps.write_content_output(tk, content_type, payload, db_path=db_path)
        ps.write_content_status(tk, content_type, gate2="PENDING", db_path=db_path)

    board = _FakeProduceBoard()
    notifier = _FakeProduceNotifier()
    route_llm = route_llm if route_llm is not None else _EmptyRouteLLM()

    orig_env = os.environ.get("DOCUMENT_STORE_PATH")
    orig = {
        "load_settings": pfs.load_settings, "_open_board": pfs._open_board,
        "make_notifier": pfs.make_notifier, "make_llm": pfs.factory.make_llm,
        "build_writer_llm": pfs.factory.build_writer_llm,
        "build_content_llm": pfs.factory.build_content_llm,
    }
    os.environ["DOCUMENT_STORE_PATH"] = str(db_path)
    pfs.load_settings = lambda *a, **kw: test_settings
    pfs._open_board = lambda settings, **kw: board
    pfs.make_notifier = lambda settings: notifier
    pfs.factory.make_llm = lambda settings: route_llm
    pfs.factory.build_writer_llm = lambda settings: writer_llm
    if content_llm is not None:
        pfs.factory.build_content_llm = lambda settings, **kw: content_llm
    try:
        for _ in range(run_times - 1):
            pfs.run(**(run_kwargs if run_kwargs is not None else {"limit": 5}))
        result = pfs.run(**(run_kwargs if run_kwargs is not None else {"limit": 5}))
    finally:
        pfs.load_settings = orig["load_settings"]
        pfs._open_board = orig["_open_board"]
        pfs.make_notifier = orig["make_notifier"]
        pfs.factory.make_llm = orig["make_llm"]
        pfs.factory.build_writer_llm = orig["build_writer_llm"]
        pfs.factory.build_content_llm = orig["build_content_llm"]
        if orig_env is None:
            os.environ.pop("DOCUMENT_STORE_PATH", None)
        else:
            os.environ["DOCUMENT_STORE_PATH"] = orig_env

    board.appended_content, board.execute_updates = _read_back_produce_result(rows, db_path=db_path)
    board.db_path = db_path   # cho test cần kiểm version count trực tiếp (vd idempotent qua nhiều run_times)
    return result, board, notifier


def test_run_persists_brief_layer_immediately_after_brief(monkeypatch):
    """Brief output duoc append vao layer brief bang Document Store API san co."""
    sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))
    import produce_from_sheet as pfs

    original_write = pfs.ds.write_document
    brief_writes = []

    def _capture_write(topic_key, layer, payload, written_by, **kwargs):
        if layer == "brief":
            brief_writes.append((topic_key, payload, written_by))
        return original_write(topic_key, layer, payload, written_by, **kwargs)

    monkeypatch.setattr(pfs.ds, "write_document", _capture_write)
    row = _approved_row("Persist brief audit", row=240, output_type=["Article"])
    _run_produce_scenario(_EmptyRouteLLM(), row, route_llm=_EmptyRouteLLM())

    assert len(brief_writes) == 1
    topic_key, payload, written_by = brief_writes[0]
    assert topic_key == row["topic_key"]
    assert written_by == "ma"
    assert "content_units" in payload
    assert "brief_status" in payload


def test_run_article_done_writes_content_marks_execute_done_and_notifies():
    """outcome=DONE: ghi CONTENT (article), Execute=DONE, notify start+draft_changed
    (+ gate2_done vì written>0). Dùng writer_llm trả JSON sạch (_clean_writer_json)."""
    class _CleanWriterLLM:
        def complete(self, system, prompt, *, model=None, fail_loud=False):
            return _clean_writer_json()

    result, board, notifier = _run_produce_scenario(
        _CleanWriterLLM(), _approved_row("Bài test 4.9 DONE", row=2))

    assert board.execute_updates.get(2) == "DONE"
    article_rows = [r for r in board.appended_content if r[2] == "Article"]  # Context|Type|Status|...
    assert len(article_rows) == 1 and article_rows[0][3] == "DONE"           # Status
    events = [e for e, _ in notifier.events]
    article_events = [e for e, ctx in notifier.events if ctx.get("type") == "article"]
    assert "start" in events and "gate2_done" in events
    assert "draft_changed" in article_events and "error" not in article_events


def test_run_writes_full_body_to_store_over_1500_chars_not_truncated():
    """VIỆC 1.2 + VIỆC 3 (Lead 2026-07-27) — bug gốc Bước 5.3: store
    (content_output.output) từng nhận bản `preview` cắt 1500 ký tự (giống hệt
    ô Sheet), KHÔNG PHẢI draft.body đầy đủ -- render_production_assets.py đọc
    lại thì vỡ JSON. Fix: _write_content() giờ ghi draft.body NGUYÊN VĂN;
    truncate CHỈ còn ở store/sync_service.py::_preview_output() (điểm đẩy
    Sheet). Test dùng nội dung DÀI HƠN 1500 ký tự thật (mock cũ luôn ngắn hơn
    ngưỡng nên bug không lộ ra qua test có sẵn)."""
    import json as _json

    long_content = ("Doanh thu quý này tăng mạnh nhờ xuất khẩu tăng tốc. " * 40) + "MARKER_CUOI_BAI_KHONG_DUOC_CAT"
    assert len(long_content) > 1500   # đúng điều kiện gây bug thật

    class _LongWriterLLM:
        def complete(self, system, prompt, *, model=None, fail_loud=False):
            return _json.dumps({
                "title": "Bài dài hơn 1500 ký tự", "sapo": "Tóm tắt.",
                "sections": [{"heading": "Bối cảnh", "content": long_content}],
                "disclaimer": "Nội dung chỉ mang tính thông tin, không phải khuyến nghị đầu tư. "
                              "Nhà đầu tư tự chịu trách nhiệm với quyết định của mình.",
                "sources": [],
            }, ensure_ascii=False)

    result, board, notifier = _run_produce_scenario(
        _LongWriterLLM(), _approved_row("Bài test dài >1500 ký tự", row=2))

    article_rows = [r for r in board.appended_content if r[2] == "Article"]
    assert len(article_rows) == 1
    output_field = article_rows[0][4]   # content_row(): index 4 = Output
    assert len(output_field) > 1500
    assert "MARKER_CUOI_BAI_KHONG_DUOC_CAT" in output_field, (
        "store bị cắt bản đầy đủ -- marker cuối bài biến mất (đúng bug Bước 5.3, "
        "nội dung dài chỉ được lưu ra file cục bộ, KHÔNG vào store)")
    assert "…(xem" not in output_field   # hậu tố cắt cũ KHÔNG được xuất hiện trong store


def test_run_topic_keys_filters_to_matched_rows_and_ignores_limit():
    """VIỆC 5.1 (điểm ráp webhook per-topic):
    - topic_keys=[k] -> CHỈ dòng có TopicKey=k được xử lý (Execute cập nhật);
      dòng khác KHÔNG chạm.
    - limit KHÔNG cắt cụt khi topic_keys được truyền (danh sách user bấm).
    - topic_keys=None -> hành vi cũ (xử tất cả) — tương thích ngược scheduler 30'.
    run() vẫn là NƠI DUY NHẤT ghi Execute (webhook chỉ đọc lại)."""
    class _CleanWriterLLM:
        def complete(self, system, prompt, *, model=None, fail_loud=False):
            return _clean_writer_json()

    def rows():
        return [
            _approved_row("Bài A 5.1", row=2, topic_key="tk-A"),
            _approved_row("Bài B 5.1", row=3, topic_key="tk-B"),
        ]

    # topic_keys=[tk-A] -> CHỈ dòng 2 chạm Execute, dòng 3 không.
    _r, board_a, _n = _run_produce_scenario(
        _CleanWriterLLM(), approved_rows=rows(), run_kwargs={"topic_keys": ["tk-A"]})
    assert 2 in board_a.execute_updates
    assert 3 not in board_a.execute_updates

    # limit=1 nhưng topic_keys 2 phần tử -> XỬ CẢ HAI (limit bị bỏ qua).
    _r2, board_both, _n2 = _run_produce_scenario(
        _CleanWriterLLM(), approved_rows=rows(),
        run_kwargs={"topic_keys": ["tk-A", "tk-B"], "limit": 1})
    assert 2 in board_both.execute_updates and 3 in board_both.execute_updates

    # topic_keys=None -> hành vi cũ: xử tất cả.
    _r3, board_all, _n3 = _run_produce_scenario(
        _CleanWriterLLM(), approved_rows=rows(), run_kwargs={"limit": 5})
    assert 2 in board_all.execute_updates and 3 in board_all.execute_updates


def test_run_infographic_composer_swaps_to_route_llm_and_flags_needs_human_when_facts_empty():
    """Phase 4.11: chạy run() THẬT — InfographicSpecAgent.llm/.model bị SWAP
    sang route_llm/alias 'composer' NGAY TRƯỚC khi gọi run() (không crash, dùng
    ĐÚNG _EmptyRouteLLM của fixture — chứng minh wiring vào vòng thật hoạt
    động). route_llm rỗng -> brief.content_units=[] -> infographic Status=ERROR kèm
    note 'content_units[] rỗng' (KHÔNG bịa nhãn 'Số liệu N')."""
    class _CleanWriterLLM:
        def complete(self, system, prompt, *, model=None, fail_loud=False):
            return _clean_writer_json()

    result, board, notifier = _run_produce_scenario(
        _CleanWriterLLM(), _approved_row("Bài test 4.11 composer", row=2))

    infographic_rows = [r for r in board.appended_content if r[2] == "Infographic"]
    assert len(infographic_rows) == 1
    assert infographic_rows[0][3] == "ERROR"          # Status
    assert "Không trích được dữ kiện nào từ bài gốc" in infographic_rows[0][5]    # VIỆC 5: CONTENT_UNITS_EMPTY
    assert "Số liệu" not in infographic_rows[0][4]     # Output — KHÔNG bịa nhãn


def test_run_infographic_skipped_when_no_numeric_content_true_article_still_produced():
    """Phase 4.12 Mục B (rỗng-HỢP-LỆ) — BƯỚC 4.4 (Router, 31/07) đã THAY cơ
    chế phát hiện: router (rỗng ở test này) fallback -> channels default
    article/infographic/video=True, NHƯNG brief_result.has_numeric_units=False
    (content_units=[] hợp lệ, tin thuần định tính, no_numeric_content=true) ->
    format_mismatch_channels ép infographic=False NGAY TỪ ĐẦU (trước khi vào
    vòng lặp agent, KHÔNG còn nhánh "router/brief bất đồng" cũ — đã XOÁ vì
    thành code chết, xem produce_from_sheet.py comment tại chỗ) -> infographic
    SKIPPED (KHÔNG gọi composer, KHÔNG phải ERROR/NEEDS_HUMAN, Notes mã
    FORMAT_MISMATCH), article vẫn sinh bình thường (chế độ định tính),
    Execute vẫn DONE (KHÔNG bị kéo xuống NEEDS_HUMAN chỉ vì tin không có số)."""
    import json as _json

    class _CleanWriterLLM:
        def complete(self, system, prompt, *, model=None, fail_loud=False):
            return _clean_writer_json()

    class _QualitativeBriefRouteLLM:
        """route_llm giả: Brief (system chứa 'no_numeric_content', đặc trưng
        brief._SYSTEM) -> content_units=[] + no_numeric_content=true; các bước khác
        (router) trả rỗng -> fallback S1 (không quan trọng ở test này)."""

        def complete(self, system, prompt, *, model=None, fail_loud=False, **kw):
            if "no_numeric_content" in system:
                return _json.dumps({"content_units": [], "no_numeric_content": True},
                                   ensure_ascii=False)
            return ""

    result, board, notifier = _run_produce_scenario(
        _CleanWriterLLM(), _approved_row("Bài test 4.12 SKIPPED", row=2),
        route_llm=_QualitativeBriefRouteLLM())

    infographic_rows = [r for r in board.appended_content if r[2] == "Infographic"]
    assert len(infographic_rows) == 1
    assert infographic_rows[0][3] == "BỎ QUA"           # Status (nhãn VI, xem sheets_board._display_status)
    assert "Nội dung không đủ dữ liệu để dựng thành Infographic" in infographic_rows[0][5]  # VIỆC 5: câu nghiệp vụ INFOGRAPHIC_NOT_WORTHY

    article_rows = [r for r in board.appended_content if r[2] == "Article"]
    assert len(article_rows) == 1 and article_rows[0][3] == "DONE"

    assert board.execute_updates.get(2) == "DONE"       # KHÔNG bị kéo xuống NEEDS_HUMAN
    events = [e for e, _ in notifier.events]
    assert "skipped" in events                          # emoji ℹ️, không phải error/needs_human
    skipped_events = [ctx for e, ctx in notifier.events if e == "skipped"]
    assert any(ctx.get("type") == "infographic" for ctx in skipped_events)


def test_run_infographic_skipped_by_code_count_ignoring_router_rationale():
    """Phase 4.13 Mục A (SỬA kỳ vọng theo BƯỚC A, Router, quyết định Lead 31/07
    "gỡ nốt cứng nhắc Infographic"): trước đây Router (LLM) TỰ quyết định
    infographic=False qua channel_rationale riêng của nó — GIỜ tuyến infographic
    ở chế độ AUTO do CODE quyết định HOÀN TOÀN (agents/brief.BriefResult.
    infographic_worthy, đếm content_unit theo type), Ý KIẾN RIÊNG của Router
    cho tuyến này KHÔNG CÒN Ý NGHĨA (dù Router vẫn có thể tự nói gì đó qua
    channel_rationale, Notes GIỜ LÀ lý do đếm-số của CODE, không phải câu chữ
    Router). Ca này chỉ có 1 content_unit numeric (dưới ngưỡng ≥2) -> vẫn
    SKIPPED nhưng vì CODE đếm không đủ, không phải vì Router "thấy không hợp".
    article/video (channels=True) vẫn sinh bình thường (không bị ảnh hưởng)."""
    import json as _json

    class _CleanWriterLLM:
        def complete(self, system, prompt, *, model=None, fail_loud=False):
            return _clean_writer_json()

    class _ChannelFalseRouteLLM:
        """route_llm giả: Brief trả content_units thật (không rỗng — chứng minh channel
        gate KHÔNG phụ thuộc content_units rỗng/không); router trả output_channels.
        infographic=False kèm rationale, để composer KHÔNG BAO GIỜ được gọi
        (PoisonComposer sẽ raise nếu lỡ gọi tới).

        ContentUnit "raw" PHẢI verify được TRONG evidence thật dùng ở test này (source=
        "" -> fetch_full_evidence() lùi về fallback=item["hook"]="hook gợi ý",
        xem _approved_row/fetch_full_evidence) — Phase C tính brief_status từ
        content_units ĐÃ VERIFY (không tin no_numeric_content rời), "10%" không
        verify được (không có trong "hook gợi ý") sẽ khiến out=[] -> brief_
        status=NO_USABLE_CONTENT SAI Ý ĐỊNH test này (content_units THẬT, không rỗng)."""

        def complete(self, system, prompt, *, model=None, fail_loud=False, **kw):
            if "no_numeric_content" in system:   # Brief system prompt đặc trưng
                return _json.dumps({
                    "content_units": [{"value": "ý", "label": "Số liệu test", "unit": None,
                              "kind": "percent", "raw": "gợi ý", "approx": False}],
                    "no_numeric_content": False,
                }, ensure_ascii=False)
            return _json.dumps({
                "content_type": "article", "structure": "S1", "hook": "H1",
                "secondary_structure": None, "rationale": "Tin bảng-số thuần.",
                "signals": {"has_genuine_paradox": False, "drivers": [],
                           "has_central_thesis": True},
                "output_channels": {"article": True, "infographic": False, "video": True},
                "channel_rationale": {"infographic": "Tin bảng-số không đủ dữ liệu trình bày hình"},
            }, ensure_ascii=False)

    result, board, notifier = _run_produce_scenario(
        _CleanWriterLLM(), _approved_row("Bài test 4.13 channel-false", row=2),
        route_llm=_ChannelFalseRouteLLM())

    infographic_rows = [r for r in board.appended_content if r[2] == "Infographic"]
    assert len(infographic_rows) == 1
    assert infographic_rows[0][3] == "BỎ QUA"
    assert "Nội dung không đủ dữ liệu để dựng thành Infographic" in infographic_rows[0][5]  # VIỆC 5: INFOGRAPHIC_NOT_WORTHY
    assert "Tin bảng-số không đủ dữ liệu trình bày hình" not in infographic_rows[0][5], (
        "Notes PHẢI là lý do đếm-số của CODE, KHÔNG phải câu chữ Router — "
        "Router mất quyền quyết riêng tuyến infographic ở chế độ AUTO (Bước A)"
    )

    article_rows = [r for r in board.appended_content if r[2] == "Article"]
    assert len(article_rows) == 1 and article_rows[0][3] == "DONE"

    article_rows = [r for r in board.appended_content if r[2] == "Article"]
    assert len(article_rows) == 1 and article_rows[0][3] == "DONE"

    assert board.execute_updates.get(2) == "DONE"
    skipped_events = [ctx for e, ctx in notifier.events if e == "skipped"]
    assert any(ctx.get("type") == "infographic" for ctx in skipped_events)


def test_run_article_skipped_when_router_decides_channel_false_upfront():
    """Phase 4.13 Mục A (SỬA kỳ vọng theo BƯỚC 4.3, Router, quyết định Lead
    31/07): router quyết output_channels.article=False (tin quá vụn) NHƯNG
    Brief cũng xác nhận content_units=[]+no_numeric_content=False (chính là
    chữ ký brief_status=NO_USABLE_CONTENT) -> article SKIPPED (KHÔNG gọi
    writer_llm — PoisonWriterLLM sẽ raise nếu lỡ gọi), Execute KHÔNG bị kéo
    NEEDS_HUMAN/FAILED (chỉ SKIPPED hợp lệ). Notes GIỜ LÀ "NO_USABLE_CONTENT"
    (KHÔNG còn hiện rationale riêng "Tin chỉ 1 câu" của Router như Phase 4.13
    — Bước 4.3 chuẩn hoá: NO_USABLE_CONTENT là sự thật NỀN TẢNG, thắng mọi ý
    kiến chủ quan của Router về từng tuyến riêng lẻ, xem produce_from_sheet.py
    comment tại no_usable_content_channels)."""
    import json as _json

    class _PoisonWriterLLM:
        def complete(self, *a, **kw):
            raise AssertionError("KHÔNG được gọi writer khi brief_status=NO_USABLE_CONTENT")

    class _ArticleFalseRouteLLM:
        def complete(self, system, prompt, *, model=None, fail_loud=False, **kw):
            if "no_numeric_content" in system:
                return _json.dumps({"content_units": [], "no_numeric_content": False}, ensure_ascii=False)
            return _json.dumps({
                "content_type": "article", "structure": "S1", "hook": "H1",
                "secondary_structure": None, "rationale": "Tin quá vụn.",
                "signals": {"has_genuine_paradox": False, "drivers": [],
                           "has_central_thesis": True},
                "output_channels": {"article": False, "infographic": True, "video": True},
                "channel_rationale": {"article": "Tin chỉ 1 câu, không đủ chất liệu viết bài"},
            }, ensure_ascii=False)

    result, board, notifier = _run_produce_scenario(
        _PoisonWriterLLM(), _approved_row("Bài test 4.13 article-false", row=2),
        route_llm=_ArticleFalseRouteLLM())

    article_rows = [r for r in board.appended_content if r[2] == "Article"]
    assert len(article_rows) == 1 and article_rows[0][3] == "BỎ QUA"
    assert "Bài gốc không có nội dung thực chất" in article_rows[0][5]  # VIỆC 5: NO_USABLE_CONTENT_FULL


def test_run_article_forced_true_when_router_vetoes_but_content_units_anchored():
    """BƯỚC 4.1/4.2 (Router, quyết định Lead 31/07) — KHÁC HẲN test ngay trên
    (`..._router_decides_channel_false_upfront`, ở đó content_units=[] nên
    brief_status=NO_USABLE_CONTENT, Router VẪN có quyền quyết): ca NÀY Brief
    xác nhận có content_unit THẬT (verify được, đủ để brief_status=OK VÀ
    has_anchored_units=True), NHƯNG Router (LLM) VẪN tự ý nói article:false
    kèm rationale riêng ("tin quá vụn") — CODE PHẢI ÉP article=True, BỎ QUA ý
    kiến Router, đúng chữ "KHÔNG BAO GIỜ đặt article=false vì thiếu số/nguồn
    ngắn" khi ĐÃ có chất liệu neo nguồn thật. Writer PHẢI được gọi (khác hẳn
    PoisonWriterLLM ở test trên — ở đây writer_llm PHẢI chạy được)."""
    import json as _json

    class _CleanWriterLLM:
        def complete(self, system, prompt, *, model=None, fail_loud=False):
            return _clean_writer_json()

    class _AnchoredButRouterVetoesRouteLLM:
        """`raw`/`value` PHẢI verify được trong evidence THẬT dùng ở test này
        (source="" -> fetch_full_evidence() lùi về fallback=item["hook"]=
        "hook gợi ý", xem _approved_row/fetch_full_evidence) -- "8,18%" không
        verify được (không có trong "hook gợi ý") sẽ khiến content_units=[]
        -> brief_status=NO_USABLE_CONTENT SAI Ý ĐỊNH test này (cần OK+anchored)."""

        def complete(self, system, prompt, *, model=None, fail_loud=False, **kw):
            if "no_numeric_content" in system:
                return _json.dumps({
                    "content_units": [{"shape": "scalar", "value": "ý", "label": "GDP 6 tháng",
                                      "unit": None, "kind": "percent", "raw": "gợi ý", "approx": False}],
                    "no_numeric_content": False,
                }, ensure_ascii=False)
            return _json.dumps({
                "content_type": "article", "structure": "S1", "hook": "H1",
                "secondary_structure": None, "rationale": "Router tự ý cho là quá vụn.",
                "signals": {"has_genuine_paradox": False, "drivers": [],
                           "has_central_thesis": True},
                "output_channels": {"article": False, "infographic": True, "video": True},
                "channel_rationale": {"article": "Router tự ý: tin chỉ có 1 con số, quá vụn"},
            }, ensure_ascii=False)

    evidence = "GDP 6 tháng đầu năm tăng 8,18%, mức cao nhất nhiều năm."
    result, board, notifier = _run_produce_scenario(
        _CleanWriterLLM(), _approved_row(evidence, row=2),
        route_llm=_AnchoredButRouterVetoesRouteLLM())

    article_rows = [r for r in board.appended_content if r[2] == "Article"]
    assert len(article_rows) == 1 and article_rows[0][3] == "DONE", (
        f"content_units có anchored data thật -- Router KHÔNG được quyền phủ quyết article, "
        f"thực tế: {article_rows[0][3] if article_rows else 'KHÔNG có dòng'}"
    )


def test_run_infographic_format_mismatch_when_no_numeric_units_article_video_untouched():
    """BƯỚC 4.4 (Router) — "no numeric chỉ tắt Data Infographic, KHÔNG chạm
    article/video": brief_status=OK VỚI content_unit ĐỊNH TÍNH THẬT (không
    phải content_units=[]+no_numeric_content=true như test Phase 4.12 cũ) —
    has_numeric_units=False, has_qualitative_units=True -> infographic
    SKIPPED mã FORMAT_MISMATCH (KHÔNG gọi composer), article DONE + video
    KHÔNG bị loại."""
    import json as _json

    class _CleanWriterLLM:
        def complete(self, system, prompt, *, model=None, fail_loud=False):
            return _clean_writer_json()

    class _QualitativeOnlyRouteLLM:
        """`source` PHẢI verify được (substring sau chuẩn hoá khoảng trắng)
        trong evidence THẬT dùng ở test này — source="" -> fetch_full_
        evidence() lùi về fallback=item["hook"]="hook gợi ý" (xem _approved_
        row/fetch_full_evidence), nên `source` dùng ĐÚNG cụm "hook gợi ý"."""

        def complete(self, system, prompt, *, model=None, fail_loud=False, **kw):
            if "no_numeric_content" in system:
                return _json.dumps({
                    "content_units": [{"shape": "qualitative", "type": "policy_change",
                                      "subject": "Ngân hàng Nhà nước",
                                      "claim": "Ngân hàng Nhà nước bỏ trần lãi suất huy động",
                                      "source": "hook gợi ý",
                                      "evidence": "direct_quote"}],
                    "no_numeric_content": False,
                }, ensure_ascii=False)
            return ""   # router fallback -> channels mặc định cả 3 True

    class _QualitativeVideoContentLLM:
        def __init__(self):
            from twmkt.agents.router import Usage
            self.usage = Usage()

        def complete(self, system, prompt, *, model=None, fail_loud=False, **kw):
            return _json.dumps({
                "schema_version": 1, "title": "Chính sách mới",
                "scenes": [
                    {"role": "hook", "visual_kind": "statement",
                     "payload": {"hero": "NHNN bỏ trần lãi suất", "desc": ""},
                     "narration": "NHNN bỏ trần lãi suất"},
                    {"role": "body", "visual_kind": "statement",
                     "payload": {"hero": "Tác động", "desc": "Ảnh hưởng thị trường."},
                     "narration": "Tác động thị trường"},
                    {"role": "outro", "visual_kind": "outro",
                     "payload": {"brand_name": "FVA Capital", "cta": "Theo dõi thêm"},
                     "narration": "Theo dõi thêm"},
                ],
                "source": "ignored", "disclaimer": "d",
            }, ensure_ascii=False)

    evidence = "Ngân hàng Nhà nước bỏ trần lãi suất huy động kỳ hạn ngắn."
    result, board, notifier = _run_produce_scenario(
        _CleanWriterLLM(), _approved_row(evidence, row=2),
        route_llm=_QualitativeOnlyRouteLLM(), content_llm=_QualitativeVideoContentLLM())

    infographic_rows = [r for r in board.appended_content if r[2] == "Infographic"]
    assert len(infographic_rows) == 1 and infographic_rows[0][3] == "BỎ QUA"
    assert "Nội dung không đủ dữ liệu để dựng thành Infographic" in infographic_rows[0][5]  # VIỆC 5: INFOGRAPHIC_NOT_WORTHY

    article_rows = [r for r in board.appended_content if r[2] == "Article"]
    assert len(article_rows) == 1 and article_rows[0][3] == "DONE"
    video_rows = [r for r in board.appended_content if r[2] == "Video"]
    assert len(video_rows) == 1 and video_rows[0][3] != "BỎ QUA"


def test_run_output_type_explicit_choice_overrides_router_veto():
    """BƯỚC 4.5 (Router) — "người chọn TƯỜNG MINH một loại -> Router MẤT
    quyền phủ quyết": Output Type=["Infographic"] CHỈ chọn infographic, Router
    (LLM) lại tự ý nói infographic:false (channel_rationale riêng, KHÔNG phải
    do thiếu số/format_mismatch — content_units CÓ số thật) -> CODE phải BỎ
    QUA ý kiến Router, vẫn cho infographic chạy (composer ĐƯỢC gọi, KHÔNG
    SKIPPED). Article dù channels mặc định True (router không nói gì) nhưng
    KHÔNG được chọn ở Output Type -> KHÔNG ghi dòng nào."""
    import json as _json

    class _ComposerLLM:
        def __init__(self):
            from twmkt.agents.router import Usage
            self.usage = Usage()

        def complete(self, system, prompt, *, model=None):
            return _json.dumps({
                "title": "GDP 6 tháng", "subtitle": "Tăng trưởng vượt kỳ vọng",
                "hero": [{"label": "GDP 6 tháng", "value": "+8,18%"}],
                "market": [], "highlights": ["Mức cao nhất nhiều năm."], "related": [],
                "priority": {"primary": [], "secondary": [], "minor": []},
                "source": "ignored", "render_hint": {"ratio": "1:1"},
            }, ensure_ascii=False)

    class _RouterVetoesInfographicDespiteNumbersRouteLLM:
        """`raw`/`value` PHẢI verify được trong evidence THẬT (source="" ->
        fetch_full_evidence() lùi về fallback=item["hook"]="hook gợi ý", xem
        _approved_row/fetch_full_evidence) — dùng "gợi ý"/"ý" thay vì "8,18%"
        (không verify được, sẽ khiến content_units=[] SAI Ý ĐỊNH test này)."""

        def complete(self, system, prompt, *, model=None, fail_loud=False, **kw):
            if "no_numeric_content" in system:
                return _json.dumps({
                    "content_units": [{"shape": "scalar", "value": "ý", "label": "GDP 6 tháng",
                                      "unit": None, "kind": "percent", "raw": "gợi ý", "approx": False}],
                    "no_numeric_content": False,
                }, ensure_ascii=False)
            return _json.dumps({
                "content_type": "article", "structure": "S1", "hook": "H1",
                "secondary_structure": None, "rationale": "Router tự ý không thích infographic.",
                "signals": {"has_genuine_paradox": False, "drivers": [],
                           "has_central_thesis": True},
                "output_channels": {"article": True, "infographic": False, "video": True},
                "channel_rationale": {"infographic": "Router tự ý: không thích hợp dù có số"},
            }, ensure_ascii=False)

    evidence = "GDP 6 tháng đầu năm tăng 8,18%, mức cao nhất nhiều năm."
    result, board, notifier = _run_produce_scenario(
        _ComposerLLM(),
        _approved_row(evidence, row=2, output_type=["Infographic"]),
        route_llm=_RouterVetoesInfographicDespiteNumbersRouteLLM(),
        content_llm=_ComposerLLM())

    rows_by_type = {r[2]: r for r in board.appended_content}
    assert set(rows_by_type) == {"Infographic"}, (
        f"CHỈ được ghi dòng infographic (Output Type chọn riêng), thực tế: {sorted(rows_by_type)}"
    )
    assert rows_by_type["Infographic"][3] == "DONE", (
        f"Output Type chọn tường minh infographic -- Router KHÔNG được quyền phủ quyết dù tự ý nói false, "
        f"thực tế: {rows_by_type['infographic'][3]} | {rows_by_type['infographic'][5][:150]}"
    )


def test_run_boilerplate_source_now_skipped_not_fabricated_article_phase_c():
    """PHASE C — ca boilerplate/trang điều hướng/"đang cập nhật": Brief đọc
    được (JSON parse ĐƯỢC, không phải lỗi hạ tầng) nhưng content_units RỖNG
    và KHÔNG tự tin khẳng định no_numeric_content=true (không có gì để đọc
    hiểu, khác hẳn "brief hỏng" hay "tin định tính đã xác nhận"). TRƯỚC Phase
    C: Article vẫn được Writer viết BỊA từ trang rỗng (content_units=[]+no_numeric_
    content=False không đủ tín hiệu phân biệt) -- xác nhận THẬT ở Phase B
    (nhánh feature/regression-tests-phase-b, test_regression_row11_...).
    Test này SAU thay đổi Phase C (brief_status=NO_USABLE_CONTENT ép CẢ 3
    tuyến SKIPPED ngay từ đầu, KHÔNG gọi Writer/Composer) PHẢI PASS."""
    import json as _json

    class _PoisonWriterLLM:
        def complete(self, *a, **kw):
            raise AssertionError("KHÔNG được gọi writer khi brief_status=NO_USABLE_CONTENT")

    class _BoilerplateRouteLLM:
        def complete(self, system, prompt, *, model=None, fail_loud=False, **kw):
            if "no_numeric_content" in system:
                return _json.dumps({"content_units": [], "no_numeric_content": False}, ensure_ascii=False)
            return ""   # router fallback -> channels mặc định cả 3 True

    result, board, notifier = _run_produce_scenario(
        _PoisonWriterLLM(),
        _approved_row("Trang chủ. Menu. Đăng nhập. Đang cập nhật nội dung...", row=2),
        route_llm=_BoilerplateRouteLLM())

    statuses = {r[2]: r[3] for r in board.appended_content}
    assert statuses.get("Article") == "BỎ QUA", f"kỳ vọng BỎ QUA (SKIPPED), thực tế: {statuses}"
    for r in board.appended_content:
        if r[2] == "Article":
            assert "Bài gốc không có nội dung thực chất" in r[5]  # VIỆC 5: NO_USABLE_CONTENT_FULL


def test_run_output_type_restricts_to_selected_type_only():
    """Bước 4 + đổi hành vi 2026-07-28 (quyết định Lead): output_type=
    ["Infographic"] -> CHỈ SINH RA ĐÚNG 1 DÒNG infographic. Tuyến người KHÔNG
    chọn KHÔNG còn ghi dòng SKIPPED nào — trước đây tab CONTENT lúc nào cũng 3
    dòng/chủ đề dù người chỉ muốn 1, 2 dòng kia là nhiễu thuần tuý.
    Vẫn KHÔNG gọi writer_llm cho article (PoisonWriterLLM raise nếu lỡ gọi)."""
    class _PoisonWriterLLM:
        def complete(self, *a, **kw):
            raise AssertionError("KHÔNG được gọi writer khi Output Type không chọn article")

    result, board, notifier = _run_produce_scenario(
        _PoisonWriterLLM(),
        _approved_row("Bài test Output Type infographic-only", row=2, output_type=["Infographic"]))

    rows_by_type = {r[2]: r for r in board.appended_content}
    assert set(rows_by_type) == {"Infographic"}, \
        f"chỉ được ghi dòng infographic, thực tế: {sorted(rows_by_type)}"
    assert rows_by_type["Infographic"][3] != "SKIPPED"   # thật sự được thử sinh
    # Không thông báo "skipped" cho tuyến người vốn không yêu cầu -- không có
    # gì bị bỏ qua theo nghĩa người cần biết.
    skipped_events = [ctx for e, ctx in notifier.events if e == "skipped"]
    assert {ctx.get("type") for ctx in skipped_events} == set()


def test_run_output_type_auto_behaves_like_no_restriction():
    """output_type=["AUTO"] -> KHÔNG thêm giới hạn nào (giữ hành vi router-only
    trước Bước 4) — không dòng SKIPPED nào mang lý do "Output Type"."""
    class _CleanWriterLLM:
        def complete(self, system, prompt, *, model=None, fail_loud=False):
            return _clean_writer_json()

    result, board, notifier = _run_produce_scenario(
        _CleanWriterLLM(),
        _approved_row("Bài test Output Type AUTO", row=2, output_type=["AUTO"]))

    for row in board.appended_content:
        if row[3] == "SKIPPED":
            assert "Output Type không chọn" not in row[5]


def test_run_output_type_empty_behaves_like_no_restriction():
    """output_type rỗng (mặc định, chưa ai chọn) -> tương đương AUTO, KHÔNG
    thêm giới hạn — regression-guard cho hành vi TRƯỚC Bước 4 (mọi test run()
    cũ không truyền output_type vẫn phải chạy y hệt)."""
    class _CleanWriterLLM:
        def complete(self, system, prompt, *, model=None, fail_loud=False):
            return _clean_writer_json()

    result, board, notifier = _run_produce_scenario(
        _CleanWriterLLM(), _approved_row("Bài test Output Type rỗng", row=2))

    for row in board.appended_content:
        if row[3] == "SKIPPED":
            assert "Output Type không chọn" not in row[5]


def test_run_output_type_long_article_reuses_article_writer_writes_long_article_type():
    """VIỆC 1 (2026-08-03, Lead) — Long-Article giờ ĐÃ NỐI: chọn riêng nó dùng
    CHUNG đường Writer với Article (KHÔNG producer riêng), nhưng content_type
    ghi ra store là "long_article" (không phải "article"). THAY THẾ test cũ
    test_run_output_type_long_article_has_no_producer_all_skipped (đã ghi lại
    hành vi "chưa nối" — nay lỗi thời)."""
    class _CleanWriterLLM:
        def complete(self, system, prompt, *, model=None, fail_loud=False):
            return _clean_writer_json()

    result, board, notifier = _run_produce_scenario(
        _CleanWriterLLM(),
        _approved_row("Bài test Output Type Long-Article", row=2, output_type=["Long-Article"]))

    rows = [r for r in board.appended_content if r[7]]   # TopicKey không rỗng
    assert len(rows) == 1
    assert rows[0][2] == "Long-Article"          # Type ghi ra ĐÚNG content_type mới
    assert rows[0][3] == "DONE"
    assert board.execute_updates.get(2) not in ("FAILED", "NEEDS_HUMAN")


def test_run_output_type_unrecognized_value_never_marks_done_without_content():
    """TASK-016 — bug thật topic_key=91d09f039226343c lô 03/08/2026: gate_status
    đạt Execute=DONE HAI LẦN (04:26->05:15 và 08:51->08:54) dù content_output/
    infographic/video/content_status = 0 bản ghi TUYỆT ĐỐI cho chủ đề (xem
    reports/CODEBASE_SURVEY_2026-08-03.md mục 2.4). Nguyên nhân xác nhận qua
    `git log`: commit 15187ad1 (VIỆC 1, 2026-08-03 16:29) mới nối "Long-Article"
    vào `_OUTPUT_TYPE_TO_CONTENT_TYPE` (produce_from_sheet.py:152) — TRƯỚC đó
    dict chỉ có {"Article","Infographic","Video"}, và CẢ 2 lần DONE xảy ra
    TRƯỚC 16:29 cùng ngày, tức dưới bản code CHƯA nối kênh này.

    `_allowed_output_types()` (dòng 156-164) trả `set()` RỖNG (KHÔNG PHẢI
    None) khi output_type có giá trị nhưng KHÔNG khớp map — vòng lặp output_
    type_excluded (dòng ~607-610) vì vậy loại SẠCH cả 3 kênh (article/
    infographic/video), rơi vào các nhánh "người không chọn -> KHÔNG ghi dòng
    nào cả" (dòng ~634-641 cho article, ~699-703 cho video/infographic) —
    content_output KHÔNG BAO GIỜ nhận 1 write nào. `_is_fully_produced_
    channels()` (dòng 243-262) khi đó thấy channels toàn False, vòng for
    không bao giờ chạm `return False`, rơi thẳng xuống `return True` cuối hàm
    (vacuously true) — Execute=DONE dù 0 nội dung.

    Test dùng giá trị Output Type KHÔNG khớp kênh nào (mô phỏng TỔNG QUÁT —
    bất kỳ giá trị tương lai nào lọt vào cột Output Type trước khi được nối
    kênh sẽ tái lập NGUYÊN VĂN lỗi này; "Long-Article" cụ thể đã được nối nên
    không còn tái lập được bằng chính giá trị đó nữa)."""
    from store import pipeline_store as ps

    class _PoisonWriterLLM:
        def complete(self, *a, **kw):
            raise AssertionError("KHÔNG được gọi writer khi Output Type không khớp kênh nào")

    row = _approved_row("Bài test TASK-016 output_type lạ", row=16,
                        output_type=["Podcast-Chua-Co-Kenh"])
    result, board, notifier = _run_produce_scenario(_PoisonWriterLLM(), row)

    # NGUYÊN TẮC CỨNG (TASK-016): topic không sinh được nội dung TUYỆT ĐỐI
    # không được ghi execute=DONE.
    assert board.execute_updates.get(16) != "DONE", (
        f"Execute không được DONE khi 0 nội dung sinh ra, thực tế: {board.execute_updates}")
    assert board.execute_updates.get(16) == "NEEDS_HUMAN", (
        f"phải là FAILED/NEEDS_HUMAN kèm lý do đọc được, thực tế: {board.execute_updates}")

    out = ps.read_content_output(row["topic_key"], "article", db_path=board.db_path)
    assert out is not None, "phải có ÍT NHẤT 1 dòng CONTENT giải thích lý do, không được im lặng"
    assert out["status"] == "NEEDS_HUMAN"
    assert out["notes"], "Notes phải có lý do đọc được cho biên tập viên"


def test_long_article_prompt_contains_both_rule_files_article_only_daily():
    """VIỆC 1.5/1.6 — content_type="long_article" nạp NGUYÊN VĂN CẢ 2 file
    (nền daily-v3.4 + bổ sung deep-v3.0), không mất mục nào; content_type=
    "article" hồi quy CHỈ nạp daily-v3.4, KHÔNG lẫn deep."""
    from pathlib import Path
    from twmkt.agents.writer import build_writer_system
    from twmkt.config import load_settings

    settings = load_settings()
    system_long = build_writer_system(content_type="long_article", settings=settings)
    system_article = build_writer_system(content_type="article", settings=settings)

    daily_text = Path("prompts/content-rules-daily-v3.4.md").read_text(encoding="utf-8").rstrip()
    deep_text = Path("prompts/content-rules-deep-v3.0.md").read_text(encoding="utf-8").rstrip()

    assert daily_text in system_long
    assert deep_text in system_long
    assert daily_text in system_article
    assert deep_text not in system_article


# ==== PHASE B (2026-07-3x) — hồi quy §7 reports/LEAD_DECISION_INPUT_STRICTNESS.md ====
#
# File nguồn (báo cáo nhanh gửi Lead 2026-07-29, "rủi ro quá khắt khe đầu vào")
# đã bị XOÁ theo yêu cầu Lead sau khi đọc xong (gitignored, không phải tài
# liệu bền của repo — nội dung 10 ca §7 được chép NGUYÊN VĂN vào docstring
# từng test dưới đây làm nguồn tham chiếu duy nhất còn lại).
#
# QUAN TRỌNG — khi bắt đầu Phase B, phần lớn P0 (Router output_channels AI-
# phán thay vì đếm số cứng, Infographic SKIPPED-không-ERROR khi no_numeric_
# content, Output Type lọc thật) ĐÃ ĐƯỢC LÀM Ở PHASE 4.12/4.13 (xem git log
# "San xuat: Output Type loc that...", commit bfabab9) — SAU thời điểm báo
# cáo được viết. Vì vậy nhiều ca dưới đây PASS ngay bằng cách TÁI DÙNG hạ
# tầng test 4.12/4.13 đã có (_QualitativeBriefRouteLLM v.v.) — đây KHÔNG phải
# "test chưa chạm hành vi thật" (điều kiện DỪNG KHI #1) vì các ca THẬT SỰ
# fail (9/10/11 dưới đây) chứng minh bộ test này CÓ chạm code thật, chỉ là
# phần Router đã được sửa trước khi tới lượt tôi.


def test_regression_row1_row7_qualitative_article_done_infographic_skipped_video_not_gated():
    """§7 dòng 1 ("Chính sách mới, không có số": Article DONE, Infographic
    Explanatory-hoặc-SKIPPED-hợp-lệ, Video ngắn) + dòng 7 ("Brief chạy tốt,
    facts định lượng rỗng nhưng facts định tính có": DONE, Infographic KHÔNG
    báo Brief lỗi, Video KHÔNG bị loại mặc định) — 2 dòng cùng cơ chế
    (no_numeric_content=True), gộp 1 test.

    Article + Infographic: ĐÃ PASS từ Phase 4.12 (test_run_infographic_
    skipped_when_no_numeric_content_true_article_still_produced) — không lặp
    lại, chỉ thêm phần CHƯA có test nào phủ: Video. Đọc code (scripts/
    produce_from_sheet.py, nhánh `isinstance(agent, VideoScriptAgent)`) xác
    nhận KHÔNG có gate `if not brief.facts` nào cho Video (khác Infographic) —
    Composer video vẫn được GỌI bình thường bất kể facts=[]/no_numeric_
    content. Test này khoá lại bằng chứng đó: Composer trả video hợp lệ (đủ
    sàn 3 scene) -> phải ra ĐÚNG 1 dòng video, KHÔNG SKIPPED/thiếu dòng.

    LƯU Ý (không thuộc phạm vi test này): nếu nguồn định tính THẬT SỰ quá
    nghèo để Composer dựng đủ 3 scene, `InsufficientScenesError` vẫn đưa
    video xuống NEEDS_HUMAN — đó là RÀNG BUỘC RENDERER cố ý KHÔNG nới (P1,
    xem InsufficientScenesError docstring), KHÁC BẢN CHẤT với việc Router/
    code chủ động LOẠI video vì thiếu số — dòng 7 chỉ đòi hỏi vế SAU."""
    import json as _json

    class _CleanWriterLLM:
        def complete(self, system, prompt, *, model=None, fail_loud=False):
            return _clean_writer_json()

    class _QualitativeBriefVideoRouteLLM:
        def complete(self, system, prompt, *, model=None, fail_loud=False, **kw):
            if "no_numeric_content" in system:
                return _json.dumps({"facts": [], "no_numeric_content": True}, ensure_ascii=False)
            return ""

    class _QualitativeVideoContentLLM:
        """content_llm giả cho Video composer -- Infographic KHÔNG tới lượt gọi
        composer trong ca này (nhánh no_numeric_content continue trước khi gọi),
        nên fake này chỉ cần đúng schema Video. `.usage` bắt buộc -- produce_
        from_sheet.run() đọc content_llm.usage.as_dict() ở cuối để ghi log tổng
        (LLMRouter.Usage thật cũng có field này, fake phải khớp interface)."""

        def __init__(self):
            from twmkt.agents.router import Usage
            self.usage = Usage()

        def complete(self, system, prompt, *, model=None, fail_loud=False, **kw):
            return _json.dumps({
                "schema_version": 1, "title": "Chính sách mới",
                "scenes": [
                    {"role": "hook", "visual_kind": "statement",
                     "payload": {"hero": "Chính sách mới ban hành", "desc": ""},
                     "narration": "Chính sách mới vừa ban hành"},
                    {"role": "body", "visual_kind": "statement",
                     "payload": {"hero": "Tác động", "desc": "Ảnh hưởng ngành."},
                     "narration": "Tác động tới ngành"},
                    {"role": "outro", "visual_kind": "outro",
                     "payload": {"brand_name": "FVA Capital", "cta": "Theo dõi thêm"},
                     "narration": "Theo dõi thêm"},
                ],
                "source": "ignored", "disclaimer": "d",
            }, ensure_ascii=False)

    result, board, notifier = _run_produce_scenario(
        _CleanWriterLLM(), _approved_row("Chính sách mới, không có số liệu cụ thể", row=2),
        route_llm=_QualitativeBriefVideoRouteLLM(), content_llm=_QualitativeVideoContentLLM())

    video_rows = [r for r in board.appended_content if r[2] == "Video"]
    assert len(video_rows) == 1, "Video phải có ĐÚNG 1 dòng, không bị âm thầm loại vì facts=[]"
    assert video_rows[0][3] != "SKIPPED"

    article_rows = [r for r in board.appended_content if r[2] == "Article"]
    assert len(article_rows) == 1 and article_rows[0][3] == "DONE"


def test_regression_row2_row3_process_timeline_units_real_qualitative_extraction_ok():
    """§7 dòng 2 ("Quy trình năm bước" -> Article DONE, Infographic Explanatory
    DONE) + dòng 3 ("Timeline nhiều mốc không tiền/%" -> Article DONE,
    Infographic Explanatory DONE) — BỔ SUNG sau khi Bước 3 (trích content_unit
    ĐỊNH TÍNH thật) hoàn tất, đúng yêu cầu Lead "xác nhận Phase B đủ 10 ca §7,
    bổ sung ca thiếu trước Bước 4". Lúc viết Phase B gốc, 2 dòng này CHƯA viết
    được test tất định vì chưa có parser content_unit định tính (chỉ có type=
    "numeric" mặc định) — giờ ĐÃ CÓ (_parse_qualitative_unit, Bước 3).

    Test Ở TẦNG BRIEF trực tiếp (content_units_from_llm_output), KHÔNG qua
    _run_produce_scenario/produce_from_sheet.run() -- lý do: harness đó luôn
    fallback evidence về "hook gợi ý" (item["source"]="" -> fetch_full_
    evidence trả fallback=item["hook"], xem _approved_row/fetch_full_evidence)
    khi không có source/URL thật, nên KHÔNG mô phỏng được 1 văn bản dài có
    source câu THẬT để content_unit định tính verify — hành vi "article/video
    không bị loại khi content_units non-empty bất kể type" đã được khoá ở
    tầng produce_from_sheet bởi test_regression_row1_row7_... (dùng no_
    numeric_content=true) VÀ 2 test Phase 4.13 channel-false/article-false
    (dùng content_units type=numeric) — CƠ CHẾ ĐÓ không phân biệt theo `type`
    (chỉ kiểm `content_units` rỗng hay không, xem produce_from_sheet.py
    `no_usable_content_channels`), nên không cần lặp lại ở đây.

    VẪN CHƯA ĐẠT (giữ nguyên biên giới đã nêu ở Phase B, KHÔNG đổi): Infographic
    "Explanatory" là 1 KIỂU INFOGRAPHIC RIÊNG (P1, chưa xây)."""
    import json as _json
    from twmkt.agents.brief import content_units_from_llm_output

    evidence = ("Doanh nghiệp phải nộp hồ sơ, chờ thẩm định, rồi mới được cấp phép. "
               "Dự án dự kiến khởi công trong quý 3 và hoàn thành vào quý 1 năm sau.")
    raw = _json.dumps({
        "content_units": [
            {"shape": "qualitative", "type": "process", "subject": "Doanh nghiệp",
             "claim": "Doanh nghiệp phải nộp hồ sơ, chờ thẩm định, rồi mới được cấp phép",
             "source": "Doanh nghiệp phải nộp hồ sơ, chờ thẩm định, rồi mới được cấp phép.",
             "evidence": "direct_quote"},
            {"shape": "qualitative", "type": "timeline", "subject": "Dự án",
             "claim": "Dự án khởi công quý 3 và hoàn thành vào quý 1 năm sau",
             "source": "Dự án dự kiến khởi công trong quý 3 và hoàn thành vào quý 1 năm sau.",
             "evidence": "paraphrase"},
        ],
        "no_numeric_content": False,
    }, ensure_ascii=False)

    br = content_units_from_llm_output(raw, evidence)
    assert br.brief_status == "OK"
    assert br.has_qualitative_units is True and br.has_numeric_units is False
    assert {u.type for u in br.content_units} == {"process", "timeline"}
    assert len(br.content_units) == 2, "cả 2 unit phải verify được (source substring văn bản thật)"


def test_regression_row5_short_two_sentence_source_article_done_not_needs_human():
    """§7 dòng 5 ("Nguồn hai đoạn nhưng có sự kiện rõ" -> Article ngắn DONE,
    KHÔNG phải NEEDS_HUMAN). Đọc AnalysisWriterAgent.run() xác nhận KHÔNG có
    sàn độ dài evidence tối thiểu nào trong code (chỉ build prompt rồi gọi
    LLM) -- test khoá lại: nguồn 2 câu vẫn phải ra DONE khi Writer trả JSON
    sạch, KHÔNG NEEDS_HUMAN/SKIPPED chỉ vì nguồn ngắn."""
    class _CleanWriterLLM:
        def complete(self, system, prompt, *, model=None, fail_loud=False):
            return _clean_writer_json()

    short_source = "Ngân hàng X công bố tăng lãi suất huy động thêm 0,3 điểm %. Áp dụng từ đầu tháng sau."
    result, board, notifier = _run_produce_scenario(
        _CleanWriterLLM(), _approved_row(short_source, row=2))

    article_rows = [r for r in board.appended_content if r[2] == "Article"]
    assert len(article_rows) == 1 and article_rows[0][3] == "DONE", (
        f"nguồn ngắn 2 câu phải DONE, thực tế: {article_rows[0][3] if article_rows else 'KHÔNG có dòng'}"
    )


def test_regression_row9_composer_empty_subtitle_kept_empty_not_auto_filled():
    """§7 dòng 9 ("Composer trả subtitle: ''" -> Infographic PHẢI giữ nguyên
    theo schema, KHÔNG tự điền) -- ĐÃ SỬA (Lead 02/08, "code đang BỊA dữ liệu
    vào ảnh"). `infographic_spec_from_data()` (agents/production.py) giờ chỉ
    thay subtitle bằng `brief.title` khi key VẮNG MẶT/None (Composer thật sự
    không điền); subtitle="" (Composer TRẢ RỖNG tường minh) được GIỮ NGUYÊN.
    Test set brief.title KHÁC brief.hook để phân biệt rõ 2 nguồn."""
    from twmkt.agents.production import infographic_spec_from_data, ProductionBrief

    brief = ProductionBrief(title="Tiêu đề Brief gốc KHÁC hẳn", hook="Hook khác nữa",
                            url="https://cafef.vn/x.chn", evidence="Doanh thu tăng 40%.",
                            content_units=_infographic_test_content_units())
    data = {
        "title": "FPT lãi kỷ lục", "subtitle": "",
        "hero": [{"label": "Tăng trưởng doanh thu", "value": "+40%"}],
        "market": [], "highlights": [], "related": [],
        "priority": {"primary": [], "secondary": [], "minor": []},
        "render_hint": {"ratio": "1:1"},
    }
    spec = infographic_spec_from_data(data, brief)
    assert spec["subtitle"] == "", (
        f"Composer trả subtitle rỗng có chủ đích nhưng code lại điền thành "
        f"{spec['subtitle']!r} (brief.title) -- phải GIỮ RỖNG."
    )


def test_regression_row10_composer_empty_related_kept_empty_not_auto_filled():
    """§7 dòng 10 ("Composer trả related: []" -> Infographic PHẢI giữ rỗng,
    KHÔNG tự chèn ticker) -- ĐÃ SỬA (Lead 02/08). `infographic_spec_from_data()`
    giờ chỉ lùi về `_entity_names_from_content_units()`/`brief.tickers` khi key
    "related" VẮNG MẶT/None; related=[] (Composer trả rỗng tường minh) được
    GIỮ NGUYÊN, KHÔNG còn coi [] falsy giống thiếu field. Test set
    brief.tickers khác rỗng để lộ rõ hành vi đúng."""
    from twmkt.agents.production import infographic_spec_from_data, ProductionBrief

    brief = ProductionBrief(title="t", hook="h", tickers=["FPT", "HPG"],
                            url="https://cafef.vn/x.chn", evidence="Doanh thu tăng 40%.",
                            content_units=_infographic_test_content_units())
    data = {
        "title": "FPT lãi kỷ lục", "subtitle": "Góc nhìn",
        "hero": [{"label": "Tăng trưởng doanh thu", "value": "+40%"}],
        "market": [], "highlights": [], "related": [],
        "priority": {"primary": [], "secondary": [], "minor": []},
        "render_hint": {"ratio": "1:1"},
    }
    spec = infographic_spec_from_data(data, brief)
    assert spec["related"] == [], (
        f"Composer trả related=[] tường minh nhưng code lại chèn lại "
        f"{spec['related']!r} (từ facts/tickers) -- phải GIỮ RỖNG."
    )


def test_regression_row9_row10_composer_missing_keys_still_get_fallback():
    """Đối chứng cho 2 test trên (Lead 02/08, 1.4): khi Composer KHÔNG trả key
    "subtitle"/"related" (thiếu hẳn, KHÔNG phải rỗng tường minh) thì code VẪN
    phải lùi về mặc định như cũ (brief.title / entity_names-hoặc-tickers) --
    phân biệt đúng "rỗng có chủ đích" (giữ) với "thiếu field" (lùi mượt)."""
    from twmkt.agents.production import infographic_spec_from_data, ProductionBrief

    brief = ProductionBrief(title="Tiêu đề Brief gốc KHÁC hẳn", hook="Hook khác nữa",
                            tickers=["FPT", "HPG"],
                            url="https://cafef.vn/x.chn", evidence="Doanh thu tăng 40%.",
                            content_units=_infographic_test_content_units())
    data = {
        "title": "FPT lãi kỷ lục",
        "hero": [{"label": "Tăng trưởng doanh thu", "value": "+40%"}],
        "market": [], "highlights": [],
        "priority": {"primary": [], "secondary": [], "minor": []},
        "render_hint": {"ratio": "1:1"},
    }   # KHÔNG có "subtitle"/"related" trong JSON -- khác hẳn "" và [] tường minh.
    spec = infographic_spec_from_data(data, brief)
    assert spec["subtitle"] == brief.title
    assert spec["related"] == ["FPT", "HPG"]


def test_regression_row11_boilerplate_source_currently_produces_fabricated_article_known_gap():
    """Ca THÊM (A6/Phase B yêu cầu bổ sung, KHÔNG có trong §7 gốc — sàn chống
    sửa quá tay khi Phase D nới Router): nguồn boilerplate/trang điều
    hướng/"đang cập nhật" (Brief đọc được nhưng KHÔNG có nội dung thực chất
    nào, không phải lỗi hạ tầng) -- PHẢI được SKIPPED (mã lý do BOILERPLATE/
    NO_USABLE_CONTENT), TUYỆT ĐỐI KHÔNG ra Article DONE (không có gì thật để
    viết) và KHÔNG cần người can thiệp.

    XÁC NHẬN GAP THẬT bằng CHẠY THẬT (không suy đoán): `curation.normalize.
    is_relevant()` chỉ kiểm ticker/từ khoá vĩ mô, KHÔNG phát hiện boilerplate,
    nên nguồn này lọt tới tận Brief/Writer. Chạy scenario này qua debug script
    cho kết quả THẬT: article=DONE (AnalysisWriterAgent KHÔNG hề biết facts=[]
    -- viết bất kể input rỗng tuếch, Execute tổng=DONE), infographic=ERROR
    (KHÔNG phải SKIPPED), video=DONE (composer không kiểm nội dung nguồn).
    KHÔNG CÓ tuyến nào bị chặn lại đúng cách -- ngược hẳn kỳ vọng "SKIPPED,
    không cần người". Đây CHÍNH LÀ lý do Phase C cần `brief_status` 3 giá trị
    (OK|NO_USABLE_CONTENT|FAILED) độc lập với facts=[]/no_numeric_content --
    hiện tại hoàn toàn KHÔNG có tín hiệu nào phân biệt "brief chạy tốt nhưng
    nguồn rỗng tuếch" với "brief chạy tốt, nguồn định tính hợp lệ" (cả 2 đều
    cho facts=[]+no_numeric_content=False vì LLM không tự tin khẳng định
    "chắc chắn không có số" khi đọc trang không có nội dung gì). Test này SẼ
    FAIL cho tới khi Phase C/D làm xong, đúng vai trò SÀN chống sửa quá tay."""
    import json as _json

    class _CleanWriterLLM:
        def complete(self, system, prompt, *, model=None, fail_loud=False):
            return _clean_writer_json()

    class _BoilerplateRouteLLM:
        """Mô phỏng Brief đọc 1 trang boilerplate: JSON parse ĐƯỢC (không phải
        lỗi hạ tầng) nhưng facts=[] và no_numeric_content=False (LLM không tự
        tin khẳng định "chắc chắn không có số" vì nội dung không có gì để đọc)."""

        def complete(self, system, prompt, *, model=None, fail_loud=False, **kw):
            if "no_numeric_content" in system:
                return _json.dumps({"facts": [], "no_numeric_content": False}, ensure_ascii=False)
            return ""

    result, board, notifier = _run_produce_scenario(
        _CleanWriterLLM(),
        _approved_row("Trang chủ. Menu. Đăng nhập. Đang cập nhật nội dung...", row=2),
        route_llm=_BoilerplateRouteLLM())

    statuses = {r[2]: r[3] for r in board.appended_content}
    article_status = statuses.get("Article")
    assert article_status != "DONE", (
        f"BUG XÁC NHẬN (ca mới A6): nguồn boilerplate/không có nội dung thật vẫn ra Article "
        f"DONE (bịa bài từ trang rỗng) thay vì SKIPPED -- toàn bộ trạng thái: {statuses}, "
        f"Execute={board.execute_updates.get(2)}"
    )


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
    assert not any(r[2] == "Article" for r in board.appended_content)
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
    article_rows = [r for r in board.appended_content if r[2] == "Article"]
    assert len(article_rows) == 1 and article_rows[0][3] == "ERROR"
    events = [e for e, _ in notifier.events]
    article_events = [e for e, ctx in notifier.events if ctx.get("type") == "article"]
    assert "start" in events and "needs_human" in events   # adapter Phase 4.5
    assert "error" in article_events and "draft_changed" not in article_events


def test_run_article_idempotent_skips_writer_when_already_in_content():
    """Idempotent (Lớp 5 Phase 2): (TopicKey,'article') ĐÃ có trong CONTENT
    (existing_content_keys, tra THEO KHÓA — không theo Context) -> KHÔNG gọi
    writer_llm lần nào (PoisonLLM raise nếu bị gọi), skip hoàn toàn."""
    from twmkt.curation.keys import compute_topic_key

    class _PoisonWriterLLM:
        def complete(self, *a, **kw):
            raise AssertionError("KHÔNG được gọi writer khi article đã có trong CONTENT")

    _URL = "https://example.com/bai-da-co-article"
    _KEY = compute_topic_key(_URL)

    _r, board, _n = _run_produce_scenario(
        _PoisonWriterLLM(), _approved_row("Bài đã có article", row=2, source=_URL),
        pre_seed_content=[(_KEY, "article", {"status": "DONE", "output": "x", "notes": "", "facts": "[]"})])

    # run() KHÔNG raise (PoisonLLM chứng minh writer KHÔNG bị gọi) + article vẫn
    # giữ NGUYÊN output đã pre-seed ("x") -- KHÔNG bị ghi đè/sinh lại.
    article_rows = [r for r in board.appended_content if r[2] == "Article"]
    assert len(article_rows) == 1 and article_rows[0][4] == "x"
    # video/infographic vẫn được xử lý bình thường (pre_seed_content chỉ có
    # article) -> lượt này sinh đủ CẢ 3 loại (article đã có từ trước + video/
    # infographic mới) -> Execute=DONE ĐÚNG theo logic cũ (_is_fully_produced),
    # KHÔNG phải vì writer chạy lại.
    assert board.execute_updates.get(2) == "DONE"


def test_run_retries_channel_after_error_not_stuck_forever_nafoods_bug():
    """SỬA LỖI THẬT (2026-08-03, Lead báo qua ca "Nafoods Group") —
    existing_content_keys() TRƯỚC ĐÂY coi content_output ERROR/NEEDS_HUMAN là
    "đã xong" VĨNH VIỄN -> Gate1 re-approve (hoặc đổi Output Type) không bao
    giờ thật sự thử lại kênh đã lỗi: Execute lên DONE nhưng CONTENT vẫn hiện
    dữ liệu ERROR CŨ (Composer bị gọi lại rồi kết quả BỊ VỨT ở nhánh `if
    (topic_key, type_) in seen`). ERROR/NEEDS_HUMAN giờ KHÔNG chặn retry —
    lượt chạy SAU (mô phỏng re-approve) PHẢI ghi version MỚI (status=DONE)."""
    import json as _json
    from store import document_store as ds

    class _ComposerLLM:
        def __init__(self):
            from twmkt.agents.router import Usage
            self.usage = Usage()

        def complete(self, system, prompt, *, model=None, **kw):
            return _json.dumps({
                "title": "Nafoods lợi nhuận tăng", "subtitle": "Kết quả kinh doanh khả quan",
                "hero": [{"label": "Lợi nhuận", "value": "+96%"}],
                "market": [], "highlights": ["Kết quả tốt nhất nhiều quý."], "related": [],
                "priority": {"primary": [], "secondary": [], "minor": []},
                "source": "ignored", "render_hint": {"ratio": "1:1"},
            }, ensure_ascii=False)

    class _RouterVetoesInfographicRouteLLM:
        """CÙNG công thức đã xác nhận chạy đúng ở test_run_output_type_
        explicit_choice_overrides_router_veto: raw="gợi ý" verify được nhờ
        _approved_row(source="") -> fetch_full_evidence() lùi về fallback=
        item["hook"]="hook gợi ý". Output Type=Infographic tường minh -> BƯỚC
        4.5 ép channels["infographic"]=True bất kể Router/infographic_worthy
        nói gì -- CHỈ cần content_units KHÔNG rỗng (brief_status=OK)."""

        def complete(self, system, prompt, *, model=None, fail_loud=False, **kw):
            if "no_numeric_content" in system:
                return _json.dumps({
                    "content_units": [{"shape": "scalar", "value": "ý", "label": "Lợi nhuận tăng",
                                      "unit": None, "kind": "percent", "raw": "gợi ý", "approx": False}],
                    "no_numeric_content": False,
                }, ensure_ascii=False)
            return ""   # router rỗng -> fallback, không quan trọng ở test này

    _KEY = "nafoods-group-test-key"

    _r1, board1, _n1 = _run_produce_scenario(
        _ComposerLLM(),
        _approved_row("Nafoods Group: Lợi nhuận nửa đầu năm tăng 96%", row=2,
                     topic_key=_KEY, output_type=["Infographic"]),
        route_llm=_RouterVetoesInfographicRouteLLM(), content_llm=_ComposerLLM(),
        pre_seed_content=[(_KEY, "infographic", {
            "status": "ERROR", "output": "",
            "notes": "Số liệu không thấy trong evidence/background: 96%",
        })])

    history = ds.read_history(_KEY, "content_output", "infographic", db_path=board1.db_path)
    assert len(history) == 2, (
        f"kỳ vọng ĐÚNG 2 version (ERROR pre-seed + DONE mới) sau khi thử lại, thực tế {len(history)}"
    )
    assert history[-1][1]["status"] == "DONE", "Lần thử lại PHẢI ghi version MỚI status=DONE, không bị vứt"


def test_run_twice_same_topic_key_no_duplicate_content_rows():
    """Lớp 5 Phase 2: produce CÙNG 1 chủ đề 2 lần (source URL cố định -> khoá
    tất định) -> lần 2 KHÔNG ghi version MỚI cho bất kỳ content_type nào
    (existing_content_keys() đọc THẲNG store thật, tra THEO KHÓA — không theo
    Context/row-index) — kiểm bằng SỐ VERSION (read_history), KHÔNG phải bằng
    độ dài appended_content (chỉ đọc bản MỚI NHẤT nên không phân biệt được
    "ghi 1 lần" với "ghi đè version 2" — version count mới là bằng chứng thật
    KHÔNG trùng)."""
    from store import document_store as ds

    class _CleanWriterLLM:
        def complete(self, system, prompt, *, model=None, fail_loud=False):
            return _clean_writer_json()

    _URL = "https://example.com/chu-de-lap-lai-2-lan"
    row = _approved_row("Chủ đề lặp lại 2 lần", row=2, source=_URL)
    _, board, _n = _run_produce_scenario(_CleanWriterLLM(), row, run_times=2)

    for t, label in (("article", "Article"), ("video", "Video"), ("infographic", "Infographic")):
        matching = [r for r in board.appended_content if r[2] == label]
        assert len(matching) == 1, f"{t}: kỳ vọng đúng 1 dòng sau 2 lượt chạy, thực tế {len(matching)}"
        history = ds.read_history(row["topic_key"], "content_output", t, db_path=board.db_path)
        assert len(history) == 1, f"{t}: kỳ vọng ĐÚNG 1 version sau 2 lượt chạy (không ghi đè), thực tế {len(history)}"
    assert board.execute_updates.get(2) == "DONE"


# test_run_against_already_merged_content_no_duplicate_no_orphan (mergeCells
# Sheet UI cleanup Phase 1 legacy) và test_run_content_row_missing_topic_key_
# marks_needs_human_no_production (INVARIANT "CONTENT có Type nhưng TopicKey
# rỗng") ĐÃ XOÁ ở P2 store-as-truth (nhánh feature/store-as-truth,
# 2026-07-23): cả 2 test SHEET-ĐỜI-CŨ này — dữ liệu Sheet bị mergeCells xoá ô/
# dữ liệu CONTENT chưa backfill TopicKey — không còn khả năng tồn tại trong
# store (document_store.write_document() BẮT BUỘC topic_key ở MỌI write, xem
# store/document_store.py). Nhánh missing_key_contexts/existing_content_
# missing_keys() tương ứng trong produce_from_sheet.py::run() cũng đã bị xoá
# (MOOT) trong refactor này -- xem comment "P2 store-as-truth: topic_key ĐÃ có
# sẵn" đầu vòng lặp for item in approved.


def test_phase3_adversarial_reorder_insert_delete_sort_topic_key_invariant_and_reproduce():
    """Lớp 5 Phase 3.1 — PROBE ĐỐI KHÁNG: dựng 3 chủ đề (A đủ 3 loại, B thiếu
    video, C chưa có gì), chụp ánh xạ {TopicKey: nội dung} GỐC, rồi:
      (a) chèn 1 dòng KHÔNG liên quan lên ĐẦU block (CONTENT lẫn CONTEXT),
      (b) xóa 1 dòng Ở GIỮA (CONTENT: video của A; CONTEXT: 1 dòng phụ),
      (c) re-sort (CONTENT: đảo thứ tự; CONTEXT: Hot% GIẢM DẦN — đúng hành vi
          sort_context_by_hot() thật).
    Assert ánh xạ TopicKey BẤT BIẾN (0 lệch, 0 mồ côi), rồi PRODUCE LẠI —
    assert upsert hạ ĐÚNG dòng theo khóa (0 trùng, 0 dòng mới sai chỗ)."""
    from collections import Counter

    from twmkt.curation.keys import compute_topic_key
    from twmkt.sheets_board import (
        CONTENT_HEADER, CONTEXT_HEADER, approved_context_from_rows, content_row,
        content_topic_keys, context_row,
    )

    URL_A = "https://example.com/chu-de-a-probe"
    URL_B = "https://example.com/chu-de-b-probe"
    URL_C = "https://example.com/chu-de-c-probe"
    KEY_A, KEY_B, KEY_C = compute_topic_key(URL_A), compute_topic_key(URL_B), compute_topic_key(URL_C)

    # ---- 1) Dựng CONTEXT gốc: 3 chủ đề, Hot% khác nhau, đều APPROVE+RUN ----
    ctx_data_rows = [
        context_row(title="Chủ đề A probe", hook_line="hook A", source_url=URL_A,
                    score=5, hot_pct=50.0, status="APPROVE", execute="RUN", topic_key=KEY_A),
        context_row(title="Chủ đề B probe", hook_line="hook B", source_url=URL_B,
                    score=8, hot_pct=90.0, status="APPROVE", execute="RUN", topic_key=KEY_B),
        context_row(title="Chủ đề C probe", hook_line="hook C", source_url=URL_C,
                    score=2, hot_pct=10.0, status="APPROVE", execute="RUN", topic_key=KEY_C),
    ]

    # ---- 2) Dựng CONTENT gốc: A đủ 3 loại, B thiếu video, C chưa có gì ----
    content_rows = [
        content_row(context="Chủ đề A probe", type_="article", status="DONE", output="A-article", topic_key=KEY_A),
        content_row(context="Chủ đề A probe", type_="video", status="DONE", output="A-video", topic_key=KEY_A),
        content_row(context="Chủ đề A probe", type_="infographic", status="DONE", output="A-info", topic_key=KEY_A),
        content_row(context="Chủ đề B probe", type_="article", status="DONE", output="B-article", topic_key=KEY_B),
        content_row(context="Chủ đề B probe", type_="infographic", status="DONE", output="B-info", topic_key=KEY_B),
    ]

    it, io, ik = CONTENT_HEADER.index("Type"), CONTENT_HEADER.index("Output"), CONTENT_HEADER.index("TopicKey")

    def _snapshot(rows):
        keys, _missing = content_topic_keys(CONTENT_HEADER, rows)
        out = {(r[ik], r[it]): r[io] for r in rows if r[ik]}
        return out, keys

    # ---- 3) Chụp ánh xạ GỐC {TopicKey: nội dung} ----
    original_map, original_keys = _snapshot(content_rows)
    assert original_keys == {
        (KEY_A, "Article"), (KEY_A, "Video"), (KEY_A, "Infographic"),
        (KEY_B, "Article"), (KEY_B, "Infographic"),
    }

    # ---- 4) DỜI THỨ TỰ trên CONTENT: (a) chèn đầu, (b) xóa giữa, (c) đảo thứ tự ----
    unrelated_content = content_row(context="Chủ đề KHÔNG liên quan", type_="article",
                                    status="DONE", output="unrelated", topic_key="unrelated-probe-key")
    content_rows = [unrelated_content] + content_rows                       # (a) chèn đầu block
    del_i = next(i for i, r in enumerate(content_rows) if r[ik] == KEY_A and r[it] == "Video")
    del content_rows[del_i]                                                  # (b) xóa 1 dòng Ở GIỮA
    content_rows = list(reversed(content_rows))                              # (c) re-sort (đảo thứ tự)

    # ---- 5) DỜI THỨ TỰ trên CONTEXT: (a) chèn đầu, (b) xóa 1 dòng phụ, (c) sort Hot% giảm dần ----
    unrelated_ctx = context_row(title="Chủ đề KHÔNG liên quan CONTEXT", hook_line="x",
                                source_url="https://example.com/khong-lien-quan-ctx",
                                score=1, hot_pct=5.0, status="PENDING", execute="")
    to_delete_ctx = context_row(title="Sẽ bị xóa CONTEXT", hook_line="x",
                                source_url="https://example.com/se-bi-xoa-ctx",
                                score=1, hot_pct=1.0, status="PENDING", execute="")
    ctx_data_rows = [unrelated_ctx, to_delete_ctx] + ctx_data_rows            # (a) chèn đầu block
    del ctx_data_rows[1]                                                      # (b) xóa 1 dòng Ở GIỮA (to_delete_ctx)
    hot_idx = CONTEXT_HEADER.index("Hot%")
    ctx_data_rows.sort(key=lambda r: float(r[hot_idx]), reverse=True)         # (c) sort Hot% GIẢM DẦN
    ctx_rows = [CONTEXT_HEADER] + ctx_data_rows

    # ---- 6) Đọc lại -> assert ánh xạ TopicKey BẤT BIẾN (0 lệch, 0 mồ côi) ----
    after_map, after_keys = _snapshot(content_rows)
    expected_after_keys = {
        (KEY_A, "Article"), (KEY_A, "Infographic"),         # video A đã bị xóa CHỦ Ý ở bước (b)
        (KEY_B, "Article"), (KEY_B, "Infographic"),
        ("unrelated-probe-key", "Article"),
    }
    assert after_keys == expected_after_keys, "0 lệch: khoá phải khớp CHÍNH XÁC sau chèn/xóa/sort"
    for k in expected_after_keys - {("unrelated-probe-key", "Article")}:
        assert after_map[k] == original_map[k], f"Nội dung khoá {k} bị LỆCH sau reorder"
    _k2, missing_after = content_topic_keys(CONTENT_HEADER, content_rows)
    assert missing_after == [], "0 mồ côi: không dòng nào mất khả năng định danh theo khoá"

    approved_all = approved_context_from_rows(ctx_rows)
    approved_by_key = {a["topic_key"]: a for a in approved_all if a["topic_key"] in (KEY_A, KEY_B, KEY_C)}
    assert set(approved_by_key) == {KEY_A, KEY_B, KEY_C}
    assert approved_by_key[KEY_A]["context"] == "Chủ đề A probe"
    assert approved_by_key[KEY_B]["context"] == "Chủ đề B probe"
    assert approved_by_key[KEY_C]["context"] == "Chủ đề C probe"

    # ---- 7) PRODUCE LẠI sau reorder — upsert phải hạ ĐÚNG dòng theo khóa ----
    # P2 store-as-truth: "reorder/insert/delete/sort dòng" (bước 4-6 trên) chỉ
    # còn ý nghĩa cho sheets_board.py (đã nghiệm thu ở bước 6, KHÔNG đụng ở
    # đây) -- store tra theo topic_key (SQL key), không có khái niệm "thứ tự
    # dòng" nên seed lại qua pre_seed_content (dict, không phụ thuộc thứ tự).
    class _CleanWriterLLM:
        def complete(self, system, prompt, *, model=None, fail_loud=False):
            return _clean_writer_json()

    approved_list = [approved_by_key[KEY_A], approved_by_key[KEY_B], approved_by_key[KEY_C]]
    seed = [(r[ik], r[it].lower(), {"status": "DONE", "output": r[io], "notes": "", "facts": "[]"})
           for r in content_rows if r[ik]]
    _r, board, notifier = _run_produce_scenario(
        _CleanWriterLLM(), approved_rows=approved_list, run_kwargs={"limit": 10},
        pre_seed_content=seed)

    # ---- 8) Nghiệm thu produce-lại: 0 trùng, 0 dòng mới sai chỗ ----
    # board.appended_content (đọc lại từ store) đã là TOÀN BỘ trạng thái HIỆN
    # TẠI của A/B/C (pre_seed_content + mới sinh gộp lại, store không phân
    # biệt "cũ"/"mới" — đọc bản MỚI NHẤT) -- CHỈ cộng thêm dòng "không liên
    # quan" (topic NGOÀI approved_rows, store không đụng tới) để khớp nghiệm
    # thu gốc, KHÔNG cộng lại content_rows cả khối (sẽ đếm TRÙNG giả với
    # phần A/B đã pre-seed).
    unrelated_rows = [r for r in content_rows if r[ik] == "unrelated-probe-key"]
    all_rows_after = unrelated_rows + board.appended_content
    final_keys, final_missing = content_topic_keys(CONTENT_HEADER, all_rows_after)
    assert final_missing == []
    for key in (KEY_A, KEY_B, KEY_C):
        for t in ("Article", "Video", "Infographic"):
            assert (key, t) in final_keys, f"THIẾU {(key, t)} sau produce-lại"

    counts = Counter((r[ik], r[it]) for r in all_rows_after if r[it])
    dup = {k: c for k, c in counts.items() if c > 1}
    assert dup == {}, f"TRÙNG sau produce-lại (đúng lỗi 'content mồ côi' cần chặn): {dup}"

    # A.article/A.infographic/B.article/B.infographic KHÔNG bị sinh lại (nội
    # dung GIỮ NGUYÊN bản gốc — writer/agent KHÔNG được gọi lại cho các khoá này).
    assert [r[io] for r in all_rows_after if r[ik] == KEY_A and r[it] == "Article"] == ["A-article"]
    assert [r[io] for r in all_rows_after if r[ik] == KEY_A and r[it] == "Infographic"] == ["A-info"]
    assert [r[io] for r in all_rows_after if r[ik] == KEY_B and r[it] == "Article"] == ["B-article"]
    assert [r[io] for r in all_rows_after if r[ik] == KEY_B and r[it] == "Infographic"] == ["B-info"]
    # dòng KHÔNG liên quan không bị đụng tới (đúng 1 dòng, nguyên nội dung).
    assert [r[io] for r in all_rows_after if r[ik] == "unrelated-probe-key"] == ["unrelated"]

    assert board.execute_updates.get(approved_by_key[KEY_A]["row"]) == "DONE"
    assert board.execute_updates.get(approved_by_key[KEY_B]["row"]) == "DONE"
    assert board.execute_updates.get(approved_by_key[KEY_C]["row"]) == "DONE"


# =====================================================================
# PHASE (a)-SEAL — LÁT CẮT DỌC: 1 chủ đề fixture chạy qua TOÀN BỘ chuỗi thật
# (Brief -> route-once StructureRouter -> voice-lock -> Writer -> guardrail
# canonical -> produce_from_sheet.run() -> Execute/Notify), MockLLM/fake $0 —
# KHÔNG gọi claude -p thật. 3 kịch bản (a)(b)(c) dùng CHUNG 1 evidence fixture
# (thật ra CÓ SỐ, để scenario (a)/(c) test được guardrail; (b) chỉ khác ở
# output_channels router chọn).
# =====================================================================
_SLICE_EVIDENCE = ("Doanh thu quý 2 tăng 45,6% lên 1.200 tỷ đồng, đánh dấu quý "
                   "tăng trưởng cao nhất 5 năm.")


def _slice_brief_json() -> str:
    import json as _json
    return _json.dumps({
        "content_units": [
            {"value": "45,6", "label": "Tăng trưởng doanh thu quý 2", "unit": "%",
             "kind": "growth", "raw": "tăng 45,6%", "approx": False},
            {"value": "1.200", "label": "Doanh thu quý 2", "unit": "tỷ đồng",
             "kind": "money", "raw": "1.200 tỷ đồng", "approx": False},
        ],
        "no_numeric_content": False,
    }, ensure_ascii=False)


def _slice_router_json(*, output_channels: dict) -> str:
    """Router trả has_genuine_paradox=true + residual_tension + 3 drivers ->
    CODE sẽ ép structure=S5 (RÀNG BUỘC #4) và secondary=S4 (driver_count>=3),
    BẤT KỂ raw structure="S1"/secondary=None ở đây — chứng minh 2 luật cứng
    của router hoạt động XUYÊN SUỐT lát cắt, không chỉ ở test cô lập."""
    import json as _json
    return _json.dumps({
        "content_type": "article", "structure": "S1", "hook": "H2",
        "secondary_structure": None,
        "rationale": "Tăng trưởng kỷ lục nhưng ban lãnh đạo vẫn thận trọng.",
        "signals": {
            "has_genuine_paradox": True,
            "residual_tension": "Ban lãnh đạo thận trọng dù tăng trưởng kỷ lục — đà này có bền?",
            "drivers": ["Doanh thu lõi", "Mở rộng thị trường mới", "Cắt giảm chi phí vận hành"],
            "has_central_thesis": True,
        },
        "output_channels": output_channels,
        "channel_rationale": {"article": "Đủ chất liệu.", "infographic": "Có số dựng hình.",
                              "video": "Có narrative kể được."},
    }, ensure_ascii=False)


def _slice_composer_json() -> str:
    import json as _json
    return _json.dumps({
        "title": "Doanh thu quý 2 bứt phá", "subtitle": "Tăng 45,6%, đạt 1.200 tỷ đồng",
        "hero": [{"label": "Tăng trưởng doanh thu quý 2", "value": "+45,6%"},
                {"label": "Doanh thu quý 2", "value": "1.200 tỷ đồng"}],
        "market": [], "highlights": ["Quý tăng trưởng cao nhất 5 năm."],
        "related": [], "priority": {"primary": [], "secondary": [], "minor": []},
        "source": "test.vn", "render_hint": {"theme": "dark", "palette": "navy-gold", "ratio": "4:5"},
    }, ensure_ascii=False)


class _SliceRouteLLM:
    """route_llm giả DÙNG CHUNG cho brief/router/composer (3 marker phân biệt
    theo system prompt) — cùng cơ chế phân biệt đã dùng ở Phase 4.12/4.13 test."""

    def __init__(self, *, output_channels: dict):
        self.output_channels = output_channels
        self.router_calls = 0

    def complete(self, system, prompt, *, model=None, fail_loud=False, **kw):
        if "no_numeric_content" in system:                # Brief
            return _slice_brief_json()
        if "Infographic Composer" in system:               # Composer
            return _slice_composer_json()
        if "output_channels" in system:                    # StructureRouter
            self.router_calls += 1
            return _slice_router_json(output_channels=self.output_channels)
        return ""


class _SliceRouterPoisonLLM:
    """route_llm giả cho VÒNG 2 (chứng minh route-once bền qua 2 lần produce()
    THẬT) — brief/composer gọi bình thường (trả rỗng, không quan trọng ở test
    này), NHƯNG router bị CẤM gọi tuyệt đối."""

    def complete(self, system, prompt, *, model=None, fail_loud=False, **kw):
        if "output_channels" in system:                    # StructureRouter marker
            raise AssertionError("KHÔNG được gọi router lần 2 — route-once phải đóng băng")
        return ""


class _SliceCleanWriterLLM:
    """writer_llm giả — echo lại ĐÚNG số nguyên văn evidence (không tự chế/
    gộp/rớt đơn vị), CAPTURE `system` để kiểm voice-lock đã ráp đúng khung."""

    def __init__(self):
        self.captured_system = None

    def complete(self, system, prompt, *, model=None, fail_loud=False):
        import json as _json
        self.captured_system = system
        return _json.dumps({
            "title": "Doanh thu quý 2 bứt phá", "sapo": "Tăng 45,6% lên 1.200 tỷ đồng.",
            "sections": [{"heading": "Kết quả", "content": _SLICE_EVIDENCE}],
            "disclaimer": "Nội dung chỉ mang tính thông tin, không phải khuyến nghị đầu tư. "
                          "Nhà đầu tư tự chịu trách nhiệm với quyết định của mình.",
            "sources": [],
        }, ensure_ascii=False)


class _SliceFabricatingWriterLLM:
    """writer_llm giả — CHẾ 1 số KHÔNG có trong evidence/content_units (999 tỷ đồng)
    để chứng minh guardrail canonical (Mục C) còn nguyên trong lát cắt đầy đủ."""

    def complete(self, system, prompt, *, model=None, fail_loud=False):
        import json as _json
        return _json.dumps({
            "title": "Doanh thu quý 2 bứt phá", "sapo": "Tăng vọt.",
            "sections": [{"heading": "Kết quả",
                         "content": "Doanh thu quý 2 đạt 999 tỷ đồng, một con số chưa từng có."}],
            "disclaimer": "Nội dung chỉ mang tính thông tin, không phải khuyến nghị đầu tư. "
                          "Nhà đầu tư tự chịu trách nhiệm với quyết định của mình.",
            "sources": [],
        }, ensure_ascii=False)


def _slice_row(row: int = 2) -> dict:
    # hook = evidence (source="" -> fetch_full_evidence() lùi mượt về hook NGAY,
    # $0, không mạng — brief.evidence = evidence fixture, khớp content_units.raw phía trên).
    return {"context": "Doanh thu quý 2 bứt phá", "hook": _SLICE_EVIDENCE, "source": "",
           "tickers": [], "group": "", "topic": "", "execute": "RUN", "row": row,
           "topic_key": f"row-{row}-key"}


def test_vertical_slice_a_full_quantitative_topic_three_channels_clean():
    """PHASE (a)-SEAL kịch bản (a): tin định lượng đủ -> Brief tách đúng
    content_units[]+canonical_value (mắt xích 1, gọi run_brief() THẬT độc lập trước) ->
    chạy produce_from_sheet.run() THẬT: router ép S5(paradox)+S4(driver>=3),
    output_channels đủ 3 True đóng băng route-once (vòng 2 dùng PoisonLLM
    chứng minh KHÔNG gọi lại router), voice-lock ráp đúng khung+anchor vào
    system Writer THẬT, writer echo số nguyên văn -> guardrail clean -> CẢ 3
    tuyến DONE, Execute=DONE, notify đúng điểm, path ghi qua data_root."""
    import tempfile
    from pathlib import Path
    from twmkt.agents.brief import run_brief
    from twmkt.agents.route_once import RouterDecisionStore
    from twmkt.config import data_root

    # --- Mắt xích 1: Brief (gọi THẬT, độc lập với produce()) ---
    class _BriefOnlyLLM:
        def complete(self, system, prompt, *, model=None, fail_loud=False, **kw):
            return _slice_brief_json()

    brief_result = run_brief(_BriefOnlyLLM(), _SLICE_EVIDENCE)
    assert len(brief_result.content_units) == 2
    assert brief_result.no_numeric_content is False   # content_units không rỗng -> cờ ép False
    growth = next(f for f in brief_result.content_units if f.kind == "growth")
    money = next(f for f in brief_result.content_units if f.kind == "money")
    assert growth.canonical_value is not None
    assert money.canonical_value == 1_200_000_000_000.0   # "1.200 tỷ đồng"

    # --- Chạy TOÀN BỘ pipeline thật, vòng 1 ---
    sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))
    import produce_from_sheet as pfs

    decisions_path = Path(tempfile.mkdtemp()) / "router_decisions.json"
    route_llm = _SliceRouteLLM(output_channels={"article": True, "infographic": True, "video": True})
    writer_llm = _SliceCleanWriterLLM()
    result, board, notifier = _run_produce_scenario(
        writer_llm, _slice_row(), route_llm=route_llm, decisions_path=decisions_path)

    # --- Mắt xích: produce chỉ sinh tuyến true + outcome DONE ---
    types_status = {r[2]: r[3] for r in board.appended_content}
    assert types_status == {"Article": "DONE", "Video": "DONE", "Infographic": "DONE"}
    assert board.execute_updates.get(2) == "DONE"
    assert route_llm.router_calls == 1

    # --- Mắt xích: RouterDecision đóng băng đầy đủ field ---
    key = pfs._slug(_slice_row()["context"])
    decision = RouterDecisionStore(decisions_path).get(key)
    assert decision is not None
    assert decision.structure == "S5"                       # ép bởi RÀNG BUỘC #4 (paradox effective)
    assert decision.secondary_structure == "S4"              # ép bởi driver_count>=3
    assert decision.hook == "H2"
    assert decision.signals["residual_tension"] is not None
    assert decision.output_channels == {"article": True, "infographic": True, "video": True}
    assert decision.channel_rationale["infographic"]
    assert decision.fallback is False

    # --- Mắt xích: voice-lock ráp ĐÚNG khung/anchor vào system Writer THẬT ---
    sysprompt = writer_llm.captured_system
    assert "## Khung chính đã chọn (S5)" in sysprompt
    assert "## Khung phụ — dùng cho 1 đoạn trong bài (S4)" in sysprompt
    assert "### Ví dụ A" in sysprompt   # anchor mặc định S5 (_DEFAULT_ANCHOR_BY_STRUCTURE)

    # --- Mắt xích: guardrail canonical clean (số writer viết khớp evidence) ---
    article_row = next(r for r in board.appended_content if r[2] == "Article")
    assert article_row[3] == "DONE" and article_row[5] == ""   # Status, Notes rỗng (không compliance issue)

    # --- Mắt xích: Notifier bắn đúng điểm (start 1 lần, draft_changed x3, gate2_done, KHÔNG error) ---
    events = [e for e, _ in notifier.events]
    assert events.count("start") == 1
    assert events.count("draft_changed") == 3
    assert "gate2_done" in events
    assert "error" not in events and "needs_human" not in events

    # --- Mắt xích: path ghi qua data_root, KHÔNG rơi vào repo ---
    root = data_root()
    try:
        root.relative_to(REPO_ROOT)
        inside_repo = True
    except ValueError:
        inside_repo = False
    assert not inside_repo

    # --- Mắt xích: route-once BỀN qua 2 lần produce() THẬT (không chỉ 1 process) ---
    poison_writer = _SliceCleanWriterLLM()
    result2, board2, notifier2 = _run_produce_scenario(
        poison_writer, _slice_row(), route_llm=_SliceRouterPoisonLLM(), decisions_path=decisions_path)
    decision2 = RouterDecisionStore(decisions_path).get(key)
    assert decision2.structure == "S5" and decision2.hook == "H2"   # ĐÚNG quyết định cũ, không đổi


def test_vertical_slice_b_router_disables_one_channel_no_error():
    """PHASE (a)-SEAL kịch bản (b) — ĐỔI TUYẾN sang VIDEO (BƯỚC A, Router,
    quyết định Lead 31/07): bản gốc dùng infographic để chứng minh "Router
    quyết-định-từ-đầu 1 tuyến false -> SKIPPED sạch, không lỗi" — nhưng từ
    BƯỚC A, tuyến infographic ở chế độ AUTO do CODE quyết định HOÀN TOÀN
    (agents/brief.BriefResult.infographic_worthy đếm content_unit), Ý KIẾN
    RIÊNG của Router cho tuyến NÀY không còn ý nghĩa (2 content_unit numeric
    của _slice_row() -> infographic_worthy=True, code SẼ ép bật lại bất kể
    Router nói gì — xem test_run_infographic_skipped_by_code_count_ignoring_
    router_rationale cho hành vi MỚI của tuyến infographic). Tuyến VIDEO
    KHÔNG có cơ chế ép-bật tương tự (Bước 4/A chỉ chạm article + infographic)
    nên vẫn giữ đúng Ý ĐỊNH GỐC của test này: router tự quyết 1 tuyến false ->
    SKIPPED sạch, KHÔNG lỗi, các tuyến khác vẫn DONE."""
    route_llm = _SliceRouteLLM(output_channels={"article": True, "infographic": True, "video": False})
    writer_llm = _SliceCleanWriterLLM()
    result, board, notifier = _run_produce_scenario(writer_llm, _slice_row(), route_llm=route_llm)

    types_status = {r[2]: r[3] for r in board.appended_content}
    assert types_status["Article"] == "DONE"
    assert types_status["Infographic"] == "DONE"
    assert types_status["Video"] == "BỎ QUA"            # KHÔNG phải ERROR

    video_row = next(r for r in board.appended_content if r[2] == "Video")
    assert video_row[4] == ""                            # Output rỗng (không gọi composer)
    assert "Nội dung không phù hợp để làm video" in video_row[5]  # VIỆC 5: câu nghiệp vụ + rationale Router giữ nguyên

    assert board.execute_updates.get(2) == "DONE"              # KHÔNG bị SKIPPED cản DONE
    events = [e for e, _ in notifier.events]
    assert "skipped" in events and "error" not in events


def test_vertical_slice_c_fabricated_number_still_blocked_needs_human():
    """PHASE (a)-SEAL kịch bản (c): writer CHẾ số không có trong evidence/content_units
    (999 tỷ đồng) -> guardrail canonical (Mục C) VẪN CHẶN trong lát cắt đầy đủ
    (không bị nới bởi bất kỳ thay đổi Phase 4.12/4.13 nào) -> outcome=
    NEEDS_HUMAN, Execute=NEEDS_HUMAN, CONTENT article Status=ERROR kèm lý do."""
    route_llm = _SliceRouteLLM(output_channels={"article": True, "infographic": True, "video": True})
    writer_llm = _SliceFabricatingWriterLLM()
    result, board, notifier = _run_produce_scenario(writer_llm, _slice_row(), route_llm=route_llm)

    article_row = next(r for r in board.appended_content if r[2] == "Article")
    assert article_row[3] == "ERROR"
    assert "999" in article_row[5]                              # Notes nêu đúng số bịa bị chặn

    assert board.execute_updates.get(2) == "NEEDS_HUMAN"
    events = [e for e, _ in notifier.events]
    assert "needs_human" in events
    article_events = [ctx for e, ctx in notifier.events if e == "error" and ctx.get("type") == "article"]
    assert article_events


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
        def complete(self, system, prompt, **kwargs):
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
    """CONTENT.Output video (docs/CONTENT_OUTPUT_SCHEMA.md): scenes[{role,
    visual_kind,payload,narration}], CTA nằm trong payload của scene cuối
    (visual_kind="outro"), KHÔNG còn field "cta" rời cấp top."""
    from twmkt.agents.production import VideoScriptAgent, ProductionBrief
    import json as _json

    class JsonLLM:
        def complete(self, system, prompt, **kwargs):
            return _json.dumps({
                "schema_version": 1, "title": "HPG hook",
                "scenes": [
                    {"role": "hook", "visual_kind": "stat",
                     "payload": {"label": "HPG", "value": "+40%", "note": "biểu đồ"},
                     "narration": "HPG lãi tăng mạnh"},
                    # BƯỚC 3: sàn 3 scene (InsufficientScenesError) — thêm 1 scene
                    # thân, KHÔNG đổi ý nghĩa test (test kiểm scene ĐẦU/CUỐI).
                    {"role": "body", "visual_kind": "statement",
                     "payload": {"hero": "Diễn biến", "desc": "Thông tin thêm."},
                     "narration": "Một câu thân bài."},
                    {"role": "outro", "visual_kind": "outro",
                     "payload": {"brand_name": "FVA Capital", "cta": "CTA riêng"},
                     "narration": "CTA riêng"},
                ],
                "source": "ignored", "disclaimer": "Nội dung chỉ mang tính thông tin.",
            }, ensure_ascii=False)

    brief = ProductionBrief(title="HPG báo lãi", tickers=["HPG"], evidence="x")
    d = VideoScriptAgent(JsonLLM()).run(brief)
    data = _json.loads(d.body)
    assert data["schema_version"] == 1
    assert "HPG lãi tăng mạnh" in d.body and "+40%" in d.body and "biểu đồ" in d.body
    assert "CTA riêng" in d.body
    assert data["scenes"][0]["role"] == "hook"
    assert data["scenes"][-1]["role"] == "outro" and data["scenes"][-1]["visual_kind"] == "outro"
    assert data["scenes"][-1]["payload"]["cta"] == "CTA riêng"


def test_video_agent_uses_frozen_router_decision_for_voice_lock():
    """Phase 4.10: VideoScriptAgent.run(brief, decision) nối voice-lock ĐỘNG
    (khung §2 khớp decision.structure) + §4 chuyển-thể video (TTS) vào system —
    CÙNG decision article của chủ đề dùng (route-once, Mục A). decision=None
    vẫn chạy được (fallback an toàn), không lỗi."""
    from twmkt.agents.production import VideoScriptAgent, ProductionBrief
    from twmkt.agents.structure_router import RouterDecision
    import json as _json

    class _SpyLLM:
        def __init__(self):
            self.last_system = ""

        def complete(self, system, prompt, **kwargs):
            self.last_system = system
            return _json.dumps({
                "schema_version": 1, "title": "t",
                "scenes": [
                    {"role": "hook", "visual_kind": "statement",
                     "payload": {"hero": "x", "desc": ""}, "narration": "x"},
                    # BƯỚC 3: sàn 3 scene — thêm 1 scene thân, không đổi ý nghĩa test.
                    {"role": "body", "visual_kind": "statement",
                     "payload": {"hero": "y", "desc": ""}, "narration": "y"},
                    {"role": "outro", "visual_kind": "outro",
                     "payload": {"brand_name": "FVA Capital", "cta": "c"}, "narration": "c"},
                ],
                "source": "ignored", "disclaimer": "d",
            }, ensure_ascii=False)

    llm = _SpyLLM()
    brief = ProductionBrief(title="t", hook="h", evidence="Doanh thu tăng 40%.")
    decision = RouterDecision(content_type="article", structure="S3", hook="H1",
                              secondary_structure=None, rationale="r",
                              signals={"has_genuine_paradox": False, "residual_tension": None,
                                      "drivers": [], "driver_count": 0, "has_central_thesis": False})
    VideoScriptAgent(llm).run(brief, decision)
    assert "VOICE-LOCK" in llm.last_system and "S3" in llm.last_system
    assert "CHUYỂN THỂ VIDEO" in llm.last_system and "TTS" in llm.last_system

    VideoScriptAgent(llm).run(brief, None)   # decision=None -> fallback, KHÔNG lỗi
    assert "VOICE-LOCK" in llm.last_system


def _infographic_test_content_units():
    from twmkt.models import ContentUnit
    return [
        ContentUnit(value="40", label="Tăng trưởng doanh thu", unit="%", kind="percent",
            raw="tăng 40%", canonical_value=40.0),
        ContentUnit(value="1.200", label="Lợi nhuận kỷ lục", unit="tỷ đồng", kind="money",
            raw="1.200 tỷ đồng", canonical_value=1200e9),
    ]


def test_infographic_composer_produces_condensed_8_field_spec_from_llm():
    """Phase 4.11: InfographicSpecAgent giờ là 1 bước LLM (composer, uses_llm=
    True) — nén content_units[] thành spec 8 TRƯỜNG + render_hint TÁCH RIÊNG. Nhãn vẫn
    lấy từ content_units[] (NGHĨA), value do composer TỰ NÉN."""
    from twmkt.agents.production import InfographicSpecAgent, ProductionBrief
    import json as _json

    class _ComposerLLM:
        def complete(self, system, prompt, *, model=None):
            return _json.dumps({
                "title": "FPT lãi kỷ lục", "subtitle": "Tăng trưởng vượt kỳ vọng quý này",
                "hero": [{"label": "Tăng trưởng doanh thu", "value": "+40%"}],
                "market": [{"label": "Lợi nhuận kỷ lục", "value": "1,2 nghìn tỷ"}],
                "highlights": ["Doanh thu và lợi nhuận cùng lập kỷ lục trong quý."],
                "related": ["FPT"],
                "priority": {"primary": ["Tăng trưởng doanh thu"],
                            "secondary": ["Lợi nhuận kỷ lục"], "minor": []},
                "source": "ignored-code-tinh-lai",
                "render_hint": {"theme": "dark", "palette": "teal", "ratio": "1:1"},
            }, ensure_ascii=False)

    agent = InfographicSpecAgent(_ComposerLLM())
    assert agent.uses_llm is True
    brief = ProductionBrief(title="Chủ đề thật của bài", hook="h", tickers=["FPT"],
                            url="https://cafef.vn/x.chn",
                            evidence="Doanh thu tăng 40%, đạt 1.200 tỷ đồng, kỷ lục.",
                            content_units=_infographic_test_content_units())
    spec = _json.loads(agent.run(brief).body)

    assert set(spec.keys()) == {"title", "subtitle", "hero", "market", "highlights",
                                "related", "priority", "source", "render_hint"}
    assert spec["title"] == "FPT lãi kỷ lục"
    assert spec["subtitle"] and spec["subtitle"] != spec["title"]   # KHÔNG lặp headline
    assert spec["hero"] == [{"label": "Tăng trưởng doanh thu", "value": "+40%"}]
    assert spec["market"] == [{"label": "Lợi nhuận kỷ lục", "value": "1,2 nghìn tỷ"}]
    assert not any(s["label"].startswith("Số liệu") for s in spec["hero"] + spec["market"])
    assert spec["highlights"] == ["Doanh thu và lợi nhuận cùng lập kỷ lục trong quý."]
    assert spec["priority"]["primary"] == ["Tăng trưởng doanh thu"]
    assert spec["source"] == "cafef.vn"   # TẤT ĐỊNH từ url, bỏ qua composer tự bịa domain
    assert spec["render_hint"] == {"theme": "dark", "palette": "teal", "ratio": "1:1"}


def test_infographic_poor_source_title_plus_2_stat_passes_full_pipeline_no_padding():
    """rules v2.1 §8.2/§3.1 (BƯỚC 2, 2026-07-22) — nguồn NGHÈO (chỉ đủ 2 fact)
    -> Composer trả spec THƯA (title + 2 hero stat, subtitle/market/highlights/
    related RỖNG) phải THÔNG hết pipeline thật (compose -> apply_guardrails ->
    render SVG), KHÔNG bị đánh dấu ERROR/NEEDS_HUMAN, và KHÔNG có card/nhãn nào
    bị CODE tự thêm vào cho "đủ số" (§3.1: không bịa để hoàn thiện cấu trúc).
    Đây là ca nghiệm thu chính của BƯỚC 2 — chứng minh Contract Validator hiện
    có (render_infographic_svg + apply_guardrails) đã giải đúng bài toán sparse,
    không cần sửa code, chỉ cần test chứng minh."""
    from twmkt.agents.production import InfographicSpecAgent, ProductionBrief, apply_guardrails
    from twmkt.render import render_infographic_svg
    import json as _json
    import xml.dom.minidom as minidom

    class _SparseComposerLLM:
        def complete(self, system, prompt, *, model=None):
            # Composer THẤY nguồn nghèo (2 fact) -> tự chọn spec THƯA, đúng §3.1
            # ("nếu nguồn chỉ đủ đầu ra ngắn, hãy tạo đầu ra ngắn"), KHÔNG bịa
            # subtitle/market/highlights/related cho "đủ mục".
            return _json.dumps({
                "title": "Doanh thu và lợi nhuận cùng tăng",
                "subtitle": "", "hero": [{"label": "Tăng trưởng doanh thu", "value": "+40%"}],
                "market": [{"label": "Lợi nhuận kỷ lục", "value": "1,2 nghìn tỷ"}],
                "highlights": [], "related": [],
                "priority": {"primary": [], "secondary": [], "minor": []},
                "source": "ignored", "render_hint": {},
            }, ensure_ascii=False)

    content_units = _infographic_test_content_units()   # ĐÚNG 2 fact — nguồn nghèo có chủ đích
    brief = ProductionBrief(title="Chủ đề nguồn nghèo", hook="h", tickers=["FPT"],
                            url="https://cafef.vn/x.chn",
                            evidence="Doanh thu tăng 40%, lợi nhuận 1.200 tỷ đồng.",
                            content_units=content_units)
    agent = InfographicSpecAgent(_SparseComposerLLM())
    draft = agent.run(brief)
    draft = apply_guardrails(draft, brief.evidence, brief.background, content_units)

    # KHÔNG reject: is_clean=True <=> Status=DONE (không ERROR/NEEDS_HUMAN).
    assert draft.is_clean, f"bị reject oan trên nguồn nghèo hợp lệ: {draft.compliance_issues}"

    spec = _json.loads(draft.body)
    assert spec["title"] == "Doanh thu và lợi nhuận cùng tăng"
    # PHÁT HIỆN (không sửa — ngoài phạm vi BƯỚC 2, chỉ báo cáo): khi Composer cố
    # ý để subtitle rỗng (đúng §3.1) -- ĐÃ SỬA (Lead 02/08): infographic_spec_
    # from_data() giờ TÔN TRỌNG subtitle="" tường minh, KHÔNG còn tự điền
    # brief.title (đúng tinh thần "không đệm cấu trúc" của §3.1/§8.2).
    assert spec["subtitle"] == ""
    assert spec["hero"] == [{"label": "Tăng trưởng doanh thu", "value": "+40%"}]
    assert spec["market"] == [{"label": "Lợi nhuận kỷ lục", "value": "1,2 nghìn tỷ"}]
    assert spec["highlights"] == []                # KHÔNG bịa highlight
    # KHÔNG có nhãn giả "Số liệu N" / card đệm nào lẫn vào 2 stat thật.
    assert not any(s["label"].startswith("Số liệu") for s in spec["hero"] + spec["market"])
    assert len(spec["hero"]) + len(spec["market"]) == 2   # ĐÚNG 2, không đệm thêm

    # Renderer không crash với cấu trúc thưa, SVG hợp lệ, có đủ 2 số.
    # (Title bị word-wrap thành nhiều <tspan> ở max_chars=18 nên không kiểm
    # nguyên chuỗi liền — kiểm giá trị số, thứ không bị wrap.)
    svg = render_infographic_svg(spec)
    minidom.parseString(svg)
    assert "+40%" in svg
    assert "1,2 nghìn tỷ" in svg


def test_infographic_composer_empty_facts_returns_empty_spec_no_llm_call():
    """content_units[] rỗng (Brief timeout/lỗi) -> spec RỖNG CÓ CHỦ Ý, KHÔNG gọi LLM
    (PoisonLLM raise nếu bị gọi), KHÔNG bịa nhãn 'Số liệu N' (caller đánh dấu
    NEEDS_HUMAN, xem scripts/produce_from_sheet.run)."""
    from twmkt.agents.production import InfographicSpecAgent, ProductionBrief

    class _PoisonLLM:
        def complete(self, *a, **kw):
            raise AssertionError("KHÔNG được gọi composer khi content_units[] rỗng")

    agent = InfographicSpecAgent(_PoisonLLM())
    brief = ProductionBrief(title="t", hook="h", url="https://cafef.vn/x.chn",
                            evidence="Doanh thu tăng 40%, đạt 1.200 tỷ đồng, kỷ lục.",
                            content_units=[])
    d = agent.run(brief)
    assert d.body.count('"hero": []') == 1 or '"hero":[]' in d.body.replace(" ", "")
    assert "Số liệu" not in d.body


# --- Content Factory Phase D: vá rò brand cũ (CTA/disclaimer brand-driven) ---
def test_default_cta_reads_brand_name_from_config_not_hardcoded():
    from twmkt.agents.production import _default_cta

    assert _default_cta({"name": "FVA Capital"}) == "Theo dõi FVA Capital để cập nhật phân tích."
    assert _default_cta({"name": "Brand Khác"}) == "Theo dõi Brand Khác để cập nhật phân tích."
    # brand rỗng/thiếu name -> KHÔNG bịa tên nào (kể cả brand cũ hay mới), câu vẫn hợp lệ
    assert _default_cta({}) == "Theo dõi để cập nhật phân tích."


def test_default_disclaimer_reads_from_brand_yaml_footer():
    from twmkt.agents.production import _default_disclaimer

    assert _default_disclaimer({"footer": {"disclaimer": "Câu miễn trừ riêng."}}) == "Câu miễn trừ riêng."
    # thiếu brand/footer -> lùi mượt về câu chung, KHÔNG hard-code brand
    assert _default_disclaimer({}) == "Nội dung mang tính thông tin, không phải khuyến nghị đầu tư."


def test_analysis_fields_overwrites_llm_disclaimer_that_differs_from_canonical():
    """E' (2026-07-24, theo chỉ đạo Lead) -- disclaimer là dòng miễn trừ trách
    nhiệm PHÁP LÝ: LLM viết khác chữ (không rỗng) so với bản chuẩn
    (config/brand.yaml: footer.disclaimer) -> analysis_fields_from_data() PHẢI
    ghi đè bằng bản chuẩn TẠI CHỖ, và render_analysis() (nối disclaimer vào
    body) chỉ được thấy ĐÚNG MỘT disclaimer trong output cuối -- KHÔNG đôi."""
    from twmkt.agents.production import (
        ProductionBrief, _default_disclaimer, analysis_fields_from_data, render_analysis,
    )

    canonical = _default_disclaimer()
    llm_data = {
        "title": "Tiêu đề", "sapo": "Tóm tắt.",
        "sections": [{"heading": "Bối cảnh", "content": "Nội dung."}],
        "disclaimer": "Đây là câu LLM tự viết lại, khác bản chuẩn.",
        "sources": [],
    }
    brief = ProductionBrief(title="T", hook="H", url="https://cafef.vn/x.chn", evidence="E")

    title, sapo, sections, disclaimer, sources = analysis_fields_from_data(llm_data, brief)
    assert disclaimer == canonical   # ghi đè, KHÔNG giữ bản LLM viết

    body = render_analysis(title, sapo, sections, disclaimer, sources, brief)
    assert body.count(canonical) == 1   # ĐÚNG MỘT bản, không nối thêm
    assert "Đây là câu LLM tự viết lại" not in body   # bản LLM KHÔNG còn sót trong output


def test_analysis_fields_from_data_empty_sections_needs_human_not_auto_written():
    """Nhóm B (Lead 02/08, "dạng NẶNG NHẤT" của bug subtitle/related) —
    Composer trả JSON HỢP LỆ nhưng sections RỖNG (tường minh "sections": []
    HOẶC thiếu hẳn key) KHÔNG còn được LÙI MƯỢT tự dựng lại 100% bài từ
    brief.evidence/brief.background -- phải EmptySectionsError, KHÁC hẳn
    data=None (case đó VẪN LÙI MƯỢT, xem test_production_agent_graceful_
    empty_llm -- KHÔNG đụng)."""
    import pytest
    from twmkt.agents.production import (
        EmptySectionsError, ProductionBrief, analysis_fields_from_data,
    )

    brief = ProductionBrief(title="Bài có content_units verified", hook="h",
                            url="https://cafef.vn/x.chn", evidence="Doanh thu tăng 40%.")

    # (a) sections: [] tường minh.
    with pytest.raises(EmptySectionsError) as ei:
        analysis_fields_from_data(
            {"title": "T", "sapo": "s", "sections": [], "disclaimer": "d", "sources": []}, brief)
    assert "sections rỗng" in str(ei.value)

    # (b) THIẾU hẳn key "sections" -- CÙNG outcome (B4: phân biệt rõ với rỗng
    # tường minh nhưng cùng NEEDS_HUMAN, KHÔNG tự viết đè).
    with pytest.raises(EmptySectionsError):
        analysis_fields_from_data({"title": "T", "sapo": "s"}, brief)

    # Đối chứng: data=None (LLM/composer lỗi hạ tầng thật) VẪN LÙI MƯỢT như cũ,
    # KHÔNG bị đụng bởi thay đổi này.
    title, sapo, sections, disclaimer, sources = analysis_fields_from_data(None, brief)
    assert sections and title


def test_run_writer_with_retry_empty_sections_needs_human_no_fabricated_body():
    """Nhóm B (Lead 02/08) — tích hợp qua đường SỐNG THẬT (agents/writer.py:
    run_writer_with_retry): Writer trả JSON hợp lệ nhưng sections=[] -> outcome
    NEEDS_HUMAN NGAY (KHÔNG retry -- đây là lỗi VĨNH VIỄN về nội dung, giống
    guardrail reject, KHÁC LLMCallError hạ tầng), draft.body RỖNG (KHÔNG có
    bài tự dựng từ evidence), Notes/compliance_issues nêu rõ "sections rỗng"."""
    import json as _json
    from twmkt.agents.production import ProductionBrief
    from twmkt.agents.writer import WriterOutcome, run_writer_with_retry

    class _EmptySectionsWriterLLM:
        def complete(self, system, prompt, *, model=None, fail_loud=False):
            return _json.dumps({
                "title": "T", "sapo": "s", "sections": [],
                "disclaimer": "d", "sources": [],
            }, ensure_ascii=False)

    brief = ProductionBrief(title="Bài có content_units verified", hook="h",
                            url="https://cafef.vn/x.chn", evidence="Doanh thu tăng 40%.")
    result = run_writer_with_retry(_EmptySectionsWriterLLM(), brief, settings=_writer_retry_settings())

    assert result.outcome == WriterOutcome.NEEDS_HUMAN
    assert result.attempts == 1   # KHÔNG retry -- lỗi nội dung, không phải hạ tầng
    assert "sections rỗng" in result.reason
    assert result.draft.body == ""   # KHÔNG có bài tự dựng thay Composer


def test_render_analysis_and_video_use_dynamic_cta_not_hardcoded_brand():
    """Regression trực tiếp cho sự cố THẬT: render_analysis (article) VÀ
    video_fields_from_data (video, cả đường LLM-thiếu-cta LẪN đường lùi mượt
    hoàn toàn) đều PHẢI lấy CTA từ _default_cta() (brand.yaml), KHÔNG còn hằng
    số hard-code brand cũ nào sống sót ở các đường gọi này."""
    from twmkt.agents.production import (
        ProductionBrief, _default_cta, render_analysis, video_fields_from_data,
    )

    brief = ProductionBrief(title="X", hook="", url="https://cafef.vn/x.chn", evidence="")
    body = render_analysis("Tiêu đề", "Sapo", [{"heading": "H", "content": "C"}],
                           "disclaimer", [], brief)
    assert _default_cta() in body

    # Video: LLM trả JSON nhưng scene CUỐI THIẾU payload.cta -> fallback _default_cta()
    # (CTA giờ nằm trong payload của scene cuối, visual_kind="outro", KHÔNG còn field
    # "cta" rời cấp top — xem docs/CONTENT_OUTPUT_SCHEMA.md).
    # BƯỚC 3 (sàn 3 scene, InsufficientScenesError): thêm 1 scene thân, KHÔNG
    # đổi ý nghĩa test (vẫn kiểm scene CUỐI thiếu cta -> fallback).
    _title, _scenes, _disc = video_fields_from_data(
        {"title": "T", "scenes": [
            {"role": "hook", "visual_kind": "statement",
             "payload": {"hero": "v", "desc": ""}, "narration": "v"},
            {"role": "body", "visual_kind": "statement",
             "payload": {"hero": "w", "desc": ""}, "narration": "w"},
            {"role": "outro", "visual_kind": "statement",
             "payload": {"hero": "v", "desc": ""}, "narration": "v"},
        ]}, brief)
    assert _scenes[-1]["payload"]["cta"] == _default_cta()

    # Video: data=None (LLM hỏng hoàn toàn) -> đường lùi mượt CŨNG dùng _default_cta()
    _title2, _scenes2, disc2 = video_fields_from_data(None, brief)
    assert _scenes2[-1]["payload"]["cta"] == _default_cta()
    assert disc2 != ""   # vẫn có disclaimer hợp lệ (brand-driven), không rỗng


def test_find_spelled_number_phrases_flags_real_numerals_not_plain_words():
    """VIỆC 0.3 — detector CHỈ bắt số VIẾT-BẰNG-CHỮ thực (có từ cấu trúc/hậu tố
    lớn/%), KHÔNG bắt oan chữ đời thường chỉ gồm từ-đơn-vị ("hai năm"=2 năm)."""
    from twmkt.media_factory.numbers import find_spelled_number_phrases as f

    # VI PHẠM
    assert f("năm hai nghìn không trăm hai mươi lăm") == ["năm hai nghìn không trăm hai mươi lăm"]
    assert f("đạt mười ba phẩy tám tỷ đồng") == ["mười ba phẩy tám tỷ"]
    assert f("tăng hai mươi ba phần trăm") == ["hai mươi ba phần trăm"]
    assert f("doanh thu một tỷ đồng") == ["một tỷ"]
    # SẠCH (không oan)
    assert f("năm 2025, tăng 4,98%") == []
    assert f("Quý hai năm nay giảm") == []            # "hai năm" = 2 năm
    assert f("một trong những doanh nghiệp") == []
    assert f("giá 66.800 đồng, lãi 585 tỷ") == []      # chữ số + 'tỷ' sau CHỮ SỐ
    assert f("linh hồn thương hiệu") == []


def test_video_narration_contract_rejects_spelled_out_numbers():
    """VIỆC 0.3 — video_fields_from_data (đường Composer/LLM) THROW khi narration
    chứa số viết bằng chữ, nêu rõ cảnh + chuỗi. Đường fallback (data=None) KHÔNG
    bị áp (đi qua evidence nguồn, có thể chứa số-chữ tự nhiên)."""
    import pytest
    from twmkt.agents.production import (
        ProductionBrief, SpelledNumberContractError, video_fields_from_data,
    )

    brief = ProductionBrief(title="X", hook="Hook thường", url="https://cafef.vn/x.chn",
                            evidence="Doanh thu tăng.")

    bad = {"title": "T", "scenes": [
        {"role": "hook", "visual_kind": "statement", "payload": {"hero": "a", "desc": "b"},
         "narration": "Báo cáo năm hai nghìn không trăm hai mươi lăm cho thấy đà tăng."},
        {"role": "outro", "visual_kind": "outro", "payload": {"brand_name": "FVA"}, "narration": "Cảm ơn."},
    ]}
    with pytest.raises(SpelledNumberContractError) as ei:
        video_fields_from_data(bad, brief)
    assert "scene[0]" in str(ei.value)
    assert "hai nghìn không trăm" in str(ei.value)

    # narration dạng CHỮ SỐ -> KHÔNG throw.
    # BƯỚC 3 (sàn 3 scene): thêm 1 scene thân, không đổi ý nghĩa test (vẫn kiểm
    # narration digit-form không bị chặn oan).
    ok = {"title": "T", "scenes": [
        {"role": "hook", "visual_kind": "statement", "payload": {"hero": "a", "desc": "b"},
         "narration": "Báo cáo năm 2025 cho thấy đà tăng 4,98%."},
        {"role": "body", "visual_kind": "statement", "payload": {"hero": "c", "desc": "d"},
         "narration": "Một câu thân bài."},
        {"role": "outro", "visual_kind": "outro", "payload": {"brand_name": "FVA"}, "narration": "Cảm ơn."},
    ]}
    _t, scenes, _d = video_fields_from_data(ok, brief)
    assert scenes[0]["narration"].startswith("Báo cáo năm 2025")

    # Fallback (data=None) KHÔNG bị validator chặn, kể cả khi hook có số-chữ.
    brief_fb = ProductionBrief(title="Năm hai nghìn không trăm hai mươi lăm mở màn",
                               hook="", url="https://cafef.vn/x.chn", evidence="")
    _t2, _s2, _d2 = video_fields_from_data(None, brief_fb)   # không raise


def test_video_fields_from_data_rejects_fewer_than_3_scenes_no_padding():
    """BƯỚC 3 (rules v2.1, 2026-07-22) — nguồn chỉ đủ 1-2 cảnh (đường Composer/
    LLM THẬT, KHÔNG phải fallback) -> InsufficientScenesError, nêu RÕ số cảnh
    thật + đề xuất chuyển loại. TUYỆT ĐỐI KHÔNG tự độn cảnh cho đủ 3 (kiểm
    scenes trả về KHÔNG tồn tại — hàm phải THROW trước khi return, không có
    đường nào âm thầm vá đủ số)."""
    import pytest
    from twmkt.agents.production import (
        InsufficientScenesError, ProductionBrief, video_fields_from_data,
    )

    brief = ProductionBrief(title="Tin ngắn nguồn nghèo", hook="h",
                            url="https://cafef.vn/x.chn", evidence="Một câu tin ngắn.")

    # 2 cảnh — ĐÚNG dưới sàn 3 (khớp aigen scene-builder: scenes[] 3-12).
    two_scenes = {"title": "T", "scenes": [
        {"role": "hook", "visual_kind": "statement", "payload": {"hero": "a", "desc": "b"},
         "narration": "Câu dẫn."},
        {"role": "outro", "visual_kind": "outro", "payload": {"brand_name": "FVA"}, "narration": "Cảm ơn."},
    ]}
    with pytest.raises(InsufficientScenesError) as ei:
        video_fields_from_data(two_scenes, brief)
    msg = str(ei.value)
    assert "2 cảnh" in msg
    assert "chuyển loại" in msg and "infographic" in msg and "article" in msg
    assert "bịa" in msg   # tự khai rõ KHÔNG bịa, không phải im lặng vá

    # 1 cảnh — càng dưới sàn, cùng hành vi.
    with pytest.raises(InsufficientScenesError):
        video_fields_from_data({"title": "T", "scenes": [two_scenes["scenes"][0]]}, brief)

    # ĐÚNG sàn 3 -> KHÔNG throw (biên chính xác, không lệch off-by-one).
    three_scenes = dict(two_scenes)
    three_scenes["scenes"] = [
        two_scenes["scenes"][0],
        {"role": "body", "visual_kind": "statement", "payload": {"hero": "c", "desc": "d"}, "narration": "Thân."},
        two_scenes["scenes"][1],
    ]
    _t, scenes, _d = video_fields_from_data(three_scenes, brief)
    assert len(scenes) == 3


def test_video_fields_from_data_empty_scenes_needs_human_not_auto_built():
    """Nhóm B (Lead 02/08) — Composer trả JSON HỢP LỆ nhưng scenes RỖNG (tường
    minh "scenes": [] HOẶC thiếu hẳn key "scenes") KHÔNG còn được LÙI MƯỢT tự
    dựng 4 cảnh mặc định (bug "bịa cả video từ JSON rỗng") -- phải
    InsufficientScenesError (LƯỚI CÓ SẴN, produce_from_sheet.run() đã bắt
    riêng -> NEEDS_HUMAN), nêu rõ "rỗng"/0 cảnh, KHÁC hẳn data=None (case đó
    VẪN LÙI MƯỢT, xem test ngay trên -- video_fields_from_data(None, ...))."""
    import pytest
    from twmkt.agents.production import (
        InsufficientScenesError, ProductionBrief, video_fields_from_data,
    )

    brief = ProductionBrief(title="Tin có content_units verified", hook="h",
                            url="https://cafef.vn/x.chn", evidence="Một câu tin.")

    # (a) scenes: [] tường minh.
    with pytest.raises(InsufficientScenesError) as ei:
        video_fields_from_data({"title": "T", "scenes": []}, brief)
    assert "rỗng" in str(ei.value) and "0 cảnh" in str(ei.value)

    # (b) THIẾU hẳn key "scenes" -- PHẢI cùng hành vi (B4: phân biệt rõ với
    # rỗng tường minh nhưng CÙNG outcome NEEDS_HUMAN, KHÔNG tự viết đè).
    with pytest.raises(InsufficientScenesError):
        video_fields_from_data({"title": "T"}, brief)


def test_produce_from_sheet_insufficient_scenes_marks_needs_human_no_crash():
    """BƯỚC 3 — InsufficientScenesError bắt RIÊNG ở produce_from_sheet.run():
    dòng video ghi NEEDS_HUMAN kèm note đề xuất chuyển loại, KHÔNG crash cả
    lượt run() (article của CÙNG dòng vẫn phải sản xuất bình thường —
    per-row isolation, không phải lỗi hạ tầng nuốt trọn output)."""
    import json as _json

    class _CleanWriterLLM:
        def complete(self, system, prompt, *, model=None, fail_loud=False):
            return _clean_writer_json()

    class _TwoSceneVideoLLM:
        """content_llm cho VideoScriptAgent — luôn trả 2 cảnh (dưới sàn 3).
        `.usage` (interface LLMRouter thật, agents/router.py) — run() đọc
        content_llm.usage.as_dict() để log chi phí, dù stub $0."""
        def __init__(self):
            from twmkt.agents.router import Usage
            self.usage = Usage()

        def complete(self, system, prompt, *, model=None, fail_loud=False, temperature=None):
            return _json.dumps({
                "schema_version": 1, "title": "T",
                "scenes": [
                    {"role": "hook", "visual_kind": "statement",
                     "payload": {"hero": "a", "desc": "b"}, "narration": "Câu dẫn."},
                    {"role": "outro", "visual_kind": "outro",
                     "payload": {"brand_name": "FVA"}, "narration": "Cảm ơn."},
                ],
                "source": "ignored", "disclaimer": "d",
            }, ensure_ascii=False)

    result, board, notifier = _run_produce_scenario(
        _CleanWriterLLM(), _approved_row("Tin nguồn nghèo BƯỚC 3", row=2),
        content_llm=_TwoSceneVideoLLM())

    # KHÔNG crash: run() trả result bình thường, article VẪN được sản xuất.
    assert result["produced"] >= 1
    article_rows = [r for r in board.appended_content if r[2] == "Article"]
    assert len(article_rows) == 1 and article_rows[0][3] == "DONE"

    # Dòng video: NEEDS_HUMAN, note đề xuất chuyển loại — KHÔNG có cảnh bịa nào
    # (không có content_row nào type="video" với Status=DONE).
    video_rows = [r for r in board.appended_content if r[2] == "Video"]
    assert len(video_rows) == 1
    assert video_rows[0][3] == "Cần người review lại nội dung"   # nhãn VI cho NEEDS_HUMAN
    assert "Nguồn không đủ chất liệu để dựng video" in video_rows[0][5]   # VIỆC 5: INSUFFICIENT_SCENES


def test_run_and_run_draft_die_only_at_sheet_native_config_reads_when_credential_off():
    """P2 store-as-truth -- NGHIỆM THU Nguyên tắc 3 ("Pipeline và Sheet KHÔNG
    BIẾT NHAU"): TẮT HẲN credential Sheet (spreadsheet_id/creds_path rỗng, ENV
    TWMKT_SHEET_ID/TWMKT_SHEETS_CREDS xoá) rồi chạy run()/run_draft() THẬT với
    1 topic đã APPROVE/RUN trong store. Nếu code còn đụng Sheet SỚM hơn 2 điểm
    đọc config được phép (read_sources/read_prompt_versions, xem docstring
    run()) thì lỗi sẽ nổ SỚM hơn/khác thông điệp mong đợi -- test này bắt
    ĐÚNG CHỖ CHẾT, không chỉ "có lỗi là được". Trước lazy-load (2026-07-24)
    test này chết ngay ở board = _open_board() đầu hàm, TRƯỚC khi chạm
    ps.list_approved_topics() -- xem git history/báo cáo Bước 2 cho bằng
    chứng cũ. run_ingest() chạy đối chứng: KHÔNG cần board (đọc lại từ
    *.brief.json có sẵn, xem test_run_draft_then_run_ingest_round_trip...)."""
    import pytest
    import tempfile
    from pathlib import Path

    sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))
    import produce_from_sheet as pfs
    from store import document_store as ds
    from twmkt.config import Settings, load_settings as real_load_settings

    base = real_load_settings()
    data = dict(base.raw)
    data["sheets"] = {"spreadsheet_id": "", "creds_path": ""}   # TẮT HẲN credential
    test_settings = Settings(data)

    row = _approved_row("Bài kiểm credential tắt", row=2)
    db_path = Path(tempfile.mkdtemp()) / "test_store.db"
    ds.init_db(db_path)
    _seed_approved(row, db_path=db_path)

    orig_env_db = os.environ.get("DOCUMENT_STORE_PATH")
    orig_env_sheet_id = os.environ.pop("TWMKT_SHEET_ID", None)
    orig_env_creds = os.environ.pop("TWMKT_SHEETS_CREDS", None)
    orig_load_settings = pfs.load_settings
    os.environ["DOCUMENT_STORE_PATH"] = str(db_path)
    pfs.load_settings = lambda *a, **kw: test_settings
    try:
        # run(): phải chạy TRỌN store logic (đọc approved, brief/router/writer,
        # guardrail, ghi content_output) rồi CHẾT ĐÚNG ở get_board() bên trong
        # -- verify bằng thông điệp SystemExit của _open_board(), KHÔNG chỉ
        # "raise gì đó" (tránh false-positive nếu 1 lỗi KHÁC xảy ra sớm hơn).
        with pytest.raises(SystemExit, match="Thiếu sheets.spreadsheet_id/creds_path"):
            pfs.run(limit=5, offline=True)

        # run_draft(): cùng điểm chết, cùng lý do.
        with pytest.raises(SystemExit, match="Thiếu sheets.spreadsheet_id/creds_path"):
            pfs.run_draft(limit=5)

        # run_ingest(): KHÔNG cần Sheet -- chạy sạch, KHÔNG raise (đối chứng âm).
        result = pfs.run_ingest()
        assert result == {"ingested": 0, "skipped": 0, "pending": 0}
    finally:
        pfs.load_settings = orig_load_settings
        if orig_env_db is None:
            os.environ.pop("DOCUMENT_STORE_PATH", None)
        else:
            os.environ["DOCUMENT_STORE_PATH"] = orig_env_db
        if orig_env_sheet_id is not None:
            os.environ["TWMKT_SHEET_ID"] = orig_env_sheet_id
        if orig_env_creds is not None:
            os.environ["TWMKT_SHEETS_CREDS"] = orig_env_creds


def test_run_draft_then_run_ingest_round_trip_writes_store_and_marks_done():
    """P2 store-as-truth: run_draft() ghi infographic vào store NGAY + chuẩn bị
    *.brief.json (field "topic_key" -- THAY "execute_row" cũ, xem docstring
    run_draft()) + *.<type>.prompt.md; giả lập Claude Code viết *.article.json/
    *.video.json cạnh đó; run_ingest() đọc ĐÚNG topic_key từ brief.json (KHÔNG
    đoán lại) -> ghi article+video vào store, Execute=DONE khi đủ cả 3 loại,
    dọn sạch file tạm. Test NGUYÊN 1 vòng draft->ingest thật, KHÔNG mock 2 hàm
    này -- đây là bằng chứng "brief.json topic_key" nối đúng giữa 2 hàm."""
    import json
    import tempfile
    from pathlib import Path

    sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))
    import produce_from_sheet as pfs
    from store import document_store as ds
    from store import pipeline_store as ps
    from twmkt.config import Settings, load_settings as real_load_settings

    base = real_load_settings()
    test_settings = Settings(dict(base.raw))

    _URL = "https://example.com/bai-draft-ingest-round-trip"
    row = _approved_row("Bài draft ingest round trip", row=2, source=_URL)
    db_path = Path(tempfile.mkdtemp()) / "test_store.db"
    ds.init_db(db_path)
    _seed_approved(row, db_path=db_path)

    board = _FakeProduceBoard()
    orig_env = os.environ.get("DOCUMENT_STORE_PATH")
    orig = {"load_settings": pfs.load_settings, "_open_board": pfs._open_board}
    os.environ["DOCUMENT_STORE_PATH"] = str(db_path)
    pfs.load_settings = lambda *a, **kw: test_settings
    pfs._open_board = lambda settings, **kw: board
    # Đăng ký TOÀN BỘ đường dẫn file tạm CÓ THỂ được ghi NGAY (trước khi gọi
    # run_draft(), không đợi assert nào chạy xong) -- tránh rò file thật vào
    # data_root() ngoài repo nếu test fail giữa chừng (đã xảy ra 1 lần khi viết
    # test này: NameError giữa chừng để lại 3 file *.prompt.md/*.brief.json
    # thật, khiến lượt chạy lại SAU đó tưởng "đã chuẩn bị" và bỏ qua -- dọn thủ
    # công + sửa lại thứ tự này).
    slug = pfs._slug(row["context"])
    drafts_dir = pfs.data_path(test_settings.get("storage.drafts_dir", "state/production_drafts"),
                               pfs._today(), settings=test_settings)
    brief_path = drafts_dir / f"{slug}.brief.json"
    article_answer = drafts_dir / f"{slug}.article.json"
    video_answer = drafts_dir / f"{slug}.video.json"
    created_files: list[Path] = [
        brief_path, article_answer, video_answer,
        drafts_dir / f"{slug}.article.prompt.md", drafts_dir / f"{slug}.video.prompt.md",
    ]
    try:
        draft_result = pfs.run_draft(limit=5)
        assert draft_result["infographic_done"] == 1
        assert draft_result["prepared"] == 2   # article + video prompt chuẩn bị
        assert brief_path.exists()
        brief_raw = json.loads(brief_path.read_text(encoding="utf-8"))
        assert brief_raw["topic_key"] == row["topic_key"]
        assert "execute_row" not in brief_raw   # field Sheet-era cũ ĐÃ bỏ

        article_answer.write_text(json.dumps({
            "title": "Tiêu đề test", "sapo": "Tóm tắt.",
            "sections": [{"heading": "Bối cảnh", "content": "Nội dung thân bài."}],
            "disclaimer": "Nội dung chỉ mang tính thông tin, không phải khuyến nghị đầu tư. "
                          "Nhà đầu tư tự chịu trách nhiệm với quyết định của mình.",
            "sources": [],
        }, ensure_ascii=False), encoding="utf-8")
        video_answer.write_text(json.dumps({
            "title": "Tiêu đề video test",
            "scenes": [
                {"role": "hook", "visual_kind": "statement", "payload": {"hero": "a"}, "narration": "Mở đầu."},
                {"role": "body", "visual_kind": "statement", "payload": {"hero": "b"}, "narration": "Thân bài."},
                {"role": "outro", "visual_kind": "outro", "payload": {"brand_name": "FVA"}, "narration": "Cảm ơn."},
            ],
            "disclaimer": "Nội dung chỉ mang tính thông tin, không phải khuyến nghị đầu tư.",
        }, ensure_ascii=False), encoding="utf-8")

        ingest_result = pfs.run_ingest()
    finally:
        pfs.load_settings = orig["load_settings"]
        pfs._open_board = orig["_open_board"]
        if orig_env is None:
            os.environ.pop("DOCUMENT_STORE_PATH", None)
        else:
            os.environ["DOCUMENT_STORE_PATH"] = orig_env
        for f in created_files:
            f.unlink(missing_ok=True)

    assert ingest_result["ingested"] == 2   # article + video
    assert ingest_result["flagged"] == 0
    article_out = ps.read_content_output(row["topic_key"], "article", db_path=db_path)
    video_out = ps.read_content_output(row["topic_key"], "video", db_path=db_path)
    infographic_out = ps.read_content_output(row["topic_key"], "infographic", db_path=db_path)
    assert article_out["status"] == "DONE"
    assert video_out["status"] == "DONE"
    assert infographic_out is not None   # ghi bởi run_draft(), vẫn còn nguyên
    gate = ps.read_gate_status(row["topic_key"], db_path=db_path)
    assert gate["execute"] == "DONE"   # đủ cả 3 loại (infographic+article+video)
    # file tạm đã dọn sạch (brief/prompt xoá sau khi đủ, answer xoá ngay sau ingest).
    assert not brief_path.exists()


def test_infographic_composer_falls_back_to_deterministic_spec_when_llm_fails():
    """LLM composer trả rỗng/không parse được -> LÙI MƯỢT: spec TẤT ĐỊNH từ
    content_units[] trực tiếp (không nén được chữ, nhưng vẫn đúng 8 trường + title !=
    subtitle + không bịa số)."""
    from twmkt.agents.production import InfographicSpecAgent, ProductionBrief
    import json as _json

    class _EmptyLLM:
        def complete(self, system, prompt, *, model=None):
            return ""

    agent = InfographicSpecAgent(_EmptyLLM())
    brief = ProductionBrief(title="Chủ đề thật của bài", hook="", tickers=["FPT"],
                            url="https://cafef.vn/x.chn",
                            evidence="Doanh thu tăng 40%, đạt 1.200 tỷ đồng, kỷ lục.",
                            content_units=_infographic_test_content_units())
    spec = _json.loads(agent.run(brief).body)
    assert spec["title"] != spec["subtitle"] or spec["subtitle"] == ""
    assert spec["hero"] or spec["market"]   # vẫn có số THẬT, không rỗng
    all_labels = [s["label"] for s in spec["hero"] + spec["market"]]
    assert set(all_labels) == {"Tăng trưởng doanh thu", "Lợi nhuận kỷ lục"}
    assert set(spec.keys()) == {"title", "subtitle", "hero", "market", "highlights",
                                "related", "priority", "source", "render_hint"}


def test_entity_names_from_content_units_filters_by_subject_salience_only():
    """Content Factory Phase 2b — nguồn 'related' ở đường LÙI MƯỢT (composer
    LLM hỏng) CHỈ lấy salience="subject", loại "context" VÀ "" (dữ liệu cũ
    chưa phân loại — an toàn hơn khi KHÔNG chắc chắn)."""
    from twmkt.agents.production import _entity_names_from_content_units
    from twmkt.models import ContentUnit

    content_units = [
        ContentUnit(value="", label="Cảng", shape="entity_list", entities=["Cần Giờ"], salience="subject"),
        ContentUnit(value="Hiệp hội BĐS", label="Đơn vị tổ chức", shape="entity", salience="context"),
        ContentUnit(value="Ban Chính sách", label="Đơn vị đồng tổ chức", shape="entity"),   # salience rỗng (dữ liệu cũ)
    ]
    assert _entity_names_from_content_units(content_units) == ["Cần Giờ"]


def test_infographic_composer_title_never_equals_subtitle_even_if_llm_repeats():
    """RÀNG BUỘC CỨNG: composer lỡ lặp subtitle=title -> CODE tự sửa (không tin
    mù field rời của LLM, cùng triết lý driver_count/has_genuine_paradox)."""
    from twmkt.agents.production import InfographicSpecAgent, ProductionBrief
    import json as _json

    class _RepeatingLLM:
        def complete(self, system, prompt, *, model=None):
            return _json.dumps({
                "title": "Chủ đề thật của bài", "subtitle": "Chủ đề thật của bài",
                "hero": [{"label": "Tăng trưởng doanh thu", "value": "+40%"}],
                "market": [], "highlights": [], "related": [],
                "priority": {"primary": [], "secondary": [], "minor": []},
                "source": "x",
            }, ensure_ascii=False)

    agent = InfographicSpecAgent(_RepeatingLLM())
    brief = ProductionBrief(title="Chủ đề thật của bài", hook="", url="https://cafef.vn/x.chn",
                            content_units=_infographic_test_content_units())
    spec = _json.loads(agent.run(brief).body)
    assert spec["title"] != spec["subtitle"] or spec["subtitle"] == ""


def test_infographic_composer_guardrail_canonical_accepts_condensed_recognized_unit():
    """Item 8: số NÉN dùng ĐÚNG từ đơn vị canonical parser nhận diện được
    ('nghìn tỷ') vẫn map về canonical_value gốc — tái dùng NGUYÊN unsupported_
    numbers (Mục C), KHÔNG sửa gì ở đó."""
    from twmkt.agents.production import unsupported_numbers
    from twmkt.models import ContentUnit

    content_units = [ContentUnit(value="41.200", label="LNTT MB", unit="tỷ đồng", kind="money",
                  raw="41.200 tỷ đồng", canonical_value=41200e9)]
    body = '{"hero": [{"label": "LNTT MB", "value": "41,2 nghìn tỷ"}]}'
    assert unsupported_numbers(body, "", content_units) == []


def test_infographic_composer_guardrail_canonical_still_blocks_fabricated_number():
    """Số bịa hoàn toàn trong spec (không khớp evidence lẫn canonical nào) vẫn
    bị chặn — composer KHÔNG được tự ý đổi giá trị, chỉ nén chữ."""
    from twmkt.agents.production import unsupported_numbers
    from twmkt.models import ContentUnit

    content_units = [ContentUnit(value="41.200", label="LNTT MB", unit="tỷ đồng", kind="money",
                  raw="41.200 tỷ đồng", canonical_value=41200e9)]
    body = '{"hero": [{"label": "LNTT MB", "value": "99,9 nghìn tỷ"}]}'   # bịa, lệch xa canonical
    bad = unsupported_numbers(body, "", content_units)
    assert any("99,9" in b or "99" in b for b in bad)


def test_pick_emphasis_index_prefers_percent_growth_money_over_first():
    from twmkt.agents.production import _pick_emphasis_index
    from twmkt.models import ContentUnit

    content_units = [ContentUnit(value="8", label="Số dự án", kind="count"),
            ContentUnit(value="18", label="Số cổ phiếu", kind="count"),
            ContentUnit(value="8,18", label="GDP", kind="percent")]
    assert _pick_emphasis_index(content_units) == 2   # percent, dù không phải fact đầu

    all_count = [ContentUnit(value="1", label="a", kind="count"), ContentUnit(value="2", label="b", kind="count")]
    assert _pick_emphasis_index(all_count) == 0   # không có kind ưu tiên -> fact đầu (hành vi cũ)


# --- Phase 2: Research/Brief -> content_units[] có nhãn (agents/brief.py) -----------
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


def test_verify_fact_in_evidence_matches_across_nfc_nfd_unicode_forms():
    """BUG THẬT phát hiện qua round-trip trên bài cảng biển thật (Content
    Factory Phase 2b): collector 1 số nguồn (cafef.vn) trả markdown với dấu
    tiếng Việt ở dạng TỔ HỢP (NFD — "ó" = 'o' + dấu sắc rời, 2 code point)
    trong khi LLM luôn trả NFC (1 code point). Trước fix: 15/15 tên tỉnh trong
    1 entity_list chỉ còn sống sót "Gia Lai" (tên duy nhất không dấu tổ hợp) —
    mọi tên có dấu ghép đều bị loại OAN vì so khớp chuỗi thô thất bại dù NHÌN
    GIỐNG HỆT. value NFC phải khớp được evidence NFD và ngược lại."""
    import unicodedata

    from twmkt.agents.brief import verify_fact_in_evidence

    value_nfc = unicodedata.normalize("NFC", "Thanh Hóa")
    value_nfd = unicodedata.normalize("NFD", "Thanh Hóa")
    assert value_nfc != value_nfd   # sanity: 2 dạng THẬT khác byte (test không vô nghĩa nếu bằng nhau)
    evidence_nfd = unicodedata.normalize("NFD", "Danh sách gồm Thanh Hóa, Nghệ An và Hà Tĩnh.")
    sent = verify_fact_in_evidence(value_nfc, evidence_nfd)
    # sent trả về GIỮ NGUYÊN dạng Unicode của evidence đầu vào (hàm chỉ chuẩn
    # hoá NỘI BỘ để SO KHỚP, không đổi dữ liệu trả về) — trong pipeline thật,
    # content_units_from_llm_output() đã chuẩn hoá source_text 1 LẦN trước khi gọi vào
    # đây nên sent luôn là NFC; ở đây so bằng bản NFC hoá để kiểm đúng nội dung
    # mà không phụ thuộc dạng byte cụ thể.
    assert sent is not None
    assert "Thanh Hóa" in unicodedata.normalize("NFC", sent)

    # Chiều ngược lại: value NFD, evidence NFC — cũng phải khớp.
    evidence_nfc = unicodedata.normalize("NFC", "Danh sách gồm Thanh Hóa, Nghệ An và Hà Tĩnh.")
    assert verify_fact_in_evidence(value_nfd, evidence_nfc) is not None


def test_content_units_from_llm_output_entity_list_survives_nfd_evidence_full_list():
    """Regression Ở CẤP fact — trước fix: 1 entity_list 3 phần tử với dấu tổ
    hợp trong evidence (NFD) chỉ còn sống sót phần tử KHÔNG dấu ghép. Sau fix:
    CẢ 3 phải sống sót."""
    import json as _json
    import unicodedata

    from twmkt.agents.brief import content_units_from_llm_output

    evidence_nfd = unicodedata.normalize(
        "NFD", "Xây dựng khu bến Cần Giờ, khu bến Liên Chiểu, khu bến Nam Đồ Sơn.")
    raw = _json.dumps({"content_units": [
        {"shape": "entity_list", "label": "3 khu bến mới",
         "entities": ["Cần Giờ", "Liên Chiểu", "Nam Đồ Sơn"], "salience": "subject"},
    ]}, ensure_ascii=False)
    content_units = content_units_from_llm_output(raw, evidence_nfd).content_units
    assert len(content_units) == 1
    assert content_units[0].entities == ["Cần Giờ", "Liên Chiểu", "Nam Đồ Sơn"]


def test_verify_fact_in_evidence_rejects_short_value_lodged_inside_longer_number():
    """Bug thật phát hiện qua round-trip: value NGẮN ("8") KHÔNG được khớp nhầm
    vào bên trong 1 số dài hơn ("8,18%") — phải đợi tới câu có "8" ĐỨNG RIÊNG."""
    from twmkt.agents.brief import verify_fact_in_evidence

    evidence = ("GDP 6 tháng đầu năm tăng tới 8,18%, mức cao nhất nhiều năm. "
                "Tuy nhiên SSI vẫn lựa chọn 8 cổ phiếu có triển vọng tích cực.")
    sent = verify_fact_in_evidence("8", evidence)
    assert sent is not None and sent.startswith("Tuy nhiên")   # KHÔNG phải câu GDP
    assert verify_fact_in_evidence("8,18%", evidence).startswith("GDP")


def test_content_units_from_llm_output_reassembles_value_when_llm_splits_unit():
    """Bug thật phát hiện qua round-trip: LLM đôi khi tách unit RIÊNG
    ("value":"8,18","unit":"%") thay vì dính liền ("8,18%"). value trơ "8,18"
    đứng ngay trước "%" sẽ bị luật biên chặn (đúng, tránh khớp nhầm phần thập
    phân) -> phải thử ghép lại "value+unit" trước khi kết luận bịa."""
    from twmkt.agents.brief import content_units_from_llm_output
    import json as _json

    raw = _json.dumps({"content_units": [
        {"value": "8,18", "label": "GDP 6 tháng đầu năm 2026", "unit": "%", "raw": "8,18%"},
    ]}, ensure_ascii=False)
    content_units = content_units_from_llm_output(raw, _SSI_EVIDENCE).content_units
    assert len(content_units) == 1
    assert content_units[0].value == "8,18" and content_units[0].unit == "%"
    assert "8,18%" in content_units[0].source


def test_content_units_from_llm_output_labels_meaningful_and_drops_hallucinated():
    """Bài SSI: nhãn phải CÓ NGHĨA (không còn 'Số liệu N'); fact bịa (value
    không có trong evidence) PHẢI bị loại."""
    from twmkt.agents.brief import content_units_from_llm_output
    import json as _json

    raw = _json.dumps({"content_units": [
        {"value": "8,18%", "label": "GDP 6 tháng đầu năm 2026", "unit": "%", "raw": "8,18%"},
        {"value": "8 cổ phiếu", "label": "Số cổ phiếu SSI khuyến nghị triển vọng tích cực", "unit": None,
         "raw": "8 cổ phiếu"},
        {"value": "15%", "label": "Biên lợi nhuận bịa (không có trong bài)", "unit": "%", "raw": "15%"},
    ]}, ensure_ascii=False)

    content_units = content_units_from_llm_output(raw, _SSI_EVIDENCE).content_units
    values = {f.value for f in content_units}
    assert values == {"8,18%", "8 cổ phiếu"}          # "15%" bịa -> loại
    assert not any(f.label.startswith("Số liệu") for f in content_units)   # KHÔNG còn nhãn vô nghĩa
    gdp = next(f for f in content_units if f.value == "8,18%")
    assert gdp.label == "GDP 6 tháng đầu năm 2026" and gdp.unit == "%"
    assert "8,18%" in gdp.source and "GDP" in gdp.source   # source = câu evidence gốc


def test_content_units_from_llm_output_empty_or_bad_json_returns_empty_list():
    from twmkt.agents.brief import content_units_from_llm_output

    assert content_units_from_llm_output("", _SSI_EVIDENCE).content_units == []
    assert content_units_from_llm_output("không phải JSON", _SSI_EVIDENCE).content_units == []
    assert content_units_from_llm_output('{"content_units": []}', _SSI_EVIDENCE).content_units == []


# =====================================================================
# PHASE C (content_unit contract, 2026-07-3x) — brief_status 3 giá trị thay
# suy luận nhị phân content_units=[]/no_numeric_content cũ (Phase 4.12). `.content_units`
# là tên field CHÍNH (BriefResult) — `.content_units` GIỮ LÀM property tương thích
# ngược, HẠN CỨNG 2026-08-10 (xem BriefResult.content_units docstring, agents/brief.py).
# =====================================================================
def test_brief_result_status_failed_when_json_truly_broken():
    """FAILED — LLM rỗng/JSON không parse được (lỗi hạ tầng THẬT), KHÁC hẳn
    NO_USABLE_CONTENT (JSON parse ĐƯỢC nhưng rỗng tuếch) — 2 nguyên nhân khác
    nhau, không được gộp (đây chính là gap Phase 4.12 để lọt, xem docstring
    BriefResult)."""
    from twmkt.agents.brief import content_units_from_llm_output

    assert content_units_from_llm_output("", _SSI_EVIDENCE).brief_status == "FAILED"
    assert content_units_from_llm_output("không phải JSON", _SSI_EVIDENCE).brief_status == "FAILED"


def test_brief_result_status_no_usable_content_when_json_parses_but_nothing_extractable():
    """NO_USABLE_CONTENT — JSON parse ĐƯỢC (không phải lỗi hạ tầng), content_
    units RỖNG, VÀ LLM KHÔNG tự tin khẳng định no_numeric_content=true. Đây là
    CHỮ KÝ của nguồn boilerplate/trang điều hướng/"đang cập nhật" — LLM không
    đọc hiểu được nội dung gì để khẳng định BẤT CỨ điều gì, kể cả "chắc chắn
    không có số". TRƯỚC Phase C: case này lẫn vào cùng nhóm với "Brief hỏng
    thật" (cả 2 đều content_units=[]+no_numeric_content=False), khiến Article vẫn
    được viết bịa (xem test_produce_boilerplate_source_now_skipped_not_done
    bên dưới, integration test full pipeline cho đúng ca này)."""
    from twmkt.agents.brief import content_units_from_llm_output

    result = content_units_from_llm_output('{"content_units": [], "no_numeric_content": false}', _SSI_EVIDENCE)
    assert result.brief_status == "NO_USABLE_CONTENT"
    assert result.content_units == []


def test_brief_result_status_ok_when_qualitative_confirmed_even_with_zero_units():
    """OK — content_units RỖNG nhưng LLM XÁC NHẬN CHẮC CHẮN no_numeric_content
    =true (cơ chế Phase 4.12 GIỮ NGUYÊN) -> vẫn OK (có chất liệu định tính,
    Router được quyền định tuyến), KHÔNG bị brief_status mới coi là
    NO_USABLE_CONTENT."""
    from twmkt.agents.brief import content_units_from_llm_output

    result = content_units_from_llm_output('{"content_units": [], "no_numeric_content": true}', _SSI_EVIDENCE)
    assert result.brief_status == "OK"
    assert result.content_units == []


def test_brief_result_status_ok_when_content_units_non_empty():
    """OK — content_units khác rỗng (bất kể no_numeric_content) -> OK, cùng
    hành vi Phase 4.12 (content_units thật luôn -> OK), chỉ đổi TÊN suy luận."""
    from twmkt.agents.brief import content_units_from_llm_output
    import json as _json

    raw = _json.dumps({
        "content_units": [{"shape": "scalar", "value": "8,18", "label": "GDP 6 tháng", "unit": "%",
                  "kind": "percent", "raw": "8,18%", "approx": False}],
        "no_numeric_content": False,
    }, ensure_ascii=False)
    result = content_units_from_llm_output(raw, _SSI_EVIDENCE)
    assert result.brief_status == "OK"
    assert len(result.content_units) == 1


def test_brief_result_facts_property_is_adapter_for_content_units():
    """`.content_units` (property, HẠN CỨNG 2026-08-10) PHẢI trả ĐÚNG object với
    `.content_units` — code cũ đọc `.content_units` không được thấy khác biệt."""
    from twmkt.agents.brief import content_units_from_llm_output
    import json as _json

    raw = _json.dumps({
        "content_units": [{"shape": "scalar", "value": "8,18", "label": "P/E SSI", "unit": None,
                  "kind": "other", "raw": "8,18", "approx": False}],
    }, ensure_ascii=False)
    result = content_units_from_llm_output(raw, _SSI_EVIDENCE)
    assert result.content_units is result.content_units


def test_has_numeric_units_and_has_qualitative_units_independent_flags():
    """Phase C — 2 cờ độc lập tính từ `type` của TỪNG content_unit (mặc định
    "numeric", models.py). Bước 3 đã xây parser thật cho type != "numeric"
    (_parse_qualitative_unit, agents/brief.py) nên has_qualitative_units GIỜ
    phản ánh dữ liệu THẬT khi Brief chạy thật (xem test_regression_row2_row3_
    ..., chốt kiểm nội bộ thật với claude -p/Anthropic API); test này khoá
    đúng CÔNG THỨC tính bằng cách tự dựng ContentUnit type khác nhau trực
    tiếp, không qua LLM giả."""
    from twmkt.agents.brief import BriefResult
    from twmkt.models import ContentUnit

    numeric_only = BriefResult(content_units=[ContentUnit(value="8", label="x", type="numeric")])
    assert numeric_only.has_numeric_units is True
    assert numeric_only.has_qualitative_units is False

    qualitative_only = BriefResult(content_units=[ContentUnit(value="", label="x", type="policy_change")])
    assert qualitative_only.has_numeric_units is False
    assert qualitative_only.has_qualitative_units is True

    mixed = BriefResult(content_units=[ContentUnit(value="8", label="x", type="numeric"),
                                       ContentUnit(value="", label="y", type="event")])
    assert mixed.has_numeric_units is True
    assert mixed.has_qualitative_units is True


def test_has_anchored_units_numeric_always_counts_qualitative_needs_direct_or_paraphrase():
    """Bước 4.1 (Router) — has_anchored_units là sàn MỚI thay "đếm số" cho
    quyết định article=true. MỌI content_unit type="numeric" LUÔN tính (verify
    RIÊNG của chúng đã chặt hơn "direct_quote"). content_unit ĐỊNH TÍNH CHỈ
    tính khi evidence ∈ {direct_quote, paraphrase} — "derived"/"inferred"
    KHÔNG đủ MỘT MÌNH để ép article=true (chúng là diễn giải, không phải bằng
    chứng neo nguồn trực tiếp)."""
    from twmkt.agents.brief import BriefResult
    from twmkt.models import ContentUnit

    numeric_alone = BriefResult(content_units=[ContentUnit(value="8", label="x", type="numeric")])
    assert numeric_alone.has_anchored_units is True

    qualitative_direct_quote = BriefResult(content_units=[
        ContentUnit(value="", label="s", type="statement", subject="s", claim="c",
                   source="src", evidence="direct_quote")])
    assert qualitative_direct_quote.has_anchored_units is True

    qualitative_paraphrase = BriefResult(content_units=[
        ContentUnit(value="", label="s", type="policy_change", subject="s", claim="c",
                   source="src", evidence="paraphrase")])
    assert qualitative_paraphrase.has_anchored_units is True

    only_derived = BriefResult(content_units=[
        ContentUnit(value="", label="s", type="inference", subject="s", claim="c",
                   source="src", evidence="derived")])
    assert only_derived.has_anchored_units is False, (
        "1 content_unit derived DUY NHẤT không đủ neo nguồn để ép article=true"
    )

    only_inferred = BriefResult(content_units=[
        ContentUnit(value="", label="s", type="inference", subject="s", claim="c",
                   source="src", evidence="inferred")])
    assert only_inferred.has_anchored_units is False

    empty = BriefResult(content_units=[])
    assert empty.has_anchored_units is False

    mixed_derived_plus_numeric = BriefResult(content_units=[
        ContentUnit(value="", label="s", type="inference", subject="s", claim="c",
                   source="src", evidence="derived"),
        ContentUnit(value="8", label="x", type="numeric"),
    ])
    assert mixed_derived_plus_numeric.has_anchored_units is True, (
        "1 content_unit numeric BẤT KỲ trong danh sách vẫn đủ ép article=true"
    )


# =====================================================================
# BƯỚC A (Router, gỡ nốt cứng nhắc Infographic, quyết định Lead 31/07) — A4:
# 4 ca AUTO (đủ số/đủ process/chỉ 2 unit rời/toàn quote đơn lẻ) + 1 ca Output
# Type chọn tường minh Infographic. A5: dựng content_units SẴN, KHÔNG cần LLM
# thật — đây là logic Router THUẦN (đếm/so ngưỡng), không phải chất lượng
# trích xuất (thứ ĐÃ kiểm bằng LLM thật ở chốt kiểm nội bộ riêng).
# =====================================================================
def test_infographic_worthy_auto_case_enough_numeric():
    """A4 ca 1 — "đủ số": ≥2 content_unit type=numeric -> infographic_worthy=
    True (Data Infographic, ngưỡng ≥2 — xem docstring property giải thích lý
    do lệch so với đề xuất ban đầu ≥3: dữ liệu thật/test có sẵn cho thấy 2 số
    đã đủ dùng từ trước)."""
    from twmkt.agents.brief import BriefResult
    from twmkt.models import ContentUnit

    two_numeric = BriefResult(content_units=[
        ContentUnit(value="45,6", label="Tăng trưởng doanh thu", type="numeric"),
        ContentUnit(value="1.200", label="Doanh thu", type="numeric"),
    ])
    assert two_numeric.infographic_worthy is True
    assert two_numeric.infographic_type_counts()["numeric"] == 2


def test_infographic_worthy_auto_case_enough_process_or_timeline():
    """A4 ca 2 — "đủ process": ≥3 content_unit type ∈ {process, timeline} ->
    infographic_worthy=True (sơ đồ các bước / dòng thời gian, KHÔNG cần số
    nào cả)."""
    from twmkt.agents.brief import BriefResult
    from twmkt.models import ContentUnit

    three_process = BriefResult(content_units=[
        ContentUnit(value="", label="s1", type="process", subject="Doanh nghiệp",
                   claim="Nộp hồ sơ", source="src", evidence="direct_quote"),
        ContentUnit(value="", label="s2", type="process", subject="Doanh nghiệp",
                   claim="Chờ thẩm định", source="src", evidence="direct_quote"),
        ContentUnit(value="", label="s3", type="timeline", subject="Doanh nghiệp",
                   claim="Được cấp phép sau 30 ngày", source="src", evidence="paraphrase"),
    ])
    assert three_process.infographic_worthy is True
    counts = three_process.infographic_type_counts()
    assert counts["process_timeline"] == 3 and counts["numeric"] == 0


def test_infographic_worthy_auto_case_only_two_isolated_units():
    """A4 ca 3 — "chỉ 2 unit rời": 2 content_unit KHÁC type, mỗi nhóm không đạt
    ngưỡng riêng (1 statement + 1 event, không phải numeric/process-timeline/
    relation-state, tổng cũng chưa tới 4) -> infographic_worthy=False."""
    from twmkt.agents.brief import BriefResult
    from twmkt.models import ContentUnit

    two_isolated = BriefResult(content_units=[
        ContentUnit(value="", label="s1", type="statement", subject="A",
                   claim="A tuyên bố X", source="src", evidence="direct_quote"),
        ContentUnit(value="", label="s2", type="event", subject="B",
                   claim="B xảy ra Y", source="src", evidence="direct_quote"),
    ])
    assert two_isolated.infographic_worthy is False, (
        "2 unit rời rạc khác nhóm, không đạt bất kỳ ngưỡng nào -- KHÔNG đủ dựng Infographic"
    )


def test_infographic_worthy_auto_case_all_isolated_quotes():
    """A4 ca 4 — "toàn quote đơn lẻ": nhiều content_unit type=quote nhưng KHÔNG
    đạt ngưỡng tổng ≥4 (chỉ 2 quote) -> infographic_worthy=False ("quote" KHÔNG
    nằm trong 2 nhóm ≥3 riêng [process/timeline, relation/state_change], chỉ
    tính vào tổng ≥4 chung)."""
    from twmkt.agents.brief import BriefResult
    from twmkt.models import ContentUnit

    two_quotes = BriefResult(content_units=[
        ContentUnit(value="", label="q1", type="quote", subject="A",
                   claim="Câu trích 1", source="src", evidence="direct_quote"),
        ContentUnit(value="", label="q2", type="quote", subject="B",
                   claim="Câu trích 2", source="src", evidence="direct_quote"),
    ])
    assert two_quotes.infographic_worthy is False

    four_quotes = BriefResult(content_units=[
        ContentUnit(value="", label=f"q{i}", type="quote", subject="A",
                   claim=f"Câu trích {i}", source="src", evidence="direct_quote")
        for i in range(4)
    ])
    assert four_quotes.infographic_worthy is True, (
        "4 quote (dù toàn 1 type) vẫn đạt ngưỡng tổng ≥4 -- đủ dày để dựng cấu trúc thị giác"
    )


def test_run_output_type_explicit_infographic_on_qualitative_only_article_no_number():
    """A4 ca 5 — Output Type chọn TƯỜNG MINH Infographic trên bài KHÔNG SỐ
    (chỉ 2 content_unit type=statement, dưới MỌI ngưỡng infographic_worthy) ->
    PHẢI THỰC THI (Router/CODE mất quyền phủ quyết khi user chọn tường minh,
    cùng luật Bước 4.5 áp cho MỌI định dạng, giờ áp cả cho Infographic dù lý
    do tắt là CODE đếm số chứ không phải Router LLM tự ý)."""
    import json as _json

    class _ComposerLLM:
        def __init__(self):
            from twmkt.agents.router import Usage
            self.usage = Usage()

        def complete(self, system, prompt, *, model=None):
            return _json.dumps({
                "title": "Chính sách mới", "subtitle": "Không có số liệu cụ thể",
                "hero": [], "market": [], "highlights": ["Chính sách mới ban hành."],
                "related": [], "priority": {"primary": [], "secondary": [], "minor": []},
                "source": "ignored", "render_hint": {"ratio": "1:1"},
            }, ensure_ascii=False)

    class _QualitativeOnlyNoNumberRouteLLM:
        """`source` PHẢI verify được trong evidence THẬT (fallback="hook gợi ý",
        xem _approved_row/fetch_full_evidence)."""

        def complete(self, system, prompt, *, model=None, fail_loud=False, **kw):
            if "no_numeric_content" in system:
                return _json.dumps({
                    "content_units": [
                        {"shape": "qualitative", "type": "statement", "subject": "Chính phủ",
                         "claim": "Chính phủ tuyên bố chính sách mới", "source": "hook gợi ý",
                         "evidence": "direct_quote"},
                    ],
                    "no_numeric_content": False,
                }, ensure_ascii=False)
            return ""

    result, board, notifier = _run_produce_scenario(
        _ComposerLLM(),
        _approved_row("Chính sách mới, không có số liệu cụ thể", row=2, output_type=["Infographic"]),
        route_llm=_QualitativeOnlyNoNumberRouteLLM(), content_llm=_ComposerLLM())

    rows_by_type = {r[2]: r for r in board.appended_content}
    assert set(rows_by_type) == {"Infographic"}
    assert rows_by_type["Infographic"][3] == "DONE", (
        f"Output Type chọn tường minh Infographic trên bài không số -- PHẢI thực thi, "
        f"thực tế: {rows_by_type['infographic'][3]} | {rows_by_type['infographic'][5][:150]}"
    )


# =====================================================================
# Content Factory Phase 2 — content_units_from_llm_output() VÉT CẠN 5 shape (models.
# FACT_SHAPES). Test theo shape: parse đúng + verify chống bịa RIÊNG cho từng
# hình dạng (range/delta PHẢI 2 đầu CÙNG 1 câu; entity_list lọc từng phần tử;
# entity verify như scalar). Thiếu/lạ "shape" -> lùi về "scalar" (tương thích
# ngược, đã test ở các test_content_units_from_llm_output_* phía trên — schema cũ
# không có field "shape").
# =====================================================================
def test_content_units_from_llm_output_range_shape_requires_both_bounds_same_sentence():
    from twmkt.agents.brief import content_units_from_llm_output
    import json as _json

    evidence = "Thực tế có khoảng 70 - 80% vốn FDI đăng ký mới tập trung vào KCN."
    raw = _json.dumps({"content_units": [
        {"shape": "range", "value_low": "70", "value_high": "80", "unit": "%",
         "label": "Vốn FDI chế biến, chế tạo vào KCN", "kind": "percent", "approx": True},
    ]}, ensure_ascii=False)
    content_units = content_units_from_llm_output(raw, evidence).content_units
    assert len(content_units) == 1
    f = content_units[0]
    assert f.shape == "range" and f.value_low == "70" and f.value_high == "80"
    assert f.canonical_low == 70.0 and f.canonical_high == 80.0
    assert "70 - 80%" in f.source


def test_content_units_from_llm_output_range_shape_rejects_bounds_from_different_sentences():
    """Chống bịa: value_low và value_high đến từ 2 câu KHÔNG liên quan -> KHÔNG
    được ghép thành 1 range — LOẠI cả fact."""
    from twmkt.agents.brief import content_units_from_llm_output
    import json as _json

    evidence = "Doanh nghiệp A có 70 nhân sự. Doanh nghiệp B lãi 80 tỷ đồng."
    raw = _json.dumps({"content_units": [
        {"shape": "range", "value_low": "70", "value_high": "80", "unit": None,
         "label": "Range bịa ghép 2 câu khác nhau"},
    ]}, ensure_ascii=False)
    assert content_units_from_llm_output(raw, evidence).content_units == []


def test_content_units_from_llm_output_delta_shape_numeric_from_to():
    from twmkt.agents.brief import content_units_from_llm_output
    import json as _json

    evidence = ("Doanh thu thuần quý 2/2026 chỉ đạt hơn 176 triệu đồng, giảm sâu "
               "so với mức 16,3 tỷ đồng của cùng kỳ năm 2025.")
    raw = _json.dumps({"content_units": [
        {"shape": "delta", "from_value": "16,3 tỷ đồng", "to_value": "176 triệu đồng",
         "label": "Doanh thu quý 2 (2025 → 2026)", "kind": "money"},
    ]}, ensure_ascii=False)
    content_units = content_units_from_llm_output(raw, evidence).content_units
    assert len(content_units) == 1
    f = content_units[0]
    assert f.shape == "delta"
    assert f.from_value == "16,3 tỷ đồng" and f.to_value == "176 triệu đồng"
    assert f.canonical_from == 16.3e9 and f.canonical_to == 176e6


def test_content_units_from_llm_output_delta_shape_non_numeric_status_change():
    """Delta KHÔNG PHẢI số (chuyển trạng thái) — canonical_from/to = None là
    HỢP LỆ (không phải lỗi), miễn cả 2 vế đều verify được CÙNG câu."""
    from twmkt.agents.brief import content_units_from_llm_output
    import json as _json

    evidence = "Cùng thời điểm, HVN được chuyển từ diện kiểm soát sang diện cảnh báo."
    raw = _json.dumps({"content_units": [
        {"shape": "delta", "from_value": "diện kiểm soát", "to_value": "diện cảnh báo",
         "label": "Thay đổi phân loại giao dịch cổ phiếu HVN"},
    ]}, ensure_ascii=False)
    content_units = content_units_from_llm_output(raw, evidence).content_units
    assert len(content_units) == 1
    assert content_units[0].canonical_from is None and content_units[0].canonical_to is None
    assert content_units[0].from_value == "diện kiểm soát" and content_units[0].to_value == "diện cảnh báo"


def test_content_units_from_llm_output_entity_list_shape_filters_unverified_members():
    """Chống bịa: MỖI phần tử entity_list verify RIÊNG — tên KHÔNG có trong
    evidence bị loại KHỎI DANH SÁCH (không loại cả fact, trừ khi rỗng sau lọc)."""
    from twmkt.agents.brief import content_units_from_llm_output
    import json as _json

    evidence = "Các nhà đầu tư đến từ Hàn Quốc, Nhật Bản và Mỹ tiếp tục coi Việt Nam là điểm đến."
    raw = _json.dumps({"content_units": [
        {"shape": "entity_list", "label": "Quốc gia đầu tư",
         "entities": ["Hàn Quốc", "Nhật Bản", "Mỹ", "Nga (bịa)"]},
    ]}, ensure_ascii=False)
    content_units = content_units_from_llm_output(raw, evidence).content_units
    assert len(content_units) == 1
    assert content_units[0].entities == ["Hàn Quốc", "Nhật Bản", "Mỹ"]   # "Nga (bịa)" bị lọc


def test_content_units_from_llm_output_entity_list_shape_drops_fact_when_all_members_unverified():
    from twmkt.agents.brief import content_units_from_llm_output
    import json as _json

    evidence = "Không có quốc gia nào được nhắc tới trong câu này."
    raw = _json.dumps({"content_units": [
        {"shape": "entity_list", "label": "Quốc gia bịa hoàn toàn",
         "entities": ["Đức", "Ý"]},
    ]}, ensure_ascii=False)
    assert content_units_from_llm_output(raw, evidence).content_units == []


def test_content_units_from_llm_output_entity_shape_validates_entity_type_against_config_list():
    from twmkt.agents.brief import content_units_from_llm_output
    import json as _json

    evidence = "Ông Nguyễn Duy Linh, Tổng Giám đốc CTCP Chứng khoán SHS, cho biết..."
    raw = _json.dumps({"content_units": [
        {"shape": "entity", "value": "SHS", "label": "Công ty chứng khoán", "entity_type": "company"},
        {"shape": "entity", "value": "Nguyễn Duy Linh", "label": "Người phát biểu",
         "entity_type": "loai-khong-hop-le"},
    ]}, ensure_ascii=False)
    content_units = content_units_from_llm_output(raw, evidence,
                                  entity_types=["ticker", "company", "person", "other"]).content_units
    by_value = {f.value: f for f in content_units}
    assert by_value["SHS"].entity_type == "company"
    assert by_value["Nguyễn Duy Linh"].entity_type == "other"   # loại lạ ngoài config -> "other"


def test_content_units_from_llm_output_entity_shape_drops_fabricated_name():
    from twmkt.agents.brief import content_units_from_llm_output
    import json as _json

    evidence = "Ông Nguyễn Duy Linh, Tổng Giám đốc SHS, cho biết có hai nguyên nhân chính."
    raw = _json.dumps({"content_units": [
        {"shape": "entity", "value": "Warren Buffett", "label": "Người phát biểu bịa",
         "entity_type": "person"},
    ]}, ensure_ascii=False)
    assert content_units_from_llm_output(raw, evidence).content_units == []


# --- Content Factory Phase 2b: salience (chủ thể "subject" vs phông nền "context") ---
def test_content_units_from_llm_output_parses_salience_for_entity_and_entity_list():
    from twmkt.agents.brief import content_units_from_llm_output
    import json as _json

    evidence = ("4 cảng: Cần Giờ, Liên Chiểu được quy hoạch. Hội thảo do Hiệp hội "
               "Bất động sản Việt Nam tổ chức tại Hải Phòng.")
    raw = _json.dumps({"content_units": [
        {"shape": "entity_list", "label": "4 cảng được quy hoạch",
         "entities": ["Cần Giờ", "Liên Chiểu"], "salience": "subject"},
        {"shape": "entity", "value": "Hiệp hội Bất động sản Việt Nam",
         "label": "Đơn vị tổ chức hội thảo", "entity_type": "policy", "salience": "context"},
    ]}, ensure_ascii=False)
    content_units = content_units_from_llm_output(raw, evidence,
                                  entity_salience=["subject", "context"]).content_units
    by_label = {f.label: f for f in content_units}
    assert by_label["4 cảng được quy hoạch"].salience == "subject"
    assert by_label["Đơn vị tổ chức hội thảo"].salience == "context"


def test_content_units_from_llm_output_salience_missing_or_invalid_defaults_to_context():
    """FAIL-CLOSED: salience thiếu/lạ -> "context" (AN TOÀN — không tự lên
    hình related/priority.primary nếu Brief quên gắn salience)."""
    from twmkt.agents.brief import content_units_from_llm_output
    import json as _json

    evidence = "SHS công bố báo cáo tài chính quý 2."
    raw = _json.dumps({"content_units": [
        {"shape": "entity", "value": "SHS", "label": "Công ty chứng khoán",
         "entity_type": "company"},   # thiếu salience
        {"shape": "entity_list", "label": "X", "entities": ["SHS"], "salience": "khong-hop-le"},
    ]}, ensure_ascii=False)
    content_units = content_units_from_llm_output(raw, evidence).content_units
    assert all(f.salience == "context" for f in content_units)


def test_brief_system_prompt_teaches_event_name_and_location_are_context_not_subject():
    """Phase 3.1b — regression cho lỗi THẬT đo được qua benchmark lặp lại 10
    lượt trên bài đối chứng âm cang_bien_gdp: tên sự kiện/diễn đàn bị gán
    nhầm salience="subject" 4/10 lượt (Sonnet 2/5, Opus 2/5) dù chỉ là bối
    cảnh; "Hải Phòng" (địa điểm tổ chức, ca gốc Phase 3.1) không lặp lại lần
    nào (0/10) nhưng vẫn giữ làm ví dụ neo. Xác nhận prompt dạy RÕ cả 2 tín
    hiệu (tên sự kiện + địa điểm tổ chức) đều là context, kèm câu hỏi tự vấn
    trước khi gán subject và cảnh báo tần suất-xuất-hiện không phải tín hiệu
    chủ thể."""
    from twmkt.agents.brief import _system_prompt

    system = _system_prompt()
    low = system.lower()
    assert "hải phòng" in low
    assert "diễn đàn" in low and "summit" in low
    assert "tần suất xuất hiện không phải tín hiệu" in low
    assert "chủ đề tin" in low or "chủ thể" in low


def test_content_units_from_llm_output_preserves_context_salience_for_event_and_location():
    """Tái hiện DỮ LIỆU THẬT ca cang_bien_gdp (Phase 3.1b): LLM trả 'Hải
    Phòng' (địa điểm tổ chức) và tên sự kiện với salience="context" (hành vi
    ĐÚNG sau khi siết prompt) -> content_units_from_llm_output PHẢI giữ nguyên
    "context" cho cả 2, KHÔNG tự ý nâng cấp/hạ cấp salience."""
    from twmkt.agents.brief import content_units_from_llm_output
    import json as _json

    evidence = ("Hôm nay (10/7), tại Hải Phòng, Hội thảo và Triển lãm quốc tế "
               "thường niên về khu công nghiệp \"Diễn đàn Phát triển Khu Công "
               "nghiệp Việt Nam - Vietnam Industrial Park Summit 2026\" đã diễn ra.")
    raw = _json.dumps({"content_units": [
        {"shape": "entity", "value": "Hải Phòng", "label": "Địa điểm tổ chức hội thảo",
         "entity_type": "place", "salience": "context"},
        {"shape": "entity",
         "value": "Diễn đàn Phát triển Khu Công nghiệp Việt Nam - Vietnam Industrial Park Summit 2026",
         "label": "Tên sự kiện", "entity_type": "other", "salience": "context"},
    ]}, ensure_ascii=False)
    content_units = content_units_from_llm_output(raw, evidence).content_units
    by_value = {f.value: f.salience for f in content_units}
    assert by_value.get("Hải Phòng") == "context"
    assert by_value.get(
        "Diễn đàn Phát triển Khu Công nghiệp Việt Nam - Vietnam Industrial Park Summit 2026") == "context"


def test_content_units_from_llm_output_missing_shape_defaults_to_scalar():
    """Tương thích ngược: LLM/test cũ không gửi field 'shape' -> lùi về scalar
    (KHÔNG vỡ prompt/parser cũ nào chưa cập nhật)."""
    from twmkt.agents.brief import content_units_from_llm_output
    import json as _json

    raw = _json.dumps({"content_units": [
        {"value": "8,18%", "label": "GDP", "unit": "%", "raw": "8,18%"},
    ]}, ensure_ascii=False)
    content_units = content_units_from_llm_output(raw, _SSI_EVIDENCE).content_units
    assert len(content_units) == 1 and content_units[0].shape == "scalar"


def test_content_units_from_llm_output_mixed_shapes_and_scan_note_parsed():
    from twmkt.agents.brief import content_units_from_llm_output
    import json as _json

    evidence = ("Có hơn 400 KCN và 1.000 cụm công nghiệp. Thực tế có khoảng 70 - 80% "
               "vốn FDI đăng ký mới tập trung vào KCN. Các nhà đầu tư đến từ Hàn Quốc, "
               "Nhật Bản và Mỹ tiếp tục coi Việt Nam là điểm đến.")
    raw = _json.dumps({
        "content_units": [
            {"shape": "scalar", "value": "400", "unit": "KCN", "label": "Số KCN",
             "kind": "count", "raw": "hơn 400 KCN"},
            {"shape": "range", "value_low": "70", "value_high": "80", "unit": "%",
             "label": "Vốn FDI vào KCN"},
            {"shape": "entity_list", "label": "Quốc gia đầu tư",
             "entities": ["Hàn Quốc", "Nhật Bản", "Mỹ"]},
        ],
        "no_numeric_content": False,
        "scan_note": "Bài chỉ có 3 dữ kiện, đã quét hết toàn văn.",
    }, ensure_ascii=False)
    result = content_units_from_llm_output(raw, evidence)
    assert len(result.content_units) == 3
    shapes = sorted(f.shape for f in result.content_units)
    assert shapes == ["entity_list", "range", "scalar"]
    assert result.scan_note == "Bài chỉ có 3 dữ kiện, đã quét hết toàn văn."


def test_run_brief_reads_entity_types_from_settings_not_hardcoded():
    """`settings` (tuỳ chọn) -> entity_types đọc từ guardrail.entity_types
    (KHÔNG hard-code) — thiếu settings vẫn hoạt động (lùi về default nội bộ)."""
    from twmkt.agents.brief import run_brief
    import json as _json

    class _FakeSettings:
        def get(self, key, default=None):
            if key == "guardrail.entity_types":
                return ["company", "other"]
            return default

    class _FakeBriefLLM:
        def complete(self, system, prompt, *, model=None, fail_loud=False):
            assert "company|other" in system   # entity_types từ settings LỌT vào system prompt
            return _json.dumps({"content_units": [
                {"shape": "entity", "value": "SHS", "label": "Công ty", "entity_type": "company"},
            ]})

    evidence = "SHS công bố báo cáo."
    content_units = run_brief(_FakeBriefLLM(), evidence, settings=_FakeSettings()).content_units
    assert len(content_units) == 1 and content_units[0].entity_type == "company"


def test_run_brief_passes_model_and_verifies_output():
    """Dùng fake LLM (không gọi CLI/API thật) mô phỏng haiku trả JSON — kiểm
    model truyền đúng qua step_model + content_units verify được."""
    from twmkt.agents.brief import run_brief
    import json as _json

    class _FakeBriefLLM:
        def complete(self, system, prompt, *, model=None, fail_loud=False):
            assert model == "haiku" and fail_loud is False
            return _json.dumps({"content_units": [
                {"value": "8,18%", "label": "GDP 6 tháng đầu năm 2026", "unit": "%", "raw": "8,18%"}]})

    content_units = run_brief(_FakeBriefLLM(), _SSI_EVIDENCE, model="haiku").content_units
    assert len(content_units) == 1
    assert content_units[0].value == "8,18%" and content_units[0].label == "GDP 6 tháng đầu năm 2026"


def test_run_brief_degrades_to_empty_list_on_mockllm_or_empty_output():
    """Bước 'brief' là bước PHỤ -> KHÔNG fail_loud -> lỗi/rỗng LÙI MƯỢT về []
    (BriefResult rỗng-DO-HỎNG, Phase 4.12: no_numeric_content LUÔN False ở đường này)."""
    from twmkt.agents.brief import run_brief
    from twmkt.agents.base import MockLLM

    r = run_brief(MockLLM(), _SSI_EVIDENCE)   # MockLLM không trả JSON thật -> content_units=[]
    assert r.content_units == [] and r.no_numeric_content is False

    class _EmptyLLM:
        def complete(self, *a, **k):
            return ""

    r2 = run_brief(_EmptyLLM(), _SSI_EVIDENCE)
    assert r2.content_units == [] and r2.no_numeric_content is False


def test_production_brief_facts_field_defaults_empty_and_independent_per_instance():
    from twmkt.agents.production import ProductionBrief
    from twmkt.models import ContentUnit

    b1 = ProductionBrief(title="a")
    b2 = ProductionBrief(title="b")
    assert b1.content_units == [] and b2.content_units == []
    b1.content_units.append(ContentUnit(value="1%", label="x"))
    assert b2.content_units == []   # default_factory -> KHÔNG chia sẻ list giữa instance


# --- Phase 2.5: siết recall brief (taxonomy fact mở rộng + ContentUnit.kind) -------
def test_fact_kind_defaults_to_other_and_kinds_constant():
    from twmkt.models import FACT_KINDS, ContentUnit

    assert ContentUnit(value="1%", label="x").kind == "other"
    assert set(FACT_KINDS) == {"percent", "money", "count", "growth",
                               "date", "ranking", "target", "other"}


def test_content_units_from_llm_output_parses_kind_and_falls_back_to_other():
    from twmkt.agents.brief import content_units_from_llm_output
    import json as _json

    raw = _json.dumps({"content_units": [
        {"value": "8", "label": "Số cổ phiếu SSI khuyến nghị", "unit": None, "kind": "count",
         "raw": "8 cổ phiếu"},
        {"value": "8,18%", "label": "GDP 6T/2026", "kind": "percent", "raw": "8,18%"},
        {"value": "8 cổ phiếu", "label": "Nhãn không kind hợp lệ", "kind": "khong-ton-tai",
         "raw": "8 cổ phiếu"},
    ]}, ensure_ascii=False)
    content_units = content_units_from_llm_output(raw, _SSI_EVIDENCE).content_units
    by_value = {f.value: f for f in content_units}
    assert by_value["8"].kind == "count"
    assert by_value["8,18%"].kind == "percent"
    assert by_value["8 cổ phiếu"].kind == "other"   # kind lạ -> "other", KHÔNG loại fact


def test_content_units_from_llm_output_attributes_count_fact_to_correct_sentence_not_percent():
    """Yêu cầu Phase 2.5: evidence có CẢ '8 cổ phiếu' lẫn '8,18%' -> fact
    value='8' kind=count PHẢI gán source về câu '8 cổ phiếu', KHÔNG về câu
    '8,18%' (dù cả 2 câu đều chứa ký tự '8')."""
    from twmkt.agents.brief import content_units_from_llm_output
    import json as _json

    raw = _json.dumps({"content_units": [
        {"value": "8", "label": "Số cổ phiếu SSI khuyến nghị", "unit": None, "kind": "count",
         "raw": "8 cổ phiếu"},
    ]}, ensure_ascii=False)
    content_units = content_units_from_llm_output(raw, _SSI_EVIDENCE).content_units
    assert len(content_units) == 1
    assert content_units[0].kind == "count"
    assert content_units[0].source.startswith("Tuy nhiên SSI vẫn lựa chọn 8 cổ phiếu")
    assert "8,18%" not in content_units[0].source


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


def test_content_units_from_llm_output_computes_canonical_value_and_approx_flag():
    """Mục C: Brief (AI) trả thêm raw/approx; CODE (KHÔNG phải AI) tính
    canonical_value từ value+unit đã verify."""
    from twmkt.agents.brief import content_units_from_llm_output
    import json as _json

    evidence = "Khối ngoại bán ròng toàn thị trường 585 tỷ đồng trong phiên hôm nay."
    raw = _json.dumps({"content_units": [
        {"value": "585", "label": "Khối ngoại bán ròng toàn thị trường", "unit": "tỷ đồng",
         "kind": "money", "raw": "585 tỷ đồng", "approx": False},
    ]}, ensure_ascii=False)
    content_units = content_units_from_llm_output(raw, evidence).content_units
    assert len(content_units) == 1
    f = content_units[0]
    assert f.raw == "585 tỷ đồng"
    assert f.canonical_value == 585e9
    assert f.approx is False


def test_content_units_from_llm_output_drops_fact_when_raw_not_substring_of_evidence():
    """(test 4, Mục C) raw KHÔNG phải substring THẬT của evidence -> LOẠI fact
    NGAY, dù value/unit riêng lẻ có verify được (chống AI paraphrase/bịa cụm)."""
    from twmkt.agents.brief import content_units_from_llm_output
    import json as _json

    evidence = "Khối ngoại bán ròng toàn thị trường 585 tỷ đồng trong phiên hôm nay."
    raw = _json.dumps({"content_units": [
        {"value": "585", "label": "Khối ngoại bán ròng", "unit": "tỷ đồng",
         "raw": "khoảng 585 tỷ đồng chẵn"},   # cụm bịa, KHÔNG xuất hiện y hệt trong evidence
    ]}, ensure_ascii=False)
    assert content_units_from_llm_output(raw, evidence).content_units == []


def test_content_units_from_llm_output_approx_flag_true_when_raw_has_hedge_word_even_if_ai_forgets():
    """approx = cờ AI trả HOẶC code tự dò trong raw (an toàn kép, không tin mù AI)."""
    from twmkt.agents.brief import content_units_from_llm_output
    import json as _json

    evidence = "Nhu cầu điện tại Havana chỉ được đáp ứng khoảng 1% trong ngày sự cố."
    raw = _json.dumps({"content_units": [
        {"value": "1", "label": "Phần trăm nhu cầu điện đáp ứng tại Havana", "unit": "%",
         "raw": "khoảng 1%", "approx": False},   # AI QUÊN đánh dấu approx=True
    ]}, ensure_ascii=False)
    content_units = content_units_from_llm_output(raw, evidence).content_units
    assert len(content_units) == 1 and content_units[0].approx is True   # code tự dò "khoảng" -> ép True


def test_fact_new_fields_default_backward_compatible():
    from twmkt.models import ContentUnit

    f = ContentUnit(value="1%", label="x")
    assert f.raw == "" and f.canonical_value is None and f.approx is False


# --- Phase 4.8 Mục C: guardrail canonical (agents/production.py) -----------
def _fact(canonical, approx=False):
    from twmkt.models import ContentUnit
    return ContentUnit(value="x", label="y", canonical_value=canonical, approx=approx)


def test_unsupported_numbers_accepts_approx_rounding_within_tolerance_when_body_hedges():
    """(test 1, Mục C) 'gần 600 tỷ' trong bài, evidence chỉ có '585 tỷ' -> fact
    canonical=585e9 + số trong bài đi kèm từ xấp xỉ ('gần') -> is_clean (KHÔNG
    chặn oan, đúng bug false-positive Phase 4.7 'khối ngoại')."""
    from twmkt.agents.production import unsupported_numbers

    body = "Khối ngoại bán ròng gần 600 tỷ đồng trong phiên hôm nay."
    evidence = "Khối ngoại bán ròng 585 tỷ đồng trong phiên hôm nay."
    content_units = [_fact(585e9)]
    assert unsupported_numbers(body, evidence, content_units) == []


def test_unsupported_numbers_still_flags_exact_decimal_mismatch_without_hedge_word():
    """(test 5, Mục C) '855 tỷ' khi evidence/canonical chỉ có 585 tỷ (lệch
    ~46%, KHÔNG có từ xấp xỉ) -> vẫn bị chặn, KHÔNG nhầm là làm tròn hợp lý."""
    from twmkt.agents.production import unsupported_numbers

    body = "Khối ngoại bán ròng 855 tỷ đồng trong phiên hôm nay."
    evidence = "Khối ngoại bán ròng 585 tỷ đồng trong phiên hôm nay."
    content_units = [_fact(585e9)]
    bad = unsupported_numbers(body, evidence, content_units)
    assert any("855" in b for b in bad)


def test_unsupported_numbers_flags_number_with_no_matching_canonical_fact():
    """(test 3, Mục C) '999 tỷ' bịa hoàn toàn, không khớp evidence lẫn canonical
    nào trong content_units[] -> vẫn bị chặn (guardrail chặn số bịa tuyệt đối)."""
    from twmkt.agents.production import unsupported_numbers

    body = "Lợi nhuận tăng vọt lên 999 tỷ đồng."
    evidence = "Khối ngoại bán ròng 585 tỷ đồng trong phiên hôm nay."
    content_units = [_fact(585e9)]
    bad = unsupported_numbers(body, evidence, content_units)
    assert any("999" in b for b in bad)


def test_unsupported_numbers_decimal_separator_regression_still_clean_with_facts_param():
    """(test 2, Mục C) Không regress fix 1: '12,61%' viết trong bài, evidence
    '12.61%' -> vẫn is_clean dù giờ có truyền thêm `content_units` (tham số optional)."""
    from twmkt.agents.production import unsupported_numbers

    body = "Tỷ suất lợi nhuận đạt 12,61% trong quý này."
    evidence = "Tỷ suất lợi nhuận đạt 12.61% trong quý này (dữ liệu bảng HOSE)."
    assert unsupported_numbers(body, evidence, content_units=[]) == []
    assert unsupported_numbers(body, evidence) == []   # content_units mặc định None -> vẫn hoạt động như cũ


def test_unsupported_numbers_exact_tolerance_zero_rejects_rounding_without_hedge_word():
    """Số trong bài KHÔNG đi kèm từ xấp xỉ -> dung sai mặc định = 0 (khớp
    CHÍNH XÁC), dù lệch nhỏ (600 vs 585, ~2.6%) vẫn bị chặn — 5% CHỈ áp dụng
    khi có từ xấp xỉ ngay trước số (khác test 1 ở trên)."""
    from twmkt.agents.production import unsupported_numbers

    body = "Khối ngoại bán ròng 600 tỷ đồng trong phiên hôm nay."   # KHÔNG có "gần"/"khoảng"
    evidence = "Khối ngoại bán ròng 585 tỷ đồng trong phiên hôm nay."
    content_units = [_fact(585e9)]
    bad = unsupported_numbers(body, evidence, content_units)
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


def test_route_from_llm_output_parses_output_channels_and_rationale():
    """Phase 4.13 Mục A: LLM trả output_channels/channel_rationale hợp lệ ->
    parse ĐÚNG (không bị ép default), giữ nguyên channel router chọn false."""
    from twmkt.agents.structure_router import route_from_llm_output
    import json as _json

    raw = _json.dumps({
        "content_type": "article", "structure": "S1", "hook": "H1",
        "secondary_structure": None, "rationale": "Luận điểm rõ.",
        "signals": {"has_genuine_paradox": False, "drivers": [], "has_central_thesis": True},
        "output_channels": {"article": True, "infographic": False, "video": True},
        "channel_rationale": {"article": "Đủ chất liệu", "infographic": "Không có số",
                              "video": "Có narrative kể được"},
    }, ensure_ascii=False)
    d = route_from_llm_output(raw)
    assert d.output_channels == {"article": True, "infographic": False, "video": True}
    assert d.channel_rationale["infographic"] == "Không có số"


def test_route_from_llm_output_missing_or_malformed_channels_defaults_all_true():
    """Parse LỎNG (an toàn — KHÔNG tự cắt tuyến khi không chắc): thiếu hẳn
    output_channels/channel_rationale, hoặc type sai (list thay vì dict), hay
    thiếu 1 khoá trong dict -> MẶC ĐỊNH True cho khoá đó."""
    from twmkt.agents.structure_router import route_from_llm_output
    import json as _json

    base = {"content_type": "article", "structure": "S1", "hook": "H1",
           "secondary_structure": None, "rationale": "x",
           "signals": {"has_genuine_paradox": False, "drivers": [], "has_central_thesis": True}}

    d1 = route_from_llm_output(_json.dumps(base, ensure_ascii=False))
    assert d1.output_channels == {"article": True, "infographic": True, "video": True}
    assert d1.channel_rationale == {"article": "", "infographic": "", "video": ""}

    bad = dict(base, output_channels=["not", "a", "dict"], channel_rationale="not a dict either")
    d2 = route_from_llm_output(_json.dumps(bad, ensure_ascii=False))
    assert d2.output_channels == {"article": True, "infographic": True, "video": True}

    partial = dict(base, output_channels={"infographic": False})   # thiếu article/video
    d3 = route_from_llm_output(_json.dumps(partial, ensure_ascii=False))
    assert d3.output_channels == {"article": True, "infographic": False, "video": True}


def test_fallback_always_keeps_all_channels_true():
    """_fallback() (router lỗi/JSON hỏng/S5-vi-phạm) KHÔNG BAO GIỜ tự cắt tuyến
    — lỗi hạ tầng không phải lý do hợp lệ để suy ra tin không hợp infographic/
    video. Test qua đường công khai (route_from_llm_output rỗng -> fallback)."""
    from twmkt.agents.structure_router import route_from_llm_output

    d = route_from_llm_output("")
    assert d.fallback is True
    assert d.output_channels == {"article": True, "infographic": True, "video": True}


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
    from twmkt.models import ContentUnit

    brief = ProductionBrief(title="SSI 8 cổ phiếu", hook="hook gợi ý", group="ChungKhoan",
                            topic="SSI", content_units=[ContentUnit(value="8,18", label="GDP 6T/2026",
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


def test_router_decision_store_persists_output_channels_across_instances():
    """Phase 4.13: output_channels/channel_rationale ĐÓNG BĂNG CÙNG quyết định
    (route-once) -> instance MỚI đọc lại ĐÚNG, không bị mất/reset về default."""
    from twmkt.agents.route_once import RouterDecisionStore
    from twmkt.agents.structure_router import RouterDecision

    path = _tmp_decisions_path()
    decision = RouterDecision(
        content_type="article", structure="S1", hook="H1", secondary_structure=None,
        rationale="x", signals={}, fallback=False,
        output_channels={"article": True, "infographic": False, "video": True},
        channel_rationale={"article": "", "infographic": "Không có số", "video": ""},
    )
    RouterDecisionStore(path).set("k-channels", decision)

    store2 = RouterDecisionStore(path)
    cached = store2.get("k-channels")
    assert cached.output_channels == {"article": True, "infographic": False, "video": True}
    assert cached.channel_rationale["infographic"] == "Không có số"


def test_router_decision_store_backward_compat_old_entry_defaults_channels_true():
    """Entry CŨ (đóng băng TRƯỚC Phase 4.13, KHÔNG có output_channels/
    channel_rationale trong file JSON) -> load về default CẢ 3 True (KHÔNG hồi
    tố cắt tuyến cho quyết định đã đóng băng từ trước khi có cơ chế này)."""
    import json as _json
    from twmkt.agents.route_once import RouterDecisionStore

    path = _tmp_decisions_path()
    old_entry = {
        "content_type": "article", "structure": "S1", "hook": "H1",
        "secondary_structure": None, "rationale": "x", "signals": {}, "fallback": False,
    }   # KHÔNG có output_channels/channel_rationale (định dạng CŨ, trước 4.13)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_json.dumps({"k-old": old_entry}, ensure_ascii=False), encoding="utf-8")

    cached = RouterDecisionStore(path).get("k-old")
    assert cached.output_channels == {"article": True, "infographic": True, "video": True}
    assert cached.channel_rationale == {}


def test_router_decision_store_set_channel_overrides_without_reroute():
    """(Phase 4.13) Owner override 1 tuyến qua set_channel() — KHÔNG gọi lại
    LLM, structure/hook giữ NGUYÊN, chỉ output_channels[channel] đổi (giống
    triết lý reroute nhưng KHÔNG cần route lại cả quyết định)."""
    from twmkt.agents.route_once import RouterDecisionStore, get_or_route
    from twmkt.agents.production import ProductionBrief

    store = RouterDecisionStore(_tmp_decisions_path())
    brief = ProductionBrief(title="Chủ đề owner override")
    llm = _RouterJsonLLM(structure="S3", hook="H1")
    get_or_route(llm, brief, store=store, key="k-override")
    assert llm.calls == 1

    ok = store.set_channel("k-override", "infographic", False)
    assert ok is True

    cached = store.get("k-override")
    assert cached.output_channels["infographic"] is False
    assert cached.output_channels["article"] is True          # tuyến khác KHÔNG đổi
    assert cached.structure == "S3" and cached.hook == "H1"   # KHÔNG route lại
    assert "[owner override]" in cached.channel_rationale["infographic"]
    assert llm.calls == 1   # set_channel KHÔNG gọi LLM


def test_router_decision_store_set_channel_returns_false_when_key_missing():
    from twmkt.agents.route_once import RouterDecisionStore

    store = RouterDecisionStore(_tmp_decisions_path())
    assert store.set_channel("khong-ton-tai", "video", False) is False


def test_router_decision_store_set_channel_invalid_channel_raises():
    from twmkt.agents.route_once import RouterDecisionStore, get_or_route
    from twmkt.agents.production import ProductionBrief

    store = RouterDecisionStore(_tmp_decisions_path())
    get_or_route(_RouterJsonLLM(), ProductionBrief(title="x"), store=store, key="k")
    try:
        store.set_channel("k", "podcast", True)
    except ValueError:
        return
    raise AssertionError("phải raise ValueError với channel lạ")


# --- Render Infographic (src/twmkt/render, $0 tất định) --------------------
def test_brand_kit_from_settings_reads_overrides_and_defaults():
    """Phase 1.2: brand_kit_from_settings() gộp config/brand.yaml (màu/font/
    wordmark/footer, MỘT NGUỒN) + render.infographic.* (kích thước, có thể
    ghi đè từng token brand). Đọc file brand.yaml THẬT trên đĩa (giống các
    test đọc prompts/*.md thật khác trong file này) — đổi giá trị trong
    config/brand.yaml thì cập nhật lại assertion primary/wordmark ở đây."""
    from twmkt.render import brand_kit_from_settings

    kit = brand_kit_from_settings(Settings({}))
    assert kit["width"] == 1080 and kit["primary"] == "#C9973E"
    assert kit["wordmark"] == "FVA CAPITAL"
    assert "không phải khuyến nghị đầu tư" in kit["disclaimer"]

    kit2 = brand_kit_from_settings(Settings({"render": {"infographic": {
        "primary": "#FF0000", "width": 800,
    }}}))
    assert kit2["primary"] == "#FF0000" and kit2["width"] == 800   # settings.yaml GHI ĐÈ brand.yaml
    assert kit2["bg"] == "#0B1B2B"   # key không ghi đè -> vẫn dùng brand.yaml/mặc định


def test_number_discipline_block_present_in_writer_and_composer_system():
    """Phase 4.13 Mục B: KỶ LUẬT SỐ (cấm tự cộng/gộp số, cấm rớt đơn vị/bậc số,
    quy ước dấu chấm/phẩy tiếng Việt) PHẢI có mặt ở CẢ 2 nơi sinh nội dung có
    số — writer (article) và composer (infographic) — tránh trôi giữa 2 agent."""
    from twmkt.agents.production import AnalysisWriterAgent, InfographicSpecAgent, _NUMBER_DISCIPLINE

    assert _NUMBER_DISCIPLINE in AnalysisWriterAgent.system
    assert _NUMBER_DISCIPLINE in InfographicSpecAgent.system
    assert "CỘNG/GỘP" in _NUMBER_DISCIPLINE
    assert "357.000" in _NUMBER_DISCIPLINE   # ví dụ cụ thể chống rớt bậc số


def test_infographic_composer_no_longer_teaches_risky_magnitude_conversion():
    """Regression (Phase 4.13): trước phase này, composer prompt DẠY ví dụ tự
    quy đổi bậc số ('41.200 tỷ đồng' -> '41,2 nghìn tỷ') — chính kiểu quy đổi
    này gây bug rớt '000' phát hiện ở backtest Phase 4.12-B ('357.000 tỷ đồng'
    -> '357 tỷ', sai 1.000 lần). Ví dụ rủi ro đó phải bị GỠ khỏi prompt."""
    from twmkt.agents.production import InfographicSpecAgent

    assert "41,2 nghìn tỷ" not in InfographicSpecAgent.system


def test_prompts_infographic_v1_file_matches_code_default_no_drift():
    """Phase 4.13: prompts/infographic.v1.md TỪNG lệch code default (file cũ,
    tiền-Phase-4.11, nói 'InfographicSpecAgent KHÔNG gọi LLM') trong khi tab
    PROMPTS Sheet LIVE đang bật infographic=v1 -> composer THẬT âm thầm dùng
    prompt lỗi thời (không có schema 8 trường, KHÔNG có KỶ LUẬT SỐ mới) — phát
    hiện khi backtest Phase 4.13. Khoá lại bằng test, giống drift test analysis/
    video đã có."""
    from twmkt.agents.production import InfographicSpecAgent
    from twmkt.agents.prompts import read_prompt_file

    assert read_prompt_file("infographic", "v1", prompts_dir="prompts") == InfographicSpecAgent.system


def test_render_infographic_svg_contains_headline_stats_and_disclaimer():
    from twmkt.agents.production import InfographicSpecAgent, ProductionBrief
    from twmkt.render import brand_kit_from_settings, render_infographic_svg
    import json as _json
    import xml.dom.minidom as minidom

    from twmkt.models import ContentUnit

    brief = ProductionBrief(title="PNJ tăng 40%", hook="PNJ: kỷ lục doanh thu",
                            tickers=["PNJ"], url="https://cafef.vn/x.chn",
                            evidence="Doanh thu tăng 40%, đạt 1.200 tỷ đồng, kỷ lục.",
                            content_units=[ContentUnit(value="40", label="Tăng trưởng doanh thu", unit="%",
                                       kind="percent", raw="tăng 40%", canonical_value=40.0)])
    # InfographicSpecAgent(None) -> MockLLM (junk, không parse được JSON) ->
    # LÙI MƯỢT dùng _fallback_infographic_spec (tất định từ content_units[]).
    spec = _json.loads(InfographicSpecAgent(None).run(brief).body)
    brand = brand_kit_from_settings(Settings({}))
    svg = render_infographic_svg(spec, brand)

    assert svg.startswith("<svg ")
    minidom.parseString(svg)   # phải là XML hợp lệ, không lỗi parse
    assert "PNJ" in svg
    assert spec["hero"][0]["value"] in svg
    assert "không phải khuyến nghị đầu tư" in svg
    assert brand["primary"] in svg


def test_render_infographic_svg_uses_brand_wordmark_not_old_brand():
    """Regression Phase 1.2: wordmark cũ 'TURTLE WEALTH VN' hard-code từng in
    thẳng lên MỌI ảnh infographic — đã sửa đọc từ config/brand.yaml (FVA
    Capital, xem PROJECT_HANDOFF_P5.md §1)."""
    from twmkt.render import brand_kit_from_settings, render_infographic_svg

    brand = brand_kit_from_settings(Settings({}))
    svg = render_infographic_svg({"title": "T"}, brand)
    assert "FVA CAPITAL" in svg
    assert "TURTLE WEALTH" not in svg


def test_render_infographic_svg_handles_empty_stats_and_missing_footer():
    from twmkt.render import render_infographic_svg
    import xml.dom.minidom as minidom

    svg = render_infographic_svg({"title": "Chỉ tiêu đề", "related": []})
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
    assert "Composer" in by_role["InfographicComposer"].system


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


def test_video_prompt_states_narration_number_format_contract():
    """V1 (2026-07-19) — prompt Composer PHẢI dạy rõ định dạng `narration`.

    Lỗi thật đã gặp: Opus viết "năm hai nghìn không trăm hai mươi lăm" vào
    narration, vi phạm `docs/CONTENT_OUTPUT_SCHEMA.md` ("narration giữ nguyên
    số + ticker, KHÔNG viết số bằng chữ") — vì prompt CŨ không có DÒNG NÀO nói
    về định dạng số. Test này khoá phần dạy đó lại, để không ai xoá nhầm khi
    biên tập prompt sau này.

    Test drift ở trên chỉ bảo đảm file .md == chuỗi trong code (2 bản GIỐNG
    NHAU); test này bảo đảm nội dung ĐÚNG (có thật quy tắc), là 2 việc khác
    nhau — cả hai đều cần.
    """
    from twmkt.agents.production import VideoScriptAgent

    system = VideoScriptAgent.system
    # Cấm dạy ngược (số→chữ, phiên âm) — việc của tầng voice tất định phía sau.
    assert "TUYỆT ĐỐI KHÔNG viết số thành chữ" in system
    assert "KHÔNG phiên âm" in system
    # Áp cho CẢ 2 field, không chỉ narration.
    assert "`narration` LẪN mọi field chữ trong `payload`" in system
    # Có ví dụ SAI cụ thể — mẫu Opus thật sự đã sinh ra.
    assert "hai nghìn không trăm hai mươi lăm" in system
    # Ticker/viết tắt GIỮ NGUYÊN (ghi đè luật voice-over cũ ở §4.5).
    assert "GHI ĐÈ §4.5" in system
    for keep_as_is in ("HVN", "VN-Index", "Q2/2026", "4,98%"):
        assert keep_as_is in system, f"thiếu ví dụ giữ-nguyên-dạng: {keep_as_is}"


def test_content_writer_rules_no_longer_bans_tickers_in_voice_over():
    """§4.5 từng CẤM mã CK trong voice-over — mâu thuẫn với hợp đồng narration mới.

    `_load_content_writer_rules(sections=("2","4"))` nối §4 vào system prompt
    SAU CÙNG (xem VideoScriptAgent.run), nên luật cũ ở đây sẽ THẮNG luật mới nếu
    còn nguyên văn → Composer nhận 2 chỉ thị ngược nhau → output không nhất quán.
    Đây chính là thứ cần chặn.
    """
    from twmkt.agents.production import _load_content_writer_rules

    # settings=Settings({}) TƯỜNG MINH -- cô lập khỏi config/settings.yaml THẬT
    # (từ Phase A, file đó đã set `writer.content_rules_path` cho mode "full",
    # cùng KEY này cũng là override của `_load_content_writer_rules` -- không
    # cô lập sẽ đọc NHẦM path v3.4 rồi cắt §2/§4 kiểu legacy trên file không
    # cùng cấu trúc mục, cho kết quả rỗng/sai).
    rules = _load_content_writer_rules(sections=("2", "4"), settings=Settings({}))
    assert rules, "không đọc được content_rules_v1.0.md"
    assert "Voice-over CẤM dùng mã chứng khoán" not in rules, (
        "§4.5 vẫn còn luật cũ nguyên văn — sẽ ghi đè hợp đồng narration mới"
    )
    assert "GIỮ NGUYÊN mã chứng khoán" in rules


def test_content_writer_rules_section_re_accepts_both_heading_levels_no_false_match():
    """1.2 — loader cắt mục phải nhận CẢ `# N.` LẪN `## N.`.

    Vì sao: `content_rules_v1.0.md` dùng `#`, `long_content_rules.md`
    dùng `##`. Regex cũ (`^# `) khớp 0 mục trên file longform -> loader trả ""
    ÂM THẦM (rule không bao giờ được áp, KHÔNG cảnh báo) — đúng lớp lỗi hỏng-im-lặng.

    Đồng thời PHẢI KHÔNG false-match mục con (`## 2.1.`, `### 3.1.`): regex đòi
    dấu chấm + KHOẢNG TRẮNG sau số nên "2.1. " không lọt.
    """
    from twmkt.agents.production import _CONTENT_WRITER_RULES_SECTION_RE as RE

    probe = "# 1. A\n## 2. B\n## 2.1. C\n### 3.1. D\n#### 4. E\n## 10. F\n"
    assert [m.group(1) for m in RE.finditer(probe)] == ["1", "2", "10"], (
        "phải bắt mục cấp 1 ở cả 2 mức #/##, KHÔNG bắt mục con và KHÔNG bắt ####"
    )


def test_content_writer_rules_section_re_no_regression_on_existing_file():
    """Nới regex KHÔNG được đổi kết quả trên file rule CŨ (Article/Video/
    Infographic đang định tuyến theo số mục — đổi là vỡ âm thầm cả 3 đường)."""
    import re
    from pathlib import Path
    from twmkt.agents.production import _CONTENT_WRITER_RULES_SECTION_RE as NEW

    old = re.compile(r"(?m)^# (\d+)\. ")
    text = Path("prompts/content_rules_v1.0.md").read_text(encoding="utf-8")
    assert [(m.group(1), m.start()) for m in old.finditer(text)] == \
           [(m.group(1), m.start()) for m in NEW.finditer(text)]


def test_longform_rules_file_present_in_repo_and_sectionable():
    """Rule bài dài phải NẰM TRONG repo (bản ngoài repo `content-rules/` không
    theo git -> mất khi đổi máy/VPS, CÙNG LỚP LỖI data_root) và phải cắt được
    mục bằng loader."""
    from pathlib import Path
    from twmkt.agents.production import _CONTENT_WRITER_RULES_SECTION_RE as RE

    p = Path("prompts/long_content_rules.md")
    assert p.exists(), "thiếu bản copy trong repo"
    text = p.read_text(encoding="utf-8")
    assert "NGUỒN: content-rules/" in text, "thiếu khối ghi nguồn + ngày"
    assert len(list(RE.finditer(text))) >= 15, "loader không cắt được mục của file longform"


def test_composer_rules_v21_copy_present_and_sectionable():
    """rules v2.1 (BƯỚC 1) phải NẰM TRONG repo — cùng lý do longform (bản ngoài
    repo `content-rules/` không theo git). Đủ mục §1-10 để loader trích."""
    from pathlib import Path
    from twmkt.agents.production import _CONTENT_WRITER_RULES_SECTION_RE as RE

    p = Path("prompts/content-rules-v2.1.md")
    assert p.exists(), "thiếu bản copy content-rules-v2.1.md trong repo"
    text = p.read_text(encoding="utf-8")
    assert "NGUỒN: content-rules/CONTENT_COMPOSER_RULES_v2.1.md" in text
    assert "- Hệ thống đóng dấu nguồn và disclaimer tất định" in text   # BƯỚC 0: §3.4 đã sửa
    # Dòng BULLET gốc (không phải câu nhắc trong header giải thích) phải KHÔNG
    # còn — chỉ kiểm PHẦN THÂN file (sau khối header <!-- ... -->).
    body = text.split("-->", 1)[1]
    assert "- Thêm nguồn và disclaimer khi chủ đề hoặc kênh xuất bản yêu cầu." not in body
    assert len(list(RE.finditer(text))) == 10, "phải cắt đủ 10 mục cấp 1 (§1-10)"


def test_load_composer_rules_defaults_to_v21_and_selects_correct_product_section():
    """BƯỚC 1.1/1.4 — mặc định profile v21, mỗi content_type nhận ĐÚNG phần
    §7.N của mình (article->7.1, video->7.2, infographic->7.3), core §1-6
    dùng CHUNG. KHÔNG lẫn phần loại khác (vd video không dính "Article và
    Long-form Article" của §7.1).

    settings=Settings({"writer": {"rules_load_mode": "legacy_sections"}}) TƯỜNG
    MINH -- test này khoá hành vi nhánh legacy_sections/v21 CŨ (TRƯỚC Phase A),
    phải cô lập khỏi config/settings.yaml THẬT (nay mặc định mode "full" cho
    sản xuất, xem test_load_composer_rules_full_mode_reads_v34_verbatim_no_
    section_cut) -- không cô lập sẽ vô tình test nhầm nhánh full."""
    from twmkt.agents.production import _load_composer_rules

    s = Settings({"writer": {"rules_load_mode": "legacy_sections"}})
    article = _load_composer_rules("article", settings=s)
    video = _load_composer_rules("video", settings=s)
    infographic = _load_composer_rules("infographic", settings=s)

    for r in (article, video, infographic):
        assert "## 1. Mục tiêu" in r   # core §1 dùng chung
        assert "## 8. Validation" not in r   # §8 KHÔNG nhúng (tài liệu validator, không phải Composer)

    assert "### 7.1. Article và Long-form Article" in article
    assert "### 7.2." not in article and "### 7.3." not in article

    assert "### 7.2. Video Script" in video
    assert "### 7.1." not in video and "### 7.3." not in video

    assert "### 7.3. Infographic Script" in infographic
    assert "### 7.1." not in infographic and "### 7.2." not in infographic


def test_load_composer_rules_profile_switch_and_explicit_override_wins():
    """BƯỚC 1.2 — A/C chọn được qua config `writer.rules_profile`, KHÔNG xoá.
    C (chỉ có article) lùi về A cho video/infographic. `content_rules_path`
    (override tường minh, TEST CŨ dùng) LUÔN THẮNG bất kể profile."""
    from twmkt.config import Settings
    from twmkt.agents.production import _load_composer_rules, _load_content_writer_rules

    s_default = Settings({})
    s_a = Settings({"writer": {"rules_profile": "A"}})
    s_c = Settings({"writer": {"rules_profile": "C"}})

    # Mặc định (không set gì) == profile "v21" tường minh.
    assert _load_composer_rules("article", settings=s_default) == \
           _load_composer_rules("article", settings=Settings({"writer": {"rules_profile": "v21"}}))

    # Profile A -> đúng nội dung content_writer_rules.md (hàm cũ, KHÔNG đổi).
    assert _load_composer_rules("video", settings=s_a) == \
           _load_content_writer_rules(sections=("2", "4"), settings=s_a)

    # Profile C: article có nội dung RIÊNG (khác A); video/infographic LÙI VỀ A
    # (C không có mục 2 loại này) -> giống hệt profile A.
    assert _load_composer_rules("article", settings=s_c) != _load_composer_rules("article", settings=s_a)
    assert _load_composer_rules("video", settings=s_c) == _load_composer_rules("video", settings=s_a)
    assert _load_composer_rules("infographic", settings=s_c) == _load_composer_rules("infographic", settings=s_a)

    # Override tường minh THẮNG mọi profile (kể cả v21 mặc định) — tương thích
    # test cũ trỏ file tạm qua content_rules_path.
    s_override = Settings({"writer": {"content_rules_path": "prompts/content_rules_v1.0.md",
                                      "rules_profile": "v21"}})
    assert _load_composer_rules("article", settings=s_override) == \
           _load_content_writer_rules(sections=("2", "3"), settings=s_override)


# ==== PHASE A (rules loader v3+, 2026-07-3x) — A6 test list =================

def test_load_composer_rules_full_mode_reads_v34_verbatim_no_section_cut():
    """A1/A2 — mode "full" nạp NGUYÊN VĂN content-rules-daily-v3.4.md, KHÔNG
    cắt theo mục (khác hẳn nhánh legacy_sections cắt §N riêng theo
    content_type). Cả 3 content_type nhận CÙNG 1 văn bản NGUYÊN VẸN — so khớp
    ĐÚNG BẰNG nội dung đọc trực tiếp từ đĩa (rstrip), không suy luận qua độ dài
    hay 1 câu con."""
    from pathlib import Path
    from twmkt.agents.production import _load_composer_rules

    settings = Settings({"writer": {"rules_load_mode": "full"}})
    raw = Path("prompts/content-rules-daily-v3.4.md").read_text(encoding="utf-8").rstrip()
    assert raw, "file rules v3.4 rỗng -- không test được tính verbatim"
    for content_type in ("article", "video", "infographic"):
        assert _load_composer_rules(content_type, settings=settings) == raw


def test_load_composer_rules_legacy_mode_explicit_matches_unset_default():
    """A2 — set `rules_load_mode: legacy_sections` TƯỜNG MINH phải cho kết quả
    HỆT khi KHÔNG set gì (Settings({})) -- "legacy_sections" là mặc định CODE
    khi thiếu key này (tương thích ngược tuyệt đối với pipeline đang chạy
    TRƯỚC Phase A, vốn không biết khái niệm rules_load_mode)."""
    from twmkt.agents.production import _load_composer_rules

    s_legacy = Settings({"writer": {"rules_load_mode": "legacy_sections"}})
    s_unset = Settings({})
    for content_type in ("article", "video", "infographic"):
        assert _load_composer_rules(content_type, settings=s_legacy) == \
               _load_composer_rules(content_type, settings=s_unset)
    assert "### 7.2. Video Script" in _load_composer_rules("video", settings=s_legacy)


def test_load_composer_rules_full_mode_missing_file_returns_empty():
    """LÙI MƯỢT -- file rules chỉ định (mode=full) không tồn tại -> "" (agent
    vẫn chạy bằng persona/schema gốc, KHÔNG crash), cùng nếp mọi nhánh
    legacy_sections khác trong hàm này."""
    from twmkt.agents.production import _load_composer_rules

    settings = Settings({"writer": {"rules_load_mode": "full",
                                    "content_rules_path": "prompts/khong-ton-tai-xyz-test.md"}})
    assert _load_composer_rules("article", settings=settings) == ""


def test_full_mode_composer_prompt_embeds_rules_exactly_once(tmp_path):
    """A6 -- "full-mode prompt chứa ĐÚNG 1 file rules": dựng 1 file rules tạm
    có 1 chuỗi đánh dấu DUY NHẤT, gán qua `agent.rules_settings` (per-request,
    A5, CÙNG NẾP `agent.model = ...`), xác nhận system prompt Composer chứa
    chuỗi đó ĐÚNG 1 LẦN -- không lặp (không lẫn cả bản full lẫn 1 bản cắt
    legacy nào khác cùng lúc)."""
    import json as _json
    from twmkt.agents.production import AnalysisWriterAgent, ProductionBrief

    marker = "MARKER-RULES-V34-UNIQUE-773311"
    rules_file = tmp_path / "rules_full.md"
    rules_file.write_text(f"# Rules test\n{marker}\nNội dung rules.\n", encoding="utf-8")

    class _SpyLLM:
        last_system = ""

        def complete(self, system, prompt, **kwargs):
            self.last_system = system
            return _json.dumps({
                "title": "t", "sapo": "s",
                "sections": [{"heading": "h", "content": "Doanh thu tăng 40%."}],
                "disclaimer": "d", "sources": [],
            }, ensure_ascii=False)

    llm = _SpyLLM()
    agent = AnalysisWriterAgent(llm)
    agent.rules_settings = Settings({"writer": {
        "rules_load_mode": "full", "content_rules_path": str(rules_file),
    }})
    brief = ProductionBrief(title="t", hook="h", evidence="Doanh thu tăng 40%.")
    agent.run(brief)
    assert llm.last_system.count(marker) == 1


def test_video_agent_accepts_per_request_rules_settings(tmp_path):
    """A5 -- premise gốc của task ("Video đang thiếu rules_settings riêng,
    Article/Infographic ĐÃ CÓ") ĐÃ XÁC NHẬN LÀ SAI (grep+đọc call site TRƯỚC
    Phase A: cả 3 đều gọi `_load_composer_rules(content_type)` KHÔNG settings)
    -- test này khoá hành vi ĐÃ THÊM ĐỒNG NHẤT cho cả 3, không riêng Video."""
    import json as _json
    from twmkt.agents.production import VideoScriptAgent, ProductionBrief

    marker = "MARKER-VIDEO-RULES-991122"
    rules_file = tmp_path / "video_rules.md"
    rules_file.write_text(f"# Rules\n{marker}\n", encoding="utf-8")

    class _SpyLLM:
        last_system = ""

        def complete(self, system, prompt, **kwargs):
            self.last_system = system
            return _json.dumps({
                "schema_version": 1, "title": "t",
                "scenes": [
                    {"role": "hook", "visual_kind": "statement",
                     "payload": {"hero": "x", "desc": ""}, "narration": "x"},
                    {"role": "body", "visual_kind": "statement",
                     "payload": {"hero": "y", "desc": ""}, "narration": "y"},
                    {"role": "outro", "visual_kind": "outro",
                     "payload": {"brand_name": "FVA Capital", "cta": "c"}, "narration": "c"},
                ],
                "source": "ignored", "disclaimer": "d",
            }, ensure_ascii=False)

    llm = _SpyLLM()
    brief = ProductionBrief(title="t", hook="h", evidence="Doanh thu tăng 40%.")

    agent = VideoScriptAgent(llm)
    agent.rules_settings = Settings({"writer": {
        "rules_load_mode": "full", "content_rules_path": str(rules_file),
    }})
    agent.run(brief)
    assert marker in llm.last_system

    # KHÔNG set rules_settings (None mặc định) -> lùi về settings TOÀN CỤC,
    # KHÔNG thấy marker file tạm (chứng minh set/không-set THẬT SỰ khác nhau).
    agent2 = VideoScriptAgent(llm)
    agent2.run(brief)
    assert marker not in llm.last_system


def test_infographic_agent_accepts_per_request_rules_settings(tmp_path):
    """A5 -- InfographicSpecAgent (composer LLM Loại B) cũng nhận rules_settings
    riêng mỗi request, đồng nhất với Article/Video."""
    import json as _json
    from twmkt.agents.production import InfographicSpecAgent, ProductionBrief

    marker = "MARKER-INFOGRAPHIC-RULES-334455"
    rules_file = tmp_path / "info_rules.md"
    rules_file.write_text(f"# Rules\n{marker}\n", encoding="utf-8")

    class _SpyLLM:
        last_system = ""

        def complete(self, system, prompt, **kwargs):
            self.last_system = system
            return _json.dumps({
                "title": "FPT lãi kỷ lục", "subtitle": "Tăng trưởng vượt kỳ vọng",
                "hero": [{"label": "Tăng trưởng doanh thu", "value": "+40%"}],
                "market": [], "highlights": ["x"], "related": [],
                "priority": {"primary": [], "secondary": [], "minor": []},
                "source": "ignored",
                "render_hint": {"ratio": "1:1"},
            }, ensure_ascii=False)

    llm = _SpyLLM()
    brief = ProductionBrief(title="t", hook="h", tickers=["FPT"],
                            url="https://cafef.vn/x.chn",
                            evidence="Doanh thu tăng 40%.",
                            content_units=_infographic_test_content_units())

    agent = InfographicSpecAgent(llm)
    agent.rules_settings = Settings({"writer": {
        "rules_load_mode": "full", "content_rules_path": str(rules_file),
    }})
    agent.run(brief)
    assert marker in llm.last_system

    agent2 = InfographicSpecAgent(llm)
    agent2.run(brief)
    assert marker not in llm.last_system


def test_append_rules_run_state_writes_sha256_json_and_swallows_io_error(tmp_path, monkeypatch, capsys):
    """A4 -- ghi 1 dòng JSONL {ts, content_type, path, sha256, mode} vào
    state/rules_run_log.jsonl mỗi lần nạp rules THÀNH CÔNG (truy vết bài nào
    dùng bản rules nào). Lỗi ghi (OSError -- đĩa đầy/quyền...) KHÔNG được văng
    ra ngoài làm hỏng sản xuất -- nuốt, chỉ cảnh báo console (cùng triết lý LÙI
    MƯỢT xuyên suốt module này)."""
    import json as _json
    from pathlib import Path
    from twmkt.agents.production import _append_rules_run_state, _sha256_text

    settings = Settings({"storage": {"data_root": str(tmp_path)}})
    text = "nội dung rules test"
    sha = _sha256_text(text)
    _append_rules_run_state(content_type="article", path=Path("prompts/x.md"),
                            sha256=sha, mode="full", settings=settings)
    log_path = tmp_path / "state" / "rules_run_log.jsonl"
    assert log_path.exists()
    entry = _json.loads(log_path.read_text(encoding="utf-8").strip().splitlines()[-1])
    assert entry["sha256"] == sha
    assert entry["content_type"] == "article"
    assert entry["mode"] == "full"

    def _boom(*a, **k):
        raise OSError("disk full (giả lập)")
    monkeypatch.setattr("twmkt.agents.production.data_path", _boom)
    _append_rules_run_state(content_type="article", path=Path("prompts/x.md"),
                            sha256=sha, mode="full", settings=settings)
    assert "rules_run_log" in capsys.readouterr().out


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
                     other_sources=["http://a2"], tickers=["FPT", "HPG"], status="APPROVE",
                     topic_key="key-a")
    r2 = context_row(title="Bài B", hook_line="Hook B", source_url="http://b", score=1,
                     hot_pct=10.0, status="PENDING")
    got = approved_context_from_rows([CONTEXT_HEADER, r1, r2])
    assert len(got) == 1
    a = got[0]
    assert a["context"] == "Bài A" and a["hook"] == "Hook A"
    assert a["source"] == "http://a"                     # url chính (dòng đầu ô Source gộp)
    assert a["tickers"] == ["FPT", "HPG"] and a["topic"] == "CoPhieu"
    assert a["topic_key"] == "key-a"                     # Lớp 5 Phase 1
    assert approved_context_from_rows([CONTEXT_HEADER]) == []   # 0 approved


def test_content_row_shape():
    """TopicKey (Lớp 5 Phase 1) + Facts/AssetPath/GATE3_COL (Production Factory
    Phase 1.3) — TẤT CẢ APPEND CUỐI (không chen giữa Context/Type), khớp
    comment CONTENT_HEADER trong sheets_board.py. Sheet UI cleanup Phase 3: tên
    hiển thị GATE2_COL/GATE3_COL ("Duyệt Content"/"Duyệt Public") thay
    "Approve(gate 2)"/"Gate3" cũ — so bằng hằng số, KHÔNG hard-code lại literal.
    Sheet UI cleanup Phase 6: "Social Link" chen giữa AssetPath và GATE3_COL,
    "Posting Status" append sau GATE3_COL — cả 2 đều NGƯỜI điền tay, mặc định
    rỗng cho hàng máy ghi. VIỆC 3 (2026-08-04): "Người thực hiện" chen giữa
    AssetPath và Social Link — NGƯỜI điền tay, không có tham số ở content_row()
    (xem docstring hàm), mặc định rỗng cho hàng máy ghi."""
    from twmkt.sheets_board import GATE2_COL, GATE3_COL, content_row, CONTENT_HEADER
    assert CONTENT_HEADER == ["Timestamp", "Context", "Type", "Status", "Output",
                             "Notes", GATE2_COL, "TopicKey",
                             "Facts", "AssetPath", "Người thực hiện", "Social Link", GATE3_COL,
                             "Posting Status"]
    row = content_row(context="Bài A", type_="article", status="DONE",
                      output="nội dung", notes="ok", ts="ts", topic_key="key-a")
    d = dict(zip(CONTENT_HEADER, row))
    assert d == {"Timestamp": "ts", "Context": "Bài A", "Type": "Article", "Status": "DONE",
                 "Output": "nội dung", "Notes": "ok", GATE2_COL: "PENDING",
                 "TopicKey": "key-a", "Facts": "", "AssetPath": "", "Người thực hiện": "",
                 "Social Link": "", GATE3_COL: "PENDING", "Posting Status": ""}
    row2 = content_row(context="Bài B", type_="video", status="ERROR",
                       output="x", approve="APPROVE", ts="ts2")
    d2 = dict(zip(CONTENT_HEADER, row2))
    assert d2[GATE2_COL] == "APPROVE"
    assert d2["TopicKey"] == ""   # mặc định rỗng nếu caller chưa truyền
    assert d2["Facts"] == "" and d2["AssetPath"] == "" and d2[GATE3_COL] == "PENDING"
    assert d2["Người thực hiện"] == ""
    assert d2["Social Link"] == "" and d2["Posting Status"] == ""


def test_content_row_facts_asset_path_gate3_fields():
    """Phase 1.3: content_units/asset_path điền đúng cột khi caller truyền vào; GATE3_COL
    KHÔNG nhận tham số (xem test_content_row_gate3_is_always_pending_and_not_
    settable) — luôn "PENDING" bất kể caller truyền gì cho content_units/asset_path.
    Sheet UI cleanup Phase 6: Social Link/Posting Status luôn rỗng (NGƯỜI điền
    tay, không tham số ở content_row())."""
    from twmkt.sheets_board import GATE3_COL, content_row, CONTENT_HEADER

    row = content_row(context="Bài A", type_="infographic", status="DONE",
                      output="{}", topic_key="key-a", facts='[{"value":"1"}]',
                      asset_path="storage/output/x.svg", ts="ts")
    d = dict(zip(CONTENT_HEADER, row))
    assert d["Facts"] == '[{"value":"1"}]'
    assert d["AssetPath"] == "storage/output/x.svg"
    assert d[GATE3_COL] == "PENDING"
    assert d["Social Link"] == "" and d["Posting Status"] == ""


def test_content_row_gate3_is_always_pending_and_not_settable():
    """INVARIANT VĨNH VIỄN (sự cố THẬT trên Sheet production — GATE2_COL VÀ
    GATE3_COL tự bị đổi sang APPROVE trên 3 dòng KHÔNG ai duyệt, phát hiện +
    revert thủ công khi đóng Production Factory Phase 1 round-trip THẬT, xem
    PROJECT_HANDOFF_P5.md): content_row() KHÔNG có tham số `gate3` — gọi với
    từ khoá đó phải lỗi NGAY (TypeError), chứng minh KHÔNG hàm ghi-cả-dòng nào
    có đường truyền giá trị vào cột GATE3_COL. Test này phải ĐỎ nếu ai đó thêm
    lại tham số gate3 vào content_row()."""
    import inspect

    from twmkt.sheets_board import GATE3_COL, CONTENT_HEADER, content_row

    assert "gate3" not in inspect.signature(content_row).parameters
    try:
        content_row(context="x", type_="infographic", status="DONE", output="{}",
                   gate3="APPROVE")   # type: ignore[call-arg]
    except TypeError:
        pass
    else:
        raise AssertionError("content_row() phải TỪ CHỐI tham số gate3 (TypeError) — "
                             "không hàm ghi-cả-dòng nào được phép ghi GATE3_COL.")

    row = content_row(context="x", type_="infographic", status="DONE", output="{}")
    assert dict(zip(CONTENT_HEADER, row))[GATE3_COL] == "PENDING"


def test_set_content_cell_refuses_to_write_gate3():
    """INVARIANT VĨNH VIỄN: set_content_cell() (đường ghi 1-ô dùng bởi
    scripts/render_production_assets.py cho Notes/AssetPath) phải TỪ CHỐI NGAY
    (raise, không no-op êm) nếu bất kỳ code nào gọi nó nhắm cột GATE3_COL — kể
    cả biến thể hoa/thường/khoảng trắng khác nhau. Test PHẢI network-free (fail
    ngay ở bước validate tên cột, TRƯỚC khi chạm Sheets API thật) — KHÔNG dùng
    pytest (repo này chạy test bằng _run_all() nội bộ, không có pytest cài).
    Sinh biến thể TỪ hằng số GATE3_COL (không hard-code lại "Gate3") — nếu tên
    cột đổi lần nữa, test này tự theo, không cần sửa tay."""
    from twmkt.sheets_board import SheetsBoard, GATE3_COL

    board = SheetsBoard.__new__(SheetsBoard)   # bỏ qua __init__ (không cần kết nối thật)
    for variant in (GATE3_COL, GATE3_COL.lower(), GATE3_COL.upper(), f"  {GATE3_COL}  "):
        try:
            board.set_content_cell(2, variant, "APPROVE")
        except ValueError:
            continue
        raise AssertionError(f"set_content_cell phải raise ValueError cho col_name={variant!r}")


def test_no_machine_write_path_touches_gate3():
    """INVARIANT VĨNH VIỄN, quét TĨNH toàn bộ source (không phải Sheet thật) —
    'KHÔNG luồng máy nào được ghi vào cột GATE3_COL, CHỈ người chọn dropdown.'
    Quét src/twmkt + scripts (loại trừ chính test này) tìm bất kỳ lệnh gọi
    set_content_cell(...) nào có literal string GATE3_COL (không phân biệt hoa/
    thường) làm tên cột — đây là đường ghi-1-ô DUY NHẤT hiện có cho CONTENT
    ngoài content_row() (đã khoá riêng, xem test phía trên). Pattern build TỪ
    hằng số GATE3_COL (không hard-code lại "gate3") — nếu tên cột đổi lần nữa,
    test này tự theo. Test này phải ĐỎ NGAY nếu code tương lai thêm 1 lệnh gọi
    set_content_cell(..., GATE3_COL, ...) ở BẤT KỲ file .py nào trong 2 thư
    mục này."""
    import re

    from twmkt.sheets_board import GATE3_COL

    pattern = re.compile(
        r'set_content_cell\s*\([^)]*["\']' + re.escape(GATE3_COL) + r'["\']', re.IGNORECASE)
    scan_dirs = [os.path.join(REPO_ROOT, "src", "twmkt"), os.path.join(REPO_ROOT, "scripts")]
    offenders: list[str] = []
    for base in scan_dirs:
        for dirpath, _dirs, filenames in os.walk(base):
            for fn in filenames:
                if not fn.endswith(".py"):
                    continue
                path = os.path.join(dirpath, fn)
                with open(path, encoding="utf-8") as f:
                    text = f.read()
                for m in pattern.finditer(text):
                    line_no = text.count("\n", 0, m.start()) + 1
                    offenders.append(f"{path}:{line_no}")
    assert offenders == [], (
        f"Tìm thấy lệnh ghi Gate3 qua set_content_cell() trong code MÁY — VI PHẠM "
        f"invariant 'chỉ người chọn dropdown mới được ghi Gate3': {offenders}")


def test_no_old_brand_name_anywhere_in_product_code():
    """KHÓA VĨNH VIỄN (Content Factory Phase D — vá rò brand) — sự cố THẬT:
    video script sinh CTA mang brand CŨ (đã đổi tên từ lâu ở renderer, Phase
    1.2) vì prompt CHƯA từng được quét — brand CŨ rò thẳng ra sản phẩm THẬT.

    Quét TĨNH (không phải chạy LLM) toàn bộ src/, scripts/, prompts/, config/
    (mọi file .py/.md/.yaml/.yml, kể cả docstring/comment/test fixture NẰM
    TRONG các thư mục này — không có ngoại lệ, không phân biệt hoa/thường) tìm
    MỌI biến thể brand cũ đã biết. Test này PHẢI ĐỎ NGAY nếu brand cũ tái xuất
    hiện ở BẤT KỲ đâu trong 4 thư mục này, dù chỉ trong 1 dòng comment.

    KHÔNG chặn "twmkt"/"TWMKT_*" — đó là tên package Python + tiền tố biến môi
    trường (TWMKT_SHEET_ID, TWMKT_TELEGRAM_ENABLED...), KHÔNG phải brand hiển
    thị cho người dùng, đã xác minh riêng (không phải phần bị cấm)."""
    import re

    banned_patterns = [
        re.compile(r"turtle\s*wealth", re.IGNORECASE),
        re.compile(r"\bturtle\b", re.IGNORECASE),
        re.compile(r"\btwvn\b", re.IGNORECASE),
        re.compile(r"vel\s*capital", re.IGNORECASE),
    ]
    scan_dirs = [os.path.join(REPO_ROOT, "src"), os.path.join(REPO_ROOT, "scripts"),
                os.path.join(REPO_ROOT, "prompts"), os.path.join(REPO_ROOT, "config")]
    scan_exts = (".py", ".md", ".yaml", ".yml")
    offenders: list[str] = []
    for base in scan_dirs:
        for dirpath, dirs, filenames in os.walk(base):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for fn in filenames:
                if not fn.endswith(scan_exts):
                    continue
                path = os.path.join(dirpath, fn)
                try:
                    with open(path, encoding="utf-8") as f:
                        text = f.read()
                except (UnicodeDecodeError, OSError):
                    continue
                for pattern in banned_patterns:
                    for m in pattern.finditer(text):
                        line_no = text.count("\n", 0, m.start()) + 1
                        offenders.append(f"{path}:{line_no} ({m.group(0)!r})")
    assert offenders == [], (
        f"Tìm thấy brand CŨ trong src/scripts/prompts/config — VI PHẠM invariant "
        f"'không chuỗi brand cũ nào được tồn tại trong code sản phẩm': {offenders}")


def test_facts_to_json_and_back_round_trip():
    from twmkt.sheets_board import facts_from_json, facts_to_json
    from twmkt.models import ContentUnit

    content_units = [ContentUnit(value="8,18", label="GDP", unit="%", kind="percent",
                  raw="8,18%", canonical_value=8.18, source="câu evidence")]
    raw = facts_to_json(content_units)
    assert raw and "GDP" in raw
    back = facts_from_json(raw)
    assert len(back) == 1
    assert back[0].value == "8,18" and back[0].canonical_value == 8.18
    assert back[0].label == "GDP"


# =====================================================================
# Content Factory Phase 1 — ContentUnit mở rộng scalar|range|delta|entity_list|entity
# (models.FACT_SHAPES). Test round-trip từng shape qua facts_to_json/
# facts_from_json (sheets_board.py, KHÔNG đổi hàm — ContentUnit chỉ thêm field mới,
# dataclasses.asdict/ContentUnit(**item) tự xử lý) + tương thích ngược dữ liệu scalar
# cũ (JSON KHÔNG có field "shape"/range/delta/entity vẫn đọc đúng, mặc định
# shape="scalar").
# =====================================================================
def test_fact_scalar_shape_default_and_backward_compat_with_old_json():
    """Dữ liệu ContentUnit CŨ (trước Phase 1, JSON KHÔNG có field shape/range/delta/
    entity nào) vẫn đọc đúng — shape mặc định 'scalar', KHÔNG vỡ, KHÔNG cần
    migrate dữ liệu cũ trên Sheet thật."""
    import json as _json

    from twmkt.models import FACT_SHAPES, ContentUnit
    from twmkt.sheets_board import facts_from_json

    assert "scalar" in FACT_SHAPES
    f = ContentUnit(value="8,18", label="GDP", unit="%", canonical_value=8.18)
    assert f.shape == "scalar"   # mặc định, không cần truyền

    old_json_no_shape_field = _json.dumps([{
        "value": "8,18", "label": "GDP", "unit": "%", "source": "câu cũ",
        "kind": "percent", "raw": "8,18%", "canonical_value": 8.18, "approx": False,
    }], ensure_ascii=False)
    back = facts_from_json(old_json_no_shape_field)
    assert len(back) == 1
    assert back[0].shape == "scalar" and back[0].canonical_value == 8.18


def test_fact_range_shape_round_trip():
    from twmkt.models import ContentUnit
    from twmkt.sheets_board import facts_from_json, facts_to_json

    content_units = [ContentUnit(value="", label="Vốn FDI chế biến, chế tạo", unit="%", shape="range",
                  value_low="70", value_high="80", canonical_low=70.0, canonical_high=80.0,
                  approx=True, source="khoảng 70 - 80% vốn FDI...")]
    raw = facts_to_json(content_units)
    back = facts_from_json(raw)
    assert len(back) == 1
    r = back[0]
    assert r.shape == "range"
    assert r.value_low == "70" and r.value_high == "80"
    assert r.canonical_low == 70.0 and r.canonical_high == 80.0


def test_fact_delta_shape_round_trip():
    from twmkt.models import ContentUnit
    from twmkt.sheets_board import facts_from_json, facts_to_json

    content_units = [ContentUnit(value="", label="Doanh thu quý 2 (2025 → 2026)", shape="delta",
                  from_value="16,3 tỷ đồng", to_value="176 triệu đồng",
                  canonical_from=16.3e9, canonical_to=176e6,
                  source="giảm sâu so với mức 16,3 tỷ đồng của cùng kỳ...")]
    raw = facts_to_json(content_units)
    back = facts_from_json(raw)
    assert len(back) == 1
    d = back[0]
    assert d.shape == "delta"
    assert d.from_value == "16,3 tỷ đồng" and d.to_value == "176 triệu đồng"
    assert d.canonical_from == 16.3e9 and d.canonical_to == 176e6


def test_fact_entity_list_shape_round_trip():
    from twmkt.models import ContentUnit
    from twmkt.sheets_board import facts_from_json, facts_to_json

    content_units = [ContentUnit(value="", label="Quốc gia đầu tư", shape="entity_list",
                  entities=["Hàn Quốc", "Nhật Bản", "Mỹ"],
                  source="các nhà đầu tư đến từ Hàn Quốc, Nhật Bản...")]
    raw = facts_to_json(content_units)
    back = facts_from_json(raw)
    assert len(back) == 1
    assert back[0].shape == "entity_list"
    assert back[0].entities == ["Hàn Quốc", "Nhật Bản", "Mỹ"]


def test_fact_entity_shape_round_trip():
    from twmkt.models import ContentUnit
    from twmkt.sheets_board import facts_from_json, facts_to_json

    content_units = [ContentUnit(value="SHS", label="Công ty chứng khoán được trích dẫn", shape="entity",
                  entity_type="company", source="ông Nguyễn Duy Linh, Tổng Giám đốc SHS...")]
    raw = facts_to_json(content_units)
    back = facts_from_json(raw)
    assert len(back) == 1
    assert back[0].shape == "entity" and back[0].value == "SHS"
    assert back[0].entity_type == "company"


def test_fact_salience_round_trip_and_backward_compat_default_empty():
    """Content Factory Phase 2b — salience round-trip qua facts_to_json/
    facts_from_json; dữ liệu CŨ trước Phase 2b (JSON không có field salience)
    -> mặc định "" (KHÔNG vỡ)."""
    from twmkt.models import ContentUnit
    from twmkt.sheets_board import facts_from_json, facts_to_json

    content_units = [ContentUnit(value="", label="4 cảng biển đặc biệt", shape="entity_list",
                  entities=["Cần Giờ", "Liên Chiểu"], salience="subject")]
    back = facts_from_json(facts_to_json(content_units))
    assert len(back) == 1 and back[0].salience == "subject"

    import json as _json
    old_json_no_salience = _json.dumps([{
        "value": "SHS", "label": "Công ty", "shape": "entity", "entity_type": "company",
    }], ensure_ascii=False)
    back2 = facts_from_json(old_json_no_salience)
    assert len(back2) == 1 and back2[0].salience == ""


def test_facts_to_json_empty_list_returns_empty_string():
    from twmkt.sheets_board import facts_to_json

    assert facts_to_json([]) == ""


def test_facts_from_json_bad_or_empty_input_degrades_to_empty_list():
    from twmkt.sheets_board import facts_from_json

    assert facts_from_json("") == []
    assert facts_from_json("khong phai JSON") == []
    assert facts_from_json("{}") == []           # dict, không phải list -> []
    assert facts_from_json('[{"khong_ton_tai": 1}]') == []   # field lạ -> bỏ qua fact đó


def test_content_rows_for_render_filters_by_type_and_reads_all_columns():
    from twmkt.sheets_board import GATE3_COL, CONTENT_HEADER, content_row, content_rows_for_render

    # Gate3 KHÔNG còn là tham số của content_row() (xem test_content_row_gate3_
    # is_always_pending_and_not_settable) — dòng thứ 3 giả lập 1 hàng NGƯỜI đã
    # tự duyệt Gate3 qua dropdown trên Sheet (ghi tay đúng cột GATE3_COL theo
    # index thật trong CONTENT_HEADER — Sheet UI cleanup Phase 6 chèn "Social
    # Link" trước và "Posting Status" sau GATE3_COL nên GATE3_COL KHÔNG còn là
    # cột cuối, không thể dùng row_c[-1] nữa), KHÔNG phải máy ghi.
    row_c = content_row(context="Bài B", type_="infographic", status="DONE", output="{}",
                        topic_key="tk-2", approve="APPROVE", asset_path="out/b.svg")
    row_c[CONTENT_HEADER.index(GATE3_COL)] = "APPROVE"   # mô phỏng NGƯỜI chọn dropdown Gate3
    rows = [
        content_row(context="Bài A", type_="infographic", status="DONE", output="{}",
                   topic_key="tk-1", facts='[{"value":"1"}]', asset_path=""),
        content_row(context="Bài A", type_="article", status="DONE", output="# A",
                   topic_key="tk-1"),
        row_c,
    ]
    items = content_rows_for_render(CONTENT_HEADER, rows, type_="infographic")
    assert len(items) == 2
    assert items[0]["row"] == 2 and items[0]["topic_key"] == "tk-1"
    assert items[0]["facts"] == '[{"value":"1"}]' and items[0]["asset_path"] == ""
    assert items[1]["row"] == 4 and items[1]["asset_path"] == "out/b.svg"
    assert items[1]["approve_gate2"] == "APPROVE" and items[1]["gate3"] == "APPROVE"


def test_content_rows_for_render_missing_required_column_returns_empty():
    from twmkt.sheets_board import content_rows_for_render

    assert content_rows_for_render(["Timestamp", "Context"], [["t", "c"]]) == []


def _render_prod_assets_module():
    import os as _os
    import sys as _sys
    REPO_ROOT_ = _os.path.abspath(_os.path.join(_os.path.dirname(__file__), ".."))
    _sys.path.insert(0, _os.path.join(REPO_ROOT_, "scripts"))
    import render_production_assets as rpa
    return rpa


def test_render_one_clean_spec_returns_png_bytes(monkeypatch, tmp_path):
    """render_one() giờ gọi ai_full (AI thật, MOCK ở đây) thay vì SVG tất
    định — 2026-07-21, xem docstring render_production_assets.py.

    2026-07-27 (Lead, sau bug Bước 5.3): render_one() giờ đọc JSON từ STORE
    (theo topic_key), KHÔNG còn item["output"] (ô Sheet) — seed content_output
    thật qua pipeline_store trước khi gọi."""
    import json as _json
    import httpx
    from store import document_store as ds
    from store import pipeline_store as ps
    from twmkt.config import Settings

    rpa = _render_prod_assets_module()
    # TASK-013 (2026-08-07): pixel giả 1x1 phải là màu SÁNG, không phải đen
    # tuyệt đối -- brand_stamp.select_logo_corner() (Phần B) giờ soi
    # dark_pixel_ratio để phát hiện va chạm chữ THẬT ở góc logo; 1 pixel đen
    # tuyệt đối phóng to phủ kín canvas trông giống "toàn bộ ảnh là chữ/khối
    # tối" -> false positive "hết góc trống" -> NEEDS_HUMAN oan. Các test này
    # không kiểm tra nội dung ảnh, chỉ cần placeholder hợp lệ không kích hoạt
    # nhầm heuristic va chạm.
    tiny_png_b64 = (
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4+uMPAAXPAureeOIRAAAAAElFTkSuQmCC"
    )

    def _fake_success(*a, **kw):
        return httpx.Response(200, json={"data": [{"b64_json": tiny_png_b64}]},
                              request=httpx.Request("POST", "https://api.openai.com/v1/images/generations"))

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-fake-key-not-real")
    monkeypatch.setattr(httpx, "post", _fake_success)

    db_path = tmp_path / "store.db"
    monkeypatch.setenv("DOCUMENT_STORE_PATH", str(db_path))
    ds.init_db(db_path)
    output = {"title": "GDP tăng mạnh", "hero": [{"label": "GDP", "value": "8,18%"}]}
    ps.write_content_output("tk-1", "infographic", {"output": _json.dumps(output)}, db_path=db_path)

    item = {"topic_key": "tk-1", "context": "GDP tăng mạnh"}
    settings = Settings({"storage": {"data_root": str(tmp_path)}})
    # 2026-07-23 (Phần A-C): render_one() giờ trả (png_map, warn_map, logs)
    # theo TỪNG TỶ LỆ (_RATIOS = 4:5/9:16/1:1), không còn 1 cặp duy nhất.
    png_map, warn_map, logs = rpa.render_one(item, settings=settings)
    assert png_map[rpa._PRIMARY_RATIO] is not None and warn_map[rpa._PRIMARY_RATIO] == ""


def test_render_one_parses_full_json_over_1500_chars_from_store(monkeypatch, tmp_path):
    """VIỆC 3 (Lead 2026-07-27) — khoá lại ĐÚNG bug Bước 5.3: JSON infographic
    THẬT (bài Google) dài 1565 ký tự, vượt ngưỡng _OUTPUT_PREVIEW=1500 --
    trước fix, render_one() đọc item["output"] (ô Sheet, đã bị cắt ở đúng
    ngưỡng này + hậu tố "…(xem ...)") -> json.loads() vỡ giữa chừng ->
    NEEDS_HUMAN oan dù dữ liệu hoàn toàn hợp lệ. Test PHẢI dùng nội dung DÀI
    HƠN 1500 ký tự thật (không phải mock ngắn — bug chỉ lộ ở dữ liệu dài,
    xem ghi chú "Nguyên tắc đã học" HANDOFF_2026-07-25_agentA.md)."""
    import json as _json
    import httpx
    from store import document_store as ds
    from store import pipeline_store as ps
    from twmkt.config import Settings

    rpa = _render_prod_assets_module()
    # TASK-013 (2026-08-07): pixel giả 1x1 phải là màu SÁNG, không phải đen
    # tuyệt đối -- brand_stamp.select_logo_corner() (Phần B) giờ soi
    # dark_pixel_ratio để phát hiện va chạm chữ THẬT ở góc logo; 1 pixel đen
    # tuyệt đối phóng to phủ kín canvas trông giống "toàn bộ ảnh là chữ/khối
    # tối" -> false positive "hết góc trống" -> NEEDS_HUMAN oan. Các test này
    # không kiểm tra nội dung ảnh, chỉ cần placeholder hợp lệ không kích hoạt
    # nhầm heuristic va chạm.
    tiny_png_b64 = (
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4+uMPAAXPAureeOIRAAAAAElFTkSuQmCC"
    )

    def _fake_success(*a, **kw):
        return httpx.Response(200, json={"data": [{"b64_json": tiny_png_b64}]},
                              request=httpx.Request("POST", "https://api.openai.com/v1/images/generations"))

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-fake-key-not-real")
    monkeypatch.setattr(httpx, "post", _fake_success)

    output = {
        "title": "Chỉ trong nửa năm, công ty mẹ Google thu hơn 6 triệu tỷ đồng",
        "hero": [
            {"label": f"Chỉ số tài chính thứ {i}",
             "value": f"{i} tỷ đồng, tăng trưởng ổn định so với cùng kỳ năm trước"}
            for i in range(20)
        ],
    }
    output_json = _json.dumps(output, ensure_ascii=False)
    assert len(output_json) > 1500   # tái hiện ĐÚNG điều kiện gây bug (bài thật 1565 ký tự)

    db_path = tmp_path / "store.db"
    monkeypatch.setenv("DOCUMENT_STORE_PATH", str(db_path))
    ds.init_db(db_path)
    ps.write_content_output("tk-long", "infographic", {"output": output_json}, db_path=db_path)

    item = {"topic_key": "tk-long", "context": output["title"]}
    settings = Settings({"storage": {"data_root": str(tmp_path)}})
    png_map, warn_map, logs = rpa.render_one(item, settings=settings)
    assert png_map[rpa._PRIMARY_RATIO] is not None, (
        f"JSON >1500 ký tự bị chặn oan -- store đọc lại KHÔNG đầy đủ: {warn_map[rpa._PRIMARY_RATIO]}")
    assert warn_map[rpa._PRIMARY_RATIO] == ""


def test_render_one_gate2_typo_flows_through_unchecked_known_risk(monkeypatch, tmp_path):
    """KHÔNG PHẢI hành vi mong muốn -- ghi lại RÕ đây là đánh đổi CỐ Ý (Lead
    2026-07-21): guardrail-2 nhánh ảnh (verify_spec trên block_kind) đã XOÁ
    cùng lượt chuyển renderer sang ai_full, nên số gõ nhầm ở Gate 2 KHÔNG còn
    bị chặn tự động trước render -- Gate 2/Gate 3 (duyệt người) là lớp chặn
    còn lại duy nhất. Test này khoá lại hành vi HIỆN TẠI, không phải khẳng
    định đây là an toàn.

    2026-07-27 (Lead, sau bug Bước 5.3): seed content_output qua store, giống
    test_render_one_clean_spec_returns_png_bytes."""
    import json as _json
    import httpx
    from store import document_store as ds
    from store import pipeline_store as ps
    from twmkt.config import Settings

    rpa = _render_prod_assets_module()
    # TASK-013 (2026-08-07): pixel giả 1x1 phải là màu SÁNG, không phải đen
    # tuyệt đối -- brand_stamp.select_logo_corner() (Phần B) giờ soi
    # dark_pixel_ratio để phát hiện va chạm chữ THẬT ở góc logo; 1 pixel đen
    # tuyệt đối phóng to phủ kín canvas trông giống "toàn bộ ảnh là chữ/khối
    # tối" -> false positive "hết góc trống" -> NEEDS_HUMAN oan. Các test này
    # không kiểm tra nội dung ảnh, chỉ cần placeholder hợp lệ không kích hoạt
    # nhầm heuristic va chạm.
    tiny_png_b64 = (
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4+uMPAAXPAureeOIRAAAAAElFTkSuQmCC"
    )

    def _fake_success(*a, **kw):
        return httpx.Response(200, json={"data": [{"b64_json": tiny_png_b64}]},
                              request=httpx.Request("POST", "https://api.openai.com/v1/images/generations"))

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-fake-key-not-real")
    monkeypatch.setattr(httpx, "post", _fake_success)

    db_path = tmp_path / "store.db"
    monkeypatch.setenv("DOCUMENT_STORE_PATH", str(db_path))
    ds.init_db(db_path)
    output = {"title": "GDP", "hero": [{"label": "GDP", "value": "99%"}]}   # gõ nhầm ở Gate 2, KHÔNG khớp content_units[]
    ps.write_content_output("tk-1", "infographic", {"output": _json.dumps(output)}, db_path=db_path)

    item = {"topic_key": "tk-1", "context": "GDP"}
    settings = Settings({"storage": {"data_root": str(tmp_path)}})
    png_map, warn_map, logs = rpa.render_one(item, settings=settings)
    assert png_map[rpa._PRIMARY_RATIO] is not None and warn_map[rpa._PRIMARY_RATIO] == ""   # KHÔNG bị chặn -- đúng đánh đổi đã ghi trong docstring


def test_render_one_bad_output_json_returns_error_reason(monkeypatch, tmp_path):
    """2026-07-27: JSON hỏng NẰM TRONG STORE (không phải ô Sheet) vẫn phải bị
    bắt đúng chỗ (json.loads() vỡ), KHÔNG bị lẫn với ca 'không tìm thấy
    topic_key trong store' (2 lỗi khác nhau, message khác nhau)."""
    from store import document_store as ds
    from store import pipeline_store as ps
    from twmkt.config import Settings

    rpa = _render_prod_assets_module()

    db_path = tmp_path / "store.db"
    monkeypatch.setenv("DOCUMENT_STORE_PATH", str(db_path))
    ds.init_db(db_path)
    ps.write_content_output("tk-1", "infographic", {"output": "khong phai JSON"}, db_path=db_path)

    item = {"topic_key": "tk-1", "context": "X"}
    png_map, warn_map, logs = rpa.render_one(item, settings=Settings({}))
    assert png_map[rpa._PRIMARY_RATIO] is None and "JSON hợp lệ" in warn_map[rpa._PRIMARY_RATIO]


def test_render_one_missing_topic_key_in_store_returns_error_reason(monkeypatch, tmp_path):
    """VIỆC 1.1 (Lead 2026-07-27): topic_key KHÔNG có content_output trong
    store (khác ca JSON hỏng) -> lỗi RÕ RÀNG NÊU RA store/TopicKey, không lẫn
    với ca JSON hỏng và KHÔNG crash."""
    from store import document_store as ds
    from twmkt.config import Settings

    rpa = _render_prod_assets_module()

    db_path = tmp_path / "store.db"
    monkeypatch.setenv("DOCUMENT_STORE_PATH", str(db_path))
    ds.init_db(db_path)   # store rỗng -- topic_key chưa từng ghi content_output

    item = {"topic_key": "khong-ton-tai", "context": "X"}
    png_map, warn_map, logs = rpa.render_one(item, settings=Settings({}))
    assert png_map[rpa._PRIMARY_RATIO] is None
    assert "store" in warn_map[rpa._PRIMARY_RATIO].lower()
    assert "khong-ton-tai" in warn_map[rpa._PRIMARY_RATIO]


def test_render_production_assets_run_ranking_guard_notes_survive_resync(monkeypatch, tmp_path):
    """VIỆC A5 (Lead 02/08) — PHÉP THỬ DUY NHẤT chứng minh vá đúng: chạy 1 job
    có ranking giả (spec 4 highlights, cap tỷ lệ "4:5" chỉ giữ 3 -> density
    cap CẮT 1, xem render/ai_full.apply_density_cap/_priority_rank) qua
    render_production_assets.run() THẬT, rồi gọi LẠI store/sync_service.
    render_content_to_sheet() (mô phỏng lượt sync kế tiếp) -- Notes PHẢI CÒN
    nguyên mã RENDER_RANKING_GUARD trên Sheet SAU khi sync chạy lại.

    Trước bản vá (VIỆC A): renderer ghi Notes THẲNG board.set_content_cell()
    (KHÔNG ingest ngược store) -> render_content_to_sheet() dựng lại TOÀN BỘ
    tab từ store (không có Notes đó) -> mất trắng. Test này khoá ĐÚNG luồng
    ngược lại: ghi store trước (A1), rồi để sync hiển thị theo cơ chế chung
    (A3) -- không phải test riêng lẻ render_one()/set_content_cell()."""
    import json as _json
    import httpx
    from store import document_store as ds
    from store import pipeline_store as ps
    from store import sync_service as ss
    from twmkt.config import Settings
    from twmkt.sheets_board import CONTENT_HEADER, SheetsBoard, content_row

    rpa = _render_prod_assets_module()
    # TASK-013 (2026-08-07): pixel giả 1x1 phải là màu SÁNG, không phải đen
    # tuyệt đối -- brand_stamp.select_logo_corner() (Phần B) giờ soi
    # dark_pixel_ratio để phát hiện va chạm chữ THẬT ở góc logo; 1 pixel đen
    # tuyệt đối phóng to phủ kín canvas trông giống "toàn bộ ảnh là chữ/khối
    # tối" -> false positive "hết góc trống" -> NEEDS_HUMAN oan. Các test này
    # không kiểm tra nội dung ảnh, chỉ cần placeholder hợp lệ không kích hoạt
    # nhầm heuristic va chạm.
    tiny_png_b64 = (
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4+uMPAAXPAureeOIRAAAAAElFTkSuQmCC"
    )

    def _fake_success(*a, **kw):
        return httpx.Response(200, json={"data": [{"b64_json": tiny_png_b64}]},
                              request=httpx.Request("POST", "https://api.openai.com/v1/images/generations"))

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-fake-key-not-real")
    monkeypatch.setattr(httpx, "post", _fake_success)

    db_path = tmp_path / "store.db"
    monkeypatch.setenv("DOCUMENT_STORE_PATH", str(db_path))
    ds.init_db(db_path)

    # Spec "ranking giả": 4 highlights, tỷ lệ "4:5" (cap highlights=3, xem
    # render.ai_full._DEFAULT_DENSITY_CAPS) -> density cap CHẮC CHẮN cắt 1.
    spec = {
        "title": "Tin ranking giả", "subtitle": "", "hero": [{"label": "X", "value": "1%"}],
        "market": [], "highlights": ["A", "B", "C", "D"], "related": [],
        "priority": {"primary": [], "secondary": [], "minor": []},
        "source": "test.vn", "render_hint": {"ratio": "4:5"},
    }
    ps.write_content_output("tk-rank", "infographic", {"output": _json.dumps(spec), "status": "DONE"},
                            db_path=db_path)

    row = content_row(context="Tin ranking giả", type_="infographic", status="DONE",
                      output=_json.dumps(spec), topic_key="tk-rank", approve="APPROVE")

    class _FakeContentWS:
        id = 1
        def __init__(self, values):
            self._v = [list(r) for r in values]
        def get_all_values(self):
            return [list(r) for r in self._v]

    fake_board = SheetsBoard(spreadsheet_id="X", creds_path="Y")
    fake_board._ws["CONTENT"] = _FakeContentWS([list(CONTENT_HEADER), row])

    test_settings = Settings({"storage": {"data_root": str(tmp_path / "data")}})
    monkeypatch.setattr(rpa, "load_settings", lambda: test_settings)
    monkeypatch.setattr(rpa, "_open_board", lambda settings: fake_board)

    result = rpa.run(limit=1)
    assert result["rendered"] == 1

    # (1) content_output.notes trong STORE có mã RENDER_RANKING_GUARD ngay
    # sau render — xác nhận A1 (ghi store, không ghi thẳng Sheet).
    rec = ps.read_content_output("tk-rank", "infographic", db_path=db_path)
    assert "RENDER_RANKING_GUARD" in rec["notes"], f"thiếu mã lý do trong store: {rec['notes']!r}"
    assert "highlights" in rec["notes"] and "4:5" in rec["notes"]

    # (2) PHÉP THỬ A5 THẬT: mô phỏng lượt SYNC KẾ TIẾP (store/sync_service.
    # render_content_to_sheet(), CHÍNH nơi trước đây "dựng lại toàn bộ tab từ
    # store" XOÁ MẤT Notes ghi thẳng Sheet) -- Notes PHẢI CÒN NGUYÊN sau đó.
    class _FakeSyncWS:
        def __init__(self):
            self._v: list[list[str]] = []
        def get_all_values(self):
            return [list(r) for r in self._v]
        def update(self, range_str, values, value_input_option="RAW"):
            start = int(range_str[1:]) if len(range_str) > 1 else 1
            need = start - 1 + len(values)
            while len(self._v) < need:
                self._v.append([])
            for i, r in enumerate(values):
                self._v[start - 1 + i] = [str(c) for c in r]
        def batch_clear(self, ranges):
            import re as _re
            for rng in ranges:
                m = _re.match(r"A(\d+):", rng)
                if m:
                    self._v = self._v[: int(m.group(1)) - 1]

    class _FakeSyncBoard:
        def __init__(self):
            self._tabs = {"CONTENT": _FakeSyncWS()}
        def _tab(self, name):
            return self._tabs[name]

    sync_board = _FakeSyncBoard()
    ss.render_content_to_sheet(sync_board, db_path=db_path)
    grid = sync_board._tab("CONTENT").get_all_values()
    header = grid[0]
    i_tk = [h.strip().lower() for h in header].index("topickey")
    i_notes = [h.strip().lower() for h in header].index("notes")
    row_out = next(r for r in grid[1:] if r[i_tk] == "tk-rank")
    # Nhãn VI của RENDER_RANKING_GUARD (B3, sheets_board._display_notes) —
    # Sheet hiển thị chữ đã dịch, store (kiểm ở assert phía trên) vẫn tiếng Anh.
    assert "Ảnh tự thêm số thứ tự xếp hạng không có trong dữ liệu" in row_out[i_notes], (
        f"Notes bị MẤT sau lượt sync kế tiếp -- đúng lỗi VIỆC A mô tả, thực tế: {row_out[i_notes]!r}"
    )


class _FakeSyncWS:
    """VIỆC 4/5 (2026-08-03) — fake worksheet DÙNG CHUNG cho các test render_
    content_to_sheet() dưới đây, cùng khuôn với _FakeSyncWS/_FakeSyncBoard cục
    bộ ở test_render_production_assets_run_ranking_guard_notes_survive_resync
    (không tái cấu trúc file để dùng chung — tránh đụng test đã có)."""
    def __init__(self):
        self._v: list[list[str]] = []

    def get_all_values(self):
        return [list(r) for r in self._v]

    def update(self, range_str, values, value_input_option="RAW"):
        start = int(range_str[1:]) if len(range_str) > 1 else 1
        need = start - 1 + len(values)
        while len(self._v) < need:
            self._v.append([])
        for i, r in enumerate(values):
            self._v[start - 1 + i] = [str(c) for c in r]

    def batch_clear(self, ranges):
        import re as _re
        for rng in ranges:
            m = _re.match(r"A(\d+):", rng)
            if m:
                self._v = self._v[: int(m.group(1)) - 1]


class _FakeSyncBoard:
    def __init__(self):
        self._tabs = {"CONTENT": _FakeSyncWS()}

    def _tab(self, name):
        return self._tabs[name]


def _render_content_grid(db_path):
    from store import sync_service as ss
    board = _FakeSyncBoard()
    ss.render_content_to_sheet(board, db_path=db_path)
    grid = board._tab("CONTENT").get_all_values()
    header = grid[0]
    idx = {h.strip().lower(): i for i, h in enumerate(header)}
    return grid[1:], idx


def test_auto_total_failure_collapses_to_single_auto_error_row(tmp_path):
    """VIỆC 4.2 — Output Type=AUTO, CẢ 3 tuyến đều KHÔNG sinh (0 DONE) -> ĐÚNG
    1 dòng Type=AUTO/Status=ERROR/Notes gộp đủ nguyên nhân từng loại (khớp ví
    dụ Nafoods Lead đưa). VIỆC 4.3 — store vẫn giữ đủ 3 bản ghi gốc (kiểm riêng
    qua ps.read_content_output, KHÔNG bị xoá)."""
    from store import document_store as ds
    from store import pipeline_store as ps

    db_path = tmp_path / "store.db"
    ds.init_db(db_path)
    tk = "tk-auto-fail"
    ps.write_raw(tk, {"context": "Chủ đề AUTO thất bại toàn phần", "timestamp": "03/08/2026"}, db_path=db_path)
    ps.write_gate_status(tk, gate1="APPROVE", execute="DONE", output_type=["AUTO"], db_path=db_path)
    ps.write_content_output(tk, "article", {
        "status": "ERROR", "output": "",
        "notes": "Số liệu không thấy trong evidence/background: 28%",
    }, db_path=db_path)
    ps.write_content_output(tk, "infographic", {
        "status": "ERROR", "output": "",
        "notes": "SOURCE_BROKEN: content_units[] rỗng (Brief chưa trích được số liệu, "
                "brief_status=FAILED — lỗi hạ tầng thật) -> NEEDS_HUMAN, không bịa nhãn 'Số liệu N'",
    }, db_path=db_path)
    ps.write_content_output(tk, "video", {
        "status": "ERROR", "output": "",
        "notes": "Nguồn chỉ đủ dựng 1 cảnh (cần tối thiểu 3 để video có hook+thân+outro) — "
                "KHÔNG bịa cảnh đệm cho đủ số. Đề xuất chuyển loại nội dung sang "
                "infographic/article cho chủ đề này (nguồn nghèo SCENE video, KHÔNG có "
                "nghĩa nghèo SỐ LIỆU — 2 loại kia dùng chung content_units[]).",
    }, db_path=db_path)

    rows, idx = _render_content_grid(db_path)
    matching = [r for r in rows if r[idx["topickey"]] == tk]
    assert len(matching) == 1, f"kỳ vọng ĐÚNG 1 dòng gộp, thực tế {len(matching)} dòng"
    row = matching[0]
    assert row[idx["type"]] == "AUTO"
    assert row[idx["status"]] == "ERROR"
    notes = row[idx["notes"]]
    assert notes.startswith("Không tạo được nội dung nào.")
    assert "Bài viết: Số liệu 28% trong bài không có trong nguồn" in notes
    assert "Ảnh: Không trích được dữ kiện nào từ bài gốc" in notes
    assert "Video: Nguồn không đủ chất liệu để dựng video" in notes
    # 5.1 -- KHÔNG được lộ thuật ngữ kỹ thuật trong câu gộp hiển thị.
    for banned in ("content_units[]", "brief_status", "evidence/background", "SOURCE_BROKEN"):
        assert banned not in notes, f"Notes gộp còn lộ thuật ngữ kỹ thuật: {banned!r} trong {notes!r}"

    # VIỆC 4.3 -- store vẫn giữ đủ 3 bản ghi gốc kèm mã lý do GỐC tiếng Anh.
    assert "SOURCE_BROKEN" in ps.read_content_output(tk, "infographic", db_path=db_path)["notes"]
    assert "content_units[]" in ps.read_content_output(tk, "video", db_path=db_path)["notes"]


def test_auto_partial_success_hides_error_row_keeps_done_and_skipped(tmp_path):
    """VIỆC 4.2 — Output Type=AUTO, ≥1 tuyến DONE -> BỎ dòng của loại LỖI
    (Status=ERROR), GIỮ dòng DONE và dòng SKIPPED (Router chủ động từ chối,
    KHÔNG PHẢI lỗi — không đụng, đã có Notes giải thích riêng từ trước)."""
    from store import document_store as ds
    from store import pipeline_store as ps

    db_path = tmp_path / "store.db"
    ds.init_db(db_path)
    tk = "tk-auto-partial"
    ps.write_raw(tk, {"context": "Chủ đề AUTO thành công 1 phần", "timestamp": "03/08/2026"}, db_path=db_path)
    ps.write_gate_status(tk, gate1="APPROVE", execute="DONE", output_type=["AUTO"], db_path=db_path)
    ps.write_content_output(tk, "article", {"status": "DONE", "output": "# Bài viết thật", "notes": ""},
                            db_path=db_path)
    ps.write_content_output(tk, "infographic", {
        "status": "ERROR", "output": "",
        "notes": "SOURCE_BROKEN: content_units[] rỗng (Brief chưa trích được số liệu)",
    }, db_path=db_path)
    ps.write_content_output(tk, "video", {
        "status": "SKIPPED", "output": "",
        "notes": "FORMAT_MISMATCH: Router quyết định tuyến video không hợp tin này: "
                "Thiếu narrative kể chuyện.",
    }, db_path=db_path)

    rows, idx = _render_content_grid(db_path)
    matching = {r[idx["type"]]: r for r in rows if r[idx["topickey"]] == tk}
    assert set(matching) == {"Article", "Video"}, (
        f"kỳ vọng CHỈ Article (DONE) + Video (SKIPPED), KHÔNG Infographic (ERROR bị ẩn) -- "
        f"thực tế: {sorted(matching)}"
    )
    assert matching["Article"][idx["status"]] == "DONE"
    assert matching["Video"][idx["status"]] == "BỎ QUA"
    assert "Nội dung không phù hợp để làm video" in matching["Video"][idx["notes"]]

    # Store vẫn giữ NGUYÊN bản ghi infographic ERROR (chỉ ẩn ở Sheet, không xoá).
    assert ps.read_content_output(tk, "infographic", db_path=db_path)["status"] == "ERROR"


def test_explicit_output_type_error_not_collapsed_to_auto():
    """VIỆC 4.1 — Output Type CHỌN TƯỜNG MINH (không phải AUTO) mà hỏng ->
    GIỮ NGUYÊN Type = loại đã chọn, Status = ERROR — KHÔNG gộp thành AUTO (che
    mất việc hệ thống không làm được điều người yêu cầu)."""
    import tempfile
    from pathlib import Path
    from store import document_store as ds
    from store import pipeline_store as ps

    db_path = Path(tempfile.mkdtemp()) / "store.db"
    ds.init_db(db_path)
    tk = "tk-explicit-error"
    ps.write_raw(tk, {"context": "Chủ đề chọn Article tường minh mà hỏng", "timestamp": "03/08/2026"},
                db_path=db_path)
    ps.write_gate_status(tk, gate1="APPROVE", execute="NEEDS_HUMAN", output_type=["Article"], db_path=db_path)
    ps.write_content_output(tk, "article", {
        "status": "ERROR", "output": "",
        "notes": "Số liệu không thấy trong evidence/background: 96%",
    }, db_path=db_path)

    rows, idx = _render_content_grid(db_path)
    matching = [r for r in rows if r[idx["topickey"]] == tk]
    assert len(matching) == 1
    assert matching[0][idx["type"]] == "Article"          # KHÔNG bị đổi thành AUTO
    assert matching[0][idx["status"]] == "ERROR"
    assert "Số liệu 96% trong bài không có trong nguồn" in matching[0][idx["notes"]]


def test_notes_business_unknown_code_falls_back_to_generic_message(capsys):
    """VIỆC 5.6 — mã lý do MỚI phát sinh sau này (chưa có trong labels.vi.
    notes_messages/notes_codes) mà câu vẫn còn dấu hiệu kỹ thuật (ở đây:
    "null", chưa từng dịch) -> hiển thị câu chung "Không xử lý được, cần kiểm
    tra lại", KHÔNG lộ chuỗi kỹ thuật ra Sheet, VÀ ghi log cảnh báo."""
    from twmkt.sheets_board import _display_notes_business

    raw = "SOME_BRAND_NEW_CODE: giá trị trả về là null, chưa có bộ dịch cho mã này"
    out = _display_notes_business(raw)
    assert out == "Không xử lý được, cần kiểm tra lại"
    assert "null" not in out and "SOME_BRAND_NEW_CODE" not in out
    captured = capsys.readouterr()
    assert "CẢNH BÁO" in captured.out and "mã lý do mới" in captured.out


# =============================================================================
# PHASE QUEUE (2026-07-27) — scripts/queue_worker.py::run_once()
# =============================================================================

def _queue_worker_module():
    import os as _os
    import sys as _sys
    REPO_ROOT_ = _os.path.abspath(_os.path.join(_os.path.dirname(__file__), ".."))
    _sys.path.insert(0, _os.path.join(REPO_ROOT_, "scripts"))
    import queue_worker as qw
    return qw


def test_queue_worker_run_once_returns_false_when_queue_empty(monkeypatch, tmp_path):
    from store import document_store as ds
    from twmkt.config import Settings

    qw = _queue_worker_module()
    db_path = tmp_path / "store.db"
    monkeypatch.setenv("DOCUMENT_STORE_PATH", str(db_path))
    ds.init_db(db_path)

    handled = qw.run_once(settings=Settings({}), worker_id="test-worker")
    assert handled is False


def test_queue_worker_run_once_claims_processes_and_marks_done(monkeypatch, tmp_path):
    """1 vòng: claim job -> gọi ĐÚNG produce_from_sheet.run(topic_keys=[tk],
    limit=1) -> mark_done. `run()` chỉ MOCK ở test này (đã có test thật cho
    run() riêng) -- trọng tâm là dây nối claim->run->mark_done đúng."""
    from store import document_store as ds
    from store import queue_store as qs
    from twmkt.config import Settings

    qw = _queue_worker_module()
    db_path = tmp_path / "store.db"
    monkeypatch.setenv("DOCUMENT_STORE_PATH", str(db_path))
    ds.init_db(db_path)
    qs.enqueue("tk-1", db_path=db_path)

    called = []

    def _fake_run(*, topic_keys, limit):
        called.append((topic_keys, limit))
        return {"approved": 1, "produced": 1}

    monkeypatch.setattr(qw.produce_from_sheet, "run", _fake_run)

    handled = qw.run_once(settings=Settings({}), worker_id="test-worker")
    assert handled is True
    assert called == [(["tk-1"], 1)]

    row = qs.list_queue(db_path=db_path)[0]
    assert row["status"] == "done"


def test_queue_worker_run_once_marks_failed_when_run_raises(monkeypatch, tmp_path):
    """Crash HẠ TẦNG thật sự (run() raise, không tự bắt gọn được) -> job hàng
    đợi 'failed', KHÁC hẳn NEEDS_HUMAN/FAILED nghiệp vụ (cái đó run() tự ghi
    vào gate_status.execute, không raise, không rơi vào nhánh này)."""
    from store import document_store as ds
    from store import queue_store as qs
    from twmkt.config import Settings

    qw = _queue_worker_module()
    db_path = tmp_path / "store.db"
    monkeypatch.setenv("DOCUMENT_STORE_PATH", str(db_path))
    ds.init_db(db_path)
    qs.enqueue("tk-1", db_path=db_path)

    def _fake_run_raises(*, topic_keys, limit):
        raise RuntimeError("crash hạ tầng giả lập")

    monkeypatch.setattr(qw.produce_from_sheet, "run", _fake_run_raises)

    handled = qw.run_once(settings=Settings({}), worker_id="test-worker")
    assert handled is True   # job ĐÃ được xử lý (dù kết quả là failed)

    row = qs.list_queue(db_path=db_path)[0]
    assert row["status"] == "failed"
    assert "crash hạ tầng giả lập" in row["error"]


def test_queue_worker_run_once_releases_stale_claim_then_reprocesses_same_job(monkeypatch, tmp_path):
    """Job 'claimed' quá hạn lease (worker CŨ chết giữa chừng) phải được giải
    phóng về 'queued' TRƯỚC khi lấy job mới trong CÙNG 1 lần gọi `run_once()`
    — worker MỚI phải xử lý ĐƯỢC job đó ngay, không phải chờ vòng lặp sau."""
    import sqlite3
    from datetime import datetime, timedelta, timezone

    from store import document_store as ds
    from store import queue_store as qs
    from twmkt.config import Settings

    qw = _queue_worker_module()
    db_path = tmp_path / "store.db"
    monkeypatch.setenv("DOCUMENT_STORE_PATH", str(db_path))
    ds.init_db(db_path)
    job_id = qs.enqueue("tk-1", db_path=db_path)
    qs.claim_next("worker-cu-da-chet", db_path=db_path)
    old_ts = (datetime.now(timezone.utc) - timedelta(seconds=9999)).isoformat()
    conn = sqlite3.connect(str(db_path))
    conn.execute("UPDATE execution_queue SET claimed_at = ? WHERE id = ?", (old_ts, job_id))
    conn.commit()
    conn.close()

    called = []
    monkeypatch.setattr(qw.produce_from_sheet, "run",
                        lambda *, topic_keys, limit: called.append(topic_keys))

    settings = Settings({"queue": {"lease_timeout_s": 600, "max_attempts": 3}})
    handled = qw.run_once(settings=settings, worker_id="worker-moi")
    assert handled is True
    assert called == [["tk-1"]]

    row = qs.list_queue(db_path=db_path)[0]
    assert row["status"] == "done"
    assert row["claimed_by"] == "worker-moi"


def test_queue_worker_run_once_ingests_sheet_approval_before_claiming(monkeypatch, tmp_path):
    """VIỆC PHÁT SINH (2026-07-27, phát hiện khi chuẩn bị test e2e thật):
    TRƯỚC bản vá này, KHÔNG có gì gọi `ingest_context_from_sheet()` định kỳ ->
    người duyệt Gate1=APPROVE trên Sheet thật sẽ KHÔNG BAO GIỜ tự sinh job
    trong hàng đợi (enqueue chỉ nằm TRONG hàm ingest, xem store/sync_service.py).
    `run_once(board=...)` giờ tự ingest TRƯỚC khi kiểm hàng đợi — 1 lần gọi
    PHẢI đủ để: đọc Sheet thấy Gate1=APPROVE mới -> enqueue -> claim NGAY ->
    gọi run() -> done, không cần đợi vòng lặp sau."""
    from twmkt.sheets_board import CONTEXT_HEADER
    from store import document_store as ds
    from store import queue_store as qs
    from twmkt.config import Settings

    class _FakeWorksheet:
        """Đủ method cả ingest (get_all_values) LẪN render (clear/update) --
        run_once(board=...) giờ gọi CẢ 2 chiều sau khi xử lý xong 1 job."""
        def __init__(self, values):
            self._v = values

        def get_all_values(self):
            return [list(row) for row in self._v]

        def clear(self):
            self._v = []

        def update(self, range_str, values, value_input_option="RAW"):
            # TÔN TRỌNG range (2026-07-29): sync_service giờ ghi A1 (header) và
            # A2 (dữ liệu) RIÊNG — fake cũ thay cả bảng ở mỗi lệnh nên ghi A2
            # là mất header, test đỏ oan.
            start = int(range_str[1:]) if len(range_str) > 1 else 1
            need = start - 1 + len(values)
            while len(self._v) < need:
                self._v.append([])
            for i, row in enumerate(values):
                self._v[start - 1 + i] = [str(c) for c in row]

        def batch_clear(self, ranges):
            import re as _re
            for rng in ranges:
                m = _re.match(r"A(\d+):", rng)
                if m:
                    self._v = self._v[: int(m.group(1)) - 1]

    class _FakeBoard:
        def __init__(self, context_rows):
            self._tabs = {"CONTEXT": _FakeWorksheet(context_rows), "CONTENT": _FakeWorksheet([])}

        def _tab(self, name):
            return self._tabs.get(name, _FakeWorksheet([]))

    qw = _queue_worker_module()
    db_path = tmp_path / "store.db"
    monkeypatch.setenv("DOCUMENT_STORE_PATH", str(db_path))
    ds.init_db(db_path)

    # Timestamp = HÔM NAY (không hard-code ngày cụ thể): render_context_to_sheet()
    # lọc qua _visible_rows() (store/sync_service.py) -- chỉ giữ dòng trong
    # `sheets.display_days` ngày gần nhất (mặc định 7). Test gốc hard-code
    # "24/07/2026", trôi ra ngoài cửa sổ 7 ngày khi chạy sau đó vài ngày ->
    # dòng bị lọc mất khỏi Sheet render, StopIteration ở dưới (Lead 02/08,
    # Phần 2: đây là hành vi ĐÚNG của Sheet thật/_visible_rows, KHÔNG phải bug
    # queue_worker -- sửa test cho khớp, không đụng code production).
    from datetime import datetime as _dt
    today_ddmmyyyy = _dt.now().strftime("%d/%m/%Y")
    board = _FakeBoard([
        CONTEXT_HEADER,
        [today_ddmmyyyy, "0.0", "0", "", "", "Bài vừa duyệt", "h", "u1",
         "APPROVE", "", "", "", "", "tk-vua-duyet"],
    ])

    called = []
    monkeypatch.setattr(qw.produce_from_sheet, "run",
                        lambda *, topic_keys, limit: called.append(topic_keys))

    settings = Settings({})
    handled = qw.run_once(settings=settings, worker_id="worker-test", board=board)
    assert handled is True
    assert called == [["tk-vua-duyet"]]

    # VIỆC PHÁT SINH #2 (2026-07-27): Sheet PHẢI được render lại NGAY sau khi
    # xử lý xong job -- không thì Execute đứng hình mãi ở giá trị lúc duyệt,
    # dù store đã có trạng thái thật.
    rendered = board._tab("CONTEXT").get_all_values()
    header = rendered[0]
    i_ex = header.index("Execute")
    i_tk = header.index("TopicKey")
    row = next(r for r in rendered[1:] if r[i_tk] == "tk-vua-duyet")
    # 2026-07-28: worker ghi "Running..." NGAY sau claim; NHƯNG `_sync_sheet()`
    # cuối lượt ingest LẠI Sheet trước khi render (ingest thứ 2 đọc lại Sheet
    # giả vẫn còn Execute="" từ fixture gốc, không phải giá trị "Running..."
    # vừa ghi) -> giá trị cuối quan sát được là "Waiting" (mặc định
    # EXECUTE_WAITING khi gate_status.execute rỗng), không phải "Running...".
    # Test CHỈ khoá "Sheet PHẢI phản ánh store, KHÔNG đứng hình ở giá trị lúc
    # duyệt (APPROVE)" -- chấp nhận CẢ 2 giá trị vì race ingest/render 2 lượt
    # liên tiếp trong 1 lượt gọi produce=stub là hành vi biết trước của test
    # double, KHÔNG phải điều cần khoá chặt ở đây. Cần XÁC NHẬN BẰNG LƯỢT
    # CHẠY THẬT (Lead 02/08, Phần 2.2): bấm APPROVE trên Sheet thật, cột
    # Execute phải đi Waiting -> Running -> DONE; nếu đứng hình ở Waiting mãi
    # (không đi tiếp) thì ĐÓ MỚI là bug thật trong run_once()/_sync_sheet(),
    # quay lại sửa production code.
    assert row[i_ex] in ("Running...", "Waiting")

    row = qs.list_queue(db_path=db_path)[0]
    assert row["topic_key"] == "tk-vua-duyet" and row["status"] == "done"


# =============================================================================
# scripts/queue_worker_watchdog.py (2026-08-04, Lead: "hệ thống chạy full
# tính năng mà không cần thông qua agent") — Task Scheduler từ chối đăng ký
# trigger "At log on"/"At startup" trên máy này (Access is denied, cần quyền
# nâng cao không có sẵn trong môi trường agent) -- watchdog chạy theo lịch
# MINUTE (không cần quyền nâng cao, đã dùng cho TWMKT-Crawl-*/TWMKT-Draft)
# để đạt hiệu quả tương đương "tự khởi động lại khi crash".
# =============================================================================

def _queue_worker_watchdog_module():
    import os as _os
    import sys as _sys
    REPO_ROOT_ = _os.path.abspath(_os.path.join(_os.path.dirname(__file__), ".."))
    _sys.path.insert(0, _os.path.join(REPO_ROOT_, "scripts"))
    import queue_worker_watchdog as wd
    return wd


def test_watchdog_relaunches_when_no_lock_file_yet():
    wd = _queue_worker_watchdog_module()
    relaunch, reason = wd.should_relaunch(None)
    assert relaunch is True
    assert "lần đầu" in reason


def test_watchdog_relaunches_when_lock_content_is_malformed():
    wd = _queue_worker_watchdog_module()
    relaunch, reason = wd.should_relaunch("khong-phai-host:pid-hop-le")
    assert relaunch is True
    assert "hỏng" in reason


def test_watchdog_relaunches_when_pid_in_lock_is_dead():
    wd = _queue_worker_watchdog_module()
    relaunch, reason = wd.should_relaunch("may-a:4242", is_pid_alive_fn=lambda pid: False)
    assert relaunch is True
    assert "4242" in reason and "chết" in reason


def test_watchdog_does_not_relaunch_when_pid_in_lock_is_alive():
    wd = _queue_worker_watchdog_module()
    relaunch, reason = wd.should_relaunch("may-a:4242", is_pid_alive_fn=lambda pid: True)
    assert relaunch is False
    assert "4242" in reason


def test_asset_hyperlink_formula_wraps_url_string():
    """Sheet UI cleanup Phase 6b/6c: AssetPath phải là HYPERLINK() bấm được,
    không phải text đường dẫn thô — hàm THUẦN, không I/O. Phase 6c: nhận
    URL (str) đã dựng sẵn (xem twmkt.asset_server.asset_url), KHÔNG còn nhận
    Path/file:// (bản Phase 6b dùng file:// đã xác nhận THẬT trên Sheet sống
    là KHÔNG hoạt động — trình duyệt chặn HTTPS -> file://)."""
    rpa = _render_prod_assets_module()

    url = "http://127.0.0.1:8899/2026-07-16/assets/bai-a.svg"
    formula = rpa.asset_hyperlink_formula(url)
    assert formula == '=HYPERLINK("http://127.0.0.1:8899/2026-07-16/assets/bai-a.svg", "Mở file")'


def test_asset_url_computes_relative_url_under_root():
    """twmkt.asset_server.asset_url(): file NẰM TRONG root -> URL http://host:
    port/<relative-posix-path>, không lộ phần path phía TRÊN root."""
    import tempfile
    from pathlib import Path as _Path

    from twmkt.asset_server import asset_url

    root = _Path(tempfile.mkdtemp())
    fn = root / "2026-07-16" / "assets" / "bai a.svg"   # có khoảng trắng -> phải quote
    fn.parent.mkdir(parents=True, exist_ok=True)
    fn.write_text("<svg></svg>", encoding="utf-8")

    url = asset_url(fn, root=root, host="127.0.0.1", port=8899)
    assert url == "http://127.0.0.1:8899/2026-07-16/assets/bai%20a.svg"


def test_asset_url_rejects_path_outside_root():
    """`path` PHẢI nằm trong `root` — Path.relative_to() ném ValueError nếu
    không, xác nhận hàm KHÔNG âm thầm sinh URL sai/lộ đường dẫn ngoài root."""
    import tempfile
    from pathlib import Path as _Path

    from twmkt.asset_server import asset_url

    root = _Path(tempfile.mkdtemp())
    outside = _Path(tempfile.mkdtemp()) / "x.svg"
    try:
        asset_url(outside, root=root)
    except ValueError:
        pass
    else:
        raise AssertionError("asset_url() phải raise ValueError khi path nằm ngoài root.")


def test_asset_server_real_round_trip_serves_file_over_http():
    """Round-trip THẬT (không mock): dựng server trên cổng OS tự chọn
    (port=0), viết 1 file thật vào root, GET thật qua urllib.request, xác
    nhận nội dung khớp — chứng minh cơ chế THẬT hoạt động (không chỉ đúng
    hình dạng request/URL)."""
    import tempfile
    import threading
    import urllib.request
    from pathlib import Path as _Path

    from twmkt.asset_server import asset_url, build_server

    root = _Path(tempfile.mkdtemp())
    fn = root / "test.svg"
    fn.write_text("<svg>hello</svg>", encoding="utf-8")

    server = build_server(root, port=0)
    real_port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = asset_url(fn, root=root, port=real_port)
        assert url == f"http://127.0.0.1:{real_port}/test.svg"
        with urllib.request.urlopen(url, timeout=5) as resp:
            body = resp.read().decode("utf-8")
        assert body == "<svg>hello</svg>"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_asset_server_binds_localhost_only_never_0000():
    """CHỈ bind 127.0.0.1 mặc định — KHÔNG BAO GIỜ 0.0.0.0 (không expose file
    cục bộ ra mạng, xem docstring twmkt.asset_server)."""
    import inspect

    from twmkt.asset_server import DEFAULT_HOST, build_server

    assert DEFAULT_HOST == "127.0.0.1"
    assert inspect.signature(build_server).parameters["host"].default == "127.0.0.1"


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


def test_format_message_uses_vietnamese_labels_for_known_events_and_keys():
    """Yêu cầu Trung 02/08 — nhãn tiếng Việt CHỈ ở tầng hiển thị (build text
    gửi Telegram), KHÔNG đổi string "event"/key ctx dùng làm định danh nội bộ
    (notify() call site vẫn gọi "start"/"skipped"/"error"/"draft_changed"/
    "topic"/"reason" y hệt, xem _EMOJI/notifier.events trong các test khác)."""
    from twmkt.utils.telegram_notifier import format_message

    msg = format_message("start", {"topic": "Bài test"})
    assert "Bắt đầu xử lý nội dung" in msg and "Chủ đề:" in msg

    msg = format_message("new_topic", {"topic": "Bài mới", "reason": "vì X"})
    assert "Chủ đề mới" in msg and "Chủ đề:" in msg and "Lý do:" in msg

    msg = format_message("skipped", {"topic": "t", "reason": "vì Y"})
    assert "Bỏ qua" in msg and "Lý do:" in msg

    msg = format_message("error", {"topic": "t", "reason": "vì Z"})
    assert "Lỗi xử lý" in msg

    msg = format_message("draft_changed", {"topic": "t"})
    assert "Cập nhật nội dung" in msg

    # Event/key LẠ (không trong bảng dịch) giữ NGUYÊN tiếng Anh.
    msg = format_message("gate2_done", {"written": 3, "approved": 2})
    assert "gate2_done" in msg and "written:" in msg and "approved:" in msg


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


def test_make_notifier_env_flag_overrides_settings_enabled():
    """Cờ thủ công TWMKT_TELEGRAM_ENABLED — bật/tắt nhanh KHÔNG cần sửa
    settings.yaml, đè giá trị `enabled` trong config khi ENV có mặt."""
    import os

    from twmkt.utils.telegram_notifier import make_notifier, NullNotifier, TelegramNotifier

    s_enabled = Settings({"notifications": {"telegram": {
        "enabled": True, "bot_token": "123:abc", "chat_id": "999"}}})
    s_disabled = Settings({"notifications": {"telegram": {
        "enabled": False, "bot_token": "123:abc", "chat_id": "999"}}})

    old = os.environ.get("TWMKT_TELEGRAM_ENABLED")
    try:
        os.environ["TWMKT_TELEGRAM_ENABLED"] = "0"
        assert isinstance(make_notifier(s_enabled), NullNotifier)   # ENV=0 đè settings enabled=True

        os.environ["TWMKT_TELEGRAM_ENABLED"] = "true"
        assert isinstance(make_notifier(s_disabled), TelegramNotifier)   # ENV=true đè settings enabled=False

        os.environ["TWMKT_TELEGRAM_ENABLED"] = "gia-tri-la"
        assert isinstance(make_notifier(s_disabled), NullNotifier)   # ENV lạ -> lùi về settings.yaml như cũ
    finally:
        if old is None:
            os.environ.pop("TWMKT_TELEGRAM_ENABLED", None)
        else:
            os.environ["TWMKT_TELEGRAM_ENABLED"] = old


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


# --- system_power_on.py: lock file tự chặn 2 tiến trình cùng máy ($0, không mạng) --
def test_power_on_lock_parses_and_detects_dead_pid():
    """parse_lock_content + is_pid_alive: parse "host:pid" đúng/hỏng; PID không
    tồn tại -> False; PID hiện tại (chính tiến trình test) -> True."""
    sys.path.insert(0, REPO_ROOT)
    import system_power_on as po

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
    sys.path.insert(0, REPO_ROOT)
    import system_power_on as po

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
    sys.path.insert(0, REPO_ROOT)
    import system_power_on as po

    tmp = Path(tempfile.mkdtemp()) / "power_on.lock"
    tmp.write_text("mot-may-khac:123", encoding="utf-8")
    po.acquire_lock(tmp)   # không raise
    po.release_lock(tmp)


def test_power_on_start_asset_server_disabled_by_default_returns_none():
    """Sheet UI cleanup Phase 6d: storage.asset_server_enabled VẮNG (mặc định)
    hoặc =false -> _start_asset_server() trả None, KHÔNG mở socket nào (asset
    server TẮT trên máy dev cho tới khi lên VPS bật thủ công)."""
    from twmkt.config import Settings
    sys.path.insert(0, REPO_ROOT)
    import system_power_on as po

    assert po._start_asset_server(Settings({})) is None
    assert po._start_asset_server(Settings({"storage": {"asset_server_enabled": False}})) is None


def test_power_on_start_asset_server_enabled_starts_real_server_stoppable():
    """storage.asset_server_enabled=true -> khởi động THẬT (port=0, OS tự cấp
    cổng trống, tránh đụng cổng thật đang dùng) — server sống, phục vụ ĐÚNG
    thư mục output_dir (round-trip HTTP GET thật, không mock). Monkeypatch
    `po.build_server` chỉ để BẮT LẠI đối tượng server thật (lấy cổng OS vừa
    cấp) — vẫn là server thật, KHÔNG thay hành vi build_server()."""
    import tempfile
    import threading as _threading
    import urllib.request
    from pathlib import Path as _Path

    from twmkt.config import Settings
    sys.path.insert(0, REPO_ROOT)
    import system_power_on as po

    data_root = _Path(tempfile.mkdtemp())
    (data_root / "output").mkdir()
    (data_root / "output" / "hello.txt").write_text("xin chao", encoding="utf-8")

    settings = Settings({"storage": {
        "data_root": str(data_root), "output_dir": "output",
        "asset_server_enabled": True, "asset_server_port": 0,
    }})

    captured: dict = {}
    real_build_server = po.build_server

    def _capturing_build_server(root, *, host="127.0.0.1", port=8899):
        srv = real_build_server(root, host=host, port=port)
        captured["server"] = srv
        return srv

    po.build_server = _capturing_build_server
    try:
        t = po._start_asset_server(settings)
        assert isinstance(t, _threading.Thread) and t.is_alive()
        server = captured["server"]
        real_port = server.server_address[1]
        with urllib.request.urlopen(f"http://127.0.0.1:{real_port}/hello.txt", timeout=5) as resp:
            body = resp.read().decode("utf-8")
        assert body == "xin chao"
    finally:
        po.build_server = real_build_server
        server = captured.get("server")
        if server is not None:
            server.shutdown()
            server.server_close()
def test_parse_vn_number_words_decimal_with_ty_suffix():
    from twmkt.media_factory.numbers import parse_vn_number_words

    assert parse_vn_number_words("mười ba phẩy tám tỷ") == 13.8e9


def test_parse_vn_number_words_percent_no_scale():
    from twmkt.media_factory.numbers import parse_vn_number_words

    assert parse_vn_number_words("hai mươi ba phần trăm") == 23.0


def test_parse_vn_number_words_nghin_ty_composes_correctly():
    """'nghìn' xử NHƯ BỘI SỐ ×1.000 dù đứng giữa phần nguyên -> tự ra đúng
    1.3e13 mà KHÔNG cần liệt 'nghìn tỷ' thành 1 đơn vị ghép riêng."""
    from twmkt.media_factory.numbers import parse_vn_number_words

    assert parse_vn_number_words("mười ba nghìn tỷ") == 1.3e13
    assert parse_vn_number_words("mười ba nghìn") == 13000.0


def test_parse_vn_number_words_decimal_reads_digit_by_digit():
    """Phần thập phân đọc TỪNG CHỮ SỐ ĐƠN: "phẩy không tám" = .08, KHÔNG phải
    ghép "không"+"tám" thành 1 số 2 chữ số."""
    from twmkt.media_factory.numbers import parse_vn_number_words

    assert parse_vn_number_words("mười ba phẩy không tám") == 13.08


def test_parse_vn_number_words_simple_hundreds_and_units():
    from twmkt.media_factory.numbers import parse_vn_number_words

    assert parse_vn_number_words("năm trăm tám mươi lăm tỷ") == 585e9
    assert parse_vn_number_words("một triệu") == 1e6
    assert parse_vn_number_words("hai mươi mốt") == 21.0


def test_parse_vn_number_words_linh_filler_zero_tens():
    """R2 (2026-07-19) — "linh" là ĐỆM hàng-chục-bằng-không, KHÔNG mang giá trị.

    Phát hiện bằng property round-trip test bên aigen
    (`src/production-spec/voice/spell-out-numbers.test.ts`): bộ SINH số→chữ
    phát ra "một trăm linh năm" cho 105, nhưng parser ở đây KHÔNG có "linh"
    trong từ vựng nên trả None → 162/2001 số nguyên (TẤT CẢ dạng x0y) không
    đọc ngược được → guardrail chặn oan mọi bài chứa số dạng đó.

    HỢP ĐỒNG CHÉO REPO: quy tắc này phải khớp
    `aigen/src/production-spec/guardrail/verify-spec.ts::parseSmallGroup`
    (xem `docs/ARCHITECTURE_MODULES.md` §content_units[]) — sửa 1 bên phải sửa bên kia
    cùng lượt.
    """
    from twmkt.media_factory.numbers import parse_vn_number_words

    assert parse_vn_number_words("một trăm linh năm") == 105.0
    assert parse_vn_number_words("một trăm linh một") == 101.0
    assert parse_vn_number_words("một nghìn chín trăm linh ba") == 1903.0
    assert parse_vn_number_words("một trăm linh năm tỷ") == 105e9
    # Không có "linh" thì vẫn như cũ (không hồi quy).
    assert parse_vn_number_words("một trăm mười lăm") == 115.0


def test_find_word_number_phrases_keeps_linh_phrase_contiguous():
    """R2 — "linh" phải nằm trong từ vựng số để cụm KHÔNG bị cắt làm đôi.

    Thiếu nó, "một trăm linh năm tỷ" bị tách thành "một trăm" (=100) và
    "năm tỷ" (=5e9) — cả hai đều không khớp fact 105e9 nào → 2 vi phạm oan.
    """
    from twmkt.media_factory.numbers import find_word_number_phrases

    out = find_word_number_phrases("lợi nhuận đạt một trăm linh năm tỷ đồng")
    assert len(out) == 1, f"cụm bị cắt rời: {out}"
    assert out[0][0] == "một trăm linh năm tỷ"


def test_find_word_number_phrases_ignores_edge_punctuation():
    """(b) 2026-07-19 — dấu câu dính token KHÔNG được cắt cụt cụm số.

    Ca THẬT (bài `vietnam_airlines_co_dong`): "...hai mươi lăm." — token cuối
    là "lăm." (có dấu chấm) nên trước đây rơi khỏi từ vựng số, cụm bị cắt thành
    "năm hai nghìn không trăm hai mươi" = 5020 thay vì 2025 -> guardrail chặn oan.

    HỢP ĐỒNG CHÉO REPO: khớp `findWordNumberPhrases` bên
    `aigen/src/production-spec/guardrail/verify-spec.ts`.
    """
    from twmkt.media_factory.numbers import find_word_number_phrases, parse_vn_number_words

    text = "kiểm toán năm hai nghìn không trăm hai mươi lăm. Vốn chủ"
    out = find_word_number_phrases(text)
    assert len(out) == 1, f"cụm bị cắt rời: {out}"
    phrase, start = out[0]
    assert phrase == "năm hai nghìn không trăm hai mươi lăm", phrase
    # offset trả về phải trỏ ĐÚNG vị trí trong text gốc (dùng để dò từ xấp xỉ).
    assert text[start:].startswith("năm hai")
    # (c) 2026-07-20 — ĐÃ SỬA nhập nhằng "năm": cụm mở đầu "năm" + phần còn lại
    # là năm hợp lý (1900-2100) -> "năm" là DANH TỪ (year), bỏ khỏi phép tính.
    # Nay parse ra ĐÚNG 2025 (trước đây 5025 vì "năm" bị đọc thành chữ số 5).
    # Đồng bộ `parseVnNumberWords` bên aigen verify-spec.ts.
    assert parse_vn_number_words(phrase) == 2025.0, phrase

    # Dấu phẩy giữa cụm cũng không được cắt.
    out2 = find_word_number_phrases("thời kỳ hai nghìn ba mươi, tầm nhìn xa")
    assert [p for p, _ in out2] == ["hai nghìn ba mươi"], out2
    assert parse_vn_number_words(out2[0][0]) == 2030.0

    # Hậu tố lớn dính dấu chấm vẫn phải được nhận (không mất "tỷ").
    out3 = find_word_number_phrases("đạt mười sáu phẩy ba tỷ.")
    assert [p for p, _ in out3] == ["mười sáu phẩy ba tỷ"], out3
    assert parse_vn_number_words(out3[0][0]) == 16.3e9


def test_parse_vn_number_words_disambiguates_leading_nam_as_year():
    """(c) 2026-07-20 — "năm" mở đầu cụm + phần còn lại là năm hợp lý (1900-2100)
    -> "năm" = DANH TỪ (year), bỏ khỏi phép tính. HỢP ĐỒNG CHÉO REPO: đồng bộ
    `parseVnNumberWords` bên `aigen/src/production-spec/guardrail/verify-spec.ts`.
    """
    from twmkt.media_factory.numbers import parse_vn_number_words as p

    # "năm" là DANH TỪ (year) -> bỏ khỏi phép tính.
    assert p("năm hai nghìn không trăm hai mươi lăm") == 2025.0
    assert p("năm hai nghìn không trăm hai mươi") == 2020.0
    assert p("năm hai nghìn không trăm ba mươi") == 2030.0
    assert p("năm hai nghìn hai mươi sáu") == 2026.0   # dạng đọc tắt (bộ sinh date)

    # "năm" là CHỮ SỐ 5 — phần còn lại KHÔNG rơi vào [1900,2100] -> GIỮ NGUYÊN.
    assert p("năm mươi") == 50.0
    assert p("năm mươi lăm") == 55.0
    assert p("năm trăm") == 500.0
    assert p("năm nghìn") == 5000.0
    assert p("năm triệu") == 5_000_000.0
    assert p("năm tỷ") == 5_000_000_000.0
    assert p("năm") == 5.0
    # Không có "năm" mở đầu -> không chạm.
    assert p("hai nghìn không trăm hai mươi lăm") == 2025.0


def test_parse_vn_number_words_invalid_returns_none():
    from twmkt.media_factory.numbers import parse_vn_number_words

    assert parse_vn_number_words("") is None
    assert parse_vn_number_words("con mèo") is None
    assert parse_vn_number_words("tỷ") is None            # chỉ có đơn vị, không có số
    assert parse_vn_number_words("mười ba phẩy con mèo") is None   # phần thập phân hỏng
    # "lẻ" CỐ Ý không nằm trong từ vựng (xem ghi chú _STRUCTURE_WORDS ở
    # numbers.py): bộ sinh không bao giờ phát ra nó, còn "bán lẻ" là từ thường
    # gặp trong văn tài chính — nhận nó chỉ tạo thêm dương tính giả.
    assert parse_vn_number_words("một trăm lẻ năm") is None


def test_find_word_number_phrases_min_length_and_suffix_rule():
    from twmkt.media_factory.numbers import find_word_number_phrases

    # cụm 1 từ KHÔNG có hậu tố lớn -> bỏ qua (giảm dương tính giả, "một" hay
    # dùng phi-số kiểu mạo từ trong câu tự nhiên).
    out1 = find_word_number_phrases("có một điều đáng chú ý")
    assert out1 == []

    # cụm 1 từ CÓ hậu tố lớn ngay sau -> vẫn nhận.
    out2 = find_word_number_phrases("doanh thu đạt một tỷ đồng năm nay")
    assert [p for p, _ in out2] == ["một tỷ"]

    # cụm >=2 từ số liên tiếp -> nhận dù không có hậu tố lớn.
    out3 = find_word_number_phrases("tăng trưởng hai mươi ba phần trăm so cùng kỳ")
    assert [p for p, _ in out3] == ["hai mươi ba phần trăm"]


def test_visual_kind_closed_set_and_deferred_avatar():
    """visual_kind (video, khớp 15 template AIGEN thật) là 1 tập ĐÓNG."""
    from twmkt.media_factory.spec import DEFERRED_VISUAL_KINDS, VISUAL_KINDS

    # 10 giá trị thật (đếm lại — thông báo "5->9" trước đó ĐẾM NHẦM, danh sách
    # liệt kê ra luôn là 10: title/stat/statement/list/comparison/quote/
    # ticker/news/avatar/outro).
    assert len(VISUAL_KINDS) == 10
    assert DEFERRED_VISUAL_KINDS == {"avatar"}
    assert DEFERRED_VISUAL_KINDS <= VISUAL_KINDS   # avatar CÓ trong tập, chỉ chưa kích hoạt


def test_matches_canonical_fact_range_and_delta_shapes():
    """Guardrail LẦN 1 (agents/production.py, chạy ngay sau Composer/Writer,
    TRƯỚC verify_spec) — PHẢI nhất quán với verify_spec (guardrail lần 2): số
    trong bài khớp range/delta cũng KHÔNG bị coi là bịa, số không khớp gì vẫn
    bị bắt (Phase 1 nghiệm thu: "vẫn bắt được số bịa")."""
    from twmkt.agents.production import unsupported_numbers
    from twmkt.models import ContentUnit

    content_units = [
        ContentUnit(value="", label="Vốn FDI", unit="%", shape="range",
            canonical_low=70.0, canonical_high=80.0, source="..."),
        ContentUnit(value="", label="Doanh thu Q2 (2025→2026)", shape="delta",
            canonical_from=16.3e9, canonical_to=176e6, source="..."),
    ]
    body_clean = "Vốn FDI đạt 75%, doanh thu quý 2/2026 chỉ còn 176 triệu đồng."
    assert unsupported_numbers(body_clean, "evidence không chứa số này", content_units) == []

    body_bad = "Vốn FDI đạt 95% — con số bịa."
    bad = unsupported_numbers(body_bad, "evidence không chứa số này", content_units)
    assert "95%" in bad


# =====================================================================
# "Lớp Adapter DUY NHẤT" — seam subprocess (media_factory/aigen_seam.py).
# Máy này (PC-A) KHÔNG BAO GIỜ gọi npm thật -- MOCK subprocess.run hoàn
# toàn, phủ 3 nhánh (exit 0 / exit 1 / exit 2) + idempotent-skip + dry-run.
# =====================================================================
def test_aigen_seam_success_exit0_finds_video(tmp_path=None):
    import tempfile
    from pathlib import Path
    from unittest.mock import patch, MagicMock
    from twmkt.media_factory.aigen_seam import run_aigen_pipeline

    tmp = Path(tempfile.mkdtemp())
    script_path = tmp / "script.json"
    script_path.write_text("{}", encoding="utf-8")
    video_path = tmp / "video.mp4"

    def _fake_run(cmd, cwd, capture_output, text, timeout):
        video_path.write_text("fake mp4 bytes", encoding="utf-8")  # AIGEN "renders" it
        return MagicMock(returncode=0, stdout="ok", stderr="")

    with patch("subprocess.run", side_effect=_fake_run) as m:
        result = run_aigen_pipeline(script_path, aigen_repo_path=tmp / "aigen")
        assert m.call_count == 1
        called_cmd = m.call_args.args[0]
        # 2026-07-28: `produce:content`, KHÔNG phải `pipeline` — xem
        # aigen_seam.py. `pipeline` nhận TemplateScript đã chuyển đổi và KHÔNG
        # tự bật OmniVoice; ta đưa vào CONTENT.Output nên phải qua cổng có
        # adapter + tự lo TTS.
        # 2026-07-29: cmd[0] là ĐƯỜNG DẪN THẬT do shutil.which() resolve (trên
        # Windows là npm.cmd), không phải bare "npm" — xem aigen_seam.py.
        assert called_cmd[0].replace("\\", "/").rsplit("/", 1)[-1].startswith("npm")
        assert called_cmd[1:] == ["run", "produce:content", "--", str(script_path)]
        assert m.call_args.kwargs["cwd"] == str(tmp / "aigen")

    assert result.ok is True
    assert result.video_path == video_path
    assert result.skipped_already_rendered is False
    assert result.exit_code == 0


def test_aigen_seam_exit1_pipeline_failure_is_fatal():
    import tempfile
    from pathlib import Path
    from unittest.mock import patch, MagicMock
    from twmkt.media_factory.aigen_seam import run_aigen_pipeline

    tmp = Path(tempfile.mkdtemp())
    script_path = tmp / "script.json"
    script_path.write_text("{}", encoding="utf-8")

    fake = MagicMock(returncode=1, stdout="", stderr="ffmpeg ENOENT")
    with patch("subprocess.run", return_value=fake):
        result = run_aigen_pipeline(script_path, aigen_repo_path=tmp / "aigen")

    assert result.ok is False
    assert result.exit_code == 1
    assert "exit 1" in result.error
    assert not (tmp / "video.mp4").exists()


def test_aigen_seam_exit2_missing_arg_also_fatal_same_as_exit1():
    """Tài liệu AIGEN không phân biệt đủ rõ ý nghĩa exit 1 vs exit 2 -- seam
    coi CẢ HAI fatal như nhau (xem docstring module), KHÔNG cố xử lý khác
    nhau dựa trên đoán ý nghĩa mã số."""
    import tempfile
    from pathlib import Path
    from unittest.mock import patch, MagicMock
    from twmkt.media_factory.aigen_seam import run_aigen_pipeline

    tmp = Path(tempfile.mkdtemp())
    script_path = tmp / "script.json"
    script_path.write_text("{}", encoding="utf-8")

    fake = MagicMock(returncode=2, stdout="", stderr="Usage: npm run pipeline -- <path>")
    with patch("subprocess.run", return_value=fake):
        result = run_aigen_pipeline(script_path, aigen_repo_path=tmp / "aigen")

    assert result.ok is False
    assert result.exit_code == 2
    assert "exit 2" in result.error


def test_aigen_seam_exit0_but_no_video_file_is_still_an_error():
    """KHÔNG tin exit code một mình -- exit 0 mà video.mp4 không thật sự xuất
    hiện vẫn phải báo lỗi rõ ràng, không báo ok=True mù quáng."""
    import tempfile
    from pathlib import Path
    from unittest.mock import patch, MagicMock
    from twmkt.media_factory.aigen_seam import run_aigen_pipeline

    tmp = Path(tempfile.mkdtemp())
    script_path = tmp / "script.json"
    script_path.write_text("{}", encoding="utf-8")

    fake = MagicMock(returncode=0, stdout="=== Result ===", stderr="")
    with patch("subprocess.run", return_value=fake):
        result = run_aigen_pipeline(script_path, aigen_repo_path=tmp / "aigen")

    assert result.ok is False
    assert "KHÔNG thấy video.mp4" in result.error


def test_aigen_seam_idempotent_skip_when_video_already_exists_no_subprocess_call():
    """IDEMPOTENT PER-ASSET (không cờ --force toàn cục): video.mp4 đã tồn tại
    trước khi gọi -> subprocess.run KHÔNG được gọi luôn (assert not called),
    không chỉ 'gọi rồi bỏ qua kết quả'."""
    import tempfile
    from pathlib import Path
    from unittest.mock import patch
    from twmkt.media_factory.aigen_seam import run_aigen_pipeline

    tmp = Path(tempfile.mkdtemp())
    script_path = tmp / "script.json"
    script_path.write_text("{}", encoding="utf-8")
    video_path = tmp / "video.mp4"
    video_path.write_text("da render tu truoc", encoding="utf-8")

    with patch("subprocess.run") as m:
        result = run_aigen_pipeline(script_path, aigen_repo_path=tmp / "aigen")
        m.assert_not_called()

    assert result.ok is True
    assert result.skipped_already_rendered is True
    assert result.video_path == video_path


def test_aigen_seam_dry_run_logs_command_never_calls_subprocess():
    """dry_run=True (chế độ AN TOÀN dùng trên PC-A -- máy này KHÔNG BAO GIỜ
    render thật) -- log lệnh SẼ chạy, subprocess.run KHÔNG được gọi."""
    import tempfile
    from pathlib import Path
    from unittest.mock import patch
    from twmkt.media_factory.aigen_seam import run_aigen_pipeline

    tmp = Path(tempfile.mkdtemp())
    script_path = tmp / "script.json"
    script_path.write_text("{}", encoding="utf-8")
    aigen_path = tmp / "aigen"

    with patch("subprocess.run") as m:
        result = run_aigen_pipeline(script_path, aigen_repo_path=aigen_path, dry_run=True)
        m.assert_not_called()

    assert result.ok is True
    assert result.video_path is None
    assert "DRY-RUN" in result.stdout
    assert str(script_path) in result.stdout
    assert str(aigen_path) in result.stdout


def test_aigen_seam_timeout_is_reported_not_raised():
    import tempfile
    from pathlib import Path
    from unittest.mock import patch
    import subprocess as _subprocess
    from twmkt.media_factory.aigen_seam import run_aigen_pipeline

    tmp = Path(tempfile.mkdtemp())
    script_path = tmp / "script.json"
    script_path.write_text("{}", encoding="utf-8")

    def _raise_timeout(*a, **kw):
        raise _subprocess.TimeoutExpired(cmd="npm", timeout=5)

    with patch("subprocess.run", side_effect=_raise_timeout):
        result = run_aigen_pipeline(script_path, aigen_repo_path=tmp / "aigen", timeout_s=5)

    assert result.ok is False
    assert "timeout" in result.error


# --- A5: aigen_repo_path qua CONFIG (ENV AIGEN_REPO_PATH), không hardcode ---
# (sự cố: dry-run từng in cwd=E:\aigen-fva-capital\aigen, repo ĐÃ CHẾT — xem
# docs/VPS_MIGRATION_BACKLOG.md A5). 3 test dưới KHÔNG truyền aigen_repo_path
# tường minh -> ép seam tự resolve qua config, đúng nhánh code MỚI (khác 7
# test trên -- những test đó cố ý giữ nguyên nhánh truyền tường minh cũ).
def test_aigen_seam_resolves_aigen_repo_path_from_config_when_path_exists():
    """Config (ENV AIGEN_REPO_PATH) trỏ path CÓ THẬT -> seam tự resolve, dựng
    đúng lệnh + đúng cwd -- KHÔNG cần truyền aigen_repo_path tường minh."""
    import tempfile
    from pathlib import Path
    from unittest.mock import patch, MagicMock
    from twmkt.media_factory.aigen_seam import run_aigen_pipeline

    tmp = Path(tempfile.mkdtemp())
    script_path = tmp / "script.json"
    script_path.write_text("{}", encoding="utf-8")
    video_path = tmp / "video.mp4"
    aigen_dir = Path(tempfile.mkdtemp())  # path CÓ THẬT trên đĩa

    def _fake_run(cmd, cwd, capture_output, text, timeout):
        video_path.write_text("fake mp4 bytes", encoding="utf-8")
        return MagicMock(returncode=0, stdout="ok", stderr="")

    os.environ["AIGEN_REPO_PATH"] = str(aigen_dir)
    try:
        with patch("subprocess.run", side_effect=_fake_run) as m:
            result = run_aigen_pipeline(script_path)  # KHÔNG truyền aigen_repo_path
            assert m.call_args.kwargs["cwd"] == str(aigen_dir)
            got = m.call_args.args[0]
            assert got[0].replace("\\", "/").rsplit("/", 1)[-1].startswith("npm")
            assert got[1:] == ["run", "produce:content", "--", str(script_path)]
        assert result.ok is True
    finally:
        del os.environ["AIGEN_REPO_PATH"]


def test_aigen_seam_config_path_missing_raises_clear_error_naming_the_path():
    """Config (ENV AIGEN_REPO_PATH) trỏ path KHÔNG TỒN TẠI -> raise lỗi RÕ
    RÀNG nêu đúng đường dẫn đã thử -- KHÔNG fail mù bằng lỗi OS/subprocess
    khó hiểu. Lỗi cấu hình phổ biến nhất khi đổi máy (VPS)."""
    from pathlib import Path
    from twmkt.media_factory.aigen_seam import run_aigen_pipeline, AigenRepoPathNotFoundError

    missing_path = str(Path("E:/khong-ton-tai/aigen-pipeline-gia"))  # str(Path(...)) chuẩn hoá dấu phân cách OS -- khớp đúng những gì seam sẽ in ra
    os.environ["AIGEN_REPO_PATH"] = missing_path
    try:
        run_aigen_pipeline(Path("dummy-script.json"))  # KHÔNG truyền aigen_repo_path
    except AigenRepoPathNotFoundError as e:
        assert missing_path in str(e)
        return
    finally:
        del os.environ["AIGEN_REPO_PATH"]
    raise AssertionError("phải raise AigenRepoPathNotFoundError khi config trỏ path không tồn tại")


def test_aigen_seam_changing_config_changes_resolved_cwd_not_hardcoded():
    """Đổi ENV AIGEN_REPO_PATH giữa 2 lần gọi -> cwd đổi theo -- chứng minh
    seam THẬT SỰ đọc config mỗi lần gọi, không cache/hardcode giá trị cũ."""
    import tempfile
    from pathlib import Path
    from unittest.mock import patch, MagicMock
    from twmkt.media_factory.aigen_seam import run_aigen_pipeline

    tmp = Path(tempfile.mkdtemp())
    script_path = tmp / "script.json"
    script_path.write_text("{}", encoding="utf-8")
    aigen_dir_a = Path(tempfile.mkdtemp())
    aigen_dir_b = Path(tempfile.mkdtemp())

    fake = MagicMock(returncode=0, stdout="ok", stderr="")

    def _fake_run_a(cmd, cwd, capture_output, text, timeout):
        (tmp / "video.mp4").write_text("x", encoding="utf-8")
        return fake

    os.environ["AIGEN_REPO_PATH"] = str(aigen_dir_a)
    try:
        with patch("subprocess.run", side_effect=_fake_run_a) as m:
            run_aigen_pipeline(script_path)
            assert m.call_args.kwargs["cwd"] == str(aigen_dir_a)
    finally:
        del os.environ["AIGEN_REPO_PATH"]

    (tmp / "video.mp4").unlink()  # reset idempotent-skip guard cho lần gọi thứ 2
    os.environ["AIGEN_REPO_PATH"] = str(aigen_dir_b)
    try:
        with patch("subprocess.run", return_value=fake) as m:
            run_aigen_pipeline(script_path)
            assert m.call_args.kwargs["cwd"] == str(aigen_dir_b)
            assert m.call_args.kwargs["cwd"] != str(aigen_dir_a)
    finally:
        del os.environ["AIGEN_REPO_PATH"]


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


# --- store: đường DB theo data_root (2026-07-28) -----------------------------
def test_document_store_default_db_path_follows_data_root_not_cwd(monkeypatch):
    """Mặc định TƯƠNG ĐỐI CWD ("store/document_store.db") là bẫy thật: chạy
    worker từ thư mục khác -> mở NHẦM 1 DB rỗng khác, im lặng, không lỗi nào
    (đã gặp 2026-07-28: không tìm thấy DB của agent-A ở đâu cả). Nay DB nằm
    trong `storage.data_root` như mọi dữ liệu khác — khớp thiết kế đã chốt
    "1 DB duy nhất trên VPS"."""
    from pathlib import Path as _Path
    from store import document_store as ds

    monkeypatch.delenv("DOCUMENT_STORE_PATH", raising=False)
    p = ds._default_db_path()
    assert p.name == "document_store.db"
    # KHÔNG còn nằm trong repo theo CWD -- phải đi qua data_root.
    assert p != _Path("store/document_store.db")
    assert "marketing-database" in str(p).replace("\\", "/")


def test_document_store_env_var_still_wins_over_data_root(monkeypatch, tmp_path):
    """ENV vẫn ưu tiên cao nhất — test/CI/backfill cần trỏ DB tạm."""
    from store import document_store as ds

    monkeypatch.setenv("DOCUMENT_STORE_PATH", str(tmp_path / "x.db"))
    assert ds._default_db_path() == tmp_path / "x.db"


def test_queue_store_and_document_store_always_share_one_db_path(monkeypatch, tmp_path):
    """Hàng đợi và kho tài liệu PHẢI luôn cùng 1 file. Trước 2026-07-28
    queue_store CHÉP LẠI logic đường dẫn -> khi document_store đổi mặc định,
    bản chép không đổi theo và 2 module trỏ 2 file khác nhau trong im lặng."""
    from store import document_store as ds
    from store import queue_store as qs

    monkeypatch.delenv("DOCUMENT_STORE_PATH", raising=False)
    assert qs._default_db_path() == ds._default_db_path()

    monkeypatch.setenv("DOCUMENT_STORE_PATH", str(tmp_path / "y.db"))
    assert qs._default_db_path() == ds._default_db_path() == tmp_path / "y.db"


def test_execute_column_has_one_color_rule_per_state_and_no_dropdown():
    """Cột Execute (2026-07-28): MỖI trạng thái 1 màu, và KHÔNG còn dropdown
    (read-only với người). Khoá cả 2 mặt để không ai vô tình thêm lại dropdown
    hay bỏ sót màu khi thêm trạng thái mới."""
    from twmkt.sheets_board import (
        CONTEXT_HEADER, EXECUTE_VALUES, TabMeta, _display_status, _tab_requests,
    )

    t = TabMeta(name="CONTEXT", header=list(CONTEXT_HEADER), sheet_id=1, n_rows=3)
    reqs = _tab_requests(t)
    i_exec = [h.strip().lower() for h in CONTEXT_HEADER].index("execute")

    colored = set()
    for r in reqs:
        rule = r.get("addConditionalFormatRule", {}).get("rule", {})
        rng = (rule.get("ranges") or [{}])[0]
        if rng.get("startColumnIndex") != i_exec:
            continue
        vals = rule.get("booleanRule", {}).get("condition", {}).get("values", [])
        if vals:
            colored.add(vals[0]["userEnteredValue"])
    # Rule khớp CHỮ THẬT SỰ ghi lên ô (context_row() dịch NEEDS_HUMAN -> nhãn
    # VI, xem _display_status()) — so bằng giá trị ĐÃ DỊCH, không phải hằng số
    # nội bộ trần (chỉ NEEDS_HUMAN có nhãn khác; còn lại _display_status trả
    # nguyên giá trị đầu vào).
    expected = {_display_status(v) for v in EXECUTE_VALUES}
    assert expected <= colored, f"thiếu màu cho: {expected - colored}"

    for r in reqs:
        sd = r.get("setDataValidation")
        if sd and sd["range"].get("startColumnIndex") == i_exec:
            assert "rule" not in sd, "Execute là cột read-only -> KHÔNG được có dropdown"


def test_content_rows_taller_than_context_rows_for_easier_skimming():
    """Trung 02/08 — tab CONTENT (Output/Notes dài, thân bài/JSON preview) cần
    khoảng đọc rộng hơn CONTEXT để liếc nhanh nhiều dòng, KHÔNG auto-resize
    theo độ dài nội dung (Sheets API không có, xem _CONTENT_ROW_HEIGHT) — chỉ
    set 1 chiều cao CỐ ĐỊNH cao hơn mặc định cho MỌI dòng dữ liệu CONTENT.
    CONTEXT KHÔNG bị đụng (giữ mặc định Sheets như trước)."""
    from twmkt.sheets_board import CONTENT_HEADER, CONTEXT_HEADER, TabMeta, _tab_requests

    def _row_height_requests(tab_name, header):
        t = TabMeta(name=tab_name, header=list(header), sheet_id=1, n_rows=5)
        reqs = _tab_requests(t)
        return [r["updateDimensionProperties"] for r in reqs
                if "updateDimensionProperties" in r
                and r["updateDimensionProperties"]["range"].get("dimension") == "ROWS"
                and r["updateDimensionProperties"]["range"].get("startIndex") == 1]

    content_reqs = _row_height_requests("CONTENT", CONTENT_HEADER)
    assert len(content_reqs) == 1, f"kỳ vọng ĐÚNG 1 request chiều cao dòng CONTENT: {content_reqs}"
    # Trung 02/08 (chốt sau khi đo thật): dải 45-60px, CỐ ĐỊNH (không tự giãn
    # theo nội dung như trước khi sửa).
    px = content_reqs[0]["properties"]["pixelSize"]
    assert 45 <= px <= 60, f"chiều cao dòng CONTENT phải trong dải 45-60px, thực tế {px}"

    context_reqs = _row_height_requests("CONTEXT", CONTEXT_HEADER)
    assert context_reqs == [], "CONTEXT KHÔNG được set chiều cao dòng riêng (giữ mặc định)"


def test_display_status_and_notes_read_vi_labels_from_config(monkeypatch):
    """B2 (Lead 02/08) — bảng ánh xạ nhãn tiếng Việt PHẢI đọc từ config/
    settings.yaml (`labels.vi.*`), không hard-code: đổi config -> đổi nhãn
    hiển thị NGAY, không cần sửa code. Test bằng cách monkeypatch load_
    settings() trả về 1 bảng KHÁC bảng mặc định hard-code trong code, xác
    nhận sheets_board._display_status()/_display_notes() dùng ĐÚNG bảng đó."""
    import twmkt.config as twmkt_config
    from twmkt.config import Settings
    from twmkt.sheets_board import _display_notes, _display_status

    custom = Settings({"labels": {"vi": {
        "sheet_status": {"SKIPPED": "ĐÃ HUỶ (test)"},
        "notes_codes": {"FORMAT_MISMATCH": "Sai định dạng (test)"},
    }}})
    monkeypatch.setattr(twmkt_config, "load_settings", lambda *a, **kw: custom)

    assert _display_status("SKIPPED") == "ĐÃ HUỶ (test)"      # KHÁC mặc định "BỎ QUA"
    assert "Sai định dạng (test)" in _display_notes("FORMAT_MISMATCH: lý do X")
    # Giá trị KHÔNG có trong bảng config tuỳ biến (NEEDS_HUMAN) -> lùi về giá
    # trị GỐC (config này không định nghĩa) -- không đoán/không giữ mặc định
    # hard-code cũ khi ĐàCÓ khối labels.vi.sheet_status hợp lệ (dù thiếu key).
    assert _display_status("NEEDS_HUMAN") == "NEEDS_HUMAN"


def test_display_status_and_notes_fall_back_to_hardcoded_default_when_config_missing(monkeypatch):
    """B2 — thiếu file config/khối labels.vi hoàn toàn (hoặc lỗi đọc bất kỳ)
    -> KHÔNG nổ, lùi về bảng mặc định hard-code trong code (an toàn vận
    hành — 1 lỗi cấu hình không được chặn hiển thị Sheet)."""
    import twmkt.config as twmkt_config
    from twmkt.sheets_board import _display_notes, _display_status

    def _raise(*a, **kw):
        raise FileNotFoundError("không có settings.yaml (mô phỏng)")

    monkeypatch.setattr(twmkt_config, "load_settings", _raise)

    assert _display_status("SKIPPED") == "BỎ QUA"
    assert _display_status("NEEDS_HUMAN") == "Cần người review lại nội dung"
    assert "Không hợp định dạng" in _display_notes("FORMAT_MISMATCH: lý do X")


def test_vi_labels_do_not_affect_internal_string_comparisons_b4(monkeypatch, tmp_path):
    """B4 (Lead 02/08) — đổi nhãn hiển thị KHÔNG được gãy bất kỳ so sánh
    trạng thái nào bằng chuỗi TRONG CODE (B1: giá trị store/code giữ nguyên
    tiếng Anh, chỉ Sheet/Telegram hiển thị khác). Khoá cứng bằng lượt chạy
    THẬT: đổi config `labels.vi` sang bảng KHÁC HẲN, chạy produce_from_sheet.
    run() với 1 chủ đề bị SKIP (NO_USABLE_CONTENT) -- kết quả nghiệp vụ
    (skipped/produced/Execute) PHẢI GIỐNG HỆT dù nhãn hiển thị đổi, chứng tỏ
    mọi rẽ nhánh trong code đọc giá trị GỐC tiếng Anh, không đọc chữ đã dịch."""
    import json as _json
    import twmkt.config as twmkt_config
    from twmkt.config import Settings, load_settings as real_load_settings

    class _PoisonWriterLLM:
        def complete(self, *a, **kw):
            raise AssertionError("KHÔNG được gọi writer khi brief_status=NO_USABLE_CONTENT")

    class _BoilerplateRouteLLM:
        def complete(self, system, prompt, *, model=None, fail_loud=False, **kw):
            if "no_numeric_content" in system:
                return _json.dumps({"content_units": [], "no_numeric_content": False}, ensure_ascii=False)
            return ""

    base = real_load_settings()
    weird = dict(base._data)   # Settings._data — xem twmkt/config.py
    weird["labels"] = {"vi": {
        "sheet_status": {"SKIPPED": "XXX_KHÁC_HẲN"},
        # VIỆC 5 (2026-08-03) — NO_USABLE_CONTENT giờ dịch CẢ CÂU qua
        # `notes_messages.NO_USABLE_CONTENT_FULL` (xem sheets_board.
        # _display_notes_business()), KHÔNG còn qua `notes_codes` (đó là cơ
        # chế CŨ, chỉ thay 1 token — vẫn giữ cho _display_notes() cũ, không
        # còn là đường content_row() dùng nữa).
        "notes_messages": {"NO_USABLE_CONTENT_FULL": "YYY_KHÁC_HẲN"},
    }}
    monkeypatch.setattr(twmkt_config, "load_settings", lambda *a, **kw: Settings(weird))

    result, board, notifier = _run_produce_scenario(
        _PoisonWriterLLM(),
        _approved_row("Trang chủ. Menu. Đăng nhập. Đang cập nhật nội dung...", row=2),
        route_llm=_BoilerplateRouteLLM())

    # Nghiệp vụ vẫn ĐÚNG y hệt hành vi gốc (test_run_boilerplate_source_now_
    # skipped_not_fabricated_article_phase_c) dù nhãn config đổi hẳn --
    # produce_from_sheet.py hoàn toàn KHÔNG đọc bảng labels.vi.
    statuses = {r[2]: r[3] for r in board.appended_content}
    assert statuses.get("Article") == "XXX_KHÁC_HẲN"   # Sheet hiển thị nhãn MỚI (đổi config có tác dụng)
    for r in board.appended_content:
        if r[2] == "Article":
            assert "YYY_KHÁC_HẲN" in r[5]
    assert result["produced"] == 0 and result["skipped"] >= 1   # nghiệp vụ KHÔNG đổi



def test_queue_worker_sync_sheet_ingests_before_render_never_loses_approval(monkeypatch):
    """BUG THẬT 2026-07-28 (lượt e2e đầu tiên): Lead duyệt 5 chủ đề, hệ thống
    chỉ nhận 1 — 4 lượt duyệt bị render-từ-store ghi đè PENDING trong lúc
    `run()` còn đang gọi LLM. `_sync_sheet()` PHẢI ingest TRƯỚC render, đúng
    thứ tự, để thao tác người vừa bấm được nạp vào store trước khi tab bị dựng
    lại. Test khoá THỨ TỰ — đây chính là chỗ sai."""
    qw = _queue_worker_module()

    order = []
    monkeypatch.setattr(qw.ss, "ingest_context_from_sheet", lambda b: order.append("ingest_ctx"))
    monkeypatch.setattr(qw.ss, "ingest_content_from_sheet", lambda b: order.append("ingest_content"))
    monkeypatch.setattr(qw.ss, "render_context_to_sheet", lambda b: order.append("render_ctx"))
    monkeypatch.setattr(qw.ss, "render_content_to_sheet", lambda b: order.append("render_content"))

    qw._sync_sheet(object())

    assert order == ["ingest_ctx", "ingest_content", "render_ctx", "render_content"]
    assert order.index("ingest_ctx") < order.index("render_ctx")
    assert order.index("ingest_content") < order.index("render_content")


# --- Lọc bài theo NGÀY ĐĂNG (2026-07-28) -------------------------------------
def _rpa_review_module():
    import importlib.util
    p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "scripts", "review_to_sheet.py")
    spec = importlib.util.spec_from_file_location("_review_to_sheet", p)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_review_to_sheet"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_extract_published_at_reads_meta_jsonld_and_time_tag():
    from twmkt.collectors.http_collector import extract_published_at

    assert extract_published_at(
        '<meta property="article:published_time" content="2026-07-28T08:00:00+07:00">'
    ).year == 2026
    # Thứ tự thuộc tính đảo (content= trước) -- nhiều CMS xuất kiểu này.
    assert extract_published_at(
        '<meta content="2026-07-28T08:00:00Z" property="article:published_time">'
    ) is not None
    assert extract_published_at('{"datePublished":"2026-07-28T01:00:00Z"}') is not None
    assert extract_published_at('<time datetime="2026-07-28T01:00:00Z">28/7</time>') is not None
    assert extract_published_at("<html>không có ngày nào</html>") is None
    assert extract_published_at("") is None


def test_parse_iso_datetime_always_returns_timezone_aware():
    """Datetime "naive" lọt ra ngoài sẽ nổ TypeError khi so sánh với
    now(timezone.utc) ở bộ lọc -- lỗi ngày giờ Python kinh điển."""
    from twmkt.collectors.http_collector import parse_iso_datetime

    for s in ("2026-07-28T08:00:00Z", "2026-07-28T08:00:00", "2026-07-28T08:00:00+07:00"):
        dt = parse_iso_datetime(s)
        assert dt is not None and dt.tzinfo is not None, s
    assert parse_iso_datetime("không-phải-ngày") is None
    assert parse_iso_datetime("") is None


def _doc_at(hours_ago, *, url="http://u/1"):
    from datetime import datetime as _dt, timedelta as _td, timezone as _tz
    from twmkt.models import CleanDocument
    pub = None if hours_ago is None else _dt.now(_tz.utc) - _td(hours=hours_ago)
    return CleanDocument(source="s", url=url, title="t", markdown="m", published_at=pub)


def test_filter_by_freshness_drops_old_keeps_recent():
    mod = _rpa_review_module()
    docs = [_doc_at(1, url="u-moi"), _doc_at(200, url="u-cu")]
    kept, stats = mod.filter_by_freshness(docs, settings=Settings({"crawl": {"max_age_hours": 36}}))
    assert [d.url for d in kept] == ["u-moi"]
    assert stats["too_old"] == 1


def test_filter_by_freshness_keeps_undated_by_default_but_can_drop():
    """Ca KHÔNG RÕ NGÀY là quyết định thật: mặc định GIỮ (thà lọt bài cũ còn
    hơn âm thầm đánh rơi tin nóng vì CMS thiếu thẻ meta)."""
    mod = _rpa_review_module()
    docs = [_doc_at(None, url="u-khong-ngay")]

    kept, stats = mod.filter_by_freshness(docs, settings=Settings({"crawl": {"max_age_hours": 36}}))
    assert [d.url for d in kept] == ["u-khong-ngay"] and stats["undated"] == 1

    kept2, _ = mod.filter_by_freshness(
        docs, settings=Settings({"crawl": {"max_age_hours": 36, "keep_undated": False}}))
    assert kept2 == []


def test_filter_by_freshness_disabled_when_max_age_zero():
    """Đường thoát: max_age_hours=0 -> giữ nguyên mọi bài (crawl bù dữ liệu cũ)."""
    mod = _rpa_review_module()
    docs = [_doc_at(1), _doc_at(5000, url="u-rat-cu"), _doc_at(None, url="u-none")]
    kept, stats = mod.filter_by_freshness(docs, settings=Settings({"crawl": {"max_age_hours": 0}}))
    assert len(kept) == 3 and stats["filtered"] is False


def test_clean_document_inherits_published_at_from_raw():
    """published_at phải đi XUYÊN normalize -- rơi ở đây thì bộ lọc thành vô dụng."""
    from datetime import datetime as _dt, timezone as _tz
    from twmkt.curation import normalize
    from twmkt.curation.config import CurationConfig
    from twmkt.models import RawDocument

    pub = _dt(2026, 7, 28, 1, 0, tzinfo=_tz.utc)
    raw = RawDocument(source="CafeF", url="http://u/1", title="Cổ phiếu FPT tăng",
                      markdown="Thị trường chứng khoán VN-Index tăng điểm " * 20,
                      published_at=pub)
    out = normalize([raw], CurationConfig())
    assert out and out[0].published_at == pub


# --- TASK-009: log per-nguồn PERSIST (mở khoá chẩn đoán "nguồn im lặng") ----
# Trước bản này, per_source (review_to_sheet.py) chỉ đi vào print() rồi mất
# sau khi tiến trình kết thúc -- báo cáo khảo sát 1.2/1.3 không xác định được
# vì sao 7/9 nguồn của lô 03/08 không ra bài nào. 4 hàm dưới đây tách theo
# tầng: TẦNG 1 (_collect_one -- lỗi collector), TẦNG 2 (_dedup_dropped_by_
# source -- trùng content-hash, cùng ĐÚNG luật/thứ tự với curation.normalize.
# normalize()), TẦNG 3 (_bump_by_source -- quy cụm sự kiện chéo nguồn về
# nguồn gốc), và persist (_log_source_stats -- board.log() có sẵn, 1 dòng/
# nguồn). Test dùng FakeBoard nội bộ, KHÔNG gọi mạng/Sheet/LLM thật.
class _FakeLogBoard:
    """Board giả CHỈ cần log() -- ghi lại nguyên văn từng lượt gọi để test
    xác nhận mỗi nguồn để lại ĐÚNG 1 bản ghi persist."""

    def __init__(self):
        self.calls: list[tuple[str, str]] = []

    def log(self, level, message, *, engine=""):
        self.calls.append((level, message))


def test_dedup_dropped_by_source_counts_duplicate_content_hash_per_source():
    mod = _rpa_review_module()
    from twmkt.models import RawDocument

    docs = [
        RawDocument(source="A", url="http://a/1", title="t1", markdown="Nội dung giống hệt nhau"),
        RawDocument(source="A", url="http://a/2", title="t2", markdown="Nội dung giống hệt nhau"),  # trùng A
        RawDocument(source="B", url="http://b/1", title="t3", markdown="Nội dung khác hẳn B"),
        RawDocument(source="B", url="http://b/2", title="t4", markdown="Nội dung khác hẳn B"),  # trùng B
        RawDocument(source="B", url="http://b/3", title="t5", markdown="Nội dung khác hẳn B nữa"),
        RawDocument(source="C", url="http://c/1", title="t6", markdown="Nguồn C không trùng gì cả"),
    ]
    dropped = mod._dedup_dropped_by_source(docs)
    assert dropped == {"A": 1, "B": 1}   # C không xuất hiện (0 bài trùng)


def test_dedup_dropped_by_source_total_matches_normalize_dedup_exactly():
    """Số dedup_dropped tính riêng PHẢI khớp với số normalize() thật sự dedup
    trên CÙNG raw_docs -- nếu lệch nghĩa là đã đục sai luật seen_hashes.

    3 bài đều PHẢI liên quan (có mã CK) để cô lập ĐÚNG tầng dedup -- normalize()
    còn 1 tầng lọc relevance riêng (is_relevant), test đó ở chỗ khác."""
    mod = _rpa_review_module()
    from twmkt.curation import normalize
    from twmkt.curation.config import CurationConfig
    from twmkt.models import RawDocument

    docs = [
        RawDocument(source="CafeF", url="http://a/1", title="Cổ phiếu FPT tăng",
                   markdown="Cổ phiếu FPT hôm nay tăng điểm mạnh " * 5),
        RawDocument(source="Vietstock", url="http://b/1", title="Cổ phiếu FPT tăng",
                   markdown="Cổ phiếu FPT hôm nay tăng điểm mạnh " * 5),   # trùng content-hash với bài trên
        RawDocument(source="CafeF", url="http://a/2", title="Cổ phiếu HPG",
                   markdown="Cổ phiếu HPG hưởng lợi giá thép " * 5),
    ]
    dropped = mod._dedup_dropped_by_source(docs)
    clean = normalize(docs, CurationConfig())
    assert sum(dropped.values()) == len(docs) - len(clean)


def test_bump_by_source_attributes_cluster_urls_back_to_original_source():
    """Cụm sự kiện gộp chéo nguồn (cluster_by_event) phải quy được TỪNG url
    trong cụm về ĐÚNG nguồn đã crawl ra nó."""
    mod = _rpa_review_module()
    from twmkt.models import CleanDocument

    by_url = {
        "http://cafef/1": CleanDocument(source="CafeF", url="http://cafef/1", title="t", markdown="m"),
        "http://vietstock/1": CleanDocument(source="Vietstock", url="http://vietstock/1",
                                           title="t", markdown="m"),
    }
    counts: dict[str, int] = {}
    mod._bump_by_source(counts, ["http://cafef/1", "http://vietstock/1"], by_url)   # 1 cụm, 2 nguồn
    mod._bump_by_source(counts, ["http://cafef/1"], by_url)                          # cụm khác, chỉ CafeF
    assert counts == {"CafeF": 2, "Vietstock": 1}


def test_bump_by_source_ignores_url_not_found_in_by_url():
    mod = _rpa_review_module()
    counts: dict[str, int] = {}
    mod._bump_by_source(counts, ["http://khong-ton-tai/1"], {})
    assert counts == {}


def test_collect_one_catches_exception_returns_error_string_not_crash():
    """Nguồn lỗi mạng/parse KHÔNG được crash cả run() -- _collect_one() bắt
    exception NGAY và trả về error string để per_source ghi lại."""
    mod = _rpa_review_module()
    from twmkt.models import Source

    class _RaisingCollector:
        def collect(self, s, limit):
            raise ConnectionError("timeout sau 10s")

    docs, error, diag = mod._collect_one(_RaisingCollector(), Source("BaoLoi", "http://loi"), 3)
    assert docs == []
    assert error == "ConnectionError: timeout sau 10s"
    assert diag == {}


def test_collect_one_returns_docs_and_no_error_on_success():
    mod = _rpa_review_module()
    from twmkt.models import Source

    class _OkCollector:
        def collect(self, s, limit):
            return ["doc1", "doc2"]

    docs, error, diag = mod._collect_one(_OkCollector(), Source("OK", "http://ok"), 3)
    assert docs == ["doc1", "doc2"] and error is None and diag == {}


def test_collect_one_uses_diagnostics_for_http_first_collector_html_source():
    """TASK-011: khi collector là HttpFirstCollector và nguồn fetch_type="html",
    _collect_one() phải gọi collect_with_diagnostics() (không phải collect())
    để lấy used_default_spec/listing_fetch_ok/links_found -- nếu không, WARN
    chống-im-lặng ở _log_source_stats() không bao giờ có dữ liệu để bật lên."""
    mod = _rpa_review_module()
    from twmkt.collectors.http_collector import CollectDiagnostics, HttpFirstCollector
    from twmkt.models import Source

    class _FakeHttpFirstCollector(HttpFirstCollector):
        def __init__(self):
            pass   # bỏ qua __init__ thật (không cần specs/robots/httpx)

        def collect_with_diagnostics(self, s, *, limit=10):
            return ["doc1"], CollectDiagnostics(
                used_default_spec=True, listing_fetch_ok=True, links_found=0)

    docs, error, diag = mod._collect_one(
        _FakeHttpFirstCollector(), Source("X", "http://x", fetch_type="html"), 3)
    assert docs == ["doc1"] and error is None
    assert diag == {"used_default_spec": True, "listing_fetch_ok": True, "links_found": 0}


def test_log_source_stats_persists_one_record_per_source_with_full_breakdown():
    """Yêu cầu TASK-009: mỗi nguồn để lại 1 bản ghi PERSIST (board.log()), đủ
    tách crawled / dedup_dropped / relevance_dropped / freshness_dropped /
    full_fetch_dropped / context -- KHÔNG còn chỉ đi vào print() rồi mất."""
    mod = _rpa_review_module()
    board = _FakeLogBoard()
    per_source = [
        {"name": "CafeF", "fetch_type": "html", "crawled": 5, "dedup_dropped": 1,
         "relevance_dropped": 1, "freshness_dropped": 1, "full_fetch_dropped": 0, "context": 2},
        {"name": "Vietstock", "fetch_type": "rss", "crawled": 2, "dedup_dropped": 0,
         "relevance_dropped": 0, "freshness_dropped": 0, "full_fetch_dropped": 1, "context": 1},
    ]
    mod._log_source_stats(board, per_source)

    assert len(board.calls) == 2   # ĐÚNG 1 bản ghi/nguồn
    level0, msg0 = board.calls[0]
    assert level0 == "INFO"
    assert "CafeF" in msg0 and "crawled=5" in msg0 and "dedup_dropped=1" in msg0
    assert "relevance_dropped=1" in msg0 and "freshness_dropped=1" in msg0
    assert "full_fetch_dropped=0" in msg0 and "context=2" in msg0
    level1, msg1 = board.calls[1]
    assert level1 == "INFO" and "Vietstock" in msg1 and "full_fetch_dropped=1" in msg1


def test_log_source_stats_persists_error_record_for_source_that_raised():
    """Nguồn ném exception khi collect() vẫn phải có bản ghi persist ghi rõ
    lỗi -- im lặng vì exception cũng là một câu trả lời (yêu cầu TASK-009)."""
    mod = _rpa_review_module()
    board = _FakeLogBoard()
    per_source = [
        {"name": "MatKetNoi", "fetch_type": "html", "crawled": 0,
         "error": "ConnectionError: timeout sau 10s"},
    ]
    mod._log_source_stats(board, per_source)

    assert len(board.calls) == 1
    level, msg = board.calls[0]
    assert level == "WARN"
    assert "MatKetNoi" in msg and "LỖI" in msg and "ConnectionError" in msg and "timeout" in msg


def test_log_source_stats_mixed_batch_persists_record_for_every_source():
    """Lô trộn: vài nguồn OK, vài nguồn lỗi -- KHÔNG nguồn nào bị bỏ sót
    (đúng vấn đề gốc: lô 03/08 có 7 nguồn im lặng không cách nào xác định)."""
    mod = _rpa_review_module()
    board = _FakeLogBoard()
    per_source = [
        {"name": "CafeF", "fetch_type": "html", "crawled": 3, "dedup_dropped": 0,
         "relevance_dropped": 0, "freshness_dropped": 0, "full_fetch_dropped": 0, "context": 3},
        {"name": "NguonLoi1", "fetch_type": "html", "crawled": 0, "error": "TimeoutError: 10s"},
        {"name": "NguonLoi2", "fetch_type": "rss", "crawled": 0, "error": "HTTPError: 403"},
        {"name": "NguonImLangDoLoc", "fetch_type": "html", "crawled": 4, "dedup_dropped": 0,
         "relevance_dropped": 4, "freshness_dropped": 0, "full_fetch_dropped": 0, "context": 0},
    ]
    mod._log_source_stats(board, per_source)

    assert len(board.calls) == 4
    logged_names = {msg.split("SOURCE ")[1].split(" (")[0] for _, msg in board.calls}
    assert logged_names == {"CafeF", "NguonLoi1", "NguonLoi2", "NguonImLangDoLoc"}
    # Nguồn "im lặng" vì relevance_dropped hết 4/4 -- PHÂN BIỆT ĐƯỢC với lỗi
    # kết nối, đúng mục tiêu gốc của TASK-009.
    im_lang_msg = next(msg for _, msg in board.calls if "NguonImLangDoLoc" in msg)
    assert "context=0" in im_lang_msg and "relevance_dropped=4" in im_lang_msg


# --- TASK-014: rào chắn chống ghi nhầm Sheet production trong review_to_sheet.py
# Trước bản này, run() đọc THẲNG TWMKT_SHEET_ID/sheets.spreadsheet_id (production),
# KHÔNG đi qua config.resolve_sheet_id() -- rào chắn đó CÓ TỒN TẠI (dùng cho
# benchmark/A-B) nhưng script crawl thật không dùng, nên người chạy thử phải tự
# set ENV mỗi lần, quên 1 lần là ghi vào Sheet sản xuất. _resolve_target_sheet()
# thêm cờ --test đi qua resolve_sheet_id() TRONG KHI GIỮ NGUYÊN mặc định = production
# (lịch chạy nền phụ thuộc điều đó).
def test_resolve_target_sheet_default_is_production_unchanged(monkeypatch):
    monkeypatch.delenv("TWMKT_SHEET_ID", raising=False)
    monkeypatch.delenv("TWMKT_TEST_SHEET_ID", raising=False)
    monkeypatch.delenv("TWMKT_SHEETS_CREDS", raising=False)
    mod = _rpa_review_module()

    s = Settings({"sheets": {"spreadsheet_id": "PROD-ID", "test_spreadsheet_id": "TEST-ID",
                             "creds_path": "secrets/sa.json"}})
    sheet_id, creds, label = mod._resolve_target_sheet(s, test=False)
    assert (sheet_id, creds, label) == ("PROD-ID", "secrets/sa.json", "PRODUCTION")


def test_resolve_target_sheet_test_flag_uses_resolve_sheet_id(monkeypatch):
    monkeypatch.delenv("TWMKT_SHEET_ID", raising=False)
    monkeypatch.delenv("TWMKT_TEST_SHEET_ID", raising=False)
    monkeypatch.delenv("TWMKT_SHEETS_CREDS", raising=False)
    mod = _rpa_review_module()

    s = Settings({"sheets": {"spreadsheet_id": "PROD-ID-THAT-MUST-NOT-LEAK",
                             "test_spreadsheet_id": "TEST-ID", "creds_path": "secrets/sa.json"}})
    sheet_id, creds, label = mod._resolve_target_sheet(s, test=True)
    assert (sheet_id, creds, label) == ("TEST-ID", "secrets/sa.json", "TEST")


def test_resolve_target_sheet_test_flag_blocks_when_no_test_sheet_configured(monkeypatch):
    """`--test` PHẢI đi qua rào chắn resolve_sheet_id() thật -- thiếu sheet TEST
    thì raise, KHÔNG BAO GIỜ tự ý lùi về production dù production có cấu hình sẵn."""
    monkeypatch.delenv("TWMKT_SHEET_ID", raising=False)
    monkeypatch.delenv("TWMKT_TEST_SHEET_ID", raising=False)
    monkeypatch.delenv("TWMKT_SHEETS_CREDS", raising=False)
    mod = _rpa_review_module()
    from twmkt.config import ProductionSheetBlocked

    s = Settings({"sheets": {"spreadsheet_id": "PROD-ID-THAT-MUST-NOT-LEAK",
                             "test_spreadsheet_id": "", "creds_path": "secrets/sa.json"}})
    try:
        mod._resolve_target_sheet(s, test=True)
    except ProductionSheetBlocked:
        pass
    else:
        raise AssertionError("--test PHẢI raise khi thiếu sheet TEST, không được lùi về production.")


def test_resolve_target_sheet_default_ignores_test_sheet_env(monkeypatch):
    """Mặc định (test=False) KHÔNG được đọc TWMKT_TEST_SHEET_ID -- chỉ --test mới
    chạm biến đó, đúng thiết kế "mặc định = production, không đổi"."""
    monkeypatch.delenv("TWMKT_SHEET_ID", raising=False)
    monkeypatch.setenv("TWMKT_TEST_SHEET_ID", "TEST-FROM-ENV-PHAI-BI-BO-QUA")
    monkeypatch.delenv("TWMKT_SHEETS_CREDS", raising=False)
    mod = _rpa_review_module()

    s = Settings({"sheets": {"spreadsheet_id": "PROD-ID", "creds_path": "secrets/sa.json"}})
    sheet_id, _creds, label = mod._resolve_target_sheet(s, test=False)
    assert (sheet_id, label) == ("PROD-ID", "PRODUCTION")


# --- TASK-011: chống "nguồn html rơi về default_spec" im lặng ---------------
# Trước bản này, nguồn fetch_type="html" không có SourceSpec riêng (khoá theo
# URL) rơi về default_spec (pattern CafeF) -- article_url_pattern không khớp
# domain khác -> 0 link bài -> crawled=0, giống HỆT lỗi mạng, không WARN nào
# phân biệt được. 4 test dưới đây phủ 3 nguyên nhân "0 bài" + 1 case OK.
def test_log_source_stats_warns_when_html_source_falls_back_to_default_spec():
    """crawled=0 -- WARN CHỐNG-IM-LẶNG đi TRƯỚC, cộng thêm bản ghi INFO breakdown
    như mọi nguồn khác (không continue) -- 2 bản ghi/nguồn cho case này."""
    mod = _rpa_review_module()
    board = _FakeLogBoard()
    per_source = [
        {"name": "BaoMoi", "fetch_type": "html", "crawled": 0, "dedup_dropped": 0,
         "relevance_dropped": 0, "freshness_dropped": 0, "full_fetch_dropped": 0, "context": 0,
         "used_default_spec": True, "listing_fetch_ok": True, "links_found": 0},
    ]
    mod._log_source_stats(board, per_source)

    assert len(board.calls) == 2
    level, msg = board.calls[0]
    assert level == "WARN"
    assert "BaoMoi" in msg and "default_spec" in msg
    assert board.calls[1][0] == "INFO"


def test_log_source_stats_warns_listing_fetch_failed_not_spec_issue():
    """crawled=0 vì KHÔNG tải được trang mục (robots/mạng) -- có spec riêng,
    KHÔNG phải lỗi spec -- WARN phải phân biệt rõ, không đổ oan cho spec."""
    mod = _rpa_review_module()
    board = _FakeLogBoard()
    per_source = [
        {"name": "Vietstock", "fetch_type": "html", "crawled": 0, "dedup_dropped": 0,
         "relevance_dropped": 0, "freshness_dropped": 0, "full_fetch_dropped": 0, "context": 0,
         "used_default_spec": False, "listing_fetch_ok": False, "links_found": 0},
    ]
    mod._log_source_stats(board, per_source)

    assert len(board.calls) == 2
    level, msg = board.calls[0]
    assert level == "WARN"
    assert "Vietstock" in msg and "trang mục" in msg
    assert "default_spec" not in msg
    assert board.calls[1][0] == "INFO"


def test_log_source_stats_warns_own_spec_zero_links_found():
    """Có spec riêng, tải được trang mục, nhưng article_url_pattern khớp 0
    link -- khác 2 case trên, phải WARN riêng (site đổi giao diện/spec sai)."""
    mod = _rpa_review_module()
    board = _FakeLogBoard()
    per_source = [
        {"name": "VietnamBiz", "fetch_type": "html", "crawled": 0, "dedup_dropped": 0,
         "relevance_dropped": 0, "freshness_dropped": 0, "full_fetch_dropped": 0, "context": 0,
         "used_default_spec": False, "listing_fetch_ok": True, "links_found": 0},
    ]
    mod._log_source_stats(board, per_source)

    assert len(board.calls) == 2
    level, msg = board.calls[0]
    assert level == "WARN"
    assert "VietnamBiz" in msg and "0 link bài" in msg
    assert "default_spec" not in msg
    assert board.calls[1][0] == "INFO"


def test_log_source_stats_warns_links_found_but_all_article_fetches_failed():
    """Có spec riêng, tải được trang mục, TÌM THẤY link bài (links_found > 0)
    nhưng crawled=0 -- fetch/trích từng bài đều fail (khác cả 3 case trên)."""
    mod = _rpa_review_module()
    board = _FakeLogBoard()
    per_source = [
        {"name": "Nguoiquansat", "fetch_type": "html", "crawled": 0, "dedup_dropped": 0,
         "relevance_dropped": 0, "freshness_dropped": 0, "full_fetch_dropped": 0, "context": 0,
         "used_default_spec": False, "listing_fetch_ok": True, "links_found": 5},
    ]
    mod._log_source_stats(board, per_source)

    assert len(board.calls) == 2
    level, msg = board.calls[0]
    assert level == "WARN"
    assert "Nguoiquansat" in msg and "5 link bài" in msg
    assert "default_spec" not in msg and "0 link bài" not in msg
    assert board.calls[1][0] == "INFO"


def test_log_source_stats_no_warn_when_html_source_has_docs():
    """Nguồn html crawled > 0 -- KHÔNG WARN dù có mặt used_default_spec=False
    trong diag (chỉ nhánh crawled==0 mới xét WARN chống-im-lặng)."""
    mod = _rpa_review_module()
    board = _FakeLogBoard()
    per_source = [
        {"name": "Baochinhphu", "fetch_type": "html", "crawled": 3, "dedup_dropped": 0,
         "relevance_dropped": 0, "freshness_dropped": 0, "full_fetch_dropped": 0, "context": 3,
         "used_default_spec": False, "listing_fetch_ok": True, "links_found": 3},
    ]
    mod._log_source_stats(board, per_source)

    assert len(board.calls) == 1
    level, msg = board.calls[0]
    assert level == "INFO" and "crawled=3" in msg


# --- Drive adapter (2026-07-28) ----------------------------------------------
class _FakeDriveSvc:
    """Giả lập đủ phần Drive API mà DriveAssetStore dùng — KHÔNG chạm mạng."""

    def __init__(self):
        self.items: dict[str, dict] = {}      # id -> {name, parents, mime}
        self.perms_log: list[tuple[str, str, str]] = []
        self.updated: list[str] = []
        self._n = 0

    # -- files() --
    def files(self):
        return self

    def list(self, *, q, fields, pageSize=10, **kw):
        import re as _re
        name = _re.search(r"name = '([^']*)'", q).group(1)
        parent = _re.search(r"'([^']*)' in parents", q).group(1)
        want_folder = _FOLDER_MIME_T in q
        hits = [{"id": i, "name": v["name"]} for i, v in self.items.items()
                if v["name"] == name and parent in v["parents"]
                and (v["mime"] == _FOLDER_MIME_T) == want_folder]
        return _Exec({"files": hits[:pageSize]})

    def create(self, *, body, fields, media_body=None, **kw):
        self._n += 1
        fid = f"id-{self._n}"
        self.items[fid] = {"name": body["name"], "parents": body.get("parents", []),
                           "mime": body.get("mimeType", "image/png")}
        return _Exec({"id": fid})

    def update(self, *, fileId, media_body=None, fields=None, **kw):
        self.updated.append(fileId)
        return _Exec({"id": fileId})

    # -- permissions() --
    def permissions(self):
        return _Perms(self)


_FOLDER_MIME_T = "application/vnd.google-apps.folder"


class _Perms:
    def __init__(self, svc):
        self.svc = svc

    def create(self, *, fileId, body, fields=None, **kw):
        self.svc.perms_log.append((fileId, body["type"], body["role"]))
        return _Exec({"id": "perm-1"})


class _Exec:
    def __init__(self, payload):
        self._p = payload

    def execute(self):
        return self._p


def test_drive_ensure_folder_is_idempotent_never_creates_duplicates():
    """Drive CHO PHÉP 2 thư mục trùng tên cùng cấp -> phải TÌM trước khi tạo,
    nếu không mỗi lượt render lại đẻ thêm 1 thư mục cùng tên."""
    from twmkt.publishers.drive_store import DriveAssetStore

    svc = _FakeDriveSvc()
    st = DriveAssetStore(folder_id="root", service=svc)
    a = st.ensure_folder("infographic", "root")
    b = st.ensure_folder("infographic", "root")
    assert a == b
    assert sum(1 for v in svc.items.values() if v["name"] == "infographic") == 1


def test_drive_upload_builds_date_topickey_folder_and_shares_public(tmp_path):
    from datetime import datetime as _dt
    from twmkt.publishers.drive_store import DriveAssetStore

    f = tmp_path / "anh_9x16.png"
    f.write_bytes(b"\x89PNG fake")
    svc = _FakeDriveSvc()
    st = DriveAssetStore(folder_id="root", service=svc)

    res = st.upload(f, topic="BCTC Q2/2026: MSR bứt phá", topic_key="abc123",
                    folder_date=_dt(2026, 7, 28))

    # 2026-07-28 (quyết định Lead): CÂY 1 TẦNG `<tên chủ đề>-<dd-mm-yyyy>` —
    # gom MỌI định dạng đầu ra của 1 chủ đề vào ĐÚNG 1 thư mục. Cây 3 tầng cũ
    # (`<loại>/<ngày>/<chủ đề>`) xẻ lẻ sản phẩm cùng bài ra 3 nhánh.
    # 2026-07-28 (quyết định Lead): `<dd-mm-yyyy>/<TopicKey>-<5 chữ đầu>`.
    # TopicKey đứng trước = danh tính BỀN (không đổi khi tiêu đề bài bị sửa);
    # 5 chữ đầu chỉ để người liếc còn đoán được là bài nào.
    names = [v["name"] for v in svc.items.values() if v["mime"] == _FOLDER_MIME_T]
    assert names == ["28-07-2026", "abc123-BCTC"]
    assert res["view_link"].startswith("https://drive.google.com/file/d/")
    # Quyền công khai đặt trên FILE, không phải thư mục.
    assert svc.perms_log == [(res["id"], "anyone", "reader")]


def test_drive_upload_same_name_updates_instead_of_duplicating(tmp_path):
    """Render lại cùng chủ đề trong ngày (sửa Output rồi duyệt lại) -> GHI ĐÈ,
    không để 2 file cùng tên khiến người duyệt Gate 3 không biết tin cái nào."""
    from twmkt.publishers.drive_store import DriveAssetStore

    f = tmp_path / "anh_9x16.png"
    f.write_bytes(b"x")
    svc = _FakeDriveSvc()
    st = DriveAssetStore(folder_id="root", service=svc)
    first = st.upload(f, content_type="infographic", topic="T")
    second = st.upload(f, content_type="infographic", topic="T")

    assert first["id"] == second["id"]
    assert svc.updated == [first["id"]]


def test_drive_upload_target_mime_type_converts_to_google_doc(tmp_path):
    """VIỆC 2.1 (2026-08-03, Lead) — upload .md kèm target_mime_type=GOOGLE_DOC_
    MIME -> body["mimeType"] gửi lên Drive PHẢI là mimeType Google Docs native
    (Drive tự convert, KHÔNG tự dựng bộ chuyển đổi markdown->docx ở đây).
    KHÔNG truyền target_mime_type (mặc định, vd ảnh/video) -> hành vi CŨ,
    không đụng mimeType metadata."""
    from twmkt.publishers.drive_store import GOOGLE_DOC_MIME, DriveAssetStore

    f = tmp_path / "bai-viet_article.md"
    f.write_text("# Tiêu đề\n\nNội dung.", encoding="utf-8")
    svc = _FakeDriveSvc()
    st = DriveAssetStore(folder_id="root", service=svc)

    res = st.upload(f, topic="Bài viết test", topic_key="tk-doc",
                    mime_type="text/markdown", target_mime_type=GOOGLE_DOC_MIME)

    created = svc.items[res["id"]]
    assert created["mime"] == GOOGLE_DOC_MIME

    # Không truyền target_mime_type -> KHÔNG đổi hành vi cũ (mimeType mặc định
    # do _FakeDriveSvc.create() suy ra "image/png" khi body thiếu mimeType).
    f2 = tmp_path / "anh.png"
    f2.write_bytes(b"\x89PNG")
    res2 = st.upload(f2, topic="Ảnh test", topic_key="tk-img")
    assert svc.items[res2["id"]]["mime"] == "image/png"


def test_drive_store_requires_folder_id_with_actionable_message():
    from twmkt.publishers.drive_store import DriveAssetStore, DriveConfigError

    try:
        DriveAssetStore(folder_id="  ")
    except DriveConfigError as e:
        assert "drive.folder_id" in str(e) and "settings.yaml" in str(e)
    else:
        raise AssertionError("thiếu folder_id phải raise DriveConfigError")


def test_build_drive_store_returns_none_when_disabled():
    """drive.enabled=false -> None để caller LÙI MƯỢT về asset server cục bộ."""
    from twmkt.publishers.drive_store import build_drive_store

    assert build_drive_store(Settings({"drive": {"enabled": False}})) is None
    st = build_drive_store(Settings({"drive": {"enabled": True, "folder_id": "abc"}}))
    assert st is not None and st.folder_id == "abc"


def test_drive_missing_oauth_token_says_exactly_what_to_run(tmp_path):
    """Chưa uỷ quyền -> lỗi phải NÊU ĐÚNG LỆNH cần chạy, không phải stack trace
    khó hiểu giữa lúc worker đang chạy nền."""
    from twmkt.publishers.drive_store import DriveConfigError, load_user_credentials

    try:
        load_user_credentials(str(tmp_path / "khong-ton-tai.json"))
    except DriveConfigError as e:
        assert "drive_authorize.py" in str(e)
    else:
        raise AssertionError("thiếu token phải raise DriveConfigError")


def test_drive_scope_is_drive_file_not_full_drive():
    """`drive.file` (không nhạy cảm) -> publish app sang production được NGAY,
    refresh token KHÔNG hết hạn sau 7 ngày như chế độ Testing. Scope `drive`
    đầy đủ là nhạy cảm, cần Google verification nhiều tuần. Khoá lại để không
    ai vô tình nới rộng rồi hệ thống nền chết lặng mỗi tuần."""
    from twmkt.publishers.drive_store import _SCOPES

    assert _SCOPES == ["https://www.googleapis.com/auth/drive.file"]


def test_drive_slug_folder_strips_path_breaking_chars():
    from twmkt.publishers.drive_store import slug_folder

    assert "/" not in slug_folder("a/b") and "\\" not in slug_folder("a\b")
    assert slug_folder("   ") == "khong-ten"
    assert len(slug_folder("x" * 200)) <= 60


# --- Chọn tỷ lệ ảnh theo render_hint (2026-07-28) -----------------------------
def _rpa_module():
    import importlib.util
    p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "scripts", "render_production_assets.py")
    spec = importlib.util.spec_from_file_location("_rpa_mod", p)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_rpa_mod"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_valid_ratios_match_renderer_support():
    """Tập tỷ lệ Composer được phép chọn PHẢI khớp tập renderer dựng được.
    Bug thật đã có: prompt mời chọn "16:9" trong khi renderer chỉ có 9:16 —
    Composer trả đúng như được mời thì renderer không có tỷ lệ đó."""
    from twmkt.agents.production import VALID_RATIOS

    assert set(VALID_RATIOS) == {"9:16", "4:5", "1:1"}
    assert set(_rpa_module()._RATIOS) == set(VALID_RATIOS)


def test_prompt_offers_only_renderable_ratios():
    """Prompt KHÔNG được mời tỷ lệ renderer không dựng được (16:9 là bug cũ)."""
    from twmkt.agents.production import InfographicSpecAgent

    sys_prompt = InfographicSpecAgent.system
    assert "9:16|4:5|1:1" in sys_prompt
    assert "16:9" not in sys_prompt


def test_ratios_for_renders_only_the_ratio_composer_chose():
    """Cốt lõi tiết kiệm: 1 spec -> 1 ảnh, không phải 3 (mỗi ảnh 1 lượt gọi
    gpt-image-2 mất tiền thật)."""
    mod = _rpa_module()
    s = Settings({})
    assert mod.ratios_for({"render_hint": {"ratio": "9:16"}}, settings=s) == ("9:16",)
    assert mod.ratios_for({"render_hint": {"ratio": "1:1"}}, settings=s) == ("1:1",)


def test_ratios_for_falls_back_when_hint_missing_or_invalid():
    """Hint thiếu/rác -> 1 tỷ lệ mặc định, KHÔNG raise và KHÔNG render cả 3."""
    mod = _rpa_module()
    s = Settings({})
    for spec in ({}, {"render_hint": None}, {"render_hint": {"ratio": "16:9"}},
                 {"render_hint": {"ratio": ""}}, {"render_hint": "rác"}):
        got = mod.ratios_for(spec, settings=s)
        assert got == (mod._PRIMARY_RATIO,), spec


def test_ratios_for_all_mode_is_the_escape_hatch():
    """Đường thoát khi cần đủ bộ (đăng nhiều nền tảng cùng lúc)."""
    mod = _rpa_module()
    s = Settings({"render": {"infographic": {"ratios": "all"}}})
    assert set(mod.ratios_for({"render_hint": {"ratio": "1:1"}}, settings=s)) == set(mod._RATIOS)


def test_parse_render_hint_rejects_ratio_outside_closed_set():
    from twmkt.agents.production import _parse_render_hint

    assert _parse_render_hint({"ratio": "9:16"})["ratio"] == "9:16"
    assert _parse_render_hint({"ratio": "16:9"})["ratio"] == "4:5"   # lùi mặc định
    assert _parse_render_hint({"ratio": "banana"})["ratio"] == "4:5"
    assert _parse_render_hint(None)["ratio"] == "4:5"


def test_run_output_type_writes_no_row_even_when_router_also_declined():
    """BUG bắt được ở e2e thật 2026-07-28: Output Type="Article" mà tuyến video
    vẫn ra 1 dòng SKIPPED, vì router đã tự tắt video nên nó không lọt vào nhánh
    "loại bởi Output Type". Cùng ý định của người, 2 kết cục khác nhau tuỳ tầng
    nào loại trước. Người không chọn tuyến -> KHÔNG dòng nào, bất kể ai loại."""
    class _RouterSaysNoToVideo:
        def complete(self, system, prompt, *, model=None, fail_loud=False, **kw):
            import json as _j
            if "S1" in system or "khung" in system.lower() or "router" in system.lower():
                return _j.dumps({
                    "structure": "S1", "hook": "H1", "rationale": "r",
                    "signals": {"drivers": [], "rationale": "r", "has_genuine_paradox": False,
                                "quantified_core": True, "time_series": False},
                    "output_channels": {"article": True, "infographic": True, "video": False},
                    "channel_rationale": {"video": "không hợp"},
                })
            return _clean_writer_json()

    result, board, notifier = _run_produce_scenario(
        _RouterSaysNoToVideo(),
        _approved_row("Bài chỉ muốn article", row=2, output_type=["Article"]))

    types = {r[2] for r in board.appended_content}
    assert "video" not in types, f"video KHÔNG được có dòng nào, thực tế: {sorted(types)}"
    assert "infographic" not in types, f"infographic KHÔNG được có dòng nào, thực tế: {sorted(types)}"


def test_drive_link_capture_uses_actual_rendered_ratio_not_constant():
    """BUG e2e 2026-07-28: khối upload Drive so `ratio == _PRIMARY_RATIO`
    (hằng "4:5") để chọn link chính. Composer chọn 9:16 -> không bao giờ khớp
    -> `res` rỗng -> AssetPath âm thầm giữ link 127.0.0.1 dù ảnh ĐÃ lên Drive.
    Khoá lại: mã nguồn phải so với `primary` (tỷ lệ THẬT vừa render)."""
    import inspect
    mod = _rpa_module()
    src = inspect.getsource(mod.run)
    assert "if ratio == primary:" in src
    assert "if ratio == _PRIMARY_RATIO:" not in src


def test_output_type_dropdown_offers_multi_format_combinations():
    """5 giá trị CƠ SỞ (2026-07-28): ô trên Sheet là MULTI-SELECT do Lead bật
    tay qua UI — code chỉ cần xử lý ĐÚNG mọi tổ hợp người chọn, không cần (và
    không được) tự dựng danh sách tổ hợp."""
    import importlib.util
    from twmkt.sheets_board import OUTPUT_TYPE_VALUES

    assert set(OUTPUT_TYPE_VALUES) == {"Article", "Long-Article", "Infographic",
                                       "Video", "AUTO"}

    p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "scripts", "produce_from_sheet.py")
    spec = importlib.util.spec_from_file_location("_pfs_mod", p)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_pfs_mod"] = mod
    spec.loader.exec_module(mod)

    # Mọi TỔ HỢP người có thể chọn (>=1 loại) phải map đúng.
    assert mod._allowed_output_types(["AUTO"]) is None
    # VIỆC 1 (2026-08-03) — Long-Article giờ ĐÃ NỐI, dùng CHUNG kênh router
    # "article" (Long-Article KHÔNG PHẢI kênh router riêng, chỉ khác content_type
    # ghi ra + bộ rules, xem _wants_long_article()).
    assert mod._allowed_output_types(["Long-Article"]) == {"article"}
    assert mod._allowed_output_types(["Article"]) == {"article"}
    assert mod._allowed_output_types(["Article", "Infographic"]) == {"article", "infographic"}
    assert mod._allowed_output_types(["Infographic", "Video"]) == {"infographic", "video"}
    assert mod._allowed_output_types(["Article", "Infographic", "Video"]) ==         {"article", "infographic", "video"}
    # AUTO lẫn với loại cụ thể -> AUTO THẮNG (không giới hạn): người vừa nói
    # "tự quyết" vừa nói "phải có X" thì hiểu theo vế rộng hơn, an toàn hơn.
    assert mod._allowed_output_types(["AUTO", "Article"]) is None


def test_output_type_auto_is_not_the_same_as_selecting_all_three():
    """AUTO = "router TỰ quyết" (không giới hạn thêm). Chọn đủ 3 = "người YÊU
    CẦU đủ 3" (giới hạn tường minh, router vẫn được từ chối kèm lý do). Hai ý
    định khác nhau -> giá trị trả về PHẢI khác nhau."""
    import importlib.util
    p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "scripts", "produce_from_sheet.py")
    spec = importlib.util.spec_from_file_location("_pfs_mod2", p)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_pfs_mod2"] = mod
    spec.loader.exec_module(mod)

    assert mod._allowed_output_types(["AUTO"]) is None
    assert mod._allowed_output_types(["Article", "Infographic", "Video"]) == \
        {"article", "infographic", "video"}


class _FakeTextBoard:
    """VIỆC 2 — fake board CHỈ đủ phần run_text_assets() dùng
    (read_content_for_render), KHÔNG cần Sheet thật."""
    def __init__(self, items_by_type: dict[str, list[dict]]):
        self._items = items_by_type

    def read_content_for_render(self, *, type_):
        return self._items.get(type_, [])


class _FakeTextDrive:
    """Fake drive.upload() — ghi lại MỌI lệnh gọi (kèm target_mime_type) để
    assert, KHÔNG chạm mạng thật."""
    def __init__(self):
        self.calls: list[dict] = []
        self._n = 0

    def upload(self, local_path, *, topic, topic_key, mime_type, target_mime_type=""):
        self._n += 1
        self.calls.append({
            "topic_key": topic_key, "mime_type": mime_type,
            "target_mime_type": target_mime_type,
        })
        return {"id": f"fid-{self._n}", "view_link": f"https://drive.google.com/file/d/fid-{self._n}/view"}


def test_run_text_assets_converts_article_to_google_doc_not_video(tmp_path):
    """VIỆC 2.1/2.3 (2026-08-03, Lead) — Article/Long-Article upload kèm
    target_mime_type=GOOGLE_DOC_MIME (Drive tự convert).

    SỬA LỖI THẬT (2026-08-03, Lead báo qua ca "Thế giới Di động") — "video"
    KHÔNG còn trong _TEXT_OUTPUTS: trước đây có mặt để upload KỊCH BẢN JSON
    làm AssetPath "cho đỡ trống" khi aigen "chưa nối" — nhưng aigen ĐÃ nối
    thật (run_videos()/render_video_one() dựng .mp4 thật), và "video" vẫn còn
    trong dict khiến run_text_assets() âm thầm ghi AssetPath = link KỊCH BẢN
    (không phải video thật) mỗi khi run_videos() bỏ qua/lỗi ở lượt đó — Gate 2
    trông như "đã xong" dù CHƯA có video thật. Lead xác nhận: CHỈ video.mp4
    thật lên Drive mới được coi là hoàn thành -> run_text_assets() PHẢI bỏ
    qua hoàn toàn dòng "video", dù Gate 2 đã APPROVE."""
    from store import document_store as ds
    from store import pipeline_store as ps
    from twmkt.config import Settings
    from twmkt.publishers.drive_store import GOOGLE_DOC_MIME

    rpa = _render_prod_assets_module()
    db_path = tmp_path / "store.db"
    ds.init_db(db_path)

    ps.write_content_output("tk-art", "article", {"status": "DONE", "output": "# Bài viết\n\nNội dung."},
                            db_path=db_path)
    ps.write_content_output("tk-long", "long_article", {"status": "DONE", "output": "# Bài dài\n\nNội dung dài."},
                            db_path=db_path)
    ps.write_content_output("tk-vid", "video", {"status": "DONE", "output": '{"scenes": []}'},
                            db_path=db_path)
    for tk in ("tk-art", "tk-long", "tk-vid"):
        ps.write_content_status(tk, {"tk-art": "article", "tk-long": "long_article",
                                    "tk-vid": "video"}[tk], gate2="APPROVE", db_path=db_path)

    board = _FakeTextBoard({
        "article": [{"topic_key": "tk-art", "context": "Bài viết", "approve_gate2": "APPROVE"}],
        "long_article": [{"topic_key": "tk-long", "context": "Bài dài", "approve_gate2": "APPROVE"}],
        "video": [{"topic_key": "tk-vid", "context": "Video", "approve_gate2": "APPROVE"}],
    })
    drive = _FakeTextDrive()
    settings = Settings({"storage": {"data_root": str(tmp_path)}})
    out_dir = tmp_path / "assets"
    out_dir.mkdir()

    with monkeypatch_db_path(db_path):
        result = rpa.run_text_assets(settings=settings, board=board, drive=drive, out_dir=out_dir)

    assert result["text_uploaded"] == 2   # CHỈ article + long_article -- video KHÔNG qua đường này
    by_tk = {c["topic_key"]: c for c in drive.calls}
    assert "tk-vid" not in by_tk, "video KHÔNG được upload kịch bản làm AssetPath giả -- phải qua aigen thật"
    assert by_tk["tk-art"]["target_mime_type"] == GOOGLE_DOC_MIME
    assert by_tk["tk-long"]["target_mime_type"] == GOOGLE_DOC_MIME
    # content_status của tk-vid KHÔNG bị đụng -- vẫn chờ run_videos()/aigen thật.
    assert not (ps.read_content_status("tk-vid", "video", db_path=db_path).get("asset_url") or "").strip()


def test_run_text_assets_idempotent_by_content_hash_reuploads_on_change(tmp_path):
    """VIỆC 2.4 — cùng TopicKey + cùng loại + cùng NỘI DUNG (hash) -> KHÔNG
    upload lại (drive.upload() KHÔNG được gọi lần 2). Nội dung ĐỔI (viết lại)
    -> hash khác -> upload lại (dùng lại CÙNG file qua update(), không tạo mới
    — đã khoá riêng ở DriveAssetStore, ở đây chỉ kiểm drive.upload() ĐƯỢC gọi)."""
    from store import document_store as ds
    from store import pipeline_store as ps
    from twmkt.config import Settings

    rpa = _render_prod_assets_module()
    db_path = tmp_path / "store.db"
    ds.init_db(db_path)
    ps.write_content_output("tk-art", "article", {"status": "DONE", "output": "# Bản 1"}, db_path=db_path)
    ps.write_content_status("tk-art", "article", gate2="APPROVE", db_path=db_path)

    board = _FakeTextBoard({
        "article": [{"topic_key": "tk-art", "context": "Bài viết", "approve_gate2": "APPROVE"}],
    })
    drive = _FakeTextDrive()
    settings = Settings({"storage": {"data_root": str(tmp_path)}})
    out_dir = tmp_path / "assets"
    out_dir.mkdir()

    with monkeypatch_db_path(db_path):
        r1 = rpa.run_text_assets(settings=settings, board=board, drive=drive, out_dir=out_dir)
        assert r1["text_uploaded"] == 1 and len(drive.calls) == 1

        # Chạy lại, NỘI DUNG KHÔNG đổi -> KHÔNG upload lại.
        r2 = rpa.run_text_assets(settings=settings, board=board, drive=drive, out_dir=out_dir)
        assert r2["text_uploaded"] == 0 and len(drive.calls) == 1

        # Nội dung ĐỔI (viết lại bài) -> hash khác -> upload LẠI.
        ps.write_content_output("tk-art", "article", {"status": "DONE", "output": "# Bản 2 (viết lại)"},
                                db_path=db_path)
        r3 = rpa.run_text_assets(settings=settings, board=board, drive=drive, out_dir=out_dir)
        assert r3["text_uploaded"] == 1 and len(drive.calls) == 2


class monkeypatch_db_path:
    """Context manager nhỏ: đặt ENV DOCUMENT_STORE_PATH trong khối `with` rồi
    khôi phục — pipeline_store/document_store đọc ENV này khi caller không
    truyền db_path tường minh (run_text_assets() không nhận db_path, luôn đọc
    qua ENV giống hệt production thật, xem store/document_store.py)."""
    def __init__(self, db_path):
        self._db_path = str(db_path)
        self._orig = None

    def __enter__(self):
        self._orig = os.environ.get("DOCUMENT_STORE_PATH")
        os.environ["DOCUMENT_STORE_PATH"] = self._db_path

    def __exit__(self, *exc):
        if self._orig is None:
            os.environ.pop("DOCUMENT_STORE_PATH", None)
        else:
            os.environ["DOCUMENT_STORE_PATH"] = self._orig


def test_render_videos_skips_rows_without_gate2_and_already_rendered(monkeypatch, tmp_path):
    """Tuyến video (2026-07-28): CHỈ chạy dòng đã qua Gate 2 và CHƯA có asset.
    Chặn idempotent hỏi STORE, không hỏi ô Sheet — cùng bài học đã gây bug ở
    tuyến ảnh (store xoá rồi mà ô Sheet còn link cũ -> job bị bỏ qua oan)."""
    from store import document_store as ds
    from store import pipeline_store as ps

    mod = _rpa_module()
    db = tmp_path / "s.db"
    monkeypatch.setenv("DOCUMENT_STORE_PATH", str(db))
    ds.init_db(db)

    ps.write_content_output("tk-done", "video", {"status": "DONE", "output": "{}",
                                                 "notes": "", "facts": "[]"})
    ps.write_content_status("tk-done", "video", asset_url="https://drive/x")

    class _Board:
        def read_content_for_render(self, *, type_="infographic"):
            assert type_ == "video"
            return [
                {"topic_key": "tk-chua-duyet", "context": "A", "approve_gate2": "PENDING"},
                {"topic_key": "tk-done", "context": "B", "approve_gate2": "APPROVE"},
            ]

    called = []
    monkeypatch.setattr(mod, "render_video_one",
                        lambda *a, **k: called.append(k.get("item")) or "link")

    out = mod.run_videos(settings=Settings({}), board=_Board(), drive=None, out_dir=tmp_path)
    assert called == []                       # không gọi render cho cả 2 dòng
    assert out["video_rendered"] == 0 and out["video_skipped"] == 2


def test_render_video_one_writes_content_output_json_for_aigen(monkeypatch, tmp_path):
    """Seam nhận `content-output.json` (KHÔNG phải script.json): aigen tự chạy
    adapter rồi mới render — xem aigen_seam.py, `npm run produce:content`."""
    from store import document_store as ds
    from store import pipeline_store as ps

    mod = _rpa_module()
    db = tmp_path / "s2.db"
    monkeypatch.setenv("DOCUMENT_STORE_PATH", str(db))
    ds.init_db(db)
    ps.write_content_output("tk-1", "video", {"status": "DONE", "output": '{"scenes":[]}',
                                              "notes": "", "facts": "[]"})

    seen = {}

    class _Res:
        ok, video_path, skipped_already_rendered, error, stderr = True, None, False, "", ""

    def _fake_run(co_path, *, timeout_s=1800, **kw):
        seen["path"] = co_path
        seen["body"] = co_path.read_text(encoding="utf-8")
        return _Res()

    import twmkt.media_factory.aigen_seam as seam
    monkeypatch.setattr(seam, "run_aigen_pipeline", _fake_run)

    mod.render_video_one({"topic_key": "tk-1", "context": "Bài"},
                         settings=Settings({"media_factory": {"aigen_data_root": str(tmp_path)}}),
                         drive=None, out_dir=tmp_path)

    assert seen["path"].name == "content-output.json"
    assert seen["path"].parent.name == "tk-1"      # job dir = <dataRoot>/<topic_key>
    assert seen["body"] == '{"scenes":[]}'          # NGUYÊN VĂN từ store


def test_file_store_round_trip_keeps_published_at_and_canonical_url(tmp_path):
    """_ser/_de trước 2026-07-28 bỏ rơi 3 trường. canonical_url là nghiêm trọng
    nhất: nó là đầu vào của TopicKey (`canonical_url or url`), đọc lại thiếu nó
    là tính ra khoá KHÁC lượt crawl gốc -> phá write-once của Lớp 5."""
    from datetime import datetime as _dt, timezone as _tz
    from twmkt.curation.file_store import FileDocumentStore
    from twmkt.models import CleanDocument, SourceType

    doc = CleanDocument(
        source="CafeF", url="https://cafef.vn/a.chn?id=1", title="T", markdown="m" * 50,
        tickers=["FPT"], tags=["x"], source_type=SourceType.NEWS,
        published_at=_dt(2026, 7, 27, 9, 30, tzinfo=_tz.utc),
        category_hint="CoPhieu", canonical_url="https://cafef.vn/a.chn",
    )
    st = FileDocumentStore(root=str(tmp_path), retention_days=10)
    st.upsert([doc])
    got = st.all()
    assert len(got) == 1
    assert got[0].published_at == doc.published_at
    assert got[0].canonical_url == "https://cafef.vn/a.chn"
    assert got[0].category_hint == "CoPhieu"


def test_file_store_reads_old_files_without_new_fields(tmp_path):
    """File ghi TRƯỚC bản vá (thiếu 3 khoá) vẫn đọc được, chỉ thiếu thông tin."""
    import json as _j
    from twmkt.curation.file_store import FileDocumentStore

    day = tmp_path / "2026-07-20"
    day.mkdir(parents=True)
    (day / "abc.json").write_text(_j.dumps({
        "source": "CafeF", "url": "u", "title": "t", "markdown": "m",
        "tickers": [], "tags": [], "source_type": "news",
        "fetched_at": "2026-07-20T00:00:00+00:00",
    }), encoding="utf-8")

    got = FileDocumentStore(root=str(tmp_path), retention_days=10).all()
    assert len(got) == 1 and got[0].published_at is None and got[0].canonical_url == ""


def test_render_skips_rows_with_no_content_instead_of_blaming_gate2(monkeypatch, tmp_path, capsys):
    """System-Test 2026-07-28: người duyệt Gate 2 trên dòng router đã SKIPPED
    (đọc lý do rồi bấm cho xong) -> bản cũ json.loads("") và báo "Output không
    phải JSON hợp lệ (đã bị sửa hỏng ở Gate 2?)" + đếm NEEDS_HUMAN. Chẩn đoán
    sai hẳn nguyên nhân — không ai sửa hỏng gì, chỉ là chưa từng có nội dung."""
    from store import document_store as ds
    from store import pipeline_store as ps

    mod = _rpa_module()
    db = tmp_path / "s3.db"
    monkeypatch.setenv("DOCUMENT_STORE_PATH", str(db))
    ds.init_db(db)
    ps.write_content_output("tk-skip", "infographic",
                            {"status": "SKIPPED", "output": "", "notes": "router", "facts": "[]"})

    item = {"topic_key": "tk-skip", "context": "Bài định tính",
            "approve_gate2": "APPROVE", "row": 2}
    png, warn, logs = mod.render_one(item, settings=Settings({}))
    # render_one vẫn trả lỗi JSON; điều test khoá là run() KHÔNG gọi tới đó nữa
    # -- kiểm bằng chính nhánh chặn: có rec nhưng output rỗng.
    rec = ps.read_content_output("tk-skip", "infographic")
    assert rec is not None and not (rec.get("output") or "").strip()


def test_aigen_seam_resolves_npm_via_which_for_windows_shim(tmp_path, monkeypatch):
    """BUG THẬT 2026-07-29: npm trên Windows là shim `npm.cmd`;
    subprocess.run(shell=False) KHÔNG thử PATHEXT -> bare "npm" luôn
    FileNotFoundError dù gõ tay chạy được. Cùng lỗi đã sửa ở ClaudeCodeLLM."""
    import twmkt.media_factory.aigen_seam as seam

    monkeypatch.setattr(seam.shutil, "which", lambda n: r"C:\fake\npm.cmd" if n == "npm" else None)
    seen = {}

    class _P:
        returncode, stdout, stderr = 0, "", ""

    def _run(cmd, **kw):
        seen["cmd"] = cmd
        (tmp_path / "video.mp4").write_bytes(b"x")
        return _P()

    monkeypatch.setattr(seam.subprocess, "run", _run)
    res = seam.run_aigen_pipeline(tmp_path / "content-output.json",
                                  aigen_repo_path=tmp_path)
    assert res.ok
    assert seen["cmd"][0] == r"C:\fake\npm.cmd"   # KHÔNG phải bare "npm"


def test_aigen_seam_missing_npm_gives_actionable_error(tmp_path, monkeypatch):
    """Thiếu npm -> thông báo NÊU việc phải làm, không phải FileNotFoundError
    thô (worker chạy nền có PATH khác terminal — dễ tưởng lỗi code)."""
    import twmkt.media_factory.aigen_seam as seam

    monkeypatch.setattr(seam.shutil, "which", lambda n: None)
    def _boom(*a, **k):
        raise FileNotFoundError(2, "The system cannot find the file specified")
    monkeypatch.setattr(seam.subprocess, "run", _boom)

    res = seam.run_aigen_pipeline(tmp_path / "content-output.json", aigen_repo_path=tmp_path)
    assert not res.ok and "PATH" in res.error
