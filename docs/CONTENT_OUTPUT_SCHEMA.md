# CONTENT_OUTPUT_SCHEMA.md — hợp đồng CHÉO REPO, có version

> Tồn tại GIỐNG HỆT ở CẢ HAI repo (`marketing-automation/docs/` và
> `aigen-pipeline/docs/`). Đây là schema DUY NHẤT của `CONTENT.Output` dạng
> video (JSON) — ranh giới trung lập giữa Content Factory (Python, sinh) và
> aigen-pipeline (TypeScript, đọc + xây `ProductionScene[]`). Đổi shape ở
> đây PHẢI bump version + đồng bộ cả 2 repo trong CÙNG 1 lượt — xem
> `docs/ARCHITECTURE_MODULES.md` §"facts[] — điểm drift tiềm tàng DUY NHẤT".

**Version hiện tại: `1`** (chốt 2026-07-19, lần đầu định nghĩa dạng có kiểu —
trước đó là văn xuôi có đánh dấu `[t] voiceover / On-screen: / Hình ảnh: /
[CTA] / Nguồn: / disclaimer`, KHÔNG có version).

## Shape tổng (video)

```typescript
type ContentOutputVideo = {
  schema_version: 1;
  title: string;
  scenes: Scene[];          // 3-12 phần tử, scenes[0].role === "hook", scenes[last].role === "outro"
  source: string;           // domain nguồn, vd "cafef.vn" — từ dòng "Nguồn:" cũ
  disclaimer: string;       // NGUYÊN VĂN câu miễn trừ chuẩn, không diễn giải
  facts: Fact[];             // xem shape Fact bên dưới — CÙNG shape agents/brief.py sinh ra
};

type Scene = {
  role: "hook" | "body" | "outro";
  visual_kind: VisualKind;   // 1 trong 9 giá trị in-scope (xem bảng dưới) — "avatar" DEFERRED, không dùng
  payload: Payload;          // CÓ KIỂU theo visual_kind, xem bảng dưới — hiển thị, GIỮ nguyên số/ticker
  narration: string;         // VĂN VIẾT THUẦN — giữ nguyên số + ticker, KHÔNG phiên âm, KHÔNG viết
                              // số bằng chữ. Composer viết y hệt cách viết voiceover hiện tại.
                              // aigen-pipeline (voice/) chuẩn hoá trước khi thành ProductionScene.voice_text.
  fact_ref?: number[];       // index vào facts[] — scene này dựa trên fact nào (optional, cho guardrail-2)
};
```

## `visual_kind` — 9 giá trị in-scope (10 canonical, "avatar" DEFERRED)

Nguồn: `media_factory/spec.py::VISUAL_KINDS` (marketing-automation) — PHẢI
khớp `aigen-pipeline/src/adapter/visual-kind-map.ts::IN_SCOPE_VISUAL_KIND_MAP`
byte-for-byte. Đổi 1 bên mà không đổi bên kia = drift.

| visual_kind | payload (typed) |
|---|---|
| `title` | `{headline: string, subheadline?: string}` |
| `stat` | `{label: string, value: string, note?: string}` |
| `statement` | `{hero: string, desc: string}` |
| `list` | `{title: string, items: {title: string, desc: string, tag?: string}[]}` (adapter tự cắt còn ≤5) |
| `comparison` | `{left: {label: string, bullets: string[], stat?: string}, right: {label: string, bullets: string[], stat?: string}}` |
| `quote` | `{quote: string, attribution?: string}` |
| `ticker` | `{items: {symbol: string, value: string}[]}` |
| `news` | `{headline: string, source: string}` |
| `outro` | `{brand_name: string, tagline?: string, cta?: string}` — CTA + disclaimer gộp vào scene outro, KHÔNG phải field rời cấp top |

## `Fact` — PHẢI khớp `twmkt.models.Fact` (marketing-automation) từng field

Nguồn thật (đọc trực tiếp `src/twmkt/models.py`, KHÔNG suy đoán):

