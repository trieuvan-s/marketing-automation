/**
 * execute_trigger.gs — nửa "Apps Script" của dây webhook nấc 1
 * (docs/VPS_MIGRATION_BACKLOG.md A1). Thêm menu "Thực Thi" trên tab CONTEXT,
 * bắn HTTP POST tới webhook (api/main.py::/webhook/execute) cho ĐÚNG
 * topic_key của dòng đang chọn, thay vì chờ scheduler quét 30 phút/lần.
 *
 * CHƯA CHẠY THẬT trên Sheet sống — chỉ viết code + hướng dẫn cài (xem
 * README.md). Việc cài + chạy thật do Lead/user tự duyệt riêng, PHẢI
 * snapshot Sheet trước (xem README.md "Cảnh báo bắt buộc đọc trước khi cài").
 *
 * TUYỆT ĐỐI KHÔNG thêm/xoá/đổi tên cột nào trên Sheet — ensure_tabs()/
 * migrate_rows() phía Python map dữ liệu THEO TÊN CỘT, đổi tên cột từng
 * XOÁ RỖNG dữ liệu Gate 1 thật (xem docs/VPS_MIGRATION_BACKLOG.md "QUY TẮC
 * VÀNG KHI ĐỘNG VÀO SHEET"). Script này CHỈ ĐỌC cấu trúc cột (dò theo TÊN
 * header, KHÔNG hardcode chỉ số cột) và GHI GIÁ TRỊ vào ô Execute đã có
 * sẵn — không đụng cấu trúc.
 *
 * Tên cột lấy nguyên văn từ src/twmkt/sheets_board.py (đọc, không sửa):
 * CONTEXT_HEADER = ["Timestamp","Hot%","Score","Group","Topic","Context",
 *                   "Hook","Source","Duyệt Context","Execute","tickers",
 *                   "Notes","TopicKey"]
 * GATE1_COL = "Duyệt Context"; giá trị hợp lệ {"PENDING","APPROVE","REJECT"}.
 */

var CONTEXT_SHEET_NAME = "CONTEXT";
var GATE1_COL_NAME = "Duyệt Context";
var EXECUTE_COL_NAME = "Execute";
var TOPIC_KEY_COL_NAME = "TopicKey";
var GATE1_APPROVED_VALUE = "APPROVE";

function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu("Marketing Automation")
    .addItem("Thực Thi (dòng đang chọn)", "executeSelectedRow")
    .addToUi();
}

/**
 * Đọc header row -> map {tenCot: chiSoCot (1-based)}. Dò theo TÊN, KHÔNG
 * hardcode vị trí cột — đúng nguyên tắc an toàn của dự án (xem cảnh báo
 * đầu file): cấu trúc cột có thể đã đổi so với lúc viết script này, dò
 * theo tên tự phát hiện được việc đó thay vì âm thầm đọc nhầm cột.
 */
function _buildHeaderIndex(sheet) {
  var lastCol = sheet.getLastColumn();
  var headerRow = sheet.getRange(1, 1, 1, lastCol).getValues()[0];
  var index = {};
  for (var i = 0; i < headerRow.length; i++) {
    index[headerRow[i]] = i + 1; // Apps Script Range 1-based
  }
  return index;
}

