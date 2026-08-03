# BÀN GIAO — 2026-07-29, đóng mốc MVP (agent-B)

> Đọc file này TRƯỚC. Bàn giao TRỌN VẸN một mốc (khác `HANDOFF_2026-07-26.md`
> là bàn giao giữa chừng). Hệ thống ĐANG CHẠY ĐƯỢC end-to-end; phần còn lại là
> mở rộng, không phải vá cho chạy.
>
> Lịch sử quyết định: `PROJECT_HANDOFF_P5.md`. Bản đồ code: `docs/MODULE_INDEX.md`.
> Quy tắc bất biến: `CLAUDE.md`. Nợ dài hạn: `docs/VPS_MIGRATION_BACKLOG.md`.

**MỤC LỤC** — §1 trạng thái · §2 nhánh · §3 việc đã làm · §4 nợ của
marketing-automation · **§4B nợ của aigen-pipeline** · **§4C luồng nối 2 repo +
trạng thái test** · §5 hạ tầng · §6 lệnh hay dùng · §7 nguyên tắc.

> Bổ sung 2026-07-30: bản đầu chỉ viết từ góc nhìn marketing-automation. §4B và
> §4C được thêm vì thiếu 2 thứ đó thì người tiếp nhận PHẢI mò: nợ riêng của
> aigen, và cách 2 repo nối vào nhau.

---

## 1. TRẠNG THÁI — HỆ THỐNG ĐÃ THÔNG TOÀN BỘ

Luồng dưới đây đã chạy THẬT ngày 29/07, qua đúng đường vận hành (người bấm trên
Sheet), KHÔNG thao tác tay nào ở giữa:

```
crawl (lọc theo NGÀY ĐĂNG thật)
  -> Gate 1 duyệt Context -> hàng đợi (execution_queue)
  -> Composer + guardrail số
  -> Gate 2 duyệt Content -> job render_assets
       article     -> Drive -> AssetPath
       infographic -> 1 ảnh theo render_hint -> Drive -> AssetPath
       video       -> aigen-pipeline -> OmniVoice TTS -> ffmpeg -> .mp4 -> Drive
  -> Gate 3 duyệt Public (PENDING, chờ người — khâu đăng CHƯA xây)
```

Bằng chứng cụ thể: `video.mp4` H.264 1080×1920 + AAC, 30.5s, đã lên Drive với
AssetPath bấm được. Đây là lần đầu hệ thống đi từ tin tức thô tới video thành
phẩm.

### Mốc git

| Repo | main | tag | develop |
|---|---|---|---|
| marketing-automation | `4e8b40f` | `MVP-29-07-2026` | `771f8ec` |
| aigen-pipeline | `8ce5b31` | `MVP-thong-luong-29-07-2026` | `6e69f6c` |

Test: **675 Python** + **244 aigen** + **13 Sheet UI** (chạy trên Sheet test
riêng, tự reset).

### Tiến trình cần chạy

```bash
python scripts/queue_worker.py       # BẮT BUỘC — không có nó Sheet không phản hồi
python system_power_on.py            # lịch crawl + asset server (asset_server_enabled=true)
```

⚠️ **PHẢI RESTART `queue_worker.py` sau MỌI thay đổi code/config** — Python
không tự nạp lại module. Đã mất thời gian nhiều lần vì quên điều này: sửa xong,
chạy lại, thấy hành vi cũ, tưởng bản vá sai.

---

## 2. NHÁNH — DỌN ĐƯỢC GÌ

Kiểm bằng `git branch --merged develop` + `git rev-list --count develop..<branch>`:

| Nhánh | Đã merge vào develop | Commit chưa có trong develop | Kết luận |
|---|---|---|---|
| `feature/infographic-frame` | CÓ | 0 | **XOÁ ĐƯỢC** (local + remote) |
| `fix/infographic-disclaimer-single-source` | CÓ | 0 | **XOÁ ĐƯỢC** (local + remote) |
| `origin/feature/webhook-store` | KHÔNG | 6 | **GIỮ** — xem dưới |
| `feature/store-as-truth` | đã merge, remote đã xoá | — | xong |

```bash
git branch -d feature/infographic-frame fix/infographic-disclaimer-single-source
git push origin --delete feature/infographic-frame fix/infographic-disclaimer-single-source
```

### `feature/webhook-store` — GIỮ nhưng KHÔNG merge được

Lead quyết giữ, chờ kiểm định lại tính năng *"user click → webhook gọi luồng
thực thi"*. Nhưng phải biết trước:

- Đi sau develop **39 commit**, thử merge → **10 conflict** (`add/add` trên
  `store/document_store.py`, `store/schema.sql`, `api/main.py`…).
