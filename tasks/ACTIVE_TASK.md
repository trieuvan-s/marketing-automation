# ACTIVE_TASK — Tái cấu trúc 2 repo (marketing-automation ↔ aigen-pipeline)

> **GHI ĐÈ MỖI PHIÊN** — file này phản ánh trạng thái NGAY LÚC dừng phiên gần
> nhất, không phải log lịch sử (lịch sử: `PROJECT_HANDOFF_P5.md`). Viết lại
> 2026-07-19, phiên bị cắt ngang giữa chừng vì hết tài nguyên — nhiều phần
> **CHƯA XONG**, đọc kỹ mục "CHƯA LÀM" trước khi tiếp tục, đừng làm lại từ đầu.

## QUY ƯỚC WORKFLOW
1. Đọc `CLAUDE.md` → file này → `docs/ARCHITECTURE_MODULES.md` (kiến trúc
   tổng, ĐỌC TRƯỚC KHI ĐỘNG VÀO BẤT CỨ GÌ) → `docs/CONTENT_OUTPUT_SCHEMA.md`
   (schema JSON chốt, có version) → `docs/MODULE_INDEX.md` khi cần định vị
   code. Cả 4 file này tồn tại GIỐNG HỆT ở CẢ HAI repo.
2. **DỪNG-BÁO-CÁO** khi ra ngoài scope hoặc gặp 1 trong 4 điều ở mục "DỪNG
   KHI" cuối file. KHÔNG auto-commit.
