<!--
NGUỒN: content-rules/SEMANTIC_VALIDATOR_v1.1.md (thư mục sibling NGOÀI repo,
KHÔNG theo git). COPY VÀO REPO ngày 2026-07-22, nội dung GIỮ NGUYÊN.

⚠️ ĐỌC THAM KHẢO — CHƯA DÙNG ĐỢT NÀY (theo chỉ định rõ trong nhiệm vụ BƯỚC 0-4,
2026-07-22). Đợt sau mới đối chiếu claim với facts[], KHÔNG sửa văn phong;
định nghĩa "nội dung rủi ro" sẽ chốt riêng lúc đó. KHÔNG wire vào code.
-->

# SEMANTIC VALIDATOR v1.1

Trạng thái: Draft for Lead Review  
Ngày: 22/07/2026

## 1. Mục tiêu

Semantic Validator v1.1 kiểm tra quan hệ giữa claim và bằng chứng trước khi nội dung được xuất bản hoặc chuyển sang Production Factory.

Validator phải phát hiện:

- Dữ kiện sai hoặc không có trong nguồn.
- Suy luận có cơ sở nhưng được nói quá chắc.
- Quan hệ nhân quả chưa được chứng minh.
- So sánh thiếu dữ liệu nền.
- Khái quát hóa từ một trường hợp riêng.
- Kiến thức ngoài nguồn chưa được phép hoặc chưa xác minh.
- Chi tiết suy đoán không cần thiết cho luận điểm.
- Phát ngôn lộ rules hoặc quá trình tự kiểm soát.

Validator không được:

- Viết lại toàn bộ sản phẩm chỉ vì một lỗi cục bộ.
- Ép nội dung có số section, scene, card hoặc luận điểm cố định.
- Reject vì thiếu field tùy chọn, bài ngắn hoặc mật độ thấp.
- Dùng tiêu chí thẩm mỹ để thay đổi giọng văn của Composer.
- Tự tạo bằng chứng hoặc kết luận thay thế khi nguồn không đủ.

## 2. Phạm vi

Áp dụng cho:

- Article và Long-form Article.
- Video Script.
- Infographic Script.

V1.1 ưu tiên nội dung tài chính, doanh nghiệp, thị trường, kinh tế và chính sách. Kiến trúc không phụ thuộc một schema trình bày cụ thể.

## 3. Đầu vào

```json
{
  "content_type": "article | video | infographic",
  "content": {},
  "sources": [
    {
      "source_id": "source_01",
      "title": "Tên nguồn",
      "text": "Nội dung nguồn đã chuẩn hóa",
      "published_at": "2026-07-21",
      "source_type": "official | filing | news | research | other"
    }
  ],
  "brief": {
    "task": "Mục tiêu nội dung",
    "allow_external_knowledge": false,
    "required_claims": [],
    "delivery_profile": "optional"
  }
}
```

### Yêu cầu đầu vào

- Nguồn phải có `source_id` ổn định.
- Composer không tự tạo source ID.
- Nếu `allow_external_knowledge=false`, mọi factual claim phải truy nguyên về nguồn đầu vào hoặc được đánh dấu là suy luận phát sinh từ các nguồn đó.
- Nếu không có source text, Validator chỉ kiểm tra nhất quán nội bộ và luật phát ngôn; không được tuyên bố claim đã được xác minh.

## 4. Đầu ra

```json
{
  "validator_version": "1.1",
  "status": "ACCEPT | ACCEPT_WITH_WARNINGS | TARGETED_REPAIR | VERIFY_REQUIRED | REJECT",
  "summary": {
    "claims_checked": 0,
    "blocking": 0,
    "repairable": 0,
    "warnings": 0
  },
  "findings": [],
  "repair_plan": [],
  "editorial_signals": []
}
```

Mỗi finding:

```json
{
  "finding_id": "finding_001",
  "severity": "blocking | repairable | warning | info",
  "error_code": "OVERSTATED_INFERENCE",
  "field_path": "content.body.paragraph_6",
  "claim": "Nội dung claim cần kiểm tra",
  "support_status": "EXPLICIT | DERIVED | EXTERNAL | UNSUPPORTED | CONFLICTING",
  "evidence": [
    {
      "source_id": "source_01",
      "evidence_text": "Đoạn bằng chứng ngắn",
      "relation": "supports | partially_supports | contradicts"
    }
  ],
  "missing_evidence": "Bằng chứng còn thiếu, nếu có",
  "reason": "Giải thích ngắn gọn",
  "action": "KEEP | QUALIFY | REMOVE | VERIFY",
  "suggested_revision": "Chỉ có khi có thể sửa trực tiếp từ nguồn"
}
```

## 5. Mô hình Claim–Evidence Alignment

### 5.1. Đơn vị kiểm tra

Claim là một mệnh đề có thể đúng hoặc sai, gồm:

- Con số, đơn vị, thời điểm và phạm vi.
- Sự kiện hoặc trạng thái của thực thể.
- Quan hệ so sánh.
- Quan hệ nguyên nhân–kết quả.
- Nhận định cấu trúc hoặc cơ chế.
- Dự báo, kịch bản hoặc hệ quả tương lai.
- Trích dẫn hoặc phát ngôn được gán cho một chủ thể.

Không cần tách thành claim riêng đối với câu chuyển đoạn, CTA, disclaimer hoặc mô tả thuần phong cách không mang nội dung kiểm chứng.

### 5.2. Trạng thái hỗ trợ

| Trạng thái | Định nghĩa | Hành động mặc định |
|---|---|---|
| `EXPLICIT` | Nguồn xác nhận trực tiếp claim. | `KEEP` |
| `DERIVED` | Claim được suy ra từ dữ kiện nguồn qua một bước lập luận hợp lý. | `KEEP` hoặc `QUALIFY` |
| `EXTERNAL` | Claim dựa vào kiến thức ngoài nguồn. | `VERIFY` hoặc `REMOVE` |
| `UNSUPPORTED` | Không tìm thấy bằng chứng đủ. | `REMOVE`, `QUALIFY` hoặc `VERIFY` |
| `CONFLICTING` | Claim mâu thuẫn với nguồn hoặc giữa các nguồn. | `VERIFY`; `REJECT` nếu là claim trung tâm |

### 5.3. Tiêu chuẩn cho `DERIVED`

Một claim chỉ được xếp `DERIVED` khi:

1. Các tiền đề đều có trong nguồn.
2. Chuỗi suy luận ngắn và có thể giải thích.
3. Không cần giả định ẩn mang tính quyết định.
4. Mức độ chắc chắn trong câu phù hợp với sức mạnh bằng chứng.
5. Không biến tương quan thành nhân quả.

Validator ghi lại logic derivation trong kết quả nội bộ, nhưng không yêu cầu Composer xuất nhãn “đây là suy luận”.

## 6. Error Code Registry

### 6.1. Lỗi dữ kiện

| Error code | Điều kiện | Mức mặc định |
|---|---|---|
| `FACT_NOT_IN_SOURCE` | Factual claim không có trong nguồn khi external knowledge không được phép. | `repairable` hoặc `blocking` |
| `NUMERIC_MISMATCH` | Sai giá trị, đơn vị, thời điểm hoặc phạm vi. | `repairable` |
| `ENTITY_MISMATCH` | Nhầm doanh nghiệp, cá nhân, cơ quan hoặc mã chứng khoán. | `blocking` nếu trọng yếu |
| `QUOTE_ATTRIBUTION_ERROR` | Quote sai hoặc gán sai chủ thể. | `blocking` |
| `SOURCE_CONFLICT` | Các nguồn đáng tin đưa thông tin xung đột. | `blocking` hoặc `VERIFY` |

### 6.2. Lỗi suy luận

