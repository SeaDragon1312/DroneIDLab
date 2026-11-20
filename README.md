# DroneID offline

Ứng dụng Windows đọc file IQ, phát hiện ứng viên DroneID, giải điều chế và kiểm CRC. Có bảng kết quả, phổ, chòm sao, đồ thị vị trí và xuất CSV/JSON. Chỉ xử lý file offline, không có chức năng phát sóng.

## Cài trên máy chưa có môi trường

1. Cài **Python 3.13 x64**, có thành phần Tcl/Tk; chọn **Add Python to PATH** trong bộ cài: https://www.python.org/downloads/windows/.
2. Cài **Node.js 26.x** từ https://nodejs.org/en/download. Node cần cho backend WebAssembly, không được kèm trong repository.
3. Mở PowerShell mới tại thư mục có `launch.py`.


```powershell
python --version
node --version
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe tools\check_runtime.py
.\.venv\Scripts\python.exe tools\fetch_samples.py
.\.venv\Scripts\python.exe launch.py
```

## Chạy thử và xuất kết quả

Bấm **Chọn IQ** → mở `samples/mini2_sm` hoặc `samples/mavic_air_2`. Chọn `float32`, `little`, `IQ`, Fs **50000000 Hz** (50 triệu mẫu phức/giây), mode **turbo**. **Fc để trống** vì chưa xác minh tần số trung tâm. Bấm **Chạy**, chọn một hàng để xem hình. Có thể hủy giữa các khối xử lý.

Đã chạy lại bản thu gọn trong venv mới, thư mục có dấu cách: mini2_sm có 10 ứng viên, 10 đạt CRC24 và CRC16; mavic_air_2 có 3 ứng viên, 1 đạt cả hai CRC và 2 lỗi parse. Kết quả khớp trước khi đóng gói, không được hardcode vào detector/decoder. Đã kiểm cửa sổ GUI thật, xuất rồi đọc lại CSV/JSON và lỗi thiếu backend. Đây là cài lại trên cùng máy, chưa phải kiểm trên Windows sạch khác.

Mặc định che seri/vị trí. Tắt ô che để xem dữ liệu trên máy mình; bật lại trước khi chia sẻ. Bấm **Xuất JSON/CSV** và chọn định dạng. Khi xuất CSV, gửi kèm file `.metadata.json` vì file này chứa cấu hình và đơn vị. Khung không qua đủ CRC không được hiển thị như mục tiêu hợp lệ.

Nếu thiếu Node, cài Node 26.x rồi mở lại terminal/app. Nếu thiếu backend, khôi phục đủ `droneid_lab/native/turbo_worker.cjs` và `droneid_turbo.wasm`. App báo lỗi; không tự đổi sang systematic-only. Mode `baseline` chỉ dùng để đối chiếu, không có sửa lỗi bằng parity/CRC24.
