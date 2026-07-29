# ARCHITECTURE_MODULES.md — ranh giới 2 repo (chốt 2026-07-19)

> File này TỒN TẠI GIỐNG HỆT ở CẢ HAI repo (`marketing-automation/docs/` và
> `aigen-pipeline/docs/`) — đọc ở repo nào cũng ra cùng 1 bức tranh. Sửa ở 1
> nơi PHẢI đồng bộ sang nơi kia trong cùng lượt, không để lệch.
>
> Nguồn quyết định: Lead + user, chốt khi phát hiện `docs/AGENT_B_NOTES_TO_LEAD.md`
> (aigen-pipeline) mô tả sai — video Scene Builder từng dự định nằm ở Python,
> nay chuyển hẳn sang TypeScript để cùng ngôn ngữ với renderer AIGEN.

## Kiến trúc đã chốt — 2 repo, ranh giới = `CONTENT.Output`

Hai repo, MỘT repo MỘT ngôn ngữ. Ranh giới trung lập vendor bây giờ là
**`CONTENT.Output`** (JSON do Content Factory sinh ra), **KHÔNG PHẢI**
`ProductionSpec` như thiết kế cũ (`ProductionSpec` giờ là chi tiết triển khai
NỘI BỘ của aigen-pipeline, không còn là điểm nối 2 repo).

```
marketing-automation (Python)          aigen-pipeline (TypeScript)
──────────────────────────────         ───────────────────────────────
Content Factory                        Mọi thứ biến CONTENT.Output → video
  crawl → Gate 1 → Composer (LLM)
  → Gate 2 → CONTENT.Output (JSON)  ─┐
                                      │  src/production-spec/
Renderer Infographic (GIỮ Ở ĐÂY)     │    spec.ts          (PORT: ProductionScene)
  ProductionBlock                    │    guardrail/       (PORT: guardrail-2 nhánh video)
  guardrail nhánh ảnh (nhẹ)          │    scene-builder/    (MỚI: CONTENT.Output → scenes[])
  render/infographic.py              └──▶ voice/           (MỚI: chuẩn hoá voice_text)
                                          spec.ts → src/adapter/ (GIỮ NGUYÊN, 79/79 test)
                                                  → src/render/  (ruột AIGEN, agent-B sở hữu,
                                                                  KHÔNG đụng)
```

### `marketing-automation` (Python) — Content Factory

- Sinh `CONTENT.Output` ở 3 dạng: bài viết, ảnh (infographic), video script.
- Video script chuẩn hoá: mỗi scene có `visual_kind` (1 trong 10 giá trị
  canonical) + `payload` có kiểu theo `visual_kind` + `narration` (VĂN VIẾT
  THUẦN — giữ nguyên số/ticker, KHÔNG phiên âm, KHÔNG viết số bằng chữ).
- **GIỮ NGUYÊN tại đây** (không move, không phụ thuộc AIGEN):
  - `render/infographic.py` — renderer SVG ảnh, $0, tất định.
  - `ProductionBlock` (`media_factory/spec.py`) — nhánh khối cho infographic.
  - Guardrail nhánh ảnh (nhẹ tay, chỉ soát `blocks[]`).
- Sau Gate 2: 100% tất định, KHÔNG LLM. Trí thông minh nằm ở Composer
  (TRƯỚC Gate 2) — mọi thứ sau đó chỉ ánh xạ/kiểm tra, không sinh nội dung
  mới.

### `aigen-pipeline` (TypeScript) — mọi thứ biến CONTENT.Output thành video

- `src/production-spec/spec.ts` — PORT `ProductionScene` từ Python
  (`media_factory/spec.py`), giữ nguyên ngữ nghĩa 5 shape fact
  (scalar/range/delta/entity/entity_list), salience, `source_sentence` bắt
  buộc, NFC-normalize trước so khớp (evidence tiếng Việt có thể ở dạng NFD —
  lệch âm thầm nếu không chuẩn hoá).
- `src/production-spec/guardrail/` — PORT guardrail-2 nhánh VIDEO (soát
  `scenes[]`) từ `media_factory/spec.py::verify_spec()`. Nhánh ẢNH
  (`blocks[]`) **ở lại** Python, không port.
- `src/production-spec/scene-builder/` — MỚI. Ánh xạ THUẦN TẤT ĐỊNH:
  `CONTENT.Output` (typed scene, video) → `ProductionScene[]`. KHÔNG LLM,
  KHÔNG regex đoán ngữ nghĩa từ văn xuôi.
- `src/production-spec/voice/` — MỚI. Chuẩn hoá `voice_text` tất định:
  số → chữ (thuật toán tiếng Việt) + ticker/viết tắt → phiên âm (tra từ điển
  `financial-voice-bible/.../pronunciation_dict.vi.json` ĐÃ CÓ SẴN trong repo
  này — đọc file, KHÔNG gọi service HTTP :8881).
