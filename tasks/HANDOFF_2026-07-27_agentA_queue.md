# BÀN GIAO — phiên 2026-07-27 (P2 store-as-truth, agent-A)
## PHASE QUEUE — hàng đợi request thực thi + ráp webhook

> Tiếp nối trực tiếp [tasks/HANDOFF_2026-07-27_agentA.md](HANDOFF_2026-07-27_agentA.md)
> (fix renderer đọc STORE thay Sheet preview + Bước 5.4 — đã xong, xanh, chưa
> commit). File này là việc THỨ 2 trong CÙNG phiên, sau khi Lead yêu cầu hoàn
> thiện "Store-as-truth": Sheet chỉ là UI, cần hàng đợi cho nhiều request thực
> thi cùng lúc.

## TÓM TẮT

Lead yêu cầu kiến trúc event-driven qua Redis/RabbitMQ + webhook Google Sheets
thật + worker real-time. Tôi đã trình bày đánh đổi (chưa có VPS/endpoint
always-on, Redis/RabbitMQ là hạ tầng hoàn toàn mới cho quy mô hiện tại quá cỡ)
và Lead đồng ý chia 2 phần — **đã hỏi qua AskUserQuestion + ExitPlanMode,
Lead duyệt plan trước khi code** (xem `C:\Users\PC\.claude\plans\jazzy-humming-kitten.md`
nếu cần đọc lại nguyên văn):

- **Phần A (ĐÃ LÀM, phiên này)**: hàng đợi THẬT bằng SQLite (`execution_queue`,
  cùng file `store/document_store.db`) + worker độc lập `scripts/queue_worker.py`
  (poll 3s) + `api/main.py` ráp vào hàng đợi này (thay đọc/ghi Sheet + registry
  in-memory cũ).
- **Phần B (ĐÃ VIẾT ĐỀ XUẤT, KHÔNG CODE)**: mục D2 mới trong
  `docs/VPS_MIGRATION_BACKLOG.md` — kiến trúc Redis/RabbitMQ + Apps Script
  webhook thật + VPS, giao agent-B khi có VPS. `queue_store.py` thiết kế để
  đổi backend mà KHÔNG sửa caller.

**618/618 test xanh** (597 trước phiên này + 21 mới). Đã xác nhận THẬT (không
chỉ mock): enqueue 1 job cho topic Google thật đã DONE → `queue_worker.
run_once()` thật → job `done`, KHÔNG gọi LLM (đúng thiết kế idempotent).
`uvicorn` thật + `curl` thật xác nhận webhook 202/409/status đúng — đã dọn
sạch, không để lại job `queued` treo trong store thật.

## KIẾN TRÚC MỚI (chi tiết xem docstring từng file)

### `store/schema.sql` + `store/queue_store.py` (module mới)
Bảng `execution_queue` (id, topic_key, job_type, status, requested_at,
claimed_at, claimed_by, finished_at, attempt_count, error, payload_json) —
KHÁC `documents` (append-only): bảng này CÓ UPDATE (chuyển trạng thái job tại
chỗ), vì là bookkeeping vận hành, không phải lịch sử nội dung. `id` tự tăng
cho FIFO THẬT (khác `document_store.list_topics()` sắp theo hash).

