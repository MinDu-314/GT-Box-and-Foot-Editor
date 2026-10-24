# 🏀 HƯỚNG DẪN SỬ DỤNG BỘ CÔNG CỤ TINH CHỈNH GROUND-TRUTH (`IMG_0114` & `IMG_0115`)

Bộ công cụ này đã được **đóng gói độc lập 100%** (kèm sẵn video gốc, dữ liệu hộp giới hạn và quỹ đạo khởi tạo siêu mượt từ `Solver v4` — đã khử hoàn toàn hiện tượng nhảy box và chuẩn hóa đúng danh sách cầu thủ, cùng ma trận Homography chuẩn 4 điểm của Ban Tổ Chức). Bạn có thể chạy trực tiếp trên bất kỳ máy tính nào mà không cần cấu hình đường dẫn.

---

## 1. Cấu Trúc Thư Mục Đóng Gói

```text
ABC2027_GT_Editor_Package_v4/
├── START_GT_EDITOR.bat                # [NHẤP ĐÚP ĐỂ CHẠY TRÊN WINDOWS]
├── start_gt_editor.sh                 # Script chạy trên macOS / Linux
├── gt_editor_standalone.py            # Mã nguồn công cụ Web tương tác (Solver v4)
├── requirements.txt                   # Thư viện tự động cài (opencv-python, numpy, pandas)
├── HUONG_DAN_SU_DUNG.md               # File hướng dẫn này
├── videos_source/                     # Video 720p gốc để công cụ đọc frame
│   ├── IMG_0114.MP4
│   └── IMG_0115.MP4
├── videos_v4_preview/                 # Video 720p H.264 đã vẽ sẵn Box + Minimap của Solver v4 để xem đối chiếu
│   ├── IMG_0114_v4.mp4
│   └── IMG_0115_v4.mp4
└── output_ground_truth/               # [THƯ MỤC CHỨA FILE CHUẨN GỬI LẠI SAU KHI LÀM XONG]
    ├── IMG_0114.txt                   # File chuẩn 5 cột BTC (frame, court_x, court_y, team, jersey)
    ├── IMG_0115.txt                   # File chuẩn 5 cột BTC (frame, court_x, court_y, team, jersey)
    ├── IMG_0114_gt_boxes.csv.gz       # File lưu trạng thái Box 720p (x1, y1, x2, y2) để mở lại sửa tiếp
    └── IMG_0115_gt_boxes.csv.gz       # File lưu trạng thái Box 720p (x1, y1, x2, y2) để mở lại sửa tiếp
```

---

## 2. Cách Khởi Chạy (Chỉ 1 Cú Nhấp Chuột)

1. Giải nén thư mục `ABC2027_GT_Editor_Package_v4` ra máy tính.
2. Nhấp đúp vào file **`START_GT_EDITOR.bat`** (trên Windows) hoặc chạy `./start_gt_editor.sh` (trên Mac/Linux).
   - Script sẽ tự động tìm Python trên máy, tự động cài đặt `opencv-python`, `numpy`, `pandas` nếu chưa có, tự động chọn cổng trống (mặc định `http://127.0.0.1:8899`) và mở thẳng giao diện trên trình duyệt.

---

## 3. Cách Tinh Chỉnh Box & Tự Động Tính Điểm Chân

- **Quy tắc tự động:** Bạn **chỉ cần chỉnh lại hộp `Bounding Box`**, công cụ sẽ **tự động** lấy trung điểm cạnh đáy:
  $$u_{\text{foot}} = \frac{x_1 + x_2}{2}, \quad v_{\text{foot}} = y_2$$
  và tự động chiếu qua ma trận Homography chuẩn 4 điểm của BTC sang tọa độ sân `(court_x, court_y)` (hiển thị tức thời trên Minimap 2D góc trên bên trái).
- **2 Màu đồng nhất theo đội:**
  - **Đội A (`A#6, A#9, A#10` ở `0114` / `A#4, A#10, A#12` ở `0115`):** Màu **Vàng (`#ffd700`)** trên cả Box, chấm đáy hộp và chấm trên Minimap 2D.
  - **Đội B (`B#6, B#9, B#11` ở `0114` / `B#1, B#3, B#5` ở `0115`):** Màu **Xanh Cyan (`#00c3ff`)** trên cả Box, chấm đáy hộp và chấm trên Minimap 2D.

### Bảng Phím Tắt Nhanh:
| Phím / Thao tác | Tác dụng |
|---|---|
| **`1` .. `6`** | Chọn nhanh cầu thủ thứ `1..6` |
| **Kéo chuột trong lòng Box** | Di chuyển toàn bộ Box của cầu thủ đang chọn |
| **Kéo 8 chốt vuông quanh Box** | Kéo giãn cạnh đáy `y2` (chân), đỉnh đầu `y1`, hoặc bề ngang `x1, x2` |
| **`W` + Quét chuột** | Vẽ lại Box mới hoàn toàn cho cầu thủ đang chọn |
| **`N` / `P`** | Nhảy tới / lùi về **Đoạn Khuất / Nội Suy tiếp theo** (không cần tua tay từng frame!) |
| **`Space`** | Phát / Tạm dừng video |
| **`A` / `D`** hoặc **`←` / `→`** | Lùi / Tiến `1` frame |
| **`Q` / `E`** | Lùi / Tiến `10` frame |
| **`C`** | Copy Box của cầu thủ đang chọn từ frame liền trước (`f - 1 -> f`) và tiến `+1` frame |
| **`I` $\to$ `O` $\to$ `K`** | Đặt frame đầu (`I`) $\to$ Tua tới frame cuối, nhấn (`O`) $\to$ Nhấn (`K`) để **nội suy mượt toàn bộ đoạn `[f_đầu .. f_cuối]`** |
| **Nút `Swap ID`** | Đổi chéo nhãn 2 cầu thủ bị tráo trong đoạn `[f_đầu .. f_cuối]` |
| **`Ctrl + S`** hoặc nút **`💾 Lưu GT`** | Lưu toàn bộ kết quả vào thư mục `output_ground_truth/` |
| **Nút `⬇️ Tải File Chuẩn (.txt)`** | Lưu và tải trực tiếp file `IMG_0114.txt` / `IMG_0115.txt` qua trình duyệt |

---

## 4. Sau Khi Làm Xong Cần Gửi Lại File Nào?

Sau khi nhấn **`Ctrl + S`** (hoặc **`💾 Lưu GT`**) cho cả `IMG_0114` và `IMG_0115`, bạn chỉ cần gửi lại **4 file** nằm trong thư mục **`output_ground_truth/`**:
1. `output_ground_truth/IMG_0114.txt` *(File Ground-Truth chuẩn 5 cột BTC)*
2. `output_ground_truth/IMG_0115.txt` *(File Ground-Truth chuẩn 5 cột BTC)*
3. `output_ground_truth/IMG_0114_gt_boxes.csv.gz` *(File lưu kèm Bounding Box 720p)*
4. `output_ground_truth/IMG_0115_gt_boxes.csv.gz` *(File lưu kèm Bounding Box 720p)*
