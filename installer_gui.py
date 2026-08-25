#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import json
import shutil
import subprocess
import tempfile
import tarfile
import zipfile
import re
import math
from pathlib import Path

# Cấu hình đường dẫn
BASE_DIR = Path("/media/tanma/DATA/tool_installs")
APPS_DIR = BASE_DIR / "apps"
REGISTRY_PATH = BASE_DIR / "registry.json"
DESKTOP_DIR = Path("/home/tanma/Desktop")
USER_APPLICATIONS_DIR = Path("/home/tanma/.local/share/applications")

# Tạo các thư mục nếu chưa tồn tại
APPS_DIR.mkdir(parents=True, exist_ok=True)
DESKTOP_DIR.mkdir(parents=True, exist_ok=True)
USER_APPLICATIONS_DIR.mkdir(parents=True, exist_ok=True)

# Kiểm tra thư viện PyQt5, nếu thiếu dùng zenity để thông báo trực quan
try:
    from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                                 QHBoxLayout, QLabel, QPushButton, QTableWidget, 
                                 QTableWidgetItem, QHeaderView, QTextEdit, QFileDialog, 
                                 QMessageBox, QFrame)
    from PyQt5.QtCore import Qt, QThread, pyqtSignal
    from PyQt5.QtGui import QDragEnterEvent, QDropEvent, QFont
except ImportError:
    error_msg = ("Ứng dụng Linux App Installer yêu cầu thư viện PyQt5.\\n\\n"
                 "Anh Tân vui lòng mở terminal và chạy lệnh sau để cài đặt:\\n"
                 "sudo apt install -y python3-pyqt5")
    subprocess.run(["zenity", "--error", "--title=Thiếu thư viện PyQt5", f"--text={error_msg}", "--width=400"], check=False)
    sys.exit(1)

