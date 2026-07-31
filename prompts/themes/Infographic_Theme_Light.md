<!--
NGUỒN GỐC: copy nguyên văn từ E:\content-rules\FVA_Infographic_Theme_Light.md
(thư mục content-rules/, SIBLING với marketing-automation, KHÔNG theo git —
xem docs/VPS_MIGRATION_BACKLOG.md). Ngày copy: 2026-07-21, nhánh
feature/infographic-hybrid, để đưa Theme-rules vào version control (tránh
mất khi đổi máy/lên VPS -- CÙNG LỚP LỖI với data_root trước khi hợp nhất).
KHÔNG sửa nội dung khi copy -- nếu content-rules/ gốc cập nhật, copy lại
NGUYÊN VĂN + cập nhật ngày ở header này, không tự ý diễn giải lại.
-->

---
schema_name: fva_capital_visual_theme
schema_version: "1.0"
theme_id: fva-light-research
theme_name: "FVA Capital — Light Research"
status: production
brand: "FVA Capital VN"
slogan: "Tăng Trưởng Bền Vững"
default_ratio: "4:5"
default_use: "Research, báo cáo, bài phân tích, nội dung giáo dục và tài liệu cần đọc lâu"
---

# FVA CAPITAL — LIGHT RESEARCH THEME

## 1. Mục tiêu

Theme Light là theme phụ dành cho research, báo cáo và nội dung phân tích của FVA CAPITAL VN. Thiết kế phải sáng, sạch, dễ đọc lâu và mang tinh thần Financial Times hiện đại mà không mô phỏng nguyên xi bất kỳ ấn phẩm nào.

Nguyên tắc cốt lõi:

- Một hình có một kết luận trung tâm, dù chứa nhiều dữ liệu hỗ trợ.
- Nền Ivory tạo cảm giác biên tập và giảm độ chói so với trắng thuần.
- Hình ảnh phải thuộc thế giới thật, chính xác với nội dung và không mang tính trang trí chung chung.
- Bố cục thay đổi theo cấu trúc và mật độ dữ liệu; không khóa vào mẫu 45/55.
- Tối đa ba vùng thông tin lớn; sử dụng đường kẻ và khoảng trắng thay cho nhiều card.
- Gold chỉ làm dấu nhấn; Charcoal là màu đọc chính.

## 2. Trường hợp sử dụng

Phù hợp với:

- Báo cáo vĩ mô, ngành và doanh nghiệp.
- Bài phân tích dài, nội dung giáo dục tài chính.
- Infographic cần đọc và lưu lại.
- Tài liệu trình bày với khách hàng hoặc dùng trong research nội bộ.
- Ấn phẩm có khả năng được in hoặc chuyển sang PDF.

Không ưu tiên cho:

- Thumbnail cần tương phản cực mạnh trong newsfeed.
- Nội dung cảnh báo khẩn cấp hoặc video cover có nền tối thống nhất.
- Dashboard vận hành thời gian thực.

## 3. Hệ màu

### 3.1. Design tokens

| Token | Mã màu | Vai trò |
| --- | --- | --- |
| `background.primary` | `#F6F0E5` | Nền Ivory chính |
| `background.secondary` | `#ECE8E0` | Vùng dữ liệu phụ |
| `text.primary` | `#1F1F1F` | Tiêu đề, số liệu, nội dung |
| `text.secondary` | `#60676B` | Nhãn, chú thích, nguồn |
| `accent.gold` | `#C9A14A` | Tối đa 1–2 điểm nhấn |
| `divider` | `#D3CBC0` | Đường chia mảnh |
| `positive` | `#3E8068` | Chỉ dùng khi cần ngữ nghĩa tích cực |
| `negative` | `#A94F4B` | Chỉ dùng khi cần ngữ nghĩa tiêu cực |

### 3.2. Quy tắc màu

- Không dùng nền trắng tinh trên toàn thiết kế; ưu tiên Ivory ấm.
- Charcoal phải chiếm phần lớn typography.
- Gold không vượt khoảng 8% diện tích và chỉ nhấn `priority.primary`.
- Xanh/đỏ dùng tiết chế cho chiều dữ liệu; luôn kèm ký hiệu hoặc nhãn, không dựa duy nhất vào màu.
- Không dùng drop shadow nặng, glow hoặc gradient màu rực.

## 4. Typography

- Headline: DIN Condensed, Bebas Neue, Anton, Montserrat ExtraBold hoặc sans-serif condensed tương đương.
- Nội dung và chú thích: Inter, Source Sans, Montserrat hoặc sans-serif dễ đọc.
- Tiêu đề có thể viết hoa; subtitle, insight và chú thích ưu tiên kiểu câu.
- Số liệu chính dùng cỡ lớn, nhưng không áp đảo hoàn toàn tiêu đề nghiên cứu.
- Tối đa hai họ font, ba mức weight và bốn kích thước chữ chính.
- Không giảm font dưới ngưỡng đọc mobile để chứa thêm nội dung.
- Giữ tuyệt đối dấu tiếng Việt, dấu thập phân, dấu phần trăm, dấu âm và đơn vị.

