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
import shlex
import urllib.request
import urllib.parse
import time
from pathlib import Path

# Cấu hình đường dẫn
BASE_DIR = Path("/media/tanma/DATA/tool_installs")
APPS_DIR = BASE_DIR / "apps"
REGISTRY_PATH = BASE_DIR / "registry.json"
DESKTOP_DIR = Path("/home/tanma/Desktop")
USER_APPLICATIONS_DIR = Path("/home/tanma/.local/share/applications")

# Cấu hình đường dẫn AIaC và Antigravity
AIAC_DIR = Path("/media/tanma/DATA/aiac")
GEMINI_SKILLS_DIR = Path("/home/tanma/.gemini/config/skills")

# Tạo các thư mục nếu chưa tồn tại
APPS_DIR.mkdir(parents=True, exist_ok=True)
DESKTOP_DIR.mkdir(parents=True, exist_ok=True)
USER_APPLICATIONS_DIR.mkdir(parents=True, exist_ok=True)
GEMINI_SKILLS_DIR.mkdir(parents=True, exist_ok=True)

# Kiểm tra thư viện PyQt5, nếu thiếu dùng zenity để thông báo trực quan
try:
    from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                                 QHBoxLayout, QLabel, QPushButton, QTableWidget, 
                                 QTableWidgetItem, QHeaderView, QTextEdit, QFileDialog, 
                                 QMessageBox, QFrame, QLineEdit, QProgressBar, QMenu, 
                                 QAction, QTabWidget, QSplitter, QComboBox)
    from PyQt5.QtCore import Qt, QThread, pyqtSignal
    from PyQt5.QtGui import QDragEnterEvent, QDropEvent, QFont, QCursor
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
    if size_bytes <= 0:
        return "N/A"
    if size_bytes < 1024:
        return f"{size_bytes} B"
    size_name = ("B", "KB", "MB", "GB", "TB")
    i = int(math.floor(math.log(size_bytes, 1024)))
    p = math.pow(1024, i)
    s = round(size_bytes / p, 2)
    return f"{s} {size_name[i]}"

def get_app_display_size(app_id, info):
    app_type = info.get("type", "")
    if app_type == "deb":
        size = get_deb_installed_size(info.get("deb_package_name", app_id))
        return format_size(size) if size > 0 else "Hệ thống"
    elif app_type in ["appimage", "archive"]:
        size = get_dir_size(info.get("install_path", ""))
        return format_size(size)
    elif app_type == "flatpak":
        app_id_real = info.get("flatpak_app_id", app_id)
        user_path = Path(f"/home/tanma/.local/share/flatpak/app/{app_id_real}")
        sys_path = Path(f"/var/lib/flatpak/app/{app_id_real}")
        size = 0
        if user_path.exists():
            size = get_dir_size(user_path)
        elif sys_path.exists():
            size = get_dir_size(sys_path)
        return format_size(size) if size > 0 else "Flatpak"
    elif app_type == "snap":
        app_name_real = info.get("snap_name", app_id)
        snap_file_dir = Path("/var/lib/snapd/snaps")
        size = 0
        if snap_file_dir.exists():
            for f in snap_file_dir.glob(f"{app_name_real}_*.snap"):
                size += f.stat().st_size
        return format_size(size) if size > 0 else "Snap"
    return "Không rõ"

# --- UTILS THÔNG BÁO HỆ THỐNG CINNAMON (WOW 2) ---
def send_system_notification(title, message, icon_path=None):
    try:
        cmd = ["notify-send", "-a", "Linux App Installer", title, message]
        if icon_path and os.path.exists(icon_path):
            cmd.extend(["-i", str(icon_path)])
        else:
            cmd.extend(["-i", "system-software-install"])
        subprocess.run(cmd, check=False)
    except Exception:
        pass

# --- UTILS KHỞI CHẠY APP ĐỘC LẬP & DEBUG (WOW 3) ---
def launch_app_by_id(app_id, debug_mode=False):
    registry = load_registry()
    if app_id not in registry:
        return False, "Không tìm thấy ứng dụng trong cơ sở dữ liệu."
    
    info = registry[app_id]
    exec_path = info.get("executable_path", "")
    app_name = info.get("name", app_id)
    
    if not exec_path:
        return False, "Không xác định được file thực thi cho ứng dụng này."
        
    try:
        if debug_mode:
            terminal_cmd = f'gnome-terminal --title="Log Debug: {app_name}" -- bash -c "{exec_path}; echo; echo \\"------------------------------\\"; echo \\"--- ỨNG DỤNG ĐÃ THOÁT ---\\"; read -p \\"Nhấn Enter để đóng cửa sổ này...\\" -n 1"'
            subprocess.Popen(shlex.split(terminal_cmd), start_new_session=True)
            return True, f"Đang khởi chạy chế độ Debug Log cho {app_name}..."
        else:
            args = shlex.split(exec_path)
            subprocess.Popen(
                args,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True
            )
            return True, f"Khởi chạy thành công: {app_name}"
    except Exception as e:
        return False, f"Lỗi khi chạy app: {str(e)}"

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
    name = re.sub(r'[-_]v?\d+\.\d+.*$', '', name, flags=re.IGNORECASE)
    name = re.sub(r'[-_]amd64$', '', name, flags=re.IGNORECASE)
    name = re.sub(r'[-_]x86_64$', '', name, flags=re.IGNORECASE)
    name = re.sub(r'[-_]linux$', '', name, flags=re.IGNORECASE)
    return name


# --- THREAD TẢI FILE TỪ URL (WOW 1) ---
class DownloadWorker(QThread):
    progress_signal = pyqtSignal(int, str)
    finished_signal = pyqtSignal(bool, str, str)

    def __init__(self, url):
        super().__init__()
        self.url = url.strip()

    def run(self):
        try:
            url_path = urllib.parse.urlparse(self.url).path
            filename = urllib.parse.unquote(url_path.split('/')[-1])
            if not filename or '.' not in filename:
                filename = "downloaded_package"
            
            filename = filename.split('?')[0].split('#')[0]
            
            req = urllib.request.Request(self.url, headers={'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36'})
            self.progress_signal.emit(0, "Đang kết nối đến máy chủ tải xuống...")
            
            with urllib.request.urlopen(req) as response:
                cd = response.getheader('Content-Disposition')
                if cd:
                    fname = re.findall("filename\\*?=(?:utf-8'')?([^\\s;]+)", cd)
                    if fname:
                        filename = urllib.parse.unquote(fname[0].strip('\'"'))
                
                filepath = Path(tempfile.gettempdir()) / filename
                
                content_length = response.getheader('Content-Length')
                total_size = int(content_length) if content_length else 0
                
                bytes_read = 0
                chunk_size = 1024 * 64
                start_time = time.time()
                
                with open(filepath, 'wb') as f:
                    while True:
                        chunk = response.read(chunk_size)
                        if not chunk:
                            break
                        f.write(chunk)
                        bytes_read += len(chunk)
                        
                        elapsed = time.time() - start_time
                        speed = bytes_read / elapsed if elapsed > 0 else 0
                        speed_str = format_size(speed) + "/s"
                        
                        if total_size > 0:
                            percent = int(bytes_read * 100 / total_size)
                            progress_text = f"Đang tải: {format_size(bytes_read)} / {format_size(total_size)} ({percent}%) - Tốc độ: {speed_str}"
                            self.progress_signal.emit(percent, progress_text)
                        else:
                            progress_text = f"Đang tải: {format_size(bytes_read)} - Tốc độ: {speed_str}"
                            self.progress_signal.emit(-1, progress_text)
                
                self.progress_signal.emit(100, f"Tải xuống hoàn tất! Đã lưu vào {filepath}")
                self.finished_signal.emit(True, "Tải file từ URL thành công!", str(filepath))
                
        except Exception as e:
            self.finished_signal.emit(False, f"Lỗi khi tải file: {str(e)}", "")


