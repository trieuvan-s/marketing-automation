<!--
NGUỒN: content-rules/CONTRACT_VALIDATOR_v1.md (thư mục sibling NGOÀI repo,
KHÔNG theo git). COPY VÀO REPO ngày 2026-07-22, nội dung GIỮ NGUYÊN.

VÌ SAO COPY: `content-rules/` ngoài git nên mất khi đổi máy/VPS — CÙNG LỚP LỖI
với data_root.

VAI TRÒ FILE NÀY: đặc tả NGUYÊN TẮC tham chiếu cho Contract Validator (BƯỚC 2,
rules v2.1 wiring, 2026-07-22) — schema JSON trừu tượng trong đây (§4 Input
Envelope, `blocks[].type: metric|comparison|...`) là THIẾT KẾ MỤC TIÊU TƯƠNG
LAI, KHÁC schema THẬT đang chạy (Python `ProductionBlock`/`media_factory/
spec.py`, TypeScript `required-slot-fields.ts`/`content-output.ts`). Việc ĐÃ
LÀM là áp NGUYÊN TẮC (chrome tự điền, warn-không-reject field tuỳ chọn, hard-
reject chỉ field lõi, không sinh placeholder, renderer chấp nhận cấu trúc
thưa) vào validator HIỆN CÓ — KHÔNG xây hệ envelope mới theo đúng schema literal
ở đây. Xem `tasks/ACTIVE_TASK.md`/STOP-REPORT phiên 2026-07-22 cho chi tiết đối
chiếu từng nguyên tắc §2/§8/§9/§10 vs code thật.
-->

# CONTRACT VALIDATOR v1

Trạng thái: Draft for Lead Review  
Ngày: 22/07/2026

## 1. Mục tiêu

Contract Validator v1 kiểm tra đầu ra của Composer có đúng cấu trúc tối thiểu để hệ thống phía sau sử dụng được hay không.

Validator này chỉ xử lý:

- JSON và cấu trúc payload.
- Field lõi, kiểu dữ liệu và enum.
- Field rỗng, block rỗng và collection rỗng.
- Conditional field theo loại sản phẩm.
- Delivery profile thực sự cần cho kênh đích.
- Chuẩn hóa kỹ thuật an toàn.

Validator này không xử lý:

- Dữ kiện có đúng nguồn hay không.
- Suy luận, nhân quả, dự báo hoặc luật phát ngôn.
- Chất lượng góc nhìn và văn phong.
- Số heading, số luận điểm hoặc độ dài bài.
- Mật độ ẩn dụ, lặp ý hoặc cảm giác AI hóa.

Các nội dung trên thuộc Semantic Validator, Editor hoặc Publisher.

## 2. Nguyên tắc thiết kế

1. **Minimum usable output:** chỉ bắt buộc phần lõi khiến sản phẩm có thể sử dụng.
2. **Sparse output hợp lệ:** thiếu field tùy chọn không phải lỗi.
3. **Không lấp chỗ trống:** Validator không tạo nội dung, số liệu, scene hoặc block mới.
4. **Maximum không phải minimum:** giới hạn sức chứa không được biến thành số lượng phải đạt.
5. **Deterministic first:** mọi xử lý phải thực hiện bằng code; Contract Validator không gọi LLM.
6. **Preserve valid content:** không thay đổi nội dung hợp lệ ngoài chuẩn hóa kỹ thuật đã khai báo.
7. **Profile tối thiểu:** delivery profile chỉ được tăng yêu cầu khi thiếu field khiến kênh đích không thể chạy.
8. **Không semantic hóa contract:** đúng schema không đồng nghĩa đúng sự thật; sai văn phong không đồng nghĩa sai contract.

## 3. Vị trí trong pipeline

```text
Composer output
→ Safe JSON normalization
→ Base Contract Validation
→ Delivery Profile Validation
→ PASS / PASS_NORMALIZED / REPAIR_REQUIRED / REJECT
→ Semantic Validator khi Risk Router yêu cầu
```