- `src/adapter/` — **GIỮ NGUYÊN**, đã xong (79/79 test, PR #1 merged).
  `ProductionScene` → `TemplateScript`.
- `src/render/` — Production Factory thật của AIGEN (ruột render, agent-B sở
  hữu). **KHÔNG đụng.**

### Thứ tự chạy pipeline video (aigen-pipeline)

```
CONTENT.Output (từ marketing-automation, qua data_root hoặc DB chung sau này)
  → scene-builder (map thuần tất định)
  → guardrail-2 (đối chiếu facts[], như bên ảnh nhưng cho scenes[])
  → voice (chuẩn hoá: số→chữ, ticker→phiên âm)
  → alias-guardrail (VERIFY sau chuẩn hoá — ticker lạ → throw, nêu rõ mã thiếu)
  → adapter (sceneToTemplateScene, ĐÃ XONG)
  → TemplateScript (script.json)
  → src/render/ (AIGEN thật — agent-B sở hữu)
```

### Vì sao guardrail-2 chạy TRƯỚC voice (R2, chốt 2026-07-19)

Thứ tự ban đầu đặt `voice` trước `guardrail-2`. **Đã đổi** sau lần chạy
end-to-end đầu tiên trên output Composer THẬT (3 bài trong
`reports/regression_video_prompt/`): guardrail chặn CẢ 3 bài, và phần lớn vi
phạm là DƯƠNG TÍNH GIẢ.

Nguyên nhân gốc: đứng sau `voice`, guardrail buộc phải **đọc ngược văn xuôi
tiếng Việt** thành số — việc này nhập nhằng không gỡ được bằng quy tắc:
- "năm" vừa là chữ số 5 vừa là "year" → "năm 2020" ra 5020.
- "Quý **hai năm** nay" bị đọc thành số 2.
- Bộ SINH phát ra "một trăm linh năm" (105) nhưng từ vựng parser thiếu
  "linh" → **162/2001 số nguyên** không đọc ngược được (mọi số dạng x0y).

Đứng TRƯỚC `voice`, guardrail thấy `narration` NGUYÊN DẠNG CHỮ SỐ (theo
`docs/CONTENT_OUTPUT_SCHEMA.md`: narration giữ nguyên số/ticker) → đối chiếu
`facts[].canonical_*` là khớp CHÍNH XÁC, không phải đoán.

**Phần đánh đổi** — mất lớp kiểm trên output của chính normalizer — được mua
lại RẺ HƠN và CHẶT HƠN bằng **property round-trip test**
(`aigen/src/production-spec/voice/spell-out-numbers.test.ts`): mọi số mà
`spellOutNumbers()` sinh ra PHẢI đọc ngược đúng giá trị qua
`parseVnNumberWords()`. Nguyên tắc: **kiểm CÁI MÁY SINH, không đọc lại văn
xuôi tự do.** Chính test này đã phát hiện lỗi "linh" ở trên.

`alias-guardrail.ts` **giữ nguyên vị trí SAU `voice`** và giữ nguyên code —
việc của nó là bắt ticker mà `voice/` cố ý không đoán phiên âm, thứ chỉ tồn
tại sau chuẩn hoá. Vai trò trong tài liệu vẫn là "lưới verify SAU lớp chuẩn
hoá tất định", không phải "chặn output Opus trực tiếp".

## `facts[]` — hợp đồng CHÉO REPO, điểm drift tiềm tàng DUY NHẤT

`facts[]` (5 shape: scalar/range/delta/entity/entity_list) từng chỉ sống
trong Python (`twmkt.models.Fact`). Giờ **cả 2 repo đều đọc** — Python sinh,
TypeScript (`guardrail/` PORT) đối chiếu lại. Vì vậy shape này phải:

- Định nghĩa **MỘT LẦN** trong schema `CONTENT.Output` (JSON Schema hoặc
  tương đương, có version — xem `docs/CONTENT_OUTPUT_SCHEMA.md`).
- Đổi shape ở 1 bên mà không đổi bên kia = drift âm thầm, guardrail 2 phía
  sẽ hiểu khác nhau về cùng 1 dữ liệu. Đây là rủi ro kiến trúc lớn nhất của
  thiết kế 2-repo — không có cơ chế type-check xuyên ngôn ngữ tự động, chỉ
  có kỷ luật giữ đồng bộ tài liệu + test mỗi bên tự phủ theo đúng schema đã
  chốt.

## KHÔNG đụng (ranh giới sở hữu)

- `src/render/` (aigen-pipeline) — ruột render AIGEN, agent-B sở hữu.
- `src/adapter/` (aigen-pipeline) — đã xong, 79/79 test, PR #1 đã merge.
- `render/infographic.py`, `ProductionBlock`, guardrail nhánh ảnh
  (marketing-automation) — không phụ thuộc AIGEN, không move.

## Xem thêm

- Bản đồ code chi tiết từng file: `docs/MODULE_INDEX.md` (mỗi repo tự giữ
  bản của mình, có thể khác nhau về NỘI DUNG chi tiết dù cùng kiến trúc).
- Nợ dài hạn/VPS: `docs/VPS_MIGRATION_BACKLOG.md` (marketing-automation).
- Lịch sử quyết định trước lần tái cấu trúc này: `PROJECT_HANDOFF_P5.md`
  (marketing-automation) — các dòng nói "Production Factory = media_factory/"
  trong đó đã LỖI THỜI theo kiến trúc mới, xem ghi chú sửa tại chỗ.
