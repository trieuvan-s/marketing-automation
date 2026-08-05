# BÀN GIAO DỰ ÁN — marketing-automation + aigen

**Ngày bàn giao:** 2026-08-03
**Người bàn giao:** Lead Engineer (Claude, phiên chat)
**Người nhận:** Lead Engineer kế nhiệm
**Chủ dự án / người quyết định cuối:** Trung Tran (FVA Capital)

> **Đọc mục 0 và mục 9 trước tiên.** Mục 0 cho bạn hiểu hệ thống làm gì. Mục 9 là những bài học đắt giá — bỏ qua nó bạn sẽ lặp lại đúng những sai lầm đã tốn nhiều ngày.

---

## 0. Hệ thống này làm gì

Dây chuyền sản xuất nội dung tài chính tự động cho FVA Capital:

```
Crawl tin tài chính (CafeF, ...) 
  → Gate 1: người duyệt chủ đề
  → Brief: trích dữ kiện từ bài gốc
  → Router: quyết định sinh loại nội dung nào
  → Composer (LLM): viết bài / kịch bản / spec ảnh
  → Gate 2: người duyệt nội dung
  → Render: bài viết (.md→Google Docs) · infographic (.png) · video (.mp4)
  → Upload Drive → AssetPath trên Sheet để team mở
```

**Hai repo:**

| Repo | Ngôn ngữ | Vai trò |
|---|---|---|
| `marketing-automation` | Python | Crawl → Brief → Router → Composer → render ảnh → store → Sheet |
| `aigen` | TypeScript | Nhận `CONTENT.Output` → dựng video MP4 |

**Ranh giới hai repo:** `CONTENT.Output` (dict Python dựng tay trong `production.py`). Bên aigen, `production-spec/` là cây cầu thật: `scene-builder → guardrail-2 → voice → alias-guardrail → adapter → TemplateScript`. Điểm vào: `index.ts::buildTemplateScriptFromContentOutput()`.

⚠️ **`media_factory/spec.py::ProductionSpec` (dataclass Python) là DEAD CODE.** Docstring của nó mô tả một kiến trúc chưa bao giờ được hiện thực ở phía Python. Đã làm cả Lead lẫn user hiểu sai suốt nhiều lượt. Không xây gì lên trên nó.

**MVP đã đóng** ngày 29/07/2026 — tag `MVP-29-07-2026` và `MVP-thong-luong-29-07-2026`. Bằng chứng: một video MP4 H.264 1080×1920 + AAC, 30,5s, đi trọn từ tin thô tới Drive không thao tác tay.

---

## 1. Hạ tầng và vận hành

**Máy:** VPS Windows. agent-A từng chạy trên máy cũ (ổ `E:`), nay phần lớn đã trên VPS (ổ `D:`).

**`queue_worker.py`** — tiến trình nền đọc thao tác từ Sheet, tạo job, xử lý, ghi kết quả.

| Việc | Trạng thái |
|---|---|
| OAuth app "In production" | ✅ xong (nếu còn "Testing", refresh token hết hạn sau 7 ngày, hệ thống chết lặng lẽ) |
| Đăng ký Task Scheduler cho `queue_worker` | ⚠️ **CẦN XÁC NHẬN LẠI** — đã hướng dẫn, chưa có báo cáo hoàn tất |

Lệnh đăng ký (PowerShell quyền Admin):
```powershell
$Py   = "<đường dẫn venv>\Scripts\python.exe"
$Repo = "<đường dẫn repo>"
$A = New-ScheduledTaskAction -Execute $Py -Argument "-u scripts\queue_worker.py" -WorkingDirectory $Repo
$T = New-ScheduledTaskTrigger -AtStartup
$S = New-ScheduledTaskSettingsSet -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) -StartWhenAvailable
$P = New-ScheduledTaskPrincipal -UserId "SYSTEM" -RunLevel Highest
Register-ScheduledTask -TaskName "twmkt-queue-worker" -Action $A -Trigger $T -Settings $S -Principal $P -Force
```
⚠️ `-u` bắt buộc — thiếu nó Python đệm stdout, log im lặng hoàn toàn. Đã tốn thời gian nhiều lần vì chuyện này.
⚠️ Lỗi xác thực Google khi chạy dưới SYSTEM → đổi sang `-UserId "$env:COMPUTERNAME\$env:USERNAME" -LogonType S4U`.

**⚠️ RESTART `queue_worker.py` sau MỌI thay đổi code/config.** Python không tự nạp lại module. Sửa xong, chạy lại, thấy hành vi cũ, tưởng bản vá sai — lỗi này lặp nhiều lần.

**Một chủ duy nhất cho `queue_worker`:** chỉ agent quản repo được tắt/bật. Hai agent cùng restart đã gây tranh tiến trình.

---

## 2. Đội agent

| Agent | Nền tảng | Vùng file | Ghi chú |
|---|---|---|---|
| **agent-A** | Claude Code | `agents/` · `prompts/` · loader · `store/` · `sheets_board.py` · `produce_from_sheet.py` · `queue_worker.py` · `render_production_assets.py` | Agent chính, quản repo trực tiếp |
| **agent-B** | Claude Code | `aigen` (video) · từng làm `ai_full.py`/`brand_stamp.py` | Từng hết usage tuần; có lúc đóng vai agent-A |
| **agent-C** | Codex | `render/ai_full.py` · `render/brand_stamp.py` · `render/postflight.py` | Agent phụ |