Contract Validator luôn chạy. Semantic Validator chỉ chạy theo mức rủi ro nội dung.

## 4. Input Envelope

```json
{
  "contract_version": "1.0",
  "content_type": "article | video | infographic",
  "delivery_profile": "optional-profile-id",
  "payload": {}
}
```

### Field do hệ thống cung cấp

| Field | Required | Chủ thể tạo |
|---|---|---|
| `contract_version` | Có | Runtime/orchestrator |
| `content_type` | Có | Router/orchestrator |
| `delivery_profile` | Không | Router/publisher |
| `payload` | Có | Composer |

Composer không cần sinh:

- Content ID.
- Timestamp.
- Schema version.
- Source ID.
- Tracking metadata.
- Delivery profile.

Những field này được hệ thống gắn vào envelope để tiết kiệm token và tránh Composer tự tạo metadata.

## 5. Output

```json
{
  "validator_version": "1.0",
  "status": "PASS | PASS_NORMALIZED | REPAIR_REQUIRED | REJECT",
  "content_type": "article",
  "delivery_profile": null,
  "normalized_payload": {},
  "changes": [],
  "issues": []
}
```

### Status

| Status | Ý nghĩa |
|---|---|
| `PASS` | Payload hợp lệ và không cần thay đổi. |
| `PASS_NORMALIZED` | Payload hợp lệ sau các sửa kỹ thuật an toàn. |
| `REPAIR_REQUIRED` | Thiếu hoặc sai phần lõi; không thể tự tạo nội dung để sửa. |
| `REJECT` | Không parse được, content type không hỗ trợ hoặc payload không thể xác định. |

### Issue object

```json
{
  "severity": "blocking | repairable | warning | info",
  "error_code": "MISSING_CORE_FIELD",
  "field_path": "payload.title",
  "message": "Thiếu title không rỗng.",
  "action": "UPSTREAM_REPAIR"
}
```

### Change object

```json
{
  "change_code": "REMOVE_EMPTY_OPTIONAL",
  "field_path": "payload.subtitle",
  "before": "",
  "after": "FIELD_REMOVED"
}
```

## 6. Safe Normalization

### Được phép tự động

- Xóa UTF-8 BOM.
- Bỏ Markdown code fence bao quanh một JSON root duy nhất.
- Trim khoảng trắng đầu/cuối của string.
- Chuẩn hóa line ending.
- Loại field tùy chọn có giá trị `null`, chuỗi rỗng, array rỗng hoặc object rỗng.
- Loại scene/block rỗng khi vẫn còn ít nhất một scene/block hợp lệ.
- Ánh xạ alias đã đăng ký rõ trong profile, ví dụ `headline → title`.
- Chuyển numeric string sang number chỉ với field kỹ thuật đã khai báo, như `duration_hint_sec`.
- Loại phần tử array `null` hoặc rỗng khi việc đó không làm thay đổi thứ tự phần tử còn lại.

### Không được tự động

- Viết title từ nội dung body nếu không có alias/extractor được cấu hình trước.
- Tạo subtitle, summary, narration, visual hoặc block mới.
- Suy ra mã chứng khoán, nguồn, thời điểm hoặc đơn vị.
- Chuyển nội dung hiển thị như `"13,8 tỷ USD"` thành số thuần.
- Rút gọn hoặc viết lại câu để vừa giới hạn ký tự.
- Tự chia một claim sang nhiều scene/block bằng LLM.
- Xóa phần tử vượt sức chứa mà không báo lỗi.
- Sắp xếp lại scene, block hoặc luận điểm.
- Sửa JSON khi dấu ngoặc hoặc dấu nháy bị hỏng theo cách có nhiều khả năng diễn giải.

Safe normalization phải có tính idempotent: chạy lần hai trên cùng output không tạo thêm thay đổi.

## 7. Base Contract chung

### Required

| Field | Kiểu | Rule |
|---|---|---|
| `contract_version` | string | Phải được runtime hỗ trợ. |
| `content_type` | enum | `article`, `video` hoặc `infographic`. |
| `payload` | object | Không được rỗng sau normalization. |

