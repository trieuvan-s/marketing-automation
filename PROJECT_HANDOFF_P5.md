# marketing-automation — Tài liệu bàn giao (Context Handoff) — P5

> Dán file này vào đầu cuộc trò chuyện mới để Claude / Claude Code nắm toàn bộ bối cảnh dự án
> mà không cần đọc lại lịch sử dài. Kế thừa `PROJECT_HANDOFF_P2.md` (đóng Milestone (a)).
> **Cập nhật lần cuối:** đóng **Production Factory Phase 1.0–1.3** (`twmkt.media_factory`:
> ProductionSpec/guardrail lần 2/brand-kit/render+Gate 3). Trước đó: Lớp 5 (TopicKey) + Fix (a).
> **Trạng thái:** Sheet board hội tụ bất kể máy/DB nào crawl. Brand **FVA Capital** đã wire vào
> renderer SVG (`config/brand.yaml`), CTA/persona trong `agents/*.py` CHƯA đổi. CONTENT có thêm
> `Facts`/`AssetPath`/`Gate3`.
>
> **SỬA 2026-07-19 — kiến trúc video đã đổi, dòng trên chỉ còn đúng cho NHÁNH ẢNH.**
> "Production Factory = `twmkt.media_factory`" **KHÔNG còn đúng cho video** — `ProductionScene`
> + guardrail-2 nhánh video đã PORT sang `aigen-pipeline/src/production-spec/` (TypeScript, cùng
> ngôn ngữ với renderer AIGEN). `media_factory/` ở đây giờ CHỈ còn giữ `ProductionBlock` + guardrail
> nhánh ảnh (nhẹ) cho renderer SVG nội bộ — không liên quan AIGEN/video nữa. Bản đồ đầy đủ, khỏi
> nhầm lần nữa: `docs/ARCHITECTURE_MODULES.md`. Kế tiếp: nối thông Content Factory → aigen-pipeline
> (xem `docs/VPS_MIGRATION_BACKLOG.md` A0) hoặc dọn nốt brand cũ còn lại trong prompts/CTA.

---

## 0. QUY TẮC CẬP NHẬT FILE NÀY (bắt buộc, đọc trước khi sửa bất cứ gì)

- **File này PHẢI được cập nhật** (không tạo `PROJECT_HANDOFF_P6.md` mới) mỗi khi:
  1. Một **phase/milestone lớn đóng** (vd đóng xong Production Factory, đóng Gate 3...).
  2. Một **quyết định kiến trúc đã CHỐT ở §4 bị đổi** (hiếm, phải ghi rõ lý do đổi).
  3. Phát hiện **lệch giữa doc và code thật** khi khảo lại (giống cách P5 này khảo P2) — sửa NGAY
     phần lệch, không để dồn.
  4. Một khoản **nợ kỹ thuật ở §6 được trả** hoặc phát sinh nợ mới.
- Cách cập nhật: đọc code thật trước, KHÔNG sửa theo trí nhớ/giả định — đúng nguyên tắc đã áp
  dụng khi viết bản này (xem §8, "chấm trên output thật").
- Đổi tên file thành `PROJECT_HANDOFF_P<N+1>.md` **CHỈ** khi làm lại toàn bộ Phase A (khảo + đối
  chiếu) như một cột mốc bàn giao lớn — không phải mỗi lần sửa nhỏ.
- Nếu ai đó tạo `PROJECT_HANDOFF_P2.md` như bản này (không nằm trong repo, chỉ chuyển tay qua
  Downloads) — cân nhắc `git add` file này vào `docs/` để không lặp lại tình huống "file tham
  chiếu không tìm thấy trong repo" đã xảy ra khi viết bản P5.

---

## 1. Bối cảnh & brand

**marketing-automation** — hệ tự động hoá marketing cho **FVA Capital** (Finance · Valuation ·
Analysis — "Tăng trưởng bền vững"), nội dung tài chính/đầu tư, tiếng Việt.
- Repo GitHub: `trieuvan-s/marketing-automation` (branch làm việc: `develop` → merge `main`).
- Mục tiêu: **crawl** tin tài chính/vĩ mô → **chuẩn hoá & lưu trữ** → **người duyệt trên Google
  Sheet** → **sản xuất nội dung** (article / infographic / video) → marketing đa kênh.
- Package Python: `twmkt` (trong `src/`). Chạy Python 3.14.

### Brand — CHỐT ở bản P5 này, code CHƯA migrate

- **"FVA Capital" là brand canonical DUY NHẤT** kể từ P5 (logo đã nhận — biểu tượng FVA cách
  điệu + mũi tên tăng trưởng, tông navy/vàng đồng, tagline "Tăng trưởng bền vững"). Thay thế
  "Turtle Wealth VN" và "VEL Capital".
- **"VEL Capital"** — khảo repo: **0 lần xuất hiện** trong code/config/docs. Chưa từng vào code,
  không cần dọn.
- **"Turtle Wealth"** — khảo repo (khi viết bản này): xuất hiện ở **17 file**, gồm cả nội dung
  SINH RA cho người dùng cuối:
  - CTA hard-code: `agents/production.py:81`, `agents/hook.py:15`, `agents/producers.py:80,84,109`.
  - Persona hệ thống: `agents/production.py:240,350`, `agents/hook.py:33`, `prompts/analysis.v1.md`,
    `prompts/video.v1.md`, `docs/voice_examples.md` (tiêu đề file).
  - **Wordmark in thẳng lên MỌI ảnh infographic**: `render/infographic.py:121` (`"TURTLE WEALTH VN"`).
  - `config/settings.yaml`: `project.name = "Turtle Wealth Marketing"`; **`crawl.user_agent`**
    chứa `"TurtleWealthBot/..."` + email cá nhân — User-Agent này được GỬI tới mọi site crawl.
  - `README.md`, `CLAUDE.md`, `docs/foundation.md`, `docs/google_sheets_setup.md`,
    `docs/production_agents_design.md`, `system_power_on.py` (banner khởi động,
    trước đây `scripts/power_on.py` — đã chuyển ra gốc dự án + đổi tên).
  - `models.py`, `sheets_board.py`, `src/twmkt/__init__.py` (docstring module).
