# Foundation — Kiến trúc thực tế đang chạy

> **Tài liệu snapshot.** Mô tả ĐÚNG những gì codebase làm tại thời điểm viết
> (97 test pass, `python tests/test_pipeline.py`). Không phải kế hoạch, không
> phải mong muốn — nếu code khác đi thì tài liệu này SAI và cần re-write.
> **Khi kiến trúc đổi (thêm/bớt module, đổi luồng dữ liệu, đổi contract), hãy
> viết lại toàn bộ file này từ đầu** — đừng vá từng đoạn, dễ lệch với thực tế.

---

## 0. Có HAI luồng thực thi tách biệt trong repo này

Đây là điều quan trọng nhất cần hiểu trước khi đọc phần còn lại — dễ nhầm vì
nhiều module dùng chung (agents/base.py, curation/, knowledge/rag.py...), nhưng
**hai luồng KHÔNG gọi lẫn nhau**:

| | **Luồng A — Sheets Production** (đang dùng thật) | **Luồng B — Offline MVP** (demo/thư viện) |
|---|---|---|
| Entry point | `scripts/review_to_sheet.py` + `scripts/produce_from_sheet.py` | `src/twmkt/demo.py`, `scripts/run_pipeline.py` |
| Điều phối | 2 script độc lập, tự viết logic, KHÔNG dùng `MarketingPipeline` | `orchestrator.MarketingPipeline` (máy trạng thái `Stage` enum) |
| Nghiên cứu | **KHÔNG dùng RAG/Retriever** — dựng `ResearchBrief` tại chỗ từ `CleanDocument` (title làm topic/thesis/key_points, markdown làm evidence) | Có RAG thật: `Retriever.index()` + `ResearcherAgent` truy hồi chunk |
| Sản xuất | `agents/production.py`: `AnalysisWriterAgent` / `VideoScriptAgent` / `InfographicSpecAgent` — nhận `ProductionBrief`, output JSON schema | `agents/producers.py`: `ArticleWriter` / `VideoScripter` / `InfographicDesigner` / `NewsletterBuilder` — nhận `ResearchBrief` + `MarketingHook` |
| Lưu trữ trạng thái | Google Sheet (tab CONTEXT/CONTENT) là nguồn sự thật | `PipelineState` trong bộ nhớ (1 lần chạy) |
| Cổng duyệt | Cột `Status` trên Sheet, người tự đổi tay, KHÔNG có gì lắng nghe real-time | `ApprovalGate.review()` đồng bộ trong `MarketingPipeline.run()` |
| Publish | Chưa làm (dừng ở CONTENT) | `ConsolePublisher` (in ra màn hình) |
| Vì sao tồn tại song song | Đây là hướng **đang phát triển thật**, khớp yêu cầu "Approve → Production → CONTENT" | Scaffold Phase-0 ban đầu (`CLAUDE.md`), giữ lại làm demo `$0`/thư viện tái dùng (`Agent`, `MockLLM`, RAG, guardrail...) |

**Sơ đồ ở mục 1 mô tả Luồng A** (đây là luồng người dùng thực sự tương tác qua
Google Sheet). Luồng B được nhắc gọn ở mục 1.5 để không gây hiểu lầm khi đọc
code và thấy `RAG`/`ResearcherAgent`/`orchestrator.py` vẫn tồn tại và có test.

---

## 1. Sơ đồ luồng thực tế — Luồng A (Sheets Production)

