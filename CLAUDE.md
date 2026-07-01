# CLAUDE.md — hướng dẫn cho Claude Code khi làm việc trên repo này

## Dự án
Marketing Automation cho Turtle Wealth VN: thu thập thông tin (tài chính, doanh
nghiệp, chính sách, thế giới) → chuẩn hóa & lưu trữ → **người duyệt** → sản xuất
nội dung số (bài viết, infographic, kịch bản video, newsletter) → **người duyệt**
→ phân phối MXH. Mục tiêu: kênh vệ tinh tăng độ phủ.

Đây là **service độc lập**. KHÔNG gộp với hệ Research (`ervn` đã tách sang project
khác). Nếu cần dữ liệu nghiên cứu, tiêu thụ qua contract `ResearchBrief` —
KHÔNG reintroduce `ervn` vào repo này.

## Nguyên tắc bất di bất dịch
1. **Tất định trước, LLM sau.** Crawl/dedup/chuẩn hóa/chunk/compliance/vector
   search = Python thuần ($0 token). LLM chỉ chạm ở Researcher (gửi *chunk liên
   quan*) và các producer viết-bằng-LLM.
2. **LLM đắt chỉ chạy SAU cổng duyệt 1.** Đừng sinh nội dung cho chủ đề chưa
   được người duyệt.
3. **Adapter ở mọi điểm nối ngoài**: collectors, publishers, embedder, vector
   store, LLM. Thêm nguồn/nền tảng = thêm adapter, không sửa lõi.
4. **Giữ demo offline chạy được** (`python -m twmkt.demo`, $0 token) và **mọi
   thay đổi phải kèm test**. Chạy `python tests/test_pipeline.py` trước khi commit.
5. Nội dung tài chính: giữ guardrail compliance; không nới lỏng claim cấm.

## Tầng token (rẻ → đắt)
Tầng 0 (free): crawl, curation, chunk, embedding local, vector search, infographic
spec, newsletter. Tầng 1 (rẻ): Haiku cho triage/tóm tắt nếu cần. Tầng 2 (đắt):
Sonnet cho viết bài & kịch bản, chỉ sau cổng 1.

## Chạy
```
cd src && python -m twmkt.demo
python tests/test_pipeline.py     # hoặc python -m pytest
```

## Lộ trình khi lên production
MockCollector→Crawl4aiCollector; HashingEmbedder→SentenceTransformer local;
InMemoryVectorStore→Qdrant; MockLLM→AnthropicLLM (Haiku/Sonnet theo tầng);
orchestrator→LangGraph StateGraph; AutoApproveGate→cổng duyệt React UI;
ConsolePublisher→adapter nền tảng thật.