- **Nội dung của nó ĐÃ nằm trên develop rồi, bản mới hơn** — `document_store.py`
  203 dòng (develop) vs 185 (nhánh); chênh lệch chính là 3 bug schema agent-A đã
  sửa. `apps_script/` giống hệt.
- Merge nó bây giờ là **kéo lùi code**.

→ Khi làm webhook, **viết lại trên develop hiện tại**, dùng nhánh cũ làm tài
liệu tham khảo. `apps_script/execute_trigger.gs` vẫn còn nguyên trên develop.

### Tối ưu khung render infographic: MỞ NHÁNH MỚI

`feature/infographic-frame` đã merge và **tụt hậu 20 commit** so với develop.
Dùng lại nó nghĩa là bắt đầu từ nền cũ, vẫn phải rebase — không được gì mà rối
lịch sử. Ngoài ra chế độ multi-agent cần mỗi nhánh một chủ rõ ràng.

```bash
git checkout develop && git pull
git checkout -b feature/infographic-polish
```

**Vùng file cho việc này:** `src/twmkt/render/ai_full.py` (sinh ảnh AI),
`src/twmkt/render/brand_stamp.py` (đóng logo + disclaimer LÊN TRÊN ảnh, Pillow),
`config/brand.yaml` (brand kit MỘT NGUỒN).

---

## 3. ĐÃ XỬ LÝ TRONG ĐỢT NÀY

### 3.1. Bug "source rỗng" trên infographic — GIẢI QUYẾT DỨT ĐIỂM

Đây là việc treo từ bàn giao 26/07, ba lượt chẩn đoán trước đều sai.

**Nguyên nhân thật:** `render_production_assets.py` đọc `item["output"]` từ ô
Sheet — ô đó chỉ là **preview cắt 1500 ký tự**, nên JSON infographic dài bị
cụt. Không phải lỗi ở tầng dựng field `source` như 3 lượt trước đoán.

Kiểm chứng trên dữ liệu MỚI qua pipeline thật (không phải dữ liệu soạn tay):
`source = 'cafef.vn'`, output 2412 ký tự — **vượt ngưỡng 1500**, tức là đúng ca
gây bug. Nay đọc thẳng `ps.read_content_output()` từ store.

Ghi đúng bản chất: đây là **sửa bug thật** (đổi nguồn đọc), KHÔNG phải "dữ liệu
sạch nên tự hết" như giả thuyết cũ.

### 3.2. Ảnh render của agent-A (Bước 5.3) — đã nghiệm thu

3 ảnh (9:16 / 4:5 / 1:1): Nguồn ✓, disclaimer đúng nguyên văn ✓, logo FVA ✓,
không cắt/đè chữ. Hai điểm thẩm mỹ nhỏ đã báo Lead, không chặn.

⚠️ **Guardrail-2 nhánh ảnh đã bị xoá từ 2026-07-21**, nên KHÔNG có lớp code nào
đối chiếu số trên ảnh với `facts[]`. Gate 2 + Gate 3 (người) là 2 lớp chặn duy
nhất còn lại.

### 3.3. Danh sách bug đã vá (13)

Không cái nào bị test đơn vị bắt được — tất cả lộ ra khi chạy thật.

| # | Bug | Nguồn |
|---|---|---|
| 1 | Đọc JSON từ ô Sheet bị cắt 1500 ký tự | có sẵn |
| 2 | Mất lượt duyệt: render-từ-store ghi đè APPROVE người vừa bấm | có sẵn |
| 3 | AssetPath bị xoá vài giây sau khi ghi | có sẵn |
| 4 | Prompt mời Composer chọn `16:9` mà renderer không dựng được | có sẵn |
| 5 | Chặn idempotent đọc `asset_path` từ Sheet thay vì store | có sẵn |
| 6 | Tuyến article KHÔNG BAO GIỜ lên Drive (`asset = ảnh`) | có sẵn |
| 7 | Báo "sửa hỏng ở Gate 2" cho dòng router đã SKIPPED | có sẵn |
| 8 | `ClaudeCodeLLM` nuốt lý do lỗi thật (đọc stderr, CLI ghi stdout) | có sẵn |
| 9 | Seam gọi `npm run pipeline` — sai cổng, sai định dạng, không bật TTS | có sẵn |
| 10 | `npm` không resolve trên Windows (shim `.cmd`, thiếu `shutil.which`) | có sẵn |
| 11 | `produce.ts` chạy `main()` khi bị import → exit 2 | có sẵn |
| 12 | `produce.ts` khai có ghi log nhưng dùng `stdio:"ignore"` → mù khi lỗi | có sẵn |
| 13 | Timestamp bị render ghi đè thành hôm nay mỗi lượt | có sẵn |