### 4.1. Thứ bậc thị giác

1. Kết luận/headline.
2. Hero metric hoặc biểu đồ chính.
3. Các chỉ số và luận cứ hỗ trợ.
4. Giải thích, chú thích và phương pháp.
5. Nguồn, ngày và thương hiệu.

## 5. Quy tắc hình ảnh thật

### 5.1. Yêu cầu bắt buộc

- Hình mô tả phải là ảnh chụp thực tế hoặc hình quang thực của chủ thể có tồn tại ngoài đời.
- Ưu tiên ảnh báo chí, ảnh doanh nghiệp công bố, ảnh tư liệu hoặc stock photo có quyền sử dụng và metadata nguồn.
- Ảnh phải giúp người đọc hiểu ngành, doanh nghiệp, tài sản, hoạt động sản xuất hoặc bối cảnh chính sách; không dùng ảnh chỉ để làm đẹp.
- Với nhân vật, sự kiện, doanh nghiệp, dự án và địa điểm cụ thể: chỉ dùng ảnh thật đã xác minh.
- Ảnh phải đủ sáng, màu trung tính, chi tiết sạch và có vùng crop phù hợp.
- Không dùng quá một ảnh chính; ảnh thứ hai chỉ được phép khi layout Comparison thực sự cần đối chiếu hai đối tượng.

### 5.2. Trường hợp dùng hình tạo sinh

Chỉ cho phép khi không có ảnh thật phù hợp và bối cảnh mang tính khái niệm chung:

- Hình phải photorealistic, ánh sáng tự nhiên, vật liệu và tỷ lệ hợp lý.
- Không dựng lại sự kiện có thật hoặc nhân vật có thật như ảnh báo chí.
- Không tự thêm logo, tên công ty, biển hiệu, nhãn hàng, màn hình dữ liệu hoặc văn bản.
- Không gắn nguồn báo chí cho hình AI; nếu có metadata, dùng `visual_origin: ai_photorealistic`.
- Hình AI không được dùng để chứng minh một luận điểm thực chứng.

### 5.3. Các dạng hình bị cấm

- Minh họa vector, cartoon, icon 3D và mascot làm hình chính.
- Hình stock cliché như bắt tay, tiền xu bay, biểu đồ phát sáng hoặc người chỉ vào màn hình vô nghĩa.
- Ảnh có thương hiệu không xuất hiện trong dữ liệu đầu vào.
- Ảnh AI mô phỏng phát biểu, cuộc họp, nhà máy hoặc sự kiện cụ thể.
- Collage nhiều ảnh không có quan hệ kể chuyện rõ ràng.

### 5.4. Metadata ảnh đầu vào khuyến nghị

```yaml
visual:
  mode: real_photo # real_photo | ai_photorealistic
  subject: "Mô tả chủ thể ảnh"
  relation_to_story: "Vai trò của ảnh trong luận điểm"
  source_name: "Tên nguồn hoặc null"
  source_url: "URL hoặc null"
  license_status: "owned | licensed | editorial | unknown"
  verified_entity: true
  allow_logo: false
  crop_safe: true
```

Nếu `license_status: unknown`, không tự động xuất bản.

## 6. Đánh giá mức độ giàu thông tin

```text
information_score =
  hero_count × 2
  + metric_count
  + highlight_count
  + comparison_group_count × 2
  + timeline_point_count
  + chart_count × 2
```

| Mức | Điều kiện tham khảo | Mục tiêu thiết kế |
| --- | --- | --- |
| `low` | `0–6` điểm | Editorial poster sáng, ảnh lớn, một kết luận |
| `medium` | `7–13` điểm | Cân bằng ảnh, số liệu và giải thích |
| `high` | `14–22` điểm | Research card/data-first, ảnh làm neo ngữ cảnh |
| `overflow` | Trên `22` điểm | Tách carousel, nhiều trang hoặc báo cáo PDF |

Theme Light chịu được nhiều thông tin hơn Dark nhờ nền sáng, nhưng không được lợi dụng điều này để thu nhỏ chữ hoặc xóa khoảng trắng.

## 7. Bộ chọn bố cục linh hoạt

### `L1 — Editorial Cover`

Áp dụng cho `low`: một kết luận, một hero number, tối đa hai số liệu phụ.

- Ảnh thật chiếm 45–65% hoặc làm dải ảnh trên/dưới.
- Nội dung nằm trên nền Ivory, không đặt chữ dài trực tiếp lên vùng ảnh phức tạp.
- Có thể bố trí dọc, ngang, lệch tâm hoặc split; không cố định 45/55.

