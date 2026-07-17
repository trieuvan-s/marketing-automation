# MODULE_INDEX.md — Bản đồ code (tra cứu, không phải lịch sử)

> Mỗi dòng: `path` — vai trò (≤1 câu). Cập nhật khi thêm/xoá/đổi vai trò module —
> KHÔNG cần cập nhật khi chỉ sửa logic bên trong 1 file đã liệt kê.
> Lịch sử quyết định + log từng phase: xem `PROJECT_HANDOFF_P5.md` (hoặc
> `docs/HISTORY.md` nếu handoff chưa merge). Quy tắc bất biến: `CLAUDE.md`.

## Bẫy tên đã biết (đọc TRƯỚC khi tìm module theo tên)

| Cặp/nhóm dễ nhầm | Phân biệt |
|---|---|
| `agents/production.py` vs `media_factory/` vs `factory.py` | **production.py** = Content Factory (Milestone (a), sinh ĐẶC TẢ văn bản: bài/video-script/infographic-JSON). **media_factory/** = Production Factory (Phase 5 Gate 3, biến đặc tả thành ẢNH/VIDEO THẬT). **factory.py** = lắp ráp adapter theo `settings.yaml` (DI), không liên quan nội dung/media. |
| `agents/producers.py` vs `agents/production.py` | **producers.py** = Luồng B (offline demo/legacy, 4 agent cũ). **production.py** = Luồng A (Milestone (a), đang dùng thật). Tên gần giống hệt — dễ gõ/import nhầm. |
| `agents/router.py` vs `agents/structure_router.py` vs `agents/route_once.py` | **router.py** = LLMRouter (bọc cost-tracking/budget, dùng ở Luồng B/Hook). **structure_router.py** = StructureRouterAgent (chọn khung viết S1-S5 + hook, Luồng A). **route_once.py** = đóng băng quyết định của structure_router (route 1 lần/chủ đề). |
| `curation/store.py` vs `curation/file_store.py` | **store.py** = DocumentStore Protocol, in-memory (Luồng B). **file_store.py** = FileDocumentStore, persist theo ngày+retention (Luồng A thật). |
| `approval/sheets_gate.py` vs `sheets_board.py` | **sheets_gate.py** = ApprovalGate cũ qua Sheets (Luồng B riêng, 1 worksheet Decision đơn giản). **sheets_board.py** = control-plane 8-tab hiện dùng (Luồng A: CONTEXT/CONTENT/SOURCES/...). Cả hai "sheets" nhưng khác hệ hoàn toàn. |
| `scripts/review_to_sheet.py` | Docstring dòng đầu tự ghi "DEMO khép kín" — **GÂY NHẦM**: đây thực ra là script THU THẬP THẬT của Luồng A, được `system_power_on.py` gọi theo lịch, không phải demo. |

## Collection (thu thập, Luồng A)
- `src/twmkt/collectors/base.py` — `Collector` Protocol, mọi nguồn crawl phải tuân thủ.
- `src/twmkt/collectors/http_collector.py` — `HttpFirstCollector`, full-fetch chính ($0, httpx+BeautifulSoup).
- `src/twmkt/collectors/rss_collector.py` — `RssCollector`, tầng phát hiện nhẹ (title/summary, không full-fetch).
- `src/twmkt/collectors/crawl4ai_collector.py` — `Crawl4aiCollector`, fallback khi trang cần JS render.
- `src/twmkt/collectors/sources.py` — Registry nguồn crawl THẬT (khai báo, không phải logic).
- `src/twmkt/collectors/mock.py` — `MockCollector`, dữ liệu mẫu offline (demo/test).

## Curation (chuẩn hoá, $0, tất định)
- `src/twmkt/curation/normalize.py` — Dedup theo content-hash + trích mã CK + gắn tag.
- `src/twmkt/curation/enrich.py` — Phân nhóm marketing + chấm điểm + gộp trùng chéo nguồn.
- `src/twmkt/curation/config.py` — `CurationConfig` (whitelist mã, từ khoá vĩ mô, ngưỡng liên quan).
- `src/twmkt/curation/keys.py` — **TopicKey** (Lớp 5): danh tính bền = sha256(canonical-URL), write-once + surrogate.
- `src/twmkt/curation/file_store.py` — `FileDocumentStore`, persist CleanDocument theo ngày + retention (Luồng A thật).
- `src/twmkt/curation/store.py` — `DocumentStore` Protocol, bản in-memory (Luồng B).
- `src/twmkt/curation/vn_tickers.py` — Whitelist mã CK VN tĩnh (bake sẵn từ vnstock).

## Content Factory (Milestone (a) — sau Gate 1, sinh ĐẶC TẢ văn bản)
- `src/twmkt/agents/brief.py` — Brief: evidence → `facts[]` (5 shape: scalar/range/delta/entity/entity_list, salience subject/context).
- `src/twmkt/agents/structure_router.py` — `StructureRouterAgent`: chọn khung diễn giải S1-S5 + hook H1-H3.
- `src/twmkt/agents/route_once.py` — Route 1 lần/chủ đề rồi đóng băng `RouterDecision` (chống lệch khung giữa các content-type).
- `src/twmkt/agents/voice.py` — Voice-lock động: lắp system prompt Writer theo `RouterDecision` (đọc `docs/voice_examples.md`).
- `src/twmkt/agents/writer.py` — `run_writer_with_retry()`: facts+decision → bài phân tích (Sonnet), retry + guardrail.
- `src/twmkt/agents/production.py` — 3 agent sản xuất: `AnalysisWriterAgent`/`VideoScriptAgent`/`InfographicSpecAgent` + `apply_guardrails()`/`unsupported_numbers()` (chặn bịa số).
- `src/twmkt/agents/prompts.py` — Nạp system prompt theo phiên bản (tab PROMPTS trên Sheet → `prompts/<name>.<v>.md`).
- `src/twmkt/agents/base.py` — `LLMClient` (Mock/Anthropic/ClaudeCode) + `Agent` base class.
- `src/twmkt/agents/_numeric.py` — Parser số CANONICAL (chống bịa, "AI hiểu ở Brief, CODE phán ở Guardrail").
- `src/twmkt/agents/_jsonparse.py` — Parse JSON object từ output LLM (hardening code-fence/lời dẫn).

## Production Factory (`media_factory/` — Phase 5 Gate 3, biến đặc tả thành MEDIA hoàn chỉnh)
- `src/twmkt/media_factory/spec.py` — `ProductionSpec`/`verify_spec()`: guardrail số LẦN 2 (trước render, sau khi người có thể sửa tay Gate 2).
- `src/twmkt/media_factory/numbers.py` — Chuẩn hoá số viết bằng chữ tiếng Việt (cho `voice_text`, TTS đọc tự nhiên).
- `src/twmkt/render/infographic.py` — Render spec Composer (JSON) → ảnh SVG thật ($0, tất định, brand kit từ `config/brand.yaml`).

## Guardrail
- `src/twmkt/guardrails/compliance.py` — Chặn claim cấm (hứa lợi nhuận...) + yêu cầu disclaimer, chạy trước Gate 2.

## Sheet/Board (control-plane, Luồng A)
- `src/twmkt/sheets_board.py` — `SheetsBoard`: toàn bộ 8 tab (README/SOURCES/SETTINGS/TAXONOMY/PROMPTS/CONTEXT/CONTENT/LOG), upsert theo TopicKey, format/dropdown/merge.

## Config/Infra
- `src/twmkt/config.py` — `load_settings()`, `data_path()` (config-first, data_root ngoài repo).
- `src/twmkt/models.py` — Dataclass dùng chung toàn pipeline (Source, RawDocument, CleanDocument, Fact, ContentDraft...).
- `src/twmkt/factory.py` — Lắp ráp adapter theo settings (điểm hội tụ config-first, DI).
- `src/twmkt/_encoding.py` — Ép UTF-8 stdio (tránh lỗi cp1252 trên Windows).
- `src/twmkt/utils/telegram_notifier.py` — Thông báo Telegram một chiều, non-blocking tuyệt đối.

## Luồng B (offline demo/legacy — KHÔNG dùng cho sản xuất thật, 2 luồng KHÔNG gọi lẫn nhau)
- `src/twmkt/orchestrator.py` — `MarketingPipeline`: máy trạng thái tất định, 2 cổng duyệt.
- `src/twmkt/demo.py` — `python -m twmkt.demo`: demo toàn pipeline offline, $0.
- `src/twmkt/triage.py` — Chấm điểm liên quan để chỉ đẩy top-K doc vào LLM.
- `src/twmkt/knowledge/rag.py` — RAG tối giản offline (chunk + embed local + vector search stdlib).
- `src/twmkt/agents/researcher.py` — `ResearcherAgent`: RAG → `ResearchBrief`.
- `src/twmkt/agents/hook.py` — `HookAgent`: sinh hook marketing (Luồng B).
- `src/twmkt/agents/producers.py` — 4 agent sản xuất Luồng B (KHÁC `agents/production.py` — xem Bẫy tên).
- `src/twmkt/agents/router.py` — `LLMRouter`: bọc cost-tracking/budget cho Luồng B/Hook.
- `src/twmkt/approval/gate.py` — `ApprovalGate` (Auto/Console, demo/test).
- `src/twmkt/approval/sheets_gate.py` — `ApprovalGate` qua Sheets, bản CŨ (KHÁC `sheets_board.py` — xem Bẫy tên).
- `src/twmkt/publishers/base.py` — `ConsolePublisher`/`StubPublisher` — CHƯA có publisher MXH thật.
- `src/twmkt/schedule.py` — `Scheduler` tất định, adapter nhận job callable (dùng bởi cả 2 luồng qua `system_power_on.py`).

## Scripts — vận hành Luồng A (chạy thật/theo lịch)
- `scripts/review_to_sheet.py` — Crawl thật → chuẩn hoá → upsert CONTEXT (xem Bẫy tên: docstring ghi nhầm "DEMO").
- `scripts/produce_from_sheet.py` — CONTEXT Status=APPROVE → sản xuất → CONTENT (`--draft`/`--ingest`/`--offline`/API thật).
- `system_power_on.py` (THƯ MỤC GỐC dự án, không phải `scripts/` — lệnh gọi hệ thống) — Chạy CẢ 2 lịch (crawl + draft) + asset server (tắt mặc định) trong 1 tiến trình, có lock file chống chạy trùng.
- `scripts/run_scheduler.py` — Chạy 1 job theo lịch riêng lẻ (đọc 1 section trong `settings.yaml`).

## Scripts — Lớp 5 (TopicKey)
- `scripts/backfill_topic_keys.py` — Điền/rekey TopicKey cho CONTEXT+CONTENT (write-once mặc định, `--rekey` là ngoại lệ).
- `scripts/dedupe_context.py` — Dọn dòng CONTEXT trùng TopicKey cũ (Fix (a), đã chạy 1 lần trên Sheet thật).
- `scripts/reroute.py` — Owner xoá route-once đã đóng băng để route lại chủ đề.

## Scripts — Production Factory
- `scripts/render_infographic.py` — Render `*-infographic.json` → SVG (thủ công, đường cũ trước Phase 1.3).
- `scripts/render_production_assets.py` — Phase 1.3: render + upsert `AssetPath` theo TopicKey (idempotent) → mở Gate 3.

## Scripts — Benchmark/A-B (Phase 3, KHÔNG ghi Sheet)
- `scripts/golden_evidence.py` — Đảm bảo evidence golden set trong corpus của máy (tra theo TopicKey, không phụ thuộc `_raw/`).
- `scripts/bench_brief.py` — A/B Brief Haiku/Sonnet/Opus trên golden set (6 bài: 5 dương + 1 đối chứng âm).
- `scripts/bench_negative_repeat.py` — Lặp lại N lần đo tần suất salience-miss trên bài đối chứng âm.
- `scripts/bench_writer.py` — A/B Writer Sonnet/Opus (facts[]+RouterDecision cố định, biến duy nhất = model Writer).
- `scripts/ab_voice.py` / `ab_voice2.py` — A/B voice-lock cũ (lịch sử, đã đóng, giữ tham khảo).

## Scripts — Luồng B / dữ liệu tĩnh
- `scripts/run_pipeline.py` — Chạy Luồng B: thu thập → chuẩn hoá → persist → nghiên cứu → hook (đến Gate 1).
- `scripts/crawl_one.py` — Lát cắt dọc crawl4ai 1 nguồn thật ($0).
- `scripts/build_liquidity_basket.py` — Dựng `data/tickers.txt` (rổ mã thanh khoản tốt).
- `scripts/update_tickers.py` — Làm mới whitelist mã CK (`curation/vn_tickers.py`), chạy tay khi cần.

## Config
- `config/settings.yaml` — Cấu hình trung tâm toàn hệ thống (config-first).
- `config/brand.yaml` — Brand kit MỘT NGUỒN (FVA Capital: màu/font/wordmark/disclaimer), tách khỏi settings.yaml có chủ đích.

## Tests
- `tests/test_pipeline.py` — Toàn bộ suite tự động (367 test tại thời điểm viết index này, MockLLM/$0, tất định).
- `tests/golden/*.json` — Golden set: facts người liệt kê tay, THƯỚC ĐO cho benchmark Phase 3 (giữ trong git, tham chiếu theo `topic_key`).