- **"FVA Capital"** trước P5: xuất hiện **đúng 1 lần** — `<title>` của `docs/system_design.html`.
  P2.md (§1) từng viết "Turtle Wealth VN / FVA Capital" (song song, CHƯA chốt) và tự ghi ở §14:
  *"Cần chốt: 'FVA Capital' vs 'Turtle Wealth VN' hiển thị thế nào."* — **câu hỏi đó được trả lời
  ở bản P5 này: FVA Capital.**
- **Việc CHƯA làm (ngoài phạm vi P5, task tiếp theo riêng):** đổi toàn bộ 17 file trên sang FVA
  Capital + logo + màu brand. P2.md (§14) đã định vị đúng: *"Branding sống ở tầng RENDER, KHÔNG ở
  tầng spec/nội dung"* — nghĩa là ưu tiên đổi `render/infographic.py` (brand kit + wordmark) và
  `crawl.user_agent` (không nên để tên bot gắn brand cũ đi crawl) trước; CTA/persona trong
  `agents/*.py` và `prompts/*.md` đổi theo sau, ít khẩn cấp hơn vì chỉ ảnh hưởng giọng văn, không
  lộ ra ngoài cùng mức với wordmark trên ảnh.

## 2. Vai trò làm việc (giữ nguyên từ P2)

- **Claude (chat)** = kỹ sư trưởng: thiết kế kiến trúc, review, chịu trách nhiệm chất lượng đầu ra.
- **Claude Code** (Sonnet/Opus, Pro session) = thực thi trực tiếp trên repo.
- **Quy ước đã chứng minh hiệu quả** (áp dụng xuyên suốt Lớp 5 + Fix (a)):
  - Mỗi việc lớn chia **phase, mỗi phase DỪNG-BÁO-CÁO** để review từng lớp trước khi đi tiếp.
  - Ràng buộc chuẩn: **config-first, kèm test, UTF-8, không đổi kiến trúc gate, không thêm vào
    `system_power_on.py` (khi đó còn là `scripts/power_on.py`), không auto-commit.**
  - Test tự động dùng **MockLLM/fake fixture ($0)**; **round-trip/thao tác thật chỉ khi cần xác
    nhận** (vd 1 lần gọi `claude -p` thật, hoặc chạy `--apply` thật trên Sheet sau khi đã dry-run).
  - **Chấm trên OUTPUT/DỮ LIỆU THẬT, không tin "tests pass".** Bài học lặp lại nhiều lần nhất
    (xem §8) — riêng ở Fix (a), việc đọc **hyperlink metadata thật qua `spreadsheets.get`** (thay
    vì tin `get_all_values()`) đã lật ra bug "title-chip" mà không cách nào thấy được nếu chỉ đọc
    text phẳng.

## 3. Kiến trúc tổng thể — Taxonomy 7 mốc

```
Thu thập & Board → Gate 1 (Duyệt Context) → Content Factory (= Milestone (a), ĐÃ CÓ)
   → Gate 2 (Duyệt nội dung) → Production Factory (CHƯA XÂY) → Gate 3 (Duyệt Public) (CHƯA XÂY)
   → Social/Phân phối (CHƯA XÂY)
```

Thuật ngữ 7 mốc này đã có sẵn ở `docs/system_design.html` (mục "Sơ đồ tổng quan", các node
`content_factory`/`production_factory`/`gate3`/`social`) — **KHÔNG xuất hiện trong tên module
Python** (hợp lý: Production Factory/Gate 3/Social chưa xây, chưa có gì để đặt tên code).

**Điểm cốt lõi (đã xác nhận đúng qua code):** Content Factory sinh **đặc tả nội dung** (bài
markdown, kịch bản video, **JSON spec** infographic — `InfographicSpecAgent`,
`agents/production.py`) — **KHÔNG phải media hoàn chỉnh**. Production Factory (chưa xây) mới biến
spec → **media giao được** (ảnh thật, video, bài publish-ready).

**Một ngoại lệ cần biết** (P2 không có thông tin này — phát sinh ở phiên khác): đã có **1 renderer
thủ công, tách biệt pipeline** — `src/twmkt/render/infographic.py` + `scripts/render_infographic.py`
— đọc JSON spec (schema Composer 8-trường: title/subtitle/hero/market/highlights/related/priority/
source) và sinh **ảnh SVG thật** ($0, tất định, brand kit qua `render.infographic.*` trong
`settings.yaml`). Đã khảo `produce_from_sheet.py`/`system_power_on.py`/`review_to_sheet.py`: **0 chỗ
gọi** `render_infographic` — hoàn toàn thủ công, người vận hành phải tự chạy script sau khi duyệt Gate 2.
**Không phải "0% Production Factory"** — có 1 viên gạch nền (SVG, không phải PNG như P2 §14 định
hướng "con đường 1") nhưng CHƯA wire tự động, CHƯA có brand kit FVA, CHƯA làm video. Phiên tiếp nên
kiểm tra viên gạch này TRƯỚC khi xây Production Factory từ đầu, tránh trùng việc.

## 4. Trạng thái module (ĐÃ CÓ / CHƯA XÂY)

