# 2026-08-12 — Guardrail HAI TẦNG (TASK-027)

## Giả thuyết

Guardrail chống bịa số hiện tại (1 tầng, so khớp `body` với toàn bộ
`evidence+background` bằng substring/canonical) mắc 2 loại lỗi ngược chiều
nhau:

1. **Báo động giả** khi số ĐÚNG nhưng lệch hình thức so với evidence (khoảng
   trắng lạc chèn giữa ký tự số do lỗi trích xuất HTML→markdown; hoặc số chỉ
   xuất hiện ở TIÊU ĐỀ bài gốc, không có trong thân bài truyền vào
   `evidence`).
2. **Bỏ sót** khi số ĐÚNG (có thật trong bài gốc) nhưng bị gán SAI NGỮ CẢNH —
   ví dụ Composer lấy số mục tiêu cả năm gán nhầm cho số 6 tháng. Vì cả hai
   đều là substring hợp lệ của toàn văn, so khớp toàn văn cho qua.

Tách thành 2 tầng — Tầng 1 CHẶN (nới so khớp sang toàn văn tiêu đề+thân bài,
chuẩn hoá khoảng trắng nội bộ cụm số) + Tầng 2 CẢNH BÁO không chặn (neo số về
đúng 1 câu qua `fact.source`) — được kỳ vọng giảm báo động giả MÀ KHÔNG làm
bỏ sót tăng đáng kể, vì Tầng 2 vẫn giữ nguyên khả năng phát hiện lệch ngữ
cảnh của cơ chế neo câu cũ, chỉ hạ mức độ xử phạt từ chặn xuống cảnh báo.

## Bằng chứng XÁC NHẬN

- **Ca thật báo động giả (đã sửa)**: 2 topic_key thật trong store có
  `compliance_issues` ERROR mà biên tập viên xác nhận tay là báo động giả:
  - `4668310b0e7cc1ce` (CTG/VietinBank): evidence gốc (vietnambiz.vn) bị chèn
    khoảng trắng lạc giữa ký tự số ("7 , 7 7 tỷ", "41 ,7 triệu"). Note ở
    version 2 của document_store: *"Đã đối chiếu lại với bài báo nguồn: hai
    số liệu … đều có thật, không phải số bịa. Cảnh báo tự động trước đó là
    báo động giả."*
  - `a311a2fc617468c2` (BSR/lọc dầu): video/infographic tái dùng nguyên văn
    tiêu đề bài gốc ("hơn 100.000 tỷ") làm hero/narration, nhưng tiêu đề
    không nằm trong `evidence` truyền vào guardrail (chỉ thân bài, có số
    chính xác "100.922 tỷ đồng") → báo động giả.
- Đo trực tiếp (checkout code CŨ tại HEAD~1, xem bảng 4 ô dưới): cả 2 ca trên
  tái hiện đúng thành báo động giả trên code CŨ, và biến mất trên code MỚI
  (Tầng 1: `_SPACED_MAGNITUDE_RE` + `_normalize_number` gộp khoảng trắng;
  tham số `title=` nối tiêu đề vào `source_text`).
- 4 ca sai-ngữ-cảnh dựng tay (WC1–WC4, số THẬT lấy từ 2 bài trên, tự viết câu
  gán sai) đều lọt qua TẦNG 1 (toàn văn) ở cả code CŨ lẫn MỚI — đúng dự đoán,
  vì Tầng 1 chỉ kiểm tồn tại, không kiểm ngữ cảnh.
- Tầng 2 (`unanchored_numbers`) bắt được 2/4 ca (WC1, WC3 — số hoàn toàn
  KHÔNG được trích thành fact nào) mà code CŨ (không có khái niệm Tầng 2) bỏ
  sót 100%.

## Bằng chứng BÁC BỎ / giới hạn đã biết

