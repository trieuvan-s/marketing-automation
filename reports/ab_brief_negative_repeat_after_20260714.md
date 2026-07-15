# Phase 3.1b — Lặp lại bài đối chứng âm `cang_bien_gdp` (prompt MOI (siet salience))

Chạy: 2026-07-14T19:20:12 · 0 lượt ghi Sheet.

Tín hiệu context đã xác nhận (Phase 3.1b): hải phòng (địa điểm tổ chức hội thảo — CHỈ đúng khi bị gán salience="subject").

## Tần suất salience-miss / 5 lượt

| Model | Miss / N lượt | Tỷ lệ | Chi tiết từng lượt |
|---|---|---|---|
| **sonnet** | 0/5 (lỗi: 0) | 0% | #1:sạch; #2:sạch; #3:sạch; #4:sạch; #5:sạch |
| **opus** | 0/5 (lỗi: 0) | 0% | #1:sạch; #2:sạch; #3:sạch; #4:sạch; #5:sạch |

## Chi tiết

| Model | Lượt | subject | context | miss | n_facts | Cost | Latency |
|---|---|---|---|---|---|---|---|
| opus | #1 | — | Mỹ, TQ, Nhật, Diễn đàn Phát triển Khu Công nghiệp Việt Nam - Vietnam Industrial Park Summit 2026, Ban Chính sách, Chiến lược Trung ương, Hiệp hội Bất động sản Việt Nam, Viện Nghiên cứu Chính sách và Chiến lược, Liên Chi hội Bất động sản Công nghiệp Việt Nam, CTCP IEC Consulting, TS Nguyễn Văn Khôi, Hải Phòng | — | 14 | $0.2361 | 56.7s |
| opus | #2 | — | Diễn đàn Phát triển Khu Công nghiệp Việt Nam - Vietnam Industrial Park Summit 2026, Hải Phòng, Ban Chính sách, Chiến lược Trung ương, Hiệp hội Bất động sản Việt Nam, Viện Nghiên cứu Chính sách và Chiến lược, Liên Chi hội Bất động sản Công nghiệp Việt Nam, CTCP IEC Consulting, Nguyễn Văn Khôi | — | 13 | $0.2026 | 40.8s |
| opus | #3 | — | Mỹ, Trung Quốc, Nhật, Diễn đàn Phát triển Khu Công nghiệp Việt Nam - Vietnam Industrial Park Summit 2026, Hải Phòng, Hiệp hội Bất động sản Việt Nam, Nguyễn Văn Khôi | — | 15 | $0.2147 | 47.1s |
| opus | #4 | — | Mỹ, Trung Quốc, Nhật, Diễn đàn Phát triển Khu Công nghiệp Việt Nam - Vietnam Industrial Park Summit 2026, Hải Phòng, Ban Chính sách, Chiến lược Trung ương, Hiệp hội Bất động sản Việt Nam, Viện Nghiên cứu Chính sách và Chiến lược, Liên Chi hội Bất động sản Công nghiệp Việt Nam, CTCP IEC Consulting, Nguyễn Văn Khôi | — | 14 | $0.2033 | 41.4s |
| opus | #5 | — | Mỹ, TQ, Nhật, Diễn đàn Phát triển Khu Công nghiệp Việt Nam - Vietnam Industrial Park Summit 2026, Hải Phòng, Hiệp hội Bất động sản Việt Nam, Nguyễn Văn Khôi, Cục Thống kê | — | 15 | $0.2368 | 61.1s |
| sonnet | #1 | Mỹ, TQ, Nhật | Hải Phòng, Diễn đàn Phát triển Khu Công nghiệp Việt Nam - Vietnam Industrial Park Summit 2026, Ban Chính sách, Chiến lược Trung ương, Hiệp hội Bất động sản Việt Nam, Viện Nghiên cứu Chính sách và Chiến lược, Liên Chi hội Bất động sản Công nghiệp Việt Nam, CTCP IEC Consulting, Nguyễn Văn Khôi | — | 14 | $0.2098 | 70.0s |
| sonnet | #2 | Mỹ, TQ, Nhật | Viện Nghiên cứu Chính sách và Chiến lược, Liên Chi hội Bất động sản Công nghiệp Việt Nam, CTCP IEC Consulting, Diễn đàn Phát triển Khu Công nghiệp Việt Nam - Vietnam Industrial Park Summit 2026, Hải Phòng, Ban Chính sách, Chiến lược Trung ương, Hiệp hội Bất động sản Việt Nam, Nguyễn Văn Khôi | — | 16 | $0.3007 | 82.5s |
| sonnet | #3 | Mỹ, TQ, Nhật | Hải Phòng, Diễn đàn Phát triển Khu Công nghiệp Việt Nam - Vietnam Industrial Park Summit 2026, Ban Chính sách, Chiến lược Trung ương, Hiệp hội Bất động sản Việt Nam, Viện Nghiên cứu Chính sách và Chiến lược, Liên Chi hội Bất động sản Công nghiệp Việt Nam, CTCP IEC Consulting, TS Nguyễn Văn Khôi | — | 15 | $0.2293 | 83.7s |
| sonnet | #4 | — | Hải Phòng, Diễn đàn Phát triển Khu Công nghiệp Việt Nam - Vietnam Industrial Park Summit 2026, Ban Chính sách, Chiến lược Trung ương, Hiệp hội Bất động sản Việt Nam, Viện Nghiên cứu Chính sách và Chiến lược, Liên Chi hội Bất động sản Công nghiệp Việt Nam, CTCP IEC Consulting, Nguyễn Văn Khôi, Mỹ, TQ, Nhật | — | 14 | $0.2168 | 76.6s |
| sonnet | #5 | Mỹ, TQ, Nhật | Hải Phòng, Diễn đàn Phát triển Khu Công nghiệp Việt Nam - Vietnam Industrial Park Summit 2026, Ban Chính sách, Chiến lược Trung ương, Hiệp hội Bất động sản Việt Nam, Viện Nghiên cứu Chính sách và Chiến lược, Liên Chi hội Bất động sản Công nghiệp Việt Nam, CTCP IEC Consulting, TS Nguyễn Văn Khôi, Cục Thống kê | — | 18 | $0.2236 | 80.8s |
