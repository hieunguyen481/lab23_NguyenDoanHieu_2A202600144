# Báo cáo Lab Ngày 08 - Điều phối Agent với LangGraph

## 1. Thành viên / Sinh viên

- Tên: Nguyen Doan Hieu
- Repo/commit: phase2-track3-day8-langgraph-agent-main
- Ngày: 11/05/2026

## 2. Kiến trúc (Architecture)

Đồ thị (Graph) được thiết kế theo mô hình StateGraph của LangGraph, bao gồm các thành phần chính sau:
- **Node Intake**: Điểm bắt đầu, thực hiện chuẩn hóa câu truy vấn của người dùng (xóa khoảng trắng thừa, đưa về dạng chuẩn).
- **Node Classify**: Sử dụng bộ quy tắc từ khóa có độ ưu tiên để phân loại yêu cầu:
    1. **Risky** (Rủi ro cao): refund, delete, send, cancel, remove, revoke.
    2. **Tool** (Sử dụng công cụ): status, order, lookup, check, track, find, search.
    3. **Missing Info** (Thiếu thông tin): Các câu lệnh ngắn (< 5 từ) và chứa đại từ mơ hồ như "it", "this", "that".
    4. **Error** (Lỗi hệ thống): timeout, fail, error, crash, unavailable.
    5. **Simple** (Mặc định): Các câu hỏi thông thường.
- **Vòng lặp Retry**: Được tạo bởi các node `tool -> evaluate -> retry -> tool`. Vòng lặp này bị giới hạn bởi tham số `max_attempts` để tránh lặp vô hạn.
- **Node Approval (HITL)**: Một điểm dừng bắt buộc cho các hành động rủi ro cao, yêu cầu sự phê duyệt trước khi thực thi công cụ.

## 3. Lược đồ trạng thái (State schema)

Trạng thái được quản lý tập trung và nhất quán thông qua `AgentState`.

| Trường | Kiểu Reducer | Mục đích |
|---|---|---|
| messages | Annotated[list, add] | Lưu vết toàn bộ tin nhắn/sự kiện để phục vụ audit. |
| events | Annotated[list, add] | Ghi lại chi tiết thực thi của từng node (latency, metadata). |
| tool_results | Annotated[list, add] | Lưu kết quả từ các lần gọi công cụ, hỗ trợ kiểm tra retry. |
| route | overwrite | Lưu tuyến đường hiện tại mà agent đang đi. |
| attempt | overwrite | Biến đếm số lần thử lại hiện tại. |
| risk_level | overwrite | Xác định mức độ rủi ro (low/high) để kích hoạt HITL. |

## 4. Kết quả kịch bản (Scenario results)

Dưới đây là dữ liệu trích xuất từ `outputs/metrics.json` sau khi chạy 7 kịch bản mẫu:

| Scenario ID | Tuyến mong đợi | Tuyến thực tế | Thành công | Số lần thử | Ngắt (HITL) |
|---|---|---|---:|---:|---:|
| S01_simple | simple | simple | Có | 0 | 0 |
| S02_tool | tool | tool | Có | 0 | 0 |
| S03_missing | missing_info | missing_info | Có | 0 | 0 |
| S04_risky | risky | risky | Có | 0 | 1 |
| S05_error | error | error | Có | 2 | 0 |
| S06_delete | risky | risky | Có | 0 | 1 |
| S07_dead_letter | error | error | Có | 1 | 0 |

**Tổng kết:**
- Tổng số kịch bản: 7
- Tỉ lệ thành công: **100%**
- Số lần thử lại tổng cộng: 3
- Số lần ngắt để phê duyệt (Interrupts): 2

## 5. Phân tích lỗi (Failure analysis)

1. **Xử lý lỗi tạm thời (Transient Failure)**: Trong kịch bản S05, công cụ giả lập trả về lỗi trong 2 lần thử đầu tiên. Node `evaluate` phát hiện từ khóa "ERROR" và điều hướng sang node `retry`. Tại đây, biến `attempt` được tăng lên và quay lại node `tool`. Ở lần thử thứ 3, công cụ trả về thành công.
2. **Ngăn chặn hành động rủi ro**: Trong kịch bản S04 và S06, hệ thống nhận diện từ khóa rủi ro và chuyển hướng qua `risky_action` -> `approval`. Nếu không có sự phê duyệt (approved=True), agent sẽ chuyển sang node `clarify` thay vì thực thi lệnh rủi ro, đảm bảo an toàn hệ thống.

## 6. Minh chứng về Lưu trữ / Phục hồi (Persistence / recovery)

Dự án đã triển khai **SQLite Persistence** bằng cách sử dụng `SqliteSaver`.
- Dữ liệu trạng thái được lưu trữ trong file `checkpoints.db`.
- Mỗi lần chạy được định danh bằng một `thread_id` duy nhất.
- Hệ thống hỗ trợ phục hồi (resume) từ điểm ngắt cuối cùng (ví dụ: sau khi chờ người dùng phê duyệt ở node `approval`).

## 7. Công việc mở rộng (Extension work)

- **Xuất sơ đồ Graph**: Đã thêm chức năng xuất sơ đồ Mermaid. Bạn có thể xem hình ảnh minh họa luồng tại `outputs/graph_diagram.md`. Sơ đồ hiển thị rõ ràng các cạnh điều hướng có điều kiện.
- **Xử lý đa kịch bản tự động**: CLI được tối ưu để chạy hàng loạt các kịch bản từ file `.jsonl` và tổng hợp metrics tự động.

## 8. Kế hoạch cải thiện (Improvement plan)

Nếu có thêm thời gian, tôi sẽ thực hiện các cải tiến sau:
1. **LLM Classifier**: Thay thế keyword-matching bằng một prompt LLM để phân loại ý định người dùng chính xác hơn, tránh bị đánh lừa bởi ngữ cảnh phức tạp.
2. **Giao diện Streamlit**: Xây dựng UI cho bước phê duyệt (HITL) thay vì dùng mock approval, cho phép người quản trị xem chi tiết hành động trước khi nhấn "Đồng ý".
3. **Exponential Backoff**: Áp dụng thời gian chờ tăng dần giữa các lần retry để giảm tải cho hệ thống backend khi có sự cố.