- Tầng 2 **KHÔNG** bắt được WC2 (hoán đổi THỰC THỂ — số đúng câu, sai chủ thể:
  gán sở hữu Nhà nước cho MUFG) và WC4 (hoán đổi KỲ — số đúng câu, sai mốc
  thời gian: gán tăng trưởng 6 tháng cho quý II). Lý do: `unanchored_numbers`
  chỉ đếm SỐ CÂU mà 1 giá trị số neo được, không so khớp nhãn/thực thể/kỳ của
  câu đó với ngữ cảnh Composer đang viết — số vẫn neo ĐÚNG 1 câu (câu của
  fact khác), chỉ sai ở việc AI gán nhầm nó cho fact nào.
- Đây LÀ giới hạn thiết kế đã biết trước khi đo (ghi trong test
  `..._known_gap_same_sentence_entity_swap_wc2` /
  `..._known_gap_same_sentence_period_swap_wc4`), không phải phát hiện bất
  ngờ sau đo.

## Kết luận sau khi đo

Bảng 4 ô (4 ca báo động giả FP1–FP4 dựng từ 2 bài thật + 4 ca sai ngữ cảnh
WC1–WC4 dựng tay theo đúng yêu cầu hợp đồng; đo bằng cách chạy trực tiếp
`unsupported_numbers`/`unanchored_numbers`/`apply_guardrails` trên code tại
HEAD~1 (TRƯỚC) và code hiện tại (SAU), khôi phục lại sau khi đo TRƯỚC):

|        | báo động giả | bỏ sót (sai ngữ cảnh lọt) |
|--------|:---:|:---:|
| TRƯỚC  |  2/4  |  4/4  |
| SAU    |  0/4  |  2/4  |

Cả 2 chiều đều CẢI THIỆN — báo động giả 2→0, bỏ sót 4→2 (KHÔNG tăng, nên
không rơi vào điều kiện dừng "bỏ sót SAU tăng đáng kể"). Giả thuyết được
XÁC NHẬN cho lớp lỗi mà Tầng 2 có thể phát hiện (số không neo được câu nào),
và BÁC BỎ MỘT PHẦN cho lớp lỗi hoán đổi thực thể/kỳ trong cùng 1 câu (WC2,
WC4) — Tầng 2 ở thiết kế hiện tại không phát hiện được lớp này, cần thiết kế
so khớp thực thể/nhãn tinh hơn (fact.label vs ngữ cảnh câu Composer đang
viết) nếu muốn thu hẹp tiếp, việc đó KHÔNG nằm trong phạm vi TASK-027 (yêu
cầu giữ nguyên `fact.source`, không đổi Tầng 2 thành chặn, không gộp 2 tầng).

## Nguồn dữ liệu đo

- Ca thật: `D:/trung-temp/marketing-database/marketing-automation/document_store.db`,
  bảng `documents`, `topic_key` = `4668310b0e7cc1ce` / `a311a2fc617468c2`
  (layer `content_output`, field `notes`/`status`).
- Ca dựng tay: `tests/test_pipeline.py`, các hàm `test_unanchored_numbers_*_wc1..wc4`.
- Rà soát rộng hơn trong `document_store.db` tìm thấy tổng cộng 8 topic_key
  từng có `compliance_issues` chứa "Số liệu không thấy trong evidence/
  background" (`a4c41a4949fdcb09`, `2a98decc5af5b9bc`, `220fc58d2877f8c4`,
  `4668310b0e7cc1ce`, `a311a2fc617468c2`, `3fb862f3799c866c`,
  `8fb23d81ea76e552`). Chỉ 2 ca (CTG, BSR) được xác nhận LÀ báo động giả
  (có ghi chú biên tập viên xác nhận tay); các ca còn lại hoặc đã tự khỏi ở
  lượt sinh lại sau (không phải do sửa guardrail) hoặc là ca `SOURCE_BROKEN`
  (content_units[] rỗng do Brief lỗi hạ tầng — KHÔNG liên quan thiết kế Tầng
  1/Tầng 2, ngoài phạm vi giả thuyết này) — chưa được xác minh từng ca, không
  đưa vào bảng đo để tránh lẫn 2 loại lỗi khác bản chất.