```
config/settings.yaml (sources[]) ── build_sources() ──┐
                                                       ▼
tab SOURCES (Sheet, Enable|Publisher|FeedURL|Type|     ▼
Field|Interval|Priority) ── read_sources() ──► [Source đã sắp theo Priority]
                                                       │
                          scripts/review_to_sheet.py   │
                                                       ▼
                        ┌──────────────────────────────────────────────┐
                        │  TẦNG 1 — PHÁT HIỆN (theo Source.fetch_type) │
                        │  "rss"  → RssCollector   (nhẹ: title+summary)│
                        │  "html" → HttpFirstCollector (full ngay)     │
                        └──────────────────────────────────────────────┘
                                                       │  list[RawDocument]
                                                       ▼
                        ┌──────────────────────────────────────────────┐
                        │  TẦNG 2 — normalize() (curation/normalize.py)│
                        │  dedup content_hash + whitelist mã (VN30/    │
                        │  tickers_full) + lọc liên quan (macro_hits)  │
                        └──────────────────────────────────────────────┘
                                                       │  list[CleanDocument]
                                                       ▼
                        ┌──────────────────────────────────────────────┐
                        │  ENRICH (curation/enrich.py, $0, tất định)   │
                        │  classify() → nhóm (CoPhieu/ChinhSach/...)   │
                        │  marketing_score() + hotness_pct()           │
                        │  cluster_by_event() → gộp sự kiện CHÉO NGUỒN,│
                        │  giữ báo Priority cao nhất làm đại diện       │
                        └──────────────────────────────────────────────┘
                                                       │
                                                       ▼
                        ┌──────────────────────────────────────────────┐
                        │  TẦNG 3 — full-fetch CHỈ đại diện gốc RSS    │
                        │  (HttpFirstCollector.fetch_one) — html đã có │
                        │  full body sẵn từ Tầng 1                      │
                        └──────────────────────────────────────────────┘
                                                       │
                                                       ▼
                        FileDocumentStore.upsert()  (persist — dedup
                        theo NỘI DUNG, partition theo ngày, retention 10d)
                                                       │
                                                       ▼
                        ResearchBrief dựng TẠI CHỖ (KHÔNG qua RAG):
                        topic=thesis=key_points[0]=title, evidence=[markdown[:400]]
                                                       │
                                                       ▼
                        HookAgent(hook_llm).run(brief)   [Sonnet | Claude
                        Code | fallback tất định — xem mục "2 cách điền JSON"]
                                                       │  MarketingHook
                                                       ▼
                        context_row(...) → sort Hot% giảm dần
                        board.replace_context()  [UPSERT: xoá A2:.. rồi ghi lại]
                                                       │
                                                       ▼
                ┌──────────────────────────────────────────────────────┐
                │  tab CONTEXT (Sheet) — Use|Score|Hot%|Group|Topic|    │
                │  Context|Hook|Source|Status|timestamp|tickers|Notes   │
                └──────────────────────────────────────────────────────┘
                                                       │
                                        NGƯỜI DÙNG tự đổi Status = APPROVE
                                     (KHÔNG có gì lắng nghe real-time — chỉ
                                      được đọc khi ai đó CHẠY script kế tiếp)
                                                       │
                                        scripts/produce_from_sheet.py
                                                       ▼
                        board.read_approved_context()  [lọc Status=="APPROVE"]
                                                       │
                                                       ▼
                        fetch_full_evidence()  — full-fetch LẠI thân bài thật
                        (khớp Source đăng ký theo TÊN MIỀN, vì CONTEXT không
                        lưu Publisher) → ProductionBrief.evidence
                                                       │
                                                       ▼
                        (tuỳ chọn) brief.background — Claude Code tự research
                        thêm (WebSearch) khi viết qua --draft/--ingest
                                                       │
                                                       ▼
                ┌──────────────────────────────────────────────────────┐
                │  PRODUCTION — agents/production.py (3 agent)          │
                │  AnalysisWriterAgent  (LLM, schema JSON, article)     │
                │  VideoScriptAgent     (LLM, schema JSON, video)       │
                │  InfographicSpecAgent (TẤT ĐỊNH $0 — số liệu regex    │
                │                        thẳng từ evidence+background)  │
                └──────────────────────────────────────────────────────┘
                                                       │  ContentDraft
                                                       ▼
                        apply_guardrails(draft, evidence, background)
                        - compliance.check(): disclaimer bắt buộc + chặn
                          claim cấm ("chắc chắn lãi", "cam kết lợi nhuận"...)
                        - unsupported_numbers(): mọi số liệu (%, tỷ, triệu...)
                          PHẢI có trong evidence/background — chống bịa số
                        → Status = DONE (sạch) | ERROR (vi phạm)
                                                       │
                                                       ▼
                content_row() → board.append_content_rows()
                + ghi file storage/output/<ngày>/<slug>-<type>.md|.json
                                                       ▼
                ┌──────────────────────────────────────────────────────┐
                │  tab CONTENT (Sheet) — Context|Type|Status|Output|    │
                │  timestamp|Notes                                       │
                └──────────────────────────────────────────────────────┘
                                                       │
                                        NGƯỜI DÙNG xem & duyệt sản phẩm
                                        (cổng 2 — CHƯA có bước Publish)
```

### "2 cách điền JSON" cho Analysis/Video (cùng schema, cùng guardrail)

`produce_from_sheet.py` có **4 chế độ chạy** (không phải 1 luồng cố định):

| Lệnh | Cách điền article/video | Cần gì |
|---|---|---|
| `python scripts/produce_from_sheet.py` | Gọi thẳng `AnthropicLLM` API | `ANTHROPIC_API_KEY` (để dành cho automation 100% không người trông — CLAUDE.md) |
| `... --offline` | Ép `MockLLM` → agent tự rơi về khung tất định | Không cần gì, $0 |
| `... --draft --limit N` | Sinh infographic ngay (tất định); ghi `*.brief.json` + `*.<type>.prompt.md` vào `storage/production_drafts/` để **Claude Code đọc và tự viết** (dùng gói Pro/Max/Team, KHÔNG cần API key riêng) | Phiên Claude Code đang mở |
| `... --ingest` | Đọc `*.article.json`/`*.video.json` Claude Code đã viết, chạy qua **ĐÚNG** `analysis_fields_from_data`/`render_analysis`/`apply_guardrails` như chế độ gọi API — không phân biệt "ai viết" | — |