### Optional

| Field | Kiểu | Rule |
|---|---|---|
| `delivery_profile` | string | Nếu có, profile phải tồn tại. |
| `extensions` | object | Dùng cho field mở rộng có namespace. |

### Unknown field policy

Chế độ mặc định là `lenient`:

- Unknown field tạo warning `UNDECLARED_FIELD`.
- Không làm payload bị reject nếu field lõi vẫn hợp lệ.
- Renderer/adapter chỉ đọc field đã khai báo.

Chế độ `strict` chỉ dùng cho integration test hoặc API endpoint cần hợp đồng đóng.

## 8. Article Contract

### Required

| Field | Kiểu | Rule |
|---|---|---|
| `title` | string | Sau trim phải còn nội dung. |
| `body_markdown` | string | Sau trim phải còn nội dung. |

### Optional

| Field | Kiểu |
|---|---|
| `subtitle` | string |
| `summary` | string |
| `key_points` | array of non-empty string |
| `mentioned_symbols` | array of non-empty string |
| `cta` | string |
| `disclaimer` | string |
| `extensions` | object |

### Không kiểm tra trong contract

- Số heading hoặc đoạn.
- Word count tối thiểu.
- Có hook, quote, watchlist hoặc kết luận hay không.
- Title có đúng sự thật hay hấp dẫn hay không.
- `body_markdown` có lặp ý hoặc lộ rules hay không.

### Payload tối thiểu hợp lệ

```json
{
  "title": "Tiêu đề",
  "body_markdown": "Nội dung hoàn chỉnh."
}
```

## 9. Video Contract

### Required

| Field | Kiểu | Rule |
|---|---|---|
| `title` | string | Không rỗng. |
| `scenes` | array | Ít nhất một scene hợp lệ. |

### Scene Contract

Mỗi scene phải có ít nhất một trong hai field không rỗng:

- `narration`.
- `on_screen_text`.

| Field | Required | Kiểu |
|---|---|---|
| `narration` | Conditional | string |
| `on_screen_text` | Conditional | string |
| `visual_direction` | Không | string |
| `duration_hint_sec` | Không | number lớn hơn 0 |
| `transition_hint` | Không | string |
| `source_ref` | Không | string |
| `extensions` | Không | object |

### Base contract không yêu cầu

- Số scene cố định.
- Timecode.
- Mọi scene phải có cả narration, on-screen text và visual.
- Hook, CTA hoặc transition.
- Tổng thời lượng.

### Payload tối thiểu hợp lệ

```json
{
  "title": "Tiêu đề video",
  "scenes": [
    {
      "narration": "Một scene có nội dung sử dụng được."
    }
  ]
}
```

## 10. Infographic Contract

### Required

| Field | Kiểu | Rule |
|---|---|---|
| `title` | string | Không rỗng. |
| `blocks` | array | Ít nhất một block hợp lệ. |

### Optional ở cấp payload

| Field | Kiểu |
|---|---|
| `subtitle` | string |
| `footer_note` | string |
| `mentioned_symbols` | array of non-empty string |
| `extensions` | object |

### Block Contract

| Field | Required | Kiểu/Rule |
|---|---|---|
| `type` | Có | `metric`, `comparison`, `timeline`, `list`, `insight`, `quote` hoặc `text` |
| `heading` | Không | non-empty string |
| `items` | Conditional | non-empty array |
| `text` | Conditional | non-empty string |
| `visual_hint` | Không | string hoặc object theo catalog |
| `extensions` | Không | object |

Mỗi block phải có ít nhất:

- `items` không rỗng; hoặc
- `text` không rỗng.

### Item Contract

```json
{
  "label": "optional string",
  "value": "optional string",
  "text": "optional string",
  "note": "optional string"
}
```

Mỗi item phải có ít nhất một field nội dung không rỗng. Contract Validator không kiểm tra giá trị có đúng label, đơn vị hoặc nguồn hay không; đó là Semantic Validator.

