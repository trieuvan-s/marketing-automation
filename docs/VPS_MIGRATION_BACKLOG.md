# VPS_MIGRATION_BACKLOG.md — nợ dài hạn trước/khi/sau chuyển VPS

> **NGOẠI LỆ CÓ CHỦ ĐÍCH so với quy ước file khác trong repo.**
> `tasks/ACTIVE_TASK.md` và `docs/HANDOFF.md` đều **GHI ĐÈ MỖI PHIÊN** (chỉ
> phản ánh trạng thái hiện tại, không tích luỹ); `CLAUDE.md` chỉ chứa quy tắc
> chung, không phải backlog. Không file nào trong số đó giữ được nợ dài hạn
> qua nhiều phiên — dễ mất mục việc chưa làm khi phiên sau ghi đè.
>
> File này **CHỈ THÊM, KHÔNG GHI ĐÈ**. Đóng 1 mục: đánh dấu **ĐÃ XONG + ngày**
> ngay tại mục đó, KHÔNG xoá khỏi file (giữ làm lịch sử/tham chiếu).

---

## A. CHẶN — làm ngay khi lên VPS

### A0. [ƯU TIÊN CAO NHẤT] Ghép nối marketing-automation + aigen-pipeline — test tổng thể "tin tức" → "video"
Thêm 2026-07-19, mức ưu tiên CAO NHẤT trong toàn bộ file này — đứng trước cả
A1-A5. Mở rộng A3 (đặt 2 repo cạnh nhau) thành 1 tiêu chí nghiệm thu CỤ THỂ:
không chỉ sibling directory, mà phải **chạy được 1 lượt thật, đầu-cuối**, từ
đầu vào "tin tức" tới đầu ra "video", để xác nhận Adapter hoạt động đúng và 2
module lớn (Content Factory Python + AIGEN render TS) đã khớp nhau THẬT SỰ —
không chỉ khớp trên giấy/qua test mock/qua fixture tay.

