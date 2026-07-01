# CHANGELOG

## [0.2.0] - Sprint MVP-002 (Config + Sheets + Charter)
### Added
- `config/settings.yaml` + `src/twmkt/config.py`: cấu hình trung tâm (config-first),
  truy cập dotted key, expand `${ENV}` cho bí mật.
- `src/twmkt/approval/sheets_gate.py`: cổng duyệt Google Sheets (implement
  ApprovalGate) — control-plane duyệt nội dung, thay Dashboard sau không đổi lõi.
- `docs/google_sheets_setup.md`: hướng dẫn service account + cấu hình.
- CLAUDE.md hợp nhất: tầm nhìn Information→Knowledge→Content→Media→Distribution,
  MVP flow ánh xạ vào module, 8 nguyên tắc cốt lõi.

### Notes
- Kế thừa ý tưởng tốt từ bản thiết kế ChatGPT (config-first, Sheets-as-UI,
  Signal→Context→Hook, kỷ luật release) trên nền engine twmkt đang chạy.
- Bước "Hook" (góc marketing) sẽ thêm ở agents/ — đang triển khai.

## [0.1.0] - Phase 0
- Scaffold pipeline offline: collect → curate → RAG → research → 2 gate →
  produce (4 định dạng) → publish. 7 test pass, chạy CafeF thật ở $0 token.
