# TEST_RESULT.md

> Ghi đè sau mỗi lần chạy `python tests/test_pipeline.py` liên quan tới 1 task
> đang làm — KHÔNG tích luỹ log. Đây là "test xanh" (điều kiện CẦN) — vẫn phải
> chấm trên output/dữ liệu thật riêng cho việc có rủi ro chất lượng thật (xem
> `CLAUDE.md` — "Chấm trên OUTPUT THẬT").

## Lần chạy gần nhất
- **Thời điểm:** 2026-07-28 (agent-B)
- **Lệnh:** `python -m pytest` (toàn repo: tests/ + store/ + api/ + src/)

## Kết quả
- **Suite:** PASS
- **Số liệu:** 660 passed, 0 failed
- **Ghi chú:** Cần `pip install -r requirements.txt` + `-r api/requirements-webhook.txt`
  (thiếu `pillow` -> 4 test render đỏ; thiếu `fastapi` -> không collect được
  `api/test_main.py`). Chạy từ THƯ MỤC GỐC repo, KHÔNG phải `src/`.

## Chấm trên OUTPUT THẬT (e2e 2026-07-28) — điều kiện ĐỦ

Suite xanh KHÔNG bắt được 6 bug dưới đây; tất cả lộ ra khi chạy thật, và tất cả
đều thuộc loại ÂM THẦM (không exception, không log lỗi, chỉ kết quả sai).

| Bug | Nguồn gốc | Vì sao test đơn vị không bắt |
|---|---|---|
| Mất lượt duyệt: render-từ-store ghi đè APPROVE người vừa bấm trong lúc `run()` gọi LLM | có sẵn | Cần 2 tác nhân đồng thời (người + worker) trên cùng 1 tab |
| AssetPath bị xoá vài giây sau khi ghi (ghi Sheet rồi render lại từ store) | có sẵn | Cần đúng trình tự job -> sync của worker thật |
| Prompt mời Composer chọn `16:9` mà renderer chỉ dựng 9:16/4:5/1:1 | có sẵn | Lệch giữa 2 file không ai đối chiếu |
| Output Type: tuyến router TỰ TẮT vẫn ghi 1 dòng SKIPPED thừa | agent-B, cùng phiên | Chỉ lộ khi router thật từ chối 1 tuyến |
| Link Drive không gán vì so `ratio == _PRIMARY_RATIO` (hằng "4:5") | agent-B, cùng phiên | Chỉ lộ khi Composer chọn tỷ lệ KHÁC 4:5 |
| Chặn idempotent đọc `asset_path` từ Sheet thay vì store | có sẵn | Chỉ lộ khi store và Sheet lệch nhau 1 nhịp |

**MẪU CHUNG — đáng nhớ:** mọi chỗ CÒN ĐỌC SHEET ĐỂ RA QUYẾT ĐỊNH đều hỏng.
Store là nguồn sự thật, Sheet là BẢN CHIẾU. Đã chuyển hết sang đọc store.

### Luồng đã chạy trọn vẹn trên dữ liệu thật
```
crawl (lọc ngày đăng: loại 2 bài cũ, 0 bài không rõ ngày)
  -> Gate 1 APPROVE (duyệt liền tay nhiều chủ đề -> nhận ĐỦ, không mất lượt nào)
  -> hàng đợi produce -> Composer -> guardrail (chặn bịa số thật)
  -> Gate 2 APPROVE -> hàng đợi render_assets
  -> 1 ảnh 9:16 (KHÔNG phải 3) -> Drive -> link công khai anyone/reader
  -> Gate 3 PENDING (chờ người)
```