Kèm 3 bug **do agent-B tạo ra trong chính phiên này**, đã vá:
- Output Type: tuyến router tự tắt vẫn ra dòng SKIPPED thừa
- Link Drive không gán vì so với hằng `_PRIMARY_RATIO="4:5"`
- Thêm cột `request_id` vào schema mà thiếu migration → worker chết vòng poll đầu

### 3.4. Mẫu chung — ĐỌC KỸ, sẽ lặp lại

**Mọi chỗ còn ĐỌC SHEET ĐỂ RA QUYẾT ĐỊNH đều hỏng.** Store là nguồn sự thật,
Sheet là bản chiếu. Ba nơi vi phạm (đọc JSON, ghi AssetPath, chặn idempotent)
đều gây lỗi **âm thầm** — không exception, không log, chỉ kết quả sai.

**`ws.clear()` xoá cả ĐỊNH DẠNG.** Đây là gốc của "băng màu liên tục biến mất"
và "thiết lập user bị ghi đè". `band_context_by_day()` tồn tại từ 23/07 và chạy
đúng — nhưng bị `clear()` xoá kết quả mỗi vòng worker. **Logic không mất, nó bị
ghi đè.** Nay render chỉ ghi GIÁ TRỊ (`values.update` không đụng format).

**Áp quy tắc rộng hơn phạm vi được nêu.** Lặp 3 lần trong phiên: dọn dead code
suýt xoá nhầm test còn sống; quy tắc phát âm mã CK suýt phá `GDP`/`NHNN`; bộ
lọc test khớp cả tên trong docstring. Luôn hỏi: *quy tắc này áp cho đúng tập
nào?*

**Đường dẫn tuyệt đối ngoài git.** Đổi tên thư mục repo làm chết venv
(`pyvenv.cfg`, `_editable_impl_*.pth`) — grep code và git đều không thấy.

---

## 4. NỢ — CHƯA XỬ LÝ

### 4.1. ƯU TIÊN CAO — Router/Brief quá khắt khe (đang chờ quyết định Lead)

Tài liệu: `codex-marketing/validators/reports/rules-ab/l3/LEAD_DECISION_INPUT_STRICTNESS.md`

Router đòi **vừa có số vừa có nhân vật/mạch chuyện** mới mở tuyến video; đòi
**dữ liệu định lượng** mới mở infographic. Tin tài chính hằng ngày hiếm khi đủ,
nên nhiều bài định tính (chính sách, diễn giải) bị SKIPPED oan. Quan sát thật
ngày 28-29/07: 3/3 chủ đề định hướng video đều bị router từ chối.

Gốc rễ theo tài liệu: `facts=[]` đang gánh HAI nghĩa — "Brief lỗi" và "nguồn
định tính hợp lệ". Đề xuất contract mới: `brief_status` + tách
`has_numeric_facts`/`has_qualitative_facts`.

**Lead đang trao đổi với lead khác, CHƯA chốt. ĐỪNG tự làm.**

Ý kiến agent-B đã gửi Lead (giữ lại để phiên sau không mất):
- §6 P0-5 *"bỏ `render_hint` khỏi Composer"* — nên cân nhắc lại: sẽ mất tính
  năng Composer chọn tỷ lệ ảnh vừa xây và đang chạy đúng (tiết kiệm 3 lần gọi
  API ảnh xuống 1). Đề xuất giữ `ratio` (quyết định *dung lượng*, người viết
  mới biết), bỏ `theme`/`palette` (thẩm mỹ, thuộc renderer).
- §7 Regression 10 ca nên làm **trước** khi sửa, không phải sau.
- §6 P0-1 adapter tương thích dữ liệu cũ cần **thời hạn** (đề xuất: bỏ sau khi
  retention 10 ngày cuốn hết dữ liệu cũ).

Thứ tự phase đã đề xuất: **A** loader rules v3.3/v3.4 + Output Type ép Composer
→ **B** 10 ca regression thành test → **C** contract Brief mới → **D** Router
→ **E** Explanatory Infographic.

### 4.2. Output Type ép Composer

Hiện `channels[loại] = router_đồng_ý AND người_chọn`. Yêu cầu Lead: khi Output
Type **tường minh**, router **mất quyền phủ quyết**; `AUTO` thì router tự quyết.

Lead quyết **hoãn**, làm cùng gói rules ở 4.1 (*"sửa ngay thì là sửa ngọn"*).

Lịch sử để khỏi tra lại: `output_channels` + `no_numeric_content` có từ
**2026-07-10** (`0bde337`); vế `AND Output Type` mới thêm **2026-07-25**
(`502a7f9`). Vấn đề đến từ vế CŨ.