### `L2 — Research Brief`

Áp dụng cho `medium`: headline + 3–6 chỉ số + tối đa ba insight.

- Header gọn, một cụm ảnh thật, một vùng metrics và một vùng takeaway.
- Sử dụng đường kẻ mảnh; tránh nhiều card bo tròn.
- Ảnh có thể đặt ở đầu, giữa hoặc cạnh bên tùy vùng âm.

### `L3 — Asymmetric Data Grid`

Áp dụng cho `medium–high` khi các metric có mức ưu tiên khác nhau.

- Lưới 2 cột bất đối xứng hoặc một module lớn + 2–4 module nhỏ.
- Hero metric chiếm module lớn nhất.
- Ảnh thật nằm trong một module riêng, chiếm tối thiểu 20–30% diện tích.

### `L4 — Chart-led Research`

Áp dụng khi dữ liệu có chuỗi thời gian, cơ cấu hoặc tương quan và biểu đồ giúp hiểu tốt hơn văn bản.

- Chỉ dùng một biểu đồ chính và tối đa hai callout.
- Ảnh thật dùng như dải context nhỏ hoặc cover crop, không cạnh tranh với chart.
- Trục, nhãn và chú thích phải chính xác; không dùng chart trang trí.

### `L5 — Comparison`

Áp dụng cho hai kỳ, hai doanh nghiệp, hai ngành hoặc hai kịch bản.

- Hai vế dùng cùng thang đo và hệ phân cấp.
- Có thể dùng một ảnh trung tính hoặc hai ảnh thật đã xác minh, crop tương đương.
- Không dùng diện tích hình học để phóng đại chênh lệch không đúng tỷ lệ.

### `L6 — Timeline / Thesis Flow`

Áp dụng cho diễn tiến thời gian, chuỗi chính sách hoặc logic luận điểm.

- Tối đa 5 mốc ngắn trên theme Light.
- Dùng một trục hoặc flow đơn giản, không tạo sơ đồ mạng phức tạp.
- Ảnh thật làm neo ở điểm bắt đầu, kết thúc hoặc vùng kết luận.

### `L7 — Quote + Evidence`

Áp dụng khi có một nhận định quan trọng cần đi kèm dữ liệu kiểm chứng.

- Quote/kết luận không vượt 25–30 từ.
- Evidence gồm tối đa bốn metric hoặc một chart.
- Ảnh người phát biểu chỉ được dùng khi đã xác minh đúng người, đúng ngữ cảnh và có quyền sử dụng.

### Logic chọn tự động

```text
IF has_quote AND (metric_count > 0 OR chart_count > 0) -> L7
ELSE IF comparison_group_count >= 2                    -> L5
ELSE IF timeline_point_count >= 2                      -> L6
ELSE IF chart_count >= 1                               -> L4
ELSE IF information_score <= 6                         -> L1
ELSE IF information_score <= 13                        -> L2 hoặc L3
ELSE IF information_score <= 22                        -> L3
ELSE                                                   -> SPLIT_TO_SERIES_OR_REPORT
```

Khi hai layout cùng phù hợp, chọn layout có ít vùng hơn, font lớn hơn và không che chủ thể ảnh.

## 8. Xử lý nội dung trước khi render

- Giữ nguyên số liệu, đơn vị, dấu và ngữ nghĩa đầu vào.
- `priority.primary`: tối đa 2 mục, dùng Gold hoặc kích thước lớn.
- `priority.secondary`: hiển thị bằng Charcoal ở cấp metric hỗ trợ.
- `priority.minor`: chuyển sang chú thích hoặc loại khỏi ảnh nếu làm bố cục chật.
- Highlights phải được rút gọn thành các takeaway độc lập, tránh câu dài nhiều mệnh đề.
- Nếu có biểu đồ, không lặp toàn bộ số liệu của biểu đồ thành các card riêng.
- Khi vượt ngưỡng, tách thành cover → evidence → interpretation → conclusion/source.

## 9. Biểu đồ và bảng dữ liệu

- Chỉ dùng biểu đồ khi thể hiện xu hướng, so sánh, cơ cấu hoặc tương quan rõ hơn văn bản.
- Tối đa một biểu đồ chính trên một ảnh 4:5.
- Không dùng 3D chart, pie chart quá năm lát hoặc trục bị cắt gây hiểu sai.
- Bảng chỉ nên có tối đa 5 dòng và 4 cột trong một ảnh social.
- Số liệu trong chart/bảng phải xuất phát trực tiếp từ payload; không nội suy nếu không được yêu cầu.
- Ghi chú phương pháp hoặc kỳ dữ liệu khi cần để tránh hiểu sai.

