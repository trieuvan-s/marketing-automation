# assets/ — lớp AI Background (Infographic Hybrid)

**File NÀY (`README.md`) là tài liệu, ở TRONG repo.** Ảnh nền + manifest thật
sự KHÔNG nằm ở đây — mọi dữ liệu SINH RA (dù thật hay test) đều bắt buộc nằm
NGOÀI repo, dưới `storage.data_root` (CÙNG nếp `documents_dir`/`output_dir`
đã dùng cho toàn bộ dữ liệu runtime khác, xem `src/twmkt/config.py:
data_path()`), KHÔNG BAO GIỜ commit vào git.

Nội dung của thư mục CHỈ chứa **ảnh nền minh hoạ** do lớp AI sinh ra
(`src/twmkt/render/ai_background.py`) — KHÔNG chứa chữ/số/layout/bản đồ/icon
(những thứ đó luôn là code tất định, xem `src/twmkt/render/infographic.py`).
Xem nguyên tắc PHÂN TẦNG đầy đủ ở docstring 2 file đó và
`docs/VPS_MIGRATION_BACKLOG.md` mục C6.

## Vị trí thật + cấu trúc

```
<data_root>/assets/                 # data_root = storage.data_root (settings.yaml),
  manifest.json                     # mặc định "../marketing-database/marketing-automation"
  generated/
    <hash>.png
```

`<data_root>` resolve qua `config.data_root()` (ưu tiên biến môi trường
`DATA_ROOT`, sau đó `storage.data_root` trong `config/settings.yaml`).
Thư mục con `assets` (tên) đọc từ
`infographic.ai_background.cache_dir` (`config/settings.yaml`, mặc định
`"assets"`) — đổi tên thư mục cache chỉ sửa Ở ĐÂY, không sửa code.

`get_or_generate_background(..., assets_dir=None)` (mặc định `None`) tự
resolve đường dẫn trên qua `config.data_path()`. Chỉ truyền `assets_dir`
tường minh khi cần CÔ LẬP (test dùng `tmp_path`) — production/review KHÔNG
bao giờ tự tay chỉ định đường dẫn trong repo.

`manifest.json`: 1 entry/ảnh — `topic`, `prompt`, `model`, `size`, `quality`,
`generated_at`, `cost_estimate_usd`, `file` (đường dẫn CON, tương đối trong
`assets/`, vd `"generated/<hash>.png"`).

`<hash> = sha256(topic + prompt + template_version)[:24]` — CÙNG topic + CÙNG
prompt (mặc định, không đổi `build_background_prompt()`) + CÙNG
`template_version` luôn ra CÙNG hash → cache HIT, KHÔNG gọi API lại. Đây là
cơ chế giữ TẤT ĐỊNH của renderer (API sinh ảnh tự nó KHÔNG tất định — 2 lần
gọi cùng prompt ra 2 ảnh khác nhau — nên tất định phải đến từ cache, không
đến từ bản thân API).

## Khi nào sinh ảnh MỚI (tốn tiền)

Cache MISS xảy ra khi:
- Chủ đề (`topic`) chưa từng render qua hybrid.
- Truyền `regenerate=True` (hoặc cờ `--regenerate` ở script gọi) — ép sinh
  lại dù cache đã có (dùng khi ảnh cũ không đạt, cần bản khác).
- Sửa `build_background_prompt()` hoặc đổi `template_version` (thay đổi
  logic sinh prompt → hash khác → coi như "ảnh mới").

Chi phí ước tính: xem `cost_estimate_usd` trong từng entry của
`manifest.json` (ghi tại thời điểm sinh, KHÔNG phải số hoá đơn OpenAI chính
xác — đối chiếu định kỳ với dashboard billing OpenAI, sửa hằng số
`_ESTIMATED_COST_USD` trong `ai_background.py` nếu lệch nhiều). Lần gọi thật
đầu tiên (chủ đề "4 cảng biển đặc biệt...", 2026-07-21): ~16.5s, quality
`low`, size `1024x1536`, ước tính $0.02/ảnh.