### 4.3. Khâu publish (Gate 3)

Ngữ nghĩa đã CHỐT và ghi trong `sheets_board.py`, code CHƯA xây:
- `Social Link` (trước Gate 3, người điền): link kênh sẽ đăng
- `Duyệt Public` (Gate 3, người bấm)
- `Posting Status` (sau Gate 3, máy ghi): `POSTING...` → `DONE` | `FAILED`

Bộ giá trị chốt sẵn để khi implement khỏi đổi schema lần nữa. Hiện Gate 3 duyệt
xong **không dẫn tới hành động nào** — đúng thiết kế giai đoạn này.

### 4.4. Chất lượng nội dung

- **Video ngắn** (30s, 4 scene, narration 254 ký tự tổng). Render KHÔNG cắt gì
  — Composer viết ngắn. Muốn dài hơn thì siết **prompt Composer**, không phải
  sửa aigen.
- **Chữ tràn khung**: adapter cảnh báo `hero` 71 ký tự / giới hạn 10, `desc`
  200/90. Renderer không tự chặn. Cần mắt người xác nhận rồi siết prompt.
- **Tối ưu khung render infographic** — việc Lead đã đặt, mở nhánh mới (mục 2).

### 4.5. Kỹ thuật

- **Diff từng ô** thay vì ghi cả vùng dữ liệu. Hiện ghi 1 lệnh `values.update`
  cho toàn vùng — đủ tốt ở ~15 dòng, nên làm khi lên hàng trăm dòng.
- **Cửa sổ mất thao tác người vẫn còn** (~vài giây giữa ingest và render). Đóng
  hẳn cần render CHỈ các cột máy-sở-hữu.
- **Khoá ô theo điều kiện là không thể** qua Sheets API. Khi job đang chạy,
  thay đổi của người bị **bỏ qua im lặng** — ô tự trả về ở lượt render sau,
  người dễ tưởng bấm hụt.
- **Protected Range không chặn được chủ sở hữu Sheet** — Google không cho khoá
  owner khỏi file của họ. Với Lead đây là lớp NHẮC.
- **Venv dễ chết khi đổi đường dẫn** — nên dựng lại venv thay vì sửa tay
  `pyvenv.cfg` khi lên VPS.
- **Task Scheduler cho `queue_worker.py`** — chưa đăng ký, cần chạy PowerShell
  quyền Admin:
  ```powershell
  $A = New-ScheduledTaskAction -Execute "<python.exe>" -Argument "-u scripts\queue_worker.py" -WorkingDirectory "<repo>"
  $T = New-ScheduledTaskTrigger -AtStartup
  Register-ScheduledTask -TaskName "twmkt-queue-worker" -Action $A -Trigger $T -RunLevel Highest -User "SYSTEM" -Force
  ```
  Nhớ `-u` (unbuffered) — thiếu nó log im lặng hoàn toàn.
- **Quota Sheets API 60 read/phút** là ràng buộc thật. `poll_interval_s` đã hạ
  3s → 20s. Đừng chạy `test_sheet_ui.py` khi worker đang chạy — tranh quota.

---

---

## 4B. NỢ RIÊNG CỦA `aigen-pipeline`

> Bổ sung 2026-07-30 — bản đầu của bàn giao viết từ góc nhìn
> marketing-automation, nợ của aigen gần như vắng mặt. Người tiếp nhận đọc CẢ
> mục 4 và 4B.

### 4B.1. Ô "chrome" chưa có ngữ nghĩa biên tập — video ra thiếu khung

`scene-builder` đổ `payload` (từ vựng TRUNG LẬP VENDOR) vào `slots` (từ vựng
TEMPLATE). `withChromeSlots()` đã lấp được `brand` (từ `outro.brand_name`) và
`kicker` (từ `output.source`) — MAP từ dữ liệu ĐÃ CÓ, không bịa.

CÒN TRỐNG, cần **quyết định BIÊN TẬP** chứ không phải kỹ thuật:
`eyebrow` · `side_left` · `side_right` · `badge` · `footer_left` ·
`footer_right` · `author_role` · `subline` · `tag` · `tagline`.

Hệ quả: video ra đúng nội dung nhưng **thiếu chrome** (khung trang trí, nhãn
phụ). Không chặn render vì `required:false` đã hạ cho ô thuần trang trí.