# --- QUẢN LÝ REGISTRY ---
def load_registry():
    if not REGISTRY_PATH.exists():
        return {}
    try:
        with open(REGISTRY_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_registry(registry):
    try:
        with open(REGISTRY_PATH, "w", encoding="utf-8") as f:
            json.dump(registry, f, indent=4, ensure_ascii=False)
    except Exception:
        pass

# --- UTILS ĐO DUNG LƯỢNG (STORAGE TRACKER) ---
def get_dir_size(path):
    """Tính tổng dung lượng thư mục hoặc file (bytes)"""
    total_size = 0
    try:
        path = Path(path)
        if path.is_file():
            return path.stat().st_size
        for dirpath, dirnames, filenames in os.walk(path):
            for f in filenames:
                fp = os.path.join(dirpath, f)
                if not os.path.islink(fp):
                    total_size += os.path.getsize(fp)
    except Exception:
        pass
    return total_size

def get_deb_installed_size(pkg_name):
    """Truy vấn dung lượng đã cài đặt của gói deb qua dpkg (bytes)"""
    try:
        result = subprocess.run(
            ["dpkg-query", "-W", "-f=${Installed-Size}\\n", pkg_name],
            capture_output=True, text=True, check=True
        )
        size_kb = int(result.stdout.strip())
        return size_kb * 1024
    except Exception:
        return 0

def format_size(size_bytes):
    """Format dung lượng sang dạng trực quan (KB, MB, GB)"""
    if size_bytes <= 0:
        return "N/A"
    size_name = ("B", "KB", "MB", "GB", "TB")
    i = int(math.floor(math.log(size_bytes, 1024)))
    p = math.pow(1024, i)
    s = round(size_bytes / p, 2)
    return f"{s} {size_name[i]}"

def get_app_display_size(app_id, info):
    """Lấy dung lượng hiển thị của app dựa theo loại"""
    app_type = info.get("type", "")
    if app_type == "deb":
        size = get_deb_installed_size(info.get("deb_package_name", app_id))
        return format_size(size) if size > 0 else "Hệ thống"
    elif app_type in ["appimage", "archive"]:
        size = get_dir_size(info.get("install_path", ""))
        return format_size(size)
    elif app_type == "flatpak":
        # Đo thư mục flatpak user hoặc system
        app_id_real = info.get("flatpak_app_id", app_id)
        user_path = Path(f"/home/tanma/.local/share/flatpak/app/{app_id_real}")
        sys_path = Path(f"/var/lib/flatpak/app/{app_id_real}")
        size = 0
        if user_path.exists():
            size = get_dir_size(user_path)
        elif sys_path.exists():
            size = get_dir_size(sys_path)
        return format_size(size) if size > 0 else "Hệ thống Flatpak"
    elif app_type == "snap":
        app_name_real = info.get("snap_name", app_id)
        # Snap mount loop-device nên đo file snap thực tế trong thư mục snapd
        snap_file_dir = Path("/var/lib/snapd/snaps")
        size = 0
        if snap_file_dir.exists():
            for f in snap_file_dir.glob(f"{app_name_real}_*.snap"):
                size += f.stat().st_size
        return format_size(size) if size > 0 else "Hệ thống Snap"
    return "Không rõ"

# --- UTILS SHORTCUT (.DESKTOP) ---
def make_desktop_file_trusted(desktop_path):
    try:
        os.chmod(desktop_path, 0o755)
        subprocess.run(["gio", "set", str(desktop_path), "metadata::trusted", "true"], check=False)
    except Exception:
        pass

def create_desktop_shortcuts(app_id, name, exec_path, icon_path, categories="Utility;"):
    desktop_content = f"""[Desktop Entry]
Version=1.0
Type=Application
Name={name}
Exec={exec_path}
Icon={icon_path}
Terminal=false
Categories={categories}
Comment=Cài đặt thông qua Linux App Installer Manager
"""
    desktop_shortcut = DESKTOP_DIR / f"{app_id}.desktop"
    menu_shortcut = USER_APPLICATIONS_DIR / f"{app_id}.desktop"
    
    try:
        with open(desktop_shortcut, "w", encoding="utf-8") as f:
            f.write(desktop_content)
        make_desktop_file_trusted(desktop_shortcut)
        
        with open(menu_shortcut, "w", encoding="utf-8") as f:
            f.write(desktop_content)
        os.chmod(menu_shortcut, 0o755)
        return [str(desktop_shortcut), str(menu_shortcut)]
    except Exception:
        return []

def get_clean_name(filepath):
    name = Path(filepath).stem
    # Tẩy phiên bản và hậu tố hệ thống
    name = re.sub(r'[-_]v?\d+\.\d+.*$', '', name, flags=re.IGNORECASE)
    name = re.sub(r'[-_]amd64$', '', name, flags=re.IGNORECASE)
    name = re.sub(r'[-_]x86_64$', '', name, flags=re.IGNORECASE)
    name = re.sub(r'[-_]linux$', '', name, flags=re.IGNORECASE)
    return name

# --- THREAD CÀI ĐẶT DƯỚI NỀN (QTHREAD) ---
class InstallWorker(QThread):
    progress_signal = pyqtSignal(str)
    finished_signal = pyqtSignal(bool, str)

    def __init__(self, filepath, is_upgrade=False):
        super().__init__()
        self.filepath = Path(filepath).resolve()
        self.is_upgrade = is_upgrade

    def run(self):
        filename = self.filepath.name.lower()
        try:
            if filename.endswith(".deb"):
                self.install_deb()
            elif filename.endswith(".appimage"):
                self.install_appimage()
            elif filename.endswith((".tar.gz", ".tar.xz", ".tgz", ".zip")):
                self.install_archive()
            elif filename.endswith((".sh", ".run")):
                self.install_script()
            elif filename.endswith((".flatpak", ".flatpakref")):
                self.install_flatpak()
            elif filename.endswith(".snap"):
                self.install_snap()
            else:
                self.finished_signal.emit(False, "Định dạng file không được hỗ trợ!")
        except Exception as e:
            self.finished_signal.emit(False, f"Lỗi xảy ra trong quá trình cài đặt: {str(e)}")

    def install_deb(self):
        self.progress_signal.emit(f"Đang cài đặt gói Debian (.deb): {self.filepath.name}")
        self.progress_signal.emit("Yêu cầu mật khẩu quản trị (PolicyKit)...")
        
        pkg_name = ""
        version = ""
        try:
            result = subprocess.run(["dpkg", "-I", str(self.filepath)], capture_output=True, text=True, check=True)
            for line in result.stdout.splitlines():
                line = line.strip()
                if line.startswith("Package:"):
                    pkg_name = line.split(":", 1)[1].strip()
                elif line.startswith("Version:"):
                    version = line.split(":", 1)[1].strip()
        except Exception as e:
            self.finished_signal.emit(False, f"Không thể đọc thông tin file .deb: {str(e)}")
            return

        if not pkg_name:
            self.finished_signal.emit(False, "Không thể lấy tên gói từ file .deb")
            return

        # Thực thi cài đặt bằng pkexec
        cmd = ["pkexec", "apt-get", "install", "-y", str(self.filepath)]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True)
            if proc.returncode != 0:
                self.finished_signal.emit(False, f"Cài đặt thất bại hoặc bị hủy.\\nLog: {proc.stderr}")
                return
            self.progress_signal.emit(f"Đã cài đặt gói {pkg_name} ({version})")
        except Exception as e:
            self.finished_signal.emit(False, f"Lỗi khi chạy lệnh pkexec: {str(e)}")
            return

        # Tìm shortcut hệ thống vừa sinh ra
        desktop_files = []
        try:
            list_result = subprocess.run(["dpkg", "-L", pkg_name], capture_output=True, text=True, check=True)
            for line in list_result.stdout.splitlines():
                if line.endswith(".desktop") and "/usr/share/applications/" in line:
                    desktop_files.append(Path(line))
        except Exception:
            pass

        if not desktop_files:
            for f in Path("/usr/share/applications").glob("*.desktop"):
                if pkg_name in f.name.lower():
                    desktop_files.append(f)

        created_shortcuts = []
        if desktop_files:
            for sys_desktop in desktop_files:
                dest = DESKTOP_DIR / sys_desktop.name
                try:
                    shutil.copy2(sys_desktop, dest)
                    make_desktop_file_trusted(dest)
                    created_shortcuts.append(str(dest))
                    self.progress_signal.emit(f"Đã copy shortcut ra Desktop: {sys_desktop.name}")
                except Exception as e:
                    self.progress_signal.emit(f"Lỗi copy shortcut: {str(e)}")

        # Lưu registry
        registry = load_registry()
        registry[pkg_name] = {
            "name": pkg_name,
            "type": "deb",
            "install_path": "Hệ thống (/usr/bin)",
            "executable_path": pkg_name,
            "desktop_files": created_shortcuts,
            "deb_package_name": pkg_name,
            "installed_at": str(self.filepath.name)
        }
        save_registry(registry)
        self.finished_signal.emit(True, f"Đã cài đặt gói {pkg_name} thành công!")

    def install_appimage(self):
        self.progress_signal.emit(f"Đang cài đặt AppImage: {self.filepath.name}")
        app_name = get_clean_name(self.filepath)
        app_id = app_name.lower().replace(" ", "_")
        
        app_dir = APPS_DIR / app_id
        app_dir.mkdir(parents=True, exist_ok=True)
        dest_appimage = app_dir / f"{app_id}.AppImage"
        
        if self.is_upgrade and dest_appimage.exists():
            self.progress_signal.emit("Đang dọn dẹp phiên bản cũ...")
            dest_appimage.unlink()

        self.progress_signal.emit("Đang sao chép file vào thư mục lưu trữ...")
        shutil.copy2(self.filepath, dest_appimage)
        dest_appimage.chmod(0o755)
        
        # Trích xuất icon
        self.progress_signal.emit("Đang trích xuất icon từ AppImage...")
        icon_dest_path = app_dir / "icon.png"
        final_icon = "application-x-executable"
        
        with tempfile.TemporaryDirectory() as tmpdir:
            try:
                subprocess.run([str(dest_appimage), "--appimage-extract"], cwd=tmpdir, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
                squashfs_root = Path(tmpdir) / "squashfs-root"
                if squashfs_root.exists():
                    dir_icon = squashfs_root / ".DirIcon"
                    if dir_icon.exists():
                        shutil.copy2(dir_icon, icon_dest_path)
                        final_icon = str(icon_dest_path)
                    else:
                        png_icons = list(squashfs_root.glob("*.png")) + list(squashfs_root.glob("*.svg"))
                        if png_icons:
                            best_icon = max(png_icons, key=lambda p: p.stat().st_size)
                            shutil.copy2(best_icon, icon_dest_path)
                            final_icon = str(icon_dest_path)
            except Exception:
                pass

        # Tạo Shortcut
        self.progress_signal.emit("Đang tạo shortcut Desktop...")
        shortcuts = create_desktop_shortcuts(app_id, app_name, str(dest_appimage), final_icon)

        # Registry
        registry = load_registry()
        registry[app_id] = {
            "name": app_name,
            "type": "appimage",
            "install_path": str(app_dir),
            "executable_path": str(dest_appimage),
            "desktop_files": shortcuts,
            "installed_at": str(self.filepath.name)
        }
        save_registry(registry)
        self.finished_signal.emit(True, f"Đã cài đặt/cập nhật ứng dụng {app_name} thành công!")

    def install_archive(self):
        self.progress_signal.emit(f"Đang cài đặt gói nén: {self.filepath.name}")
        app_name = get_clean_name(self.filepath)
        app_id = app_name.lower().replace(" ", "_")
        app_dir = APPS_DIR / app_id
        
        if self.is_upgrade and app_dir.exists():
            self.progress_signal.emit("Đang xóa dữ liệu phiên bản cũ...")
            shutil.rmtree(app_dir)
            
        app_dir.mkdir(parents=True, exist_ok=True)

        self.progress_signal.emit("Đang giải nén...")
        try:
            if self.filepath.suffix == ".zip":
                with zipfile.ZipFile(self.filepath, 'r') as zip_ref:
                    zip_ref.extractall(app_dir)
            else:
                mode = 'r:gz' if self.filepath.name.endswith(('.tar.gz', '.tgz')) else 'r:xz'
                with tarfile.open(self.filepath, mode) as tar_ref:
                    tar_ref.extractall(app_dir)
        except Exception as e:
            self.finished_signal.emit(False, f"Giải nén thất bại: {str(e)}")
            return

        self.progress_signal.emit("Đang tìm kiếm file chạy chính...")
        executables = []
        icons = []
        excluded_extensions = {
            '.so', '.a', '.h', '.c', '.cpp', '.pyc', '.txt', '.md', '.json', 
            '.xml', '.pdf', '.zip', '.tar.gz', '.tar.xz', '.tgz', '.html', 
            '.css', '.js', '.ts', '.png', '.jpg', '.jpeg', '.svg', '.gif', '.ico'
        }
        
        for root, dirs, files in os.walk(app_dir):
            if any(p in root for p in ["/lib", "/share", "/include", "/node_modules", "/resources", "/locales"]):
                continue
            for file in files:
                file_path = Path(root) / file
                if file_path.suffix not in excluded_extensions:
                    if os.access(file_path, os.X_OK) and file_path.is_file():
                        executables.append(file_path)
                if file_path.suffix in ['.png', '.svg']:
                    icons.append(file_path)

        if not executables:
            self.finished_signal.emit(False, f"Không tìm thấy file chạy chính nào.")
            return

        exec_path = None
        matches = [e for e in executables if app_id in e.name.lower() or app_name.lower() in e.name.lower()]
        if matches:
            exec_path = min(matches, key=lambda x: len(x.name))
        else:
            exec_path = executables[0]

        icon_path = "application-x-executable"
        if icons:
            matches_icon = [i for i in icons if app_id in i.name.lower() or app_name.lower() in i.name.lower()]
            if matches_icon:
                icon_path = str(matches_icon[0])
            else:
                icon_path = str(max(icons, key=lambda p: p.stat().st_size))

        self.progress_signal.emit("Đang tạo shortcut Desktop...")
        shortcuts = create_desktop_shortcuts(app_id, app_name, str(exec_path), icon_path)

        registry = load_registry()
        registry[app_id] = {
            "name": app_name,
            "type": "archive",
            "install_path": str(app_dir),
            "executable_path": str(exec_path),
            "desktop_files": shortcuts,
            "installed_at": str(self.filepath.name)
        }
        save_registry(registry)
        self.finished_signal.emit(True, f"Đã cài đặt/cập nhật gói nén {app_name} thành công!")

    def install_script(self):
        self.progress_signal.emit(f"Đang chạy script: {self.filepath.name}")
        self.filepath.chmod(0o755)
        
        try:
            proc = subprocess.run([str(self.filepath)], capture_output=True, text=True)
            if proc.returncode != 0:
                self.finished_signal.emit(False, f"Script lỗi: {proc.stderr}")
                return
        except Exception as e:
            self.finished_signal.emit(False, f"Lỗi chạy script: {str(e)}")
            return

        app_id = self.filepath.stem.lower().replace(" ", "_")
        registry = load_registry()
        registry[app_id] = {
            "name": self.filepath.stem,
            "type": "script",
            "install_path": "Hệ thống / Script tự cài",
            "executable_path": "",
            "desktop_files": [],
            "installed_at": str(self.filepath.name)
        }
        save_registry(registry)
        self.finished_signal.emit(True, f"Script cài đặt đã hoàn thành thành công!")

    def install_flatpak(self):
        self.progress_signal.emit(f"Đang cài đặt gói Flatpak: {self.filepath.name}")
        
        # Cài đặt mức user để không cần sudo
        cmd = ["flatpak", "install", "--user", "-y", str(self.filepath)]
        self.progress_signal.emit("Đang chạy lệnh cài đặt Flatpak ở mức user...")
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True)
            if proc.returncode != 0:
                self.finished_signal.emit(False, f"Cài đặt Flatpak lỗi: {proc.stderr}")
                return
        except Exception as e:
            self.finished_signal.emit(False, f"Lỗi thực thi lệnh flatpak: {str(e)}")
            return

        # Nhận diện Flatpak App ID
        app_id_real = ""
        if self.filepath.name.endswith(".flatpakref"):
            # Đọc file flatpakref để tìm Name (App ID)
            try:
                with open(self.filepath, "r", encoding="utf-8") as f:
                    for line in f:
                        if line.strip().startswith("Name="):
                            app_id_real = line.split("=", 1)[1].strip()
                            break
            except Exception:
                pass

        if not app_id_real:
            # Quét danh sách flatpak list để tìm app mới cài
            try:
                list_proc = subprocess.run(["flatpak", "list", "--columns=application"], capture_output=True, text=True)
                apps = [line.strip() for line in list_proc.stdout.splitlines() if line.strip()]
                # Chọn app phù hợp nhất với tên file
                clean_name = get_clean_name(self.filepath).lower()
                for app in apps:
                    if clean_name in app.lower():
                        app_id_real = app
                        break
            except Exception:
                pass

        if not app_id_real:
            app_id_real = get_clean_name(self.filepath).lower()

        # Tìm shortcut flatpak xuất ra ở user applications
        flatpak_desktop_dir = Path("/home/tanma/.local/share/flatpak/exports/share/applications")
        desktop_files = []
        if flatpak_desktop_dir.exists():
            for f in flatpak_desktop_dir.glob("*.desktop"):
                if app_id_real in f.name.lower() or get_clean_name(self.filepath).lower() in f.name.lower():
                    desktop_files.append(f)

        created_shortcuts = []
        if desktop_files:
            for sys_desktop in desktop_files:
                dest = DESKTOP_DIR / sys_desktop.name
                try:
                    shutil.copy2(sys_desktop, dest)
                    make_desktop_file_trusted(dest)
                    created_shortcuts.append(str(dest))
                    self.progress_signal.emit(f"Đã tạo shortcut Desktop: {sys_desktop.name}")
                except Exception:
                    pass

        registry = load_registry()
        registry[app_id_real] = {
            "name": get_clean_name(self.filepath),
            "type": "flatpak",
            "install_path": f"/home/tanma/.local/share/flatpak/app/{app_id_real}",
            "executable_path": f"flatpak run {app_id_real}",
            "desktop_files": created_shortcuts,
            "flatpak_app_id": app_id_real,
            "installed_at": str(self.filepath.name)
        }
        save_registry(registry)
        self.finished_signal.emit(True, f"Cài đặt Flatpak {get_clean_name(self.filepath)} thành công!")

    def install_snap(self):
        self.progress_signal.emit(f"Đang cài đặt gói Snap: {self.filepath.name}")
        self.progress_signal.emit("Yêu cầu mật khẩu quản trị (PolicyKit)...")
        
        # Cài snap offline cần cờ --dangerous
        cmd = ["pkexec", "snap", "install", "--dangerous", str(self.filepath)]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True)
            if proc.returncode != 0:
                self.finished_signal.emit(False, f"Cài đặt Snap lỗi hoặc bị hủy.\\nLog: {proc.stderr}")
                return
        except Exception as e:
            self.finished_signal.emit(False, f"Lỗi khi chạy lệnh pkexec snap: {str(e)}")
            return

        snap_name = get_clean_name(self.filepath).lower()
        
        # Tìm shortcut snap
        snap_desktop_dir = Path("/var/lib/snapd/desktop/applications")
        desktop_files = []
        if snap_desktop_dir.exists():
            for f in snap_desktop_dir.glob("*.desktop"):
                if snap_name in f.name.lower():
                    desktop_files.append(f)

        created_shortcuts = []
        if desktop_files:
            for sys_desktop in desktop_files:
                dest = DESKTOP_DIR / sys_desktop.name
                try:
                    shutil.copy2(sys_desktop, dest)
                    make_desktop_file_trusted(dest)
                    created_shortcuts.append(str(dest))
                    self.progress_signal.emit(f"Đã tạo shortcut Desktop: {sys_desktop.name}")
                except Exception:
                    pass

        registry = load_registry()
        registry[snap_name] = {
            "name": get_clean_name(self.filepath),
            "type": "snap",
            "install_path": f"/var/lib/snapd/snaps",
            "executable_path": f"snap run {snap_name}",
            "desktop_files": created_shortcuts,
            "snap_name": snap_name,
            "installed_at": str(self.filepath.name)
        }
        save_registry(registry)
        self.finished_signal.emit(True, f"Cài đặt Snap {snap_name} thành công!")


