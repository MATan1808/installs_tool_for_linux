# Linux App Installer Manager (GUI & CLI)

Công cụ quản lý cài đặt, gỡ cài đặt và tự động tạo shortcut ra màn hình Desktop cho các ứng dụng trên hệ điều hành Linux (đặc biệt tối ưu hóa cho Linux Mint Cinnamon).

## 🌟 Tính năng chính

- **Tự động nhận diện định dạng file**: Hỗ trợ `.deb`, `.AppImage`, `.tar.gz`, `.tar.xz`, `.zip`, `.sh`, `.run`.
- **Giao diện kéo thả đồ họa (GUI) trực quan**: Chỉ cần kéo file từ File Manager và thả vào giao diện ứng dụng để tiến hành cài đặt.
- **Duyệt file đồ họa**: Tích hợp File Picker để tìm và chọn file cài đặt nhanh chóng.
- **Tự động tạo Shortcut Desktop**: Tự động giải nén, trích xuất icon gốc chất lượng cao và tạo file `.desktop` trên Màn hình nền & Menu hệ thống, cấp quyền tin cậy (`trusted`) giúp ứng dụng chạy ngay không bị cảnh báo bảo mật.
- **Quản lý & Gỡ cài đặt trực quan**: Bảng danh sách hiển thị các ứng dụng đã cài đặt và hỗ trợ nút **[Gỡ bỏ]** để dọn dẹp sạch sẽ shortcut cùng thư mục cài đặt liên quan.
- **Mật khẩu đồ họa an toàn (pkexec)**: Tích hợp PolicyKit (`pkexec`) để hiển thị hộp thoại nhập mật khẩu quản trị trực quan khi cài đặt/gỡ bỏ gói `.deb`.

---

## 🛠️ Hướng dẫn cài đặt và sử dụng

### 1. Cài đặt thư viện giao diện đồ họa (PyQt5)
Mở terminal và chạy lệnh cài đặt thư viện PyQt5 (chỉ cần chạy một lần duy nhất):
```bash
sudo apt install -y python3-pyqt5
```

### 2. Sử dụng phiên bản Giao diện đồ họa (GUI)
Khởi chạy giao diện bằng lệnh:
```bash
python3 installer_gui.py
```
Hoặc anh có thể tạo shortcut launcher ra màn hình Desktop để click đúp chạy bất cứ lúc nào.

### 3. Sử dụng phiên bản Terminal (CLI)
Công cụ vẫn hỗ trợ đầy đủ các lệnh CLI trực tiếp:
- **Mở Menu tương tác**: 
  ```bash
  python3 installer.py
  ```
- **Cài đặt nhanh file**: 
  ```bash
  python3 installer.py install /đường/dẫn/đến/file_cài_đặt
  ```
- **Gỡ cài đặt nhanh**: 
  ```bash
  python3 installer.py uninstall id_ứng_dụng
  ```
- **Xem danh sách ứng dụng đã cài**: 
  ```bash
  python3 installer.py list
  ```

---

## 📂 Cấu trúc lưu trữ cục bộ

- Thư mục lưu trữ ứng dụng cài đặt (`AppImage`, giải nén...): `apps/`
- Registry lưu thông tin ứng dụng: `registry.json`