| Error code | Điều kiện | Mức mặc định |
|---|---|---|
| `OVERSTATED_INFERENCE` | Có cơ sở một phần nhưng câu khẳng định chắc hơn bằng chứng. | `repairable` |
| `CAUSAL_LEAP` | Khẳng định nguyên nhân mà nguồn chỉ thể hiện đồng thời hoặc tương quan. | `repairable` |
| `TEMPORAL_COMPARISON_WITHOUT_BASELINE` | Nói “đã đổi”, “cải thiện”, “xấu đi” nhưng thiếu dữ liệu kỳ gốc tương thích. | `repairable` |
| `GENERALIZATION_FROM_SINGLE_CASE` | Suy từ một thực thể hoặc trường hợp ra ngành/hệ thống. | `repairable` |
| `UNSUPPORTED_FORECAST` | Dự báo không có tiền đề hoặc điều kiện đủ. | `repairable` |
| `FALSE_DICHOTOMY` | Chỉ đưa hai khả năng như thể đó là toàn bộ tập khả năng. | `warning` hoặc `repairable` |
| `UNNECESSARY_SPECULATION` | Claim thiếu nguồn và không cần cho luận điểm trung tâm. | `repairable`; ưu tiên `REMOVE` |

### 6.3. Lỗi phát ngôn

| Error code | Điều kiện | Mức mặc định |
|---|---|---|
| `LEGAL_OVERCLAIM` | Quy kết sai phạm, động cơ hoặc trách nhiệm thiếu căn cứ. | `blocking` |
| `INVESTMENT_OVERCLAIM` | Hứa hẹn lợi nhuận hoặc thúc ép giao dịch không phù hợp. | `blocking` |
| `UNCERTAINTY_AS_FACT` | Biến khả năng, kế hoạch hoặc nghi vấn thành sự thật. | `blocking` hoặc `repairable` |
| `META_COMPLIANCE_LEAK` | Nhắc rubric, rules hoặc tự phân loại Fact/Inference để thanh minh với người đọc. | `repairable` |

### 6.4. Editorial signal, không phải semantic error

| Signal | Xử lý |
|---|---|
| `FORM_IMPRINT` | Chuyển Editor; không reject. |
| `REPEATED_THESIS` | Gợi ý rút gọn; không semantic repair mặc định. |
| `METAPHOR_DENSITY` | Cảnh báo khi ẩn dụ làm mờ mức độ claim. |
| `TEMPLATE_ENDING` | Publisher quyết định giữ hoặc bỏ. |
| `OPTIONAL_FIELD_MISSING` | `info`; output vẫn hợp lệ. |

## 7. Ma trận quyết định

### KEEP

Áp dụng khi claim được nguồn hỗ trợ đủ, đúng phạm vi và đúng mức độ chắc chắn.

### QUALIFY

Áp dụng khi:

- Claim có cơ sở nhưng đang nói quá chắc.
- Thiếu một phần bằng chứng nhưng vẫn có giá trị phân tích.
- Có thể sửa bằng cách thu hẹp phạm vi, thêm điều kiện hoặc nêu giới hạn cụ thể.

Không dùng các câu meta như “đây là suy luận”. Việc qualify phải được hòa vào chính câu phân tích.

### REMOVE

Áp dụng khi:

- Claim thiếu nguồn.
- Không cần thiết cho luận điểm trung tâm.
- Việc làm mềm vẫn giữ lại một suy đoán không có giá trị.
- Claim chỉ làm bài dài hoặc tăng tính hùng biện.

### VERIFY

Áp dụng khi:

- Claim quan trọng nhưng nguồn đầu vào chưa đủ.
- External knowledge được phép nhưng chưa có nguồn xác minh.
- Có xung đột giữa các nguồn.
- Việc loại claim sẽ làm mất một phần trọng yếu của sản phẩm.

## 8. Severity và outcome

### Blocking

Chỉ dùng khi:

- Claim trung tâm sai hoặc mâu thuẫn nguồn.
- Có lỗi thực thể/số liệu làm đổi bản chất.
- Có phát ngôn pháp lý hoặc đầu tư nguy hiểm.
- Không còn output sử dụng được sau khi bỏ phần sai.

### Repairable

Lỗi nằm ở một câu, heading, scene, item hoặc block và có thể sửa từ nguồn hiện có.

### Warning

Output đúng nhưng có điểm cần Editor xem xét. Warning không kích hoạt LLM semantic repair mặc định.

### Outcome logic

```text
Nếu có blocking không thể sửa từ nguồn          -> REJECT
Nếu cần thêm nguồn cho claim trung tâm          -> VERIFY_REQUIRED
Nếu có repairable và có repair plan rõ          -> TARGETED_REPAIR
Nếu chỉ có warning/info                         -> ACCEPT_WITH_WARNINGS
Nếu không có finding đáng kể                    -> ACCEPT
```

