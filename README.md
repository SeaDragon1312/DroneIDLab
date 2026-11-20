# DroneID offline

Ứng dụng Windows đọc file IQ, phát hiện ứng viên DroneID, giải điều chế và kiểm CRC. Có bảng kết quả, phổ, chòm sao, đồ thị vị trí và xuất CSV/JSON. Chỉ xử lý file offline, không có chức năng phát sóng.

## Cài trên máy chưa có môi trường

1. Cài **Python 3.13 x64**, có thành phần Tcl/Tk; chọn **Add Python to PATH** trong bộ cài: https://www.python.org/downloads/windows/.
2. Cài **Node.js 26.x** từ https://nodejs.org/en/download. Node cần cho backend WebAssembly, không được kèm trong repository.
3. Tải ZIP nguồn trên GitHub rồi giải nén, hoặc clone nếu đã cài Git. Mở PowerShell mới tại thư mục có `launch.py`.

Đã kiểm Windows 11, Python **3.13.13 conda-forge**, Tk 8.6, Node **26.13.1**. Chưa kiểm trên một máy Windows sạch khác hoặc bộ Python từ python.org; các bước cài ban đầu ở trên là yêu cầu môi trường, không phải tuyên bố đã thử mọi bộ cài. Không cần MATLAB/compiler C++ để chạy backend đã kèm.

```powershell
python --version
node --version
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe tools\check_runtime.py
.\.venv\Scripts\python.exe tools\fetch_samples.py
.\.venv\Scripts\python.exe launch.py
```

Không cần kích hoạt venv hay đổi Execution Policy. Cài thư viện cần Internet. Hai mẫu **đã nằm trong repository**: `samples/mini2_sm` và `samples/mavic_air_2` (tổng khoảng 7,6 MB). Script `fetch_samples.py` kiểm SHA-256 của file đang có; chỉ tải từ commit cố định nếu thiếu mẫu. Sau khi cài, giải mã và đồ thị chạy offline.

## Chạy thử và xuất kết quả

Bấm **Chọn IQ** → mở `samples/mini2_sm` hoặc `samples/mavic_air_2`. Chọn `float32`, `little`, `IQ`, Fs **50000000 Hz** (50 triệu mẫu phức/giây), mode **turbo**. **Fc để trống** vì chưa xác minh tần số trung tâm. Bấm **Chạy**, chọn một hàng để xem hình. Có thể hủy giữa các khối xử lý.

Đã chạy lại bản thu gọn trong venv mới, thư mục có dấu cách: mini2_sm có 10 ứng viên, 10 đạt CRC24 và CRC16; mavic_air_2 có 3 ứng viên, 1 đạt cả hai CRC và 2 lỗi parse. Kết quả khớp trước khi đóng gói, không được hardcode vào detector/decoder. Đã kiểm cửa sổ GUI thật, xuất rồi đọc lại CSV/JSON và lỗi thiếu backend. Đây là cài lại trên cùng máy, chưa phải kiểm trên Windows sạch khác.

Mặc định che seri/vị trí. Tắt ô che để xem dữ liệu trên máy mình; bật lại trước khi chia sẻ. Bấm **Xuất JSON/CSV** và chọn định dạng. Khi xuất CSV, gửi kèm file `.metadata.json` vì file này chứa cấu hình và đơn vị. Khung không qua đủ CRC không được hiển thị như mục tiêu hợp lệ.

Nếu thiếu Node, cài Node 26.x rồi mở lại terminal/app. Nếu thiếu backend, khôi phục đủ `droneid_lab/native/turbo_worker.cjs` và `droneid_turbo.wasm`. App báo lỗi; không tự đổi sang systematic-only. Mode `baseline` chỉ dùng để đối chiếu, không có sửa lỗi bằng parity/CRC24.

## Giới hạn sử dụng

- QPSK nhận `raw_fft`, nhánh equalized chỉ phục vụ quan sát; không bảo đảm giải được mọi model DJI/OcuSync.
- Vị trí là đồ thị kinh/vĩ độ offline, **không có bản đồ nền**. CRC kiểm tính toàn vẹn, không xác thực danh tính/vị trí. Bộ lọc hiện bỏ tọa độ có một thành phần bằng 0.
- App và home là trường riêng, chưa chứng minh app luôn là pilot. Vận tốc/góc ghi raw nếu đơn vị chưa xác minh; không đổi `d_1_angle` thành yaw độ. Mốc altitude/height chưa xác minh độc lập.
- Mẫu đã cắt/nối ứng viên; không suy chu kỳ phát ngoài thực tế. Chunk mặc định 0,5 s có thể cắt ngang burst; chỉ giữ dữ liệu vẽ cho 100 ứng viên đầu. File dài chưa được bảo đảm mọi ranh giới.
- Int16 được chia 32768; đã kiểm file dẫn xuất từ mẫu float32, chưa kiểm capture int16 thực địa. Cấu hình đã kiểm là 50 MS/s, 9 symbol. Legacy 8 symbol không bật.
- Đây là bản source cần Python/Node cài riêng, không phải EXE độc lập. Không yêu cầu tắt Application Control.

## Nguồn và giấy phép

Ứng dụng/phần kết hợp dùng AGPL-3.0 (`LICENSE`). Detector/đồng bộ/QPSK/parser kế thừa [DroneSecurity](https://github.com/RUB-SysSec/DroneSecurity/tree/9ff819843bee48fb140a0704ec78aff757896dea), commit `9ff819843bee48fb140a0704ec78aff757896dea`, AGPL-3.0; hai mẫu cũng từ repo này. Logic/tham số Turbo tái sử dụng [proto17/dji_droneid](https://github.com/proto17/dji_droneid/tree/7c6dddad563724df93132e91b89e74650182ea1e), MIT; TurboFEC commit `6de1f4604933d6c21a0ff0c75401cffa7debf3cd`, GPL-3.0-or-later; CRCpp commit `62d4791877a636fa4b51acc9181c65ac89364372`, BSD-3-Clause. Không nhận toàn bộ thuật toán là tự viết. Phần bổ sung gồm pipeline chung, cầu nối WASM, kiểm CRC24, GUI worker, kiểm đầu vào và xuất dữ liệu.

Thông báo bản quyền, license LLVM/WASI và các thành phần liên kết được giữ trong `licenses/`; source tương ứng của backend ở `native_turbo/`. Giữ toàn bộ giấy phép khi phân phối. Node/Python và dependency Python cài riêng, có giấy phép đi kèm bản cài.

Dành cho người bảo trì: các file build/source trong `native_turbo` được giữ để có thể xây lại backend và phân phối source tương ứng. App dùng WASM đã kèm; không cần chạy các lệnh build. Khi cần nghiên cứu build, dùng bản sao riêng: `.\.venv\Scripts\python.exe tools\setup_turbo_portable.py`, sau đó `node tools\build_turbo_portable.mjs`. Lệnh này tải toolchain ghim trong lockfile và thay WASM ở bản sao; không nằm trong phép thử cài runtime của bản thu gọn.
