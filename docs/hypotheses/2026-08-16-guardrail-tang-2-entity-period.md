# 2026-08-16 — Guardrail Tầng 2 mở rộng: hoán CHỦ THỂ / hoán KỲ (TASK-036)

## Giả thuyết

TASK-027 để lại 2 lỗ đã tự khai (WC2/WC4, xem
`docs/hypotheses/2026-08-12-guardrail-hai-tang.md` §"Bằng chứng BÁC BỎ"):
`unanchored_numbers` (Tầng 2) chỉ ĐẾM SỐ CÂU nguồn mà 1 con số neo được qua
`fact.source`, không kiểm BÊN TRONG câu đó số ấy thuộc CHỦ THỂ nào/KỲ nào. Số
có thật, câu có thật, chỉ gán sai — Composer đổi chủ thể (Nhà nước → MUFG)
hoặc đổi kỳ (6 tháng → quý II) trong khi giữ nguyên số, vẫn neo ĐÚNG 1 câu
(câu của fact BỊ gán nhầm) nên lọt qua.

Giả thuyết: có thể bịt 2 lỗ này BẰNG CODE TẤT ĐỊNH (không LLM) mà KHÔNG tăng
báo động giả đáng kể, bằng cách so khớp 2 loại token cục bộ trong CÂU chứa số
ở body với câu nguồn ĐÃ neo:
- **Token chủ thể**: mã CK/tên viết HOA liền 2-6 ký tự (`_entity_tokens`, vd
  BSR/CTG/MUFG) — không cần danh sách ticker cấu hình sẵn.