# --- THREAD GỠ CÀI ĐẶT DƯỚI NỀN (QTHREAD) ---
class UninstallWorker(QThread):
    progress_signal = pyqtSignal(str)
    finished_signal = pyqtSignal(bool, str)

    def __init__(self, app_id, purge_config=False):
        super().__init__()
        self.app_id = app_id
        self.purge_config = purge_config

    def run(self):
        registry = load_registry()
        if self.app_id not in registry:
            self.finished_signal.emit(False, "Không tìm thấy app trong registry.")
            return

        app_info = registry[self.app_id]
        app_name = app_info.get("name", self.app_id)
        self.progress_signal.emit(f"Đang tiến hành gỡ bỏ ứng dụng: {app_name}")

        # 1. Xóa các shortcut
        if "desktop_files" in app_info:
            for desk_file in app_info["desktop_files"]:
                if os.path.exists(desk_file):
                    try:
                        os.remove(desk_file)
                        self.progress_signal.emit(f"Đã xóa shortcut: {Path(desk_file).name}")
                    except Exception:
                        pass

        # 2. Xử lý gỡ theo loại
        app_type = app_info.get("type", "")
        if app_type == "deb":
            pkg_name = app_info.get("deb_package_name", self.app_id)
            self.progress_signal.emit(f"Đang gỡ gói deb (yêu cầu mật khẩu quản trị)...")
            try:
                proc = subprocess.run(["pkexec", "apt-get", "remove", "-y", pkg_name], capture_output=True, text=True)
                if proc.returncode != 0:
                    self.finished_signal.emit(False, f"Gỡ gói deb thất bại hoặc bị hủy.\\nLog: {proc.stderr}")
                    return
                subprocess.run(["pkexec", "apt-get", "autoremove", "-y"], capture_output=True, text=True)
            except Exception as e:
                self.finished_signal.emit(False, f"Lỗi gỡ gói: {str(e)}")
                return
                
        elif app_type in ["appimage", "archive"]:
            install_path = Path(app_info["install_path"])
            if install_path.exists() and install_path.is_dir() and install_path.parent == APPS_DIR:
                self.progress_signal.emit(f"Đang xóa thư mục cài đặt...")
                try:
                    shutil.rmtree(install_path)
                except Exception as e:
                    self.finished_signal.emit(False, f"Không thể xóa thư mục cài đặt: {str(e)}")
                    return
            else:
                self.progress_signal.emit("Bỏ qua xóa thư mục (đường dẫn hệ thống hoặc không an toàn).")

        elif app_type == "flatpak":
            flatpak_id = app_info.get("flatpak_app_id", self.app_id)
            self.progress_signal.emit(f"Đang gỡ Flatpak ở mức user...")
            cmd = ["flatpak", "uninstall", "--user", "-y", flatpak_id]
            try:
                proc = subprocess.run(cmd, capture_output=True, text=True)
                if proc.returncode != 0:
                    self.finished_signal.emit(False, f"Gỡ Flatpak thất bại: {proc.stderr}")
                    return
            except Exception as e:
                self.finished_signal.emit(False, f"Lỗi chạy lệnh flatpak: {str(e)}")
                return

        elif app_type == "snap":
            snap_name = app_info.get("snap_name", self.app_id)
            self.progress_signal.emit(f"Đang gỡ Snap (yêu cầu mật khẩu quản trị)...")
            cmd = ["pkexec", "snap", "remove", snap_name]
            try:
                proc = subprocess.run(cmd, capture_output=True, text=True)
                if proc.returncode != 0:
                    self.finished_signal.emit(False, f"Gỡ Snap thất bại hoặc bị hủy.\\nLog: {proc.stderr}")
                    return
            except Exception as e:
                self.finished_signal.emit(False, f"Lỗi chạy lệnh pkexec snap: {str(e)}")
                return

        # 3. Dọn cấu hình rác ở thư mục cá nhân nếu được chọn
        if self.purge_config:
            self.progress_signal.emit("Đang quét dọn cấu hình rác ở thư mục cá nhân...")
            home_config = Path("/home/tanma/.config")
            home_local = Path("/home/tanma/.local/share")
            home_cache = Path("/home/tanma/.cache")
            
            # Khớp từ khóa tìm các thư mục liên quan
            keywords = [self.app_id.lower(), app_name.lower(), app_name.lower().replace(" ", "")]
            # Thêm các ký tự thường gặp khi viết thường/viết liền
            
            purged_folders = []
            for base_dir in [home_config, home_local, home_cache]:
                if not base_dir.exists():
                    continue
                for item in base_dir.iterdir():
                    if item.is_dir():
                        item_name_lower = item.name.lower()
                        # Kiểm tra xem tên thư mục có khớp hoàn toàn hoặc chứa từ khóa
                        if any(kw == item_name_lower or (len(kw) > 3 and kw in item_name_lower) for kw in keywords):
                            # Không xóa nhầm các thư mục hệ thống cực kỳ quan trọng
                            if item.name not in [".", "..", "applications", "flatpak", "systemd", "menus", "trash"]:
                                try:
                                    shutil.rmtree(item)
                                    purged_folders.append(str(item))
                                    self.progress_signal.emit(f"Đã dọn dẹp: {item.relative_to('/home/tanma')}")
                                except Exception:
                                    pass
            if purged_folders:
                self.progress_signal.emit(f"Đã dọn sạch {len(purged_folders)} thư mục cấu hình rác.")
            else:
                self.progress_signal.emit("Không phát hiện thư mục cấu hình rác nào đáng nghi.")

        # 4. Xóa khỏi registry
        del registry[self.app_id]
        save_registry(registry)
        self.finished_signal.emit(True, f"Đã gỡ cài đặt hoàn chỉnh ứng dụng: {app_name}!")


