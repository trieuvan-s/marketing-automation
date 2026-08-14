# CLAUDE.md — hướng dẫn cho Claude Code khi làm việc trên repo này

> File này CHỈ giữ quy tắc đúng cho MỌI task. Bản đồ code: `docs/MODULE_INDEX.md`.
> Quyết định kiến trúc + lịch sử phase: `PROJECT_HANDOFF_P5.md`. Task đang làm:
> `tasks/ACTIVE_TASK.md`. Kết quả suite gần nhất: `reports/TEST_RESULT.md`.
> Nợ dài hạn trước/khi/sau chuyển VPS (file CHỈ THÊM, không ghi đè — khác
> ACTIVE_TASK.md/HANDOFF.md): `docs/VPS_MIGRATION_BACKLOG.md`.

## Kỷ luật vận hành (bắt buộc, mọi task)
- **Config-first.** Tham số ở `config/settings.yaml` (brand ở `config/brand.yaml`,
  MỘT NGUỒN riêng); bí mật qua `${ENV}` (`secrets/.env`, gitignored) — KHÔNG
  hard-code trong code hay tài liệu.
- **KHÔNG auto-commit.** Mọi thay đổi ở trạng thái working tree tới khi người
  vận hành tự `git add`/`commit`/push.
- **Phase nhỏ, DỪNG-BÁO-CÁO.** Việc lớn chia phase, dừng sau mỗi phase để
  review trước khi đi tiếp — bắt buộc trước MỌI thao tác phá huỷ (xoá dòng
  Sheet, đổi schema, `--rekey`, ghi đè file).
- **Chấm trên OUTPUT THẬT.** Test xanh là điều kiện CẦN, không phải ĐỦ — xác
  nhận bằng dữ liệu/round-trip thật trước khi báo "xong" cho việc có rủi ro
  chất lượng/dữ liệu thật.
- **Một mặt trận một lúc.** Không mở nhiều thay đổi kiến trúc song song.
- **Không rò bí mật.** Không dán Sheet ID sản xuất trần, token, đường dẫn cá
  nhân vào tài liệu — chỉ ghi tên biến config.

## Quy ước code
1. **Tất định trước, LLM sau.** Crawl/dedup/chuẩn hoá/chunk/compliance = Python
   thuần ($0 token). LLM chỉ chạm ở bước cần diễn giải ngôn ngữ (Brief/Router/
   Writer/Composer) — KHÔNG bao giờ tự làm phép tính số (xem "AI hiểu ở Brief,
   CODE phán ở Guardrail" trong `agents/brief.py`).
2. **LLM đắt chỉ chạy SAU Gate 1.** Đừng sinh nội dung cho chủ đề chưa được
   người duyệt.
3. **Adapter ở mọi điểm nối ngoài**: collectors, LLM backend, notifier,
   storage, publisher. Thêm nguồn/nền tảng = thêm adapter, không sửa lõi.
4. **Mọi thay đổi phải kèm test.** Chạy `python tests/test_pipeline.py` (hoặc
   `python -m pytest`) trước khi commit — MockLLM/fake fixture, $0.
5. Nội dung tài chính: giữ guardrail compliance; không nới lỏng claim cấm.

## Chạy
```
cd src && python -m twmkt.demo      # demo offline Luồng B, $0 token
python tests/test_pipeline.py       # full suite (hoặc python -m pytest)
```

## Ranh giới kiến trúc đã CHỐT (không đổi trừ khi có quyết định mới ghi vào PROJECT_HANDOFF)
1. **Hai khoá tách bạch, không join.** Corpus (`curation/file_store.py`) khoá =
   content-hash ("document này lưu chưa"). Board (`sheets_board.py`) khoá =
   `TopicKey` ("topic này đã là 1 dòng chưa"). 2 câu hỏi khác nhau về bản chất
   — không tra cứu chéo.
2. **TopicKey = canonical-URL, write-once.** `curation/keys.compute_topic_key()`
   giữ query định danh, chỉ bỏ tracking param. `assign_topic_key()`: đã có khoá
   → trả nguyên, KHÔNG BAO GIỜ tính lại. Không có URL → surrogate `uuid4`.
3. **Membership đọc TRỰC TIẾP cột Sheet, không Source-text/row-index.** CONTEXT
   và CONTENT đều upsert theo `TopicKey` đọc từ Sheet — KHÔNG bằng Source-text
   sống (trôi khi 2 lượt crawl ghi khác nhau), KHÔNG bằng vị trí dòng (dữ liệu
   CŨ trước Sheet UI cleanup Phase 1 có thể trôi vì `mergeCells` từng xoá giá
   trị ô — cơ chế này đã bỏ hẳn, ghi mới dùng băng màu/viền theo TopicKey, xem
   `sheets_board.regroup_and_band_content()`).
4. **TopicKey định danh THEO-TỪNG-BÀI, không mang tính ngữ nghĩa.** Không gom
   "cùng sự kiện, nhiều nguồn" vào 1 khoá — đó là tầng StoryKey CAO HƠN, CHƯA
   XÂY. `cluster_by_event()` (`curation/enrich.py`) chỉ gộp CÙNG LƯỢT crawl
   chéo nguồn, không phải danh tính bền theo thời gian.
5. **VPS đã chạy (từ 2026-08-12), TOCTOU giải bằng CAS theo timestamp, không
   phải distributed lock.** Hệ thống nay chạy trên VPS/máy chủ luôn bật — điều
   kiện "chờ VPS" của mục này đã thoả. Giả định cũ "VPS = 1 nguồn ghi = hết
   TOCTOU" đã bị BÁC BỎ bằng dữ liệu thật (TASK-028/029): race render/ingest
   xảy ra giữa NHIỀU TIẾN TRÌNH cùng 1 máy (`queue_worker.py` + lượt ingest kế
   tiếp tranh nhau ghi cột người-sở-hữu của CONTEXT), không cần 2 máy —
   `system_power_on.py` (thư mục gốc dự án, trước đây `scripts/power_on.py`)
   vẫn chỉ chặn khởi động trùng, không chặn race này. Cách giải đã chốt
   (TASK-030): compare-and-swap theo timestamp trên gate_status
   (`store/sync_service.py::_cas_user_value()`) — `render_context_to_sheet()`
   chỉ ghi đè cột người-sở-hữu khi CHỨNG MINH ĐƯỢC store mới hơn giá trị đang
   có trên Sheet, không thì giữ nguyên. KHÔNG xây distributed lock.
6. **Production Factory = code tất định SAU Gate 2, không phải LLM thêm 1
   vòng.** `media_factory/spec.py: verify_spec()` là guardrail số LẦN 2 (đối
   chiếu `facts[]`), chạy TRƯỚC render — không sinh nội dung mới, chỉ kiểm.

## Không đụng
Repo có **Luồng B** (`orchestrator.py`, `demo.py`, `agents/{researcher,hook,
producers}.py`, `approval/`, `knowledge/rag.py`) — offline demo/legacy, giữ
lại làm thư viện tham khảo. **KHÔNG dùng cho sản xuất thật, KHÔNG gọi lẫn**
với Luồng A (Sheet-based, `sheets_board.py`+`produce_from_sheet.py`+
`agents/production.py`). Đừng gộp 2 luồng khi sửa bug/thêm tính năng.
