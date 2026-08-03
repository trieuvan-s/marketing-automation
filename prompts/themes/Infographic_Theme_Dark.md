<!--
NGUỒN GỐC: copy nguyên văn từ E:\content-rules\FVA_Infographic_Theme_Dark.md
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
theme_id: fva-dark-editorial
theme_name: "FVA Capital — Dark Editorial"
status: production
brand: "FVA Capital VN"
slogan: "Tăng Trưởng Bền Vững"
default_ratio: "4:5"
default_use: "Nội dung đại chúng, social media, video cover, infographic tin nhanh"
---

# FVA CAPITAL VN — DARK EDITORIAL THEME

## 1. Mục tiêu

Theme Dark là theme chính cho sản phẩm truyền thông đại chúng của FVA CAPITAL VN. Thiết kế phải tạo cảm giác mạnh, cao cấp, đáng tin cậy và nhận diện tốt trên màn hình điện thoại nhưng không biến thành dashboard dày đặc.

Nguyên tắc cốt lõi:

- Một hình chỉ truyền tải một luận điểm trung tâm.
- Ưu tiên số liệu và thông điệp, không trang trí để lấp chỗ trống.
- Hình ảnh phải thuộc thế giới thật, phù hợp trực tiếp với nội dung.
- Bố cục được chọn theo mật độ và cấu trúc dữ liệu, không cố định một mẫu chia đôi.
- Tối đa ba vùng thông tin lớn; duy trì khoảng thở rõ ràng.
- Dark Navy là nền chủ đạo; Gold chỉ dùng để dẫn mắt, không phủ rộng.

## 2. Trường hợp sử dụng

Phù hợp với:

- Bài đăng Facebook, LinkedIn, Telegram và các kênh social.
- Cover video, thumbnail, Shorts/Reels dạng tin tài chính.
- Infographic thị trường, vĩ mô, doanh nghiệp và chính sách.
- Nội dung cần gây chú ý nhanh trong newsfeed.

Không ưu tiên cho:

- Báo cáo dài cần đọc liên tục.
- Bảng số liệu nhiều dòng hoặc tài liệu cần in.
- Nội dung học thuật cần chú thích và trích dẫn dày.

## 3. Hệ màu

### 3.1. Design tokens

| Token | Mã màu | Vai trò |
| --- | --- | --- |
| `background.primary` | `#061521` | Nền chính |
| `background.secondary` | `#0C2232` | Panel hoặc vùng chuyển nhẹ |
| `text.primary` | `#F3EBDD` | Tiêu đề và số liệu chính |
| `text.secondary` | `#C8D0D4` | Nhãn, chú thích, nguồn |
| `accent.gold` | `#C9A14A` | Tối đa 1–2 điểm nhấn |
| `divider` | `#38505E` | Đường chia mảnh |
| `positive` | `#55A987` | Chỉ dùng khi ngữ nghĩa tăng/tích cực bắt buộc |
| `negative` | `#D26A66` | Chỉ dùng khi ngữ nghĩa giảm/cảnh báo bắt buộc |

### 3.2. Quy tắc màu

- Tổng diện tích Gold không vượt quá khoảng 10% thiết kế.
- Không dùng Gold cho mọi con số. Chỉ nhấn số liệu thuộc `priority.primary`.
- Màu xanh/đỏ chỉ được dùng khi cần biểu thị chiều tăng/giảm; không biến chúng thành màu theme.
- Không dùng neon, gradient nhiều màu hoặc hiệu ứng phát sáng.
- Gradient nếu có phải rất nhẹ, cùng họ Navy và không làm giảm độ đọc.

## 4. Typography

- Họ font ưu tiên: DIN Condensed, Bebas Neue, Anton, Montserrat ExtraBold hoặc sans-serif condensed tương đương.
- Tiêu đề: chữ hoa, đậm, canh trái, giãn dòng chặt.
- Subtitle và insight: ưu tiên kiểu câu để tiếng Việt dễ đọc; không bắt buộc viết hoa toàn bộ.
- Số liệu chính phải là phần tử lớn nhất hoặc lớn thứ hai sau headline.
- Chỉ dùng tối đa hai họ font và ba mức weight.
- Không co chữ quá nhỏ để ép đủ dữ liệu. Nếu thiếu chỗ, phải rút gọn hoặc đổi layout.
- Dấu tiếng Việt, dấu âm, dấu phần trăm, dấu gạch ngang và đơn vị phải được giữ chính xác.