# --- THREAD CÀI ĐẶT DƯỚI NỀN (QTHREAD) ---
class InstallWorker(QThread):
    progress_signal = pyqtSignal(str)
    finished_signal = pyqtSignal(bool, str, str)

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
                self.finished_signal.emit(False, "Định dạng file không được hỗ trợ!", "")
        except Exception as e:
            self.finished_signal.emit(False, f"Lỗi xảy ra trong quá trình cài đặt: {str(e)}", "")

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
            self.finished_signal.emit(False, f"Không thể đọc thông tin file .deb: {str(e)}", "")
            return

        if not pkg_name:
            self.finished_signal.emit(False, "Không thể lấy tên gói từ file .deb", "")
            return

        cmd = ["pkexec", "apt-get", "install", "-y", str(self.filepath)]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True)
            if proc.returncode != 0:
                self.finished_signal.emit(False, f"Cài đặt thất bại hoặc bị hủy.\\nLog: {proc.stderr}", "")
                return
            self.progress_signal.emit(f"Đã cài đặt gói {pkg_name} ({version})")
        except Exception as e:
            self.finished_signal.emit(False, f"Lỗi khi chạy lệnh pkexec: {str(e)}", "")
            return

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
        icon_path = ""
        if desktop_files:
            for sys_desktop in desktop_files:
                dest = DESKTOP_DIR / sys_desktop.name
                try:
                    shutil.copy2(sys_desktop, dest)
                    make_desktop_file_trusted(dest)
                    created_shortcuts.append(str(dest))
                    self.progress_signal.emit(f"Đã copy shortcut ra Desktop: {sys_desktop.name}")
                    
                    with open(sys_desktop, 'r', errors='ignore') as sf:
                        for l in sf:
                            if l.startswith("Icon="):
                                icon_path = l.split("=", 1)[1].strip()
                                break
                except Exception as e:
                    self.progress_signal.emit(f"Lỗi copy shortcut: {str(e)}")

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
        self.finished_signal.emit(True, f"Đã cài đặt gói {pkg_name} thành công!", icon_path)

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

        self.progress_signal.emit("Đang tạo shortcut Desktop...")
        shortcuts = create_desktop_shortcuts(app_id, app_name, str(dest_appimage), final_icon)

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
        self.finished_signal.emit(True, f"Đã cài đặt ứng dụng {app_name} thành công!", final_icon)

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
            self.finished_signal.emit(False, f"Giải nén thất bại: {str(e)}", "")
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
            self.finished_signal.emit(False, f"Không tìm thấy file chạy chính nào.", "")
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
        self.finished_signal.emit(True, f"Đã cài đặt gói nén {app_name} thành công!", icon_path)

    def install_script(self):
        self.progress_signal.emit(f"Đang chạy script: {self.filepath.name}")
        self.filepath.chmod(0o755)
        
        try:
            proc = subprocess.run([str(self.filepath)], capture_output=True, text=True)
            if proc.returncode != 0:
                self.finished_signal.emit(False, f"Script lỗi: {proc.stderr}", "")
                return
        except Exception as e:
            self.finished_signal.emit(False, f"Lỗi chạy script: {str(e)}", "")
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
        self.finished_signal.emit(True, f"Script cài đặt đã hoàn thành thành công!", "")

    def install_flatpak(self):
        self.progress_signal.emit(f"Đang cài đặt gói Flatpak: {self.filepath.name}")
        cmd = ["flatpak", "install", "--user", "-y", str(self.filepath)]
        self.progress_signal.emit("Đang chạy lệnh cài đặt Flatpak ở mức user...")
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True)
            if proc.returncode != 0:
                self.finished_signal.emit(False, f"Cài đặt Flatpak lỗi: {proc.stderr}", "")
                return
        except Exception as e:
            self.finished_signal.emit(False, f"Lỗi thực thi lệnh flatpak: {str(e)}", "")
            return

        app_id_real = ""
        if self.filepath.name.endswith(".flatpakref"):
            try:
                with open(self.filepath, "r", encoding="utf-8") as f:
                    for line in f:
                        if line.strip().startswith("Name="):
                            app_id_real = line.split("=", 1)[1].strip()
                            break
            except Exception:
                pass

        if not app_id_real:
            try:
                list_proc = subprocess.run(["flatpak", "list", "--columns=application"], capture_output=True, text=True)
                apps = [line.strip() for line in list_proc.stdout.splitlines() if line.strip()]
                clean_name = get_clean_name(self.filepath).lower()
                for app in apps:
                    if clean_name in app.lower():
                        app_id_real = app
                        break
            except Exception:
                pass

        if not app_id_real:
            app_id_real = get_clean_name(self.filepath).lower()

        flatpak_desktop_dir = Path("/home/tanma/.local/share/flatpak/exports/share/applications")
        desktop_files = []
        if flatpak_desktop_dir.exists():
            for f in flatpak_desktop_dir.glob("*.desktop"):
                if app_id_real in f.name.lower() or get_clean_name(self.filepath).lower() in f.name.lower():
                    desktop_files.append(f)

        created_shortcuts = []
        icon_path = ""
        if desktop_files:
            for sys_desktop in desktop_files:
                dest = DESKTOP_DIR / sys_desktop.name
                try:
                    shutil.copy2(sys_desktop, dest)
                    make_desktop_file_trusted(dest)
                    created_shortcuts.append(str(dest))
                    self.progress_signal.emit(f"Đã tạo shortcut Desktop: {sys_desktop.name}")
                    
                    with open(sys_desktop, 'r', errors='ignore') as sf:
                        for l in sf:
                            if l.startswith("Icon="):
                                icon_path = l.split("=", 1)[1].strip()
                                break
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
        self.finished_signal.emit(True, f"Cài đặt Flatpak {get_clean_name(self.filepath)} thành công!", icon_path)

    def install_snap(self):
        self.progress_signal.emit(f"Đang cài đặt gói Snap: {self.filepath.name}")
        self.progress_signal.emit("Yêu cầu mật khẩu quản trị (PolicyKit)...")
        
        cmd = ["pkexec", "snap", "install", "--dangerous", str(self.filepath)]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True)
            if proc.returncode != 0:
                self.finished_signal.emit(False, f"Cài đặt Snap lỗi hoặc bị hủy.\\nLog: {proc.stderr}", "")
                return
        except Exception as e:
            self.finished_signal.emit(False, f"Lỗi khi chạy lệnh pkexec snap: {str(e)}", "")
            return

        snap_name = get_clean_name(self.filepath).lower()
        
        snap_desktop_dir = Path("/var/lib/snapd/desktop/applications")
        desktop_files = []
        if snap_desktop_dir.exists():
            for f in snap_desktop_dir.glob("*.desktop"):
                if snap_name in f.name.lower():
                    desktop_files.append(f)

        created_shortcuts = []
        icon_path = ""
        if desktop_files:
            for sys_desktop in desktop_files:
                dest = DESKTOP_DIR / sys_desktop.name
                try:
                    shutil.copy2(sys_desktop, dest)
                    make_desktop_file_trusted(dest)
                    created_shortcuts.append(str(dest))
                    self.progress_signal.emit(f"Đã tạo shortcut Desktop: {sys_desktop.name}")
                    
                    with open(sys_desktop, 'r', errors='ignore') as sf:
                        for l in sf:
                            if l.startswith("Icon="):
                                icon_path = l.split("=", 1)[1].strip()
                                break
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
        self.finished_signal.emit(True, f"Cài đặt Snap {snap_name} thành công!", icon_path)


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
            self.finished_signal.emit(False, "Ứng dụng không tồn tại trong Registry!")
            return

        info = registry[self.app_id]
        app_name = info.get("name", self.app_id)
        app_type = info.get("type", "")
        
        self.progress_signal.emit(f"Bắt đầu gỡ cài đặt: {app_name} (Loại: {app_type.upper()})")

        # 1. Xóa các shortcut .desktop
        self.progress_signal.emit("Đang xóa các shortcut Desktop & Menu...")
        desktop_files = info.get("desktop_files", [])
        for fpath in desktop_files:
            try:
                p = Path(fpath)
                if p.exists():
                    p.unlink()
                    self.progress_signal.emit(f"Đã xóa file: {p.name}")
            except Exception as e:
                self.progress_signal.emit(f"Lỗi khi xóa shortcut: {str(e)}")

        # 2. Xóa file cài vật lý hoặc chạy lệnh gỡ gói
        if app_type == "deb":
            self.progress_signal.emit("Yêu cầu quyền admin để gỡ gói apt (dpkg)...")
            cmd = ["pkexec", "apt-get", "remove", "-y", info.get("deb_package_name", self.app_id)]
            try:
                proc = subprocess.run(cmd, capture_output=True, text=True)
                if proc.returncode != 0:
                    self.finished_signal.emit(False, f"Gỡ gói .deb thất bại: {proc.stderr}")
                    return
                self.progress_signal.emit("Đã gỡ bỏ gói hệ thống thành công.")
            except Exception as e:
                self.finished_signal.emit(False, f"Lỗi thực thi lệnh gỡ apt: {str(e)}")
                return
                
        elif app_type in ["appimage", "archive"]:
            install_path = Path(info.get("install_path", ""))
            if install_path.exists() and install_path.is_dir() and install_path.resolve() != APPS_DIR.resolve():
                self.progress_signal.emit(f"Đang xóa thư mục cài đặt: {install_path}")
                try:
                    shutil.rmtree(install_path)
                    self.progress_signal.emit("Đã xóa thư mục cài đặt gốc.")
                except Exception as e:
                    self.progress_signal.emit(f"Lỗi xóa thư mục cài: {str(e)}")
            elif install_path.exists() and install_path.is_file():
                try:
                    install_path.unlink()
                    self.progress_signal.emit("Đã xóa file thực thi gốc.")
                except Exception as e:
                    self.progress_signal.emit(f"Lỗi xóa file thực thi: {str(e)}")
                    
        elif app_type == "flatpak":
            app_id_real = info.get("flatpak_app_id", self.app_id)
            self.progress_signal.emit(f"Đang chạy lệnh gỡ flatpak user cho {app_id_real}...")
            cmd = ["flatpak", "uninstall", "--user", "-y", app_id_real]
            try:
                proc = subprocess.run(cmd, capture_output=True, text=True)
                if proc.returncode != 0:
                    self.finished_signal.emit(False, f"Lỗi gỡ flatpak: {proc.stderr}")
                    return
                self.progress_signal.emit("Đã gỡ flatpak thành công.")
            except Exception as e:
                self.finished_signal.emit(False, f"Lỗi chạy lệnh flatpak: {str(e)}")
                return
                
        elif app_type == "snap":
            snap_name_real = info.get("snap_name", self.app_id)
            self.progress_signal.emit("Yêu cầu quyền admin để gỡ snap...")
            cmd = ["pkexec", "snap", "remove", snap_name_real]
            try:
                proc = subprocess.run(cmd, capture_output=True, text=True)
                if proc.returncode != 0:
                    self.finished_signal.emit(False, f"Lỗi gỡ snap: {proc.stderr}")
                    return
                self.progress_signal.emit("Đã gỡ snap thành công.")
            except Exception as e:
                self.finished_signal.emit(False, f"Lỗi chạy lệnh snap: {str(e)}")
                return

        # 3. DỌN CẤU HÌNH RÁC (PURGE DATA) (Wow 4)
        if self.purge_config:
            self.progress_signal.emit("Bắt đầu quét dọn cấu hình rác của ứng dụng...")
            home_dir = Path.home()
            
            # Các thư mục cấu hình rác tiềm năng
            target_subdirs = [
                home_dir / ".config",
                home_dir / ".local" / "share",
                home_dir / ".cache"
            ]
            
            keywords = [self.app_id.lower(), app_name.lower().replace(" ", "")]
            deleted_count = 0
            
            for parent_dir in target_subdirs:
                if not parent_dir.exists():
                    continue
                for item in parent_dir.iterdir():
                    if item.is_dir() and not item.name.startswith('.'):
                        # So khớp từ khóa
                        if any(kw in item.name.lower() for kw in keywords):
                            self.progress_signal.emit(f"Phát hiện thư mục rác: {item.relative_to(home_dir)}")
                            try:
                                shutil.rmtree(item)
                                self.progress_signal.emit(f"-> Đã dọn sạch: {item.name}")
                                deleted_count += 1
                            except Exception as e:
                                self.progress_signal.emit(f"-> Lỗi không xóa được: {str(e)}")
            if deleted_count > 0:
                self.progress_signal.emit(f"Đã dọn dẹp xong {deleted_count} thư mục cấu hình rác.")
            else:
                self.progress_signal.emit("Không tìm thấy thư mục cấu hình rác nào của ứng dụng này.")

        # 4. Cập nhật Registry
        registry.pop(self.app_id, None)
        save_registry(registry)
        
        self.finished_signal.emit(True, f"Đã gỡ cài đặt ứng dụng '{app_name}' thành công!")


