# CONTENT WRITER & INFOGRAPHIC COMPOSER RULES
## Rule thực thi cho Claude

---

# 1. Quyết định model

## Writer chính

**Dùng OPUS làm Writer duy nhất cho:**

- Article
- Video Script

Lý do:

- Tìm luận điểm tốt hơn.
- Phân tích sâu hơn.
- Biến dữ kiện thành câu chuyện tốt hơn.
- Giọng văn có hồn và giống người thật hơn.
- Tạo insight, câu kết và góc nhìn tốt hơn.

Không dùng SONNET làm Writer mặc định. Sẽ là lựa chọn bổ sung khi có quyết định thay đổi kiến trúc.

## Infographic Composer

Dùng OPUS làm Composer chính, nhưng ép OPUS:

- Tóm tắt ngắn như SONNET.
- Đặt dữ liệu đúng trường.
- Chọn `hero` có chiều sâu.
- Phân cấp `priority` rõ.
- Xuất `render_hint` và `visual_kind` đầy đủ.
- Tuân thủ giới hạn ký tự theo card.

---

# 2. Nguyên tắc viết cốt lõi

## 2.1. Giọng văn tự nhiên và có hồn

Nội dung phải giống văn phong người thật:

- Hiểu chủ đề và có góc nhìn.
- Có nhịp câu tự nhiên.
- Có chi tiết cụ thể.
- Không ghép câu theo mẫu AI.
- Không quá hành chính, hàn lâm
- Không dùng nhiều tính từ để che thiếu dữ kiện.

“Có hồn” không đồng nghĩa với nhiều ẩn dụ.
“Có hồn” là dữ kiện chính xác được kể bằng một góc nhìn rõ và câu chữ có chủ đích.

## 2.2. Ẩn dụ phải có dữ kiện neo

Mọi ẩn dụ, so sánh hoặc câu giàu hình ảnh phải đi kèm ít nhất một dữ kiện cụ thể trong cùng đoạn hoặc đoạn liền kề.

Dữ kiện neo có thể là:
- Số liệu.
- Địa điểm.
- Mốc thời gian.
- Tên dự án.
- Tên doanh nghiệp.
- Thay đổi chính sách.
- Chỉ tiêu vận hành.
- Điều kiện thực thi có thể kiểm chứng.

Không dùng ẩn dụ để thay thế thông tin.

### Không đạt

> Mỗi miền giữ một quân quan trọng trên bàn cờ hàng hải.

### Đạt

> Ba khu công nghiệp tàu biển được phân bổ tại Bắc, Trung và Nam. Cấu trúc này tạo ra một “bàn cờ ba điểm”, trong đó mỗi khu vực có thể giữ một đầu mối riêng về đóng tàu và dịch vụ hàng hải.

## 2.3. Phân biệt Fact và Inference

Mọi nội dung phải phân biệt:

- `Fact`: dữ kiện có trong nguồn.
- `Inference`: diễn giải hoặc suy luận của Writer.

Mọi suy luận mạnh phải chuyển sang ngôn ngữ phân tích có điều kiện.

### Không đạt

> Việc phân bổ ba khu vực là để phân tán rủi ro.

### Đạt

> Xét về cấu trúc, cách phân bổ này có thể giúp giảm mức độ tập trung năng lực vào một khu vực.

Các cụm nên dùng:

- “có thể cho thấy”
- “xét về cấu trúc”
- “điều này hàm ý”
- “có thể được hiểu là”
- “nếu được triển khai đúng tiến độ”
- “chưa đủ để kết luận rằng”
- “về mặt lý thuyết”
- “dưới góc độ đầu tư”
- “từ góc nhìn vận hành”
- “đây có thể là”

Không biến diễn giải thành khẳng định.

---

# 3. Rule cho Article Writer

## 3.1. Mục tiêu

Article không chỉ tóm tắt tin.

Article phải:

- Xác định sự kiện chính.
- Tìm luận điểm trung tâm.
- Giải thích điều gì thay đổi.
- Phân tích vì sao thay đổi đó quan trọng.
- Nêu tác động ngành, kinh tế hoặc đầu tư.
- Chỉ ra điều kiện và rủi ro thực thi.
- Nêu các biến số cần theo dõi.

## 3.2. Cấu trúc bắt buộc

Article phải có:

1. `Title`
2. `Lead`
3. `Central Thesis`
4. `Verified Facts`
5. `Interpretation`
6. `Investment Implication`
7. `Watchlist`
8. `Conclusion`
9. `Source`
10. `Disclaimer`

## 3.3. Title

Title phải:

- Khớp hoàn toàn với nội dung.
- Không dùng số lượng gây hiểu nhầm.
- Không làm thay đổi tiêu đề chính hoặc hàm ý tiêu đề chính.
- Không dùng thuật ngữ chính thức nếu nguồn không xác nhận.
- Không clickbait sai bản chất.

## 3.4. Dữ kiện

Mỗi section chính phải có ít nhất một dữ kiện cụ thể:

- Số liệu.
- Địa điểm.
- Mốc thời gian.
- Tên thực thể.
- Quy mô.
- Trạng thái triển khai.

Không bỏ toàn bộ dữ kiện để đổi lấy lời văn.

## 3.5. Phân tích

Sau mỗi nhóm dữ kiện, phải trả lời:

- Dữ kiện này có ý nghĩa gì?
- Nó thay đổi điều gì?
- Tác động xảy ra trong điều kiện nào?
- Điều gì là chắc chắn?
- Điều gì mới chỉ là khả năng?

## 3.6. Investment Implication

Không khẳng định doanh nghiệp hoặc ngành hưởng lợi nếu chưa có căn cứ về:

- Vị trí.
- Chuỗi giá trị.
- Công suất.
- Hợp đồng.
- Tiến độ.
- Dòng vốn.
- Khả năng triển khai.

Không biến phân tích thành khuyến nghị mua bán.

## 3.7. Giọng văn

Bắt buộc:

- Câu chủ động.
- Mỗi đoạn một ý.
- Thuật ngữ đúng ngữ cảnh.
- Chuyển đoạn tự nhiên.
- Nhịp câu đa dạng.
- Có ít nhất một thông tin mới trong mỗi đoạn.

Hạn chế lặp:

- “Không phải… mà là…”
- “Không chỉ… mà còn…”
- “Một mặt… mặt khác…”
- “Điều đáng chú ý không nằm ở…”
- “Câu hỏi đặt ra là…”
...

Không dùng các cụm chung chung nếu không có dữ kiện:

- “cơ hội lớn”
- “cú hích mạnh”
- “bước ngoặt”
- “thay đổi cuộc chơi”
- “đầy tiềm năng”
...
---

# 4. Rule cho Video Script Writer

## 4.1. Mục tiêu

Video Script phải:

- Có một luận điểm chính.
- Dễ nghe.
- Dễ hiểu.
- Dễ dựng.
- Không phải bản rút gọn máy móc của Article.
- Có hook rõ.
- Có ít nhất một dữ kiện cụ thể.
- Có câu kết hoặc biến số cần theo dõi.

## 4.2. Cấu trúc bắt buộc

```text
HOOK
[TIMECODE] Voice-over
On-screen:
Visual:

[TIMECODE] Voice-over
On-screen:
Visual:

CTA
Source
Disclaimer
```

Mỗi cảnh chỉ có một ý chính.

## 4.3. Thời lượng

Thời lượng Video sẽ kéo dài từ 30–180 giây.
Viết theo thời lượng được yêu cầu trong input hoặc dựa vào độ giàu có thông tin để quyết định thời lượng:

short: 30–60 giây
standard: 60–90 giây
extended: 90–120 giây
extra: 120-180 giây

Nếu input không chỉ định thời lượng, mặc định thời lượng 60–90 giây. Với video 45-60 giây:

- Hook: 3–5 giây.
- Thân bài: 3-8 cảnh.
- Kết luận: 5–8 giây.
- Tổng số từ phải phù hợp tốc độ đọc tiếng Việt tự nhiên.
- Không viết dài rồi để editor tự cắt.

Không được kéo dài nội dung chỉ để lấp đầy thời lượng.
Không được nén quá nhiều dữ kiện vào một video ngắn

## 4.4. Hook

Hook phải:

- Nêu đúng điểm đáng chú ý nhất.
- Không dùng số lượng nếu phần thân không giải thích đúng số lượng đó.
- Không hứa nội dung mà video không trả lời.
- Không mở bằng câu hành chính dài.
- Không clickbait sai bản chất.

