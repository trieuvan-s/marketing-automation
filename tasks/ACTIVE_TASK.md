# ACTIVE_TASK — AigenAdapter + seam subprocess (ghép Content Factory → AIGEN → video)

## QUY ƯỚC WORKFLOW (đọc trước, mọi phiên)
1. Đọc `CLAUDE.md` (quy tắc chung) → `tasks/ACTIVE_TASK.md` (file này) → tra `docs/MODULE_INDEX.md` khi cần định vị code. **KHÔNG khám phá lại repo từ đầu.**
2. Chỉ đụng file trong SCOPE khai báo dưới. Cần ra ngoài scope → **DỪNG-BÁO-CÁO**, chờ duyệt.
3. **DỪNG-BÁO-CÁO mỗi phase.** KHÔNG auto-commit. Chấm trên output thật.
4. Sau task: cập nhật `docs/HANDOFF.md` (ghi đè) + `reports/TEST_RESULT.md`.

## Mục tiêu
Ghép đường VIDEO: `ProductionSpec (variant=video, scenes[])` → **AigenAdapter** (dịch sang `TemplateScript` của AIGEN) → AIGEN render → thu `video.mp4`. Đây là lát cắt dọc video đầu tiên.

## Phạm vi HAI REPO (ranh giới cứng)
- **`../aigen-fva-capital/`** (repo AIGEN, sibling, git RIÊNG): AigenAdapter (TS) + bảng ánh xạ config. Sửa ở đây KHÔNG được lẫn vào git của marketing-automation.
- **`marketing-automation/`**: seam subprocess (Python) gọi AIGEN + thu kết quả. CHỈ phần này vào git marketing-automation.
- `git status` của marketing-automation phải KHÔNG xuất hiện file AIGEN.

## Quyết định kiến trúc đã CHỐT (không mở lại)
- **`ProductionSpec` vendor-neutral: KHÔNG chứa `templateId`.** Ánh xạ `visual_kind → templateId` sống trong **config của adapter**, không trong spec.
- **Adapter TẤT ĐỊNH, KHÔNG LLM.** Cùng ProductionSpec → cùng TemplateScript.
- **`voice.provider` của AIGEN KHÔNG map vào ProductionSpec** (đúng — vendor-neutral), nhưng
  **KHÔNG phải dead code phía AIGEN** (kết luận sai ở phase trước, đã sửa): đây là Zod
  discriminator BẮT BUỘC trên `TemplateScriptSchema` (`z.literal("omnivoice")`) — engine TTS
  thật chọn qua `TTS_PROVIDER` (env, phía operator/máy render, xem AIGEN `src/config.ts`),
  KHÔNG liên quan field này. Adapter vẫn LUÔN emit cứng `{"provider":"omnivoice","speed":1.0}`
  vì schema bắt buộc phải có giá trị, và đó là giá trị DUY NHẤT hợp lệ hiện tại.
- **Alias-theo-kênh:** `voice_text` CẤM ticker/viết-tắt (TTS đọc "HVN"→"hát-vê-en"); số viết bằng chữ (ràng buộc voiceText của AIGEN). Slot hiển thị thì được.
- **Lát cắt đầu: CHỈ hook/body/outro (11 template gốc), 9:16. KHÔNG avatar** (chờ HeyGen). TTS: **mock/OmniVoice** cho test luồng (ElevenLabs cần key+voiceID, chưa có — KHÔNG chặn adapter).
- AIGEN `CLAUDE.md §9` đã chừa sẵn ProductionSpec/AigenAdapter/Renderer-interface — tôn trọng ranh giới đó, AIGEN là Renderer.

---

## Phase 0 — Discovery + thiết kế ánh xạ (đọc, CHƯA code) — phần rủi ro nhất
Đọc (dùng MODULE_INDEX + CATALOG đã có): AIGEN `TemplateScriptSchema`, **inputs BẮT BUỘC của từng template** (11 template hook/body/outro), entry point pipeline (`npm run pipeline`/`cli.ts` — nhận `script.json` thế nào, trả `video.mp4` ở đâu), ràng buộc scene (3–12 cảnh, đầu=hook, cuối=outro). Đọc `ProductionScene` (media_factory/spec.py) hiện tại.