API: `enqueue()` (dedup nếu đã `queued`/`claimed`), `find_pending()` (tra job
đang chờ/chạy, KHÔNG dùng để dedup — chỉ để caller quyết định 202 vs 409),
`claim_next()` (ATOMIC qua `BEGIN IMMEDIATE`, an toàn nhiều worker dù phiên
này chỉ chạy 1), `mark_done()`/`mark_failed()`, `release_stale_claims()`
(job `claimed` quá hạn lease → requeue hoặc `failed` hẳn sau `max_attempts` —
giải quyết rủi ro C8 đã ghi nhận từ trước: "service chết giữa chừng → Execute
kẹt RUN vĩnh viễn").

**Quan hệ với `gate_status.execute` (KHÔNG đổi)**: `gate_status.execute` VẪN
là nguồn hiển thị Sheet (DONE/FAILED/NEEDS_HUMAN do `produce_from_sheet.py::
run()` tự ghi, y hệt trước). Hàng đợi là khái niệm KHÁC ("đã dispatch xử lý
chưa", không phải "kết quả nghiệp vụ ra sao") — không vi phạm nguyên tắc "2
nguồn sự thật cho cùng 1 trạng thái".

### `store/sync_service.py::ingest_context_from_sheet()`
Tại 2 điểm chuyển Execute thành "RUN" (bootstrap Gate1 vừa APPROVE, NEEDS_
HUMAN→RUN người yêu cầu thử lại) — THÊM 1 dòng gọi `queue_store.enqueue()`.
Không đổi gì khác trong hàm này.

### `scripts/queue_worker.py` (mới, ĐỘC LẬP — theo đúng lựa chọn Lead)
Vòng lặp: `release_stale_claims()` → `claim_next()` → nếu có job:
`produce_from_sheet.run(topic_keys=[tk], limit=1)` → `mark_done()`; `run()`
raise (crash hạ tầng thật sự, KHÁC NEEDS_HUMAN/FAILED nghiệp vụ mà `run()` tự
bắt gọn) → `mark_failed()`. Không job: `sleep(poll_interval_s)`. Khoá
1-worker-1-máy bằng lock file CÙNG PATTERN `system_power_on.py::acquire_lock()`
(tái dùng nguyên hàm, chỉ đổi tên file lock).

Chạy: `python scripts/queue_worker.py` (Ctrl+C để dừng). **CẦN CHẠY SONG SONG**
với `system_power_on.py` (2 tiến trình riêng, không tranh nhau) để job thật sự
được xử lý — hiện CHƯA đăng ký Task Scheduler/NSSM cho worker này (nợ vận
hành, xem "Việc kế tiếp").

### `api/main.py` (viết lại) + xoá `api/pipeline_bridge.py`
`webhook_execute()` giờ CHỈ enqueue (không tự gọi `produce_from_sheet.run()`
nữa — đó là việc CỦA `queue_worker.py`). Double-fire check qua
`queue_store.find_pending()` (409 nếu đã `queued`/`claimed`) thay đọc Sheet +
registry in-memory. `/status/{topic_key}` đọc job mới nhất từ hàng đợi.
`pipeline_bridge.py` xoá hẳn (dead code — sys.path bootstrap gộp thẳng vào
`main.py`).

**ĐẢO NGƯỢC 1 quyết định Lead cũ** (`api/README.md` mục cũ "RÁP SAU #4",
2026-07-19: "KHÔNG xây trạng thái bền thứ hai cho double-fire"). Lead nay
(2026-07-27) muốn đúng 1 trạng thái bền MỚI — hàng đợi. Đã ghi rõ trong
`api/README.md` để không ai ngỡ ngàng khi đọc lại thấy mâu thuẫn với quyết
định cũ.

### `config/settings.yaml` — mục `queue:` mới
`poll_interval_s: 3`, `lease_timeout_s: 600`, `max_attempts: 3`.

### `docs/VPS_MIGRATION_BACKLOG.md` — mục D2 mới (đề xuất Phần B)
Đề xuất Redis/RabbitMQ + Apps Script webhook thật + VPS cho agent-B, kèm lý
do hoãn + cách map từ Phần A.

## RANH GIỚI (đã giữ nguyên, không đụng)

`schedule_draft`/`run_draft()`/`run_ingest()` (luồng `--draft`/Claude Code
file-drop, 30 phút/lần) — GIỮ NGUYÊN, không đụng, khác phạm vi (đối tượng
"nhiều request thực thi cần hàng đợi" là đường `run()` LLM trực tiếp, đang
dùng thật). Không đổi schema Sheet (`CONTEXT_HEADER`/cột "Execute" giữ nguyên,
vẫn hiển thị y hệt trước). Không đụng aigen-pipeline/`validators/`/
`content-rules/`. Không cài Redis/RabbitMQ thật (Phần B chỉ là đề xuất).

## VIỆC KẾ TIẾP (theo thứ tự đề nghị)

1. **Commit** cả 2 phần việc phiên này (renderer/store fix + queue) — xem
   hướng dẫn commit bên dưới.
2. **Đăng ký `scripts/queue_worker.py`** chạy nền thật (Task Scheduler/NSSM,
   giống `system_power_on.py`) — hiện chỉ chạy tay khi cần, CHƯA tự động.
3. **Cân nhắc bỏ `schedule_draft` 30 phút** nếu Lead xác nhận đường `run()`
   trực tiếp (qua hàng đợi mới) đã đủ thay thế nhu cầu — hiện 2 cơ chế cùng
   tồn tại (không xung đột, nhưng có thể gây nhầm "sao có 2 đường sản xuất").
4. Merge `feature/store-as-truth` → `develop` — như phiên trước, CHỜ agent-B
   kiểm nghiệm trước, không tự merge.
5. Khi có VPS: đọc mục D2 `docs/VPS_MIGRATION_BACKLOG.md`, giao agent-B làm
   Phần B (Redis/RabbitMQ + Apps Script thật).

## FILE THAY ĐỔI (working tree, CHƯA COMMIT — gộp CẢ 2 việc phiên này)

```
M api/README.md
M api/main.py
D api/pipeline_bridge.py
M api/test_main.py
M config/settings.yaml
M docs/VPS_MIGRATION_BACKLOG.md
M reports/TEST_RESULT.md
M scripts/produce_from_sheet.py            (việc 1: renderer/store fix)
M scripts/render_production_assets.py      (việc 1: renderer/store fix)
M store/schema.sql
M store/sync_service.py
M store/test_sync_service.py
M tests/test_pipeline.py
?? scripts/queue_worker.py
?? scripts/sync_store_sheet.py             (việc 1: CLI sync_all() trên Sheet thật)
?? store/queue_store.py
?? store/test_queue_store.py
?? tasks/HANDOFF_2026-07-27_agentA.md      (bàn giao việc 1)
?? tasks/HANDOFF_2026-07-27_agentA_queue.md (file này)
```

`python -m pytest` → **618/618 xanh** (chạy lần cuối SAU mọi thay đổi trên).

## HƯỚNG DẪN COMMIT (người vận hành tự làm)

Gợi ý 2 commit tách biệt theo 2 việc (dễ đọc lịch sử hơn 1 commit gộp):

```bash
# Commit 1 -- renderer/store fix + Bước 5.4 (việc TRƯỚC trong phiên)
git add reports/TEST_RESULT.md scripts/produce_from_sheet.py \
        scripts/render_production_assets.py scripts/sync_store_sheet.py \
        store/sync_service.py store/test_sync_service.py tests/test_pipeline.py \
        tasks/HANDOFF_2026-07-27_agentA.md
git commit -m "P2 store-as-truth: renderer/store giu nguyen van Output, them CLI sync_store_sheet.py, Buoc 5.4 xac nhan phuc hoi that"

# Commit 2 -- PHASE QUEUE (viec nay)
git add api/ config/settings.yaml docs/VPS_MIGRATION_BACKLOG.md \
        reports/TEST_RESULT.md store/schema.sql store/queue_store.py \
        store/test_queue_store.py store/sync_service.py store/test_sync_service.py \
        scripts/queue_worker.py tests/test_pipeline.py \
        tasks/HANDOFF_2026-07-27_agentA_queue.md
git commit -m "P2 store-as-truth: them hang doi execution_queue + queue_worker.py doc lap + rap api/ webhook, de xuat Redis/RabbitMQ cho VPS (Phan B)"
```

(Lưu ý `store/sync_service.py`/`store/test_sync_service.py`/`tests/test_pipeline.py`/
`reports/TEST_RESULT.md` có thay đổi TỪ CẢ 2 việc — `git add` theo lệnh 2 phía
trên sẽ gộp đúng phần còn lại vào commit 2 sau khi commit 1 đã lấy phần của
nó; nếu muốn tách bạch tuyệt đối từng dòng, dùng `git add -p` thay vì add cả
file.)

**Chưa merge vào `develop`** — chờ agent-B kiểm nghiệm (theo đúng yêu cầu của
bạn), đặc biệt: cột "Nguồn: cafef.vn" hiển thị domain (việc 1, ghi nhận từ
trước), và AssetPath/`content_status` chưa lưu (việc 1), CỘng THÊM việc MỚI
phiên này — xác nhận `queue_worker.py` chạy ổn định khi để lâu (worker độc
lập, chưa test chạy liên tục nhiều giờ, chỉ test ngắn).