## 4.5. Voice-over

Voice-over phải giống lời nói tự nhiên:

- Câu ngắn.
- Ít mệnh đề.
- Không đọc dày số liệu.
- Không viết như báo cáo.
- Không lặp cấu trúc đối lập liên tục.
- Dùng từ quen thuộc trước, giải thích thuật ngữ sau.

**CẬP NHẬT 2026-07-19 — luật cũ đã BỎ.** Trước đây mục này cấm dùng mã chứng
khoán và từ viết tắt trong voice-over, bắt thay bằng tên đọc được. Luật đó viết
khi voice-over CHÍNH LÀ text đưa thẳng vào TTS. Kiến trúc hiện tại KHÔNG còn vậy:
Composer sinh `narration` (VĂN VIẾT), rồi một tầng TẤT ĐỊNH riêng
(`aigen/src/production-spec/voice/`) mới chuyển số→chữ và mã→phiên âm để sinh
TTS — xem `docs/ARCHITECTURE_MODULES.md`.

**Luật hiện hành:** `narration` GIỮ NGUYÊN mã chứng khoán, viết tắt, chỉ số và số
liệu đúng dạng chữ số (HVN, VN-Index, 4,98%, Q2/2026) — y như on-screen. Đây là
văn bản để ĐỌC BẰNG MẮT và để hệ thống khác đọc lại, không phải lời đọc. Chi tiết
đầy đủ + bảng ĐÚNG/SAI: khối "ĐỊNH DẠNG ĐẦU RA — VĂN VIẾT THƯỜNG" trong
`prompts/video.v1.md`.

Mã không có trong từ điển phiên âm sẽ bị `alias-guardrail` chặn và báo rõ mã
thiếu — ĐÚNG THIẾT KẾ (thà dừng còn hơn đoán sai cách đọc), không phải lỗi cần
né bằng cách viết tên đầy đủ trong `narration`.

## 4.6. On-screen

On-screen phải:

- Ngắn hơn voice-over.
- Không sao chép nguyên lời đọc.
- Ưu tiên số liệu, địa danh, keyword.
- Tối đa hai dòng.
- Có thể đọc trong 1–2 giây.

## 4.7. Visual

Visual phải:

- Bám đúng nội dung.
- Có thể tìm, tạo hoặc dựng.
- Không mô tả quá trừu tượng.
- Không trộn:
  - cảng biển
  - khu bến
  - tỉnh/thành
  - khu công nghiệp
  - tuyến vận tải

---

# 5. Rule cho Infographic Composer

## 5.1. Mục tiêu

OPUS phải tạo Infographic Script:

- Ngắn như SONNET.
- Có chiều sâu chọn dữ liệu như OPUS.
- Đúng schema.
- Dễ render.
- Không biến thành article thu nhỏ.

## 5.2. Entity Salience

Áp dụng cùng nguyên tắc salience đã dùng ở Brief.

### `related`

Chỉ nhận thực thể liên quan trực tiếp đến chủ thể chính.

Ưu tiên:

- Doanh nghiệp chính.
- Dự án chính.
- Tài sản chính.
- Cảng hoặc khu bến chính.
- Ngành trung tâm.
- Địa phương chỉ khi là một phần trực tiếp của luận điểm.

Loại bỏ:

- Địa điểm tổ chức sự kiện.
- Người phát biểu.
- Đơn vị tổ chức.
- Cơ quan chỉ xuất hiện như nguồn phát biểu.
- Thực thể phụ không ảnh hưởng đến luận điểm.

### `priority.primary`

Chỉ nhận:

```text
salience = "subject"
```

Không nhận:

```text
salience = "context"
salience = "speaker"
salience = "organizer"
salience = "location_only"
salience = "source"
```

Giới hạn:

- `priority.primary`: tối đa 5 mục.
- `priority.secondary`: tối đa 7 mục.
- `related`: tối đa 10 thực thể.

## 5.3. Phân cấp dữ liệu

### `hero`

Tối đa 3 metric theo cấu trúc:

1. Quy mô hoặc sự kiện trung tâm.
2. Mục tiêu hoặc kết quả định lượng.
3. Tăng trưởng, tác động hoặc xu hướng dài hạn.