## 9. Quy trình validation

### Bước 1 — Contract gate

Kiểm tra parse, field lõi và cấu trúc tối thiểu. Thiếu field tùy chọn không phải lỗi.

### Bước 2 — Claim extraction

Tách claim và giữ `field_path` về đúng vị trí trong Article, scene hoặc infographic block.

### Bước 3 — Evidence retrieval

Tìm bằng chứng trong nguồn đầu vào. Ưu tiên nguồn chính thức, báo cáo doanh nghiệp và văn bản gốc khi có.

### Bước 4 — Alignment

Gán `EXPLICIT`, `DERIVED`, `EXTERNAL`, `UNSUPPORTED` hoặc `CONFLICTING`.

### Bước 5 — Semantic checks

Chạy error registry cho số liệu, thực thể, nhân quả, baseline, generalization, forecast, phát ngôn và meta-compliance.

### Bước 6 — Necessity test

Hỏi nội bộ:

> Nếu bỏ claim này, luận điểm trung tâm có mất giá trị đáng kể không?

- Không mất giá trị: ưu tiên `REMOVE`.
- Có mất giá trị và nguồn hỗ trợ một phần: `QUALIFY`.
- Có mất giá trị nhưng nguồn không đủ: `VERIFY`.

### Bước 7 — Decision

Tạo finding, repair plan và outcome. Không sửa trong lượt shadow mode.

## 10. Targeted Repair Policy

Chỉ bật sau khi shadow mode đạt tiêu chí nghiệm thu.

Nguyên tắc:

1. Sửa đúng `field_path` được báo lỗi.
2. Giữ nguyên các phần đã đạt.
3. Không thêm dữ kiện mới ngoài evidence.
4. Ưu tiên `REMOVE` cho suy đoán phụ.
5. Chỉ `QUALIFY` khi claim còn giá trị và có bằng chứng một phần.
6. Không dùng lời phân bua về Fact/Inference trong câu sửa.
7. Mặc định tối đa một lượt LLM semantic repair.
8. Sau repair, chỉ revalidate claim đã sửa và các claim phụ thuộc trực tiếp.
9. Không full regeneration vì lỗi cục bộ.

Mẫu repair plan:

```json
{
  "finding_id": "finding_001",
  "field_path": "content.body.paragraph_6",
  "action": "QUALIFY",
  "constraints": [
    "Chỉ dùng source_01",
    "Không thêm dữ kiện",
    "Không dùng nhãn dữ kiện/suy luận",
    "Giữ giọng văn hiện tại"
  ]
}
```

## 11. Quy tắc theo loại nội dung

### 11.1. Article

- Kiểm tra title, subtitle và luận điểm trung tâm trước.
- Kiểm tra mọi số liệu, thực thể, quote và quan hệ nhân quả.
- Heading có claim phải được kiểm tra như nội dung.
- Không reject vì ít heading, không có watchlist hoặc bài ngắn.
- Form imprint, lặp ý và CTA thuộc Editor/Publisher.

### 11.2. Video Script

- Kiểm tra narration và on-screen text phải nhất quán.
- Một số liệu xuất hiện ở nhiều scene phải có cùng giá trị và đơn vị.
- Visual direction không được mô tả một sự kiện có thật nếu nguồn không xác nhận.
- Lỗi một scene chỉ sửa scene đó.
- Thiếu visual, transition hoặc timecode không phải semantic error.

### 11.3. Infographic Script

- Kiểm tra cặp label–value–unit–timeframe.
- Comparison phải có baseline tương thích.
- Quote phải có nguồn và đúng chủ thể.
- Timeline phải có mốc thời gian thật.
- Block không đủ bằng chứng được bỏ; không tạo dữ liệu để giữ layout.
- Nội dung ít kích hoạt compact layout ở Renderer, không kích hoạt reject.

## 12. Shadow Mode

Trong giai đoạn đầu, Validator chỉ:

- Trả findings.
- Đề xuất KEEP/QUALIFY/REMOVE/VERIFY.
- Không tự sửa.
- Không chặn pipeline, trừ lỗi parse hoặc lỗi phát ngôn nghiêm trọng đã được rule hiện hành xác định.