# --- WORKER CHẠY LỆNH SHELL & GIT DƯỚI NỀN (QTHREAD) ---
class ScriptWorker(QThread):
    log_signal = pyqtSignal(str)
    finished_signal = pyqtSignal(bool, str)

    def __init__(self, cmd, cwd):
        super().__init__()
        self.cmd = cmd
        self.cwd = cwd

    def run(self):
        try:
            proc = subprocess.Popen(
                self.cmd,
                cwd=str(self.cwd),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1
            )
            while True:
                line = proc.stdout.readline()
                if not line and proc.poll() is not None:
                    break
                if line:
                    self.log_signal.emit(line.strip())
            
            proc.wait()
            if proc.returncode == 0:
                self.finished_signal.emit(True, "Thực thi thành công!")
            else:
                self.finished_signal.emit(False, f"Thực thi thất bại với mã lỗi: {proc.returncode}")
        except Exception as e:
            self.finished_signal.emit(False, f"Lỗi: {str(e)}")


# --- PHÂN LOẠI & QUÉT AIaC SKILLS (SYM LINKS MANAGER) ---
def get_skill_category(name):
    """Phân loại kỹ năng dựa trên tên của nó"""
    name_lower = name.lower()
    if any(kw in name_lower for kw in ["flutter", "vuaassistant", "mobile", "ios", "android", "designer"]):
        return "📱 Mobile & App"
    elif any(kw in name_lower for kw in ["odoo", "postgres", "database", "sql"]):
        return "🐍 Odoo & Backend"
    elif any(kw in name_lower for kw in ["ponytail", "audit", "checklist", "accidental-data-loss"]):
        return "🔍 Audit & Chất lượng"
    elif any(kw in name_lower for kw in ["token", "caveman", "superpowers"]):
        return "⚡ Tiết kiệm Token"
    elif any(kw in name_lower for kw in ["gitsync", "dev-workflow", "vuaoffice", "openclaw", "payload", "marketing", "airouter", "rancher", "securities"]):
        return "⚙️ Quy trình & Git"
    else:
        return "📁 Khác / Mặc định"