### Payload mật độ thấp hợp lệ

```json
{
  "title": "Một thay đổi đáng chú ý",
  "blocks": [
    {
      "type": "insight",
      "text": "Một thông điệp có thể hiển thị độc lập."
    }
  ]
}
```

Không yêu cầu phải có đủ `hero`, `market`, `highlights`, `related` hoặc `quote`.

## 11. Delivery Profile Overlay

Base contract luôn được kiểm tra trước. Profile chỉ bổ sung yêu cầu do kênh đích thực sự cần.

### Nguyên tắc

1. Profile không thay đổi rules viết.
2. Profile không yêu cầu field chỉ để bố cục trông đầy hơn.
3. Profile có thể đặt giới hạn tối đa nhưng không biến nó thành số lượng tối thiểu.
4. Khi payload vượt sức chứa, ưu tiên `SPLIT_REQUIRED` hoặc chọn renderer khác; không cắt âm thầm.
5. Nếu không có profile, base contract là đủ.

### Ví dụ

#### `video.heygen_narrated`

- Mỗi scene phải có `narration`.
- `on_screen_text` và `visual_direction` vẫn optional.
- Timecode có thể do adapter tính sau.

#### `video.silent_social`

- Mỗi scene phải có `on_screen_text`.
- `narration` optional.

#### `infographic.social_4_5`

- Profile khai báo sức chứa tối đa theo renderer.
- Nếu vượt sức chứa: `SPLIT_REQUIRED` hoặc chuyển template.
- Nếu chỉ có một block: vẫn hợp lệ, renderer dùng compact layout.

## 12. Legacy Compatibility

Payload infographic cũ có thể sử dụng các field:

```text
hero
market
highlights
related
quote
```

Không đưa logic chuyển đổi legacy vào core validator. Pipeline chuyển tiếp:

```text
Legacy payload
→ Deterministic Legacy Adapter
→ Canonical blocks[] payload
→ Contract Validator v1
```

Ánh xạ đề xuất:

| Legacy field | Canonical block |
|---|---|
| `hero[]` | `metric` với display priority cao |
| `market[]` | `metric` hoặc `list` |
| `highlights[]` | `list` |
| `related[]` | `list` |
| `quote` | `quote` |

Adapter chỉ chuyển dữ liệu đang có; không tạo field thiếu và không lấp block rỗng.

## 13. Error Code Registry

### Parsing và envelope

| Error code | Mức | Hành động |
|---|---|---|
| `PARSE_ERROR` | blocking | Safe repair nếu không mơ hồ; nếu thất bại thì `REJECT`. |
| `MISSING_CONTRACT_VERSION` | repairable | Runtime bổ sung version đã cấu hình. |
| `UNSUPPORTED_CONTRACT_VERSION` | blocking | Route tới compatible validator hoặc reject. |
| `MISSING_CONTENT_TYPE` | blocking | Router bổ sung; không để Composer đoán. |
| `UNSUPPORTED_CONTENT_TYPE` | blocking | `REJECT`. |
| `MISSING_PAYLOAD` | blocking | `REPAIR_REQUIRED` hoặc `REJECT`. |
| `INVALID_PAYLOAD_TYPE` | blocking | `REPAIR_REQUIRED`. |

### Field và collection

| Error code | Mức | Hành động |
|---|---|---|
| `MISSING_CORE_FIELD` | repairable | `UPSTREAM_REPAIR`; không tự sinh nội dung. |
| `EMPTY_CORE_FIELD` | repairable | `UPSTREAM_REPAIR`. |
| `INVALID_TYPE` | repairable | Coerce chỉ khi rule an toàn đã đăng ký. |
| `INVALID_ENUM` | repairable | Không tự đoán enum nếu có nhiều khả năng. |
| `EMPTY_OPTIONAL_FIELD` | info | Xóa field. |
| `EMPTY_COLLECTION_ITEM` | info | Xóa item rỗng. |
| `EMPTY_COLLECTION` | info hoặc repairable | Xóa nếu optional; repair nếu core. |
| `UNDECLARED_FIELD` | warning | Giữ/ignore ở lenient mode; reject ở strict mode. |
| `DUPLICATE_SCALAR_ITEM` | warning | Không tự xóa nếu có thể mang ý nghĩa. |