⚠️ `TEMPLATE_SLOTS` **KHÔNG đồng nhất giữa các template**:
`frame-market-ticker` không có `kicker`; `frame-news-lower-third` không có
`brand`; chỉ `frame-liquid-bg-hero` và `frame-quote-pull` có đủ cả hai. Kiểm
`TEMPLATE_SLOTS[templateId]` trước khi sửa `withChromeSlots` —
`fillSlotDefaults()` sẽ DROP field ngoài slot set của template (hợp đồng đã có,
không phải bug).

### 4B.2. Guardrail số — 3 việc treo chờ quyết định

Chi tiết đầy đủ: `marketing-automation/tasks/ACTIVE_TASK.md` §V2/V3/R3. Tóm
tắt để không phải tra:

- **V2 — word-scan trước voice là bề mặt dương-tính-giả.** `checkText()` luôn
  chạy CẢ 2 lối (chữ số + số-viết-bằng-chữ). Đứng TRƯỚC `voice`, narration đúng
  hợp đồng là dạng chữ số, nên lối word-scan chỉ còn tạo oan ("Quý **hai năm**
  nay" → parse thành 2 → chặn oan). Tắt nó thì bài nào Composer viết sai sẽ lọt
  hoàn toàn không bị kiểm. Nên làm V1 (chặn contract violation ở đầu nguồn)
  trước, rồi mới tắt an tâm.
- **V3 — số TRẦN không đơn vị KHÔNG được soi.** `_DIGIT_MAGNITUDE_RE` chỉ bắt
  số CÓ đơn vị (`%|tỷ|triệu|đồng|usd`). Nên "2021"/"2030" trần không bị kiểm.
  Đây là tính chất CÓ SẴN từ lâu, không phải hồi quy. Siết thì phải sửa **ĐỒNG
  BỘ 2 REPO**.
- **R3 — delta chéo câu bị từ chối ĐÚNG chức năng.** `_find_shared_sentence`
  đòi from/to CÙNG 1 câu (chống bịa). Bài "công ty lỗ" có 2 số ở 2 câu liền kề
  nên không ghép được thành delta → Composer dùng số ngoài facts → guardrail
  chặn cấp (a). Cần quyết 1 trong 3: sửa PROMPT Brief emit thêm scalar / chấp
  nhận chặn / nới `_find_shared_sentence` (rủi ro chống-bịa, KHÔNG khuyến nghị).

⚠️ **LUẬT CỨNG: sửa bất kỳ logic số/guardrail nào PHẢI sửa ĐỒNG BỘ CẢ 2 REPO**
(`media_factory/numbers.py` Python + `production-spec/guardrail/verify-spec.ts`
TS), test 2 bên cùng lượt. Đã có tiền lệ: lỗi "linh" và lỗi tokenize dấu câu
đều phải vá đồng bộ.

### 4B.3. Cạm bẫy template đã thành tài liệu — ĐỌC TRƯỚC KHI SỬA RENDER

`docs/ADAPTER_UNDOCUMENTED_QUIRKS.md` — 10 mục, đều là bẫy đã trả giá:

1. Key `inputs` sai/gõ nhầm **thất bại IM LẶNG** — foot-gun số 1
2. Bỏ trống key có thể làm hiện **copy DEMO baked-in**, không phải ô trắng
3. `cta` trên `frame-liquid-bg-hero` là ghost slot chỉ có ở 16:9
4. `frame-logo-outro` từng chỉ có 3 slot — không có disclaimer
5. Template danh sách **cắt ở 5 mục, im lặng**
6. `frame-icon-list.title` cần khoảng trắng cuối, thiếu là chữ dính nhau
7. `voiceText` normalize là **2 cơ chế khác nhau, KHÔNG tự kết hợp**
8. Forecast/comparison cần chọn "không có winner" tường minh
9. **Brand KHÔNG data-driven** — nhiều template hardcode mark FVA
10. Giới hạn ký tự slot là thật nhưng **mềm** — chỉ adapter cảnh báo

Mục 10 đang gây hệ quả thấy được — cảnh báo THẬT lúc chạy (xem
`tasks/ACTIVE_TASK.md` dòng ~238): `primary_url` **67 ký tự / giới hạn CATALOG
40**, `hero` **17-30 / giới hạn 10**. Chữ có thể tràn hoặc bị cắt trên khung
hình. Cần MẮT NGƯỜI xem video xác nhận có tràn thật không, rồi siết PROMPT
Composer bên marketing-automation — KHÔNG vá renderer.

### 4B.4. Nợ nhỏ

- **82 assert test `production-spec` chưa ai đọc từng dòng** xem có expect viết
  sai theo (nợ từ PHA 3).
- **HeyGen avatar**: `visual_kind="avatar"` nằm TRONG `VISUAL_KINDS` nhưng cũng
  trong `DEFERRED_VISUAL_KINDS` — chưa nguồn nào sinh. Đề xuất ở
  `docs/AVATAR_HEYGEN_PROPOSAL.md`.
- **`speechLayer: "off"`** trong `config/tts.config.json` — tầng fvb (normalizer
  Python, bảng 108 mục viết tay) KHÔNG chạy trong đường aigen. Đây là lý do
  phải sinh `pronunciation_dict.vi.json`. Nếu sau này BẬT speechLayer thì xem
  lại kẻo phiên âm bị xử lý 2 lần.
- **Video ngắn** (30s, 4 scene): render KHÔNG cắt gì — Composer viết ngắn
  (narration 254 ký tự tổng). Muốn dài hơn thì siết prompt Composer bên
  marketing-automation, KHÔNG sửa aigen.

---

## 4C. LUỒNG NỐI 2 REPO — CHỈ DẪN KỸ THUẬT

> Bổ sung 2026-07-30. Đây là phần dễ mò mẫm nhất: 2 repo, 2 ngôn ngữ, 2 kho dữ
> liệu, và nhiều tên gọi TRÙNG NHAU.

### 4C.1. Hợp đồng: `CONTENT.Output`

Ranh giới DUY NHẤT giữa 2 repo. Đặc tả: `docs/CONTENT_OUTPUT_SCHEMA.md` —
**tồn tại GIỐNG HỆT ở CẢ HAI repo**, sửa phải đồng bộ.

marketing-automation (Python) **sinh**; aigen (TypeScript) **biến thành video**.
Không có kênh nào khác: aigen KHÔNG đọc Sheet, KHÔNG đọc SQLite store.

⚠️ File bàn giao này chỉ nằm trong repo **marketing-automation**. Người tiếp
nhận mà mở repo aigen trước sẽ KHÔNG thấy nó — nếu nhận việc bên aigen, đọc
`../marketing-automation/tasks/HANDOFF_2026-07-29_MVP.md` (mục §4B, §4C) trước
khi sửa gì ở `src/production-spec/`.

### 4C.2. Chuỗi gọi đầy đủ

```
[marketing-automation]
scripts/render_production_assets.py::render_video_one()
  |- doc CONTENT.Output NGUYEN VAN tu store: ps.read_content_output(tk,"video")
  |- ghi ra  <aigen_data_root>/<topic_key>/content-output.json
  |- media_factory/aigen_seam.py::run_aigen_pipeline(co_path)
        |- subprocess: npm run produce:content -- <co_path>   (cwd = aigen repo)

[aigen-pipeline]
scripts/produce-from-content-output.ts
  |- buildTemplateScriptFromContentOutput()      <-- ADAPTER DAY DU
  |     scene-builder -> withDisclaimerOnOutro -> verifySpecScenes (guardrail-2)
  |     -> normalizeScenes(dictionary) (voice) -> withChromeSlots -> adapter -> Zod
  |- ghi  <dir>/script.json    (TemplateScript, giu lai de soi khi loi)
  |- prepareTts()   <-- TU bat OmniVoice neu chua song (spawn warm, cho /health 180s)
  |- runTemplatePipeline(script.json)
        |- Chrome capture -> ffmpeg encode -> concat + mux

Ket qua trong CUNG thu muc:
  content-output.json - script.json - script.txt - voice.mp3 - clips/ - video.mp4

[quay lai marketing-automation]
  |- ps.write_content_status(tk,"video", asset_local_path=...)
  |- drive.upload(video.mp4) -> asset_url
  |- render_content_to_sheet() -> AssetPath = link Drive
```

### 4C.3. HAI CONFIG PHẢI KHỚP NHAU

| Repo | Khoá | Giá trị |
|---|---|---|
| marketing-automation | `media_factory.aigen_repo_path` | `../aigen-pipeline` |
| marketing-automation | `media_factory.aigen_data_root` | `../marketing-database/aigen-pipeline` |
| aigen-pipeline | `config/paths.config.json::dataRoot` | `../marketing-database/aigen-pipeline` |

**Hai dòng `dataRoot` lệch nhau là hỏng IM LẶNG**: Python ghi
`content-output.json` một chỗ, aigen suy `outputDir` chỗ khác. Đã có tiền lệ
thật: `aigen_repo_path` trỏ `../aigen-pipeline` trong khi thư mục thật tên
`../aigen` → seam raise ngay lần gọi thật đầu tiên, và **chưa ai phát hiện vì
chưa có caller thật nào**.

### 4C.4. LỖI Ở TẦNG NÀO — cách phân biệt

Đây là thứ tiết kiệm nhiều thời gian nhất khi debug:

| Thông báo | Tầng | Nghĩa |
|---|---|---|
| `GuardrailViolationError` + danh sách violation | guardrail-2 | Số trong scene KHÔNG khớp `facts[]`. **ĐÚNG chức năng** (chặn bịa số), KHÔNG phải lỗi tích hợp |
| `AliasGuardrailViolation: voiceText contains real ticker "XXX"` | alias-guardrail | Mã chưa có phiên âm → chạy `python scripts/gen_ticker_aliases.py` |
| Zod error từ `TemplateScriptSchema.parse()` | adapter | Slot thiếu/sai tên — xem `required-slot-fields.ts` |
| `OmniVoice server did not become healthy within 180 s` | TTS | Đọc `aigen-pipeline/output/omnivoice-server.log`. Đã gặp: venv trỏ base python sai sau khi đổi tên thư mục |
| `FileNotFoundError` khi gọi npm | seam | `npm` là shim `.cmd` trên Windows — đã vá bằng `shutil.which`, nhưng PATH của tiến trình NỀN có thể khác terminal |
| exit 0 nhưng không thấy `video.mp4` | seam | Đã có kiểm riêng — không tin exit code một mình |

### 4C.5. BẪY TÊN TRÙNG — đã gây hiểu lầm nghiêm trọng 1 lần

| Trùng chữ | Phân biệt |
|---|---|
| `aigen-pipeline/src/production-spec/` (TS) | **CÂY CẦU THẬT, đang chạy. GIỮ** |
| `marketing-automation/media_factory/spec.py::ProductionSpec` (Python) | **ĐÃ XOÁ** 2026-07-29 (bản bị thay thế) |
| `npm run pipeline` | nhận `TemplateScript` ĐÃ chuyển đổi, KHÔNG tự bật TTS |
| `npm run produce` | nhận `TemplateScript`, CÓ tự bật TTS |
| **`npm run produce:content`** | nhận **`CONTENT.Output`** + adapter + tự bật TTS ← **CỔNG ĐÚNG** |
| `marketing-database/marketing-automation/` | kho của repo Python |
| `marketing-database/aigen-pipeline/` | kho của repo TS (job dir video) |

Lead từng phải dừng lại hỏi *"bạn có thực sự hiểu kiến trúc?"* vì agent lẫn 2
dòng đầu. Luôn nêu ĐƯỜNG DẪN FILE ĐẦY ĐỦ khi nói về class/module có thể trùng
tên.

### 4C.6. Chạy thử luồng video KHÔNG cần Sheet

```bash
# 1. Lay CONTENT.Output cua 1 topic da co trong store
cd marketing-automation
python -c "import sys; sys.path.insert(0,'src'); sys.path.insert(0,'.'); from store import pipeline_store as ps; from pathlib import Path; tk='<topic_key>'; d=Path('../marketing-database/aigen-pipeline')/tk; d.mkdir(parents=True, exist_ok=True); (d/'content-output.json').write_text(ps.read_content_output(tk,'video')['output'], encoding='utf-8'); print(d)"

# 2. CHI dung TemplateScript (KHONG render) — kiem guardrail nhanh, khong ton GPU
cd ../aigen-pipeline
npx tsx scripts/_e2e_real_build.ts <topic_key>

# 3. Render day du ra .mp4 (tu bat OmniVoice)
npm run produce:content -- --job <topic_key>
```

Bước 2 là cách RẺ NHẤT để biết guardrail-2 / alias-guardrail có chặn không —
không phải chờ TTS nạp model lên GPU (~180s lần đầu).

### 4C.7. RANH GIỚI CHO CHẾ ĐỘ MULTI-AGENT

Để 2 agent không đạp nhau:

| Vùng | Chủ | Ghi chú |
|---|---|---|
| `collectors/` `curation/` `agents/` (Brief/Router/Composer) | agent nội dung | Gói rules §4.1 nằm ở đây |
| `sheets_board.py` `store/` `scripts/queue_worker.py` | agent hạ tầng Sheet/queue | Vùng dễ gây MẤT DỮ LIỆU NGƯỜI |
| `render/ai_full.py` `render/brand_stamp.py` `config/brand.yaml` | agent infographic | Nhánh `feature/infographic-polish` |
| `aigen-pipeline/src/render/` `src/adapter/` | agent video | 79/79 test adapter, đừng phá |
| `media_factory/numbers.py` + `production-spec/guardrail/` | **CẦN 2 AGENT PHỐI HỢP** | Luật cứng: sửa đồng bộ 2 repo cùng lượt |

**Luồng B** (`orchestrator.py`, `demo.py`, `agents/{researcher,hook,producers}.py`,
`approval/`, `knowledge/rag.py`) — offline demo/legacy, **KHÔNG dùng sản xuất,
KHÔNG gọi lẫn** với Luồng A. Đừng gộp 2 luồng khi sửa bug/thêm tính năng.

### 4C.8. TRẠNG THÁI TEST — CHẠY THẾ NÀO

| Suite | Số | Lệnh | Lưu ý |
|---|---|---|---|
| marketing-automation | **675 pass** | `python -m pytest -q` | Chạy từ **GỐC repo**, không phải `src/`. Cần `pillow` + `fastapi` (xem `requirements.txt` + `api/requirements-webhook.txt`) |
| aigen-pipeline | **244 pass** | `npx vitest run` | kèm `npx tsc --noEmit` |
| Sheet UI (Sheet THẬT) | **13 pass** | `python scripts/test_sheet_ui.py` | Chạy trên Sheet TEST riêng, tự reset. **Dừng worker trước** — tranh quota Sheets |

⚠️ Ba suite này **không bắt được** lỗi chỉ xuất hiện khi chạy thật với LLM/API
ảnh/TTS thật. 13 bug đợt 29/07 đều lộ ra theo đường đó. Xem §7.

---

## 5. HẠ TẦNG — NHỮNG THỨ ĐÃ CẤU HÌNH

| Thứ | Trạng thái |
|---|---|
| DB | `<data_root>/document_store.db` — đường dẫn theo `data_root`, KHÔNG còn tương đối CWD |
| Drive | OAuth NGƯỜI DÙNG (`secrets/drive_token.json`), scope `drive.file`, folder `Marketing-DB` |
| Drive layout | `<dd-mm-yyyy>/<TopicKey>-<5 chữ đầu>/` — mọi định dạng của 1 chủ đề CHUNG thư mục |
| OmniVoice TTS | `aigen-pipeline` **tự bật** qua `npm run produce:content` — KHÔNG cần khởi động tay |
| Từ điển phiên âm | 1600 mục; nguồn sự thật = `fvb/normalizer/text_normalizer.py` |
| Sheet production | `sheets.spreadsheet_id` |
| Sheet test | `sheets.test_spreadsheet_id` — `test_sheet_ui.py` từ chối chạy nếu trùng production |

**Service Account KHÔNG upload được vào My Drive** (Google chặn cứng, không
phải thiếu quyền). Đã kiểm chứng thật. Đó là lý do dùng OAuth người dùng.

⚠️ **OAuth app phải ở "In production"**, không để "Testing" — refresh token hết
hạn sau 7 ngày và hệ thống nền sẽ chết lặng lẽ mỗi tuần.

---

## 6. LỆNH HAY DÙNG

```bash
python -m pytest -q                          # 675 test, chạy từ GỐC repo
python scripts/queue_worker.py               # worker (restart sau mọi thay đổi code)
python scripts/sync_store_sheet.py           # đồng bộ 2 chiều
python scripts/sync_store_sheet.py --from-store   # store THẮNG tuyệt đối (Sheet đang sai)
python scripts/test_sheet_ui.py              # 13 ca trên Sheet test, tự reset
python scripts/gen_ticker_aliases.py         # sinh lại từ điển phiên âm
python scripts/drive_authorize.py --check    # kiểm uỷ quyền Drive
```

```bash
cd ../aigen-pipeline
npm run produce:content -- <content-output.json>   # CONTENT.Output -> video.mp4
npx vitest run && npx tsc --noEmit
```

---

## 7. NGUYÊN TẮC RÚT RA — ĐỌC TRƯỚC KHI SỬA GÌ

1. **Test xanh KHÔNG đủ.** 13/13 bug đợt này lộ ra khi chạy thật. Với việc có
   rủi ro dữ liệu/chất lượng, phải chấm trên output thật.
2. **Fake worksheet không thay được Sheet thật.** `test_sheet_ui.py` sinh ra vì
   `clear()` xoá format, `deleteDimension` dịch chỉ số, validation bị ghi đè —
   fake không có mấy thứ đó.
3. **Tra git trước khi kết luận "code bị mất".** Hai lần trong phiên tưởng logic
   biến mất, thực ra nó vẫn chạy và bị ghi đè.
4. **Đọc code không thay được chạy code.** Tôi từng báo "adapter chưa nối" trong
   khi nó là một lời gọi hàm hoàn chỉnh có 243 test.
5. **Hỏi phạm vi trước khi áp quy tắc.** Ba lần suýt phá thứ đang đúng.
6. **Trước khi viết hàm mới, tìm hàm đã có.** Đã viết trùng `band_rows_by_day`
   trong khi `band_context_by_day` tồn tại sẵn.