def scan_aiac_skills():
    skills = {}
    
    # 1. Quét trong thư mục plugins
    plugins_dir = AIAC_DIR / "360org" / "plugins"
    if plugins_dir.exists():
        for item in plugins_dir.iterdir():
            if item.is_dir() and not item.name.startswith('.'):
                skills[item.name] = {
                    "name": item.name,
                    "src_path": item,
                    "type": "Plugin (360org)"
                }
                
    # 2. Quét trong thư mục core skills
    skills_dir = AIAC_DIR / "skills"
    if skills_dir.exists():
        for item in skills_dir.iterdir():
            if item.is_dir() and not item.name.startswith('.'):
                if item.name not in skills:
                    skills[item.name] = {
                        "name": item.name,
                        "src_path": item,
                        "type": "Skill Core"
                    }
                    
    # 3. Quét kiểm tra symlink và phân loại
    for name, info in skills.items():
        dst_path = GEMINI_SKILLS_DIR / name
        info["category"] = get_skill_category(name)
        
        if not dst_path.exists() and not dst_path.is_symlink():
            info["status"] = "Chưa cài đặt"
            info["color"] = "#7f8c8d"
        elif dst_path.is_symlink():
            try:
                target = dst_path.readlink()
                src_resolved = info["src_path"].resolve()
                target_resolved = Path(os.path.normpath(os.path.join(GEMINI_SKILLS_DIR, target))).resolve()
                
                if src_resolved == target_resolved:
                    info["status"] = "Đã kích hoạt"
                    info["color"] = "#27ae60"
                else:
                    info["status"] = "Xung đột (Trỏ nơi khác)"
                    info["color"] = "#d35400"
            except Exception:
                info["status"] = "Symlink lỗi"
                info["color"] = "#c0392b"
        else:
            info["status"] = "Lỗi (Thư mục vật lý)"
            info["color"] = "#c0392b"
            
    return skills

def get_aiac_git_info():
    if not (AIAC_DIR / ".git").exists():
        return "Không phát hiện Git repo tại /media/tanma/DATA/aiac"
    try:
        res = subprocess.run(
            ["git", "log", "-n", "1", "--format=%h — %s (%cd)", "--date=format:%d/%m/%Y %H:%M"],
            cwd=str(AIAC_DIR), capture_output=True, text=True, check=True
        )
        return res.stdout.strip()
    except Exception:
        return "Không thể đọc Git log"

def get_skill_markdown_content(src_path):
    """Tìm đọc file mô tả SKILL.md hoặc README.md của skill"""
    potential_files = [
        src_path / "SKILL.md",
        src_path / "prompts" / "SKILL.md",
        src_path / "README.md"
    ]
    for pf in potential_files:
        if pf.exists():
            try:
                with open(pf, "r", encoding="utf-8", errors="ignore") as f:
                    return f.read()
            except Exception:
                pass
    return ""

def markdown_to_html(md_text):
    """Parser Markdown đơn giản sang HTML để hiển thị Rich Text"""
    if not md_text.strip():
        return "<p style='color: #7f8c8d;'>Không có file hướng dẫn hoặc mô tả SKILL.md/README.md cho skill này.</p>"
        
    # Loại bỏ Frontmatter YAML
    md_text = re.sub(r'^---.*?---', '', md_text, flags=re.DOTALL)
    
    # Escape HTML cơ bản để tránh lỗi render
    html = md_text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    
    # Thay thế code block ``` ... ```
    html = re.sub(r'```(.*?)\n(.*?)```', r'<pre style="background-color: #f5f6fa; color: #2f3640; padding: 8px; border-left: 4px solid #3498db; font-family: monospace; font-size: 10pt;">\2</pre>', html, flags=re.DOTALL)
    
    # Thay thế inline code `...`
    html = re.sub(r'`(.*?)`', r'<code style="background-color: #f1f2f6; color: #c23616; padding: 2px 4px; border-radius: 3px; font-family: monospace; font-weight: bold;">\1</code>', html)
    
    # Thay thế Heading
    html = re.sub(r'^### (.*?)$', r'<h4 style="color: #2c3e50; margin-top: 10px; margin-bottom: 5px; font-weight: bold;">\1</h4>', html, flags=re.MULTILINE)
    html = re.sub(r'^## (.*?)$', r'<h3 style="color: #2980b9; margin-top: 12px; margin-bottom: 6px; border-bottom: 1px solid #ddd; padding-bottom: 3px;">\1</h3>', html, flags=re.MULTILINE)
    html = re.sub(r'^# (.*?)$', r'<h2 style="color: #2c3e50; margin-top: 14px; margin-bottom: 8px; border-bottom: 2px solid #3498db; padding-bottom: 5px;">\1</h2>', html, flags=re.MULTILINE)
    
    # Thay thế list item `- ` hoặc `* `
    html = re.sub(r'^[-\*] (.*?)$', r'<li>\1</li>', html, flags=re.MULTILINE)
    
    # Thay thế bold **...**
    html = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', html)
    
    # Chuyển đổi ngắt dòng sang <br>
    html = html.replace('\n', '<br>')
    
    # Bọc các <li> liền kề thành <ul> (thô sơ nhưng đủ dùng)
    html = html.replace("</li><br><li>", "</li><li>")
    
    return html


