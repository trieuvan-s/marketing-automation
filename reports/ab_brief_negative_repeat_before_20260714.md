# Phase 3.1b — Lặp lại bài đối chứng âm `cang_bien_gdp` (prompt GOC (tai dung tu conversation, file that bi ghi de))

Chạy: 2026-07-14T19:21:27 · 0 lượt ghi Sheet.

Tín hiệu context đã xác nhận (Phase 3.1b): hải phòng (địa điểm tổ chức hội thảo — CHỈ đúng khi bị gán salience="subject").

## Tần suất salience-miss / 5 lượt

| Model | Miss / N lượt | Tỷ lệ | Chi tiết từng lượt |
|---|---|---|---|
| **sonnet** | 0/5 (lỗi: 0) | 0% | #1:sạch; #2:sạch; #3:sạch; #4:sạch; #5:sạch |
| **opus** | 0/5 (lỗi: 0) | 0% | #1:sạch; #2:sạch; #3:sạch; #4:sạch; #5:sạch |

## Chi tiết

| Model | Lượt | subject | context | miss | n_facts | Cost | Latency |
|---|---|---|---|---|---|---|---|
| opus | #1 | Vietnam Industrial Park Summit 2026 | Hải Phòng, Nguyễn Văn Khôi, Mỹ, Trung Quốc, Nhật Bản, Hiệp hội Bất động sản Việt Nam, Viện Nghiên cứu Chính sách và Chiến lược, Liên Chi hội Bất động sản Công nghiệp Việt Nam, CTCP IEC Consulting, Ban Chính sách, Chiến lược Trung ương | — | 14 | $0.1984 | 43.6s |
| opus | #2 | Diễn đàn Phát triển Khu Công nghiệp Việt Nam - Vietnam Industrial Park Summit 2026 | Mỹ, Trung Quốc, Nhật, Ban Chính sách, Chiến lược Trung ương, Hiệp hội Bất động sản Việt Nam, Viện Nghiên cứu Chính sách và Chiến lược, Liên Chi hội Bất động sản Công nghiệp Việt Nam, CTCP IEC Consulting, Nguyễn Văn Khôi | — | 13 | $0.2001 | 41.7s |
| opus | #3 | — | Mỹ, TQ, Nhật, Diễn đàn Phát triển Khu Công nghiệp Việt Nam - Vietnam Industrial Park Summit 2026, Ban Chính sách, Chiến lược Trung ương, Hiệp hội Bất động sản Việt Nam, Viện Nghiên cứu Chính sách và Chiến lược, Liên Chi hội Bất động sản Công nghiệp Việt Nam, CTCP IEC Consulting, Nguyễn Văn Khôi, Hải Phòng | — | 14 | $0.2447 | 63.5s |
| opus | #4 | — | Mỹ, Trung Quốc, Nhật, Diễn đàn Phát triển Khu Công nghiệp Việt Nam - Vietnam Industrial Park Summit 2026, Ban Chính sách, Chiến lược Trung ương, Hiệp hội Bất động sản Việt Nam, Viện Nghiên cứu Chính sách và Chiến lược, Liên Chi hội Bất động sản Công nghiệp Việt Nam, CTCP IEC Consulting, TS Nguyễn Văn Khôi, Hải Phòng | — | 14 | $0.2144 | 51.0s |
| opus | #5 | — | Mỹ, Trung Quốc, Nhật, Diễn đàn Phát triển Khu Công nghiệp Việt Nam - Vietnam Industrial Park Summit 2026, Hải Phòng, TS Nguyễn Văn Khôi, Ban Chính sách, Chiến lược Trung ương, Hiệp hội Bất động sản Việt Nam, Viện Nghiên cứu Chính sách và Chiến lược, Liên Chi hội Bất động sản Công nghiệp Việt Nam, CTCP IEC Consulting | — | 13 | $0.2150 | 53.8s |
| sonnet | #1 | Mỹ, TQ, Nhật | Hải Phòng, Diễn đàn Phát triển Khu Công nghiệp Việt Nam - Vietnam Industrial Park Summit 2026, Ban Chính sách, Chiến lược Trung ương, Hiệp hội Bất động sản Việt Nam, Viện Nghiên cứu Chính sách và Chiến lược, Liên Chi hội Bất động sản Công nghiệp Việt Nam, CTCP IEC Consulting, TS Nguyễn Văn Khôi, Cục Thống kê | — | 16 | $0.3173 | 96.5s |
| sonnet | #2 | Diễn đàn Phát triển Khu Công nghiệp Việt Nam - Vietnam Industrial Park Summit 2026, Mỹ, TQ, Nhật | Hải Phòng, Nguyễn Văn Khôi, Ban Chính sách, Chiến lược Trung ương, Hiệp hội Bất động sản Việt Nam, Viện Nghiên cứu Chính sách và Chiến lược, Liên Chi hội Bất động sản Công nghiệp Việt Nam, CTCP IEC Consulting | — | 15 | $0.3667 | 112.0s |
| sonnet | #3 | Mỹ, TQ, Nhật | Ban Chính sách, Chiến lược Trung ương, Hiệp hội Bất động sản Việt Nam, Viện Nghiên cứu Chính sách và Chiến lược, Liên Chi hội Bất động sản Công nghiệp Việt Nam, CTCP IEC Consulting, Hải Phòng, Diễn đàn Phát triển Khu Công nghiệp Việt Nam - Vietnam Industrial Park Summit 2026, Nguyễn Văn Khôi | — | 15 | $0.2067 | 72.7s |
| sonnet | #4 | Mỹ, TQ, Nhật | Hải Phòng, Diễn đàn Phát triển Khu Công nghiệp Việt Nam - Vietnam Industrial Park Summit 2026, Ban Chính sách, Chiến lược Trung ương, Hiệp hội Bất động sản Việt Nam, Viện Nghiên cứu Chính sách và Chiến lược, Liên Chi hội Bất động sản Công nghiệp Việt Nam, CTCP IEC Consulting, Nguyễn Văn Khôi | — | 15 | $0.2692 | 80.4s |
| sonnet | #5 | Diễn đàn Phát triển Khu Công nghiệp Việt Nam - Vietnam Industrial Park Summit 2026, Mỹ, TQ, Nhật | Hải Phòng, Ban Chính sách, Chiến lược Trung ương, Hiệp hội Bất động sản Việt Nam, Viện Nghiên cứu Chính sách và Chiến lược, Liên Chi hội Bất động sản Công nghiệp Việt Nam, CTCP IEC Consulting, Nguyễn Văn Khôi | — | 14 | $0.2274 | 85.8s |
