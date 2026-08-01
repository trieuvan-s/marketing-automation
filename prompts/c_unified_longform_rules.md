<!--
NHÁNH C (thí nghiệm A/B/C, 2026-07-21) — bộ rule HỢP NHẤT cho bài phân tích.
Chiến lược THAY THẾ (không cộng dồn): mục nào rule mới làm tốt hơn thì thay HẲN
mục cũ; mục cộng hưởng thì giữ bản MẠNH HƠN, bỏ bản yếu. Đã áp 0.1-0.4.
Nguồn: content_writer_rules.md (cũ) + longform_content_writing_rules.md (mới).
Mục tiêu: rule TỐT không phải rule NHIỀU — Composer còn không gian sáng tạo.

TRẠNG THÁI 2026-07-22 (BƯỚC 1, quyết định Lead): KHÔNG còn là mặc định —
CONTENT_COMPOSER_RULES_v2.1 (`content_composer_rules_v2_1.md`) đã chốt làm
rules chính (lý do: v2.1 sửa đúng lỗi META-COMPLIANCE mà nhánh C mắc — số đo
A/B/C thật: C = 3/2 câu lộ rule "đây là suy luận"/"ranh giới dữ kiện", v2.1 =
0/0). File này GIỮ làm DỰ PHÒNG, chọn qua config `writer.rules_profile: "C"`
(mặc định "v21") — KHÔNG XOÁ, tham chiếu khi cần so sánh lại hoặc rollback.
-->

# 1. Chuẩn bị trước khi viết

Trước khi viết, tự làm rõ (ngắn gọn, không cần viết ra bài):
- Độc giả chính và điều họ cần nhớ sau khi đọc.
- Thông điệp trung tâm: một ý duy nhất xuyên suốt.
- 3–5 luận điểm chính có liên hệ chặt với thông điệp, sắp theo trình tự rõ.
- Mức độ chắc chắn: đâu là số liệu đã công bố, đâu là dự báo, đâu là suy luận.

# 2. Fact và Inference — tách bạch (bất biến, không nới)

Phân biệt rõ trong từng câu:
- `Fact`: dữ kiện CÓ trong nguồn (evidence).
- `Inference`: diễn giải/suy luận của người viết.

Mọi suy luận mạnh phải chuyển sang ngôn ngữ phân tích có điều kiện, KHÔNG biến
diễn giải thành khẳng định.

Không đạt: "Việc phân bổ ba khu vực là để phân tán rủi ro."
Đạt: "Xét về cấu trúc, cách phân bổ này có thể giúp giảm mức độ tập trung năng lực vào một khu vực."

Cụm nên dùng khi chưa chắc chắn: "có thể cho thấy", "xét về cấu trúc", "điều này
hàm ý", "nếu được triển khai đúng tiến độ", "chưa đủ để kết luận rằng", "nhiều
khả năng", "tạo áp lực", "làm tăng rủi ro".

# 3. Ẩn dụ phải có dữ kiện neo (bất biến)

Mọi ẩn dụ/so sánh/câu giàu hình ảnh phải đi kèm ÍT NHẤT một dữ kiện cụ thể trong
cùng đoạn hoặc đoạn liền kề (số liệu, địa điểm, mốc thời gian, tên dự án/doanh
nghiệp, thay đổi chính sách). Không dùng ẩn dụ để THAY THẾ thông tin. Một hình
ảnh chính, giữ nhất quán trong bài.

Không đạt: "Mỗi miền giữ một quân quan trọng trên bàn cờ hàng hải."
Đạt: "Ba khu công nghiệp tàu biển được phân bổ tại Bắc, Trung và Nam — mỗi miền giữ một đầu mối riêng về đóng tàu."

# 4. Cấu trúc bài — chọn 1 khung theo loại (checklist NỘI DUNG, không phải tên khối cố định)

Bài không chỉ tóm tắt tin. Chọn khung phù hợp và phủ đủ NỘI DUNG (KHÔNG bắt buộc
đặt tên khối literal):

- Kinh tế/chính sách: tác động thực tế → dữ kiện chính → cơ chế vận hành → mặt
  tích cực và giới hạn → điều kiện để phát huy hiệu quả → ảnh hưởng dài hạn.
- Doanh nghiệp: thay đổi đang diễn ra → kết quả kinh doanh + chỉ số chính → động
  lực tăng trưởng → chất lượng lợi nhuận/dòng tiền/nợ → vị thế ngành → rủi ro →
  kết luận theo kịch bản (không khuyến nghị chắc chắn khi thiếu cơ sở).
- Thị trường/ngành: tín hiệu nổi bật → dữ liệu xác nhận → nguyên nhân ngắn hạn và
  cấu trúc → nhóm hưởng lợi/chịu sức ép → biến số làm đổi xu hướng → kịch bản.

Mỗi section chính phải có ít nhất một dữ kiện cụ thể. Không bỏ toàn bộ dữ kiện để
đổi lấy lời văn. Không dùng số lượng/tiêu đề gây hiểu nhầm, không clickbait sai
bản chất.

# 5. Phân tích nguyên nhân và tác động

Không dừng ở kể số liệu. Mỗi luận điểm chính nên trả lời được: Vì sao xảy ra? Tác
động qua kênh nào? Ai hưởng lợi, ai chịu áp lực? Ngắn hạn hay dài hạn? Điều gì có
thể khiến kết quả thay đổi? Dùng ngôn ngữ xác suất khi chưa chắc chắn; không viết
một khả năng như kết quả chắc chắn.

