# ACTIVE_TASK — Tái cấu trúc 2 repo (marketing-automation ↔ aigen-pipeline)

> **GHI ĐÈ MỖI PHIÊN** — file này phản ánh trạng thái NGAY LÚC dừng phiên gần
> nhất, không phải log lịch sử (lịch sử: `PROJECT_HANDOFF_P5.md`). Viết lại
> 2026-07-19 (phiên 2, SAU KHI MOVE 2 repo sang máy mới) — trạng thái đã đi
> TRƯỚC nhiều so với bản viết đầu phiên: PHA 1+2+3 ĐÃ MERGE, PHA 4.1/4.2 đã
> chạy. Đọc mục "PHÁT HIỆN PHA 4.2" trước khi làm gì tiếp — có lỗi chung
> 2 repo cần quyết định của Lead.

## MÁY MỚI (2026-07-19) — vị trí/môi trường

- Repo nằm ở `trung-temp\`: `marketing-automation` + `aigen` (LƯU Ý: thư mục
  đổi tên, KHÔNG còn là "aigen-pipeline") + **`marketing-database`** (KHO CHUNG).
- **KHO DỮ LIỆU ĐỔI 2026-07-21** — tên cũ `marketing-automation-database` ĐÃ BỎ.
  Kho chung tên trung lập, mỗi repo 1 thư mục con MANG TÊN REPO:
  `marketing-database/marketing-automation/` (documents·output·state·logs,
  `output/` partition theo NGÀY) và `marketing-database/aigen-pipeline/`
  (`<job>/` render). Dữ liệu cũ đã move, kho cũ đã xoá. Config:
  `settings.yaml storage.data_root` + `aigen config/paths.config.json dataRoot`.
- Secrets ĐÃ ĐỦ: `secrets/.env` (732B) + `secrets/sa.json` (2389B) bên
  marketing-automation; `.env.local` bên aigen.
- **Node v24.18.0 + npm 11.16.0 CÓ; ffmpeg/ffprobe 8.1.2 CÓ (trên PATH)** —
  `npx vitest run` → **206/206 pass** (kể cả 2 test audio-tools từng fail
  trên PC-A). `RUNTIME.md` (aigen) đã cập nhật 2 chỗ theo máy mới.
- **Python CHƯA CÀI trên máy này** (chỉ có stub Microsoft Store) — suite
  `python tests/test_pipeline.py` CHƯA chạy được, việc đầu tiên phiên sau.
- Task Scheduler/NSSM cho `system_power_on.py`: CHƯA đăng ký (như audit cũ).

## QUY ƯỚC WORKFLOW (không đổi)
1. Đọc `CLAUDE.md` → file này → `docs/ARCHITECTURE_MODULES.md` →
   `docs/CONTENT_OUTPUT_SCHEMA.md` → `docs/MODULE_INDEX.md` khi cần định vị
   code. 4 file tồn tại GIỐNG HỆT ở cả 2 repo.
2. **DỪNG-BÁO-CÁO** khi ra ngoài scope. KHÔNG auto-commit.
3. Nợ dài hạn: `docs/VPS_MIGRATION_BACKLOG.md` (chỉ-thêm).

## Kiến trúc đã CHỐT (không mở lại — xem `docs/ARCHITECTURE_MODULES.md`)
2 repo, ranh giới = `CONTENT.Output` (JSON, schema v1). marketing-automation
(Python) sinh; aigen (TypeScript) biến thành video. Composer (Opus, TRƯỚC
Gate 2) là nơi DUY NHẤT có LLM; sau Gate 2 100% tất định (kể cả số→chữ,
ticker→phiên âm tra từ điển — bài học "VNM = vi na miu").

---

## TRẠNG THÁI 6 PHA (2026-07-19, cuối phiên 2)

### PHA 0 — Tài liệu — **XONG**

### PHA 1 (port `ProductionScene`/guardrail-2 video sang TS) — **XONG, ĐÃ MERGE `develop` aigen** (commit `2a7a2a8`; branch `feature/production-spec` không còn; `main` CHƯA đụng — đúng quy tắc)
**PHA 1.1 (nợ đối chiếu tay) — ĐÃ LÀM XONG phiên này.** Lead-agent đã đối
chiếu từng hàm `src/production-spec/{spec.ts,guardrail/verify-spec.ts}` với
`media_factory/{spec.py,numbers.py}` gốc. Kết luận: **port TRUNG THÀNH 100%
semantics** (5 shape fact, `_fact_index_matching` dung sai 0.05/lookback 12,
`_iter_slot_texts`, `_check_plain_list_item_entity` + `_ENTITY_LIST_SLOT_KEYS`,
salience "context" loại/"" tương thích ngược, fail-closed facts rỗng, toàn bộ
parser số chữ-số + viết-bằng-chữ). Xác nhận thêm claim "guardrail-2 tách sạch
đôi": `verify_spec()` Python là 2 vòng lặp rời (`blocks`/`scenes`),
`_known_stat_labels` chỉ dùng nhánh blocks — tách sạch, ĐÚNG như docstring
spec.ts tự khai. 3 khác biệt CÓ CHỦ ĐÍCH, chấp nhận: (1) TS NFC-normalize
trước so khớp (Python gốc KHÔNG — TS mới là bên đúng theo
CONTENT_OUTPUT_SCHEMA.md); (2) TS thêm `checkFactsHaveSource` (structural,
fail-closed, scene_index=-1); (3) nit lý thuyết: `decimalWordsToDigits` TS trả
NaN thay None với input rác qua prototype-chain — cùng kết cục flag violation,
không ảnh hưởng.

### PHA 2 (chuẩn hoá output Composer, schema v1) — **XONG HẲN, ĐÃ MERGE**
PR #2 (`feature/video-composer-schema-pending-review` → `develop`, commit
`ed0d076`). **Lead XÁC NHẬN (phiên này) đã đọc đối chiếu hồi quy
`reports/regression_video_prompt/` trước khi merge, chất lượng KHÔNG giảm** —
điều kiện bắt buộc đã thoả. Đóng.

### PHA 3 (Scene Builder + voice layer) — **XONG, ĐÃ MERGE** (cùng commit PHA 1)
Soi mắt 3 câu mẫu từ phiên trước vẫn đứng. Nợ nhỏ còn lại: Lead chưa đọc
TỪNG assert của 82 test production-spec xem có expect viết sai theo không.

### PHA 4 (nối thông + dọn đường dẫn) — **4.1/4.2/4.3 ĐÃ CHẠY — 4.2 RA PHÁT HIỆN QUAN TRỌNG, xem mục dưới**
4.1 **XONG**: grep "aigen-fva-capital" — marketing-automation chỉ còn ghi chú
lịch sử hợp lệ (comment/docs); aigen còn 1 HƯỚNG DẪN SỐNG trong `RUNTIME.md`
→ ĐÃ SỬA (working tree, chưa commit).
4.2 **ĐÃ CHẠY** end-to-end trên 3 bài Opus THẬT (`*_new.txt` trong
`reports/regression_video_prompt/`): `CONTENT.Output` → scene-builder → voice
→ guardrail-2 → (adapter/Zod). Đường ống THÔNG về cơ khí (mọi tầng chạy,
lỗi ném đúng tầng, `withDisclaimerOnOutro` hoạt động) — nhưng **guardrail-2
chặn CẢ 3 bài (0/3 tới TemplateScript)**, phân loại ở mục PHÁT HIỆN dưới.
4.3 Audit VPS — xong từ trước.

### PHA 5 (test + PR) — dồn lại còn: chạy suite Python trên máy mới (chờ cài Python) + commit các sửa working tree phiên này (người vận hành tự commit).

### PHA 6 (move VPS/máy mới) — **PHẦN COPY ĐÃ XẢY RA TRÊN THỰC TẾ** (2 repo + data_root + secrets đã nằm đúng vị trí trên máy này — xem mục MÁY MỚI). Còn: cài Python, đăng ký scheduler, chạy video thật đầu tiên.

---

## R2 — ĐÃ LÀM XONG (2026-07-19 phiên 2, Lead duyệt hướng)

**Đổi kiến trúc đã CHỐT**: `guardrail-2` giờ chạy **TRƯỚC** `voice`, không phải
sau. Lý do đầy đủ ghi ở `docs/ARCHITECTURE_MODULES.md` §"Vì sao guardrail-2
chạy TRƯỚC voice" (đã đồng bộ NGUYÊN VĂN cả 2 repo, đã `diff` xác nhận).

Đã làm, tất cả xanh:
1. `aigen/src/production-spec/index.ts` — đảo thứ tự, docstring §ORDER DECISION.
2. `aigen/.../voice/spell-out-numbers.test.ts` — **property round-trip test**
   (mọi số `spellOutNumbers()` sinh ra phải đọc ngược đúng giá trị qua
   `parseVnNumberWords()`). Đây là lớp bù cho việc guardrail không còn soi
   voice_text sau chuẩn hoá — kiểm CÁI MÁY SINH thay vì đọc lại văn xuôi.
3. **Lỗi "linh" — property test phát hiện, đã vá ĐỒNG BỘ 2 REPO**: bộ sinh
   phát ra "một trăm linh năm" (105) nhưng parser thiếu "linh" trong từ vựng
   → **162/2001 số nguyên** (mọi dạng x0y) trả `None` → chặn oan. Sửa
   `verify-spec.ts::parseSmallGroup` + `numbers.py::_parse_small_group` +
   `_STRUCTURE_WORDS` cùng lượt. CỐ Ý không nhận biến thể "lẻ" (bộ sinh không
   phát ra, mà "bán lẻ" là từ thường gặp → chỉ thêm dương tính giả).
4. Test: Python **402 passed** (400 + 2 test "linh" mới), TS **212 passed**
   (206 + 6), `npx tsc --noEmit` sạch.

## KẾT QUẢ E2E SAU R2 (chấm trên 3 bài Opus THẬT) — 0/3 vẫn chưa thông, NHƯNG lý do đã khác hẳn

| Bài | Trước R2 | Sau R2 |
|---|---|---|
| `4_cang_bien_dac_biet` | 3 vi phạm (2 oan) | **QUA guardrail**, chặn ở ADAPTER: `missing required slot field(s): kicker, brand` |
| `cong_ty_lo_q2` | 7 vi phạm | 6 vi phạm — 5 là (a)/R3 thật, 1 còn oan ("hai năm") |
| `vietnam_airlines_co_dong` | 1 vi phạm | 1 vi phạm — **nguyên nhân MỚI, xem dưới** |

Nhóm (b) dấu câu + (c) nhập nhằng ở voice_text sau chuẩn hoá: **BIẾN MẤT** ở
2/3 bài. Còn lại 4 việc RÕ RÀNG, mỗi việc cần 1 quyết định:

### ✅ V1 — ĐÃ XỬ LÝ (2026-07-19), CHỜ KIỂM CHỨNG BẰNG OPUS THẬT
Đã thêm khối "ĐỊNH DẠNG ĐẦU RA — VĂN VIẾT THƯỜNG" (bảng 9 dòng ĐÚNG/SAI, lý do,
ngoại lệ số-dùng-như-từ-ngữ, bước tự kiểm) vào `prompts/video.v1.md` + mirror
trong `production.py::VideoScriptAgent.system` (sinh file .md THẲNG từ chuỗi
code nên giống từng byte — test drift có sẵn canh).
**Gỡ luôn mâu thuẫn ngầm**: `prompts/CONTENT_WRITER_RULES.md` §4.5 cấm ticker
trong voice-over, mà §4 được nối vào system prompt SAU CÙNG nên nó THẮNG luật
mới → Composer nhận 2 chỉ thị ngược nhau. Đã viết lại §4.5 theo kiến trúc hiện
tại (KHÔNG trích nguyên văn câu cấm cũ — trích lại là vẫn còn nhiễu).
2 test mới khoá nội dung hợp đồng + chặn §4.5 quay lại.

**⏸ TẠM DỪNG THEO QUYẾT ĐỊNH LEAD (2026-07-19) — VIỆC PHẢI LÀM SAU, ĐỪNG QUÊN.**
Prompt mới đã CHẶT CHẼ hơn hẳn về chuẩn `CONTENT.Output` (bảng ĐÚNG/SAI + gỡ
mâu thuẫn §4.5), đủ tốt để đi tiếp. Việc kiểm chứng bằng Opus thật DỜI sang
vòng tối ưu sau — KHÔNG phải đã xong, chỉ là hoãn có chủ đích. Khi quay lại:
chạy `rerun_regression.py` (runner đã viết sẵn), đối chiếu narration xem còn
cụm số-viết-bằng-chữ nào không. Lý do hoãn nằm ngay dưới đây.

**❌ CHƯA kiểm chứng được bằng Opus thật** — `claude -p` (llm.mode=claude_code)
trả `"Not logged in · Please run /login"`: phiên đăng nhập app desktop KHÔNG
dùng chung với CLI đứng riêng. Agent KHÔNG được thao tác đăng nhập thay người.
Lead cần làm 1 trong 2, rồi báo để chạy lại:
(a) mở terminal, `cd` vào repo, chạy `claude` 1 lần, chấp nhận trust dialog +
    `/login`; hoặc
(b) điền `ANTHROPIC_API_KEY` vào `secrets/.env` và đổi `llm.mode: "api"`.
Runner đã viết sẵn (scratchpad `rerun_regression.py`) — tái hiện đúng input cũ,
chỉ khác system prompt; chạy 1 lệnh là ra kết quả + tự dò cụm số-viết-bằng-chữ.
CLI thật nằm ở `%APPDATA%\Claude\claude-code\<ver>\claude.exe` (KHÔNG phải
`%LOCALAPPDATA%\AnthropicClaude\claude.exe` — đó là app desktop).

### ✅ (b) — ĐÃ VÁ, ĐỒNG BỘ 2 REPO
`find_word_number_phrases` tokenize bằng `\S+` nên dấu câu dính token
("mươi," / "lăm.") rơi khỏi từ vựng số → cụm bị CẮT CỤT → parse sai → chặn oan.
Thêm `_strip_token_punct` (Python) / `stripTokenPunct` (TS) bỏ dấu câu 2 mép,
GIỮ offset gốc để lookback từ xấp xỉ vẫn đúng. Cố ý KHÔNG gồm "-" (từ ghép) và
"/" (ngày tháng đi đường chữ số). Test 2 phía dùng đúng ca thật.
Kết quả: Python **405 passed**, TS **215 passed**, `tsc --noEmit` sạch.

### ✅ (c) — ĐÃ VÁ ĐỒNG BỘ 2 REPO (2026-07-20, agent-B)
Cụm "năm hai nghìn không trăm hai mươi lăm" trước parse ra **5025** (chữ "năm"
year bị đọc thành chữ số 5). Đã sửa theo đúng hướng đề xuất: trong
`parse_vn_number_words` (Python `numbers.py`) + `parseVnNumberWords` (TS
`verify-spec.ts`), nếu cụm MỞ ĐẦU bằng "năm", `scale==1`, không thập phân, và
phần CÒN LẠI tự đọc ra giá trị ∈ [1900,2100] → coi "năm" là DANH TỪ, bỏ khỏi
phép tính → nay ra **2025**. Hẹp có chủ đích: "năm mươi"(50)/"năm trăm"(500)/
"năm nghìn"(5000)/"năm triệu"/"năm tỷ" phần-còn-lại KHÔNG rơi vào [1900,2100]
nên KHÔNG dính (đã có test khẳng định). Round-trip property test không đụng vì
bộ sinh số thường không phát "năm" mở đầu (chỉ dạng date "năm <year>" — nay
parser đọc ĐÚNG luôn). 2 test ghim 5025 đã đổi sang 2025 + thêm 1 test chuyên
mỗi phía. Python 406 pass, TS 223 pass, tsc sạch.

### V1 (bản gốc, giữ để đối chiếu) — Composer VI PHẠM HỢP ĐỒNG narration
Bài `vietnam_airlines_co_dong`: Opus tự viết số bằng CHỮ ngay trong
`narration` — "báo cáo tài chính ... **năm hai nghìn không trăm hai mươi
lăm**", "từ **ngày mười bốn tháng Bảy**". `docs/CONTENT_OUTPUT_SCHEMA.md` ghi
rõ: *"narration: VĂN VIẾT THUẦN — giữ nguyên số + ticker, KHÔNG viết số bằng
chữ"*. Composer không tuân prompt ở bài này.
→ Hệ quả: `voice/` không có gì để chuẩn hoá, còn guardrail buộc phải đọc ngược
văn xuôi — đúng cái R2 muốn tránh. **Sửa ở PROMPT Composer, không vá bằng luật
máy** (theo kỷ luật "không tự vá bằng thêm luật máy móc"). Cân nhắc thêm 1
CONTRACT CHECK ở scene-builder: narration chứa cụm số-bằng-chữ → throw nêu rõ,
thay vì để guardrail đoán mò.

### V2 — Word-scan trước voice là bề mặt dương-tính-giả (cần Lead chốt)
`checkText()` luôn chạy CẢ 2 lối (chữ số + số-bằng-chữ). Đứng trước `voice`,
narration ĐÚNG hợp đồng là dạng chữ số → lối word-scan chỉ còn tạo oan:
"Quý **hai năm** nay" → parse thành 2 → chặn oan (bài `cong_ty_lo_q2`).
- Tắt word-scan (thêm option, mặc định giữ nguyên cho test cũ): hết oan,
  NHƯNG bài nào Composer viết sai như V1 sẽ **lọt hoàn toàn không bị kiểm**.
- Giữ: an toàn hơn nhưng còn oan.
→ Hai lựa chọn này chỉ hợp lý khi gắn với V1. Đề xuất: **làm V1 trước** (chặn
contract violation ngay đầu nguồn), rồi mới tắt word-scan an tâm.

### V3 — Số TRẦN không đơn vị KHÔNG được guardrail soi (đánh đổi phải biết)
`_DIGIT_MAGNITUDE_RE` chỉ bắt số CÓ đơn vị (`%|tỷ|triệu|đồng|usd...`). Nên ở
dạng chữ số, "2021"/"2030"/"2050" trần **không bị kiểm** — đó là lý do bài
cảng biển qua được guardrail (trước R2, dạng chữ nó bắt "2021" là bịa). Đây là
tính chất CÓ SẴN của nhánh ảnh Python bao lâu nay, không phải R2 tạo ra.
Nếu Lead muốn siết năm/số trần → việc riêng, sửa regex ĐỒNG BỘ 2 repo.

### 🟢 LUỒNG ĐÃ THÔNG END-TO-END LẦN ĐẦU (2026-07-20)
`1/3` bài Opus THẬT (`4_cang_bien_dac_biet`) chạy hết
`CONTENT.Output → scene-builder → guardrail-2 → voice → alias-guardrail →
adapter → TemplateScript` và **Zod parse thành công**, 5 scene.
2 bài còn lại bị chặn ở GUARDRAIL (đúng chức năng): `cong_ty_lo_q2` = R3 (Brief
sinh delta fact thiếu canonical), `vietnam_airlines_co_dong` = lỗi (c) "năm".
**Không còn bài nào chết vì lỗi lắp ráp đường ống.**

Đã làm để thông (agent-B, Lead duyệt phương án B/C):
1. `BRAND_PRIMARY_URL` = link FB kênh Lead cung cấp → điền vào
   `frame-logo-outro.primary_url` (hằng THƯƠNG HIỆU ở phía aigen, KHÔNG đưa vào
   hợp đồng `CONTENT.Output`).
2. Hạ `required: true → false` cho ô THUẦN TRANG TRÍ chưa có nguồn
   (`required-slot-fields.ts`). GIỮ required cho ô MANG NỘI DUNG (headline,
   hero, desc, quote, label, items, left/right, rows, brand_name, primary_url).
3. 2 phép ĐỔI TÊN chống rơi nội dung: `attribution → author` (quote),
   `items → rows` (ticker). Adapter KHÔNG tự đổi tên.
4. **Vá 1 lỗ thật do test phát hiện**: `isBlank()` không coi `{}` là rỗng, nên
   sau khi hạ `badge`, `frame-versus-comparison` mất sạch lưới (comparison RỖNG
   vẫn lọt). Đã thêm nhánh object-rỗng.
Kết quả: TS **217 passed**, `tsc --noEmit` sạch, Python **405 passed**.

⚠️ **NỢ CÒN LẠI, ĐỪNG QUÊN** (ghi ngay trong code, có comment ⚠️):
- ✅ **ĐÃ VÁ (2026-07-20, agent-B)** — `frame-pentagram-stat` KHÔNG có ô
  `value`. Đọc `portrait.html`: ô số lớn là `headline` (font 300px). Đã thêm 2
  phép đổi tên tất định ở `production-spec/index.ts::withChromeSlots`
  (`value → headline`, `note → subtitle`) + khôi phục `headline` về
  `required:true` ở `required-slot-fields.ts` (value là required ở payload nên
  headline luôn có nguồn). `anchor` (số nền trang trí) CỐ Ý để trống (map sẽ là
  đoán ngữ nghĩa). Test: `index.test.ts` +2 ca (map đúng ô + thiếu value phải
  nổ). TS 222 pass, tsc sạch. KHÔNG đụng repo Python (không phải logic số/
  guardrail; hợp đồng CONTENT.Output giữ nguyên).
- Ngữ nghĩa biên tập của `eyebrow`/`side_left`/`side_right`/`badge`/`footer_*`/
  `author_role`/`subline`/`tag`... vẫn trống → video ra sẽ thiếu chrome.
- Cảnh báo độ dài lúc chạy: `primary_url` 67 ký tự vs giới hạn CATALOG 40, và
  `hero` 17-30 ký tự vs giới hạn 10 → chữ có thể tràn/cắt khi render. Cân nhắc
  link rút gọn cho kênh.

### 🔴 V4 — ĐO XONG 2026-07-19: KHE HỞ TỪ VỰNG, KHÔNG PHẢI "THIẾU VÀI FIELD"
**Nguyên nhân gốc (mới xác định):** `adapter` KHÔNG đổi tên field — nó nhận
`ProductionScene.slots` ĐÃ ở đúng từ vựng SLOT của template (bằng chứng:
fixture trong `adapter/aigen-adapter.test.ts` truyền thẳng `eyebrow`,
`side_left`, `author_role`, `rows`). Nhưng `scene-builder` lại đổ THẲNG
`payload` (từ vựng TRUNG LẬP VENDOR) vào `slots`:
`slots: { ...scene.payload }`. **Hai từ vựng chưa bao giờ được nối.** Nó chỉ
"chạy được" ở `title` vì tên trùng nhau tình cờ (headline/subheadline).

**Đo thật (9/9 visual_kind đều dính):**
```
title      -> frame-liquid-bg-hero      thiếu: (đã lấp kicker/brand) subheadline*
stat       -> frame-pentagram-stat      thiếu: headline, subtitle, anchor, footer_left, footer_right
statement  -> frame-build-minimal       thiếu: eyebrow, side_left, side_right
list       -> frame-icon-list           thiếu: subtitle
comparison -> frame-versus-comparison   thiếu: badge
quote      -> frame-quote-pull          thiếu: author, author_role
ticker     -> frame-market-ticker       thiếu: title, subtitle, rows, footer_left, footer_right
news       -> frame-news-lower-third    thiếu: badge, live, timestamp, subline, tag, lower_title, lower_sub, ticker
outro      -> frame-logo-outro          thiếu: tagline, primary_url
```
(*) Con số thô 28 là CẬN TRÊN: probe chỉ so với phần BẮT BUỘC của payload, chưa
trừ field optional Composer có thể sinh. Số thật nhỏ hơn nhưng KHÁC 0 ở mọi kind.

**Hệ quả nặng nhất:** `outro` là scene BẮT BUỘC của MỌI video, mà
`frame-logo-outro` đòi `primary_url` — trường này KHÔNG có nguồn ở bất kỳ đâu
trong hợp đồng. ⇒ **Hiện tại KHÔNG bài nào có thể đi hết tới `TemplateScript`**,
kể cả bài sạch tuyệt đối. Đây là chốt chặn số 1 của mục tiêu end-to-end.

**Đã lấp được phần không cần quyết định** (`production-spec/index.ts::
withChromeSlots`, chạy SAU guardrail-2 vì chrome không phải dữ liệu từ facts):
`brand` ← `brand_name` của scene outro; `kicker` ← `output.source`. Cả hai MAP
từ dữ liệu ĐÃ CÓ trong hợp đồng, không bịa; không ghi đè nếu Composer đã điền.
Kèm `index.test.ts` (file test đầu tiên cho tầng orchestration — trước đó
docstring có nhắc nhưng file KHÔNG tồn tại).

**CẦN LEAD QUYẾT — 3 hướng, tôi khuyến nghị (B):**
- (A) Mở rộng `CONTENT.Output` cho đủ field → **phá tính trung lập vendor** (tên
  slot AIGEN chui vào hợp đồng chéo repo). Không nên.
- (B) **Xây lớp ánh xạ payload→slot trong `scene-builder`** (đúng chỗ theo
  `ARCHITECTURE_MODULES.md`: scene-builder là nơi biến hợp đồng trung lập thành
  `ProductionScene`). Tất định, không LLM. Việc thật: định nghĩa cho 9 kind.
- (C) Hạ `required: true` → `false` cho field thuần trang trí. NHƯNG
  `src/adapter/` đang KHOÁ (agent-B sở hữu, 79/79 test) → tôi KHÔNG tự sửa.

**Câu hỏi chặn (B):** một số slot cần giá trị THƯƠNG HIỆU mà không ai có:
`primary_url` (URL kênh FVA Capital?), `tagline` mặc định, và ngữ nghĩa biên tập
của `eyebrow`/`side_left`/`side_right`/`badge` cho từng loại scene. Đây là quyết
định BIÊN TẬP, không phải kỹ thuật — cần Lead cho giá trị/quy ước.

### V4 (ghi chú cũ) — Khe hở schema adapter (đã biết từ trước, giờ mới lộ ra vì qua được guardrail)
`scene-builder` chỉ kiểm required-field theo `CONTENT_OUTPUT_SCHEMA.md`, còn
`adapter/required-slot-fields.ts` đòi NHIỀU field hơn theo template thật
(`title` cần thêm `kicker`, `brand`). Đã được ghi rõ trong docstring
`scene-builder/index.ts` là "REAL, currently-open gap". Bài cảng biển chết ở
đây. → Phải chốt: nới template hay bắt Composer sinh thêm field.

### Còn nguyên (không đổi sau R2)
- **R3 — ĐÃ XÁC ĐỊNH LẠI ROOT CAUSE (2026-07-20, agent-B): KHÔNG phải "canonical
  null" như mô tả cũ.** Kiểm trên fixture THẬT `cong_ty_lo_q2_new.txt`: mọi
  delta trong facts[] ĐÃ có canonical đúng (16,3 tỷ → 16.3e9...). Vấn đề thật:
  khoản LỖ `9,34 tỷ` và `12,6 tỷ` nằm ở **2 CÂU LIỀN KỀ KHÁC NHAU** trong
  evidence ("...là 9,34 tỷ đồng. Con số này...so với mức lỗ 12,6 tỷ đồng...") →
  quy tắc chống-bịa `_find_shared_sentence` (from/to delta phải CÙNG 1 câu) TỪ
  CHỐI ghép chúng thành delta (ĐÚNG chức năng), và Brief cũng không emit chúng
  dưới dạng scalar → Composer dùng 2 số này ở scene → guardrail chặn cấp (a).
  Đã chứng minh bằng `facts_from_llm_output` trên evidence thật (2 câu → delta
  bị loại; nếu 1 câu → canonical tính đúng). Parser `parse_magnitude_token`
  KHÔNG có bug ở đây (đã thử vá dấu âm rồi REVERT vì Brief nhận value từ evidence
  = prefix CHỮ, không phải dấu "-").
  **CẦN LEAD QUYẾT + LLM THẬT** (không phải sửa code tất định): (A) sửa PROMPT
  Brief để emit thêm SCALAR cho từng con số khoản lỗ dù nằm khác câu; hoặc (B)
  chấp nhận chặn (Composer không nên trình bày so sánh chéo-câu như 1 delta đã
  kiểm); hoặc (C) nới `_find_shared_sentence` (RỦI RO chống-bịa, không khuyến
  nghị). Cả 3 đều cần chạy Brief Opus thật để kiểm — hiện `claude -p` chưa
  đăng nhập (xem VIỆC KẾ TIẾP #5). ĐỪNG tự sửa máy móc.
- **(b) lỗi tokenize dấu câu** trong `find_word_number_phrases` (cả 2 repo):
  "…hai mươi lăm**.**" bị cắt mất "lăm" → parse 5020 thay vì 2025. Sau R2 ít
  ảnh hưởng hơn (word-scan chỉ còn chạm bài vi phạm V1) nhưng VẪN LÀ BUG, và
  nhánh ảnh Python vẫn dùng. Vá đồng bộ 2 repo khi làm V2.

## PHÁT HIỆN PHA 4.2 (2026-07-19 phiên 2) — nền của R2, GIỮ LẠI ĐỂ ĐỐI CHIẾU

Guardrail-2 chặn cả 3 bài thật. Soi từng violation, chia 3 loại:

**(a) Chặn ĐÚNG (fail-closed như thiết kế)** — số trong bài KHÔNG có fact
canonical đối chứng: `2021` (bài cảng biển — Composer dùng năm không có
fact); `3 tỷ`/`9,34 tỷ đồng`/`12,6 tỷ`/`16,3 tỷ` (bài công ty lỗ — Brief
sinh fact delta nhưng `canonical_from/to` = null, và không có fact scalar
nào mang các số này). → Lỗi thượng nguồn ở **Brief** (fact delta thiếu
canonical) + Composer dùng số ngoài facts. Đúng quy trình: NEEDS_HUMAN.

**(b) DƯƠNG TÍNH GIẢ — lỗi tokenize DẤU CÂU, CHUNG CẢ 2 REPO**:
`find_word_number_phrases` (Python `numbers.py` LẪN bản port TS — port trung
thành nên lỗi giống hệt) tách token bằng `\S+` rồi so `NUMBER_CORE` — token
dính dấu câu ("mươi," / "mươi." / "tỷ.") KHÔNG nhận ra → cụm số bị CẮT CỤT
→ parse sai giá trị → flag oan. Bằng chứng thật: "hai nghìn ba mươi," bị cắt
thành "hai nghìn ba" (=2003 ≠ fact 2030 → oan); "hai nghìn năm mươi." →
"hai nghìn năm" (=2005 ≠ 2050); "mười sáu phẩy ba tỷ." mất hậu tố "tỷ." →
16,3 thay vì 16,3e9. **Sửa PHẢI đổi CẢ 2 REPO CÙNG LƯỢT** (hợp đồng chéo —
xem ARCHITECTURE_MODULES.md §facts[] drift). Hướng sửa gợi ý: strip dấu câu
mép token khi so NUMBER_CORE/hậu tố (giữ vị trí ký tự gốc cho lookback).

**(c) DƯƠNG TÍNH GIẢ — nhập nhằng từ "năm"/"hai" (giới hạn ĐÃ tài liệu hoá
trong docstring numbers.py, nay thành vấn đề THẬT vì voice_text sau chuẩn
hoá đầy số-chữ)**: "Quý **hai năm** nay" → cụm "hai năm" parse=2 → oan;
"**năm** hai nghìn không trăm hai mươi" ("năm 2020") → chữ "năm" (year) bị
hút vào cụm số → parse=5020 ≠ 2020 → oan. Khó sửa triệt để bằng regex thuần
— cần Lead quyết hướng (vd: bỏ qua cụm bắt đầu bằng "năm" đứng trước cụm
năm-4-chữ-số? whitelist mẫu "Quý hai"?...). KHÔNG tự vá máy móc.

Ghi chú liên quan: `spellOutNumbers("2030")` → "hai nghìn ba mươi" (đọc tắt,
không phải "hai nghìn KHÔNG TRĂM ba mươi") — parse đúng 2030 nếu không dính
lỗi (b), nhưng Lead có thể muốn chuẩn hoá cách đọc năm cho tự nhiên.

## VIỆC PHIÊN SAU (theo thứ tự)
1. Cài Python (3.12/3.13, python.org hoặc winget) → `python tests/test_pipeline.py` — phải 400/400 như PC-A.
2. Lead quyết hướng sửa (b) + (c) ở trên → sửa ĐỒNG BỘ `numbers.py` (Python)
   + `verify-spec.ts` (TS) + test 2 bên cùng lượt.
3. Xem lại Brief: fact shape=delta sinh `canonical_from/to`=null cho số tiền
   ("9,34 tỷ" → null) — đây là lý do chính bài "công ty lỗ" bị chặn oan cấp
   (a); cân nhắc Brief phải điền canonical khi from/to là số.
4. Câu hỏi mở còn treo: `media_factory/aigen_seam.py` còn cần không.
5. File lạ untracked bên aigen: `docs/AVATAR_HEYGEN_PROPOSAL.md` — chưa rõ
   phiên nào tạo, Lead xem rồi quyết giữ/xoá.
6. Nợ nhỏ PHA 3: Lead đọc 82 assert test production-spec.

## DỪNG KHI
1. Chất lượng biên tập GIẢM ở bất kỳ kiểm tra hồi quy nào sau này.
2. Cần render AIGEN thật lần đầu (giờ máy này CÓ ffmpeg — nhưng OmniVoice
   chưa dựng, vẫn chưa render được; dựng xong báo Lead trước khi chạy).
3. Đụng kiến trúc đã chốt ở `docs/ARCHITECTURE_MODULES.md`.
4. Sửa bất kỳ logic số/guardrail nào mà không sửa ĐỒNG BỘ cả 2 repo.

## KHÔNG LÀM
Không đụng `src/render/` (aigen, agent-B sở hữu). Không đụng `src/adapter/`
(79/79 test, PR #1 merged). Không xây DB chung (A6). Không reset Sheet.
Không merge gì vào `main` (aigen). Không tự vá dương tính giả (b)/(c) khi
Lead chưa chọn hướng.