```typescript
type FactShape = "scalar" | "range" | "delta" | "entity_list" | "entity";

type Fact = {
  value: string;              // scalar: "8,18"/"1.200" (nguyên văn, KHÔNG kèm unit).
                               // entity: tên thực thể đơn ("SHS", "Nghị quyết 57").
                               // range/delta/entity_list: RỖNG — dùng field riêng.
  label: string;               // nhãn CÓ NGHĨA, vd "GDP 6T/2026"
  unit: string | null;         // "%", "tỷ đồng"... null nếu không kèm unit
  source: string;              // CÂU NGUYÊN VĂN chứa dữ kiện (audit/verify) — BẮT BUỘC khác rỗng
  kind: "percent" | "money" | "count" | "growth" | "date" | "ranking" | "target" | "other";
  shape: FactShape;
  raw: string;                 // cụm nguyên văn (value+unit, kể cả từ xấp xỉ) — substring THẬT của evidence
  canonical_value: number | null;   // scalar: số máy đọc — CODE tính, KHÔNG phải AI
  approx: boolean;             // true nếu raw có từ xấp xỉ (gần/khoảng/xấp xỉ/hơn/trên/dưới)

  // CHỈ dùng khi shape === "range"
  value_low?: string;
  value_high?: string;
  canonical_low?: number | null;
  canonical_high?: number | null;

  // CHỈ dùng khi shape === "delta"
  from_value?: string;
  to_value?: string;
  canonical_from?: number | null;
  canonical_to?: number | null;

  // CHỈ dùng khi shape === "entity_list"
  entities?: string[];

  // CHỈ dùng khi shape === "entity"
  entity_type?: "ticker" | "company" | "policy" | "place" | "person" | "project" | "other";

  // CHỈ dùng khi shape === "entity" | "entity_list"
  salience?: "subject" | "context";
};
```

**Ràng buộc chống bịa (MỌI shape, đã enforce ở Python phía sinh —
`agents/brief.facts_from_llm_output()`, TypeScript phía đọc KHÔNG cần enforce
lại, chỉ TIN DỮ LIỆU ĐÃ QUA Gate 2)**: mỗi Fact value chính PHẢI xuất hiện
nguyên văn trong `source`. Fact không verify được đã bị loại TRƯỚC khi vào
`CONTENT.Output` — phía TypeScript không cần re-validate việc này, guardrail-2
phía TypeScript chỉ đối chiếu `scenes[].narration`/`payload` với `facts[]` đã
sạch (soát BỊA Ở KHÂU HIỂN THỊ, không phải bịa ở khâu trích).

**NFC-normalize TRƯỚC khi so khớp chuỗi** (`source`, `value`, `entities[]`) —
evidence tiếng Việt crawl về có thể ở dạng NFD (dấu tách rời) tuỳ nguồn, so
khớp thô theo byte sẽ lệch ÂM THẦM dù mắt nhìn giống hệt.

## Ví dụ đầy đủ (mẫu FPT, rút gọn)

```json
{
  "schema_version": 1,
  "title": "FPT: khối ngoại bán ròng 7 phiên liên tiếp",
  "scenes": [
    {
      "role": "body",
      "visual_kind": "stat",
      "payload": {
        "label": "FPT 15/7",
        "value": "-4,98%",
        "note": "Xuống 66.800đ — khối ngoại bán ròng 7 phiên liên tiếp, ~739 tỷ đồng"
      },
      "narration": "Phiên 15/7, FPT giảm 4,98%, xuống 66.800 đồng — khối ngoại bán ròng 7 phiên liên tiếp, khoảng 739 tỷ đồng."
    },
    {
      "role": "outro",
      "visual_kind": "outro",
      "payload": {
        "brand_name": "FVA Capital",
        "cta": "Bạn nghĩ đây là cơ hội hay tín hiệu rủi ro thật?"
      },
      "narration": "Bạn nghĩ đây là cơ hội hay tín hiệu rủi ro thật?"
    }
  ],
  "source": "cafef.vn",
  "disclaimer": "Nội dung mang tính thông tin, không phải khuyến nghị đầu tư"
}
```

## Điểm KHÔNG có trong schema (cố ý)

- `templateId`, tên slot AIGEN, `"hyperframes"` — cấm tuyệt đối (Nguyên tắc
  vendor-neutral, xem `docs/ARCHITECTURE_MODULES.md`).
- Mốc thời gian `[0-5s]`/`t` — bỏ. AIGEN tự fit clip theo độ dài audio TTS
  render từ `narration` (đã chuẩn hoá), không đọc timestamp từ input.
  `TemplateScene` (AIGEN) không có field thời lượng.
- `narration.spoken`/dạng phiên âm — KHÔNG do Composer sinh. Chuẩn hoá tất
  định ở `aigen-pipeline/src/production-spec/voice/`, xem
  `docs/ARCHITECTURE_MODULES.md`.
- `branding`, `aspect: "4:5"` — chưa ai đọc, không thêm (giữ đúng phạm vi
  đã chốt, xem `docs/CONTRACT_DECISIONS_LOCKED.md` (c)/(d) phía aigen-pipeline).