### 4.1. Thứ bậc thị giác

1. `title` hoặc `hero.primary.value`.
2. `hero.primary.label` và subtitle.
3. Chỉ số hỗ trợ.
4. Highlights/insights.
5. Nguồn, ngày và thương hiệu.

## 5. Quy tắc hình ảnh thật

### 5.1. Yêu cầu bắt buộc

- Hình mô tả nội dung phải là ảnh chụp thực tế hoặc hình quang thực của vật thể, địa điểm, ngành nghề và hoạt động có tồn tại trong thế giới thật.
- Ưu tiên ảnh báo chí, ảnh doanh nghiệp, ảnh tư liệu hoặc stock photo có quyền sử dụng và có nguồn rõ ràng.
- Ảnh phải liên quan trực tiếp đến luận điểm; không dùng ảnh đẹp nhưng chỉ liên quan chung chung tới "tài chính".
- Chỉ dùng một ảnh chủ đạo hoặc một cụm ảnh có cùng bối cảnh. Không tạo collage hỗn tạp.
- Ảnh phải có chiều sâu, ít vật thể, chừa vùng âm để đặt chữ và chịu được crop 4:5.
- Với sự kiện, con người, doanh nghiệp hay địa điểm cụ thể: chỉ dùng ảnh thật đã xác minh; không dùng AI để dựng lại như bằng chứng báo chí.

### 5.2. Trường hợp dùng hình tạo sinh

Hình tạo sinh chỉ được dùng khi không có ảnh thật phù hợp và nội dung mang tính khái niệm hoặc bối cảnh chung. Khi đó:

- Bắt buộc đạt phong cách photorealistic; vật thể, tỷ lệ, ánh sáng và môi trường phải hợp lý.
- Không mô phỏng một sự kiện có thật, một nhân vật có thật hoặc một địa điểm cụ thể theo cách khiến người xem hiểu nhầm là ảnh tư liệu.
- Không tự thêm logo, tên doanh nghiệp, biển hiệu, người nổi tiếng hoặc nhãn sản phẩm.
- Không tạo số liệu, chữ, biểu đồ hoặc màn hình giả bên trong phần ảnh.
- Nếu hệ thống có metadata, đặt `visual_origin: ai_photorealistic` và không ghi nguồn ảnh như ảnh báo chí.

### 5.3. Các dạng hình bị cấm

- Icon hoạt hình, vector minh họa, 3D cartoon hoặc nhân vật mascot làm hình chính.
- Bắt tay doanh nhân chung chung, đồng xu bay, mũi tên phát sáng và các stock cliché không gắn với nội dung.
- Ảnh có logo hoặc biển hiệu không xuất hiện trong dữ liệu đầu vào.
- Ảnh gây hiểu nhầm về quy mô, địa điểm, nhân vật hoặc sự kiện.
- Ảnh mờ, quá nhiều chi tiết hoặc không có vùng đặt chữ.

### 5.4. Metadata ảnh đầu vào khuyến nghị

```yaml
visual:
  mode: real_photo # real_photo | ai_photorealistic
  subject: "Mô tả chủ thể ảnh"
  relation_to_story: "Ảnh liên quan thế nào tới luận điểm"
  source_name: "Tên nguồn hoặc null"
  source_url: "URL hoặc null"
  license_status: "owned | licensed | editorial | unknown"
  verified_entity: true
  allow_logo: false
  crop_safe: true
```

Nếu `license_status: unknown`, hệ thống phải chuyển sang hàng đợi kiểm duyệt thay vì tự động xuất bản.

## 6. Đánh giá mức độ giàu thông tin

Tính `information_score` trước khi chọn bố cục:

```text
information_score =
  hero_count × 2
  + metric_count
  + highlight_count
  + comparison_group_count × 2
  + timeline_point_count
```

| Mức | Điều kiện tham khảo | Mục tiêu thiết kế |
| --- | --- | --- |
| `low` | `0–6` điểm | Poster giàu hình ảnh, một số liệu hoặc thông điệp lớn |
| `medium` | `7–12` điểm | Cân bằng ảnh và dữ liệu; tối đa 2–3 cụm số liệu |
| `high` | `13–20` điểm | Data-first, ảnh giảm diện tích nhưng vẫn hiện diện |
| `overflow` | Trên `20` điểm | Không ép vào một ảnh; tách carousel/series hoặc giảm dữ liệu |