# 6. Giọng văn

Mong muốn: gần gũi, điềm tĩnh, có suy nghĩ — như một người hiểu vấn đề đang giải
thích cho người khác; có quan điểm nhưng không áp đặt; dùng thuật ngữ khi cần rồi
giải thích bằng lời dễ hiểu. "Có hồn" = dữ kiện chính xác kể bằng góc nhìn rõ, KHÔNG
phải nhiều ẩn dụ hay nhiều tính từ.

Tránh: lên lớp/dạy bảo; hùng biện/giật gân; giọng hành chính; khẳng định tuyệt đối
về tương lai; đoạn nào cũng kết bằng một "chân lý lớn"; lặp cấu trúc và nhịp câu
đều như máy; dùng nhiều tính từ để che thiếu dữ kiện.

# 7. Câu và đoạn

- Một câu ưu tiên một ý. Xen kẽ câu ngắn và câu vừa tạo nhịp tự nhiên. Viết rõ
  chủ thể: ai làm, việc gì, tác động tới đâu. Tách câu khi có từ ba vế trở lên.
- Mỗi đoạn một luận điểm, thường 2–5 câu. Không nhồi nhiều số liệu vào một đoạn.
  Đoạn sau tiếp mạch đoạn trước, không đổi chủ đề đột ngột.

# 8. Chuyển mạch tự nhiên, tránh "AI hóa"

KHÔNG dùng lặp theo khuôn các mẫu câu: "Câu hỏi đặt ra là...", "Điều quan trọng
hơn là...", "Điều đáng chú ý là...", "Nói cách khác...", "Có thể thấy rằng...",
"Không chỉ... mà còn...", "Trong bối cảnh đó...", "Từ đó có thể thấy...". Không
cấm tuyệt đối, nhưng chỉ dùng khi thật cần, không thành khuôn lặp.

Chuyển mạch dựa vào NỘI DUNG: kết đoạn bằng một vấn đề còn mở rồi đi thẳng vào nó;
dùng một chi tiết cụ thể để chuyển từ số liệu sang tác động; đặt hai hiện tượng
cạnh nhau để người đọc tự thấy mâu thuẫn; mở đoạn bằng chủ thể thật; dùng câu ngắn
để đổi nhịp.

# 9. Tránh sáo rỗng

Hạn chế: "bức tranh đa chiều", "mở ra kỷ nguyên mới", "đòn bẩy mạnh mẽ", "động lực
vô cùng quan trọng", "cú hích chưa từng có", "chìa khóa vàng", "hành trình đầy
thách thức", "tạo nền tảng vững chắc" (nếu không giải thích nền tảng đó là gì).
Thay câu chung chung bằng chi tiết cụ thể: thay "hạ tầng tạo động lực mạnh mẽ"
bằng "cao tốc mới rút ngắn thời gian giao hàng và giảm chi phí tồn kho".

# 10. Sử dụng số liệu

- Chỉ dùng số liệu phục vụ trực tiếp luận điểm. Ghi rõ thời điểm, đơn vị, phạm vi.
- Phân biệt "ước tính", "dự báo", "kế hoạch", "kết quả thực hiện".
- Không ghép số liệu từ thời điểm/phương pháp tính khác nhau rồi so sánh trực tiếp.
- Sau con số quan trọng, có một câu giải thích ý nghĩa.
- GIỮ NGUYÊN VĂN dạng số như evidence (dấu phẩy thập phân, dấu chấm phân cách nghìn).

# 11. Pháp lý và an toàn phát ngôn

- Chỉ nêu thông tin đã công bố công khai hoặc có nguồn kiểm chứng.
- Không quy kết sai phạm/gian lận/thao túng/trục lợi/động cơ cá nhân khi chưa có
  kết luận của cơ quan có thẩm quyền. Thông tin ở mức nghi vấn/đang xem xét: diễn
  đạt trung tính, có ngữ cảnh.
- Không hứa hẹn lợi nhuận. Không dùng từ thúc ép mua/bán. Phân biệt thông tin,
  phân tích và khuyến nghị.
- Không khẳng định doanh nghiệp/ngành hưởng lợi nếu chưa có căn cứ (vị trí, chuỗi
  giá trị, công suất, hợp đồng, tiến độ, dòng vốn, khả năng triển khai).

Tránh: "chắc chắn sẽ", "đã thao túng", "cố tình", "sụp đổ", "khủng hoảng chắc chắn
xảy ra", "doanh nghiệp lừa đảo". Ưu tiên: "theo thông tin công khai", "ước tính",
"có thể tạo áp lực", "cần tiếp tục theo dõi", "chưa đủ dữ liệu để kết luận".

# 12. Từ khóa tìm kiếm

Đề xuất 3–4 từ khóa phù hợp chủ đề và ý định độc giả (1 từ khóa chính, 2–3 phụ),
dùng tự nhiên trong bài, không nhồi lặp. KHÔNG tự nhận đã kiểm chứng bằng Google
Trends / Search Console / Keyword Planner — người/công cụ kiểm ở Gate.

# 13. Dẫn nguồn

Gắn nguồn vào số liệu quan trọng. Không sao chép dài nguyên văn — tóm tắt bằng lời
người viết, giữ đúng ý nghĩa nguồn.