**Chuỗi cần chạy được (đầu-cuối, không cắt đoạn)**:
tin tức thật (crawl → CONTEXT) → duyệt Gate 1 (Context=APPROVE) → Content
Factory sinh Output (Gate 2) → `media_factory.spec.py::build_spec_from_content()`
hoặc tương đương cho nhánh video (**xem điều kiện B2 bên dưới**) →
`ProductionSpec.scenes[]` → AigenAdapter (`aigen-pipeline/src/adapter/`) →
`TemplateScript` (`script.json`) → `media_factory/aigen_seam.py::
run_aigen_pipeline(dry_run=False)` → `npm run pipeline` → **`video.mp4` thật,
mở lên xem được, không lỗi, không lộ demo placeholder (quirk #1/#2)**.

**Điều kiện tiên quyết (PHẢI xong trước, theo đúng thứ tự phụ thuộc đã ghi ở
A2/A3 bên dưới)**:
- A2 (data_root hợp nhất) — VPS phải là nơi dữ liệu SỐNG DUY NHẤT trước khi
  chạy thật, tránh test này ghi lệch giữa 2 bản data_root.
- A3 (2 repo sibling, `../aigen-pipeline`) — seam (A5, đã sửa) resolve path
  qua config, cần repo đã ở đúng vị trí sibling để tự tìm thấy.
- Máy chạy: **PC-B/VPS** (có OmniVoice/ffmpeg/CUDA) — PC-A KHÔNG BAO GIỜ
  render thật (ranh giới máy đã chốt, xem CLAUDE.md + `aigen_seam.py`
  docstring). `dry_run=True` trên PC-A KHÔNG tính là đã nghiệm thu mục này.

**Khoảng trống cần biết trước khi chạy**: B2 (Video Scene Builder thật —
`CONTENT.Output` → `ProductionSpec.scenes[]`) **CHƯA XÂY** — `scenes[]` hiện
LUÔN RỖNG trong pipeline thật. Nếu B2 chưa xong khi tới lượt chạy test này,
2 lựa chọn: (a) xây 1 bản Scene Builder tối thiểu đủ cho 1 chủ đề thật để có
`scenes[]` thật thay vì bịa, HOẶC (b) chạy tạm bằng fixture tay đã có
(`aigen-pipeline/out/handoff-to-pcb/script.json`, 7 scene THẬT lấy từ video
PNJ đã render — KHÔNG phải toàn chuỗi đầu-cuối, chỉ xác nhận đoạn Adapter→
AIGEN, KHÔNG xác nhận đoạn Content Factory→ProductionSpec.scenes[]). Ghi rõ
trong báo cáo nghiệm thu đã dùng (a) hay (b) — 2 mức bằng chứng khác nhau.

**Sau khi chạy xong**: soi từng frame `video.mp4` tìm chữ demo lọt lên (quirk
#1/#2, KHÔNG test nào bắt được tự động — xem C5), nghe kỹ `voiceText` tìm
acronym đọc sai (C4), đối chiếu `AigenPipelineResult.ok`/`error` không có gì
bất thường.

### A1. WEBHOOK thay scheduler 30 phút
Hiện tại: `system_power_on` khởi chạy scheduler quét Sheet 30'/lần tìm cờ
Execute=RUN. User bấm "Thực Thi" có thể chờ tới 30' mới thấy chạy.

Đích: user duyệt Context=APPROVE + bấm "Thực Thi" → Apps Script bắn HTTP tới
endpoint always-on trên VPS → gọi produce_from_sheet xử lý Context→Content
THEO ĐÚNG TopicKey đó NGAY LẬP TỨC → phản hồi ngược ghi trạng thái
DONE / FAILED / NEEDS_HUMAN.

Lý do hoãn tới giờ: webhook cần endpoint always-on, môi trường local không có.

**CẦN HỎI LEAD TRƯỚC KHI CODE**: state machine Execute
(empty→RUN→DONE/FAILED/NEEDS_HUMAN) đang là cơ chế idempotency chính. Có cần
trạng thái trung gian (đã gọi webhook, chờ phản hồi) để chống double-fire khi
user bấm 2 lần hoặc webhook timeout không?

Khi làm: GỠ scheduler 30' khỏi system_power_on — không để 2 cơ chế song song.

### A2. HỢP NHẤT data_root — mục đích chính của việc lên VPS  [ĐÃ CHỐT]
data_root KHÔNG đồng bộ giữa 2 máy là nguồn nhiều bug thật (dòng trùng,
evidence thiếu khi đổi máy). Bản CHUẨN = PC-A. Lên VPS: copy từ PC-A lên, VPS
là nơi ở VĨNH VIỄN, không đồng bộ ngược, không giữ bản song song.

### A3. Hợp nhất repo thành sibling directory
marketing-automation và **aigen-pipeline** (KHÔNG phải aigen-fva-capital — đã
chết) nằm cạnh nhau. Sau đó mới test được seam THẬT.

### A4. serve_assets.py wire vào power_on
Hiện phải chạy tay mới mở được link AssetPath. Lên VPS: đổi `base_path`
config + cho chạy nền cùng power_on.

### A5. Seam path hardcode  [ĐÃ SỬA ngày 2026-07-19 — đưa vào config, xem BƯỚC 1]
Bằng chứng lỗi trước khi sửa: dry-run in ra `cwd=E:\aigen-fva-capital\aigen`
— repo đã chết, seam sẽ FAIL LÚC CHẠY THẬT. Đã sửa: `media_factory/
aigen_seam.py::run_aigen_pipeline()` giờ nhận `aigen_repo_path=None` mặc
định, resolve qua `twmkt.config.aigen_repo_path()` (ENV `AIGEN_REPO_PATH`
hoặc `media_factory.aigen_repo_path` trong `settings.yaml`, mặc định sibling
`"../aigen-pipeline"`, CÙNG NẾP `data_root()`). Path không tồn tại → raise
`AigenRepoPathNotFoundError` nêu rõ đường dẫn đã thử. Đổi máy (VPS) chỉ cần
đổi 1 dòng config hoặc set ENV, KHÔNG sửa code. Test phủ:
`test_aigen_seam_resolves_aigen_repo_path_from_config_when_path_exists`,
`test_aigen_seam_config_path_missing_raises_clear_error_naming_the_path`,
`test_aigen_seam_changing_config_changes_resolved_cwd_not_hardcoded`
(`tests/test_pipeline.py`).

### A6. TopicKey Document Store (DB chung) — bổ sung 2026-07-19, chi tiết hoá B1
Thêm sau khi kiến trúc 2 repo chốt (`docs/ARCHITECTURE_MODULES.md`) — cùng
khái niệm B1 bên dưới, nhưng giờ có thêm ràng buộc QUYỀN GHI vì 2 repo 2 ngôn
ngữ cùng cần đụng dữ liệu:

1 DB, mọi bản ghi neo TopicKey. **QUYỀN GHI TÁCH BẠCH**: marketing-automation
ghi tầng 1-3 (thô, brief, `CONTENT.Output`) + kết quả infographic;
aigen-pipeline ghi tầng video. Bên kia CHỈ ĐỌC — không bảng nào cả 2 bên cùng
ghi (tránh race-write xuyên ngôn ngữ, không có transaction chung).

⚠️ **LÀM SAU khi luồng thông** (B2 Scene Builder xong, chạy end-to-end được ít
nhất 1 lần). Sheet HIỆN ĐANG LÀ database (Facts/Output/Gate status chỉ tồn
tại trên Sheet) → xem cảnh báo TUYỆT ĐỐI ở B1 bên dưới, vẫn còn nguyên giá trị.

### A7. Document Store — schema ĐÃ XÁC THỰC bằng DỮ LIỆU THẬT (cập nhật A6)
Bổ sung 2026-07-19, nhánh `feature/webhook-store` (chưa merge `develop`).

Đã có: `store/schema.sql` + `store/document_store.py`
(write_document/read_latest/read_history/list_topics) +
`store/backfill_from_sheet.py` (script CHỈ ĐỌC Sheet, `--dry-run`/`--write`
vào DB TẠM — KHÔNG đụng store thật, KHÔNG ghi Sheet). Chạy dry-run + write
thật trên Sheet production (9 dòng CONTEXT + 9 dòng CONTENT), phát hiện và
SỬA 3 bug:
- **BUG 1**: khoá UNIQUE thiếu `content_type` — 1 topic_key có 3
  content_type (article/infographic/video) trong layer `content_output` bị
  coi là 3 version NỐI TIẾP của CÙNG 1 tài liệu, "chôn" mất 2/3 khi đọc lại.
  Sửa: thêm cột `content_type` vào `UNIQUE(topic_key, layer, content_type,
  version)`; `read_latest()`/`read_history()` giờ BẮT BUỘC tham số
  `content_type`.
- **BUG 2**: `ContentFormat.VIDEO_SCRIPT="video_script"` không khớp Sheet
  thật (Sheet ghi `"video"`). Sửa ENUM theo Sheet (Sheet là nguồn sự thật ở
  giai đoạn backfill) — xem C7 bên dưới về 1 chỗ CHƯA sửa được.
- **BUG 3** (làm rõ, không phải bug code): layer `infographic`/`video` = 0
  bản ghi vì cột `AssetPath` RỖNG ở CẢ 9/9 dòng CONTENT thật (kể cả 3 dòng
  Type=infographic) — Production Factory (`render_production_assets.py`)
  chưa từng render cho các dòng này, KHÔNG phải lỗi đọc thiếu cột.

Kết quả xác minh: 27/27 bản ghi (raw+brief+content_output) ghi thành công
vào DB tạm; 3/3 topic_key đa content_type đọc lại ĐỘC LẬP, đúng, không cái
nào chôn. 42/42 test xanh.

⚠️ **CHƯA làm** (đúng phạm vi "viết sẵn chờ ráp", không tạo thêm diff chờ
ráp lúc chưa cần — xem A6 "LÀM SAU khi luồng thông"):
- Dual-write thật vào `store/document_store.db` thật (chỉ mới có DB TẠM
  dùng để test schema).
- Nối `backfill_from_sheet.py`/`document_store.py` vào
  `scripts/produce_from_sheet.py` hay pipeline thật.
- Quyết định 7 cột CONTEXT + 8 cột CONTENT không map vào layer nào (toàn bộ
  là cột trạng thái vận hành: Duyệt Context/Execute/Approve(gate 2)/Gate3/
  Posting Status/Notes/Timestamp/Hot%/Score/Group) — có cần 1 nơi neo khác
  ngoài Sheet không, hay cố ý để Sheet giữ trạng thái vận hành mãi mãi
  (đúng kiến trúc A6 "Sheet chỉ là UI/view") — CẦN LEAD XÁC NHẬN.

---

## B. MODULE LỚN — sau khi A xong

### B1. TopicKey Document Store
Đã chốt: làm SAU VPS (2 máy sẽ tạo 2 store phân kỳ).

Đích: Sheet CHỈ LÀ UI/view; mọi dữ liệu (evidence, facts, output mọi format,
trạng thái từng Gate, asset path, lịch sử) nằm trong store neo theo TopicKey;
xóa Sheet rồi render lại từ store được.

⚠️ **HIỆN TRẠNG**: CHƯA CÓ store nào. Facts/Output/Gate status CHỈ tồn tại trên
Sheet — Sheet ĐANG LÀ database. TUYỆT ĐỐI KHÔNG xóa/reset Sheet trước khi
store tồn tại và đã backfill xong.

### B2. Video Scene Builder thật (CONTENT.Output → ProductionSpec.scenes[])
Hiện scenes[] LUÔN RỖNG; đang dùng fixture tay để chứng minh contract.

### B3. Attribution & Audit (Apps Script onEdit → LastEditedBy/LastEditedAt + tab LOG)
Phụ thuộc A1 (endpoint) và B1 (LOG neo theo TopicKey, không theo dòng).
Điều kiện tiên quyết: revoke token Telegram trước khi xây lớp này.

---

## C. NỢ NHỎ / RỦI RO ĐÃ BIẾT

- **C1.** `scripts/reset_sheet.py` CHƯA từng chạy `--confirm` lên Sheet thật.
- **C2.** Prompt caching cho `content_writer_rules.md` — nhúng `extra_system`
  MỖI lần gọi LLM; chưa bật caching = đốt tiền thật.
- **C3.** ElevenLabs chưa wire (thiếu API key + voiceID).
- **C4.** alias-guardrail chỉ chặn mã trong `VALID_TICKERS`. Viết tắt KHÔNG
  phải mã chứng khoán (ETF, GDP, FDI) lọt qua → TTS đọc sai. FVB đã tắt khỏi
  vòng render nên không còn gì đỡ. Hướng xử: siết `content_writer_rules.md`
  phía Content Factory, KHÔNG thêm từ điển vào adapter.
- **C5.** Quirk #1/#2 (demo placeholder lòi lên video) KHÔNG test nào bắt
  được — phải soi frame sau mỗi lần render thật.
- **C6.** [2026-07-20, nghiệm thu VIỆC 3 trên video thật `4_cang_bien_dac_biet`]
  **`frame-build-minimal` hero TRÀN/VỠ TỪ khi text dài.** `visual_kind=
  "statement"` map sang template này, ô `hero` giới hạn CATALOG 10 ký tự (thiết
  kế cho cụm ngắn kiểu "82%") nhưng renderer KHÔNG auto-shrink (khác
  `frame-pentagram-stat` đã có `fitText`). Bằng chứng: scene 2 hero "Bỏ phân
  nhóm cảng" (17ch) → "cảng" vỡ "cả"/"ng"; scene 4 "Hòn Khoai: bến cảng lưỡng
  dụng" (30ch) → vỡ 4 dòng cắt giữa từ. Lead chọn CHẤP NHẬN TẠM (2026-07-20),
  sửa ở vòng tối ưu sau. 3 hướng đã cân nhắc: (a) thêm fitText vào template
  [agent-B, render], (b) siết contract hero statement ≤10-12 ký tự [Composer],
  (c) đổi mapping statement-dài sang template khác. KHÔNG có test nào bắt —
  cùng lớp C5, soi frame thủ công.
- **C7.** [2026-07-20] Outro `primary_url` = link FB profile thô 67 ký tự
  (`BRAND_PRIMARY_URL` trong `aigen production-spec/index.ts`) wrap 2 dòng
  uppercase, xấu. Cân nhắc link rút gọn cho kênh (đã ghi từ HANDOFF, chưa làm).
- **C8.** [nhánh `feature/webhook-store`, đánh số lại từ C6 trùng khi rebase
  lên develop 2026-07-21 — nội dung KHÔNG đổi] Service webhook chết giữa
  chừng → cờ `Execute` kẹt `RUN` vĩnh viễn, user không kích hoạt lại được.
  Nấc 1: xử tay (xoá ô). Xử tử tế khi có Document Store (có timestamp → phát
  hiện "RUN quá lâu" → tự giải phóng).
- **C9.** [nhánh `feature/webhook-store`, đánh số lại từ C7 trùng khi rebase
  lên develop 2026-07-21 — nội dung KHÔNG đổi. KHOẢNG TRỐNG GIỮA 2 AGENT —
  đọc trước khi merge] `scripts/produce_from_sheet.py` VẪN còn dùng chuỗi
  `"video_script"` cũ (xác nhận qua `grep -n "video_script"
  scripts/produce_from_sheet.py`) — KHÔNG khớp `ContentFormat.VIDEO_SCRIPT`
  đã sửa thành `"video"` ở `models.py`/`sheets_board.py` (xem A7, BUG 2).
  **CỐ Ý KHÔNG SỬA** trong lúc viết dòng này vì file đó đang là vùng agent-B
  sửa dở (diff lớn chưa commit trên `develop`) — sửa lúc đó rủi ro đụng
  độ/mất việc của agent-B. Đây KHÔNG phải lỗi của agent-B (họ không biết bug
  enum này tồn tại khi bắt đầu sửa file) — **người merge/rebase SAU CÙNG (khi
  cả 2 agent xong) phải chủ động rà lại `scripts/produce_from_sheet.py` tìm
  `"video_script"` còn sót**, đừng để mỗi bên tưởng bên kia đã sửa.

---

## D. HƯỚNG PHÁT TRIỂN MỞ RỘNG (chưa chốt — chờ Lead duyệt)

### D1. Trục AVATAR VIDEO (HeyGen) song song luồng template trong Production Factory
Thêm 2026-07-20. Đề xuất ĐẦY ĐỦ (agent-B → Lead) ở
`aigen/docs/AVATAR_HEYGEN_PROPOSAL.md` (ngày viết 2026-07-19). Ghép thêm một
trục sản xuất Avatar Video dùng HeyGen chạy **song song** luồng template hiện
tại, trong cùng Production Factory.

**Đã đánh giá lại 2026-07-20 (agent-B) — 3 claim kỹ thuật cốt lõi VẪN ĐÚNG với
code hiện tại**, xác minh trực tiếp:
- `render/video-tools.ts::overlayAvatarVideo` chỉ `-map "[out]"` (video-only,
  `[0:v][am]overlay`) → audio clip avatar KHÔNG được map = bỏ hoàn toàn
  (docstring tự khai "muted — the scene's TTS narration remains the only audio").
- Avatar clip bị `-stream_loop -1` + `shortest=1` → lặp/cắt theo clip nền.
- `render/template-pipeline.ts` (~L168-188): `clipToFit = avatarClip` rồi
  `fitClipToDuration(clipToFit, visualDur, ...)` — khớp avatar vào duration
  suy từ audio TTS riêng, độc lập nội dung avatar.
→ Kết luận: cơ chế `frame-avatar-presenter` hiện tại giả định avatar là b-roll
CÂM; thả thẳng output HeyGen (đã lip-sync sẵn) vào sẽ lệch khẩu hình. Đề xuất
đúng vấn đề, hướng giải (audio-driven lip-sync, TTS AIGEN vẫn là nguồn giọng
duy nhất) hợp lý.

**Ràng buộc kiến trúc đề xuất giữ**: giọng cho HeyGen PHẢI ra từ OmniVoice/
ElevenLabs (không dùng voice riêng HeyGen) → `AvatarSpec` cố ý không có field
chọn voice. Đúng tinh thần quyết định (b) "một text chuẩn hoá dùng chung mọi
engine".

**Chia 2 tầng** (đề xuất mục 4): Tầng 1 = thêm 2 field optional `avatar`/
`audioSource` vào `TemplateScript` (additive, không đổi hành vi render, 3 file
test PNJ/FPT/FVA vẫn valid nguyên xi). Tầng 2 = sửa THẬT `template-pipeline.ts`
+ `video-tools.ts` + viết HeyGen API client (giống `elevenlabs-client.ts`) —
việc kỹ thuật có gọi API async, lên task riêng, KHÔNG phải "chỉ thêm field".

**Cần Lead chốt** (mục 6 của proposal, e–h): (e) duyệt Tầng 1 ngay?; (f) lịch
Tầng 2; (g) ai gọi HeyGen API — đề xuất là AIGEN/agent-B vì cần audio AIGEN vừa
TTS; (h) `avatarId` lấy từ đâu (Content Factory tự chọn hay danh sách cố định).

⚠️ File `AVATAR_HEYGEN_PROPOSAL.md` hiện UNTRACKED bên aigen — người vận hành
`git add` để đưa vào lịch sử repo (đề xuất đã đánh giá là chính xác, nên giữ).

---

## QUY TẮC VÀNG KHI ĐỘNG VÀO SHEET

`ensure_tabs()`/`migrate_rows()` tự chạy khi mở board, map theo TÊN cột — đổi
tên cột từng XÓA RỖNG dữ liệu thật (mất Gate 1 của 3 dòng). `mergeCells` từng
XÓA THẬT Context/Timestamp, không idempotent.

→ Mọi thao tác đổi cấu trúc Sheet: xác nhận đường gọi `_headers_need_setup()`/
migrate TRƯỚC → snapshot TRƯỚC → làm → đối chiếu SAU.