Điểm số là gợi ý. Cấu trúc dữ liệu — so sánh, diễn tiến thời gian, xếp hạng — có quyền ưu tiên hơn tổng điểm.

## 7. Bộ chọn bố cục linh hoạt

### `D1 — Editorial Hero`

Áp dụng cho `low`: một headline, một hero number, tối đa hai supporting metrics.

- Ảnh thật có thể chiếm 50–70% diện tích.
- Chữ đặt ở vùng âm hoặc trong panel Navy.
- Không bắt buộc chia trái/phải; có thể dùng ảnh tràn nền với overlay tối.

### `D2 — Asymmetric Split`

Áp dụng cho `low–medium` khi ảnh và câu chuyện có vai trò ngang nhau.

- Tỷ lệ linh hoạt 40/60, 45/55 hoặc 55/45.
- Có thể chia dọc, chéo hoặc theo block bất đối xứng.
- Không lặp lại cùng một tỷ lệ cho mọi sản phẩm.

### `D3 — Data Rail + Photo`

Áp dụng cho `medium`: 3–6 chỉ số có thứ tự rõ.

- Một rail số liệu dọc hoặc ngang; ảnh thật giữ 35–50% diện tích.
- Mỗi metric chỉ gồm value + label ngắn.
- Dùng đường chia mảnh, không dùng card bo tròn dày đặc.

### `D4 — Modular Data Grid`

Áp dụng cho `high`: nhiều số liệu nhưng vẫn có một luận điểm chính.

- Lưới bất đối xứng 2 cột hoặc 3 module lớn; không dùng lưới card đồng đều kiểu dashboard.
- Ảnh thật xuất hiện trong một module lớn, chiếm tối thiểu 25% diện tích.
- Hero metric phải lớn hơn rõ rệt các metric còn lại.

### `D5 — Comparison`

Áp dụng khi có hai nhóm, hai kỳ hoặc hai kịch bản.

- Chia 2 vế rõ ràng theo cùng thang đo.
- Một ảnh thật trung tính có thể đặt giữa, trên hoặc làm nền mờ.
- Không dùng kích thước thị giác gây hiểu sai tỷ lệ dữ liệu.

### `D6 — Timeline / Flow`

Áp dụng khi điểm chính là diễn biến theo thời gian hoặc chuỗi nguyên nhân–kết quả.

- Tối đa 4 mốc trên một ảnh.
- Dùng một trục đơn giản; ảnh thật làm anchor tại mốc hoặc phần kết.
- Nếu trên 4 mốc, chuyển sang carousel.

### Logic chọn tự động

```text
IF comparison_group_count >= 2      -> D5
ELSE IF timeline_point_count >= 2   -> D6
ELSE IF information_score <= 6      -> D1 hoặc D2
ELSE IF information_score <= 12     -> D2 hoặc D3
ELSE IF information_score <= 20     -> D4
ELSE                                -> SPLIT_TO_CAROUSEL
```

Trong trường hợp có nhiều lựa chọn, ưu tiên layout tạo được vùng âm lớn và không làm chữ đè lên chủ thể ảnh.

## 8. Xử lý nội dung trước khi render

- Không sửa số liệu, đơn vị, chiều tăng/giảm hoặc ý nghĩa của dữ liệu gốc.
- `priority.primary`: tối đa 2 mục, được dùng Gold và kích thước lớn.
- `priority.secondary`: hiển thị ở cấp độ metric hỗ trợ.
- `priority.minor`: chỉ hiển thị nếu còn đủ khoảng thở; nếu không, loại khỏi ảnh.
- Highlight dài phải được biên tập thành một câu ngắn, không làm thay đổi nội dung.
- Không lặp cùng số liệu trong headline và hero block nếu sự lặp lại không tạo thêm giá trị.
- Nếu dữ liệu vượt ngưỡng, ưu tiên tách carousel theo thứ tự: cover → dữ liệu → luận điểm → kết luận/nguồn.

## 9. Thành phần thương hiệu

