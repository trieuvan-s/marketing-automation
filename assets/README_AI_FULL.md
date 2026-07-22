# assets_ai_full/ — mode "ai_full" (mặc định, 2026-07-21)

**File NÀY ở trong repo (tài liệu). Cache ảnh THẬT nằm NGOÀI repo**, dưới
`storage.data_root` — CÙNG quy tắc đã chốt cho mode "hybrid" cũ (xem
`assets/README.md` — mục "Nợ hiển nhiên KHÔNG được lặp lại": KHÔNG bao giờ
ghi dữ liệu sinh ra vào trong repo, kể cả tay/one-off).

## Vị trí thật

```
<data_root>/assets_ai_full/     # tên đọc từ infographic.ai_full.cache_dir
  manifest.json
  generated/
    <hash>.png                  # ảnh THÔ, CHƯA đóng dấu brand
```

`<hash> = sha256(spec_json_sorted + theme + ratio + prompt_version)[:24]` —
xem `src/twmkt/render/ai_full.py::_cache_key()`. Ảnh đã ĐÓNG DẤU brand
(`brand_stamp.py`) KHÔNG cache riêng — stamp là hàm thuần, $0, chạy lại bất
kỳ lúc nào từ ảnh thô đã cache, không cần gọi API lại nếu chỉ đổi
logo/font/vị trí brand.

## Kiến trúc PHÂN TẦNG ngược Hybrid

Hybrid cũ: code (SVG) vẽ TRƯỚC, AI (nền) chèn DƯỚI — text/số luôn ở lớp
tất định, AI chỉ là khí quyển mờ phía sau.

`ai_full`: AI vẽ TOÀN BỘ ảnh (chữ/số/layout/minh hoạ) TRƯỚC, code (Pillow,
`brand_stamp.py`) đóng dấu logo/nguồn/disclaimer LÊN TRÊN sau cùng — vì AI
không bao giờ vẽ ĐÚNG logo được. Đây là đánh đổi CÓ CHỦ ĐÍCH (xem
`ai_full.py` docstring): text/số nằm trong ảnh raster, guardrail-2 chống-bịa
KHÔNG kiểm được sau khi render (khác Hybrid) — bù lại bằng Gate 2 (duyệt
người trước khi render) + Gate 3 (duyệt asset sau khi render).

## Model / chi phí

- Model: `gpt-image-2` (config `infographic.ai_full.model`).
- Quality: `medium` mặc định (config `infographic.ai_full.quality`).
- **CHƯA có bảng giá `gpt-image-2` xác nhận** tại thời điểm viết (2026-07-21)
  — response API trả `usage` (input/output/total_tokens) THẬT, ghi vào
  `manifest.json` mỗi entry, nhưng KHÔNG tự quy đổi ra USD (tránh bịa số).
  Đối chiếu dashboard billing OpenAI rồi gọi
  `ai_full.record_actual_cost(cache_key=..., cost_usd=..., assets_dir=...)`
  để ghi số thật vào manifest.
- Thời gian đo thật (quality medium, 2026-07-21): ~55-95s/ảnh tuỳ tỷ lệ.

## 3 tỷ lệ, KHÔNG crop

`RATIO_SIZES` (`ai_full.py`) — mỗi tỷ lệ gọi API RIÊNG, size CHÍNH XÁC (API
chấp nhận size tuỳ ý miễn chia hết cho 16, xác nhận thật):

| Tỷ lệ | Size | Ghi chú |
|---|---|---|
| 1:1 | 1024×1024 | |
| 4:5 | 1024×1280 | chính xác 4:5, KHÔNG phải 1024×1536 (2:3) xấp xỉ |
| 9:16 | 864×1536 | chính xác 9/16 = 0.5625 |

KHÔNG BAO GIỜ sinh 1 ảnh rồi crop sang tỷ lệ khác — đây chính là nguyên nhân
bug "crop 4:5 mất logo/nguồn" ở bài test trước (xem lịch sử hội thoại) —
mỗi tỷ lệ có vùng an toàn (`_TOP_SAFE_PCT`/`_BOTTOM_SAFE_PCT`) riêng, đóng
dấu riêng.

## QUY TRÌNH BẮT BUỘC trước khi dùng 1 ảnh mới

Giống hệt `assets/README.md` (Hybrid cũ) — xem trực tiếp PNG trong
`<data_root>/assets_ai_full/generated/`, xác nhận KHÔNG có chữ sai/logo giả/
bản đồ VN trước khi dùng thật, xoá + `regenerate=True` nếu không đạt.

**Thêm 1 mục kiểm cho ai_full (KHÔNG có ở Hybrid, vì Hybrid AI không vẽ
chữ)**: đối chiếu TỪNG SỐ trong ảnh với spec JSON gốc — dù đo thật 2026-07-21
cho thấy độ chính xác số RẤT cao, đây vẫn là ảnh AI vẽ chữ, KHÔNG có gì tự
động kiểm sau khi sinh (khác Hybrid).

## Nợ đã biết (2026-07-21, phát hiện qua ảnh test thật, ĐÃ SỬA)

- **Trùng dòng "Nguồn"**: bản `_PROMPT_VERSION="v1"` không cấm AI tự vẽ field
  `source` thành chữ trên ảnh → trùng với dòng "Nguồn:" do `brand_stamp.py`
  đóng dấu sau. Sửa: `_PROMPT_VERSION="v2"`, prompt cấm rõ AI vẽ "Nguồn:"/
  source text. Cache v1 vẫn còn trong `generated/` (không tự xoá) nhưng
  KHÔNG bao giờ được đọc lại (key đổi theo prompt_version) — có thể dọn tay
  nếu cần giải phóng dung lượng.