`--model sonnet|opus` chỉ áp dụng cho chế độ gọi API thẳng (không áp dụng cho
`--draft`/`--ingest`, vì ở đó "model" chính là Claude Code đang chạy phiên đó).

### Không có gì tự động phát hiện Approve/Reject

Đổi `Status` trên Sheet **không kích hoạt gì cả**. Chỉ khi ai đó (người dùng
hoặc Claude Code được yêu cầu) **chạy** `produce_from_sheet.py --draft` thì
script mới quét lại toàn bộ CONTEXT và lọc dòng `APPROVE` chưa có trong CONTENT
(dedup qua `existing_content_keys()`). `REJECT` không được xử lý gì — chỉ đơn
giản không lọt qua bộ lọc.

`src/twmkt/schedule.py` + `scripts/run_scheduler.py` **có thể** lên lịch chạy
`--draft` định kỳ (thuần Python, deterministic) nhưng bước **viết nội dung**
(Claude Code đọc prompt rồi trả lời) vẫn cần một phiên chat đang mở — không
thể chạy tự động 100% bằng cron job ở chế độ hiện tại.

---

## 1.5 Luồng B — Offline MVP (`orchestrator.MarketingPipeline`)

Không đụng Google Sheets (trừ khi `gates.*.type=sheets`, dùng
`SheetsApprovalGate` + tab `ResearchReview`/`ContentReview` — khác hẳn tab
`CONTEXT`/`CONTENT`). Máy trạng thái tất định (`models.Stage` enum), chạy 1
lần trong bộ nhớ (`PipelineState`), có RAG thật:

```
Source[] → Collector.collect() → normalize() → store.upsert() + Retriever.index()
  → ResearcherAgent.run(topic, retriever)  [RAG: retriever.retrieve(topic, k)]
  → HookAgent.run(brief)
  → _gate_research()  [ApprovalGate — Console/Auto/Sheets]
  → all_producers()  [ArticleWriter/VideoScripter/InfographicDesigner/NewsletterBuilder]
  → compliance.apply() mỗi draft
  → _gate_content()  [ApprovalGate]
  → _stage_publish()  [ConsolePublisher]
```

- `src/twmkt/demo.py` (`python -m twmkt.demo`): chạy trọn luồng này với
  `MockCollector` + `MockLLM` + `AutoApproveGate`, $0, không mạng.
- `scripts/run_pipeline.py`: **KHÔNG gọi `MarketingPipeline`** — tự viết lại
   collect→normalize→persist→RAG→Researcher→Hook bằng factory functions trực
  tiếp, rồi **dừng trước Gate 1** (chỉ lưu brief+hook ra `storage/output/`,
  không tạo `ContentDraft` nào). Dùng để "nếm" chất lượng Researcher/Hook thật
  trên dữ liệu crawl thật mà không tốn token Producer.

---

## 2. Danh sách module + vai trò + file path

