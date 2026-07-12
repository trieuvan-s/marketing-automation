"""Production Factory (twmkt.media_factory) — biến ĐẶC TẢ nội dung (do Content
Factory sinh, tầng `agents/` + `twmkt.agents.production`) thành MEDIA giao
được (ảnh, sau này video). 100% CODE TẤT ĐỊNH — KHÔNG có LLM nào chạy trong
package này.

TÊN GÓI: đề bài gốc đặt `twmkt.production`, phiên trước đổi sang `twmkt.factory`
— cả 2 đều ĐỤNG tên module đã có sẵn (`twmkt.agents.production` và
`twmkt.factory` — chính là factory.py, module lắp adapter trung tâm dùng
XUYÊN SUỐT dự án: `factory.build_store`/`make_llm`/`llm_status`/...). Tạo thư
mục `twmkt/factory/` đã PHÁ import `from twmkt import factory` ở TOÀN BỘ
scripts/tests hiện có (280+ test đỏ ngay khi phát hiện) — đã đổi ngay sang
`twmkt.media_factory` để tránh đụng CẢ HAI tên cũ. Xác nhận với người đọc
trước khi dùng tên khác trong tương lai — collision loại này rất dễ tái diễn
vì "production"/"factory" đều đã có chủ khác trong repo.

KHÔNG NHẦM với `twmkt.agents.production` (Content Factory — Writer/Composer,
CÓ dùng LLM, chạy TRƯỚC Gate 2) và `twmkt.factory` (adapter-factory trung tâm,
KHÔNG liên quan Production Factory). Ba tên gần giống nhau, BA vai trò khác
hẳn nhau — xem PROJECT_HANDOFF_P5.md để không nhầm khi mở phiên mới.
"""