- **Nguồn dài tràn mép ảnh**: `brand_stamp.py` trước đây vẽ `draw.text()`
  thẳng 1 dòng, không đo/bọc theo chiều rộng — nguồn dài (vd trích dẫn HoSE)
  tràn hẳn ra ngoài. Sửa: thêm `_wrap_to_width()`, đo bằng `draw.textlength`
  thật (không ước lượng ký tự/dòng).

## Nợ P0 đã sửa (2026-07-22, phát hiện qua ảnh thật CẢ 4-6 tỷ lệ — bản
"v2fix" trước đó của mục trên KHÔNG bắt được vì chỉ test chuỗi ngắn)

- **Chồng đè disclaimer/nguồn**: `line_h` cũ là ƯỚC LƯỢNG cố định
  (`bottom_h * 0.38`), không khớp chiều cao chữ THẬT ở font size đã chọn —
  khi wrap nhiều dòng (nguồn dài, tỷ lệ hẹp 9:16), khối "Nguồn" bắt đầu vẽ
  ĐÈ lên khối disclaimer chưa vẽ xong. Sửa: đo `draw.textbbox()` THẬT, xếp
  khối TỪ DƯỚI LÊN (dòng trên = dòng dưới - chiều cao thật - khoảng cách),
  không hardcode Y cho bất kỳ dòng nào.
- **Cụt chữ**: hệ quả trực tiếp của lỗi chồng đè trên (2 khối đè lên nhau ở
  cùng khu vực nhìn như chữ bị cắt) — cùng 1 lần sửa giải quyết cả 2.
- **Vùng an toàn không đủ, chữ đè lên nội dung AI**: co font tới
  `_MIN_READABLE_FONT_SIZE=16px` không phải lúc nào cũng đủ (nguồn rất dài +
  tỷ lệ hẹp). Sửa: thêm SCRIM (dải nền mờ dần, kỹ thuật chuẩn cho phụ đề) vẽ
  LUÔN phía sau khối disclaimer+nguồn, đảm bảo đọc được BẤT KỂ AI vẽ gì bên
  dưới — không cần đoán/phân tích pixel ảnh nền.
  ⚠️ **CHƯA hoàn hảo 100%, ghi nhận trung thực**: ở chủ đề nội dung DÀY NHẤT
  đã test (cảng biển, 8 thẻ số liệu + 3 điểm nhấn + 7 địa danh), tỷ lệ 4:5,
  scrim phải phủ cao tới mức che mất ĐUÔI câu điểm nhấn thứ 3 của AI (toàn bộ
  số liệu/thẻ chính vẫn nguyên vẹn, không mất). Đây là đánh đổi CÓ CHỦ Ý
  (scrim che 1 phần văn bản phụ CÒN HƠN chữ đóng dấu chồng đè không đọc
  được) — nếu cần triệt để hơn, phải "nới prompt" (tăng `_BOTTOM_SAFE_PCT`,
  bump `_PROMPT_VERSION`, tốn thêm 1 lượt gọi API thật cho MỌI ảnh đã cache)
  — CHƯA làm vì ngoài phạm vi "chỉ sửa brand_stamp.py" của nhiệm vụ này.

## Quyết định ĐÃ CHỐT (2026-07-22, Lead)

- AI vẽ logo/livery THẬT của DOANH NGHIỆP KHÁC (không phải FVA) khi họ là
  CHỦ THỂ bài viết (vd logo Vietnam Airlines trên máy bay) — **CHẤP NHẬN
  ĐƯỢC**. Ranh giới: (1) KHÔNG để AI vẽ SAI thành hãng khác/méo phản cảm —
  phát hiện lúc kiểm ảnh thì coi KHÔNG ĐẠT, xoá + regenerate; (2) logo FVA
  Capital LUÔN LUÔN đóng dấu tất định, KHÔNG BAO GIỜ để AI vẽ (không đổi).
  Xem `docs/VPS_MIGRATION_BACKLOG.md` mục C7.

## Nợ CHƯA sửa (cần Lead quyết, ghi nhận trung thực)

- Bản đồ Việt Nam: KHÔNG có asset chuẩn nào trong repo tại 2026-07-21 (đã
  tìm kỹ, xem báo cáo) — prompt hiện cấm AI vẽ map TUYỆT ĐỐI (không có nhánh
  "chừa chỗ dán bản đồ thật"). Bổ sung khi Lead cấp asset.
- Trường hợp nội dung SIÊU dày (xem cảnh báo scrim ở trên) — nếu Lead muốn
  triệt để 0% che nội dung AI, cần quyết "nới prompt" (tốn thêm chi phí API
  regenerate) thay vì chỉ dựa vào scrim.

## Cấu hình liên quan

- `render.infographic.render_mode` — `"ai_full"` (mặc định) | `"hybrid"`.
  `"pure_html"` ĐÃ XOÁ KHỎI CODE (không còn là giá trị hợp lệ).
- `infographic.ai_full.{model,quality,cache_dir}` (`config/settings.yaml`).
- `OPENAI_API_KEY` — DÙNG CHUNG với mode "hybrid" (không phải secret mới,
  xem `docs/VPS_MIGRATION_BACKLOG.md` mục C6) — nhưng giờ là secret BẮT BUỘC
  để render_mode mặc định hoạt động (Hybrid trước đây coi thiếu key là
  fallback an toàn về pure_html; pure_html đã xoá nên thiếu key ở ai_full
  = KHÔNG render được ảnh nào, chỉ NEEDS_HUMAN).