Mục tiêu shadow mode là đo:

- Precision của finding.
- False positive.
- Tỷ lệ finding có evidence hợp lệ.
- Tỷ lệ Lead/Editor đồng ý với action.
- Chi phí token và độ trễ mỗi sản phẩm.

## 13. Regression Set ban đầu

Sử dụng sáu output A/C/v2.1 của hai chủ đề hiện có.

Các case bắt buộc phát hiện:

| Case | Expected code | Expected action |
|---|---|---|
| Tự giải thích “dữ kiện là, suy luận là” | `META_COMPLIANCE_LEAK` | `QUALIFY`/rewrite |
| Nói cơ cấu lỗ “đã đổi” khi thiếu cơ cấu kỳ trước | `TEMPORAL_COMPARISON_WITHOUT_BASELINE` | `QUALIFY` |
| Suy đoán lý do doanh nghiệp công bố sớm | `UNNECESSARY_SPECULATION` hoặc `CAUSAL_LEAP` | `REMOVE` |
| Nói dự báo chung là phép chia tổng bằng không | `OVERSTATED_INFERENCE` | `QUALIFY` |
| Gắn khiếu nại của giới vận tải khi nguồn không đề cập | `FACT_NOT_IN_SOURCE` | `REMOVE` hoặc `VERIFY` |
| Thiếu quote/watchlist/field tùy chọn | Không finding lỗi | `KEEP` |

## 14. Tiêu chí nghiệm thu v1.1

Đề xuất ngưỡng cho regression set và tập kiểm thử mở rộng:

- 100% lỗi số liệu/thực thể trọng yếu được phát hiện.
- Ít nhất 85% case suy luận mục tiêu được Lead/Editor đồng ý.
- False positive semantic không vượt 10% trên các claim được đánh dấu.
- 100% finding `FACT_NOT_IN_SOURCE`, `OVERSTATED_INFERENCE` và `CAUSAL_LEAP` phải có evidence hoặc mô tả rõ evidence còn thiếu.
- Không reject vì thiếu field tùy chọn hoặc mật độ thấp.
- Không full regeneration trong targeted repair test.
- Ít nhất 90% repair giữ nguyên các đoạn/scene/block không liên quan.
- Validator không làm xuất hiện Meta-compliance trong suggested revision.

Các ngưỡng trên là mục tiêu thử nghiệm, Lead có thể hiệu chỉnh sau khi có dữ liệu thực tế.

## 15. Logging tối thiểu

Lưu:

- Validator version.
- Content ID và source IDs.
- Finding/error code.
- Evidence reference.
- Action được đề xuất và action được chấp thuận.
- Token, latency và số lượt repair.
- Kết quả human review.

Không log chain-of-thought hoặc giải thích nội bộ dài. Chỉ lưu derivation summary ngắn đủ để audit.

## 16. Ranh giới kiến trúc

| Thành phần | Trách nhiệm |
|---|---|
| Composer Rules v2.1 | Tạo nội dung đúng hướng, tự nhiên và có góc nhìn. |
| Content Contract | Bảo đảm cấu trúc tối thiểu sử dụng được. |
| Semantic Validator v1.1 | Kiểm tra claim, evidence, suy luận và phát ngôn. |
| Editor | Rút gọn, giảm lặp, kiểm soát ẩn dụ và form imprint. |
| Publisher | CTA, disclaimer, metadata và yêu cầu kênh. |
| Renderer/Adapter | Layout, timecode, visual component và production format. |

## 17. Đề xuất phê duyệt

Đề nghị Lead:

1. Review error registry và ma trận KEEP/QUALIFY/REMOVE/VERIFY.
2. Xác nhận chính sách external knowledge mặc định.
3. Phê duyệt shadow mode với regression set A/C/v2.1.
4. Chưa bật auto-repair cho tới khi đạt tiêu chí nghiệm thu.
5. Giữ Composer Rules v2.1 ổn định trong suốt giai đoạn đo để tránh thay đổi đồng thời hai biến.

Nguyên tắc cuối:

> Một claim không trở nên hợp lệ chỉ vì nó được viết tự nhiên; một output không trở nên không hợp lệ chỉ vì nó ngắn hoặc không điền đủ template.
