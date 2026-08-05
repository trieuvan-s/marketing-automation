# Khảo sát codebase — marketing-automation (2026-08-03/04)

**Ngày khảo sát:** 2026-08-04 (dữ liệu crawl/production dẫn chứng thuộc lô 03/08/2026)
**SHA của `develop` lúc khảo sát:** `e7011c594336bc8998b49f4057a7f07853976fa7` (2026-08-04 12:35:22 +0700)

> ⚠️ **Báo cáo phản ánh trạng thái tại SHA trên.** Code đổi sau đó thì kết luận
> có thể sai — LUÔN dùng cột "Lệnh kiểm nhanh" để tự xác nhận lại trước khi
> tin, đừng coi báo cáo này là nguồn sự thật. Tiền lệ cần tránh:
> `src/twmkt/media_factory/spec.py` từng có docstring mô tả kiến trúc
> `ProductionSpec` đã KHÔNG CÒN TỒN TẠI (xem mục 4.1) — tài liệu không có
> bằng chứng file:dòng sẽ trôi khỏi thực tế, đây là báo cáo được viết để
> tránh lặp lại lỗi đó.

---

## 1. NGUỒN CRAWL

**Kết luận:** Nguồn crawl thật đọc từ tab SOURCES trên Google Sheet (13 nguồn,
Enable=TRUE), KHÔNG phải từ `config/settings.yaml` (có 9 nguồn `enabled: true`
— [config/settings.yaml:210-313](../config/settings.yaml#L210), đã lệch so với
Sheet — 4 nguồn chỉ tồn tại trên Sheet: Baochinhphu - Vĩ mô, Baochinhphu -
Chứng khoán, Nguoiquansat - Tài chính Ngân hàng, VietnamBiz - Tài Chính Ngân
Hàng).

> **Ghi chú lệch config/Sheet (priority Vietstock):** `config/settings.yaml:318`
> ghi `priority: 3` cho `vietstock-rss-co-phieu`, nhưng bảng dưới đây (đọc trực
> tiếp Sheet) ghi Priority 5 — giữ nguyên số liệu Sheet trong bảng, chỉ ghi chú
> lệch tại đây, không suy ra nguồn nào đúng.

**Bằng chứng:**
- Precedence Sheet-trước-config: [scripts/review_to_sheet.py:199](../scripts/review_to_sheet.py#L199)
  `sources = board.read_sources() or factory.build_sources(settings)`
- Dispatch fetch_type → collector: [src/twmkt/factory.py:262-292](../src/twmkt/factory.py#L262)
  (`"rss"` → `RssCollector`, `"html"` → `HttpFirstCollector`)
- Sort theo Priority giảm dần + lọc Enable: [src/twmkt/sheets_board.py:785-794](../src/twmkt/sheets_board.py#L785)
  (`sources_from_rows()`, docstring dòng 794: "Kết quả SẮP theo Priority GIẢM DẦN")
- Giới hạn số bài/nguồn: `limit` mặc định 3, ÁP DỤNG ĐỒNG NHẤT mọi nguồn
  (không có override riêng từng nguồn) — [scripts/review_to_sheet.py:249-250](../scripts/review_to_sheet.py#L249),
  default tại [scripts/review_to_sheet.py:403](../scripts/review_to_sheet.py#L403)
- Priority còn dùng để chọn đại diện khi gộp trùng sự kiện chéo nguồn:
  [src/twmkt/curation/enrich.py:94](../src/twmkt/curation/enrich.py#L94)

**Lệnh kiểm nhanh:**
```bash
sed -n '195,201p' scripts/review_to_sheet.py
sed -n '260,293p' src/twmkt/factory.py
sed -n '785,795p' src/twmkt/sheets_board.py
```

**Danh sách 13 nguồn (đọc trực tiếp tab SOURCES lúc khảo sát — sẽ đổi nếu ai
sửa Sheet sau đó, không phải hằng số trong code):**

| Publisher | Type | Priority |
|---|---|---|
| CafeF - Doanh nghiệp | html | 5 |
| CafeF - Vĩ mô | html | 5 |
| CafeF - Tài chính quốc tế | html | 3 |
| CafeF - RSS Chứng khoán | rss | 4 |
| CafeF - RSS Bất động sản | rss | 4 |
| CafeBiz - RSS Vĩ mô | rss | 4 |
| CafeBiz - RSS Chính sách | rss | 4 |
| CafeBiz - RSS Thế giới | rss | 4 |
| Vietstock - RSS Cổ phiếu | rss | 5 |
| Baochinhphu - Vĩ mô | html | 5 |
| Baochinhphu - Chứng khoán | html | 4 |
| Nguoiquansat - Tài chính Ngân hàng | html | 4 |
| VietnamBiz - Tài Chính Ngân Hàng | html | 4 |

**Mức chắc chắn:** ĐÃ XÁC MINH BẰNG CODE (danh sách + collector + sort +
limit). SUY LUẬN (priority dùng cho chọn đại diện — đọc đúng dòng code
nhưng chưa chạy lại thực nghiệm riêng cho mục này).

---

### 1.2 / 1.3 — Số bài mỗi nguồn lô 03/08, nguồn nào không ra bài

**Kết luận:** Trong 30 dòng CONTEXT có Timestamp=03/08/2026, TOÀN BỘ đến từ
`cafef.vn` (28) hoặc `vietstock.vn` (2). 7/13 nguồn cấu hình (CafeBiz ×3,
Baochinhphu ×2, Nguoiquansat, VietnamBiz) **không đóng góp bài nào — kể cả
dưới dạng nguồn phụ bị gộp chéo sự kiện.**

**Bằng chứng:**
- Cột Source trên CONTEXT gộp cả báo phụ dạng `"(+N báo)"` khi có trùng sự
  kiện: [src/twmkt/sheets_board.py:870-876](../src/twmkt/sheets_board.py#L870)
  (`_source_cell()`) — đã đọc trực tiếp 30 dòng Source của lô 03/08/2026,
  **không dòng nào có annotation `(+N báo)`.**
- KHÔNG có log per-source hay tổng crawl nào được persist — chỉ in console:
  [scripts/review_to_sheet.py:249](../scripts/review_to_sheet.py#L249) và
  [scripts/review_to_sheet.py:370](../scripts/review_to_sheet.py#L370) đều là
  `print(...)`, không ghi `board.log(...)`. Log tổng hợp DUY NHẤT có tồn tại
  trong code ở [scripts/review_to_sheet.py:347](../scripts/review_to_sheet.py#L347)
  nhưng KHÔNG có bản ghi khớp nào trong LOG lịch sử của lô 03/08 (đã tra toàn
  bộ layer `log` trong store cho ngày đó, chỉ thấy log "TỔNG Production", 0
  log "TỔNG: crawled...").

**Lệnh kiểm nhanh:**
```bash
grep -n "print(f\"\[" scripts/review_to_sheet.py     # xác nhận console-only
grep -n "board.log" scripts/review_to_sheet.py        # log persist duy nhất, dòng 347 vùng crawl-summary
```

**Vì sao 7 nguồn im lặng — CHƯA XÁC ĐỊNH ĐƯỢC.** Không có log per-source
persist để phân biệt: lỗi kết nối / feed rỗng / bị lọc trùng content-hash /
bị `filter_by_freshness` loại trước khi tới `cluster_by_event`. Muốn trả lời
dứt điểm cần chạy lại `review_to_sheet.py --debug` và thêm log tạm — KHÔNG
làm trong lượt khảo sát chỉ-đọc này.

**Mức chắc chắn:** ĐÃ XÁC MINH BẰNG CODE (0 log persist, 0 dòng gộp nguồn
phụ). CHƯA XÁC ĐỊNH ĐƯỢC (nguyên nhân gốc của việc 7 nguồn không ra bài).

---

### 1.4 — Cơ chế giới hạn/ưu tiên

**Kết luận:** Có 2 cơ chế riêng biệt, đã nêu ở mục 1 — `limit` (đồng nhất
mọi nguồn, không override riêng) và `Priority` (thứ tự crawl + chọn đại diện
khi gộp trùng).

**Mức chắc chắn:** ĐÃ XÁC MINH BẰNG CODE.

---

## 2. RULES ĐANG NẠP

**Kết luận:** Cả 4 loại output đọc `_load_composer_rules()` — 1 đường nạp
DUY NHẤT, mode = `"full"` (đọc file nguyên văn, không cắt section).

| Output | File | Mode |
|---|---|---|
| Article | `prompts/content-rules-daily-v3.4.md` | full |
| Long-Article | file trên + nối `prompts/content-rules-deep-v3.0.md` | full |
| Infographic | `prompts/content-rules-daily-v3.4.md` | full |
| Video Script | `prompts/content-rules-daily-v3.4.md` | full |

**Bằng chứng:**
- Hàm nạp: [src/twmkt/agents/production.py:274-341](../src/twmkt/agents/production.py#L274)
- Mode cấu hình: [config/settings.yaml:545](../config/settings.yaml#L545) (`rules_load_mode: "full"`)
- File base: [config/settings.yaml:551](../config/settings.yaml#L551)
- File supplement (chỉ Long-Article): [config/settings.yaml:557](../config/settings.yaml#L557)
- Lời gọi thật: Article/Long-Article [src/twmkt/agents/writer.py:88](../src/twmkt/agents/writer.py#L88)
  (`build_writer_system()`, docstring dòng 68 tự khai "ĐÂY là đường Article/
  Long-Article THẬT đang chạy sản xuất"), chuỗi gọi:
  `scripts/produce_from_sheet.py:651` (`run_writer_with_retry(...)`) →
  `run_writer()` [writer.py:106](../src/twmkt/agents/writer.py#L106) →
  `build_writer_system()` [writer.py:88](../src/twmkt/agents/writer.py#L88).
  `production.py:602` nằm trong `AnalysisWriterAgent.run()` nhưng agent này
  **KHÔNG được gọi ở đường sản xuất thật** — chỉ 2 nơi gọi
  `AnalysisWriterAgent(`: [scripts/ab_voice.py:74](../scripts/ab_voice.py#L74)
  và [scripts/ab_voice2.py:62](../scripts/ab_voice2.py#L62) (script A/B thử
  giọng văn, không phải sản xuất).
  Video [production.py:797](../src/twmkt/agents/production.py#L797),
  Infographic [production.py:1329](../src/twmkt/agents/production.py#L1329)

**Lệnh kiểm nhanh:**
```bash
sed -n '274,341p' src/twmkt/agents/production.py
grep -n "rules_load_mode\|content_rules_path\|content_rules_supplement_path" config/settings.yaml
grep -rn "_load_composer_rules(" src/ scripts/
grep -rn "AnalysisWriterAgent(" scripts/ src/
sed -n '64,91p' src/twmkt/agents/writer.py
```

**Mức chắc chắn:** ĐÃ XÁC MINH BẰNG CODE.

---

### 2.2 — Video Script có `rules_settings` theo request chưa

**Kết luận:** Chưa. Cơ chế `rules_settings` (A/B theo request, khai báo ở base
class `Agent`) chỉ THẬT SỰ được dùng ở Video ([production.py:797](../src/twmkt/agents/production.py#L797))
và Infographic ([production.py:1329](../src/twmkt/agents/production.py#L1329))
— nhưng grep toàn bộ `scripts/produce_from_sheet.py` + `agents/production.py`
cho `.rules_settings =` ra **0 kết quả**, nên tham số này luôn `None` ở cả 2
loại output đó. Đường Article/Long-Article THẬT (`writer.py:88`, xem mục 2)
**KHÔNG đi qua cơ chế `rules_settings` này** — `build_writer_system()` nhận
`settings` toàn cục qua tham số hàm thẳng từ `produce_from_sheet.py:651`, không
qua thuộc tính `.rules_settings` của agent nào cả.

**Bằng chứng:**
- Khai báo: [src/twmkt/agents/base.py:242](../src/twmkt/agents/base.py#L242) (`rules_settings: object | None = None`)
- Khởi tạo: [src/twmkt/agents/base.py:247](../src/twmkt/agents/base.py#L247) (`self.rules_settings = None`)
- Dùng ở Video/Infographic: [production.py:797](../src/twmkt/agents/production.py#L797),
  [production.py:1329](../src/twmkt/agents/production.py#L1329)

**Lệnh kiểm nhanh:**
```bash
grep -rn "\.rules_settings\s*=" scripts/produce_from_sheet.py src/twmkt/agents/production.py
```
(mong đợi: không ra dòng nào ngoài khai báo trong `base.py`)

**Mức chắc chắn:** ĐÃ XÁC MINH BẰNG CODE.

---

### 2.3 — Long-Article đã nối chưa (enum + map + 2-file loader)

**Kết luận:** ĐÃ XONG (Việc 1, commit `15187ad`).

**Bằng chứng:**
- Enum: [src/twmkt/models.py:45](../src/twmkt/models.py#L45) (`LONG_ARTICLE = "long_article"`)
- Map Output Type → content_type: [scripts/produce_from_sheet.py:152-153](../scripts/produce_from_sheet.py#L152)
  (`_OUTPUT_TYPE_TO_CONTENT_TYPE`, gồm `"Long-Article": "article"`)
- 2-file loader: xem mục 2 (supplement chỉ áp dụng `content_type == "long_article"`)

**Lệnh kiểm nhanh:**
```bash
git show 15187ad --stat
grep -n "LONG_ARTICLE\|long_article" src/twmkt/models.py scripts/produce_from_sheet.py
```

**Mức chắc chắn:** ĐÃ XÁC MINH BẰNG CODE + git log.

---

### 2.4 — Bài nào đi qua Long-Article lô 03/08? Dừng ở đâu?

**Kết luận:** Đúng 1 topic chọn Long-Article: `topic_key=91d09f039226343c`.
Trace TOÀN BỘ layer trong store (`raw`, `brief`, `content_output`,
`infographic`, `video`, `gate_status`, `content_status`, mọi content_type) cho
topic này: **CHỈ có `raw` (1 bản) và `gate_status` (8 bản) — layer `brief`
KHÔNG HỀ được ghi, dù `gate_status` đạt `execute=DONE` 2 lần** (04:26→05:15 và
08:51→08:54, ngày 03/08/2026). Nghĩa là chuỗi Brief→Router→Composer chưa từng
thực thi — dừng TRƯỚC BƯỚC BRIEF, không phải Brief chạy rồi Composer lỗi.

**Bằng chứng:** trace bằng `store/document_store.py::read_history()` cho
`topic_key="91d09f039226343c"` — kết quả thực nghiệm (không phải suy đoán):
```
raw ''          v1  (dữ liệu crawl gốc)
gate_status ''  v1  gate1=PENDING  execute=Waiting     output_type=[AUTO]
gate_status ''  v2  gate1=APPROVE  execute=Waiting     output_type=[Long-Article]
gate_status ''  v3  gate1=APPROVE  execute=Running...  output_type=[Long-Article]
gate_status ''  v4  gate1=APPROVE  execute=DONE        output_type=[Long-Article]
gate_status ''  v5  gate1=PENDING  execute=Waiting     output_type=[]
gate_status ''  v6  gate1=APPROVE  execute=Waiting     output_type=[Long-Article]
gate_status ''  v7  gate1=APPROVE  execute=Running...  output_type=[Long-Article]
gate_status ''  v8  gate1=APPROVE  execute=DONE        output_type=[Long-Article]
brief / content_output / infographic / video / content_status: 0 bản ghi (mọi content_type)
```

**Lệnh kiểm nhanh** (chạy trong repo, có `PYTHONPATH` gồm `src`):
```bash
python -c "
import sys; sys.path.insert(0, 'src')
from store import document_store as ds
tk = '91d09f039226343c'
for layer in ['raw','brief','content_output','infographic','video','gate_status','content_status']:
    for ct in ['', 'article', 'infographic', 'video', 'long_article']:
        h = ds.read_history(tk, layer, ct)
        if h: print(layer, repr(ct), len(h))
"
```

**Đây là bug thật, chưa root-cause được tới dòng code cụ thể.** Cần trace
runtime (thêm log tạm hoặc breakpoint khi chạy lại `scripts/produce_from_sheet.py`
với Output Type=Long-Article) để biết chính xác điều kiện nào khiến topic bị
bỏ qua TRƯỚC Brief mà vẫn ghi `execute=DONE`. KHÔNG làm trong lượt khảo sát
chỉ-đọc này.

**Mức chắc chắn:** ĐÃ XÁC MINH BẰNG CODE/dữ liệu store (hiện tượng). CHƯA
XÁC ĐỊNH ĐƯỢC (dòng code gây dừng sớm — cần điều tra runtime riêng).

---

### 2.5 — Video Script rules có hướng dẫn chiều sâu nội dung không

**Kết luận:** Có, không chỉ ràng buộc kỹ thuật.

**Bằng chứng:** [prompts/content-rules-daily-v3.4.md:267-277](../prompts/content-rules-daily-v3.4.md#L267)
(`## 4.3. Video Script`) — hướng dẫn hook/nhịp kể chuyện/độ dài theo nguồn;
số cảnh/thời lượng/timecode cố tình đẩy ra cấu hình sản phẩm, không nằm
trong file rules.

**Lệnh kiểm nhanh:**
```bash
sed -n '267,277p' prompts/content-rules-daily-v3.4.md
```

**Mức chắc chắn:** ĐÃ XÁC MINH BẰNG CODE.

---

## 3. PROMPT SINH ẢNH

**Kết luận:** Prompt gửi gpt-image-2 dựng ở `build_ai_full_prompt()`, phiên
bản `_PROMPT_VERSION = "v12"` (mới hơn "v10" được nhắc trong câu hỏi gốc).

**Bằng chứng:**
- Version: [src/twmkt/render/ai_full.py:70](../src/twmkt/render/ai_full.py#L70)
- Hàm dựng prompt: [src/twmkt/render/ai_full.py:399-494](../src/twmkt/render/ai_full.py#L399)

**Nguyên văn khối yêu cầu bắt buộc (`safety_block`) + khối 8 (photo subject):**
```
YÊU CẦU BẮT BUỘC (không thoả hiệp):
1. Dùng TOÀN BỘ canvas tỷ lệ {ratio}... Full-bleed full-canvas...
2. {visual_direction}
3. Góc trên-phải giữ thị giác nhẹ... Mép dưới dùng nền ít chi tiết...
4. KHÔNG vẽ logo, thương hiệu, watermark, chữ "FVA Capital", nguồn, tác giả...
5. KHÔNG vẽ bản đồ... ƯU TIÊN HÌNH ẢNH THẬT: dùng ngôn ngữ ảnh chụp báo chí/
   doanh nghiệp tự nhiên làm minh hoạ chính... Vì đầu vào không cung cấp tài
   sản ảnh đã xác minh, đây phải là AI photorealistic mô tả BỐI CẢNH CHUNG,
   không được giả làm ảnh bằng chứng của đúng sự kiện, nhân vật hay địa điểm
   cụ thể. Không dựng gương mặt người thật, logo doanh nghiệp, biển hiệu có
   thương hiệu hoặc công trình nhận diện cụ thể...
6. Chỉ dùng ĐÚNG số liệu có trong JSON...
7. Giữ nguyên dấu tiếng Việt...
8. PHOTO SUBJECT ANCHOR: use {generic-category-description}. The photograph
   must explain the subject at first glance... Treat it as generic contextual
   imagery, never as evidence of the named event, company or location.
```
Nguyên văn tại [ai_full.py:452-476](../src/twmkt/render/ai_full.py#L452), khối 8
tại [ai_full.py:439-440](../src/twmkt/render/ai_full.py#L439) gọi
`_photo_subject_direction()` [ai_full.py:249-373](../src/twmkt/render/ai_full.py#L249).

**Lệnh kiểm nhanh:**
```bash
sed -n '399,494p' src/twmkt/render/ai_full.py
```

**Mức chắc chắn:** ĐÃ XÁC MINH BẰNG CODE.

---

### 3.3 — Có truyền TÊN CHỦ THỂ cụ thể vào mô tả ảnh không?

**Kết luận:** 2 lớp, tác dụng NGƯỢC nhau:
1. Toàn bộ JSON spec (`title`, `hero`, `tickers`...) nhúng NGUYÊN VĂN vào
   prompt qua `spec_json_str` — chỉ 2 field rỗng (`subtitle`, `related`) bị
   lược. Model THẤY tên doanh nghiệp/ticker thật trong phần dữ liệu JSON.
2. Khối chỉ đạo ảnh cụ thể (mục 8, `_photo_subject_direction()`) KHÔNG dùng
   tên chủ thể nguyên văn — match keyword theo ~10 category cố định (vd
   "khai khoáng" → "a real industrial materials... environment... without
   any company logo or claim that it is the named company's facility"),
   không khớp category nào thì fallback về mô tả chung.

**Bằng chứng:**
- Nhúng JSON nguyên văn: [ai_full.py:424](../src/twmkt/render/ai_full.py#L424)
  (`spec_json_str = json.dumps(prompt_spec, ...)`)
- Lược field rỗng: `_spec_for_image_prompt()` [ai_full.py:376-396](../src/twmkt/render/ai_full.py#L376)
- Bảng category cố định: [ai_full.py:283-343](../src/twmkt/render/ai_full.py#L283)
- Fallback chung: [ai_full.py:361-366](../src/twmkt/render/ai_full.py#L361)

**Lệnh kiểm nhanh:**
```bash
sed -n '249,373p' src/twmkt/render/ai_full.py
```

**Kết luận phụ (SUY LUẬN, không phải bằng chứng trực tiếp):** đây là nguyên
nhân hợp lý nhất cho hiện tượng "ảnh không liên quan chủ thể" — do THIẾT KẾ
(chặn AI tự bịa "ảnh bằng chứng" giả cho sự kiện/công ty/địa điểm cụ thể,
khớp rào ở mục 5), không phải lỗi ngẫu nhiên.

**Mức chắc chắn:** ĐÃ XÁC MINH BẰNG CODE (2 lớp tồn tại thật). SUY LUẬN (đây
là nguyên nhân gây "ảnh không liên quan" mà Lead quan sát).

---

### 3.4 — Theme rules §5.1/5.2/5.3 — mục nào đang nạp?

**Kết luận:** KHÔNG mục nào trong §5 (Quy tắc hình ảnh thật) được nạp vào
prompt. Hàm DUY NHẤT đọc file theme markdown chỉ trích bảng màu + theme_id
bằng regex, tự khai rõ trong docstring rằng phần layout/typography/density
KHÔNG được parse.

**Bằng chứng:**
- [src/twmkt/render/brand_stamp.py:171-175](../src/twmkt/render/brand_stamp.py#L171)
  (docstring: "Các phần layout D*/L*, typography và density trong markdown
  không được parse hay đưa vào renderer")
- Trích xuất thật: chỉ `_THEME_TOKEN_ROW_RE` (màu) + `_THEME_ID_RE` (theme_id)
  — [brand_stamp.py:183-194](../src/twmkt/render/brand_stamp.py#L183)
- Nội dung §5 tồn tại thuần làm tài liệu: [prompts/themes/Infographic_Theme_Dark.md:94-134](../prompts/themes/Infographic_Theme_Dark.md#L94)

**Lệnh kiểm nhanh:**
```bash
sed -n '166,195p' src/twmkt/render/brand_stamp.py
grep -n "^## 5\." prompts/themes/Infographic_Theme_Dark.md
```

**Mức chắc chắn:** ĐÃ XÁC MINH BẰNG CODE.

---

### 3.5 — Có cơ chế dùng ảnh THẬT từ bài gốc không?

**Kết luận:** Không tìm thấy — 100% ảnh do AI sinh. `RawDocument` không có
field lưu URL ảnh (`image_url`/`thumbnail`/`og:image`); grep toàn repo
`src/twmkt` cho các từ khóa này chỉ khớp trong văn bản tiếng Việt của chính
`ai_full.py` (không phải field code). Prompt tự thừa nhận điều này.

**Bằng chứng:**
- `RawDocument` dataclass không có field ảnh: [src/twmkt/models.py:78-101](../src/twmkt/models.py#L78)
- Prompt tự nhận "đầu vào không cung cấp tài sản ảnh đã xác minh":
  [ai_full.py:471-472](../src/twmkt/render/ai_full.py#L471)

**Lệnh kiểm nhanh:**
```bash
grep -rn "image_url\|thumbnail\|og:image\|photo_url" src/twmkt/ | grep -v ai_full.py
```
(mong đợi: không ra kết quả nào ngoài `ai_full.py`)

**Mức chắc chắn:** ĐÃ XÁC MINH BẰNG CODE.

---

## 4. NĂM MỆNH ĐỀ LEAD CŨ ĐÃ GHI — xác nhận đúng/sai

⚠️ **Cả 5 mệnh đề đều SAI/LỖI THỜI so với `develop` tại SHA khảo sát** — đây
là ưu tiên cao nhất Lead yêu cầu ghi rõ.

### 4.1 — "ProductionSpec dataclass là dead code"

**SAI/LỖI THỜI.** `ProductionSpec`/`ProductionScene`/`verify_spec()` KHÔNG
CÒN TỒN TẠI trong Python — đã bị XOÁ HẲN 2026-07-28 (commit `68fc2bf`), KHÔNG
phải "dead code còn nằm đó chưa dọn". Lý do xoá: được PORT sang TypeScript
(`aigen-pipeline/src/production-spec/guardrail/verify-spec.ts`), đã đối
chiếu tay 100% semantics và chạy thật trên video.mp4. File hiện tại chỉ còn
`VISUAL_KINDS`/`DEFERRED_VISUAL_KINDS` (2 hằng số vẫn được `agents/production.py`
import thật).

**Bằng chứng:**
- [src/twmkt/media_factory/spec.py:1-51](../src/twmkt/media_factory/spec.py) —
  toàn bộ file, docstring dòng 1-36 ghi rõ lịch sử xoá + lý do.
- Commit xoá: `68fc2bf` "Don dead code: xoa ProductionSpec/verify_spec Python
  (da duoc thay the)"

**Lệnh kiểm nhanh:**
```bash
grep -rn "class ProductionSpec\|class ProductionScene" src/ scripts/   # mong đợi: 0 kết quả
git show 68fc2bf --stat
cat src/twmkt/media_factory/spec.py
```

**Mức chắc chắn:** ĐÃ XÁC MINH BẰNG CODE + git log.

### 4.2 — "Long-Article chưa được nối"

**SAI/LỖI THỜI.** Đã nối xong (Việc 1, commit `15187ad`) — xem mục 2.3 ở
trên. Lưu ý: dù đã nối, mục 2.4 phát hiện 1 bug KHÁC (topic Long-Article
03/08 bị dừng trước Brief) — không liên quan tới việc "nối" hay chưa, đây là
bug thực thi runtime, không phải thiếu enum/map/loader.

**Mức chắc chắn:** ĐÃ XÁC MINH BẰNG CODE + git log.

### 4.3 — "is_pid_alive() dùng os.kill(pid, 0)"

**SAI/LỖI THỜI.** Đã sửa (commit `0cd60e4`, 2026-08-02) — Windows dùng
`ctypes.windll.kernel32.OpenProcess(SYNCHRONIZE, ...)`, POSIX vẫn giữ
`os.kill(pid, 0)` (đúng ngữ nghĩa trên OS đó). Bug cũ: `os.kill(pid, 0)` trên
Windows KHÔNG phải no-op — giá trị 0 là bí danh CTRL_C_EVENT, gửi Ctrl+C thật.

**Bằng chứng:**
- [system_power_on.py:89-114](../system_power_on.py#L89) — docstring dòng
  92-108 ghi rõ bug cũ + lý do sửa; code dòng 109-114 nhánh theo `os.name`.

**Lệnh kiểm nhanh:**
```bash
sed -n '89,120p' system_power_on.py
git show 0cd60e4 --stat
```

**Mức chắc chắn:** ĐÃ XÁC MINH BẰNG CODE + git log.

### 4.4 — "render_production_assets.py còn ghi thẳng Sheet"

**SAI/LỖI THỜI.** Đã sửa (Việc A, commit `258eca3`). `_append_notes()` giờ
đọc/ghi `content_output` qua `store` (`ps.write_content_output()`), AssetPath
cũng ghi qua `ps.write_content_status()` — KHÔNG còn gọi `board.set_content_cell()`
trực tiếp lên Sheet ở đường Notes/AssetPath. 2 chỗ còn nhắc `board.set_content_cell`
trong file là COMMENT lịch sử (giải thích lỗi CŨ), không phải code đang chạy.

**Bằng chứng:**
- [scripts/render_production_assets.py:92-120](../scripts/render_production_assets.py#L92)
  (`_append_notes()`, docstring dòng 93-98 giải thích lỗi cũ + lý do sửa)
- [scripts/render_production_assets.py:526-538](../scripts/render_production_assets.py#L526)
  (AssetPath ghi qua `ps.write_content_status(...)`, comment dòng 528-535 xác
  nhận KHÔNG còn ghi thẳng Sheet)

**Lệnh kiểm nhanh:**
```bash
grep -n "board\.set_content_cell\|board\._tab(\|\.append_row(" scripts/render_production_assets.py
# mong đợi: chỉ 2 dòng comment (93, 528-529), KHÔNG có lời gọi thật
git show 258eca3 --stat
```

**Mức chắc chắn:** ĐÃ XÁC MINH BẰNG CODE + git log.

### 4.5 — "Schema store có FOREIGN KEY chưa, PRAGMA foreign_keys có bật không"

**Kết luận: KHÔNG có FOREIGN KEY nào trong schema, và `PRAGMA foreign_keys`
KHÔNG BAO GIỜ được bật ở bất kỳ điểm kết nối SQLite nào.** `topic_key` là cột
TEXT thường (CHECK length > 0), không tham chiếu khoá ngoại tới bảng nào — kể
cả giữa `documents` và `execution_queue`. Đây có vẻ là THIẾT KẾ CHỦ Ý (khớp
nguyên tắc append-only/không-DELETE của module), không phải thiếu sót bị bỏ
quên — nhưng báo cáo này CHỈ XÁC NHẬN HIỆN TRẠNG, không đánh giá đúng/sai của
quyết định thiết kế.

**Bằng chứng:**
- Toàn bộ [store/schema.sql](../store/schema.sql) — 2 bảng `documents` (dòng
  57-96) và `execution_queue` (dòng 110-137), không bảng nào có mệnh đề
  `FOREIGN KEY`.
- [store/document_store.py:110-118](../store/document_store.py#L110)
  (`_connect()`) — chỉ `sqlite3.connect()` + `row_factory`, không có
  `PRAGMA foreign_keys`.

**Lệnh kiểm nhanh:**
```bash
grep -n "FOREIGN KEY" store/schema.sql               # mong đợi: 0 kết quả
grep -rn "foreign_keys" store/*.py                   # mong đợi: 0 kết quả
```

**Mức chắc chắn:** ĐÃ XÁC MINH BẰNG CODE.

---

## 5. NHỮNG GÌ KHÔNG KIỂM ĐƯỢC

1. **Nguyên nhân gốc 7 nguồn không ra bài lô 03/08** (mục 1.2/1.3) — không có
   log per-source persist, chỉ có proxy hậu-dedup. Không phân biệt được lỗi
   kết nối / feed rỗng / bị lọc trùng / bị filter freshness.
2. **Dòng code chính xác gây Long-Article dừng trước Brief** (mục 2.4) — xác
   nhận được HIỆN TƯỢNG bằng dữ liệu store thật, chưa xác định được ĐIỂM DỪNG
   trong `scripts/produce_from_sheet.py` — cần trace runtime (thêm log/
   breakpoint khi chạy lại), ngoài phạm vi khảo sát chỉ-đọc.
3. **Quyết định thiết kế "không FOREIGN KEY" (mục 4.5) đúng/sai** — báo cáo
   chỉ xác nhận hiện trạng, không đánh giá rủi ro toàn vẹn dữ liệu của quyết
   định này (nằm ngoài phạm vi "khảo sát, chỉ đọc").
