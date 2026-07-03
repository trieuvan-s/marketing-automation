# twmkt — Turtle Wealth VN Marketing Automation

Hệ thống tự động hóa marketing cho Turtle Wealth VN, phục vụ xây kênh vệ tinh
tăng độ phủ: tự động thu thập thông tin (tài chính, doanh nghiệp, chính sách,
thế giới) → chuẩn hóa & lưu trữ → **người duyệt** → sản xuất nội dung số (bài
phân tích / infographic / kịch bản video / newsletter) → **người duyệt** →
phân phối lên mạng xã hội.

Phase 0: khung chạy được offline ($0 token, không cần mạng/khóa API), 7 test pass.

## Nguyên tắc

- **Tất định trước, LLM sau.** Đẩy tối đa việc xuống tầng miễn phí; LLM đắt chỉ
  chạm vào ở đúng khoảnh khắc sinh nội dung, và chỉ SAU khi người duyệt.
- **Đội chuyên trách, KHÔNG bầy agent tự hành.** Máy trạng thái tất định điều
  phối các agent chuyên biệt + 2 cổng người duyệt (≈ mô hình LangGraph).
- **Tách service, chia sẻ dữ liệu.** Marketing độc lập; tích hợp Research qua
  contract `ResearchBrief`. Knowledge Layer thiết kế để dùng chung về sau.
- **Adapter ở mọi điểm nối ngoài** (collectors, publishers, embedder, vector store).

## Tầng chi phí token

| Giai đoạn | Tầng | Chi phí |
|---|---|---|
| Crawl, dedup, chuẩn hóa, trích mã, tag, chunk, compliance, lọc liên quan | 0 — tất định | $0 |
| Embedding (local), vector search | 0-1 | ~$0 sau setup |
| Sinh Infographic spec, Newsletter | 0 — tất định | $0 |
| Researcher (chỉ gửi chunk liên quan) | 2 — LLM | thấp |
| Viết bài, kịch bản video | 2 — LLM | phần chính |

Cổng duyệt 1 đứng TRƯỚC khâu sinh nội dung đắt → không đốt token cho chủ đề bị loại.

## Luồng

```
Nguồn → Collector(Crawl4AI) → Chuẩn hóa+Lưu → Index RAG
   → Researcher(RAG) → [CỔNG 1] → Sản xuất(Article/Infographic/Video/Newsletter)
   → Compliance → [CỔNG 2] → Publishers
```

## Cấu trúc

```
src/twmkt/
  models.py            # data contracts + PipelineState
  collectors/          # base + mock + crawl4ai_collector
  curation/            # normalize (dedup, trích mã, tag) + store
  knowledge/           # rag: chunk + embed(local) + vector store + retriever
  agents/              # base(LLM mock/Anthropic) + researcher + producers
  guardrails/          # compliance
  approval/            # gate (Auto/Console) — human-in-the-loop
  publishers/          # base + console + stub
  orchestrator.py      # máy trạng thái = LangGraph tương lai
  demo.py
tests/test_pipeline.py
```

## Chạy

```bash
cd src && python -m twmkt.demo
python tests/test_pipeline.py      # hoặc: python -m pytest
```

## Production (Phase 1+)

1. `orchestrator.py` → LangGraph `StateGraph` (giữ nguyên agents/adapters).
2. `MockCollector` → `Crawl4aiCollector` (`pip install crawl4ai && crawl4ai-setup`).
3. `HashingEmbedder` → SentenceTransformer local (vẫn $0 token); `InMemoryVectorStore` → Qdrant.
4. `MockLLM` → `AnthropicLLM`: Haiku cho triage, Sonnet chỉ cho sinh nội dung.
5. `AutoApproveGate` → cổng duyệt thật trên React UI (LangGraph interrupt).
6. `ConsolePublisher` → adapter nền tảng thật (xem ghi chú giới hạn API trong `publishers/base.py`).

## Cấu hình Google Sheets

Demo duyệt qua Google Sheet (`scripts/review_to_sheet.py`: crawl thật → ghi
title + hook lên tab CONTEXT để duyệt) cần **2 tham số**, đều nằm ở
`config/settings.yaml` (mục `sheets`) và **CÓ THỂ THAY ĐỔI** trực tiếp tại đây:

```yaml
sheets:
  spreadsheet_id: "157b9WY9cpgLvzNP2TH8loN-6AiEy6YXmGpFdObYhNwo"  # ID lấy từ URL Sheet
  creds_path: "secrets/sa.json"        # đường dẫn khóa service account (JSON)
```

- **`spreadsheet_id`** — lấy từ URL: `https://docs.google.com/spreadsheets/d/<ID>/edit`.
- **`creds_path`** — trỏ tới file khóa service account JSON.

**Thứ tự ưu tiên** khi chạy: biến môi trường `TWMKT_SHEET_ID` / `TWMKT_SHEETS_CREDS`
(nếu đặt, để override tạm) **→** giá trị trong `settings.yaml`. Không bắt buộc đặt
biến môi trường; cả hai trống mới báo lỗi hướng dẫn.

**Bí mật (`secrets/`)** — đặt file khóa `sa.json` vào thư mục `secrets/`. Thư mục
này (và mọi `*.json`) đã nằm trong `.gitignore` nên **KHÔNG commit** khóa lên git.
Chia sẻ Sheet với email service account (quyền Editor). Chi tiết:
[docs/google_sheets_setup.md](docs/google_sheets_setup.md).

## Lưu ý

- Tôn trọng robots.txt, rate-limit, ToS khi crawl.
- Guardrail tự động chặn claim cấm; người vẫn duyệt lần cuối ở Cổng 2.
