# Thiết kế 3 Agent sản xuất (Approve → CONTENT)

Chạy SAU cổng duyệt 1 (Status=APPROVE). Đây là lúc bật **Sonnet** (đắt, đã qua duyệt).
Mỗi agent = **prompt chuyên nghiệp + schema Output + guardrail**, trên base sẵn có.

## Cơ chế nạp prompt từ tab PROMPTS
- Text prompt để trong repo: `prompts/<name>.<version>.md` (version-controlled, diff được).
- Tab **PROMPTS** (Name|Version|Enable) = *bảng kích hoạt*: agent đọc dòng Enable=TRUE của
  Name mình → nạp đúng `prompts/{Name}.{Version}.md`. Không thấy → dùng default nội bộ.
- Đổi văn phong = sửa file prompt + tăng version + Enable ở sheet, KHÔNG sửa code.

## Đầu vào chung (từ 1 dòng CONTEXT approved)
`{title, hook, angle, headlines, tickers, evidence[], source_url, group, topic}`

## Guardrail chung (tất định, chạy SAU khi sinh, trước khi ghi CONTENT)
- Bắt buộc có disclaimer "không phải khuyến nghị đầu tư".
- Chặn claim cấm: "chắc chắn lãi", "cam kết lợi nhuận", "khuyến nghị mua/bán".
- Mọi CON SỐ phải xuất hiện trong `evidence` (không bịa số).
- Bắt buộc trích nguồn báo (ghi "Theo <publisher>").
- Vi phạm -> đánh dấu Status=ERROR + ghi lý do, KHÔNG publish.

---

## 1. AnalysisWriterAgent — Bài phân tích
**Model:** Sonnet. **Name (PROMPTS):** `analysis`.

**System prompt (prompts/analysis.v1.md):**
> Bạn là chuyên viên phân tích của Turtle Wealth, viết cho nhà đầu tư cá nhân VN.
> Viết bài phân tích tài chính RÕ RÀNG, TRUNG LẬP, BÁM SÁT dữ liệu được cung cấp.
> Cấu trúc: (1) mở bài từ hook, (2) bối cảnh ngắn, (3) phân tích số liệu trong
> evidence (giải thích ý nghĩa, không chỉ thuật lại), (4) tác động với NĐT
> (cơ hội/rủi ro, trung lập), (5) disclaimer. KHÔNG bịa số ngoài evidence.
> KHÔNG khuyến nghị mua/bán. Trích nguồn báo. Giọng chuyên nghiệp, dễ đọc.

**Output schema (JSON):**
```json
{"title": str, "sapo": str,
 "sections": [{"heading": str, "content": str}],
 "disclaimer": str, "sources": [str]}
```

---

## 2. VideoScriptAgent — Kịch bản video ngắn
**Model:** Sonnet. **Name (PROMPTS):** `video`.

**System prompt (prompts/video.v1.md):**
> Bạn viết kịch bản video ngắn (~45–60s) cho kênh tài chính Turtle Wealth.
> Bố cục: HOOK (0–3s, dùng hook đã có) → 3 beat nội dung (mỗi beat 1 ý + số liệu
> từ evidence) → CTA. Với mỗi cảnh: lời thoại (voiceover) NÓI tự nhiên, chữ chạy
> trên hình (on-screen text) ngắn, gợi ý hình ảnh. Canh thời lượng. Kết bằng
> disclaimer 1 dòng. KHÔNG bịa số, KHÔNG hô hào mua.

**Output schema (JSON):**
```json
{"title": str, "duration_sec": int,
 "scenes": [{"t": str, "voiceover": str, "on_screen_text": str, "visual_hint": str}],
 "cta": str, "disclaimer": str}
```

---

## 3. InfographicSpecAgent — Spec infographic
**Model:** Sonnet (chỉ cho headline/insight; số liệu lấy tất định từ evidence).
**Name (PROMPTS):** `infographic`.

**System prompt (prompts/infographic.v1.md):**
> Bạn tạo SPEC infographic (JSON) cho designer/tool render — KHÔNG vẽ ảnh.
> Chọn 3–5 số liệu NỔI BẬT NHẤT có trong evidence + 1 takeaway. Headline ngắn, gây
> chú ý. Chỉ dùng số CÓ trong evidence. Footer gồm disclaimer + nguồn.

**Output schema (JSON):**
```json
{"headline": str, "subhead": str,
 "stats": [{"label": str, "value": str, "emphasis": bool}],
 "takeaway": str, "footer": {"disclaimer": str, "source": str}}
```

---

## Ghi CONTENT
Mỗi sản phẩm -> 1 dòng tab **CONTENT** (`Context | Type | Status | Output`) + file
`storage/output/<ts>-<slug>.<type>.json/.md`. Type ∈ {article, video, infographic}.
Status: DONE nếu qua guardrail, ERROR nếu vi phạm. Cột Output = link/preview.
