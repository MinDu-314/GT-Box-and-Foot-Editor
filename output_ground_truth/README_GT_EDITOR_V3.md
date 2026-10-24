# 🏀 Hướng Dẫn Sử Dụng Công Cụ Tạo & Tinh Chỉnh Ground-Truth (`GT Box & Trajectory Editor v3`)

Công cụ này được khởi tạo trực tiếp từ **kết quả dự đoán của `Solver v3` (`93.30% TI-HOTA`)** kết hợp **ma trận Homography chuẩn 4 điểm của Ban Tổ Chức (`RKU0, RKU1, RKU10, RKU11`)** trên toàn bộ `11,823` frame của `IMG_0114` và `11,906` frame của `IMG_0115`.

---

## 1. Cách Khởi Động Nhanh (1-Click)
- **Cách 1 (Khuyên dùng):** Nhấp đúp chuột vào file [`run_gt_editor.bat`](file:///d:/QBao%20projects/ABC2027/run_gt_editor.bat) ở thư mục gốc `d:\QBao projects\ABC2027\run_gt_editor.bat`.
- **Cách 2 (Dòng lệnh PowerShell / CMD):**
  ```powershell
  & "C:\Users\Mac Duong\miniconda3\envs\hokkaido_env\python.exe" "d:\QBao projects\ABC2027\tools\gt_editor_v3.py" --port 8765
  ```
- Trình duyệt sẽ tự động mở giao diện tại địa chỉ: **`http://127.0.0.1:8765`**

---

## 2. Cơ Chế Hoạt Động Tự Động
1. **Tự động lấy Trung điểm Đáy Hộp (`Bottom Midpoint`):**
   - Bạn chỉ cần **kéo / chỉnh lại hộp giới hạn `Bounding Box (x1, y1, x2, y2)`** của cầu thủ trên màn hình.
   - Công cụ sẽ **tự động** lấy điểm chính giữa cạnh đáy:
     $$u_{\text{foot}} = \frac{x_1 + x_2}{2}, \quad v_{\text{foot}} = y_2$$
   - Và chiếu tức thời qua ma trận Homography chuẩn 4 điểm của BTC $\mathcal{H}_{\text{img}\to\text{court}}$ sang tọa độ mặt sân `(court_x, court_y)` (đơn vị `cm`), đồng thời cập nhật ngay chấm tròn trên **Minimap 2D ở góc trên bên trái**.
2. **Tự động Đánh dấu các Đoạn Khuất / Nội suy (`225` điểm ở `IMG_0114`, `219` điểm ở `IMG_0115`):**
   - Thay vì phải xem thủ công toàn bộ 11,823 frame, bạn chỉ cần nhấn phím **`N`** (*Next Flagged Episode*) hoặc **`P`** (*Prev Flagged Episode*) để nhảy thẳng tới các đoạn cầu thủ bị khuất hoặc giao cắt phức tạp.

---

## 3. Bảng Phím Tắt & Thao Tác Nhanh

| Phím tắt / Thao tác | Chức năng |
|---|---|
| **`Space`** | Phát / Tạm dừng video (`Play / Pause`) |
| **`A` / `D`** hoặc **`←` / `→`** | Lùi / Tiến `1` frame |
| **`Q` / `E`** | Lùi / Tiến `10` frame |
| **`N` / `P`** | Nhảy tới / lùi về **Đoạn Khuất / Nội Suy tiếp theo** (*Next / Prev Flagged Frame*) |
| **`1` .. `6`** | Chọn nhanh cầu thủ thứ `1..6` trong danh sách Roster |
| **Kéo bên trong Box** | Di chuyển toàn bộ Bounding Box `(x1, y1, x2, y2)` của cầu thủ đang chọn |
| **Kéo 8 chốt vuông quanh Box** | Thay đổi kích thước cạnh/góc của Bounding Box (chiều cao chân `y2`, đỉnh đầu `y1`, bề ngang `x1, x2`) |
| **`W` + Kéo chuột** | Vẽ lại mới hoàn toàn Bounding Box cho cầu thủ đang chọn |
| **`C`** | Sao chép Bounding Box của cầu thủ đang chọn từ frame liền trước (`f - 1 -> f`) |
| **`I`**, **`O`**, **`K`** | Đặt frame đầu (`I`), đặt frame cuối (`O`), và **Nội suy tuyến tính mượt** Bounding Box của cầu thủ đang chọn trong toàn bộ đoạn `[f_start .. f_end]` (`K`) |
| **Nút `Swap ID [f1..f2]`** | Đổi chéo toàn bộ hộp & quỹ đạo của 2 cầu thủ trong đoạn frame `[f1 .. f2]` |
| **`Ctrl + S`** hoặc nút **`💾 Save GT`** | Lưu toàn bộ dữ liệu đã chỉnh sửa ra file Ground-Truth chuẩn BTC (`work/gt_challenge/IMG_0114.txt`, `IMG_0115.txt`) và cập nhật luôn file nộp bài (`work/final_submission/IMG_0114.txt`, `IMG_0115.txt`) |

---

## 4. Vị Trí Các File Đầu Ra
- `d:\QBao projects\ABC2027\work\gt_challenge\IMG_0114.txt` & `IMG_0115.txt`: File Ground-Truth chuẩn 5 cột của BTC (`frame_id, court_x, court_y, team_id, jersey_number`).
- `d:\QBao projects\ABC2027\work\gt_challenge\IMG_0114_gt_boxes.csv.gz` & `IMG_0115_gt_boxes.csv.gz`: File lưu đầy đủ cả Bounding Box 720p `(x1, y1, x2, y2)` lẫn `(court_x, court_y)` để bạn có thể mở lại chỉnh sửa tiếp bất cứ lúc nào.