3. Nợ dài hạn không thuộc task này: `docs/VPS_MIGRATION_BACKLOG.md`
   (file chỉ-thêm, không ghi đè — đọc trước khi bắt tay, có mục A0 "ưu tiên
   cao nhất" liên quan trực tiếp task này).

## Kiến trúc đã CHỐT (không mở lại — xem đầy đủ ở `docs/ARCHITECTURE_MODULES.md`)
2 repo, ranh giới = `CONTENT.Output` (JSON, có version — KHÔNG PHẢI
`ProductionSpec` như thiết kế cũ). marketing-automation (Python) sinh
`CONTENT.Output`; aigen-pipeline (TypeScript) biến nó thành video —
`ProductionScene`, guardrail-2 nhánh video, Scene Builder, chuẩn hoá
voice_text **ĐÃ CHUYỂN HẲN sang TypeScript** (không còn ở Python). Renderer
Infographic + `ProductionBlock` **Ở LẠI** Python.

Nguyên tắc: **Composer (Opus, TRƯỚC Gate 2) là nơi DUY NHẤT có trí thông
minh/LLM.** Sau Gate 2: 100% code tất định — kể cả chuẩn hoá số→chữ và
ticker→phiên âm, KHÔNG giao LLM (bài học rút ra giữa phiên: LLM/kể cả người
suy luận theo quy tắc chữ-cái đều ĐOÁN SAI cách đọc ticker thật — VNM đọc
"vi na miu" theo thương hiệu, không theo quy tắc nào suy ra được. Xem
`docs/CONTENT_OUTPUT_SCHEMA.md` phần Fact/ví dụ để hiểu tại sao).

---

## TRẠNG THÁI 6 PHA (2026-07-19, cuối phiên)

### PHA 0 — Tài liệu — **XONG**
- `docs/ARCHITECTURE_MODULES.md` — tạo mới, giống hệt 2 repo.
- `docs/CONTENT_OUTPUT_SCHEMA.md` — tạo mới, giống hệt 2 repo (schema
  `CONTENT.Output` video, version 1, đối chiếu `Fact` thật từ `models.py`).
- `docs/MODULE_INDEX.md` — cập nhật cả 2 repo (aigen-pipeline trước đó CHƯA
  có file này, đã tạo mới).
- `PROJECT_HANDOFF_P5.md` — sửa 2 chỗ nói sai "Production Factory =
  media_factory/".
- `docs/VPS_MIGRATION_BACKLOG.md` — thêm mục A6 (DB chung, chi tiết hoá B1).

### PHA 1 (aigen-pipeline: đo + port `ProductionScene`/guardrail-2 video) — **XONG, ĐÃ Ở `develop`, PR draft mở**
**CẬP NHẬT 2026-07-19 (sau khi Lead tự tay dọn nhánh)**: nhánh làm việc
`feature/production-spec` đã được Lead **đổi tên thẳng thành `develop`**
(local + remote, xác nhận qua `git ls-remote origin develop` khớp commit
`2a7a2a8`). `aigen-pipeline` giờ có đúng 2 nhánh: `main` (sạch, chỉ có PR #1
cũ) và `develop` (chứa toàn bộ PHA 1+3). Đã mở **PR draft** `develop` → `main`
trên GitHub (GitHub tự cập nhật PR theo tên nhánh mới khi rename) — ĐỂ Ở
TRẠNG THÁI DRAFT có chủ đích, xem lý do ở mục PHA 1.1 ngay dưới. Nhánh cũ
`feature/adapter-productionspec` (PR #1, đã merge từ trước) đã bị xoá cả
local lẫn remote — sạch.

Trước khi tìm thấy trạng thái thật ở trên, tôi từng tưởng subagent làm PHA
1+3 bị mất (worktree rỗng, `TaskStop` báo "No task found") — điều tra lại kỹ
hơn phát hiện subagent thực ra làm việc TRỰC TIẾP trên cây chính
`aigen-pipeline` (không phải worktree cô lập như dự kiến ban đầu) và ĐÃ HOÀN
THÀNH thật trước khi bị dừng. Đã kiểm tra: `npx vitest run src/production-spec`
→ 82/82 pass; `npx tsc --noEmit` sạch; full suite 204/206 (2 fail còn lại là
`ffmpeg`/`ffprobe` ENOENT, hạn chế PC-A đã biết từ trước, không liên quan).

**Việc PHA 1.1 (đo trước) — CHƯA có báo cáo số liệu tường minh** từ subagent
(không rõ có thực sự đo dòng/kiểm tra "guardrail-2 tách sạch" như brief yêu
cầu, hay chỉ port thẳng dựa trên đọc code). Code port
(`src/production-spec/spec.ts` + `guardrail/verify-spec.ts`) NHÌN kỹ lưỡng
(vd tự nhận ra và xử lý đúng 1 nuance không có trong brief: `CONTENT.Output.
disclaimer` ở top-level cần bridge vào `slots.disclaimer` của scene outro,
xem docstring `src/production-spec/index.ts::withDisclaimerOnOutro`) — NHƯNG
**CHƯA CÓ AI (Lead) đối chiếu tay port này với `verify_spec()` Python gốc**
để xác nhận đúng semantics 100%, đặc biệt: NFC-normalize (ĐÃ CÓ,
`verify-spec.ts:42`), 5 shape fact, salience. Đây là việc nên làm trước khi
mở PR/merge.

`media_factory/aigen_seam.py` (Python) — **CHƯA THẤY ghi nhận đánh giá** còn
cần hay không trong bất kỳ đâu (report của subagent hay code) — vẫn là câu
hỏi mở, xem lại khi có thời gian.

### PHA 2 (marketing-automation: chuẩn hoá output Composer) — **CODE XONG, CHƯA DUYỆT CHẤT LƯỢNG**
**Nằm trên branch riêng, CHƯA merge vào `develop`:**
`feature/video-composer-schema-pending-review` (đã push lên
`origin` — `git fetch && git checkout feature/video-composer-schema-pending-review`
để xem). Nội dung: `prompts/video.v1.md` (chỉ dòng định dạng đầu ra),
`agents/production.py` (`VideoScriptAgent.system`/`video_fields_from_data()`/
`render_video()` — parse+serialize schema mới), test cập nhật khớp.
`python tests/test_pipeline.py` → **400/400 xanh** trên branch đó.

**⚠️ VIỆC CÒN THIẾU, BẮT BUỘC TRƯỚC KHI MERGE**: kiểm tra hồi quy chất lượng
biên tập. Dữ liệu THÔ đã có sẵn trên branch đó, tại
`reports/regression_video_prompt/` — 3 chủ đề × (bản CŨ + bản MỚI, prompt
khác nhau, cùng input, Opus thật):
`cong_ty_lo_q2`, `vietnam_airlines_co_dong`, `4_cang_bien_dac_biet`
(mỗi chủ đề 2 file `*_old.txt`/`*_new.txt`). **CHƯA CÓ AI ĐỌC ĐỐI CHIẾU
CŨ/MỚI** — đây là việc CHỈ NGƯỜI (Lead) làm được, không giao LLM/subagent
(phán đoán biên tập cần sắc thái). Đọc xong, nếu chất lượng KHÔNG giảm →
merge branch vào `develop`. Nếu giảm → sửa prompt tiếp, KHÔNG tự vá bằng
thêm luật máy móc.

### PHA 3 (aigen-pipeline: Scene Builder + voice layer) — **XONG, CHƯA MERGE** (cùng branch `feature/production-spec` với PHA 1, xem trên)
Đã có đủ: `src/production-spec/voice/spell-out-numbers.ts` +
`voice/pronunciation.ts` (đọc file `pronunciation_dict.vi.json` trực tiếp,
KHÔNG gọi HTTP :8881 — xác nhận đúng yêu cầu), `scene-builder/index.ts`
(ánh xạ thuần tất định), `index.ts::buildTemplateScriptFromContentOutput()`
(orchestration đầy đủ: scene-builder → voice → guardrail-2 → adapter có
sẵn). Từ điển đã thêm ĐÚNG 4 entry đã xác nhận (`PNJ`/`VNM`/`HPG`/`MWG`),
không thêm gì khác — đã đối chiếu diff, sạch.

**✅ ĐÃ SOI MẮT** (2026-07-19, cuối phiên) — chạy `normalizeForTts()` thật
trên 3 câu (mẫu FPT + câu có cả 4 ticker + câu acronym GDP/CPI/ETF), kết
quả ĐÚNG cả 3: `4,98%→"bốn phẩy chín tám phần trăm"`,
`66.800→"sáu mươi sáu nghìn tám trăm"`, `739→"bảy trăm ba mươi chín"`,
`PNJ→"pi en di"`, `VNM→"vi na miu"`, `HPG→"hát pê gờ"`,
`MWG→"mờ đắp-liu gờ"` (khớp CHÍNH XÁC 4 mã Lead xác nhận), `GDP→"giê đê
pê"`/`CPI→"xê pê ai"`/`ETF→"i tê ép"` (khớp từ điển FVB có sẵn). `FPT`
(KHÔNG có trong từ điển) giữ nguyên thô — ĐÚNG THIẾT KẾ (alias-guardrail sẽ
chặn khi gặp thật, không đoán mù). Lệnh xác minh (đứng ở gốc `aigen-pipeline`,
branch `feature/production-spec`, viết 1 file `.mts` tạm với import tương
đối rồi `npx tsx` — import path tuyệt đối `E:/...` KHÔNG chạy được với ESM
loader của Node, đã gặp lỗi `ERR_UNSUPPORTED_ESM_URL_SCHEME`, phải dùng
đường dẫn tương đối).

**Vẫn còn CHƯA làm**: chỉ soi 3 câu, chưa soi hết mọi edge case (số âm, ngày
tháng dạng khác, số cực lớn) — 82/82 test tự động phủ nhiều ca hơn nhưng
Lead chưa đọc TỪNG assert xem có tự viết expect sai theo hay không.

### PHA 4 (nối thông + dọn đường dẫn) — **CHƯA LÀM** (phụ thuộc PHA 1-3 xong)
4.1 Grep "aigen-fva-capital" cả 2 repo phải về 0 (đã gần 0 từ phiên trước,
chỉ còn ghi chú lịch sử hợp lệ — kiểm lại sau khi PHA 1-3 xong, có thể phát
sinh thêm nếu subagent trước đó có sửa gì không rõ).
4.2 Chạy end-to-end 1 bài THẬT: `CONTENT.Output` → scene-builder → voice →
guardrail → adapter → `TemplateScript`, Zod validate thật. KHÔNG render
AIGEN thật (máy không đủ phần cứng — xem PHA 6 cho việc trên VPS).
4.3 Audit môi trường VPS — **ĐÃ LÀM XONG** (subagent Nhánh C hoàn tất, xem
`docs/VPS_MIGRATION_BACKLOG.md` mục ghi chú audit, hoặc tìm trong lịch sử
hội thoại phiên này nếu cần chi tiết đầy đủ — tóm tắt: chưa có Task
Scheduler/service nào đăng ký, đang chạy tay; OmniVoice cần driver NVIDIA
≥570/CUDA 12.8, đã test trên GTX 1070 Ti Pascal; 0 xung đột tên file hoa/thường).

### PHA 5 (test + commit) — **CHƯA LÀM**
Chờ PHA 1-4 xong. `aigen-pipeline`: branch mới `feature/production-spec`,
MỞ PR, KHÔNG merge main. `marketing-automation`: branch `develop`, sau khi
PHA 2 được Lead duyệt chất lượng và merge `feature/video-composer-schema-pending-review`.

### PHA 6 (đóng gói data move VPS) — **CHƯA LÀM**
Xem mục "DỮ LIỆU NGOÀI GIT — CẦN COPY TAY" bên dưới (đã liệt kê đủ, chưa
đóng gói/nén).

---

## DỮ LIỆU NGOÀI GIT — CẦN COPY TAY LÊN VPS

### marketing-automation
- **`E:\marketing-automation-database\`** (data_root, sibling ngoài repo) —
  **47MB**: `output/` 47MB (gần hết dung lượng), `documents/` 88KB,
  `logs/`+`state/` rỗng. Đường dẫn tương đối `../marketing-automation-database`
  trong `settings.yaml`, không hardcode ổ đĩa — copy nguyên thư mục, đặt
  đúng vị trí sibling so với repo trên VPS.
- **`secrets/.env`** (732 bytes) — 2 biến ACTIVE: `TELEGRAM_BOT_TOKEN`,
  `TELEGRAM_CHAT_ID` (giá trị KHÔNG được in ra bất cứ đâu, tự điền tay).
  `ANTHROPIC_API_KEY` hiện để trống hợp lệ (llm.mode="claude_code", dùng
  CLI `claude -p`, không cần key riêng — chỉ cần nếu đổi sang llm.mode="api").
- **`secrets/sa.json`** (2389 bytes) — credential Service Account Google
  Sheet, tham chiếu qua `settings.yaml: sheets.creds_path`.

### aigen-pipeline
- **`node_modules/`** — KHÔNG copy, cài lại bằng `npm install` trên VPS
  (112 package, `package-lock.json` đã khớp sẵn).
- **`.env.local`** (nếu có, cho OmniVoice/ElevenLabs — xem `RUNTIME.md`) —
  chưa xác nhận đã tồn tại trên máy này, kiểm tra lại khi dựng VPS.
- **Tầng 2 chưa dựng trên máy này** (không phải "dữ liệu cần copy" mà là
  "phần mềm cần CÀI MỚI trên VPS"): ffmpeg/ffprobe, OmniVoice server
  (`:8123`), financial-voice-bible server (`:8881` — CHỈ dùng làm nguồn dữ
  liệu tĩnh cho `voice/`, KHÔNG chạy service này trong luồng render thật).

### Thứ tự dựng trên VPS (tham khảo, chi tiết đầy đủ hơn cần viết
`out/move-to-vps/MOVE_README.md` — **CHƯA VIẾT**, PHA 6 chưa làm):
1. Clone `marketing-automation` + `aigen-pipeline` làm sibling directory.
2. `npm install` (aigen-pipeline).
3. Copy `E:\marketing-automation-database\` (data_root) vào đúng vị trí
   sibling.
4. Điền `secrets/.env` + `secrets/sa.json` (marketing-automation).
5. Đổi `storage.asset_server_enabled: false → true` trong
   `config/settings.yaml` (cho `system_power_on.py` tự chạy asset server).
6. Đăng ký Task Scheduler/NSSM cho `system_power_on.py` (CHƯA có cơ chế
   nào — `scripts/run_scheduler.py --print-os` in sẵn lệnh `schtasks` mẫu
   để tham khảo).
7. Chạy test 2 repo (`python tests/test_pipeline.py`, `npx vitest run`).
8. Merge `feature/video-composer-schema-pending-review` SAU KHI Lead đọc
   xong `reports/regression_video_prompt/` (xem PHA 2).
9. Làm nốt PHA 1/3 (aigen-pipeline, theo brief ở trên).
10. Chạy thử 1 video thật (PHA 4.2 mở rộng — có phần cứng GPU/OmniVoice
    thật trên VPS, máy PC-A này không có).

---

## DỪNG KHI (4 điều, không đổi so với lần chốt trước)
1. Guardrail-2 KHÔNG tách sạch đôi được (PHA 1.1).
2. Chất lượng biên tập GIẢM ở kiểm tra hồi quy (PHA 2 — Lead tự đọc, chưa
   xong ở cuối phiên này).
3. Cần render AIGEN thật (máy không đủ phần cứng).
4. Đụng kiến trúc đã chốt ở `docs/ARCHITECTURE_MODULES.md`.

## KHÔNG LÀM
Không đụng `src/render/` (aigen-pipeline, ruột AIGEN, agent-B sở hữu).
Không đụng `src/adapter/` (đã xong, 79/79 test, PR #1 merged). Không xây
DB chung (A6 — làm sau khi luồng thông). Không reset Sheet (Sheet ĐANG LÀ
database, xem "QUY TẮC VÀNG" trong `docs/VPS_MIGRATION_BACKLOG.md`). Không
merge `feature/video-composer-schema-pending-review` vào `develop` trước
khi Lead đọc xong hồi quy. Không merge bất cứ gì vào `main` (aigen-pipeline).