### ⚠️ LUẬT MERGE — QUAN TRỌNG NHẤT VỀ ĐIỀU PHỐI

**Chỉ agent quản repo trực tiếp (agent-A) mới được merge vào `develop`. Agent phụ dừng ở push nhánh feature hoặc tạo PR.**

Lead cũ đã vi phạm luật này ba lần (cấp "quyền riêng lần này" cho agent-C). Hậu quả: `develop` local đi trước origin, rác từ fast-forward dở, ba lượt trao đổi chỉ để gỡ một tình huống lẽ ra không xảy ra. **Đừng cấp ngoại lệ.**

### Giới hạn về mô hình

⚠️ agent-C chạy Codex. **Không giao nó việc ĐO hoặc MÔ PHỎNG hành vi Composer.** Bài học đắt: một lượt A/B rules sinh mẫu bằng Codex trong khi Composer production chạy Opus → toàn bộ số liệu vô giá trị vì đo sai mô hình.

Việc an toàn cho Codex: hình học Pillow, gọi API sinh ảnh, đọc code, chạy test, viết script.

---

## 3. Kiến trúc đã chốt — không bàn lại

| # | Quyết định | Bằng chứng |
|---|---|---|
| 1 | Store SQLite là **nguồn sự thật**. Sheet chỉ là **view**. Sync dựng lại Sheet từ store | Bước 2-3 store-as-truth |
| 2 | Renderer đọc JSON đầy đủ **từ store**, không đọc ô Sheet (ô chỉ lưu preview cắt 1500 ký tự) | Bug 5.3, đã sửa |
| 3 | **Disclaimer thuộc CODE**, chuỗi nằm `config/brand.yaml`. Composer KHÔNG viết | `production.py:490/522/756` |
| 4 | Chuỗi disclaimer chuẩn: `Nội dung mang tính tham khảo, không phải khuyến nghị đầu tư.` (CÓ dấu chấm) | Lead chốt 30/07 |
| 5 | `TopicKey = sha256("url:" + canonical_url)[:16]` — hash, **không phải URL** | `curation/keys.py:184-188` |
| 6 | Cây cầu vendor-neutral ở **aigen**; `ProductionSpec` dataclass Python là dead code | agent-B grep xác minh |
| 7 | Adapter aigen **ĐÃ KHOÁ** (79/79 test, PR #1) — không sửa | `disclaimer-slot.ts` |
| 8 | Đặt tên **đơn nghĩa**: `source_name`="CafeF", `article_url`=địa chỉ. Cấm tên ghép `source_url` | Xem mục 9.1 |
| 9 | Band đáy infographic hiển thị **tên nguồn** ("CafeF"), không dùng domain | Lead chốt |
| 10 | Khung ảnh: **fit-inside**, cấm center-crop. Phần dư dồn lên đỉnh. Logo góc trên phải | Xem mục 9.2 |
| 11 | Bỏ Semantic Validator khỏi MVP; Contract Validator thu về kiểm schema tất định | Lead chốt |
| 12 | Theme **Dark** cho tin hằng ngày, **Light** cho track chuyên sâu | Cả 2 file theme tự khai `default_use` |
| 13 | Nhãn hiển thị tiếng Việt ở tầng Sheet/Telegram; **giá trị trong store giữ tiếng Anh** | Bảng ánh xạ trong config |
| 14 | Sửa logic **SỐ/GUARDRAIL** phải sửa **ĐỒNG BỘ 2 REPO** (`media_factory/numbers.py` + `production-spec/guardrail/verify-spec.ts`) | Đã phải vá đồng bộ 2 lần |

---

## 4. Bộ rules nội dung

**Quy ước tên file:**
```
prompts/content-rules-daily-v3.4.md    # tin hằng ngày — Article, Infographic, Video
prompts/content-rules-deep-v3.0.md     # chuyên sâu — nạp KÈM daily, không thay thế
prompts/content-rules-v2.1.md          # legacy, fallback
```

**Config:**
```yaml
writer:
  content_rules_path: "prompts/content-rules-daily-v3.4.md"
  rules_load_mode: "full"      # full | legacy_sections
```
`full` = nạp nguyên văn, không phụ thuộc heading. Không hard-code tên file.

**Lịch sử rules — vì sao v3.4:**

| Bản | Vấn đề |
|---|---|
| `content_writer_rules.md` (gốc, 639 dòng) | §3.2 quy định Article **bắt buộc đủ 10 mục** → đây chính là bộ sinh ra "bài viết dạng điền form" |
| v2.1 (248 dòng) | Chống form-filling tốt, nhưng thiếu sàn/trần và luật chống bẻ fact |
| v3.0→v3.4 | Lead cũ sửa 4 vòng. **Bài học: mỗi vòng thêm luật cấm thì tiêu chí "sáng tạo" tụt một bậc.** v3.3 phải bổ sung "Phần II — Không gian sáng tạo" để cân lại |
| v3.4 | Bản hiện tại. 3 sửa cuối đều từ phát hiện thực nghiệm: disclaimer về CODE · cấm bẻ 1 fact thành nhiều mục để đạt sàn · giới hạn câu bảo lưu lặp |

⚠️ **Đừng sửa rules bằng tranh luận.** Lead cũ đi từ v3.0 lên v3.4 qua 4 vòng, không vòng nào dựa trên dữ liệu cho tới lượt cuối. Sửa rules phải có bằng chứng từ output thật.

---

## 5. Contract Brief hiện tại

```json
{
  "brief_status": "OK | NO_USABLE_CONTENT | FAILED",
  "has_numeric_units": true,
  "has_qualitative_units": true,
  "content_units": [
    {
      "type": "numeric|event|policy_change|statement|process|relation|state_change|timeline|quote|inference",
      "subject": "chủ thể",
      "claim": "nội dung",
      "source": "câu nguồn NGUYÊN VĂN",
      "evidence": "direct_quote|paraphrase|derived|inferred"
    }
  ]
}
```

**Ba sàn chống bịa:**
1. Mỗi unit bắt buộc đủ `subject` + `claim` + `source`. Thiếu 1 → không hợp lệ.
2. `source` phải là **substring** của văn bản nguồn sau chuẩn hoá khoảng trắng.
3. Router chỉ đếm `evidence ∈ {direct_quote, paraphrase}` để bật article. `derived`/`inferred` là diễn giải, không phải bằng chứng neo nguồn.

**Router:**
- `article=true` khi `brief_status=OK` **và** có ≥1 unit hợp lệ, bất kể type.
- Không số → **chỉ** tắt Data Infographic. Không chạm article/video.
- User chọn **tường minh** một loại → Router **mất quyền phủ quyết**.
- User chọn **AUTO** → Router tự quyết.
- Mã SKIP: `SOURCE_BROKEN | DUPLICATE | BOILERPLATE | NO_USABLE_CONTENT | FORMAT_MISMATCH`

---

## 6. ĐANG LÀM DỞ — giao agent-A, chưa có báo cáo hoàn tất

Đây là gói việc cuối cùng được giao. **Kiểm trạng thái từng mục trước khi giao việc mới.**

### Việc 1 — Nối Long-Article ⚠️ NGUYÊN NHÂN GỐC
`Long-Article` **chưa bao giờ được hiện thực**: không có trong `_OUTPUT_TYPE_TO_CONTENT_TYPE` (`produce_from_sheet.py:138`), không có trong `ContentFormat` enum (`models.py:30-32`), `_allowed_output_types()` trả tập rỗng → chọn nó không sinh gì.

Cần: thêm `LONG_ARTICLE` vào enum + map · loader nạp **2 file** (daily nền, deep bổ sung) · thêm `writer.content_rules_supplement_path` · producer dùng chung đường article.

### Việc 2 — Lưu bài viết dạng Google Docs
Hiện upload `.md` → Drive mở bằng trình xem thô, người dùng thấy dấu `#`, `##`.
Cách làm: khi upload đặt `mimeType: application/vnd.google-apps.document`, body `text/markdown`. Drive tự parse. **Đừng viết bộ chuyển đổi markdown→docx.**
Chỉ áp Article/Long-Article. File `.md` cũ giữ nguyên.

### Việc 3 — Cột Type khớp dropdown
Cột Type đang ghi `article`/`infographic`/`video` (chữ thường), không khớp Output Type (`Article`/`Infographic`/`Video`/`Long-Article`).
Bảng giá trị hiển thị: `Article · Long-Article · Infographic · Video · AUTO` (5 giá trị).
Giá trị trong store giữ tiếng Anh chữ thường. Ánh xạ trong config.
⚠️ **User chờ agent-A xác nhận bảng 5 giá trị rồi mới dựng dropdown** — sai một ký tự là mọi ô lỗi validation.

### Việc 4 — Gộp dòng lỗi khi AUTO
Một chủ đề hỏng đang sinh nhiều dòng ERROR (bài Nafoods 3/8 sinh 3 dòng).
- AUTO + có loại thành công → hiện dòng thành công, bỏ dòng lỗi.
- AUTO + hỏng hết → **đúng 1 dòng**: `Type=AUTO · Status=ERROR · Notes gộp lý do`.
- User chọn **tường minh** mà hỏng → **giữ nguyên** Type = loại đã chọn.
- ⚠️ Gộp ở tầng **hiển thị**, store giữ đủ bản ghi từng loại (dữ liệu chẩn đoán).

### Việc 5 — Notes viết cho người dùng
Notes hiện là log kỹ thuật đặt nhầm chỗ. Người duyệt Gate là biên tập viên.
⛔ Cấm trong Notes hiển thị: `content_units[]` · `fact[]` · `brief` · `evidence` · `schema` · `JSON` · `parse` · `None` · tên hàm · tên file · mã lý do thô.
Ví dụ: `content_units[] rỗng` → "Không trích được dữ kiện nào từ bài gốc".
Bảng ánh xạ trong config. Mã lý do mới chưa ánh xạ → câu chung + ghi log cảnh báo.

### Việc 6 — Khảo sát 3 câu (CHỈ ĐỌC, chưa có kết quả)
1. **Nguồn crawl nào đang được cấu hình?** Lô 3/8 chủ yếu từ CafeF — cần biết nguồn khác có cấu hình mà không lấy được, hay chưa cấu hình.
2. **Rules nào đang nạp cho từng loại output?** Đặc biệt Video Script có nhận `rules_settings` theo request chưa.
3. **Prompt sinh ảnh có truyền TÊN CHỦ THỂ cụ thể không?**
   ⚠️ Đây nhiều khả năng là **gốc của vấn đề ảnh không liên quan**: nếu prompt chỉ mô tả phong cách mà không truyền tên doanh nghiệp/sự kiện, AI không biết bài nói về Vingroup hay PNJ → vẽ tòa nhà bất kỳ.

---

## 7. VẤN ĐỀ MỞ — chưa có hướng xử lý

### 7.1. Chất lượng nội dung — vấn đề nghiêm trọng nhất hiện tại

**Nghiệm thu lô 3/8:** tỷ lệ xử lý thành công tăng rõ, nhưng chất lượng gây lo ngại.

Đánh giá của Lead cũ sau khi đọc 4 bài thật: kỹ năng viết **cao**, nhưng **vi phạm bám nguồn**. Ví dụ:
- Bài siêu tháp: *"khoảng cách giữa bản vẽ và tòa nhà thật thường được đo bằng chu kỳ tín dụng"* — không có trong nguồn
- Bài Quốc hội: *"Bỏ cấp trung gian nghĩa là hàng loạt quy trình... không còn khớp"* — suy luận riêng
- Bài PNJ: *"Một doanh nghiệp bán lẻ trang sức sống bằng niềm tin của người mua"* — luận điểm nền

**Chẩn đoán:** đã gỡ cứng nhắc ở **đầu vào** (Brief, Router) rất tốt, nhưng **không có lớp nào kiểm đầu ra**. Semantic Validator — lớp duy nhất từng làm việc này — đã bị bỏ khỏi MVP.

Cửa vào mở rộng, cửa ra không ai gác. Bài **đọc hay hơn nhưng đáng tin ít hơn** — với nội dung tài chính, đó là hướng sai.

**Đề xuất chưa được duyệt:** đo trước khi sửa. Lấy các bài đã sinh, đối chiếu từng đoạn với `content_units` của chính nó, đếm bao nhiêu câu khẳng định không truy được về unit nào. Có số rồi mới quyết siết bằng rules hay bật lại Semantic Validator ở phạm vi hẹp.

### 7.2. Ảnh render không liên quan chủ thể
Xem Việc 6 câu 3. Nghi vấn: prompt không truyền tên chủ thể cụ thể.

### 7.3. Video hời hợt
Chưa điều tra. Cần biết rules Video Script có phần nào hướng dẫn chiều sâu nội dung hay chỉ có ràng buộc kỹ thuật (số cảnh, timecode).

### 7.4. Nguồn crawl đơn điệu
Lô 3/8 chủ yếu CafeF. Xem Việc 6 câu 1.

### 7.5. Thiết kế lại DB — user đã yêu cầu, chưa bắt đầu

**Yêu cầu của user:**
1. Xoá nhầm → khôi phục được
2. Xử lý lại 1 chủ đề → xoá dữ liệu đã xử lý (DB + Drive), chạy lại
3. `Output Type = DELETE` → xoá cả raw + processed + Drive
4. Không lưu trùng, không để artifact "mồ côi"
5. Dễ làm sạch và bảo trì

**Mâu thuẫn cốt lõi:** yêu cầu (1) cần **giữ lịch sử**, yêu cầu (3) cần **xoá thật**. Append-only làm được (1), không làm được (3).

**Đề xuất (chưa thẩm định trên schema thật):**

```
topics     — topic_key PK · url · title · crawled_at · status · deleted_at
artifacts  — topic_key FK ON DELETE CASCADE · kind · version · payload 
             · content_hash · created_at · superseded_at
             UNIQUE(topic_key, kind, content_hash)
assets     — topic_key FK · drive_file_id · kind · created_at · deleted_at
```

- **Xoá mềm** (mặc định): đánh `superseded_at`/`deleted_at`, hoàn tác được. Drive → thùng rác (giữ 30 ngày).
- **Xoá cứng** (chỉ khi DELETE): 2 pha — đặt `topics.deleted_at`, chờ retention 7 ngày, rồi `DELETE FROM topics` để CASCADE quét sạch.
- `FOREIGN KEY` + `CASCADE` là thứ khiến artifact mồ côi **không tồn tại được về cấu trúc** — mạnh hơn mọi quy ước.

**⚠️ Ba câu phải khảo sát trước khi làm:**
1. Schema hiện tại đã có `FOREIGN KEY` chưa, và SQLite có bật `PRAGMA foreign_keys = ON` không? (**mặc định TẮT** — bẫy phổ biến)
2. Artifact đang lưu theo layer riêng hay một bảng chung?
3. Đã có danh mục file Drive chưa, hay chỉ có `asset_url` rời rạc? Chưa có → phải đối soát với Drive thật xem còn bao nhiêu file mồ côi từ các lượt test.

### 7.6. Nợ kỹ thuật khác
- `cropped_top_px` — AI vẫn sinh dải lạ ở mép 1/6 ảnh, edge sanitizer đang gánh; chính sách prompt chưa triệt để
- `frame-market-ticker` tràn lề phải khi đủ 4 dòng (lỗi template có sẵn)
- 82 assert test `production-spec` chưa ai đọc từng dòng
- `speechLayer: "off"` — bật lại thì kiểm phiên âm không bị xử lý 2 lần
- 10 ô chrome template video chưa quyết nội dung (`eyebrow`, `badge`, `tag`, `tagline`, `subline`, `side_left/right`, `footer_left/right`, `author_role`) — **chờ quyết định biên tập của user**
- Nhạc nền CC-BY sau cờ config, mặc định TẮT. Bật thì bắt buộc có `attribution` không rỗng, thiếu là dừng render
- Video hiện 30s/4 scene — render không cắt, Composer viết ngắn. Muốn dài hơn phải siết prompt Composer, không sửa aigen

---

## 8. Chưa mở — có chủ đích

| Việc | Điều kiện mở |
|---|---|
| **Webapp** | Store phải qua test phục hồi (Bước 5.4). Webapp đọc chính store đó |
| **Avatar video** | Cắm **sau adapter** trong aigen như render target mới. **Không** dựng pipeline song song — sẽ nhân đôi toàn bộ tầng guardrail |
| **Explanatory Infographic** | = theme Light + layout L6/L7 đã có trong đặc tả. **Không xây mới** |
| **Gate 3 publish** | Biên của MVP: hệ thống dừng ở Drive + AssetPath |
| **Bố cục có điều kiện** | Đơn chủ đề → layout theme D1-D6; đa chủ thể → giữ hiện tại. Thiếu tín hiệu phân biệt (đếm subject không đủ — bài PNJ nhiều chủ thể nhưng một chủ đề) |
| **Semantic Validator** | Module shadow đã xây xong, unit test 7/7 pass, nằm trên `feature/semantic-validator`, **chưa merge**. Là tài sản, chưa tới lúc dùng |

---

## 8B. LỘ TRÌNH GIAI ĐOẠN TIẾP THEO — bốn nhiệm vụ lớn

Thứ tự ưu tiên do chủ dự án chốt: **1 → 2 → 3 → 4**. Mục 4 làm sau cùng.

### NV1 — Xây Webapp cho hệ thống

**Mục tiêu:** UI thứ hai đọc từ store, song song với Sheet. Sheet vốn chỉ là view;
webapp là view đầy đủ hơn, không bị giới hạn 1500 ký tự mỗi ô.

**Điều kiện tiên quyết:** store phải qua **test phục hồi (Bước 5.4)** — xoá vài
dòng Sheet, chạy sync, Sheet trở lại nguyên vẹn. Chưa đạt thì webapp xây trên
móng chưa đông.

**Ràng buộc kiến trúc:**
- Webapp đọc **store**, không đọc Sheet. Cùng nguyên tắc đã áp cho renderer.
- Không dựng schema riêng. Dùng đúng `content_units` / `brief_status` hiện có.
- Sheet **không bị thay thế** — hai view song song, cùng một nguồn sự thật.

**Nên gộp với NV3 mục 7.5 (thiết kế lại DB).** Webapp cần truy vấn theo TopicKey,
theo ngày, theo trạng thái — nếu schema chưa có `topics`/`artifacts`/`assets`
tách bạch thì webapp sẽ phải tự chắp vá, rồi phải viết lại khi DB đổi.

**Chưa quyết:** stack (React/Vue/server-rendered), có auth không, chạy trên VPS
hay host riêng, có thay Gate 1/Gate 2 không hay chỉ đọc.

---

### NV2 — Video tin tức: chất lượng tốt và ổn định hơn

**Trạng thái hiện tại:** luồng chạy được (video 30,5s, 4 scene, H.264 1080×1920
+ AAC, có Ken Burns, xfade, nhạc nền sau cờ config). Nhưng chủ dự án nghiệm thu
lô 3/8: *"nội dung hời hợt, kém chất lượng"*.

**Chưa điều tra nguyên nhân.** Ba hướng nghi vấn, cần khảo sát trước khi sửa:

1. **Rules Video Script có hướng dẫn chiều sâu nội dung không**, hay chỉ có ràng
   buộc kỹ thuật (số cảnh, độ dài, timecode)? — nằm trong Việc 6 câu 2 (§6).
2. **Video 30s/4 scene là do render cắt hay do Composer viết ngắn?** Đã xác minh:
   render KHÔNG cắt, Composer viết ngắn (narration 254 ký tự tổng). → Muốn dài
   hơn phải siết **prompt Composer**, không sửa aigen.
3. **10 ô chrome template chưa có nội dung** (`eyebrow`, `badge`, `tag`,
   `tagline`, `subline`, `side_left/right`, `footer_left/right`, `author_role`).
   Video ra đúng nội dung nhưng **thiếu khung** → trông sơ sài.
   ⚠️ Đây là **quyết định biên tập của chủ dự án**, không phải kỹ thuật. Chặn
   mọi việc template video cho tới khi có.

**Nợ đã biết:** `frame-market-ticker` tràn lề phải khi đủ 4 dòng · `speechLayer:
"off"` (bật lại phải kiểm phiên âm không xử lý 2 lần) · 82 assert test
`production-spec` chưa ai đọc từng dòng.

**Thứ tự đề xuất:** chủ dự án quyết 10 ô chrome → khảo sát rules video → siết
prompt Composer cho độ dài/chiều sâu → sửa template.

---

### NV3 — Hai tính năng MỚI

#### 3.1. Báo cáo tổng hợp thị trường hàng ngày

**Khác bản chất với mọi thứ đã xây.** Toàn bộ hệ thống hiện tại là **một bài
nguồn → một sản phẩm**. Báo cáo tổng hợp là **nhiều nguồn → một sản phẩm**.

Hệ quả kiến trúc — cần quyết trước khi code:
- `TopicKey` neo theo canonical URL của **một** bài. Báo cáo tổng hợp không có
  URL gốc duy nhất → cần loại khoá khác, hoặc một `topic_key` tổng hợp có quy
  tắc riêng (ví dụ `daily-report:YYYY-MM-DD`).
- `content_units` hiện gắn với một `source` là câu nguyên văn từ một bài. Báo
  cáo tổng hợp phải gộp unit từ **nhiều bài** → mỗi unit cần mang thêm định danh
  bài gốc, nếu không sẽ mất khả năng truy nguồn.
- Router hiện quyết định tuyến cho một chủ đề. Báo cáo tổng hợp không đi qua
  Router theo cách đó.
- Gate 1 duyệt **chủ đề**. Báo cáo tổng hợp duyệt cái gì — duyệt danh sách bài
  đưa vào, hay duyệt bản nháp?

**Chưa quyết:** phạm vi (toàn thị trường / theo ngành / theo watchlist), tần suất
(cuối phiên / sáng hôm sau), định dạng đầu ra (Article dài / Infographic /
cả hai / PDF), nguồn dữ liệu (chỉ tin đã crawl hay thêm dữ liệu giá).

⚠️ **Đây là nhiệm vụ có rủi ro thiết kế cao nhất trong bốn nhiệm vụ.** Đừng bắt
đầu bằng code — bắt đầu bằng việc chốt bốn câu trên với chủ dự án.

#### 3.2. Đóng dấu brand-kit / logo vào ảnh

**Phần lớn đã có sẵn** trong `brand_stamp.py`: logo góc trên phải, band đáy với
nguồn + disclaimer, guardrail phát hiện chữ trong bbox logo và bbox metadata,
màu lấy từ token theme.

**Phần còn thiếu:** brand-kit đầy đủ của FVA Capital chưa được sản xuất. Đã được
ghi nhận là "hoãn tới Phase 6 render" từ giai đoạn trước và chưa làm.

Cần chốt với chủ dự án: bộ logo đầy đủ (biến thể sáng/tối/đơn sắc) · palette
chính thức · font chính thức · footer chuẩn · slogan có dùng không và dùng ở đâu.

⚠️ **Có một ràng buộc đã trả giá 3 vòng sửa để có, không được phá:**
fit-inside cấm center-crop · phần dư dồn lên đỉnh · logo nằm trọn trong vùng
đệm, không đè nội dung · band đáy tách biệt · assert `scale_factor ≤ 1.0`.
Mọi thay đổi thẩm mỹ phải chạy lại test regression "2 vạch đỉnh/đáy không mất"
và test A3 (ảnh nền lấp kín 100% khung).

**Đây là nhiệm vụ dễ nhất trong bốn** — chủ yếu là chốt tài sản thương hiệu rồi
thay token, không phải viết logic mới.

---

### NV4 — aigen thành nhà máy đa chức năng (LÀM SAU CÙNG)

**Mục tiêu:** nhiều định dạng đầu vào (tin thô · video script · video scene
schema · video source + text script) và nhiều luồng đầu ra (avatar video và các
loại khác, song song luồng tin tức hiện có).

**Ranh giới kiến trúc đã chốt — đọc kỹ trước khi thiết kế:**

Cây cầu vendor-neutral hiện tại:
```
CONTENT.Output → scene-builder → guardrail-2 → voice → alias-guardrail → adapter → [render target]
```

Toàn bộ đoạn **trước adapter** là vendor-neutral: guardrail nội dung, chuẩn hoá
giọng, chặn ticker lạ — mọi loại video đều cần y hệt. Chỉ **sau adapter** mới là
phần riêng của từng vendor.

⚠️ **Avatar là render target mới cắm SAU adapter, KHÔNG phải pipeline song song
từ đầu.** Chủ dự án từng nêu hướng "line riêng song song" vì lo avatar phức tạp
khó tích hợp vào aigen — lo ngại đó đúng, nhưng lối ra là cho avatar một **render
target riêng cạnh aigen**, dùng chung cây cầu:

```
                                  ┌→ adapter-aigen  → AIGEN (ken-burns, hiện có)
... → alias-guardrail → adapter ──┤
                                  └→ adapter-avatar → AVATAR (phức tạp tuỳ ý)
```

Tách cả tầng guardrail sẽ **nhân đôi toàn bộ luật an toàn nội dung tài chính** và
buộc phải giữ đồng bộ mãi mãi — đúng loại lỗi liên tầng mà dự án đã trả giá.

**Rủi ro cần chặn:** khi thiết kế đầu vào đa định dạng, ai đó sẽ tìm một schema
để nhận input và có thể nhặt nhầm `media_factory/spec.py::ProductionSpec` —
dataclass đã chết. **Phải xoá nó trước khi bắt đầu NV4**, không thì nó thành móng
cho nhánh mới.

**Nhiều định dạng đầu vào** nghĩa là cần một lớp chuẩn hoá: mọi loại input đều
quy về `CONTENT.Output` trước khi vào scene-builder. Đừng cho mỗi loại input một
đường riêng.

---

### Phụ thuộc giữa bốn nhiệm vụ

| Nhiệm vụ | Chặn bởi |
|---|---|
| NV1 Webapp | Test phục hồi 5.4 · nên gộp với thiết kế lại DB (§7.5) |
| NV2 Video | Chủ dự án quyết 10 ô chrome · khảo sát rules video (Việc 6 câu 2) |
| NV3.1 Báo cáo tổng hợp | Chốt 4 câu thiết kế (khoá, truy nguồn, Router, Gate) |
| NV3.2 Brand-kit | Chủ dự án cung cấp tài sản thương hiệu |
| NV4 aigen đa chức năng | Xoá `ProductionSpec` dataclass · NV2 xong (video tin tức phải ổn trước khi nhân bản) |

**Việc làm được ngay, không chờ ai:** khảo sát Việc 6 (§6) · xoá `ProductionSpec`
dead code · thiết kế lại DB (§7.5).


---

## 9. BÀI HỌC — đọc kỹ, đây là phần đắt nhất

### 9.1. Tên biến đa nghĩa là nguồn bug tốn nhất dự án

`source_url` từng tồn tại ở hai tầng với **ba nghĩa**: tên nguồn ("CafeF") / URL đầy đủ / domain rút gọn. `production.py` ghi khoá `"source"`, `spec.py` khai báo `source_url`. Bug mất dòng "Nguồn:" trên ảnh tốn **hơn 10 lượt** điều tra.

**Nguyên tắc user đã chốt, áp cho mọi agent:**
1. Tên biến **đơn nghĩa** — một biến một nghĩa. Cấm tên ghép đa nghĩa.
2. Mỗi hàm **một việc**.
3. **Không tạo giá trị phái sinh** khi dữ liệu gốc đã có sẵn. DB có sẵn `source`="CafeF" và `url` — đọc thẳng, đừng gọi `domain_of()` để rút.

**Bài học phân việc:** bug này tồn tại được vì `source` sống ở tầng production, `source_url` ở tầng spec, **ranh giới giữa hai tầng không ai sở hữu**. → Việc liên tầng chặt (schema/spec) giao **một agent làm trọn**, đừng chia theo tầng.

### 9.2. Lead sai vì suy luận thay vì đọc code — ít nhất 5 lần

| Lead cũ khẳng định | Thực tế |
|---|---|
| gpt-image-2 có enum kích thước cố định | Nhận **mọi** kích thước chia hết 16 → Δratio từ 0,135 xuống 0,0002 |
| `TopicKey` = canonical URL | Là sha256 cắt 16 hex, không parse ngược được |
| Article không có đường đóng disclaimer | Có **2 điểm**, `render_analysis()` luôn nối vào cuối |
| `ProductionSpec` là cây cầu đang chạy | Dataclass Python đã chết; cây cầu ở aigen |
| Ảnh 28/07 "vi phạm theme" | Hai bộ quy tắc cho hai hình dạng nội dung; ảnh chạy **đúng** bộ của nó |
| Bố cục fit-inside sẽ đẹp | Đẻ ra viền lộ như khung tranh — lỗi trong đặc tả của Lead |

**→ Mọi mệnh đề về "code hiện đang làm gì" phải kèm một bước bắt agent xác minh.** Câu *"tự xác minh, không tin con số trong prompt này"* đã tạo ra phát hiện giá trị nhất sprint.

**→ Nếu Lead khẳng định kiến trúc mà không dẫn được bằng chứng code, coi đó là suy đoán.**

### 9.3. Đo bằng mô hình khác mô hình production = số vô giá trị
Lượt A/B rules sinh mẫu bằng Codex trong khi Composer chạy Opus. Toàn bộ bảng số phải bỏ. Dấu hiệu nhận biết: chỉ số sạch **tuyệt đối** (0,00 trên mọi mẫu) — đó là mô hình né danh sách cấm nó vừa đọc, không phải văn hay hơn.

### 9.4. Checklist dài tạo cảm giác tick xong là xong
agent-B từng chấm "cắt cụt ở đáy — 6/6 PASS" trong khi thực tế 6/6 FAIL. Nó đối chiếu **đúng** checklist được giao; checklist thiếu. → Chấm bằng **số đo trong log**, không bằng mắt.

### 9.5. Prompt dài không tốn tiền, nhưng mở rộng diện tích để Lead sai
Chênh lệch token giữa prompt 3.000 và 1.000 token ≈ 5 cent/phiên. Không đáng kể. **Nhưng** lỗi center-crop nằm trong chính đặc tả Lead — viết dài là mở rộng chỗ để sai.

Giữ lại: điều kiện **DỪNG KHI** · ranh giới file · lý do ở chỗ agent có thể làm đúng vì lý do sai.
Cắt: boilerplate lặp · bằng chứng Lead đã tự quan sát (để agent tự kiểm) · giải thích ở quyết định hiển nhiên.

### 9.6. Ghi tên nhánh ngay dòng đầu mọi prompt
Có lần prompt không ghi nhánh, agent checkout thẳng `develop` và làm việc ở đó.

### 9.7. Regression làm TRƯỚC khi đổi routing
Lỗi 6 ảnh 24/07 đều lọt lưới unit test, chỉ lộ khi chạy thật. Test viết sau khi sửa thì không bắt được gì.

### 9.8. Giá trị "tạm" sẽ nằm lại vĩnh viễn nếu không có hạn chót
Chuỗi disclaimer từng tồn tại ở **4 nơi với 3 cách viết**. Mọi adapter tương thích ngược phải ghi **ngày hết hạn cụ thể** trong comment.

### 9.9. `content-rules/` — thư mục anh em ngoài git
Chứa đặc tả gốc, **không theo version control**. Bản copy trong repo từng cố ý lệch một dòng so với bản gốc. **READ-ONLY với mọi agent.** Muốn đổi → đề xuất trong STOP-REPORT, user sửa tay.

---

## 10. Cách làm việc với chủ dự án

**Trung Tran là người quyết định cuối.** Anh ấy đã phát hiện phần lớn sai lầm của Lead cũ:
- `source_url` đa nghĩa
- Lead lẫn hai thứ trùng tên `ProductionSpec`
- Lead lan man sang avatar khi đang cần đóng MVP
- "Sao quy trình lại dừng vì giới hạn Sheet?" — câu hỏi vạch ra store-as-truth chưa khép kín
- Ảnh 28/07 chạy đúng rules, không phải vi phạm theme

**→ Đừng bỏ user ra khỏi vòng lặp.** Vai trò đúng: bỏ user khỏi việc **trung chuyển dữ liệu** giữa các agent, giữ user ở **cổng quyết định** — duyệt Gate 1/Gate 2, bật đèn cho thao tác xoá, chốt lựa chọn thương hiệu, nghiệm thu ảnh/video bằng mắt.

**Phong cách làm việc mong đợi:**
- Prompt ngắn gọn, tập trung **làm gì — làm thế nào**, không diễn giải dài
- Mỗi agent một file prompt riêng, **không gom chung**
- Phản hồi báo cáo cũng viết riêng từng agent
- Không tạo file mới khi nội dung ngắn — xuất thẳng dạng khung text
- **Đừng mỗi lượt lại kết luận "một lỗi nghiêm trọng"** rồi mở điều tra mới — user đã phàn nàn về việc này. Đóng việc, đừng mở thêm.

---

## 11. Việc nên làm ngay khi tiếp nhận

1. **Xác nhận Task Scheduler đã đăng ký chưa** (mục 1). Chưa → làm ngay, đây là lỗi im lặng.
0. **Đọc §8B — lộ trình bốn nhiệm vụ lớn giai đoạn tiếp theo.** Thứ tự ưu tiên chủ dự án đã chốt: Webapp → Video → Tính năng mới → aigen đa chức năng.
2. **Hỏi agent-A trạng thái Việc 1-6** (mục 6). Việc 1 là nguyên nhân gốc của "không có bài Long-Form".
3. **Đọc kết quả khảo sát Việc 6** — nó khoanh được nguyên nhân của cả 4 vấn đề chất lượng.
4. **Quyết định về mục 7.1** — chất lượng bài viết. Đề xuất: đo trước, sửa sau.
5. **Dựng dropdown cột Type** sau khi agent-A xác nhận bảng 5 giá trị.

## 12. Mốc quan trọng

| Ngày | Sự kiện |
|---|---|
| 29/07 | MVP đóng — tag `MVP-29-07-2026` |
| 30/07 | Rules v3.4 · theme Dark hard-code · quy ước tên file rules |
| 31/07 | `content_units` thay `facts[]` · Router gỡ cứng nhắc |
| 03/08 | Merge agent-A + agent-C · chạy e2e lô 28/07+29/07+03/08 |

**Nhánh đáng chú ý:**
- `develop` — nhánh chính
- `feature/semantic-validator` — module shadow, chưa merge, là tài sản
- `feature/webhook-store` — **GIỮ làm tham khảo, KHÔNG merge** (đi sau develop 39 commit, 10 conflict, nội dung đã có bản mới hơn)