| Module | File | Vai trò |
|---|---|---|
| **Models** | `src/twmkt/models.py` | Toàn bộ data contract dùng chung (`Source`, `RawDocument`, `CleanDocument`, `ResearchBrief`, `ContentDraft`, `PublishResult`, `PipelineState`, enums `SourceType`/`ContentFormat`/`Stage`/`Decision`) |
| **Config** | `src/twmkt/config.py` | `load_settings()` đọc `config/settings.yaml`, expand `${ENV}`, nạp `secrets/.env` qua `python-dotenv` (`override=False`) |
| **Factory** | `src/twmkt/factory.py` | Điểm hội tụ config-first: chọn LLM (mock/anthropic theo tầng), Gate (console/auto/sheets), Collector (mock/http/crawl4ai, dispatch theo `fetch_type`), Store (memory/file), `llm_status()`/`model_engine_label()` (banner + nhãn Engine) |
| **Curation — normalize** | `src/twmkt/curation/normalize.py` | `normalize()`: dedup content-hash, `extract_tickers()` (whitelist + xử lý mã dễ nhầm theo ngữ cảnh), `is_relevant()` (lọc bài macro theo từ khóa) |
| **Curation — config** | `src/twmkt/curation/config.py` | `CurationConfig.from_settings()`: nạp whitelist/ambiguous/macro keywords từ file |
| **Curation — store** | `src/twmkt/curation/store.py` | `InMemoryStore` (Protocol `DocumentStore`) |
| **Curation — file_store** | `src/twmkt/curation/file_store.py` | `FileDocumentStore`: persist `storage/documents/<YYYY-MM-DD>/<content_hash>.json`, dedup theo NỘI DUNG chéo ngày, retention N ngày |
| **Curation — enrich** | `src/twmkt/curation/enrich.py` | `classify()` (gắn nhóm), `marketing_score()`/`hotness_pct()` (chấm điểm), `cluster_by_event()` (gộp sự kiện chéo nguồn giữ Priority cao), `is_near_duplicate()`/`title_similarity()` |
| **Curation — vn_tickers** | `src/twmkt/curation/vn_tickers.py` | `VALID_TICKERS`: whitelist tĩnh 1526 mã HOSE/HNX/UPCOM (nguồn vnstock) |
| **Knowledge — RAG** | `src/twmkt/knowledge/rag.py` | `chunk_text()`, `HashingEmbedder`, `InMemoryVectorStore`, `Retriever` — **chỉ dùng bởi Luồng B** |
| **Collectors — base** | `src/twmkt/collectors/base.py` | Protocol `Collector` |
| **Collectors — mock** | `src/twmkt/collectors/mock.py` | `MockCollector`: 3 doc mẫu tiếng Việt (có 1 bản trùng để test dedup) |
| **Collectors — rss** | `src/twmkt/collectors/rss_collector.py` | `RssCollector`: đọc RSS 2.0 thuần stdlib, TẦNG 1 (phát hiện nhẹ, không full-fetch) |
| **Collectors — http** | `src/twmkt/collectors/http_collector.py` | `HttpFirstCollector`: httpx+BeautifulSoup, `collect()` (listing→bài) + `fetch_one()` (1 URL biết trước, dùng ở Tầng 3 và Production) |
| **Collectors — crawl4ai** | `src/twmkt/collectors/crawl4ai_collector.py` | `Crawl4aiCollector`: fallback khi nguồn cần JS render (import crawl4ai hoãn) |
| **Collectors — sources** | `src/twmkt/collectors/sources.py` | Registry `SourceConfig` tĩnh — **legacy, không được `factory.py` dùng** (đã thay bằng `settings.yaml: sources[]`) |
| **Agents — base** | `src/twmkt/agents/base.py` | Protocol `LLMClient`, `MockLLM`, `AnthropicLLM` (lùi mượt: thiếu SDK/khóa/lỗi call → trả `""`, không raise), `Agent` (role+system+llm) |
| **Agents — router** | `src/twmkt/agents/router.py` | `LLMRouter`: bọc `LLMClient`, đo token/chi phí (`Usage`), cache theo hash, `budget_usd` cứng (`BudgetExceeded`) |
| **Agents — _jsonparse** | `src/twmkt/agents/_jsonparse.py` | `try_json_object()`: parse JSON từ output LLM, bóc code-fence, lấy `{...}` ngoài cùng — dùng chung bởi Hook + Production |
| **Agents — researcher** | `src/twmkt/agents/researcher.py` | `ResearcherAgent`: truy hồi RAG → `ResearchBrief` — **chỉ dùng bởi Luồng B** |
| **Agents — hook** | `src/twmkt/agents/hook.py` | `HookAgent`: sinh `MarketingHook` (persona sắc + few-shot), fallback tất định dẫn-bằng-số; dùng bởi CẢ 2 luồng |
| **Agents — producers** | `src/twmkt/agents/producers.py` | `ArticleWriter`/`VideoScripter`/`InfographicDesigner`/`NewsletterBuilder` — nhận `ResearchBrief`+`MarketingHook` — **chỉ dùng bởi Luồng B** |
| **Agents — production** | `src/twmkt/agents/production.py` | `AnalysisWriterAgent`/`VideoScriptAgent`/`InfographicSpecAgent` — nhận `ProductionBrief` — **chỉ dùng bởi Luồng A**; `apply_guardrails()`, `unsupported_numbers()`, `domain_of()` |
| **Agents — prompts** | `src/twmkt/agents/prompts.py` | `resolve_prompts()`/`read_prompt_file()`: nạp `prompts/<name>.<version>.md` theo bảng kích hoạt tab PROMPTS |
| **Guardrails** | `src/twmkt/guardrails/compliance.py` | `check()`/`apply()`: chặn cụm từ cấm + bắt buộc disclaimer (dùng bởi cả `ContentDraft` của Luồng A lẫn B) |
| **Approval — gate** | `src/twmkt/approval/gate.py` | Protocol `ApprovalGate`, `AutoApproveGate`, `ConsoleApprovalGate` |
| **Approval — sheets_gate** | `src/twmkt/approval/sheets_gate.py` | `SheetsApprovalGate`: cổng duyệt qua tab `ResearchReview`/`ContentReview` (poll ô Decision) — **chỉ dùng bởi Luồng B khi `gates.*.type=sheets`** |
| **Sheets board** | `src/twmkt/sheets_board.py` | `SheetsBoard`: toàn bộ I/O Google Sheets (10 tab), hàm thuần `*_from_rows()` để test không mạng, `format_board()` (UI idempotent) |
| **Publishers** | `src/twmkt/publishers/base.py` | Protocol `Publisher`, `ConsolePublisher`, `StubPublisher` — **chỉ dùng bởi Luồng B**, Luồng A chưa có bước publish |
| **Orchestrator** | `src/twmkt/orchestrator.py` | `MarketingPipeline` (Luồng B), `PipelineConfig` |
| **Schedule** | `src/twmkt/schedule.py` | `ScheduleConfig`, `Scheduler`, `next_run_at()` (hàm thuần) — lập lịch chạy job (bất kỳ callable), tách khỏi đồng hồ thật để test được |
| **Triage** | `src/twmkt/triage.py` | `score()`/`rank()`/`select()`: chấm điểm liên quan tất định — **hiện không được luồng nào gọi** (dự phòng/thử nghiệm sớm) |
| **Demo** | `src/twmkt/demo.py` | `python -m twmkt.demo` — chạy trọn Luồng B offline |
| **Script — review_to_sheet** | `scripts/review_to_sheet.py` | Crawl thật → CONTEXT (Luồng A, nửa đầu) |
| **Script — produce_from_sheet** | `scripts/produce_from_sheet.py` | CONTEXT APPROVE → CONTENT (Luồng A, nửa sau); 4 chế độ (API/offline/draft/ingest) |
| **Script — run_pipeline** | `scripts/run_pipeline.py` | Luồng B rút gọn, dừng trước Gate 1, lưu `storage/output/` |
| **Script — run_scheduler** | `scripts/run_scheduler.py` | CLI lập lịch (`--once`/`--print-os`/loop nội bộ), job = `review_to_sheet` hoặc `run_pipeline` |
| **Script — build_liquidity_basket** | `scripts/build_liquidity_basket.py` | Dựng `data/tickers.txt` (rổ thanh khoản top-N) từ CSV nội bộ hoặc vnstock |
| **Script — update_tickers** | `scripts/update_tickers.py` | Làm mới `curation/vn_tickers.py` (whitelist đầy đủ) qua vnstock |
| **Script — crawl_one** | `scripts/crawl_one.py` | Tiện ích crawl thử 1 URL (debug selector) |

