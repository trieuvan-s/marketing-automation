# BÀN GIAO CUỐI NGÀY — 2026-07-27 (P2 store-as-truth, agent-A)

> File TỔNG HỢP cuối cùng của phiên hôm nay — đọc file này TRƯỚC, 2 file kia
> chỉ để tra chi tiết lịch sử nếu cần:
> - [HANDOFF_2026-07-27_agentA.md](HANDOFF_2026-07-27_agentA.md) — renderer đọc
>   STORE thay Sheet preview (bug Bước 5.3) + Bước 5.4 phục hồi thật.
> - [HANDOFF_2026-07-27_agentA_queue.md](HANDOFF_2026-07-27_agentA_queue.md) —
>   PHASE QUEUE (`execution_queue` + `queue_worker.py` + ráp `api/main.py`).

## TÓM TẮT — ĐÁNH GIÁ THẲNG (đã trao đổi + Lead đồng ý hướng đi)

**Code + kiến trúc đủ vững để commit + merge.** Nhưng bài kiểm quan trọng nhất
— "1 topic mới chạy TRỌN VẸN qua hàng đợi ra đủ 3 loại nội dung SẠCH" — **CHƯA
đạt**, vì lý do NGOÀI code (giới hạn dùng "Claude Code" — xem mục "GIỚI HẠN
CLAUDE CODE" bên dưới). Merge lần này là merge kèm ghi rõ giới hạn, KHÔNG phải
"đã test xong 100%". `python -m pytest` → **621 passed, 0 failed**.

## VIỆC MỚI trong phiên này (SAU 2 file handoff kia)

### 1. Dọn Sheet — xoá 2 tab backup

Xoá `CONTEXT_backup_p2-truoc-buoc52-20260725` + `CONTENT_backup_p2-truoc-buoc52-20260725`
(backup trước Bước 5.2, theo yêu cầu Lead "hệ thống đang phát triển, dữ liệu
chưa quan trọng"). **Không xoá gì trong DB** — kiểm tra thấy 2 TopicKey trùng
giữa bản backup và store hiện tại (`90e8175b4a883d1c`, `b63ad00e9fd6e8af`)
nhưng đó là **dữ liệu ĐANG HOẠT ĐỘNG thật** (2 trong các dòng CONTEXT test
suốt các phiên trước), không phải rác backup — đã báo Lead, KHÔNG xoá.

### 2. Crawl thật hôm nay (27/07/2026)

`review_to_sheet.py` chạy thật — CONTEXT +5 dòng mới, tổng 12 dòng.

### 3. Vá 2 lỗ hổng trong `scripts/queue_worker.py` (phát hiện khi chuẩn bị e2e thật)

- **Enqueue không tự động**: KHÔNG có gì gọi `ingest_context_from_sheet()`
  định kỳ trước đây → Gate1=APPROVE trên Sheet KHÔNG BAO GIỜ tự sinh job. Đã
  vá: `run_once()` giờ tự ingest CONTEXT+CONTENT mỗi vòng poll (rẻ, chỉ đọc +
  ghi có điều kiện).
- **Sheet đứng hình sau khi xử lý xong**: `queue_worker.py` chỉ ghi STORE,
  KHÔNG render ngược lại Sheet → Execute/CONTENT trên Sheet đứng yên ở giá trị
  lúc duyệt dù store đã có DONE/FAILED/ERROR thật (xác nhận thật: topic
  `cd4994b3749257d8` có `gate_status.execute=DONE` trong store nhưng Sheet vẫn
  hiện "RUN"). Đã vá: render lại CONTEXT+CONTENT NGAY sau khi xử lý xong 1
  job (không render mỗi vòng poll rỗng — tốn quota Sheets API vô ích).
- 2 test mới xác nhận (`store/test_sync_service.py`, `tests/test_pipeline.py`).

### 4. Fix dropdown "Output Type" trên tab CONTEXT

Bug: cột này CHƯA TỪNG có nhánh `setDataValidation` trong `_tab_requests()`
(`src/twmkt/sheets_board.py`) — ô Sheet lộ dropdown SÓT của cột Execute (4 giá
trị RUN/DONE/FAILED/NEEDS_HUMAN) do Output Type được chèn giữa Duyệt
Context/Execute bằng ghi lại header (không phải true "insert column"). Đã
thêm nhánh riêng, đúng `OUTPUT_TYPE_VALUES` (Article/Long-Article/Infographic/
Video/AUTO). Ô rỗng giờ hiển thị chữ **"AUTO"** tường minh thay vì để trắng
(hành vi xử lý KHÔNG đổi — `_allowed_output_types(["AUTO"])` vẫn = không giới
hạn thêm). Đã áp dụng + xác nhận thật qua Sheets API trên Sheet production
(đối chiếu snapshot xác nhận KHÔNG đổi dữ liệu, chỉ format/validation).

**Giới hạn API đã tra cứu** (không sửa được): Google Sheets API v4 KHÔNG hỗ
trợ "dropdown chip / cho phép chọn nhiều" qua `batchUpdate` — chỉ bật thủ công
qua UI Sheets. `strict: False` vẫn cho gõ tay nhiều giá trị phân tách dấu
phẩy, đủ dùng ở tầng dữ liệu.

**Đã DỪNG đúng ranh giới** (theo yêu cầu Lead, KHÔNG tự xây): ngữ nghĩa AUTO
MỚI (Composer tự đánh giá độ giàu thông tin/mức độ quan trọng → chọn 1-2 định
dạng) và Long-Article (chờ rule mới từ agent-C) — đã ghi chú kỹ trong
`sheets_board.py` cho agent-B đọc, CHƯA xây.

### 5. Đổi backend LLM cho Producers — Claude Pro/Max thay Anthropic API

Theo yêu cầu Lead ("phiên phát triển, request còn ít, dùng Claude Pro thay vì
trả phí riêng qua Anthropic API"):

- Phát hiện: `factory.build_content_llm()` (dùng cho InfographicSpecAgent/
  VideoScriptAgent) LUÔN đi qua `llm.provider` (chỉ hỗ trợ mock|anthropic),
  KHÁC hẳn `make_llm()`/`build_writer_llm()` (đã hỗ trợ `llm.mode=claude_code`
  từ trước) — thiếu `ANTHROPIC_API_KEY` khiến content_llm ÂM THẦM lùi mượt về
  MOCK, sinh "video: MOCK (chưa bật Sonnet)" giả thay vì thật.
- Sửa: `src/twmkt/factory.py::_build_llm()` thêm nhánh `provider="claude_code"`
  (CLI `claude -p`, cùng cơ chế writer_llm đã dùng). `config/settings.yaml`:
  `llm.provider: "anthropic"` → `"claude_code"`.
- **LƯU Ý VẬN HÀNH QUAN TRỌNG**: đổi code Python trong khi `queue_worker.py`
  ĐANG CHẠY sẽ KHÔNG tự áp dụng (tiến trình Python không tự nạp lại module) —
  PHẢI dừng + khởi động lại `queue_worker.py` sau MỌI thay đổi code/config.
  Đã tự phát hiện: quên restart khiến vài topic vẫn ra "MOCK" dù code đã sửa
  đúng — đã restart lại, xác nhận đúng 1 tiến trình (`Get-CimInstance
  Win32_Process`, lock file khớp PID).
- 3 test mới (`tests/test_pipeline.py`).

### 6. Chạy thử e2e thật — KẾT QUẢ + GIỚI HẠN CLAUDE CODE (⚠️ quan trọng nhất)

Lead tự duyệt Gate1=APPROVE cho nhiều topic thật (không chỉ 3 như dự kiến ban
đầu). Kết quả quan sát qua store thật:

| Topic | Output Type | Kết quả |
|---|---|---|
| `cd4994b3...` (thuế 12,5%) | AUTO | Execute=DONE. Article ERROR (guardrail bắt ĐÚNG số liệu bịa "12,5%" không có trong evidence — **hành vi guardrail ĐÚNG THIẾT KẾ**). Infographic/Video SKIPPED (router quyết định đúng — tin định tính). **Đây là 1 lượt ĐI TRỌN đường hàng đợi mới, kết quả nghiệp vụ hợp lý dù không "sạch 100%".** |
| `47df5043...` (ethanol) | Article | FAILED — `claude -p` lỗi exit 1, do giới hạn Claude Code (xem dưới). |
| `2430635b...` (VietinBank) | Article | FAILED — cùng lý do. |
| `8c005ecb...` (dòng tiền cá mập) | Infographic | ERROR "facts[] rỗng" (Brief không trích được số — nghi cũng do giới hạn Claude Code chặn brief). |
| `be553781...`, `90e8175b...` | AUTO | ERROR/guardrail đúng + video MOCK (chạy TRƯỚC khi restart worker áp fix #5). |

**GIỚI HẠN CLAUDE CODE — chưa giải quyết**: `claude -p` liên tục trả
`is_error:true, api_error_status:429, "You've hit your monthly spend limit"`.
Đã xác nhận `claude auth status` — ĐÚNG tài khoản Lead (email khớp, gói Pro),
KHÔNG PHẢI lỗi xác thực/nhầm tài khoản. Giả thuyết có căn cứ nhất (Lead + tôi
cùng thảo luận): "Claude Code" là 1 hạn mức RIÊNG (tách khỏi % chat claude.ai
hiển thị trên trang usage), và **hạn mức này DÙNG CHUNG giữa chính phiên
Claude Code agent đang chạy việc này (rất dài, rất nhiều thao tác) VÀ các lệnh
`claude -p` lồng bên trong nó** — nên phiên dài tự nó đã ăn phần lớn hạn mức
trước khi tới lượt xử lý topic thật.

**Hệ quả cho agent-B**: **PHẢI là người đầu tiên chạy lại đủ 1 lượt e2e SẠCH**
(topic mới, đủ 3 loại nội dung, KHÔNG dính lỗi hạ tầng) trước khi coi hệ
thống "sẵn sàng dùng thật" — đây là việc CÒN TREO quan trọng nhất, không phải
"đã xong chờ fix nếu có bug". Khuyến nghị: chạy `queue_worker.py` từ terminal
THƯỜNG (không lồng trong 1 phiên Claude Code agent khác) để không tranh hạn
mức, HOẶC đợi mốc reset (phiên hiện tại reset sau vài giờ, hạn mức tuần reset
theo lịch cố định — xem claude.ai/settings/usage).

### 7. Task Scheduler cho `queue_worker.py` — VẪN CHƯA ĐĂNG KÝ ĐƯỢC

`Register-ScheduledTask`/`schtasks.exe` đều "Access is denied" — phiên
PowerShell hiện tại không chạy quyền Administrator (dù tài khoản có trong
nhóm Administrators, UAC hạ quyền token). Đã đưa Lead lệnh PowerShell đầy đủ
để tự chạy trong cửa sổ "Run as Administrator" (xem chat, chưa xác nhận Lead
đã chạy). **Hiện `queue_worker.py` chỉ chạy tay** (khởi động lại nhiều lần
trong phiên qua Bash tool) — KHÔNG bền qua khi tắt máy/phiên.

## VIỆC CÒN TREO (ưu tiên cho agent-B, theo thứ tự)

1. **[QUAN TRỌNG NHẤT]** Chạy lại e2e sạch (mục 6) sau khi hết giới hạn Claude
   Code — xác nhận thật 1 topic ra đủ 3 loại nội dung KHÔNG lỗi hạ tầng.
2. Đăng ký `queue_worker.py` qua Task Scheduler (lệnh PowerShell đã đưa Lead,
   cần chạy quyền Admin) — hoặc NSSM nếu lên VPS.
3. Quyết định sửa `src/twmkt/agents/base.py::ClaudeCodeLLM.complete()` —
   hiện khi `claude -p` lỗi (exit≠0) chỉ đọc `stderr` (thường rỗng), bỏ qua
   `stdout` (nơi CLI thật sự trả JSON lý do, vd lỗi 429 ở mục 6) — Telegram
   báo lỗi trống `''` thay vì lý do thật. Lead CHƯA xác nhận cho sửa (file
   ngoài ranh giới agent-A phiên này).
4. AUTO (Composer chọn 1-2 định dạng theo độ giàu thông tin) + Long-Article
   (rule mới agent-C) — xem ghi chú trong `sheets_board.py`, CHƯA xây.
5. Cân nhắc bỏ `schedule_draft` (30 phút cũ) nếu đường `run()` qua hàng đợi
   mới đã đủ thay thế — 2 cơ chế hiện cùng tồn tại, không xung đột nhưng có
   thể gây nhầm.
6. Đề xuất Phần B (Redis/RabbitMQ + webhook thật + VPS) — xem
   `docs/VPS_MIGRATION_BACKLOG.md` mục D2, giao khi có VPS.

## RANH GIỚI (giữ nguyên suốt phiên)

Không đụng aigen-pipeline (repo khác), `validators/`, `content-rules/`
(agent-C), `ai_full.py`/`brand_stamp.py`. Không đổi schema Sheet (tên cột).
Không cài Redis/RabbitMQ thật. Không tự sửa `agents/base.py` (chờ xác nhận).
Không tự merge `develop` (Lead tự quyết + tự yêu cầu agent-B).

## FILE THAY ĐỔI (đầy đủ cả 3 việc trong ngày — CHƯA COMMIT tới thời điểm viết file này)

```
M api/README.md
M api/main.py
D api/pipeline_bridge.py
M api/test_main.py
M config/settings.yaml
M docs/VPS_MIGRATION_BACKLOG.md
M reports/TEST_RESULT.md
M scripts/produce_from_sheet.py
M scripts/render_production_assets.py
M src/twmkt/factory.py
M src/twmkt/sheets_board.py
M store/schema.sql
M store/sync_service.py
M store/test_sync_service.py
M tests/test_pipeline.py
?? scripts/queue_worker.py
?? scripts/sync_store_sheet.py
?? store/queue_store.py
?? store/test_queue_store.py
?? tasks/HANDOFF_2026-07-27_agentA.md
?? tasks/HANDOFF_2026-07-27_agentA_queue.md
?? tasks/HANDOFF_2026-07-27_agentA_final.md   (file này)
```

`python -m pytest` → **621 passed, 0 failed** (chạy lần cuối ngay trước khi
viết file này).

## TRẠNG THÁI SHEET/STORE THẬT SAU PHIÊN

CONTEXT: 12 dòng (7 cũ + 5 crawl mới hôm nay), 2 tab backup đã xoá. Nhiều
topic đã qua hàng đợi mới (xem bảng mục 6) — kết quả THẬT phản ánh đúng trên
Sheet (đã render lại). `queue_worker.py` đang chạy (tay, PID xác nhận qua lock
file `<data_root>/logs/queue_worker.lock`), sẽ tự bắt các Gate1=APPROVE mới.

## HƯỚNG DẪN COMMIT + PUSH (agent-A thực hiện theo yêu cầu Lead)

```bash
git add api/ config/settings.yaml docs/VPS_MIGRATION_BACKLOG.md \
        reports/TEST_RESULT.md scripts/produce_from_sheet.py \
        scripts/render_production_assets.py scripts/queue_worker.py \
        scripts/sync_store_sheet.py src/twmkt/factory.py \
        src/twmkt/sheets_board.py store/ tests/test_pipeline.py \
        tasks/HANDOFF_2026-07-27_agentA.md tasks/HANDOFF_2026-07-27_agentA_queue.md \
        tasks/HANDOFF_2026-07-27_agentA_final.md

git commit -m "P2 store-as-truth: fix renderer/store, PHASE QUEUE (execution_queue + queue_worker.py), fix dropdown Output Type, doi content_llm sang Claude Code CLI"

git push -u origin feature/store-as-truth
```

**CHƯA merge `develop`** — Lead sẽ tự cân nhắc yêu cầu agent-B ngay hay chờ
xử lý xong giới hạn Claude Code + chạy e2e sạch trước (mục "VIỆC CÒN TREO #1").