### Article, Video và Infographic

| Error code | Mức | Hành động |
|---|---|---|
| `ARTICLE_BODY_MISSING` | repairable | `UPSTREAM_REPAIR`. |
| `SCENE_WITHOUT_CONTENT` | repairable | Bỏ scene nếu còn scene hợp lệ; nếu không thì repair. |
| `BLOCK_WITHOUT_CONTENT` | repairable | Bỏ block nếu còn block hợp lệ; nếu không thì repair. |
| `ITEM_WITHOUT_CONTENT` | info/repairable | Bỏ item; repair nếu block mất toàn bộ nội dung. |
| `PROFILE_NOT_FOUND` | blocking | Sửa cấu hình profile. |
| `PROFILE_REQUIREMENT_MISSING` | repairable | Adapter/upstream repair; không bịa content. |
| `ARRAY_OVER_CAPACITY` | warning/repairable | `SPLIT_REQUIRED` hoặc chọn renderer khác. |
| `OUT_OF_RANGE` | repairable | Chỉ clamp với field kỹ thuật được phép. |

## 14. Decision Logic

```text
1. Không parse được sau safe normalization       → REJECT
2. Contract/content type/profile không hỗ trợ    → REJECT
3. Thiếu field lõi không thể tự bổ sung           → REPAIR_REQUIRED
4. Có lỗi profile khiến kênh không chạy           → REPAIR_REQUIRED
5. Chỉ có safe normalization                      → PASS_NORMALIZED
6. Chỉ có warning/info                            → PASS hoặc PASS_NORMALIZED
7. Không có issue                                 → PASS
```

Không được trả `REJECT` chỉ vì:

- Thiếu field tùy chọn.
- Bài ngắn.
- Infographic chỉ có một block.
- Video chỉ có một scene.
- Không có quote, CTA, watchlist hoặc visual direction.
- Không đạt đầy sức chứa template.

## 15. Pseudocode tham chiếu

```text
function validateContract(rawInput, runtimeConfig):
    parsed = safeParse(rawInput)
    if parsed.failed:
        return REJECT(PARSE_ERROR)

    envelope = injectRuntimeFields(parsed, runtimeConfig)
    envelope = normalizeEnvelope(envelope)

    validateBaseContract(envelope)
    if hasBlockingEnvelopeIssue:
        return REJECT(issues)

    payloadResult = validateByContentType(
        envelope.content_type,
        envelope.payload
    )

    if envelope.delivery_profile:
        profileResult = validateProfileOverlay(
            envelope.delivery_profile,
            payloadResult.normalized_payload
        )

    issues = mergeIssues(payloadResult, profileResult)
    changes = mergeChanges(payloadResult, profileResult)

    if hasMissingCoreOrProfileRequirement(issues):
        return REPAIR_REQUIRED(issues, changes)
    if changes.notEmpty:
        return PASS_NORMALIZED(normalized_payload, issues, changes)
    return PASS(normalized_payload, issues)
```

## 16. Test Matrix

### Article

| Case | Expected |
|---|---|
| Có title và body | `PASS` |
| Subtitle rỗng | Xóa subtitle, `PASS_NORMALIZED` |
| Không có key points/watchlist | `PASS` |
| Không có title | `REPAIR_REQUIRED` |
| Body chỉ có khoảng trắng | `REPAIR_REQUIRED` |

### Video

| Case | Expected |
|---|---|
| Một scene chỉ có narration | `PASS` |
| Một scene chỉ có on-screen text | `PASS` ở base contract |
| Một scene rỗng giữa các scene hợp lệ | Bỏ scene rỗng, `PASS_NORMALIZED` |
| Tất cả scene rỗng | `REPAIR_REQUIRED` |
| HeyGen narrated thiếu narration | `REPAIR_REQUIRED` theo profile |
| Thiếu timecode | `PASS` |