---

## 3. Data contracts

### `RawDocument` (`models.py`) — output của Collector

```python
@dataclass
class RawDocument:
    source: str                              # tên nguồn, vd "CafeF - Doanh nghiệp"
    url: str
    title: str
    markdown: str                            # thân bài thô (RSS: chỉ summary; HTML: full)
    source_type: SourceType = SourceType.NEWS  # NEWS|DISCLOSURE|IR|OTHER
    fetched_at: datetime = field(default_factory=_now)
    category_hint: str = ""                  # gợi ý Field từ <category> RSS

    @property
    def content_hash(self) -> str: ...       # sha256(title+markdown chuẩn hoá) — key dedup
```
Ví dụ:
```python
RawDocument(source="Vietstock", url="https://vietstock.vn/x.htm",
           title="HPG: Sản lượng thép phục hồi",
           markdown="Tập đoàn Hòa Phát (HPG) ghi nhận sản lượng...",
           source_type=SourceType.NEWS)
```

### `CleanDocument` (`models.py`) — output của `normalize()`

```python
@dataclass
class CleanDocument:
    source: str; url: str; title: str; markdown: str
    tickers: list[str] = field(default_factory=list)   # trích từ whitelist
    tags: list[str] = field(default_factory=list)       # earnings/dividend/operations/margins
    source_type: SourceType = SourceType.NEWS
    fetched_at: datetime = field(default_factory=_now)
    category_hint: str = ""
```
Ví dụ: `CleanDocument(source="CafeF", url="...", title="...", markdown="...", tickers=["HPG"], tags=["operations"])`

### `ResearchBrief` (`models.py`) — dùng bởi CẢ 2 luồng, nhưng dựng KHÁC NHAU

```python
@dataclass
class ResearchBrief:
    topic: str
    tickers: list[str]
    thesis: str                              # 1 câu luận điểm
    key_points: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)   # chunk RAG (Luồng B) hoặc [markdown[:400]] (Luồng A)
    sources: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=_now)
```
- **Luồng A** (`review_to_sheet.py`): dựng tại chỗ, KHÔNG qua RAG —
  `ResearchBrief(topic=c.title, tickers=c.tickers, thesis=c.title, key_points=[c.title], evidence=[c.markdown[:400]])`.
- **Luồng B** (`ResearcherAgent`): `topic` = chủ đề tra cứu, `evidence` = chunk
  truy hồi từ `Retriever`, `thesis` do LLM viết bám evidence (fallback =
  `key_points[0]` nếu LLM rỗng).

### `MarketingHook` (`agents/hook.py`) — output của `HookAgent`

```python
@dataclass
class MarketingHook:
    topic: str
    angle: str                               # góc marketing 1 câu
    headlines: list[str] = field(default_factory=list)   # 3 tiêu đề: dẫn-số/tò-mò/tương-phản
    audience: str = "nhà đầu tư cá nhân"
    emotion: str = "tò mò"
    cta: str = "Theo dõi Turtle Wealth để cập nhật phân tích."
```
Ví dụ (fallback tất định, không LLM):
```python
MarketingHook(topic="HPG lãi quý 3 tăng 40%", angle="Dẫn bằng 40%: HPG lãi quý 3 tăng 40%",
             headlines=["HPG: HPG lãi quý 3 tăng 40%", "Con số 40% nói lên điều gì?",
                       "Điều ít nhà đầu tư để ý phía sau: HPG lãi quý 3 tăng 40%"])
```