# --- WIDGET KÉO THẢ (DRAG & DROP ZONE) ---
class DropZoneWidget(QFrame):
    fileDropped = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setFrameStyle(QFrame.StyledPanel | QFrame.Sunken)
        self.setLineWidth(2)
        
        self.normal_style = """
            QFrame {
                border: 2px dashed #3498db;
                border-radius: 12px;
                background-color: #ecf0f1;
            }
            QFrame:hover {
                background-color: #e2e8f0;
            }
        """
        self.drag_style = """
            QFrame {
                border: 2px dashed #2ecc71;
                border-radius: 12px;
                background-color: #d5f5e3;
            }
        """
        self.setStyleSheet(self.normal_style)

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)

        self.label_icon = QLabel("📥", self)
        self.label_icon.setFont(QFont("Segoe UI", 36))
        self.label_icon.setAlignment(Qt.AlignCenter)
        
        self.label_text = QLabel("KÉO THẢ FILE CÀI ĐẶT VÀO ĐÂY\n(.deb, .AppImage, .zip, .tar.gz, .flatpak, .snap, .sh, .run)", self)
        self.label_text.setFont(QFont("Segoe UI", 11, QFont.Bold))
        self.label_text.setStyleSheet("color: #2c3e50;")
        self.label_text.setAlignment(Qt.AlignCenter)

        self.btn_browse = QPushButton("Hoặc bấm vào đây để chọn file", self)
        self.btn_browse.setFont(QFont("Segoe UI", 10))
        self.btn_browse.setStyleSheet("""
            QPushButton {
                background-color: #3498db;
                color: white;
                border-radius: 6px;
                padding: 8px 16px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #2980b9;
            }
        """)
        self.btn_browse.clicked.connect(self.select_file_dialog)

        layout.addWidget(self.label_icon)
        layout.addWidget(self.label_text)
        layout.addWidget(self.btn_browse)

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.setStyleSheet(self.drag_style)
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        self.setStyleSheet(self.normal_style)

    def dropEvent(self, event: QDropEvent):
        self.setStyleSheet(self.normal_style)
        for url in event.mimeData().urls():
            filepath = url.toLocalFile()
            if filepath:
                self.fileDropped.emit(filepath)
                break

    def select_file_dialog(self):
        file_filter = "File cài đặt Linux (*.deb *.AppImage *.zip *.tar.gz *.tar.xz *.tgz *.flatpak *.flatpakref *.snap *.sh *.run);;Tất cả file (*)"
        filepath, _ = QFileDialog.getOpenFileName(self, "Chọn file cài đặt", "/home/tanma/Downloads", file_filter)
        if filepath:
            self.fileDropped.emit(filepath)