function executeSelectedRow() {
  var ui = SpreadsheetApp.getUi();
  var sheet = SpreadsheetApp.getActiveSheet();

  if (sheet.getName() !== CONTEXT_SHEET_NAME) {
    ui.alert('Chức năng này chỉ chạy trên tab "' + CONTEXT_SHEET_NAME + '". Đang ở tab "' + sheet.getName() + '".');
    return;
  }

  var activeRow = sheet.getActiveRange().getRow();
  if (activeRow < 2) {
    ui.alert("Chọn 1 dòng dữ liệu (không phải dòng header) rồi thử lại.");
    return;
  }

  var headerIndex = _buildHeaderIndex(sheet);
  var requiredCols = [GATE1_COL_NAME, EXECUTE_COL_NAME, TOPIC_KEY_COL_NAME];
  for (var i = 0; i < requiredCols.length; i++) {
    if (!headerIndex[requiredCols[i]]) {
      ui.alert('Không tìm thấy cột "' + requiredCols[i] + '" trên tab CONTEXT -- cấu trúc Sheet có thể đã đổi, DỪNG (không đoán mù).');
      return;
    }
  }

  var gate1Value = sheet.getRange(activeRow, headerIndex[GATE1_COL_NAME]).getValue();
  if (String(gate1Value).toUpperCase() !== GATE1_APPROVED_VALUE) {
    ui.alert('Dòng này chưa duyệt ("' + GATE1_COL_NAME + '" = "' + gate1Value + '", cần "' + GATE1_APPROVED_VALUE + '") -- không gửi.');
    return;
  }

  // TopicKey là cột máy-sở-hữu, thường đang ẨN trên giao diện -- vẫn đọc
  // được bình thường qua getValue() (ẩn chỉ là thuộc tính hiển thị UI,
  // không chặn truy cập API/script). CHỈ ĐỌC, không bao giờ ghi cột này.
  var topicKey = sheet.getRange(activeRow, headerIndex[TOPIC_KEY_COL_NAME]).getValue();
  if (!topicKey) {
    ui.alert("Dòng này chưa có TopicKey (cột máy-sở-hữu) -- không gửi. Có thể cần chạy scripts/backfill_topic_keys.py trước.");
    return;
  }

  var props = PropertiesService.getScriptProperties();
  var endpointUrl = props.getProperty("WEBHOOK_URL");
  var token = props.getProperty("WEBHOOK_TOKEN");
  if (!endpointUrl || !token) {
    ui.alert("Thiếu cấu hình -- vào Extensions > Apps Script > Project Settings > Script Properties, đặt WEBHOOK_URL và WEBHOOK_TOKEN trước khi dùng (xem README.md).");
    return;
  }

  var response;
  try {
    response = UrlFetchApp.fetch(endpointUrl, {
      method: "post",
      contentType: "application/json",
      payload: JSON.stringify({ topic_key: topicKey, token: token }),
      muteHttpExceptions: true, // tự đọc status code, không để UrlFetchApp throw
    });
  } catch (err) {
    // Lỗi mạng/timeout thật (DNS, connection refused, quá thời gian Apps
    // Script cho phép...) -- KHÔNG tự retry (retry mù là nguồn double-fire,
    // xem cảnh báo đầu file), chỉ báo rõ cho người dùng tự quyết.
    ui.alert("Lỗi mạng khi gọi webhook: " + err.message + " -- KHÔNG tự động thử lại, vui lòng kiểm tra thủ công.");
    return;
  }

  var statusCode = response.getResponseCode();
  var execCell = sheet.getRange(activeRow, headerIndex[EXECUTE_COL_NAME]);

  if (statusCode === 202) {
    execCell.setValue("RUN");
    ui.alert("Đã gửi, đang xử lý (topic_key: " + topicKey + ").");
  } else if (statusCode === 409) {
    // 409 nghĩa là ĐÃ đang RUN rồi (dù do webhook tự biết hay do Execute
    // trên Sheet đã là RUN từ trước) -- ghi "RUN" ở đây là idempotent,
    // không tạo trạng thái mới, chỉ xác nhận lại đúng trạng thái hiện tại.
    execCell.setValue("RUN");
    ui.alert("Dòng này đang được xử lý rồi -- không gửi lại.");
  } else if (statusCode === 401) {
    // Lỗi cấu hình (token sai), KHÔNG phải lỗi của dòng này -- không ghi
    // gì vào Execute, tránh đánh dấu nhầm 1 dòng vô tội vì lỗi hệ thống.
    ui.alert("Token sai -- kiểm tra lại Script Properties WEBHOOK_TOKEN. KHÔNG ghi gì vào Execute.");
  } else {
    ui.alert("Webhook trả mã lỗi không mong đợi: " + statusCode + " -- " + response.getContentText() + ". KHÔNG ghi gì vào Execute, kiểm tra thủ công.");
  }
}