### `ContentDraft` (`models.py`) — output của MỌI producer (cả 2 luồng)

```python
@dataclass
class ContentDraft:
    fmt: ContentFormat                       # ARTICLE|INFOGRAPHIC|VIDEO_SCRIPT|NEWSLETTER
    title: str
    body: str                                # markdown, hoặc JSON string (infographic)
    brief_topic: str = ""
    compliance_issues: list[str] = field(default_factory=list)
    approved: bool = False
    created_at: datetime = field(default_factory=_now)

    @property
    def is_clean(self) -> bool: return len(self.compliance_issues) == 0
```
Ở Luồng A, `compliance_issues` do `apply_guardrails()` gán (disclaimer + claim
cấm + số liệu không có trong evidence/background). `is_clean` quyết
`Status = DONE|ERROR` khi ghi tab CONTENT.

### `ProductionBrief` (`agents/production.py`) — đầu vào 3 agent Luồng A

```python
@dataclass
class ProductionBrief:
    title: str                               # CONTEXT.Context (tiêu đề bài)
    hook: str = ""                            # CONTEXT.Hook
    tickers: list[str] = field(default_factory=list)
    group: str = ""                           # CONTEXT.Group
    topic: str = ""                           # CONTEXT.Topic
    url: str = ""                              # CONTEXT.Source (bài chính)
    evidence: str = ""                          # thân bài full-fetch LẠI (chống bịa số)
    background: str = ""                         # bối cảnh Claude Code research thêm (WebSearch)
```
Ví dụ:
```python
ProductionBrief(title="PNJ đang mua, đổi kim cương của khách hàng thế nào?",
                hook="PNJ: PNJ đang mua, đổi kim cương của khách hàng thế nào?",
                tickers=["PNJ"], group="CoPhieu, ViMoVN", topic="CoPhieu",
                url="https://cafef.vn/pnj-...chn",
                evidence="Mã liên quan: PNJ. Gần đây, trên các diễn đàn...")
```

---

## 4. Config map — `settings.yaml` key → module đọc