# --- CỬA SỔ CHÍNH ---
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Linux App Installer Manager (AIaC 2026)")
        self.setMinimumSize(850, 650)
        self.init_ui()
        self.refresh_table()

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(15)

        title_label = QLabel("LINUX APP INSTALLER MANAGER", self)
        title_label.setFont(QFont("Segoe UI", 18, QFont.Bold))
        title_label.setStyleSheet("color: #2c3e50;")
        title_label.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(title_label)

        # Drop Zone
        self.drop_zone = DropZoneWidget(self)
        self.drop_zone.fileDropped.connect(self.check_and_start_install)
        main_layout.addWidget(self.drop_zone, stretch=2)

        # Log View
        self.log_view = QTextEdit(self)
        self.log_view.setReadOnly(True)
        self.log_view.setPlaceholderText("Trạng thái tiến trình cài đặt...")
        self.log_view.setMaximumHeight(110)
        self.log_view.setStyleSheet("background-color: #2c3e50; color: #ecf0f1; font-family: Courier; border-radius: 8px; padding: 6px;")
        main_layout.addWidget(self.log_view, stretch=1)

        list_label = QLabel("Danh sách ứng dụng đã quản lý:", self)
        list_label.setFont(QFont("Segoe UI", 11, QFont.Bold))
        list_label.setStyleSheet("color: #2c3e50; margin-top: 5px;")
        main_layout.addWidget(list_label)

        # Bảng danh sách app (Thêm cột Dung lượng)
        self.table = QTableWidget(self)
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["Tên Ứng Dụng", "Định Dạng", "Dung Lượng", "Nguồn File Cài", "Thao Tác"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents) # Dung lượng
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents) # Thao tác
        self.table.setStyleSheet("""
            QTableWidget {
                background-color: white;
                border: 1px solid #bdc3c7;
                border-radius: 8px;
            }
            QHeaderView::section {
                background-color: #34495e;
                color: white;
                font-weight: bold;
                padding: 6px;
                border: none;
            }
        """)
        main_layout.addWidget(self.table, stretch=3)

        self.statusBar().showMessage("Sẵn sàng.")

    def log(self, text):
        self.log_view.append(text)
        self.log_view.moveCursor(self.log_view.textCursor().End)

    def refresh_table(self):
        self.table.setRowCount(0)
        registry = load_registry()
        
        self.table.setRowCount(len(registry))
        for row, (app_id, info) in enumerate(registry.items()):
            # Tên
            self.table.setItem(row, 0, QTableWidgetItem(info.get("name", app_id)))
            # Định dạng
            self.table.setItem(row, 1, QTableWidgetItem(info.get("type", "Không rõ").upper()))
            # Dung lượng (Storage Tracker)
            size_str = get_app_display_size(app_id, info)
            self.table.setItem(row, 2, QTableWidgetItem(size_str))
            # Nguồn
            self.table.setItem(row, 3, QTableWidgetItem(info.get("installed_at", "Không rõ")))
            
            # Nút gỡ
            btn_uninstall = QPushButton("Gỡ bỏ")
            btn_uninstall.setStyleSheet("""
                QPushButton {
                    background-color: #e74c3c;
                    color: white;
                    border-radius: 4px;
                    padding: 4px 12px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: #c0392b;
                }
            """)
            btn_uninstall.clicked.connect(lambda checked, aid=app_id: self.confirm_uninstall(aid))
            self.table.setCellWidget(row, 4, btn_uninstall)

    # --- KIỂM TRA TRÙNG LẶP & SMART UPDATE ---
    def check_and_start_install(self, filepath):
        path = Path(filepath)
        app_name = get_clean_name(path)
        app_id = app_name.lower().replace(" ", "_")
        
        # Một số định dạng dùng app_id khác
        filename = path.name.lower()
        if filename.endswith(".deb"):
            # Đối với deb ta parse tên từ file deb trước để tránh trùng lặp chính xác
            try:
                res = subprocess.run(["dpkg", "-I", str(path)], capture_output=True, text=True, check=True)
                for line in res.stdout.splitlines():
                    if line.strip().startswith("Package:"):
                        app_id = line.split(":", 1)[1].strip()
                        break
            except Exception:
                pass
        elif filename.endswith(".flatpakref"):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    for line in f:
                        if line.strip().startswith("Name="):
                            app_id = line.split("=", 1)[1].strip()
                            break
            except Exception:
                pass

        registry = load_registry()
        is_upgrade = False
        
        if app_id in registry:
            old_info = registry[app_id]
            old_file = old_info.get("installed_at", "phiên bản cũ")
            
            reply = QMessageBox.question(
                self, "Phát hiện phiên bản cũ",
                f"Ứng dụng '{app_name}' đã được cài đặt qua tool (nguồn: {old_file}).\\n\\n"
                f"Anh Tân có muốn chạy nâng cấp tự động (Smart Update), đè lên phiên bản cũ và giữ nguyên cấu hình/shortcut không?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            )
            if reply == QMessageBox.No:
                self.log("Hủy cài đặt do người dùng không đồng ý nâng cấp.")
                return
            is_upgrade = True
            
        self.start_install(filepath, is_upgrade)

    def start_install(self, filepath, is_upgrade=False):
        self.log_view.clear()
        self.log(f"-> Nhận file cài đặt: {filepath}")
        
        self.drop_zone.setEnabled(False)
        self.statusBar().showMessage("Đang thực hiện cài đặt...")

        self.worker = InstallWorker(filepath, is_upgrade)
        self.worker.progress_signal.connect(self.log)
        self.worker.finished_signal.connect(self.on_install_finished)
        self.worker.start()

    def on_install_finished(self, success, message):
        self.drop_zone.setEnabled(True)
        self.refresh_table()
        
        if success:
            self.log(f"[XONG] {message}")
            self.statusBar().showMessage("Cài đặt thành công!")
            QMessageBox.information(self, "Thành công", message)
        else:
            self.log(f"[THẤT BẠI] {message}")
            self.statusBar().showMessage("Cài đặt thất bại.")
            QMessageBox.critical(self, "Lỗi cài đặt", message)

    # --- CONFIRM UNINSTALL & PURGE CONFIG ---
    def confirm_uninstall(self, app_id):
        registry = load_registry()
        app_info = registry.get(app_id, {})
        app_name = app_info.get("name", app_id)
        
        # Hỏi gỡ app
        reply = QMessageBox.question(
            self, "Xác nhận gỡ bỏ", 
            f"Anh Tân có chắc chắn muốn gỡ cài đặt ứng dụng '{app_name}' không?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            # Hỏi thêm dọn cấu hình rác (Purge Config Data)
            purge_reply = QMessageBox.question(
                self, "Dọn dẹp cấu hình rác",
                f"Anh Tân có muốn dọn sạch dữ liệu cấu hình cá nhân của '{app_name}' (~/.config, ~/.local/share, ~/.cache) không?\\n\\n"
                "Chọn 'Yes' để dọn sạch sẽ hệ thống 100%, chọn 'No' nếu muốn giữ lại cấu hình cũ.",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            )
            
            purge_config = (purge_reply == QMessageBox.Yes)
            
            self.log_view.clear()
            self.log(f"-> Nhận yêu cầu gỡ cài đặt: {app_name}")
            
            self.drop_zone.setEnabled(False)
            self.statusBar().showMessage("Đang thực hiện gỡ cài đặt...")

            self.un_worker = UninstallWorker(app_id, purge_config)
            self.un_worker.progress_signal.connect(self.log)
            self.un_worker.finished_signal.connect(self.on_uninstall_finished)
            self.un_worker.start()

    def on_uninstall_finished(self, success, message):
        self.drop_zone.setEnabled(True)
        self.refresh_table()
        
        if success:
            self.log(f"[XONG] {message}")
            self.statusBar().showMessage("Gỡ cài đặt thành công!")
            QMessageBox.information(self, "Thành công", message)
        else:
            self.log(f"[THẤT BẠI] {message}")
            self.statusBar().showMessage("Gỡ cài đặt thất bại.")
            QMessageBox.critical(self, "Lỗi gỡ cài đặt", message)


# --- MAIN ---
def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