## QUY TRÌNH BẮT BUỘC trước khi dùng 1 ảnh mới

1. Sinh ảnh (cache MISS hoặc `--regenerate`).
2. **Xem trực tiếp file PNG trong `<data_root>/assets/generated/`** — xác
   nhận:
   - KHÔNG có chữ/số/watermark/nhãn/biểu đồ nào trong ảnh (kể cả tiếng Anh
     lẫn tiếng Việt) — nếu có, ảnh đó KHÔNG được dùng, xoá + sinh lại
     (`regenerate=True`), không sửa/crop thủ công để "che" chữ lỗi.
   - Tông màu hợp brand (nền tối, xanh dương/xanh ngọc/vàng cam) — không bắt
     buộc đúng tuyệt đối 2 mã màu `config/brand.yaml`, chỉ cần đúng tinh
     thần "tối, tài chính, cao cấp".
3. Nếu đạt — để nguyên trong cache, dùng bình thường (không cần thao tác gì
   thêm, `get_or_generate_background()` tự phục vụ từ cache lần sau).
4. Nếu KHÔNG đạt — xoá đúng 2 dòng liên quan (file PNG + entry trong
   `manifest.json`) hoặc gọi lại với `regenerate=True`, lặp lại bước 1-2.

KHÔNG có bước "duyệt tự động" — review bằng mắt là bắt buộc, vì guardrail
chống bịa số KHÔNG kiểm được nội dung ảnh raster.

## Xoá cache để sinh lại từ đầu

Xoá thủ công trong `<data_root>/assets/` (không có script riêng, thao tác
đơn giản, rủi ro thấp vì đây chỉ là ảnh minh hoạ, không phải dữ liệu
Sheet/Store):

```powershell
Remove-Item <data_root>\assets\generated\<hash>.png
# rồi sửa <data_root>\assets\manifest.json, xoá đúng entry key = <hash>
```

Hoặc xoá SẠCH toàn bộ cache (mọi chủ đề sẽ sinh lại từ đầu ở lần render kế
tiếp, tốn tiền cho MỌI chủ đề, cân nhắc kỹ trước khi làm trên môi trường có
nhiều topic đã cache):

```powershell
Remove-Item <data_root>\assets\generated\*.png
Remove-Item <data_root>\assets\manifest.json
```

## Nợ hiển nhiên KHÔNG được lặp lại

Bản đầu của tính năng này từng lỡ đặt cache TRONG repo
(`E:\marketing-automation\assets\generated\`) VÀ 1 lần render thử-so-sánh ra
`E:\marketing-automation\out\infographic-hybrid\` — cả 2 đã dọn sang
`<data_root>` (2026-07-21). Đường lối chốt kể từ đây: **BẤT KỲ dữ liệu SINH
RA nào (ảnh, SVG render thử, spec test, log...) đều đi qua `data_path()`,
KHÔNG BAO GIỜ ghi thẳng 1 đường dẫn trong repo** — kể cả script one-off/tay,
kể cả dữ liệu "chỉ để xem thử".

## Cấu hình liên quan

- `render.infographic.render_mode` (`config/settings.yaml`) — `"hybrid"`
  (mặc định) hoặc `"pure_html"` (tắt hẳn lớp AI, không cần `OPENAI_API_KEY`,
  không gọi mạng).
- `infographic.ai_background.{model,size,quality,cache_dir}`
  (`config/settings.yaml`) — tham số gửi OpenAI Images API + tên thư mục
  cache dưới `data_root`, đổi ở đây KHÔNG sửa code.
- `storage.data_root` (`config/settings.yaml`, override qua biến môi trường
  `DATA_ROOT`) — GỐC chứa `assets/` thật, xem `src/twmkt/config.py`.
- `OPENAI_API_KEY` — biến môi trường, đọc qua `secrets/.env` (gitignored).
  Thiếu key → tự fallback `pure_html`, ghi cảnh báo rõ, KHÔNG crash. Xem
  `docs/VPS_MIGRATION_BACKLOG.md` mục C6 khi chuyển máy/VPS.