| Key (dotted) | Module đọc | Dùng để |
|---|---|---|
| `project.*` | — | metadata, không code nào đọc |
| `paths.*` | — | không code nào đọc trực tiếp (dùng `storage.*` thay) |
| `storage.type` | `factory.build_store()` | `file` → `FileDocumentStore`, `memory` → `InMemoryStore` |
| `storage.documents_dir` | `factory.build_store()` → `FileDocumentStore` | thư mục persist CleanDocument |
| `storage.output_dir` | `run_pipeline.py`, `produce_from_sheet.py` | nơi ghi `.md`/`.json` sản phẩm |
| `storage.drafts_dir` | `produce_from_sheet.py` (`run_draft`/`run_ingest`) | hàng chờ Claude Code viết (`*.prompt.md`/`*.json`) |
| `storage.retention_days`, `storage.timezone` | `factory.build_store()` | retention + mốc chia ngày của `FileDocumentStore` |
| `prompts.dir` | `produce_from_sheet.py` → `agents.prompts.resolve_prompts()` | thư mục `prompts/<name>.<version>.md` |
| `sources[]` (list) | `factory.build_sources()` | nguồn crawl (dùng khi tab SOURCES rỗng, hoặc `--from-config`) |
| `crawl.engine` | `factory.build_collector()` | `http` → `HttpFirstCollector`, `crawl4ai` → `Crawl4aiCollector` (khi không truyền `source=`) |
| `crawl.limit_per_source` | `run_pipeline.py`, `produce_from_sheet.py`, `run_scheduler.py` | số bài tối đa/nguồn |
| `crawl.rate_limit_s/jitter_s/timeout_s/max_retries/backoff_base_s/user_agent/respect_robots` | `HttpFirstCollector.from_settings()`, `RssCollector.from_settings()` | hạ tầng mạng lịch sự |
| `crawl.article_url_pattern/title_selector/body_selector/noise_selectors/ticker_box_selector` | `HttpFirstCollector.from_settings()` | selector MẶC ĐỊNH (nguồn tự khai trong `sources[]` override) |
| `curation.tickers_file` | `CurationConfig.from_settings()` | whitelist mã đầy đủ (`data/tickers_full.txt`) |
| `curation.watchlist_file` | `review_to_sheet._watchlist_curation()` | whitelist hẹp cố định (`data/tickers.txt`), ÉP thay `tickers_file` cho Luồng A |
| `curation.ambiguous_file`, `curation.ambiguous_context_window` | `CurationConfig.from_settings()` | mã dễ nhầm (vd GAS) cần ngữ cảnh |
| `curation.relevance.keywords_file/min_macro_keywords` | `CurationConfig.from_settings()` | lọc bài macro 0-mã |
| `curation.groups` | `enrich.groups_from_settings()` | nhóm chủ đề (`classify()`) |
| `curation.score.marketing.*`, `curation.score.hotness.*` | `review_to_sheet._score_weights()` | trọng số `marketing_score()`/`hotness_pct()` |
| `curation.taxonomy` | *(không còn module nào đọc — đã bỏ `classify_field_topic`, xem lịch sử)* | dự phòng, hiện KHÔNG dùng |
| `knowledge.chunk_size/chunk_overlap/embedder/top_k` | `Retriever.from_settings()` | **chỉ Luồng B** |
| `llm.provider` | `factory._build_llm()`, `factory.llm_status()` | `mock`\|`anthropic` |
| `llm.triage_model` | `factory.build_research_llm()`, `factory.llm_status()` | model Researcher (Haiku, tầng rẻ) |
| `llm.hook_model` | `factory.build_hook_llm()`, `factory._hook_model()` | model Hook (mặc định = `content_model`) |
| `llm.content_model` | `factory.build_content_llm()`, `factory.build_llm()` | model Producers (Sonnet, tầng đắt) |
| `llm.max_tokens` | `factory._build_llm()` | giới hạn output |
| `llm.budget_usd` | `factory._budget()` | hạn mức cứng cho `LLMRouter` |
| `producers.hook` | `factory.build_pipeline()` → `PipelineConfig.hook_enabled` | bật/tắt bước Hook — **chỉ Luồng B** |
| `producers.article/infographic/video_script/newsletter` | *(không code nào đọc)* | dự phòng, hiện KHÔNG dùng để bật/tắt producer |
| `gates.research.type`, `gates.content.type` | `factory.build_gate()` | `console`\|`auto`\|`sheets` — **chỉ Luồng B** |
| `sheets.spreadsheet_id/creds_path` | `SheetsBoard.__init__` (qua `_open_board`/script `run()`), `sheets_gate.from_settings()` | kết nối Google Sheets |
| `sheets.research_worksheet/content_worksheet/poll_interval_s/timeout_s/on_timeout` | `sheets_gate.from_settings()` | **chỉ `SheetsApprovalGate` (Luồng B)** |
| `publishers[]` | `factory.build_publishers()` | **chỉ Luồng B** (`ConsolePublisher`) |
| `schedule.*` | `ScheduleConfig.from_settings()` | cấu hình `Scheduler`/`run_scheduler.py` |

---

## 5. Test coverage — 97 test (`python tests/test_pipeline.py`)