Báo cáo:
1. **Bảng ánh xạ `visual_kind → templateId`** (10 giá trị → template thật). Nhiều template/1 visual_kind (vd title→4 template) → nêu **quy tắc chọn tất định** (theo role+variant, hay default+rotation). avatar → đánh dấu DEFERRED.
2. **Với mỗi template: inputs bắt buộc là gì**, và `ProductionScene.slots` hiện có cung cấp đủ không? Chỗ nào THIẾU field → báo (đây là gap phải lấp trước khi render được).
3. Điểm nối subprocess: Content Factory ghi `script.json` ở đâu, gọi lệnh gì, thu `video.mp4` ở đâu, mã lỗi ra sao.
4. `voice_text` từ spec có sẵn cho scene video chưa? (báo cáo trước từng nói build_spec_from_content chưa build scene video — xác nhận trạng thái thật.)

**DỪNG. BÁO CÁO bảng ánh xạ + gap inputs. Chờ duyệt trước khi code.**

---

## Phase 1 — Bảng ánh xạ config (AIGEN side)
Ghi bảng `visual_kind → templateId` + quy tắc chọn vào **config của adapter** (không hard-code trong code TS). Test: mỗi visual_kind resolve đúng 1 templateId tất định.

**DỪNG. BÁO CÁO. Chờ duyệt.**

## Phase 2 — AigenAdapter (TS, AIGEN side)
`ProductionSpec JSON → TemplateScript`: map visual_kind→templateId qua config; điền inputs từ slots (theo gap đã rõ ở Phase 0); enforce thứ tự (đầu=hook, cuối=outro) + ràng buộc 3–12 cảnh; chuyển voice_text (enforce alias-theo-kênh: reject nếu có ticker/viết-tắt, số phải là chữ). Test: spec hợp lệ → TemplateScript hợp lệ; spec vi phạm (ticker trong voice_text, <3 cảnh, thiếu hook/outro) → lỗi rõ ràng.

**DỪNG. BÁO CÁO. Chờ duyệt.**

## Phase 3 — Seam subprocess (Python, marketing-automation side)
Viết caller: dựng ProductionSpec (video) → serialize JSON → gọi AIGEN qua subprocess (`npm run pipeline` tại `../aigen-fva-capital/`) → thu `video.mp4` + xử lý exit code/timeout/lỗi. AIGEN ở repo riêng, gọi qua đường dẫn config (giống base_path). Test: mock subprocess (không chạy render thật) — luồng ghi JSON → gọi → thu file → xử lý lỗi đúng.

**DỪNG. BÁO CÁO. Chờ duyệt.**

## Phase 4 — Lát cắt dọc video THẬT (1 tin)
1 tin video thật → ProductionSpec → adapter → AIGEN render (TTS mock/OmniVoice) → `video.mp4` 9:16. Ghi vào data_root theo ngày. **GIAO file video** để xem.

**DỪNG. GIAO VIDEO. BÁO CÁO. KHÔNG commit.**

---

## Ghi chú chuyển giao (HANDOFF.md)
- Bảng `visual_kind→templateId` — nguồn để mở rộng template sau.
- Gap inputs template (nếu có) — chỗ cần thêm field ProductionScene sau.
- ElevenLabs (key+voiceID) chưa wire — TTS đang mock/OmniVoice; đổi khi có key.
- guardrail-2 trên `blocks[]` (đường infographic) VẪN nợ từ Phase 3 ProductionSpec — làm sau.

## Nghiệm thu
Adapter tất định (cùng spec→cùng TemplateScript) · ProductionSpec vẫn 0 templateId (vendor-neutral) · alias-theo-kênh enforce trong voice_text · seam thu được video.mp4, xử lý lỗi đúng · file AIGEN không lẫn git marketing-automation · 1 video thật giao được · suite xanh · không auto-commit.