## 10. Thành phần thương hiệu

- Logo hoặc wordmark nhỏ, đặt ở vùng âm phù hợp; không bắt buộc một góc cố định.
- Nếu thiếu asset logo, dùng chữ `FVA CAPITAL`; không tạo biểu tượng rùa mới.
- Slogan chỉ xuất hiện trên cover hoặc trang kết, không lặp ở mọi card.
- Ngày render dùng `DD/MM/YYYY` theo thời gian thực.
- Nguồn đặt ở footer; với research có thể thêm kỳ dữ liệu hoặc chú thích phương pháp.

## 11. Prompt khung cho hệ thống tạo ảnh

```text
Thiết kế một financial research poster theo theme FVA Capital VN Light.
Tỷ lệ: {{ratio | default: 4:5}}.
Luận điểm trung tâm: {{core_message}}.
Mức độ thông tin: {{information_level}}.
Bố cục: {{layout_id}}, được phép thay đổi vị trí ảnh và khối dữ liệu để tối ưu
khả năng đọc; không khóa vào bố cục chia đôi.

Nền Ivory (#F6F0E5), chữ Charcoal (#1F1F1F), Gold (#C9A14A) chỉ nhấn
tối đa hai dữ liệu primary. Phong cách tối giản, biên tập cao cấp, nhiều khoảng
trắng, đường chia mảnh, không dùng nhiều card hoặc shadow nặng.

Hình ảnh: {{visual.subject}}. Bắt buộc ưu tiên ảnh thật đã xác minh và có quyền
sử dụng. Nếu visual.mode=ai_photorealistic, chỉ tạo bối cảnh chung có thật,
quang thực, không giả làm ảnh báo chí và không tự thêm người, logo, thương hiệu,
biển hiệu, chữ hoặc sự kiện. Ảnh phải giải thích trực tiếp nội dung, không chỉ
làm nền trang trí.

Giữ nguyên chính xác dữ liệu và tiếng Việt:
Title: {{title}}
Subtitle: {{subtitle}}
Hero: {{hero}}
Metrics: {{market}}
Highlights đã rút gọn: {{highlights_compact}}
Chart data: {{chart_data | optional}}
Nguồn: {{source}}
Ngày: {{render_date_ddmmyyyy}}
Thương hiệu: FVA Capital VN

Tránh: nền trắng lạnh, dashboard chật, nhiều card đều nhau, icon hoạt hình,
stock cliché, logo giả, ảnh AI giả tư liệu, chart 3D, chữ sai dấu, số liệu bịa,
ảnh không liên quan và hiệu ứng rực.
```

## 12. Kiểm tra chất lượng trước khi xuất bản

### Dữ liệu

- [ ] Số liệu, đơn vị, kỳ dữ liệu và chiều tăng/giảm khớp input.
- [ ] Chart/bảng không làm sai tỷ lệ.
- [ ] Không lặp evidence không cần thiết.
- [ ] Nguồn, ngày và chú thích phương pháp đầy đủ.

### Hình ảnh

- [ ] Ảnh thật đã được xác minh hoặc là fallback quang thực đúng điều kiện.
- [ ] Ảnh hỗ trợ trực tiếp luận điểm.
- [ ] Không có người, logo, doanh nghiệp hoặc địa điểm ngoài input.
- [ ] Không gắn nhãn ảnh báo chí cho hình AI.
- [ ] Quyền sử dụng đã rõ hoặc đã chuyển Human Review.

### Thiết kế

- [ ] Có một kết luận trung tâm rõ ràng.
- [ ] Nền Ivory, chữ Charcoal và Gold được dùng đúng tỷ lệ.
- [ ] Layout phù hợp cấu trúc dữ liệu, không mặc định split 45/55.
- [ ] Không quá ba vùng thông tin lớn.
- [ ] Font đủ lớn để đọc trên mobile.
- [ ] Khoảng trắng đủ và không có card/icon thừa.
- [ ] Không có chữ lỗi, vật thể méo hoặc chi tiết AI bất thường.

## 13. Điều kiện từ chối render tự động

Hệ thống phải dừng hoặc chuyển Human Review khi:

- Ảnh nhân vật, sự kiện, doanh nghiệp hoặc dự án cụ thể chưa được xác minh.
- Nguồn ảnh/quyền sử dụng là `unknown`.
- Dữ liệu thiếu nguồn, kỳ dữ liệu, đơn vị hoặc có mâu thuẫn.
- `information_score > 22` nhưng chỉ cho phép một ảnh.
- Chart không đủ dữ liệu để thiết lập đúng trục hoặc thang đo.
- Công cụ tự thêm logo, tên doanh nghiệp hoặc nội dung ngoài payload.
- Công cụ làm sai số liệu hoặc dấu tiếng Việt sau tối đa một lần sửa.