### Infographic

| Case | Expected |
|---|---|
| Một block insight | `PASS` |
| Không có hero/market/quote | `PASS` |
| Một block rỗng giữa các block hợp lệ | Bỏ block rỗng, `PASS_NORMALIZED` |
| Không còn block hợp lệ | `REPAIR_REQUIRED` |
| Ít block hơn sức chứa layout | `PASS` và compact renderer |
| Nhiều block hơn sức chứa | `ARRAY_OVER_CAPACITY`, `SPLIT_REQUIRED` |

### Safety properties

| Property | Expected |
|---|---|
| Chạy normalize hai lần | Kết quả giống lần một |
| Optional field thiếu | Không reject |
| Payload mật độ thấp hợp lệ | Không tạo dữ liệu mới |
| Một block lỗi | Không thay đổi block đúng |
| Unknown field ở lenient mode | Warning, không reject |

## 17. Tiêu chí nghiệm thu

- 100% payload hợp lệ trong regression set được chấp nhận.
- 100% trường hợp thiếu core field được phát hiện.
- 0 trường hợp reject vì thiếu field tùy chọn.
- 0 field nội dung được tự tạo trong normalization.
- 100% change có `change_code` và `field_path`.
- Normalization đạt tính idempotent.
- Không thay đổi thứ tự scene, block hoặc item hợp lệ.
- Không gọi LLM và không phát sinh token inference.
- Không kiểm tra hoặc sửa claim theo ngữ nghĩa.
- Không xóa dữ liệu vượt capacity; phải trả `SPLIT_REQUIRED` hoặc chọn renderer khác.

## 18. Logging tối thiểu

Lưu:

- Validator version và contract version.
- Content type và delivery profile.
- Status cuối.
- Error code, field path và action.
- Danh sách safe normalization đã thực hiện.
- Latency và payload size.

Không log toàn bộ nội dung nếu không cần cho audit. Không log chain-of-thought.

## 19. Versioning

| Thay đổi | Version |
|---|---|
| Sửa lỗi validator, không đổi contract | Patch |
| Thêm field optional hoặc error code tương thích | Minor |
| Thay đổi required field hoặc hành vi không tương thích | Major |

Contract Validator v1 chỉ xác nhận Contract v1.x. Runtime phải route version khác tới validator tương ứng.

## 20. Cấu trúc triển khai đề xuất

```text
contracts/
├── CONTENT_CONTRACTS_v1.md
├── schemas/
│   ├── envelope.v1.schema.json
│   ├── article.v1.schema.json
│   ├── video.v1.schema.json
│   └── infographic.v1.schema.json
└── profiles/
    ├── video.heygen_narrated.json
    ├── video.silent_social.json
    └── infographic.social_4_5.json

validation/
├── contract_validator/
│   ├── validator
│   ├── normalizers
│   ├── error_codes
│   └── profile_loader
└── tests/
    ├── article_fixtures
    ├── video_fixtures
    └── infographic_fixtures
```

Tên file triển khai cụ thể tùy ngôn ngữ của repository. Không cần tạo một Contract Validator Agent.

## 21. Đề xuất cho Lead

1. Phê duyệt required tối thiểu của ba content type.
2. Xác nhận canonical infographic dùng `blocks[]` và legacy schema được xử lý qua adapter.
3. Xác nhận default mode là `lenient`; `strict` chỉ dùng cho integration test/API đóng.
4. Phê duyệt danh sách safe normalization.
5. Xác nhận delivery profile nào thật sự cần ở MVP.
6. Triển khai Contract Validator trước Semantic Validator vì không có chi phí LLM và dễ test tất định.

Nguyên tắc cuối:

> Contract Validator bảo đảm sản phẩm có hình dạng sử dụng được; nó không quyết định nội dung có đúng, hay hoặc đầy đủ theo một template hay không.