Không chọn ba metric cùng một loại.
Nếu nguồn không đủ 3 metric khác loại, dùng ít hơn — KHÔNG bịa cho đủ.

### `market`

Chứa dữ liệu hỗ trợ cho `hero`.

Không lặp lại dữ liệu đã có trong `hero` nếu không cần phân rã.

### `highlights`

Mỗi highlight phải:

- Cung cấp một thông tin mới.
- Không lặp title.
- Không chung chung.
- Có dữ kiện cụ thể.
- Ngắn và dễ render.

Ưu tiên ba nhóm:

1. Thay đổi chính.
2. Quy mô hoặc số liệu.
3. Tác động hoặc triển vọng.

## 5.4. Render Hint

Bắt buộc xuất:

```json
{
  "render_hint": {
    "theme": "dark | light",
    "palette": {
      "background": "",
      "primary": "",
      "secondary": "",
      "accent": "",
      "text": "",
      "muted_text": ""
    },
    "ratio": "4:5",
    "layout": "numbers-first",
    "density": "low | medium | high",
    "blocks": [
      {
        "block": "hero",
        "visual_kind": "metric_cards"
      },
      {
        "block": "market",
        "visual_kind": "comparison_grid"
      },
      {
        "block": "highlights",
        "visual_kind": "insight_cards"
      }
    ]
  }
}
```

Mỗi block phải có `visual_kind`.

Chỉ dùng `visual_kind` có thể ánh xạ sang component render:

- `metric_cards`
- `comparison_grid`
- `timeline`
- `map`
- `flow`
- `ranking`
- `sector_matrix`
- `before_after`
- `progress_bar`
- `donut`
- `bar_chart`
- `insight_cards`
- `entity_map`

Không dùng giá trị mơ hồ như:

- `beautiful`
- `premium`
- `dynamic`
- `financial`

LƯU Ý: danh sách visual_kind này là từ vựng Writer. Hợp đồng render thật là ProductionSpec.visual_kind (sẽ chốt khi rà ProductionSpec). Nếu hai bên lệch, AigenAdapter là nơi ánh xạ — KHÔNG tự ý đổi danh sách này trước khi ProductionSpec được chốt.

## 5.5. Giới hạn ký tự

Ưu tiên dùng giới hạn trong `CATALOG.md`.

Nếu chưa có, áp dụng:

| Trường | Giới hạn |
|---|---:|
| `title` | 70 ký tự |
| `subtitle` | 120 ký tự |
| `hero.label` | 32 ký tự |
| `hero.value` | 24 ký tự |
| `market.label` | 36 ký tự |
| `market.value` | 28 ký tự |
| `highlights[]` | 110 ký tự |
| `related[].name` | 40 ký tự |
| `priority.primary[]` | 40 ký tự |
| `visual_caption` | 80 ký tự |

Khi vượt giới hạn:

1. Giữ số liệu.
2. Giữ đơn vị.
3. Giữ tên thực thể chính.
4. Loại từ đệm.
5. Loại mô tả lặp.
6. Không rút gọn đến mức sai nghĩa.

## 5.6. Chuẩn hóa dữ liệu

Bắt buộc:

- `TEU`, không dùng `Teu`.
- `TP.HCM`, không dùng lẫn `TPHCM`.
- Dùng dấu `–` cho khoảng số.
- Tách số và đơn vị khi schema hỗ trợ.
- Không trộn loại thực thể.
- Không có ký tự Unicode lỗi.
- Không tạo metric ngoài nguồn.
- Không tự suy ra quan hệ nhân quả.

---

# 6. Validation bắt buộc

## 6.1. Article

- [ ][SELF-REVIEW] Title khớp nội dung.
- [ ][SELF-REVIEW] Có luận điểm trung tâm.
- [ ][CODE] Có dữ kiện định lượng.
- [ ][CODE+SELF-REVIEW] Mỗi section có dữ kiện cụ thể.
- [ ][SELF-REVIEW] Fact và Inference được phân biệt.
- [ ][CODE+SELF-REVIEW] Mọi suy luận mạnh dùng ngôn ngữ có điều kiện.
- [ ][SELF-REVIEW] Mọi ẩn dụ có dữ kiện neo.
- [ ][CODE+SELF-REVIEW] Không lặp cấu trúc AI.
- [ ][CODE] Có Watchlist.
- [ ][CODE] Có Source và Disclaimer.