- **Token kỳ**: quý/tháng/năm (`_period_tokens`, vd "quý 2/2026", "6 tháng
  đầu năm 2026", "năm 2026"), số La Mã chuẩn hoá về số thường.

Chỉ báo động khi diff (token trong câu body trừ token trong câu nguồn đã neo)
**ĐÚNG 1 phần tử** VÀ phần tử đó khớp token của 1 fact KHÁC trong
content_units — không phải "chỉ cần vắng mặt". Lý do chọn diff==1 (không phải
>=1): câu liệt kê nhiều chủ thể thật trong tiếng Việt tài chính ("VCB, CTG và
BID lần lượt đạt...") luôn để lại diff >=2 token khi câu nguồn của 1 fact chỉ
còn 1 mã (do Brief cắt gọn) — yêu cầu diff==1 tự động loại các câu liệt kê mơ
hồ, tránh đúng rủi ro `rang_buoc_thiet_ke.khong_duoc_danh_doi` nêu trong hợp
đồng TASK-036.

## Bằng chứng XÁC NHẬN

Đo bằng cách chạy trực tiếp `unanchored_numbers` trên code TRƯỚC (HEAD tại
thời điểm nhận task, commit `86d7f44`) và code SAU (thêm `_entity_tokens`/
`_period_tokens`/`_context_mismatch`, xem `agents/production.py`), khôi phục
lại sau khi đo TRƯỚC — cùng phương pháp TASK-027.

**Bộ ca (12 ca, tái dùng đúng bộ WC1-4 của TASK-027 + mở rộng, số THẬT lấy từ
2 bài BSR lọc dầu + CTG/VietinBank đã dùng ở TASK-027, không dựng số mới trừ
ca đối chứng liệt kê C5):**

- 4 ca hoán CHỦ THỂ: WC2 (Nhà nước→MUFG, đã có từ TASK-027) + WC5/WC6/WC7 mới
  (doanh thu BSR→CTG, sở hữu MUFG→BSR, giá CTG→BSR — cả 2 chiều, cả 3 loại
  chỉ số doanh thu/sở hữu/giá).
- 4 ca hoán KỲ: WC4 (6 tháng→quý II, đã có từ TASK-027) + PS2/PS3/PS4 mới
  (LNST quý II→6 tháng, kế hoạch năm→quý II, 6 tháng→kế hoạch năm — cả 2
  hướng năm/quý/6-tháng).
- 5 ca đối chứng ĐÚNG: 4 ca gán đúng chủ thể+kỳ (viết lại nguyên câu nguồn) +
  1 ca QUAN TRỌNG mô phỏng câu liệt kê nhiều mã CK thật ("VCB, CTG và BID lần
  lượt ghi nhận lợi nhuận... trong quý II/2026").

Toàn bộ 12 ca nằm trong `tests/test_pipeline.py`
(`test_unanchored_numbers_*_wc2/wc4/wc5/wc6/wc7`,
`test_unanchored_numbers_period_swap_ps2/ps3/ps4`,
`test_unanchored_numbers_control_*`).

|        | báo động giả (5 ca đối chứng) | bỏ sót hoán chủ thể (4 ca) | bỏ sót hoán kỳ (4 ca) |
|--------|:---:|:---:|:---:|
| TRƯỚC  |  0/5  |  4/4  |  4/4  |
| SAU    |  0/5  |  0/4  |  0/4  |

- Bỏ sót hoán chủ thể 4/4 → 0/4: cả 4 ca (WC2/WC5/WC6/WC7) đều BỊ bắt sau khi
  thêm `_context_mismatch`.
- Bỏ sót hoán kỳ 4/4 → 0/4: cả 4 ca (WC4/PS2/PS3/PS4) đều BỊ bắt.
- Báo động giả 0/5 → 0/5: KHÔNG đổi — đặc biệt ca liệt kê nhiều mã CK (C5,
  rủi ro rõ nhất theo hợp đồng) vẫn sạch nhờ luật diff==1.
- Suite đầy đủ: 558 → 569 test pass (11 test mới, không hồi quy), chạy cả
  `tests/` lẫn `store/`. 1 lỗi tồn tại từ trước ở `store/test_sync_service.py`
  (`test_gate1_delete_removes_topic_from_db_and_sheet`) — xác nhận tái hiện Y
  HỆT trên code TRƯỚC khi tôi sửa gì (baseline `86d7f44`), thuộc phạm vi
  `store/sync_service.py` (forbidden path TASK-036, agent-b TASK-035) — không
  liên quan thay đổi này.

## Bằng chứng BÁC BỎ / giới hạn còn lại

- `_entity_tokens` CHỈ bắt token viết HOA LIỀN (ticker-style, 2-6 ký tự) —
  KHÔNG bắt tên tổ chức viết thường/hỗn hợp kiểu "Ngân hàng Nhà nước"/
  "VietinBank"/"cổ đông chiến lược". Hệ quả: hoán chủ thể theo chiều "ticker
  thật → cụm danh từ chung" (vd gán số MUFG cho câu "cổ đông Nhà nước...")
  KHÔNG bị bắt, vì không có token HOA-liền nào của MUFG bị thiếu trong câu
  body để tạo diff (câu body dùng "Nhà nước", không dùng dạng viết hoa nào
  xung khắc). Đã KHÔNG đưa case này vào bộ đo 4 ca chính thức (chọn 4 ca
  ticker-đối-ticker thay vì ticker-đối-cụm-danh-từ) để tránh báo cáo sai số
  đo — đây là giới hạn còn lại, ghi nhận tường minh thay vì che giấu.
- Luật diff==1 ưu tiên AN TOÀN (không đánh đổi báo động giả) hơn ĐỘ PHỦ: câu
  có 3+ chủ thể/kỳ trong cùng câu mà chỉ 1 trong số đó bị hoán (vd "VCB, CTG,
  BID lần lượt đạt X, Y, Z" nhưng Z thực ra là của mã D không có trong câu)
  sẽ KHÔNG bị bắt nếu diff cục bộ >=2 token — chưa đo ca này (hiếm, cần thêm
  fact thứ 4 ngoài câu liệt kê).
- Token kỳ không xử lý paraphrase ("nửa đầu năm 2026" thay vì "6 tháng đầu
  năm 2026") — nếu Composer diễn giải lại kỳ bằng từ khác thay vì viết số,
  `_period_tokens` không trích được gì (rỗng), diff rỗng → không báo (chấp
  nhận được: thà bỏ sót còn hơn báo động giả trên câu paraphrase ĐÚNG).

## Kết luận sau khi đo

Giả thuyết ĐƯỢC XÁC NHẬN cho phạm vi đã đo: bịt được cả 2 lỗ WC2/WC4 (và biến
thể mở rộng WC5-7/PS2-4) bằng code tất định (`_entity_tokens`/
`_period_tokens`/`_context_mismatch`, TRƯỚC render, guardrail Tầng 2 — vẫn
CẢNH BÁO, KHÔNG nâng ERROR, đúng ràng buộc `rang_buoc_thiet_ke.muc_canh_bao`)
mà KHÔNG tăng báo động giả trên bộ đo hiện có (0/5 cả trước và sau, gồm ca
liệt kê nhiều mã CK — rủi ro cụ thể hợp đồng nêu). Giữ nguyên kiến trúc hai
tầng, không đổi `_anchor_fact_count`→`_anchored_facts` (chỉ đổi kiểu trả về
đếm→danh sách, hành vi CŨ giữ nguyên qua `len(...)`).

Đề xuất KHÔNG nâng Tầng 2 thành ERROR ở task này — số liệu 0/5 báo động giả
là trên bộ đo 12 ca dựng tay/số thật giới hạn, chưa đủ quy mô (khuyến nghị
TASK-027 gốc: cần đo trên corpus rộng hơn, vd rà `document_store.db` như
TASK-027 đã làm cho Tầng 1) để chủ dự án cân nhắc nâng cấp trong 1 task sau
nếu muốn.

## Nguồn dữ liệu đo

- Câu nguồn THẬT: tái dùng `_BSR_EVIDENCE_REAL`/`_CTG_EVIDENCE_REAL` đã có
  trong `tests/test_pipeline.py` (trích từ store thật, xem TASK-027) — mọi
  ca WC2/WC4-7/PS1-4/đối chứng 1-4 đều dùng câu NGUYÊN VĂN cắt từ 2 khối này.
- Ca đối chứng liệt kê nhiều mã CK (C5) là ca DUY NHẤT dựng số tay hoàn toàn
  (không có sẵn evidence thật phù hợp trong 2 khối trên chứa đúng mẫu "lần
  lượt" — ghi nhận tường minh, không nhận vơ là số thật).
- Đo TRƯỚC/SAU chạy bằng script tạm (không commit) gọi trực tiếp
  `unanchored_numbers` với 12 ca trên, đối chiếu kết quả với code tại
  `86d7f44` (TRƯỚC, trước khi thêm `_entity_tokens`/`_period_tokens`/
  `_context_mismatch`) và code sau khi sửa (SAU).