- Logo hoặc wordmark đặt nhỏ ở góc có vùng âm; không bắt buộc cố định góc phải.
- Slogan chỉ dùng khi đủ không gian và không cạnh tranh với nguồn.
- Ngày xuất bản dùng định dạng `DD/MM/YYYY` và lấy theo ngày render thực tế.
- Nguồn dữ liệu đặt ở footer, dễ đọc nhưng không nổi hơn nội dung.
- Không tự tạo logo mới. Nếu không có asset logo chính thức, dùng wordmark chữ `FVA CAPITAL VN`.

## 10. Prompt khung cho hệ thống tạo ảnh

```text
Thiết kế một financial editorial poster theo theme FVA Capital VN Dark.
Tỷ lệ: {{ratio | default: 4:5}}.
Mục tiêu: truyền tải duy nhất luận điểm {{core_message}}.
Mức độ thông tin: {{information_level}}.
Bố cục được chọn: {{layout_id}}; được phép điều chỉnh tỷ lệ vùng để giữ khoảng thở.

Nền Deep Navy (#061521), chữ off-white (#F3EBDD), Gold (#C9A14A)
chỉ nhấn tối đa hai dữ liệu thuộc priority.primary. Typography condensed
sans-serif đậm, headline chữ hoa, canh trái, phân cấp rõ, dễ đọc trên mobile.

Hình ảnh: {{visual.subject}}. Bắt buộc dùng ảnh chụp thật đã xác minh; nếu
visual.mode=ai_photorealistic thì chỉ tạo bối cảnh chung có thật, quang thực,
không giả làm ảnh tư liệu. Không tự thêm người, logo, tên doanh nghiệp, biển
hiệu, chữ hoặc sự kiện không có trong input. Ảnh phải liên quan trực tiếp tới
nội dung, ít vật thể, có chiều sâu và có vùng âm phù hợp với bố cục.

Giữ nguyên chính xác toàn bộ số liệu và dấu tiếng Việt:
Title: {{title}}
Subtitle: {{subtitle}}
Hero: {{hero}}
Metrics: {{market}}
Highlights đã rút gọn: {{highlights_compact}}
Nguồn: {{source}}
Ngày: {{render_date_ddmmyyyy}}
Thương hiệu: FVA CAPITAL VN

Tránh: dashboard chật, nhiều card nhỏ, neon, icon hoạt hình, stock cliché,
logo giả, số liệu bịa, chữ thừa, chữ sai dấu, ảnh không liên quan và hiệu ứng rực.
```

## 11. Kiểm tra chất lượng trước khi xuất bản

### Dữ liệu

- [ ] Tất cả số liệu khớp input.
- [ ] Không thiếu hoặc sai đơn vị.
- [ ] Không lặp dữ liệu vô ích.
- [ ] Nguồn và ngày hiển thị đúng.

### Hình ảnh

- [ ] Là ảnh thật đã xác minh hoặc hình quang thực đúng điều kiện fallback.
- [ ] Liên quan trực tiếp tới nội dung.
- [ ] Không có logo, người hoặc doanh nghiệp ngoài input.
- [ ] Không tạo cảm giác đây là ảnh tư liệu nếu thực chất là ảnh AI.
- [ ] Có quyền sử dụng hoặc đã chuyển qua kiểm duyệt.

### Thiết kế

- [ ] Chỉ có một trọng tâm chính.
- [ ] Gold không vượt vai trò điểm nhấn.
- [ ] Bố cục phù hợp mật độ dữ liệu.
- [ ] Không quá ba vùng thông tin lớn.
- [ ] Đọc được ở kích thước màn hình điện thoại.
- [ ] Không có chữ lỗi, chữ giả hoặc vật thể méo.

## 12. Điều kiện từ chối render tự động

Hệ thống phải dừng hoặc chuyển Human Review khi:

- Không xác minh được ảnh của nhân vật/sự kiện/doanh nghiệp cụ thể.
- Nguồn ảnh hoặc quyền sử dụng không rõ.
- Dữ liệu mâu thuẫn, thiếu đơn vị hoặc thiếu nguồn.
- `information_score > 20` nhưng output chỉ cho phép một ảnh.
- Tên thương hiệu, con người hoặc địa điểm trong ảnh không khớp input.
- Công cụ tạo ảnh làm sai số liệu hoặc tiếng Việt sau tối đa một lần sửa.