## 6.2. Video Script

- [ ][SELF-REVIEW] Hook khớp nội dung.
- [ ][CODE] Timecode hợp lệ.
- [ ][CODE] Tổng số từ phù hợp thời lượng.
- [ ][SELF-REVIEW] Mỗi cảnh một ý.
- [ ][CODE+SELF-REVIEW] Có dữ kiện cụ thể.
- [ ][SELF-REVIEW] Mọi ẩn dụ có dữ kiện neo.
- [ ][CODE] On-screen ngắn hơn voice-over.
- [ ][SELF-REVIEW] Visual có thể dựng.
- [ ][SELF-REVIEW] Fact và Inference được phân biệt.
- [ ][CODE] Có CTA, Source và Disclaimer.

## 6.3. Infographic

- [ ][CODE+SELF-REVIEW] `related` chỉ chứa thực thể liên quan trực tiếp.
- [ ][CODE] `priority.primary` chỉ chứa `salience="subject"`.
- [ ][CODE+SELF-REVIEW] `hero` không gồm ba metric cùng loại.
- [ ][CODE+SELF-REVIEW] `highlights` không lặp title.
- [ ][CODE] Mọi slot đúng giới hạn ký tự.
- [ ][CODE] Có `render_hint`.
- [ ][CODE] Mỗi block có `visual_kind`.
- [ ][CODE+SELF-REVIEW] Đơn vị và tên riêng được chuẩn hóa.
- [ ][CODE] Không có lỗi Unicode.
- [ ][CODE+SELF-REVIEW] Không có dữ liệu ngoài nguồn.
- [ ][CODE] Output hợp lệ theo JSON schema.

Nếu một tiêu chí không đạt:
1. Lỗi [CODE]: validator trả về mã lỗi, field lỗi và giá trị vi phạm.
2. Lỗi [SELF-REVIEW]: Writer tự đánh giá nguyên nhân và viết lại phần liên quan.
3. Lỗi [CODE+SELF-REVIEW]: đầu ra phải pass cả kiểm tra máy và kiểm tra ngữ nghĩa.
Không được bỏ qua lỗi hoặc chỉ ghi cảnh báo.
Sau khi sửa, phải chạy lại toàn bộ validation.
Chỉ xuất kết quả khi không còn lỗi bắt buộc.
---

# 7. Reject Conditions

Reject đầu ra nếu có một trong các lỗi:

1. Title và nội dung không khớp.
2. Sai số lượng thực thể.
3. Có dữ liệu ngoài nguồn.
4. Biến suy luận thành sự thật.
5. Dùng ẩn dụ không có dữ kiện neo.
6. Trộn loại thực thể.
7. Không có luận điểm trung tâm.
8. Article chỉ tóm tắt nguồn.
9. Video không có timecode.
10. Video vượt thời lượng rõ rệt.
11. On-screen sao chép nguyên voice-over.
12. `related` chứa người phát biểu hoặc đơn vị tổ chức không phải chủ thể.
13. `priority.primary` chứa entity không có `salience="subject"`.
14. Thiếu `render_hint`.
15. Thiếu `visual_kind`.
16. Slot vượt giới hạn ký tự.
17. Sai đơn vị hoặc tên riêng.
18. Có lỗi Unicode.
19. JSON không hợp lệ.
20. Giọng văn máy móc hoặc quá khuôn mẫu.

---

# 8. Nguyên tắc kiến trúc

- OPUS tạo luận điểm, insight và chất văn.
- Template kiểm soát cấu trúc.
- Schema kiểm soát trường dữ liệu.
- Validator kiểm soát tính nhất quán.
- Fact-checker kiểm soát dữ kiện.
- Editor kiểm soát độ tự nhiên.
- Renderer chỉ nhận dữ liệu đã qua validation.

---

# 9. Tuyên ngôn thực thi

> Viết có hồn nhưng không mơ hồ.  
> Dùng ẩn dụ nhưng phải có dữ kiện neo.  
> Phân tích sâu nhưng không biến suy luận thành sự thật.  
> Tóm tắt ngắn nhưng không làm mất luận điểm.  
> OPUS quyết định dữ liệu nào đáng được nhìn thấy trước.  
> Rule và schema buộc đầu ra đúng trường, đúng độ dài và có thể render.