# --- TÙY CHỈNH WIDGET KÉO THẢ (DRAG & DROP ZONE) ---
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
        self.setWindowTitle("Linux App & AIaC Skill Manager (AIaC 2026)")
        self.setMinimumSize(1000, 750)
        self.all_skills = {}
        self.init_ui()
        self.refresh_table()
        self.refresh_skills_table()

    def init_ui(self):
        # Sử dụng QTabWidget phân chia giao diện
        tab_widget = QTabWidget(self)
        self.setCentralWidget(tab_widget)

        # ==========================================
        # TAB 1: APP INSTALLER
        # ==========================================
        tab_installer = QWidget()
        tab_installer_layout = QVBoxLayout(tab_installer)
        tab_installer_layout.setContentsMargins(15, 15, 15, 15)
        tab_installer_layout.setSpacing(12)

        # Title Tab 1
        title_label = QLabel("LINUX APP INSTALLER MANAGER", self)
        title_label.setFont(QFont("Segoe UI", 16, QFont.Bold))
        title_label.setStyleSheet("color: #2c3e50;")
        title_label.setAlignment(Qt.AlignCenter)
        tab_installer_layout.addWidget(title_label)

        # URL Input Layout
        url_layout = QHBoxLayout()
        url_layout.setSpacing(10)
        url_label = QLabel("Link tải trực tiếp:", self)
        url_label.setFont(QFont("Segoe UI", 10, QFont.Bold))
        self.url_input = QLineEdit(self)
        self.url_input.setPlaceholderText("https://github.com/.../vuaoffice.AppImage (Direct link tải file)...")
        self.url_input.setStyleSheet("padding: 8px; border: 1px solid #bdc3c7; border-radius: 6px; background-color: white;")
        self.btn_download = QPushButton("Tải & Cài đặt", self)
        self.btn_download.setFont(QFont("Segoe UI", 10, QFont.Bold))
        self.btn_download.setStyleSheet("""
            QPushButton { background-color: #2ecc71; color: white; border-radius: 6px; padding: 8px 18px; }
            QPushButton:hover { background-color: #27ae60; }
        """)
        self.btn_download.clicked.connect(self.start_download)
        url_layout.addWidget(url_label)
        url_layout.addWidget(self.url_input)
        url_layout.addWidget(self.btn_download)
        tab_installer_layout.addLayout(url_layout)

        # Progress Bar
        self.download_progress = QProgressBar(self)
        self.download_progress.setRange(0, 100)
        self.download_progress.setValue(0)
        self.download_progress.setStyleSheet("""
            QProgressBar { border: 1px solid #bdc3c7; border-radius: 6px; text-align: center; height: 20px; }
            QProgressBar::chunk { background-color: #3498db; border-radius: 5px; }
        """)
        self.download_progress.hide()
        tab_installer_layout.addWidget(self.download_progress)

        # Drop Zone
        self.drop_zone = DropZoneWidget(self)
        self.drop_zone.fileDropped.connect(self.check_and_start_install)
        tab_installer_layout.addWidget(self.drop_zone, stretch=2)

        # Log View Tab 1
        self.log_view = QTextEdit(self)
        self.log_view.setReadOnly(True)
        self.log_view.setPlaceholderText("Nhật ký tiến trình cài đặt...")
        self.log_view.setMaximumHeight(90)
        self.log_view.setStyleSheet("background-color: #2c3e50; color: #ecf0f1; font-family: Courier; border-radius: 8px; padding: 6px;")
        tab_installer_layout.addWidget(self.log_view, stretch=1)

        # Apps List
        list_label = QLabel("Danh sách ứng dụng đã quản lý (Double-click / Chuột phải để mở app nhanh):", self)
        list_label.setFont(QFont("Segoe UI", 11, QFont.Bold))
        tab_installer_layout.addWidget(list_label)

        self.table = QTableWidget(self)
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["Tên Ứng Dụng", "Định Dạng", "Dung Lượng", "Nguồn File Cài", "Thao Tác"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table.setStyleSheet("""
            QTableWidget { background-color: white; border: 1px solid #bdc3c7; border-radius: 8px; }
            QHeaderView::section { background-color: #34495e; color: white; font-weight: bold; padding: 6px; border: none; }
        """)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.show_context_menu)
        self.table.itemDoubleClicked.connect(self.on_table_double_clicked)
        tab_installer_layout.addWidget(self.table, stretch=3)

        tab_widget.addTab(tab_installer, "📦  Trình cài đặt ứng dụng")

        # ==========================================
        # TAB 2: AIaC SKILLS MANAGER
        # ==========================================
        tab_aiac = QWidget()
        tab_aiac_layout = QVBoxLayout(tab_aiac)
        tab_aiac_layout.setContentsMargins(15, 15, 15, 15)
        tab_aiac_layout.setSpacing(12)

        # Hướng dẫn & Giải thích ý nghĩa các nút / cơ chế (Wow 5)
        help_frame = QFrame(self)
        help_frame.setStyleSheet("background-color: #eef2f7; border-left: 5px solid #3498db; padding: 8px; border-radius: 4px;")
        help_layout = QVBoxLayout(help_frame)
        help_layout.setSpacing(4)
        
        lbl_help_title = QLabel("💡 <b>Hướng dẫn & Giải thích Cơ chế vận hành AIaC:</b>", self)
        lbl_help_title.setFont(QFont("Segoe UI", 9, QFont.Bold))
        
        lbl_help_desc = QLabel(
            "- <b>Kích hoạt / Tắt</b>: Bật (tạo symlink) để Antigravity nhận diện và trang bị thêm skill cho AI, "
            "hoặc Tắt (xóa symlink) khi không dùng để giảm tải bộ nhớ context, <b>tiết kiệm token/chi phí</b>.<br>"
            "- <b>Kiểm tra & Pull Git</b>: Kéo code, prompt và các skill mới nhất của AIaC từ máy chủ (Git Upstream) về local.<br>"
            "- <b>Đồng bộ tất cả</b>: Kích hoạt liên kết hàng loạt tất cả skill có sẵn vào thư mục config của Antigravity.<br>"
            "- <b>Cập nhật Resource</b>: Tải/Cập nhật các tài nguyên offline cần thiết cho bộ kiểm duyệt kỹ năng.",
            self
        )
        lbl_help_desc.setFont(QFont("Segoe UI", 9))
        lbl_help_desc.setWordWrap(True)
        
        help_layout.addWidget(lbl_help_title)
        help_layout.addWidget(lbl_help_desc)
        tab_aiac_layout.addWidget(help_frame)

        # Header Git Info
        git_header = QFrame(self)
        git_header.setStyleSheet("background-color: #f8f9fa; border: 1px solid #e9ecef; border-radius: 8px; padding: 8px;")
        git_header_layout = QVBoxLayout(git_header)
        
        self.lbl_git_path = QLabel(f"<b>Đường dẫn AIaC local:</b> {AIAC_DIR}", self)
        self.lbl_git_path.setFont(QFont("Segoe UI", 10))
        self.lbl_git_info = QLabel("<b>Commit hiện tại:</b> Đang đọc...", self)
        self.lbl_git_info.setFont(QFont("Segoe UI", 10))
        self.update_git_label()
        
        git_header_layout.addWidget(self.lbl_git_path)
        git_header_layout.addWidget(self.lbl_git_info)
        tab_aiac_layout.addWidget(git_header)

        # Buttons Control layout
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)
        
        self.btn_git_pull = QPushButton("🔄 Kiểm tra & Pull Git", self)
        self.btn_git_pull.setFont(QFont("Segoe UI", 10, QFont.Bold))
        self.btn_git_pull.setStyleSheet("background-color: #3498db; color: white; border-radius: 6px; padding: 8px;")
        self.btn_git_pull.clicked.connect(self.run_git_pull)
        
        self.btn_sync_all = QPushButton("⚡ Đồng bộ tất cả (install-aiac)", self)
        self.btn_sync_all.setFont(QFont("Segoe UI", 10, QFont.Bold))
        self.btn_sync_all.setStyleSheet("background-color: #2ecc71; color: white; border-radius: 6px; padding: 8px;")
        self.btn_sync_all.clicked.connect(self.run_install_aiac)
        
        self.btn_update_resource = QPushButton("📚 Cập nhật Resource", self)
        self.btn_update_resource.setFont(QFont("Segoe UI", 10, QFont.Bold))
        self.btn_update_resource.setStyleSheet("background-color: #9b59b6; color: white; border-radius: 6px; padding: 8px;")
        self.btn_update_resource.clicked.connect(self.run_update_resource)
        
        btn_layout.addWidget(self.btn_git_pull)
        btn_layout.addWidget(self.btn_sync_all)
        btn_layout.addWidget(self.btn_update_resource)
        tab_aiac_layout.addLayout(btn_layout)

        # Bộ lọc Nhóm kỹ năng (Wow 6)
        filter_layout = QHBoxLayout()
        lbl_filter = QLabel("<b>Phân loại nhóm kỹ năng:</b>", self)
        lbl_filter.setFont(QFont("Segoe UI", 10))
        self.filter_combo = QComboBox(self)
        self.filter_combo.addItems([
            "Tất cả các kỹ năng",
            "📱 Mobile & App (Flutter, iOS, Hermes)",
            "🐍 Odoo & Backend (Python, Database)",
            "⚙️ Quy trình & Git (GitSync, Dev-Workflow)",
            "🔍 Audit & Chất lượng code (Ponytail, Checklist)",
            "⚡ Tiết kiệm Token (Token-Killer, Caveman)"
        ])
        self.filter_combo.setStyleSheet("padding: 6px; border: 1px solid #bdc3c7; border-radius: 6px; background-color: white;")
        self.filter_combo.currentIndexChanged.connect(self.refresh_skills_table)
        filter_layout.addWidget(lbl_filter)
        filter_layout.addWidget(self.filter_combo)
        filter_layout.addStretch()
        tab_aiac_layout.addLayout(filter_layout)

        # Splitter ngang chia đôi Trái (Bảng) - Phải (Mô tả chi tiết) (Wow 7)
        main_splitter = QSplitter(Qt.Horizontal)
        
        # Cột bên trái: Bảng
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        
        self.skills_table = QTableWidget(self)
        self.skills_table.setColumnCount(3)
        self.skills_table.setHorizontalHeaderLabels(["Tên Kỹ Năng", "Trạng Thái", "Thao Tác"])
        self.skills_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.skills_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.skills_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.skills_table.setStyleSheet("""
            QTableWidget { background-color: white; border: 1px solid #bdc3c7; border-radius: 8px; }
            QHeaderView::section { background-color: #34495e; color: white; font-weight: bold; padding: 6px; border: none; }
        """)
        self.skills_table.cellClicked.connect(self.on_skill_selected)
        left_layout.addWidget(self.skills_table)
        main_splitter.addWidget(left_widget)

        # Cột bên phải: Panel chi tiết kỹ năng
        self.detail_panel = QTextEdit(self)
        self.detail_panel.setReadOnly(True)
        self.detail_panel.setPlaceholderText("💡 Vui lòng click chọn một Kỹ năng bên bảng trái để xem mô tả chi tiết, hướng dẫn cách sử dụng và dự án phù hợp...")
        self.detail_panel.setStyleSheet("background-color: white; border: 1px solid #bdc3c7; border-radius: 8px; padding: 12px; font-size: 11pt;")
        main_splitter.addWidget(self.detail_panel)
        
        main_splitter.setSizes([500, 450])
        tab_aiac_layout.addWidget(main_splitter, stretch=3)

        # Log View Tab 2 ở dưới cùng
        self.aiac_log_view = QTextEdit(self)
        self.aiac_log_view.setReadOnly(True)
        self.aiac_log_view.setPlaceholderText("Nhật ký tiến trình đồng bộ Git & Skills...")
        self.aiac_log_view.setMaximumHeight(100)
        self.aiac_log_view.setStyleSheet("background-color: #2c3e50; color: #ecf0f1; font-family: Courier; border-radius: 8px; padding: 6px;")
        tab_aiac_layout.addWidget(self.aiac_log_view, stretch=1)

        tab_widget.addTab(tab_aiac, "🤖  AIaC Skill Manager")
        self.statusBar().showMessage("Sẵn sàng.")

    def update_git_label(self):
        git_info = get_aiac_git_info()
        self.lbl_git_info.setText(f"<b>Commit hiện tại:</b> {git_info}")

    def aiac_log(self, text):
        self.aiac_log_view.append(text)
        self.aiac_log_view.moveCursor(self.aiac_log_view.textCursor().End)

    def log(self, text):
        self.log_view.append(text)
        self.log_view.moveCursor(self.log_view.textCursor().End)

    # --- REFRESH APP INSTALLER TABLE ---
    def refresh_table(self):
        self.table.setRowCount(0)
        registry = load_registry()
        
        self.table.setRowCount(len(registry))
        for row, (app_id, info) in enumerate(registry.items()):
            self.table.setItem(row, 0, QTableWidgetItem(info.get("name", app_id)))
            self.table.setItem(row, 1, QTableWidgetItem(info.get("type", "Không rõ").upper()))
            size_str = get_app_display_size(app_id, info)
            self.table.setItem(row, 2, QTableWidgetItem(size_str))
            self.table.setItem(row, 3, QTableWidgetItem(info.get("installed_at", "Không rõ")))
            
            action_widget = QWidget()
            action_layout = QHBoxLayout(action_widget)
            action_layout.setContentsMargins(4, 2, 4, 2)
            action_layout.setSpacing(6)
            
            btn_launch = QPushButton("Mở")
            btn_launch.setStyleSheet("""
                QPushButton { background-color: #2ecc71; color: white; border-radius: 4px; padding: 4px 12px; font-weight: bold; }
                QPushButton:hover { background-color: #27ae60; }
            """)
            btn_launch.clicked.connect(lambda checked, aid=app_id: self.launch_app_by_id(aid))
            
            btn_uninstall = QPushButton("Gỡ bỏ")
            btn_uninstall.setStyleSheet("""
                QPushButton { background-color: #e74c3c; color: white; border-radius: 4px; padding: 4px 12px; font-weight: bold; }
                QPushButton:hover { background-color: #c0392b; }
            """)
            btn_uninstall.clicked.connect(lambda checked, aid=app_id: self.confirm_uninstall(aid))
            
            action_layout.addWidget(btn_launch)
            action_layout.addWidget(btn_uninstall)
            self.table.setCellWidget(row, 4, action_widget)

    # --- REFRESH AIaC SKILLS TABLE (LỌC THEO BỘ LỌC) ---
    def refresh_skills_table(self):
        self.skills_table.setRowCount(0)
        self.all_skills = scan_aiac_skills()
        
        filter_index = self.filter_combo.currentIndex()
        filter_text = self.filter_combo.currentText()
        
        # Xác định nhóm cần lọc
        target_category = ""
        if filter_index > 0:
            if "Mobile" in filter_text: target_category = "📱 Mobile & App"
            elif "Odoo" in filter_text: target_category = "🐍 Odoo & Backend"
            elif "Audit" in filter_text: target_category = "🔍 Audit & Chất lượng"
            elif "Token" in filter_text: target_category = "⚡ Tiết kiệm Token"
            elif "Quy trình" in filter_text: target_category = "⚙️ Quy trình & Git"

        # Lọc danh sách
        self.filtered_skill_names = []
        for name, info in self.all_skills.items():
            if target_category and info["category"] != target_category:
                continue
            self.filtered_skill_names.append(name)

        self.skills_table.setRowCount(len(self.filtered_skill_names))
        for row, name in enumerate(self.filtered_skill_names):
            info = self.all_skills[name]
            
            # Tên skill
            name_item = QTableWidgetItem(name)
            self.skills_table.setItem(row, 0, name_item)
            
            # Trạng thái
            status_item = QTableWidgetItem(info["status"])
            status_item.setForeground(Qt.white)
            status_item.setBackground(QApplication.palette().color(QApplication.palette().Window))
            status_item.setTextAlignment(Qt.AlignCenter)
            self.skills_table.setItem(row, 1, status_item)
            
            # Button kích hoạt/tắt symlink
            btn_action = QPushButton()
            if info["status"] == "Đã kích hoạt":
                btn_action.setText("Tắt")
                btn_action.setStyleSheet("""
                    QPushButton { background-color: #e67e22; color: white; border-radius: 4px; padding: 4px 12px; font-weight: bold; }
                    QPushButton:hover { background-color: #d35400; }
                """)
                btn_action.clicked.connect(lambda checked, n=name: self.deactivate_skill(n))
            else:
                btn_action.setText("Kích hoạt")
                btn_action.setStyleSheet("""
                    QPushButton { background-color: #3498db; color: white; border-radius: 4px; padding: 4px 12px; font-weight: bold; }
                    QPushButton:hover { background-color: #2980b9; }
                """)
                btn_action.clicked.connect(lambda checked, n=name, src=info["src_path"]: self.activate_skill(n, src))
                
            self.skills_table.setCellWidget(row, 2, btn_action)

    # --- SỰ KIỆN CLICK CHỌN SKILL ĐỂ HIỂN THỊ MÔ TẢ (Wow 7) ---
    def on_skill_selected(self, row, col):
        if not (0 <= row < len(self.filtered_skill_names)):
            return
        name = self.filtered_skill_names[row]
        info = self.all_skills[name]
        
        # Đọc file SKILL.md hoặc README.md
        md_content = get_skill_markdown_content(info["src_path"])
        html_content = markdown_to_html(md_content)
        
        # Header thông tin chung
        header_html = f"""
        <div style="background-color: #f8f9fa; border: 1px solid #ddd; padding: 10px; border-radius: 6px; margin-bottom: 12px;">
            <h2 style="color: #2c3e50; margin: 0 0 6px 0;">{name}</h2>
            <b>Phân loại nhóm:</b> <span style="color: #2980b9;">{info['category']}</span><br>
            <b>Trạng thái Antigravity:</b> <span style="color: {info.get('color', '#2c3e50')}; font-weight: bold;">{info['status']}</span><br>
            <b>Đường dẫn nguồn:</b> <code style="font-size: 9pt;">{info['src_path']}</code>
        </div>
        """
        
        self.detail_panel.setHtml(header_html + html_content)

    # --- BẬT/TẮT SYM LINK SKILL ĐƠN LẺ ---
    def activate_skill(self, name, src_path):
        dst_path = GEMINI_SKILLS_DIR / name
        try:
            if dst_path.exists() or dst_path.is_symlink():
                if dst_path.is_symlink():
                    dst_path.unlink()
                elif dst_path.is_dir():
                    shutil.rmtree(dst_path)
                else:
                    dst_path.unlink()
            
            os.symlink(src_path, dst_path)
            self.aiac_log(f"[OK] Đã tạo liên kết symlink cho skill: {name}")
            self.statusBar().showMessage(f"Đã kích hoạt skill {name} thành công!", 3000)
            send_system_notification("Kích hoạt Skill thành công", f"Skill '{name}' đã được liên kết vào Antigravity.")
        except Exception as e:
            self.aiac_log(f"[LỖI] Không thể kích hoạt skill {name}: {str(e)}")
            QMessageBox.critical(self, "Lỗi kích hoạt", f"Không thể tạo symlink cho skill {name}: {str(e)}")
            
        self.refresh_skills_table()
        # Click lại dòng vừa chọn để cập nhật trạng thái bên panel chi tiết
        try:
            row = self.filtered_skill_names.index(name)
            self.on_skill_selected(row, 0)
        except Exception:
            pass

    def deactivate_skill(self, name):
        dst_path = GEMINI_SKILLS_DIR / name
        try:
            if dst_path.is_symlink():
                dst_path.unlink()
                self.aiac_log(f"[OK] Đã gỡ liên kết symlink cho skill: {name}")
                self.statusBar().showMessage(f"Đã tắt skill {name} thành công!", 3000)
                send_system_notification("Gỡ bỏ Skill thành công", f"Skill '{name}' đã được ngắt kết nối.")
            else:
                QMessageBox.warning(self, "Không thể gỡ", f"Đường dẫn '{dst_path}' không phải symlink an toàn. Vui lòng kiểm tra thủ công.")
        except Exception as e:
            self.aiac_log(f"[LỖI] Không thể tắt skill {name}: {str(e)}")
            QMessageBox.critical(self, "Lỗi", f"Không thể xóa symlink: {str(e)}")
            
        self.refresh_skills_table()
        try:
            row = self.filtered_skill_names.index(name)
            self.on_skill_selected(row, 0)
        except Exception:
            pass

    # --- CHẠY SHELL SCRIPTS DƯỚI NỀN (PULL / INSTALL / UPDATE) ---
    def start_script_worker(self, cmd, title):
        self.aiac_log_view.clear()
        self.aiac_log(f"-> Khởi chạy: {title}")
        
        self.btn_git_pull.setEnabled(False)
        self.btn_sync_all.setEnabled(False)
        self.btn_update_resource.setEnabled(False)
        self.statusBar().showMessage(f"Đang thực hiện {title}...")

        self.script_worker = ScriptWorker(cmd, AIAC_DIR)
        self.script_worker.log_signal.connect(self.aiac_log)
        self.script_worker.finished_signal.connect(lambda success, msg: self.on_script_finished(success, msg, title))
        self.script_worker.start()

    def on_script_finished(self, success, message, title):
        self.btn_git_pull.setEnabled(True)
        self.btn_sync_all.setEnabled(True)
        self.btn_update_resource.setEnabled(True)
        
        self.refresh_skills_table()
        self.update_git_label()
        
        if success:
            self.aiac_log(f"[XONG] {title} hoàn tất thành công!")
            self.statusBar().showMessage(f"{title} thành công!")
            send_system_notification(title, "Tiến trình đồng bộ hoàn tất thành công!")
            QMessageBox.information(self, "Thành công", f"{title} đã hoàn thành thành công!")
        else:
            self.aiac_log(f"[LỖI] {title} thất bại: {message}")
            self.statusBar().showMessage(f"{title} thất bại.")
            send_system_notification(f"{title} thất bại", message)
            QMessageBox.critical(self, "Lỗi thực thi", f"{title} thất bại: {message}")

    def run_git_pull(self):
        self.start_script_worker(["git", "pull"], "Git Pull Cập nhật AIaC")

    def run_install_aiac(self):
        self.start_script_worker(["bash", "install-aiac.sh"], "Đồng bộ tất cả Skill (install-aiac.sh)")

    def run_update_resource(self):
        self.start_script_worker(["bash", "update-skills-source.sh"], "Cập nhật tài nguyên Skills (update-skills-source.sh)")

    # --- WOW 1: TẢI FILE TỪ URL ---
    def start_download(self):
        url = self.url_input.text().strip()
        if not url:
            QMessageBox.warning(self, "Thiếu liên kết", "Anh Tân vui lòng nhập hoặc dán liên kết URL tải app!")
            return
        if not (url.startswith("http://") or url.startswith("https://")):
            QMessageBox.warning(self, "Liên kết không hợp lệ", "Liên kết phải bắt đầu bằng http:// hoặc https://")
            return

        self.log_view.clear()
        self.log(f"-> Khởi tạo tải xuống từ liên kết: {url}")
        
        self.btn_download.setEnabled(False)
        self.url_input.setEnabled(False)
        self.drop_zone.setEnabled(False)
        self.download_progress.setValue(0)
        self.download_progress.show()
        self.statusBar().showMessage("Đang tải file từ URL...")

        self.dl_worker = DownloadWorker(url)
        self.dl_worker.progress_signal.connect(self.on_download_progress)
        self.dl_worker.finished_signal.connect(self.on_download_finished)
        self.dl_worker.start()

    def on_download_progress(self, percent, progress_text):
        if percent >= 0:
            self.download_progress.setValue(percent)
        self.log(progress_text)
        self.statusBar().showMessage(progress_text)

    def on_download_finished(self, success, message, filepath):
        self.btn_download.setEnabled(True)
        self.url_input.setEnabled(True)
        self.drop_zone.setEnabled(True)
        self.download_progress.hide()
        
        if success:
            self.log(f"[XONG] Tải file hoàn tất: {filepath}")
            send_system_notification("Tải xuống hoàn tất", f"Đã tải thành công file cài đặt từ liên kết về thư mục tạm.")
            self.check_and_start_install(filepath)
        else:
            self.log(f"[LỖI] Tải thất bại: {message}")
            self.statusBar().showMessage("Tải file thất bại.")
            QMessageBox.critical(self, "Lỗi tải file", message)

    # --- KHỞI CHẠY APP & CONTEXT MENU (WOW 3) ---
    def launch_app_by_id(self, app_id, debug_mode=False):
        success, message = launch_app_by_id(app_id, debug_mode)
        if success:
            self.log(f"[CHẠY] {message}")
            self.statusBar().showMessage(message, 3000)
            
            registry = load_registry()
            info = registry.get(app_id, {})
            final_icon = ""
            if info.get("type") in ["appimage", "archive"]:
                app_dir = Path(info.get("install_path", ""))
                if (app_dir / "icon.png").exists():
                    final_icon = str(app_dir / "icon.png")
            send_system_notification("Khởi chạy ứng dụng", f"Đang chạy ứng dụng '{info.get('name', app_id)}'...", final_icon)
        else:
            self.log(f"[LỖI] {message}")
            QMessageBox.critical(self, "Lỗi khởi chạy", message)

    def on_table_double_clicked(self, item):
        row = item.row()
        registry = load_registry()
        app_ids = list(registry.keys())
        if 0 <= row < len(app_ids):
            app_id = app_ids[row]
            self.launch_app_by_id(app_id)

    def show_context_menu(self, pos):
        item = self.table.itemAt(pos)
        if not item:
            return
        row = item.row()
        registry = load_registry()
        app_ids = list(registry.keys())
        if not (0 <= row < len(app_ids)):
            return
            
        app_id = app_ids[row]
        
        menu = QMenu(self)
        menu.setFont(QFont("Segoe UI", 10))
        
        act_run = QAction("▶️  Khởi chạy ứng dụng", self)
        act_run.triggered.connect(lambda: self.launch_app_by_id(app_id))
        
        act_debug = QAction("🐛  Chạy chế độ Debug Log (Xem Log)", self)
        act_debug.triggered.connect(lambda: self.launch_app_by_id(app_id, debug_mode=True))
        
        act_uninstall = QAction("🗑️  Gỡ cài đặt ứng dụng", self)
        act_uninstall.triggered.connect(lambda: self.confirm_uninstall(app_id))
        
        menu.addAction(act_run)
        menu.addAction(act_debug)
        menu.addSeparator()
        menu.addAction(act_uninstall)
        
        menu.exec_(QCursor.pos())

    # --- KIỂM TRA TRÙNG LẶP & SMART UPDATE ---
    def check_and_start_install(self, filepath):
        path = Path(filepath)
        app_name = get_clean_name(path)
        app_id = app_name.lower().replace(" ", "_")
        
        filename = path.name.lower()
        if filename.endswith(".deb"):
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

    def on_install_finished(self, success, message, icon_path):
        self.drop_zone.setEnabled(True)
        self.refresh_table()
        
        if success:
            self.log(f"[XONG] {message}")
            self.statusBar().showMessage("Cài đặt thành công!")
            send_system_notification("Cài đặt thành công", message, icon_path)
            QMessageBox.information(self, "Thành công", message)
        else:
            self.log(f"[THẤT BẠI] {message}")
            self.statusBar().showMessage("Cài đặt thất bại.")
            send_system_notification("Cài đặt thất bại", message)
            QMessageBox.critical(self, "Lỗi cài đặt", message)

    # --- CONFIRM UNINSTALL & PURGE CONFIG ---
    def confirm_uninstall(self, app_id):
        registry = load_registry()
        app_info = registry.get(app_id, {})
        app_name = app_info.get("name", app_id)
        
        reply = QMessageBox.question(
            self, "Xác nhận gỡ bỏ", 
            f"Anh Tân có chắc chắn muốn gỡ cài đặt ứng dụng '{app_name}' không?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
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
            send_system_notification("Gỡ cài đặt thành công", message)
            QMessageBox.information(self, "Thành công", message)
        else:
            self.log(f"[THẤT BẠI] {message}")
            self.statusBar().showMessage("Gỡ cài đặt thất bại.")
            send_system_notification("Gỡ cài đặt thất bại", message)
            QMessageBox.critical(self, "Lỗi gỡ cài đặt", message)


# --- MAIN ---
def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