| Module | Trạng thái | File chính |
|---|---|---|
| Collectors (rss/html) | ĐÃ CÓ | `collectors/rss_collector.py`, `collectors/http_collector.py` |
| Curation (normalize/enrich/dedup) | ĐÃ CÓ | `curation/normalize.py`, `curation/enrich.py`, `curation/_numeric.py` |
| Corpus (evidence, content-hash) | ĐÃ CÓ | `curation/file_store.py` |
| TopicKey (danh tính chủ đề, canonical-URL hash) | ĐÃ CÓ (Lớp 5) | `curation/keys.py` |
| Sheet board (CONTEXT/CONTENT/SOURCES/...) | ĐÃ CÓ | `sheets_board.py` |
| CONTEXT dedup đọc Sheet (Fix (a)) | ĐÃ CÓ | `sheets_board.py: upsert_context_rows/_context_topic_keys` |
| Dọn dòng trùng cũ (Fix (a) cleanup) | ĐÃ CHẠY 1 LẦN trên Sheet thật | `scripts/dedupe_context.py` |
| Research/Brief (facts[] + canonical_value) | ĐÃ CÓ | `agents/brief.py` |
| Structure Router (S1–S5, output_channels) | ĐÃ CÓ | `agents/structure_router.py` |
| Route-once (đóng băng quyết định) | ĐÃ CÓ | `agents/route_once.py` |
| Voice-lock động | ĐÃ CÓ | `agents/voice.py`, `docs/voice_examples.md` |
| Writer (retry, outcome DONE/FAILED/NEEDS_HUMAN) | ĐÃ CÓ | `agents/writer.py` |
| Guardrail canonical (chặn số bịa) | ĐÃ CÓ | `guardrails/compliance.py`, `curation/_numeric.py` |
| LLM adapter (claude_code/api/mock) | ĐÃ CÓ | `agents/base.py`, `factory.py` |
| Telegram notifier | ĐÃ CÓ (non-blocking) | `utils/telegram_notifier.py` |
| Scheduler (crawl + draft, 1 tiến trình) | ĐÃ CÓ | `system_power_on.py`, `schedule.py` |
| Renderer infographic (SVG) — brand-kit wired | ĐÃ CÓ | `render/infographic.py` (`config/brand.yaml`, `config.load_brand()`) |
| `ProductionBlock`/`Violation` (nhánh ẢNH, schema trung lập vendor) | ĐÃ CÓ | `media_factory/spec.py` |
| `ProductionScene` (nhánh VIDEO) — **ĐÃ MOVE 2026-07-19**, không còn ở Python | ĐÃ CÓ, Ở REPO KHÁC | `aigen-pipeline/src/production-spec/spec.ts` |
| Chuẩn hoá số-chữ tiếng Việt (13,8 tỷ đọc bằng chữ) — bản Python cho ẢNH; bản VIDEO đã port sang TS | ĐÃ CÓ (2 bản, khác repo) | `media_factory/numbers.py` (ẢNH, parser ngược) · `aigen-pipeline/src/production-spec/voice/` (VIDEO, sinh xuôi) |
| Guardrail lần 2 nhánh ẢNH (`verify_spec`, TRƯỚC render, sau khi người sửa Gate 2) | ĐÃ CÓ | `media_factory/spec.py: verify_spec/build_spec_from_content` |
| Guardrail lần 2 nhánh VIDEO — **ĐÃ MOVE 2026-07-19** | ĐÃ CÓ, Ở REPO KHÁC | `aigen-pipeline/src/production-spec/guardrail/` |
| CONTENT.Facts/AssetPath/Gate3 (persist facts[] ra Sheet, KHÔNG data_root) | ĐÃ CÓ | `sheets_board.py` (`content_row`, `facts_to_json/facts_from_json`) |
| Render + upsert asset theo TopicKey (idempotent) → Gate 3 | ĐÃ CÓ | `scripts/render_production_assets.py` |
| Lớp 1–4, 6 (block ngày, khoá cột, sliding window, Manual adapter, validation tập trung) | **CHƯA XÂY** (GÁC, xem §5) | — |
| Production Factory — VIDEO (media hoàn chỉnh cho video, TTS/avatar) | **CHƯA XÂY** (Phase 2) | — |
| PNG export (hiện chỉ SVG — quyết định #4 Phase 1.0, giữ SVG không Playwright) | **CHƯA XÂY**, xem `scripts/render_infographic.py` cũ (thủ công, tách biệt) | — |
| Social/Phân phối (publisher thật) | **CHƯA XÂY** (chỉ `ConsolePublisher` stub) | `publishers/base.py` |
| Story Clustering (StoryKey) | **CHƯA XÂY** (0 tham chiếu trong code) | — |
| Web app (Vite+React/FastAPI) | **CHƯA XÂY** | — |

**Test:** `python tests/test_pipeline.py` → **287/287 pass, 0 xfail** (tại thời điểm viết bản này;
tăng từ 250/250 ở P2 — thêm chủ yếu từ Lớp 5 TopicKey + Fix (a)).

## 5. Quyết định kiến trúc đã CHỐT (mỗi mục kèm lý do + file/hàm thật)

### 5.1 Hai khóa tách bạch (corpus vs board) — CHỐT, không đổi
- **Corpus** (`curation/file_store.py`, `FileDocumentStore`): khóa = **content-hash** (title +
  markdown) — trả lời *"document này đã lưu chưa"* (evidence, phục vụ chống bịa số).
- **Board** (Sheet): khóa = **`TopicKey` = sha256(canonical-URL)** — trả lời *"topic này đã là 1
  dòng chưa"*. Định nghĩa: `curation/keys.py: compute_topic_key()`.
- **Lý do tách:** 2 câu hỏi khác nhau về bản chất. Nếu publisher sửa vài chữ sau khi đã duyệt,
  content-hash đổi (phá liên kết đã có) nhưng URL thường giữ nguyên — dùng content-hash cho
  "topic đã có chưa" sẽ tạo dòng trùng giả mỗi khi bài được publisher chỉnh sửa.
- **Không có join giữa 2 hệ khóa** — cả 2 chỉ tính song song từ CÙNG 1 `CleanDocument`, không tra
  cứu chéo (`review_to_sheet.py`).

### 5.2 `normalize_url` — giữ query định danh, chỉ bỏ tracking — CHỐT
- File: `curation/keys.py: normalize_url()` (dòng 139–168).
- Ép `https`; hạ thường host; bỏ `www.`; bỏ cổng mặc định 80/443; chuẩn hoá percent-encoding; bỏ
  `/` cuối path; bỏ fragment; **CHỈ** bỏ query trong denylist tracking (`utm_*`, `fbclid`, `gclid`,
  ... — cấu hình được qua `sheets.topic_key.tracking_params`), **GIỮ** mọi query khác (vd `?id=`).
- **Lý do:** bản gốc (Phase 1) bỏ HẾT query-string → rủi ro va chạm thật (2 bài khác nhau, khác
  `?id=`, ra CÙNG khóa — sai). Đã sửa ở Phase 1R.

### 5.3 Canonical resolve ở tầng collector, 4 lớp kiểm định — CHỐT
- File: `collectors/http_collector.py: extract_canonical_url()` (dòng 150–187), gọi từ
  `_fetch_and_extract()` (dòng 306–338).
- 4 kiểm định trước khi tin `<link rel="canonical">`: (1) resolve relative→absolute qua base_url
  đã fetch; (2) phải CÙNG HOST (bỏ www trước khi so); (3) reject nếu path rỗng/chỉ `/` (trỏ về
  trang chủ); (4) reject nếu canonical là TIỀN TỐ THẬT SỰ của path bài (dấu hiệu site cấu hình sai
  ở mức chuyên mục). Bất kỳ bước nào fail → `None`, caller lùi về `final_url` — không bỏ bài.
- `models.py: RawDocument` — `url` (URL THẬT đã fetch, KHÔNG BAO GIỜ bị ghi đè) và `canonical_url`
  (field RIÊNG, `""` nếu không có/không qua kiểm định) — 2 field TÁCH BIỆT có chủ đích.

### 5.4 Write-once — CHỐT
- File: `curation/keys.py: assign_topic_key()` (dòng 188–207).
- `existing_key` khác rỗng → trả nguyên, KHÔNG tính lại — dù `url`/`normalize_url()` đổi sau này.
  Dòng không-URL → surrogate `uuid4` (`sur-` prefix) gán MỘT LẦN.
- **TopicKey là định danh THEO-TỪNG-BÀI, TUYỆT ĐỐI không mang tính ngữ nghĩa** (không gom "cùng sự
  kiện, nhiều nguồn" vào 1 khóa). Gom tin nhiều nguồn = tầng **StoryKey riêng, cao hơn** — **CHƯA
  XÂY** (0 tham chiếu trong code; khác `cluster_by_event()` trong `curation/enrich.py`, vốn chỉ gộp
  NGAY LÚC crawl 1 lượt để chọn đại diện, không phải danh tính bền theo thời gian).

### 5.5 Membership/dedup CONTEXT — Fix (a), CHỐT (vừa xây ở phiên trước bản P5 này)
- File: `sheets_board.py: upsert_context_rows()` + `_context_topic_keys()`.
- CONTEXT quyết "đã có dòng chưa" bằng **cột `TopicKey` đọc TRỰC TIẾP từ Sheet** — KHÔNG bằng
  corpus cục bộ, KHÔNG bằng Source-text sống, KHÔNG bằng row-index.
- **MATCH → KHÔNG ghi cột nào** (giữ nguyên TOÀN BỘ dòng cũ, kể cả Hot%/Score — không có refresh).
  **NO-MATCH → append + `assign_topic_key()`.**
- CONTENT cũng upsert theo `(TopicKey, Type)` — `sheets_board.py: content_topic_keys()`, dùng bởi
  `produce_from_sheet.py` (3 chỗ: dòng ~260, ~611, ~736 — `board.existing_content_keys()`).
- **Lý do đổi từ Source-URL literal-match cũ:** 2 lượt crawl (2 máy khác nhau, hoặc dữ liệu cũ
  trước khi convention "Source=URL" chuẩn hoá) có thể ghi Source-text KHÁC NHAU cho CÙNG 1 chủ đề
  — literal-match bỏ sót, tạo dòng trùng dù TopicKey giống hệt. Đã xác nhận bug THẬT trên Sheet
  production (2 cặp trùng) trước khi sửa.
- **Cleanup 1 lần đã chạy:** `scripts/dedupe_context.py --apply` — xoá 2 dòng trùng, chép URL thật
  (đọc qua `hyperlink` metadata, không tin text) vào 2 dòng giữ đang là "title-chip". Đã backup 2
  tab (`CONTEXT_backup_<ngày>`, `CONTENT_backup_<ngày>`) trước khi xoá. Verify: 19→17 dòng CONTEXT,
  0 mồ côi (`existing_content_missing_keys() == []`).

### 5.6 LLM adapter — Manual/Auto cùng 1 interface — CHỐT
```
LLMClient.complete(system, prompt, *, model=None, fail_loud=False)   # mở rộng keyword-only, KHÔNG đổi chữ ký cũ
├── ClaudeCodeLLM   → shell `claude -p --output-format json`   (DEV/MANUAL = Pro session)
├── AnthropicLLM    → Messages API + key                        (AUTO/VPS)
└── MockLLM         → test
        ▲
   llm.mode: claude_code | api | mock
   llm.step_models: { brief: haiku, router: haiku, writer: sonnet }   # ALIAS, mỗi backend tự map
   llm.fail_loud_steps: ["writer"]   # bước writer lỗi → raise LLMCallError, KHÔNG lùi mượt âm thầm
```
- File: `agents/base.py`, `factory.py: make_llm()/step_model()/is_fail_loud_step()`.
- `fail_loud` là phần MỞ RỘNG thêm sau P2 (không có trong tài liệu P2) — bước phụ (brief/router)
  vẫn lùi mượt về `""`/fallback; bước Writer (sinh nội dung thật) BẮT BUỘC lỗi thấy được, không
  được âm thầm ghi CONTENT rỗng.
- `claude -p` KHÔNG expose tham số sampling (temperature=0 là no-op ở backend `claude_code`) → ổn
  định router giải bằng **route-once** (đóng băng `RouterDecision`), không dựa vào temperature.
- Timeout: `llm.claude_code.timeout_s = 240` (mặc định chung mọi bước, nới từ 120 vì bước brief
  timeout thật trên vài chủ đề dài); **`writer.timeout_s = 120`** (riêng cho Writer — tách biệt,
  bổ sung sau P2, P2 chưa ghi nhận key này).

### 5.7 Hạ tầng: KHÔNG engineer cho 2 DB, dồn về 1 VPS — CHỐT
- `data_root` (config-first): mọi ghi dữ liệu runtime qua `config.data_path(*parts)`; mặc định
  `storage.data_root: "../marketing-automation-database"` (ngoài repo, override qua `${DATA_ROOT}`).
- Đây **KHÔNG phải web app**. Kỷ luật TẠM THỜI tới khi có VPS: **một máy crawl/ghi tại một thời
  điểm**; TOCTOU (2 máy ghi ĐỒNG THỜI) **cố ý CHƯA xử lý** — khảo code xác nhận chỉ có
  `system_power_on.py: acquire_lock()/release_lock()` (trước đây `scripts/power_on.py`, đã chuyển ra
  gốc dự án + đổi tên) chặn 2 tiến trình **CÙNG MÁY** (lock file dưới
  `data_root/logs/power_on.lock`, hostname:pid, tên file lock KHÔNG đổi); máy khác giữ lock chỉ bị
  CẢNH BÁO, không bị chặn
  (không thể chặn liên-máy từ 1 file cục bộ). Giải bằng VPS (1 nguồn ghi), **không xây distributed
  lock**.

## 6. Trạng thái Phase 5 (Sheet board, 6 lớp) + lý do gác

**ĐÃ ĐÓNG:**
- **Lớp 5 — Ghi CONTENT neo theo khóa chủ đề** (sửa gốc "content mồ côi") — probe đối kháng:
  `tests/test_pipeline.py: test_phase3_adversarial_reorder_insert_delete_sort_topic_key_invariant_and_reproduce`
  (chèn/xoá/sort dòng ngẫu nhiên, xác nhận ánh xạ TopicKey→nội dung không trôi).
- **Fix (a) — Membership/dedup CONTEXT đọc Sheet** + dọn dòng trùng cũ (xem §5.5).

**GÁC — làm SAU VPS** (cả 3 giả định MỘT writer + "hôm nay" ổn định — chưa đúng khi còn 2 máy):
- **Lớp 1 — Block theo ngày.** ✅ **Mâu thuẫn giữa P2.md (§11.1: "mới nhất trên cùng") và giả
  thuyết ban đầu của P5 ("mới nhất dưới cùng") đã được người vận hành CHỐT LẠI: dòng bài MỚI NHẤT
  nằm DƯỚI CÙNG (append-only, ngày mới xuống dưới) — ghi đè lựa chọn cũ của P2.** Hiện tại code
  CHƯA XÂY block-theo-ngày (CHƯA XÂY, vẫn GÁC tới sau VPS) — `sort_context_by_hot()`
  (`sheets_board.py:1507`) đang sắp TOÀN BẢNG theo Hot% giảm dần mỗi lần crawl, không liên quan
  ngày/thứ tự chèn; khi mở Lớp 1, thứ tự chèn theo ngày (mới nhất dưới cùng) sẽ cần thay/bổ sung
  cho cách sort Hot% hiện tại — quyết định CÁCH kết hợp 2 tiêu chí (ngày vs Hot%) vẫn còn mở, chỉ
  HƯỚNG (trên/dưới) là đã chốt.
- **Lớp 2 — Khóa cột theo máy-sở-hữu.** P2 (§11.2) mô tả khóa theo **NGÀY** (protected range cho
  block < hôm nay, Owner unlock). Bản P5 giả thuyết chi tiết hơn: khóa CỘT cụ thể (`TopicKey`,
  `Source`, `Timestamp`), **chừa `Approver`**, SA (service account) miễn protection. Khảo code:
  **0 dòng** liên quan `protectedRange`/`Approver` — cả 2 mô tả đều CHƯA XÂY, chi tiết-hơn của P5
  có thể là tinh chỉnh chưa kịp ghi vào P2, không hẳn mâu thuẫn — cần xác nhận khi mở lớp này.
  **Cập nhật (Production Factory Phase 1.3):** CONTENT có thêm cột `Facts` (JSON facts[] snapshot)
  — **MÁY-SỞ-HỮU, thuộc CÙNG nhóm khoá với `TopicKey`/`Source`/`Timestamp`** khi Lớp 2 mở (xem
  comment `CONTENT_HEADER` trong `sheets_board.py`) — người KHÔNG được sửa tay cột này (nếu cần sửa
  facts, phải re-route/re-brief, không gõ trực tiếp JSON). `AssetPath` cũng máy-sở-hữu (ghi bởi
  `scripts/render_production_assets.py`) nhưng CHƯA xếp cùng nhóm khoá — cần xác nhận khi mở Lớp 2.
  `Gate3` (dropdown APPROVE/PENDING/REJECT) là cột NGƯỜI, giống `Approve(gate 2)`/`Approver` —
  KHÔNG khoá. Ngoài ra: **reader phải lấy `hyperlink` URI qua `spreadsheets.get`** để khôi phục
  Source bị "title-chip hoá" — đã có sẵn hàm dùng lại được: `sheets_board.py: extract_cell_url()`,
  `is_title_chip()`, `fetch_context_source_cells()` (xây ở Fix (a), xem §7).
- **Lớp 3 — Cửa sổ TRƯỢT 6 ngày làm việc** (bỏ CN, giữ T7, KHÔNG reset theo tuần lịch) + archive
  CONTEXT/CONTENT theo tuổi (**Manual theo tuổi AND Status=DONE**). Khớp P2 §11.3 (P2 không ghi rõ
  "trượt" nhưng ý tương đồng). CHƯA XÂY (0 tham chiếu "archive"/sliding window trong code).

**GÁC — "tinh chỉnh UI/logic", làm SAU Production Factory:**
- **Lớp 6 — Data-validation tập trung** cho mọi cột dropdown + cột `Approver` (**đã CHỐT sẽ bật**,
  chưa xây). Lưu ý: **ĐÃ CÓ SẴN** data-validation dropdown RIÊNG LẺ (Status/Execute/`Approve(gate
  2)`) qua `_one_of_list()`/`_set_validation()` trong `sheets_board.py` — đây là validation
  **theo-cột-đơn-lẻ có từ trước**, KHÔNG phải "trung tâm hoá" (1 hàm khai báo chung cho mọi cột
  dropdown mới) như Lớp 6 dự định — đừng nhầm 2 thứ.
- **Lớp 4 — Manual adapter ở Gate 2** (dropdown `MANUAL` → copy sang Manual sheet riêng, đánh dấu
  `MANUAL_SENT`). Khảo code: **0 tham chiếu** `MANUAL_SENT`/Manual sheet — CHƯA XÂY. P2 (§10) có
  nhắc 1 Sheet ID riêng cho Manual adapter — **không lặp lại ID đó ở đây** (xem §8, quy ước không
  rò bí mật); tham chiếu qua vai trò "Manual sheet" khi cần, tra ID thật trong `secrets/`/ghi chú
  vận hành riêng ngoài git.

## 7. Nợ kỹ thuật & bẫy đã biết (ghi rõ để không giẫm lại)

- **`mergeCells` XÓA THẬT giá trị** Context/Timestamp của mọi ô bị merge trừ ô đầu (không chỉ ẩn
  hiển thị) — `sheets_board.py: regroup_and_merge_content()` dùng `MERGE_COLUMNS`. Đây là cơ chế
  GỐC của "content mồ côi" mà Lớp 5 phải sửa vòng (TopicKey sống sót merge vì đặt CUỐI header,
  không nằm trong `_CONTENT_MERGE_COLS`). **Lớp 1 (block theo ngày) khi xây NÊN BỎ HẲN mergeCells**,
  dùng bold divider/border thay vì merge — tránh tái tạo đúng lỗi đã mất công sửa.
- **"Title-chip"** — Google Sheets có thể hiển thị TIÊU ĐỀ ở ô Source trong khi `hyperlink` ẩn bên
  dưới vẫn là URL thật; `get_all_values()`/`values.get` CHỈ trả `formattedValue` (tiêu đề), KHÔNG
  trả `hyperlink`. **Đã xác nhận + sửa 2 dòng** trong Fix (a) (dòng 5 & 7 gốc, xem §5.5). **Còn
  ~7 dòng title-chip CHƯA khôi phục** (Source số Sheet hiện tại: 2, 3, 4, 6, 8, 9, 10 — đếm lại
  bằng `sheets_board.is_title_chip()` khi mở việc này, số dòng có thể xê dịch nếu Sheet đổi thêm).
  **KHÔNG bấm "Yes" khi Google Sheets tự đề nghị "replace URL with title"** trên cột Source —
  URL vẫn còn nguyên trong hyperlink metadata **CHỈ KHI chưa bấm Yes lần nữa/chưa xoá dòng** — nếu
  thao tác tay trên các dòng còn lại, dùng `board.fetch_context_source_cells([...])` để đọc `href`
  thật trước khi sửa gì, đừng xóa dòng tưởng "không có URL".
- **`Timestamp` = first-seen, KHÔNG bump khi re-crawl.** Fix (a) MATCH không ghi cột nào nên điều
  này TỰ ĐỘNG đúng — nhưng nếu sau này ai thêm logic "refresh Hot%/Score khi match" (đã CÂN NHẮC
  rồi BỎ ở Fix (a) Phase 1, xem quyết định trong lịch sử phiên) thì PHẢI KHÔNG đụng Timestamp —
  bump sẽ khiến topic không bao giờ rơi khỏi cửa sổ 6 ngày (Lớp 3).
- **TOCTOU (2 máy ghi đồng thời) chưa xử lý — CỐ Ý**, xem §5.7. Không phải thiếu sót, là quyết định
  hoãn tới VPS.
- **Team dùng Gmail thường** → Apps Script `getActiveUser()` khả năng cao trả rỗng → auto-attribution
  (tự động biết ai duyệt) **không khả thi** ở trạng thái hiện tại. **Không thể xác minh từ repo
  git** (Apps Script sống trong Google Sheet, ngoài phạm vi source code) — ghi nhận là rủi ro vận
  hành cần kiểm tra trực tiếp trên Sheet khi mở Lớp 2/6. Giải pháp tạm: cột `Approver` thủ công
  (người tự ghi tên khi duyệt) cho tới khi có web app với đăng nhập thật.
- **`docs/deployment_vps.md` được P2 (§9) liệt trong sơ đồ repo nhưng KHÔNG tồn tại** — chưa viết,
  hoặc đã mất. Cần viết khi thật sự chuẩn bị lên VPS (không cần làm ngay).
- ~~**Token Telegram từng lộ trong 1 phiên chat trước** (theo P2 §8)~~ — **ĐÃ XỬ LÝ: người vận
  hành xác nhận đã `/revoke` qua BotFather.** Không lặp lại giá trị token ở bất kỳ tài liệu nào
  (kể cả file này). Nếu chưa cập nhật token mới vào `secrets/.env`, notifier sẽ tự lùi mượt về
  no-op (không crash) tới khi điền lại — xem `utils/telegram_notifier.py: make_notifier()`.

## 8. Lộ trình kế tiếp

- **Production Factory** (module lớn kế tiếp, theo đúng thứ tự phụ thuộc P2 đã định vị):
  **infographic TRƯỚC** (video phụ thuộc renderer ảnh cho scene card) — nhưng nhớ đã có 1 renderer
  SVG thủ công sẵn (§3), kiểm tra tái dùng trước khi xây từ đầu. Ranh giới cần tự chốt: phần nào
  **tự xây** (brand/số/QA, vốn cần chính xác tuyệt đối và rẻ) vs phần nào **đi mua**
  (TTS/avatar — HeyGen đắt, để sau, sau cờ flag). Cần **brand-kit FVA** thật (logo 2 bản
  sáng/tối dạng vector, mã màu hex chính xác từ logo đã nhận, font, dòng chân trang) trước khi
  render production — hiện `render.infographic.*` trong `settings.yaml` vẫn là bảng màu tạm/cũ.
- **Gate 3 (Duyệt Public)** — sau khi Production Factory ra media hoàn chỉnh.
- **Social/Phân phối** — publisher adapter thật (FB/LinkedIn/YouTube/Zalo), thay `ConsolePublisher`.
- **Story Clustering (StoryKey)** — tầng gom-nhiều-nguồn cao hơn TopicKey, chưa mở.
- **Web app (Vite+React/FastAPI)** — nơi giải bài toán attribution/audit thật (đăng nhập thật thay
  Gmail thường), thay Google Sheet làm control-plane khi quy mô lớn hơn.
- **Backlog dài hạn đã ghi nhớ từ P2 (§13, §15), vẫn còn giá trị:**
  1. Tối ưu chất lượng content thêm vài vòng trên dữ liệu lớn/đa dạng hơn.
  2. Phân loại thêm định dạng Video (News/Avatar/Human/Reel/Short) — hiện `video_script` là 1
     tuyến chung; content-fit router (đã có `output_channels`) là chỗ tự nhiên để mở rộng.
  3. Tinh chỉnh Context + Hook TRƯỚC Gate 1 — hiện còn thô hơn bài đã qua voice-lock; cân nhắc cho
     Hook pre-gate dùng chung menu hook §2b của `docs/voice_examples.md`.
  4. Backend corpus online đa máy + dedup URL (Postgres/Supabase) thay `FileDocumentStore` local —
     tự giải quyết luôn phần "2 máy" ở §5.7 nếu làm sớm hơn VPS thuần.
  5. Redesign tab SOURCES dạng "Router" (Module Publisher / Fields / Feed-Type).
- **Bật automation thật:** khi VPS sẵn sàng, đổi `llm.mode: api` + bật `system_power_on.py` (giữ
  `hook_offline: true` để lịch nền không tự đốt token cho Hook). **Hai Gate giữ nguyên** ở mọi chế
  độ — không có phiên bản "bỏ qua duyệt người" nào được lên kế hoạch.

## 9. Quy ước làm việc

- **Config-first.** Mọi tham số ở `config/settings.yaml`; bí mật qua `${ENV}` (`secrets/.env`,
  gitignored) — KHÔNG hard-code trong code hay trong tài liệu (kể cả file này).
- **Phase nhỏ, DỪNG-BÁO-CÁO.** Mỗi việc lớn chia phase, dừng sau mỗi phase để review trước khi đi
  tiếp — đặc biệt bắt buộc trước MỌI thao tác phá huỷ (xoá dòng Sheet, đổi schema, `--rekey`).
- **Không auto-commit.** Mọi thay đổi code/tài liệu ở trạng thái working tree cho tới khi người
  vận hành tự `git add`/`commit`/push.
- **Chấm trên OUTPUT THẬT.** Test xanh là điều kiện CẦN, không phải ĐỦ — luôn xác nhận bằng dữ
  liệu/round-trip thật trước khi báo "xong" cho việc có rủi ro chất lượng/dữ liệu thật.
- **Không rò bí mật.** Không dán Sheet ID sản xuất trần, token, đường dẫn cá nhân, hay giá trị
  `${ENV}` thật vào bất kỳ tài liệu nào — chỉ ghi tên biến config.
- **Một mặt trận một lúc.** Không mở nhiều thay đổi kiến trúc song song trên repo.
- **Adapter ở mọi điểm nối ngoài** (collectors, LLM backend, notifier, storage, publisher) — thêm
  nguồn/nền tảng = thêm adapter, không sửa lõi.

---

**Việc cần làm ngay khi mở phiên mới (theo thứ tự ưu tiên):**
1. ~~Xác nhận với người vận hành: Lớp 1 sort thế nào~~ — **ĐÃ CHỐT: mới nhất DƯỚI cùng** (§6).
2. ~~Xác nhận token Telegram đã `/revoke` chưa~~ — **ĐÃ XÁC NHẬN: đã revoke** (§7).
3. Quyết định: bắt đầu Production Factory bằng cách NÂNG CẤP `render/infographic.py` có sẵn
   (brand kit FVA + wire vào pipeline), hay thiết kế lại từ đầu.
4. Nếu muốn dọn nốt 7 dòng title-chip còn lại (§7) — dùng lại `sheets_board.extract_cell_url()`/
   `fetch_context_source_cells()` đã có, không cần xây lại.

---

## 10. Lưu trữ — nội dung đã DI CHUYỂN khỏi `CLAUDE.md` (kỷ luật tài liệu, task ACTIVE_TASK doc-only)

`CLAUDE.md` được rút gọn chỉ còn quy tắc chung + ranh giới kiến trúc đã CHỐT (trỏ
sang `docs/MODULE_INDEX.md` cho bản đồ code, sang đây cho quyết định/lịch sử).
Phần dưới đây là **NGUYÊN VĂN** `CLAUDE.md` bản GỐC (Phase 0, trước Milestone
(a)) — **ĐÃ SUPERSEDE HOÀN TOÀN**, giữ lại chỉ vì lý do lịch sử (không xoá
thông tin, chỉ di chuyển). Kiến trúc THẬT hiện tại xem §3-§5 phía trên — bản
gốc dưới đây nhắc tới `ervn`/LangGraph/Qdrant/React UI là lộ trình đã BỎ, không
áp dụng.

> ### CLAUDE.md gốc (Phase 0 — LỊCH SỬ, không còn phản ánh kiến trúc hiện tại)
>
> #### Dự án
> Marketing Automation cho Turtle Wealth VN: thu thập thông tin (tài chính, doanh
> nghiệp, chính sách, thế giới) → chuẩn hóa & lưu trữ → **người duyệt** → sản xuất
> nội dung số (bài viết, infographic, kịch bản video, newsletter) → **người duyệt**
> → phân phối MXH. Mục tiêu: kênh vệ tinh tăng độ phủ.
>
> Đây là **service độc lập**. KHÔNG gộp với hệ Research (`ervn` đã tách sang project
> khác). Nếu cần dữ liệu nghiên cứu, tiêu thụ qua contract `ResearchBrief` —
> KHÔNG reintroduce `ervn` vào repo này.
>
> #### Nguyên tắc bất di bất dịch
> 1. **Tất định trước, LLM sau.** Crawl/dedup/chuẩn hóa/chunk/compliance/vector
>    search = Python thuần ($0 token). LLM chỉ chạm ở Researcher (gửi *chunk liên
>    quan*) và các producer viết-bằng-LLM.
> 2. **LLM đắt chỉ chạy SAU cổng duyệt 1.** Đừng sinh nội dung cho chủ đề chưa
>    được người duyệt.
> 3. **Adapter ở mọi điểm nối ngoài**: collectors, publishers, embedder, vector
>    store, LLM. Thêm nguồn/nền tảng = thêm adapter, không sửa lõi.
> 4. **Giữ demo offline chạy được** (`python -m twmkt.demo`, $0 token) và **mọi
>    thay đổi phải kèm test**. Chạy `python tests/test_pipeline.py` trước khi commit.
> 5. Nội dung tài chính: giữ guardrail compliance; không nới lỏng claim cấm.
>
> #### Tầng token (rẻ → đắt)
> Tầng 0 (free): crawl, curation, chunk, embedding local, vector search, infographic
> spec, newsletter. Tầng 1 (rẻ): Haiku cho triage/tóm tắt nếu cần. Tầng 2 (đắt):
> Sonnet cho viết bài & kịch bản, chỉ sau cổng 1.
>
> #### Chạy
> ```
> cd src && python -m twmkt.demo
> python tests/test_pipeline.py     # hoặc python -m pytest
> ```
>
> #### Lộ trình khi lên production
> MockCollector→Crawl4aiCollector; HashingEmbedder→SentenceTransformer local;
> InMemoryVectorStore→Qdrant; MockLLM→AnthropicLLM (Haiku/Sonnet theo tầng);
> orchestrator→LangGraph StateGraph; AutoApproveGate→cổng duyệt React UI;
> ConsolePublisher→adapter nền tảng thật.
>
> **Đối chiếu với thực tế hiện tại (đã CHỐT, khác bản gốc trên):** KHÔNG dùng
> LangGraph/Qdrant/React UI — kiến trúc thật là Google Sheets control-plane
> (`sheets_board.py`) + 2 Gate trên Sheet + `ClaudeCodeLLM`/`AnthropicLLM`/
> `MockLLM` (`agents/base.py`). "Tầng token" khái niệm vẫn đúng tinh thần nhưng
> tên bước đã đổi (Brief=Haiku, Router=Haiku, Writer=Sonnet — xem §5.6). "Cổng
> duyệt 1" = Gate 1 (CONTEXT.Status); Luồng B (`orchestrator.py`+`demo.py`) là
> nơi DUY NHẤT còn khớp gần đúng với mô tả gốc này (offline, 2 gate, không dùng
> sản xuất thật).