| Nhóm | Số test | Tên test |
|---|---:|---|
| **Curation/normalize** | 6 | `test_dedup_removes_duplicate_doc`, `test_ticker_extraction_filters_noise`, `test_curation_whitelist_and_ambiguous`, `test_ambiguous_tokens_do_not_mutually_validate`, `test_relevance_filter_by_macro_keywords`, `test_full_ticker_whitelist_loads_and_includes_vn30` |
| **Knowledge/RAG** | 2 | `test_chunking_overlaps`, `test_rag_retrieves_relevant_doc` |
| **Guardrails/compliance** | 1 | `test_compliance_flags_banned_claim` |
| **Orchestrator (Luồng B)** | 5 | `test_full_pipeline_publishes_when_approved`, `test_research_gate_rejection_saves_tokens`, `test_pipeline_sets_hook_after_run`, `test_hook_disabled_skips_step`, `test_hook_feeds_producers_title_and_cta` |
| **Config** | 4 | `test_load_settings_reads_keys`, `test_settings_expands_env`, `test_load_dotenv_sets_env_without_overriding_shell`, `test_load_dotenv_missing_file_is_noop` |
| **Factory (LLM/gate/collector/store)** | 15 | `test_gate_factory_console_auto_sheets`, `test_gate_factory_rejects_unknown_type`, `test_build_llm_by_provider`, `test_config_built_pipeline_runs_offline`, `test_build_research_llm_offline_and_provider`, `test_build_hook_llm_uses_content_model_sonnet`, `test_build_store_by_type`, `test_build_collector_engine_http_and_crawl4ai`, `test_build_collector_dispatch_by_fetch_type`, `test_build_content_llm_sonnet_router`, `test_build_content_llm_model_override_sonnet_opus`, `test_llm_status_banner_mock_when_provider_not_anthropic`, `test_llm_status_banner_mock_when_anthropic_unavailable`, `test_llm_status_banner_active_when_key_present`, `test_model_engine_label_maps_haiku_sonnet_mock` |
| **HookAgent** | 6 | `test_hook_agent_offline_fallback_is_deterministic`, `test_hook_fallback_uses_article_title_not_raw_topic`, `test_hook_fallback_has_no_generic_market_prefix`, `test_hook_parses_llm_json`, `test_try_json_hardening_fence_and_prose`, `test_hook_agent_stores_last_prompt_and_raw_for_debug` |
| **ResearcherAgent (Luồng B)** | 2 | `test_researcher_prompt_anchors_on_article_titles`, `test_researcher_empty_llm_falls_back_to_article_title` |
| **LLM base/router** | 2 | `test_llm_router_tracks_tokens_cost_and_caches`, `test_anthropic_llm_degrades_gracefully_without_key` |
| **FileDocumentStore** | 3 | `test_file_store_dedup_across_runs`, `test_file_store_day_partition_and_intraday_dedup`, `test_file_store_cross_day_dedup_and_retention_10` |
| **Collectors (crawl4ai/http/rss)** | 7 | `test_crawl4ai_extracts_article_links_from_fake_listing`, `test_http_extract_links_filters_pattern_and_domain`, `test_http_extract_article_parses_and_strips_noise`, `test_http_extract_article_missing_body_returns_empty`, `test_rss_parse_rss_fixture`, `test_rss_collector_collect_maps_items_to_raw_documents`, `test_http_collector_fetch_and_extract_reuses_extract_article` |
| **run_pipeline.py (script)** | 1 | `test_source_stats_counts_kept_rejected_and_tickers` |
| **SheetsBoard (tabs/format/CONTEXT)** | 18 | `test_sheets_sources_from_rows_filters_enable`, `test_sheets_context_row_column_order`, `test_build_format_requests_covers_features_and_is_deterministic`, `test_format_board_smoke_no_network`, `test_write_context_dedup_by_url`, `test_sheets_settings_from_rows_and_priority_groups`, `test_prompt_versions_from_rows_filters_enable`, `test_sheets_board_read_prompt_versions_via_fake_ws`, `test_sheets_context_titles_reads_context_column`, `test_sheets_sort_context_by_hot_noop_without_hot_column`, `test_replace_context_clears_then_rewrites`, `test_sources_from_rows_hardening_skips_bad_url`, `test_sources_from_rows_tolerates_old_header`, `test_engine_for_rss_vs_html`, `test_sheets_log_header_has_engine_column`, `test_sheets_board_log_writes_engine_column`, `test_approved_context_from_rows_filters_and_maps`, `test_content_row_shape` |
| **Prompts (agents/prompts.py)** | 2 | `test_prompts_read_file_and_resolve_overrides`, `test_prompts_v1_files_match_code_defaults_no_drift` |
| **Enrich (classify/score/hot/cluster/dedup)** | 5 | `test_enrich_classify_matches_3_groups`, `test_enrich_hotness_pct_increases_with_priority`, `test_enrich_in_priority_and_marketing_score`, `test_enrich_is_near_duplicate_catches_variants_not_different_titles`, `test_enrich_cluster_by_event_keeps_highest_priority` |
| **Schedule** | 4 | `test_schedule_parse_hhmm_and_config`, `test_next_run_at_interval_and_daily`, `test_scheduler_loop_uses_fake_clock_no_wait`, `test_scheduler_survives_job_error` |
| **Production (agents/production.py + produce_from_sheet.py)** | 14 | `test_production_agents_produce_three_types_clean`, `test_production_agent_graceful_empty_llm`, `test_domain_of_extracts_netloc`, `test_unsupported_numbers_flags_hallucinated_figures`, `test_apply_guardrails_flags_error_on_hallucination`, `test_apply_guardrails_checks_background_too`, `test_analysis_agent_parses_llm_json_schema`, `test_video_agent_parses_llm_json_schema`, `test_infographic_agent_extracts_stats_from_evidence_deterministic`, `test_all_production_agents_applies_prompt_overrides_by_name`, `test_match_source_by_domain_and_fetch_full_evidence_fallback`, `test_prompt_md_includes_system_user_and_ingest_instruction`, `test_prompt_md_requires_research_before_writing`, `test_draft_to_content_draft_matches_llm_path` |
| **TỔNG** | **97** | |

Không có test nào gọi mạng thật/LLM thật — mọi test dùng `MockLLM`/fake
`SheetsBoard`/fixture nội bộ, chạy `$0` bằng `python tests/test_pipeline.py`
hoặc `python -m pytest`.

---

## Ghi chú cho lần viết lại tiếp theo

Khi quay lại re-write file này, kiểm tra trước:
1. `python tests/test_pipeline.py` — số test còn khớp không?
2. `review_to_sheet.py`/`produce_from_sheet.py` có còn là 2 script tách biệt,
   hay đã gộp/đổi luồng?
3. `ResearchBrief` ở Luồng A còn dựng tại chỗ hay đã nối RAG thật?
4. Đã có bước Publish cho Luồng A chưa (hiện dừng ở CONTENT)?
5. `curation.taxonomy`/`producers.article|infographic|video_script|newsletter`
   trong `settings.yaml` — có còn "khai nhưng không ai đọc" không, hay đã nối?
