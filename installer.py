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

# Mã màu terminal ANSI
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
BLUE = "\033[94m"
BOLD = "\033[1m"
RESET = "\033[0m"

def print_success(msg):
    print(f"{GREEN}{BOLD}[THÀNH CÔNG]{RESET} {msg}")

def print_info(msg):
    print(f"{BLUE}[THÔNG TIN]{RESET} {msg}")

def print_warning(msg):
    print(f"{YELLOW}{BOLD}[CẢNH BÁO]{RESET} {msg}")

def print_error(msg):
    print(f"{RED}{BOLD}[LỖI]{RESET} {msg}")

# --- QUẢN LÝ REGISTRY ---
def load_registry():
    if not REGISTRY_PATH.exists():
        return {}
    try:
        with open(REGISTRY_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print_error(f"Không thể đọc file registry.json: {e}")
        return {}

def save_registry(registry):
    try:
        with open(REGISTRY_PATH, "w", encoding="utf-8") as f:
            json.dump(registry, f, indent=4, ensure_ascii=False)
    except Exception as e:
        print_error(f"Không thể ghi file registry.json: {e}")

# --- UTILS SHORTCUT (.DESKTOP) ---
def make_desktop_file_trusted(desktop_path):
    """Cấp quyền thực thi và đánh dấu trusted cho file .desktop trên Desktop"""
    try:
        # Cấp quyền thực thi
        os.chmod(desktop_path, 0o755)
        # Đánh dấu trusted bằng gio (đặc thù của Cinnamon/GNOME)
        subprocess.run(["gio", "set", str(desktop_path), "metadata::trusted", "true"], check=False)
    except Exception as e:
        print_warning(f"Không thể đặt thuộc tính trusted cho shortcut desktop: {e}")

def create_desktop_shortcuts(app_id, name, exec_path, icon_path, categories="Utility;"):
    """Tạo shortcut .desktop ở Desktop và Application Menu"""
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
    # Shortcut trên Desktop
    desktop_shortcut = DESKTOP_DIR / f"{app_id}.desktop"
    # Shortcut trong Menu ứng dụng
    menu_shortcut = USER_APPLICATIONS_DIR / f"{app_id}.desktop"
    
    try:
        with open(desktop_shortcut, "w", encoding="utf-8") as f:
            f.write(desktop_content)
        make_desktop_file_trusted(desktop_shortcut)
        
        with open(menu_shortcut, "w", encoding="utf-8") as f:
            f.write(desktop_content)
        os.chmod(menu_shortcut, 0o755)
        
        print_success(f"Đã tạo shortcut trên Desktop: {desktop_shortcut}")
        print_success(f"Đã thêm ứng dụng vào Menu hệ thống.")
        return [str(desktop_shortcut), str(menu_shortcut)]
    except Exception as e:
        print_error(f"Không thể tạo file shortcut .desktop: {e}")
        return []

# --- XỬ LÝ CÁC LOẠI FILE CÀI ĐẶT ---

def get_clean_name(filepath):
    """Lấy tên ứng dụng sạch từ tên file"""
    name = Path(filepath).stem
    # Loại bỏ các hậu tố phiên bản, kiến trúc thường gặp
    name = re.sub(r'[-_]v?\d+\.\d+.*$', '', name, flags=re.IGNORECASE)
    name = re.sub(r'[-_]amd64$', '', name, flags=re.IGNORECASE)
    name = re.sub(r'[-_]x86_64$', '', name, flags=re.IGNORECASE)
    name = re.sub(r'[-_]linux$', '', name, flags=re.IGNORECASE)
    return name

def install_deb(filepath):
    print_info(f"Đang cài đặt gói Debian (.deb): {filepath}")
    
    # 1. Phân tích file .deb để lấy thông tin gói
    try:
        result = subprocess.run(["dpkg", "-I", filepath], capture_output=True, text=True, check=True)
        pkg_name = ""
        version = ""
        for line in result.stdout.splitlines():
            line = line.strip()
            if line.startswith("Package:"):
                pkg_name = line.split(":", 1)[1].strip()
            elif line.startswith("Version:"):
                version = line.split(":", 1)[1].strip()
        
        if not pkg_name:
            print_error("Không thể lấy tên package từ file .deb")
            return
    except Exception as e:
        print_error(f"Lỗi khi đọc thông tin file .deb: {e}")
        return

    # 2. Cài đặt bằng apt (để tự giải quyết dependencies)
    print_info(f"Đang chạy lệnh cài đặt: sudo apt install -y {filepath}")
    try:
        subprocess.run(["sudo", "apt", "install", "-y", filepath], check=True)
        print_success(f"Đã cài đặt thành công gói {pkg_name} ({version})")
    except subprocess.CalledProcessError as e:
        print_error(f"Cài đặt gói .deb thất bại: {e}")
        return

    # 3. Tìm file .desktop do apt cài đặt để copy ra Desktop của anh Tân
    desktop_files = []
    try:
        # dpkg -L liệt kê toàn bộ file đã cài
        list_result = subprocess.run(["dpkg", "-L", pkg_name], capture_output=True, text=True, check=True)
        for line in list_result.stdout.splitlines():
            if line.endswith(".desktop") and "/usr/share/applications/" in line:
                desktop_files.append(Path(line))
    except Exception as e:
        print_warning(f"Không thể liệt kê file cài đặt để tìm shortcut: {e}")

    # Nếu không tìm thấy bằng dpkg -L, quét thủ công trong /usr/share/applications/
    if not desktop_files:
        for f in Path("/usr/share/applications").glob("*.desktop"):
            if pkg_name in f.name.lower():
                desktop_files.append(f)

    created_shortcuts = []
    if desktop_files:
        # Copy file .desktop tìm thấy ra ngoài Desktop của anh Tân
        for sys_desktop in desktop_files:
            dest = DESKTOP_DIR / sys_desktop.name
            try:
                shutil.copy2(sys_desktop, dest)
                make_desktop_file_trusted(dest)
                created_shortcuts.append(str(dest))
                print_success(f"Đã copy shortcut hệ thống ra Desktop: {dest}")
            except Exception as e:
                print_error(f"Không thể copy shortcut ra Desktop: {e}")
    else:
        print_warning(f"Không tìm thấy file .desktop hệ thống cho {pkg_name}. Anh có thể tự khởi chạy từ Menu.")

    # 4. Lưu vào registry
    registry = load_registry()
    registry[pkg_name] = {
        "name": pkg_name,
        "type": "deb",
        "install_path": "Hệ thống (/usr/bin)",
        "executable_path": pkg_name,
        "desktop_files": created_shortcuts,
        "deb_package_name": pkg_name,
        "installed_at": str(Path(filepath).name)
    }
    save_registry(registry)

def install_appimage(filepath):
    print_info(f"Đang cài đặt AppImage: {filepath}")
    filepath = Path(filepath).resolve()
    
    app_name = get_clean_name(filepath)
    app_id = app_name.lower().replace(" ", "_")
    
    app_dir = APPS_DIR / app_id
    app_dir.mkdir(parents=True, exist_ok=True)
    
    dest_appimage = app_dir / f"{app_id}.AppImage"
    
    # 1. Sao chép và cấp quyền
    try:
        shutil.copy2(filepath, dest_appimage)
        dest_appimage.chmod(0o755)
        print_info(f"Đã lưu AppImage vào: {dest_appimage}")
    except Exception as e:
        print_error(f"Không thể copy file AppImage: {e}")
        return

    # 2. Trích xuất icon và file desktop gốc
    icon_dest_path = app_dir / "icon.png"
    # Mặc định dùng icon hệ thống nếu không trích xuất được
    final_icon = "application-x-executable" 
    
    with tempfile.TemporaryDirectory() as tmpdir:
        print_info("Đang trích xuất metadata từ AppImage...")
        # Chạy lệnh trích xuất AppImage
        try:
            # Hầu hết AppImage hỗ trợ --appimage-extract
            # Ta sẽ chạy lệnh này trong thư mục tạm
            subprocess.run([str(dest_appimage), "--appimage-extract"], cwd=tmpdir, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
            
            squashfs_root = Path(tmpdir) / "squashfs-root"
            if squashfs_root.exists():
                # Tìm file .desktop và file icon
                desktop_files = list(squashfs_root.glob("*.desktop"))
                
                # Tìm icon: .DirIcon hoặc file .png/.svg lớn nhất
                dir_icon = squashfs_root / ".DirIcon"
                if dir_icon.exists():
                    shutil.copy2(dir_icon, icon_dest_path)
                    final_icon = str(icon_dest_path)
                else:
                    png_icons = list(squashfs_root.glob("*.png")) + list(squashfs_root.glob("*.svg"))
                    if png_icons:
                        # Lấy file icon có dung lượng lớn nhất (thường là chất lượng cao nhất)
                        best_icon = max(png_icons, key=lambda p: p.stat().st_size)
                        shutil.copy2(best_icon, icon_dest_path)
                        final_icon = str(icon_dest_path)
            else:
                print_warning("Không thể tự động trích xuất icon từ AppImage, sẽ dùng icon mặc định.")
        except Exception as e:
            print_warning(f"Lỗi trích xuất icon từ AppImage: {e}")

    # 3. Tạo Shortcut
    shortcuts = create_desktop_shortcuts(
        app_id=app_id,
        name=app_name,
        exec_path=str(dest_appimage),
        icon_path=final_icon
    )

    # 4. Lưu vào registry
    registry = load_registry()
    registry[app_id] = {
        "name": app_name,
        "type": "appimage",
        "install_path": str(app_dir),
        "executable_path": str(dest_appimage),
        "desktop_files": shortcuts,
        "installed_at": str(filepath.name)
    }
    save_registry(registry)
    print_success(f"Đã cài đặt thành công AppImage {app_name}!")

def install_archive(filepath):
    print_info(f"Đang cài đặt gói nén: {filepath}")
    filepath = Path(filepath).resolve()
    
    app_name = get_clean_name(filepath)
    app_id = app_name.lower().replace(" ", "_")
    
    app_dir = APPS_DIR / app_id
    if app_dir.exists():
        print_warning(f"Thư mục cài đặt {app_dir} đã tồn tại. Sẽ giải nén đè lên.")
    app_dir.mkdir(parents=True, exist_ok=True)

    # 1. Giải nén
    try:
        if filepath.suffix == ".zip":
            print_info("Đang giải nén file .zip...")
            with zipfile.ZipFile(filepath, 'r') as zip_ref:
                zip_ref.extractall(app_dir)
        elif filepath.name.endswith(".tar.gz") or filepath.name.endswith(".tgz"):
            print_info("Đang giải nén file .tar.gz...")
            with tarfile.open(filepath, 'r:gz') as tar_ref:
                tar_ref.extractall(app_dir)
        elif filepath.name.endswith(".tar.xz"):
            print_info("Đang giải nén file .tar.xz...")
            with tarfile.open(filepath, 'r:xz') as tar_ref:
                tar_ref.extractall(app_dir)
        else:
            print_error("Định dạng file nén không được hỗ trợ!")
            return
        print_success("Giải nén hoàn tất!")
    except Exception as e:
        print_error(f"Giải nén thất bại: {e}")
        return

    # 2. Tìm file thực thi (executable binary)
    executables = []
    icons = []
    
    # Danh sách các đuôi file loại trừ
    excluded_extensions = {
        '.so', '.a', '.h', '.c', '.cpp', '.pyc', '.txt', '.md', '.json', 
        '.xml', '.pdf', '.zip', '.tar.gz', '.tar.xz', '.tgz', '.html', 
        '.css', '.js', '.ts', '.png', '.jpg', '.jpeg', '.svg', '.gif', '.ico'
    }
    
    # Quét đệ quy
    for root, dirs, files in os.walk(app_dir):
        # Bỏ qua các thư mục con không chứa app chạy chính
        if any(p in root for p in ["/lib", "/share", "/include", "/node_modules", "/resources", "/locales"]):
            continue
            
        for file in files:
            file_path = Path(root) / file
            
            # Quét file thực thi
            if file_path.suffix not in excluded_extensions:
                if os.access(file_path, os.X_OK) and file_path.is_file():
                    executables.append(file_path)
            
            # Quét file icon
            if file_path.suffix in ['.png', '.svg']:
                icons.append(file_path)

    if not executables:
        print_error(f"Không tìm thấy file thực thi nào trong thư mục giải nén: {app_dir}")
        print_info("Em đã giải nén xong, anh có thể tự kiểm tra thư mục cài đặt.")
        return

    # Chọn file thực thi phù hợp nhất
    exec_path = None
    if len(executables) == 1:
        exec_path = executables[0]
    else:
        # Ưu tiên các file có tên trùng hoặc gần giống app_id hoặc app_name
        matches = [e for e in executables if app_id in e.name.lower() or app_name.lower() in e.name.lower()]
        if matches:
            # Chọn file có độ dài tên ngắn nhất trong số trùng (thường là file chính)
            exec_path = min(matches, key=lambda x: len(x.name))
        else:
            # Nếu không tìm thấy, liệt kê cho người dùng chọn
            print_warning("Tìm thấy nhiều file thực thi. Vui lòng chọn file chạy chính:")
            for idx, exe in enumerate(executables):
                print(f"  {idx + 1}. {exe.relative_to(app_dir)}")
            
            try:
                choice = input(f"Lựa chọn của anh (1-{len(executables)}) [Mặc định: 1]: ").strip()
                if not choice:
                    exec_path = executables[0]
                else:
                    exec_path = executables[int(choice) - 1]
            except Exception:
                exec_path = executables[0]

    print_info(f"Đã chọn file chạy chính: {exec_path}")

    # Tìm icon phù hợp nhất
    icon_path = "application-x-executable"
    if icons:
        # Ưu tiên file icon chứa tên app
        matches_icon = [i for i in icons if app_id in i.name.lower() or app_name.lower() in i.name.lower()]
        if matches_icon:
            icon_path = str(matches_icon[0])
        else:
            # Lấy icon lớn nhất
            icon_path = str(max(icons, key=lambda p: p.stat().st_size))

    # 3. Tạo Shortcut
    shortcuts = create_desktop_shortcuts(
        app_id=app_id,
        name=app_name,
        exec_path=str(exec_path),
        icon_path=icon_path
    )

    # 4. Lưu vào registry
    registry = load_registry()
    registry[app_id] = {
        "name": app_name,
        "type": "archive",
        "install_path": str(app_dir),
        "executable_path": str(exec_path),
        "desktop_files": shortcuts,
        "installed_at": str(filepath.name)
    }
    save_registry(registry)
    print_success(f"Đã cài đặt thành công gói nén {app_name}!")

def install_script(filepath):
    print_info(f"Đang chuẩn bị chạy script cài đặt (.sh/.run): {filepath}")
    filepath = Path(filepath).resolve()
    
    # Cấp quyền thực thi
    try:
        filepath.chmod(0o755)
    except Exception as e:
        print_warning(f"Không thể cấp quyền thực thi cho file: {e}")

    # Chạy script trực tiếp trong terminal để người dùng tương tác
    print_info("Đang chạy script... Vui lòng tương tác trực tiếp nếu script yêu cầu.")
    try:
        subprocess.run([str(filepath)], shell=True, check=True)
        print_success("Chạy script cài đặt hoàn tất!")
    except subprocess.CalledProcessError as e:
        print_error(f"Script cài đặt trả về mã lỗi: {e}")
        return

    # Lưu ghi chú vào registry
    app_id = filepath.stem.lower().replace(" ", "_")
    registry = load_registry()
    registry[app_id] = {
        "name": filepath.stem,
        "type": "script",
        "install_path": "Hệ thống / Do script tự định nghĩa",
        "executable_path": "",
        "desktop_files": [],
        "installed_at": str(filepath.name)
    }
    save_registry(registry)
    print_info("Script đã chạy xong. Nếu script tự tạo shortcut thì shortcut đã có sẵn. Nếu chưa, anh hãy kiểm tra hướng dẫn của app đó.")

# --- TỰ ĐỘNG PHÂN BIỆT LOẠI FILE ---
def route_install(file_path_str):
    # Loại bỏ dấu nháy đơn/kép (kéo thả thường bị)
    file_path_str = file_path_str.strip("'\" ")
    if not file_path_str:
        print_error("Đường dẫn file trống!")
        return

    path = Path(file_path_str)
    if not path.exists():
        print_error(f"File không tồn tại: {file_path_str}")
        return

    filename = path.name.lower()
    
    if filename.endswith(".deb"):
        install_deb(path)
    elif filename.endswith(".appimage"):
        install_appimage(path)
    elif filename.endswith(".tar.gz") or filename.endswith(".tar.xz") or filename.endswith(".tgz") or filename.endswith(".zip"):
        install_archive(path)
    elif filename.endswith(".sh") or filename.endswith(".run"):
        install_script(path)
    else:
        print_warning("Định dạng file không thuộc các nhóm phổ biến (.deb, .AppImage, .tar.gz, .zip, .sh, .run).")
        choice = input("Anh có muốn thử chạy cài đặt như một script (.sh) không? (y/n) [Mặc định: n]: ").strip().lower()
        if choice == 'y':
            install_script(path)

# --- GỠ CÀI ĐẶT ---
def uninstall_app(app_id):
    registry = load_registry()
    if app_id not in registry:
        # Thử tìm kiếm theo tên gần giống
        matches = [k for k in registry.keys() if app_id.lower() in k.lower() or app_id.lower() in registry[k]["name"].lower()]
        if len(matches) == 1:
            app_id = matches[0]
        elif len(matches) > 1:
            print_warning(f"Tìm thấy nhiều ứng dụng khớp với từ khóa '{app_id}':")
            for idx, m in enumerate(matches):
                print(f"  {idx + 1}. {registry[m]['name']} ({m})")
            try:
                choice = input(f"Lựa chọn gỡ cài đặt (1-{len(matches)}): ").strip()
                app_id = matches[int(choice) - 1]
            except Exception:
                print_error("Lựa chọn không hợp lệ.")
                return
        else:
            print_error(f"Không tìm thấy ứng dụng '{app_id}' trong danh sách đã cài đặt qua công cụ.")
            return

    app_info = registry[app_id]
    print_info(f"Đang chuẩn bị gỡ cài đặt ứng dụng: {app_info['name']}")
    
    # 1. Xóa các shortcut .desktop
    if "desktop_files" in app_info:
        for desk_file in app_info["desktop_files"]:
            if os.path.exists(desk_file):
                try:
                    os.remove(desk_file)
                    print_info(f"Đã xóa file shortcut: {desk_file}")
                except Exception as e:
                    print_warning(f"Không thể xóa shortcut {desk_file}: {e}")

    # 2. Xử lý gỡ cài đặt theo loại ứng dụng
    if app_info["type"] == "deb":
        pkg_name = app_info.get("deb_package_name", app_id)
        print_info(f"Đang gỡ gói deb qua apt: sudo apt remove -y {pkg_name}")
        try:
            subprocess.run(["sudo", "apt", "remove", "-y", pkg_name], check=True)
            subprocess.run(["sudo", "apt", "autoremove", "-y"], check=True)
            print_success(f"Đã gỡ cài đặt gói deb {pkg_name} thành công.")
        except Exception as e:
            print_error(f"Gỡ gói deb thất bại: {e}")
            return
            
    elif app_info["type"] in ["appimage", "archive"]:
        install_path = Path(app_info["install_path"])
        if install_path.exists() and install_path.is_dir() and install_path.parent == APPS_DIR:
            print_info(f"Đang xóa thư mục ứng dụng: {install_path}")
            try:
                shutil.rmtree(install_path)
                print_success(f"Đã xóa thư mục ứng dụng {app_info['name']}.")
            except Exception as e:
                print_error(f"Không thể xóa thư mục cài đặt: {e}")
                return
        else:
            print_warning(f"Đường dẫn thư mục cài đặt {install_path} không tồn tại hoặc không an toàn để xóa tự động.")

    elif app_info["type"] == "script":
        print_warning(f"Ứng dụng cài đặt bằng script. Công cụ chỉ xóa shortcut. Anh có thể cần gỡ cài đặt thủ công theo hướng dẫn của app.")

    # 3. Xóa khỏi registry
    del registry[app_id]
    save_registry(registry)
    print_success(f"Gỡ cài đặt hoàn tất cho ứng dụng: {app_info['name']}")

# --- HIỂN THỊ DANH SÁCH ---
def list_apps():
    registry = load_registry()
    if not registry:
        print_info("Chưa có ứng dụng nào được cài đặt thông qua công cụ này.")
        return

    print(f"\n{BOLD}{BLUE}==========================================================================")
    print(f"        DANH SÁCH ỨNG DỤNG ĐÃ CÀI ĐẶT QUA MANAGER")
    print(f"=========================================================================={RESET}")
    print(f"{BOLD}{'ID':<15} | {'Tên ứng dụng':<25} | {'Định dạng':<10} | {'File nguồn cài đặt'}{RESET}")
    print("-" * 74)
    for app_id, info in registry.items():
        name = info.get("name", "Không rõ")
        app_type = info.get("type", "Không rõ").upper()
        source = info.get("installed_at", "Không rõ")
        print(f"{app_id:<15} | {name:<25} | {app_type:<10} | {source}")
    print("=" * 74 + "\n")

# --- INTERACTIVE CLI ---
def interactive_menu():
    while True:
        print(f"{BOLD}{BLUE}==================================================")
        print("        LINUX APP INSTALLER MANAGER (AIaC)")
        print(f"=================================================={RESET}")
        print("1. Cài đặt ứng dụng mới (Nhập đường dẫn / Kéo thả file)")
        print("2. Danh sách ứng dụng đã cài đặt")
        print("3. Gỡ cài đặt ứng dụng")
        print("4. Thoát")
        print("==================================================")
        
        try:
            choice = input("Lựa chọn của anh (1-4): ").strip()
            if choice == "1":
                file_input = input("Anh kéo thả file vào terminal hoặc nhập đường dẫn file cài: ").strip()
                route_install(file_input)
            elif choice == "2":
                list_apps()
            elif choice == "3":
                list_apps()
                app_input = input("Nhập ID ứng dụng cần gỡ cài đặt: ").strip()
                if app_input:
                    uninstall_app(app_input)
            elif choice == "4" or choice.lower() == 'q':
                print_info("Hẹn gặp lại anh Tân!")
                break
            else:
                print_error("Lựa chọn không hợp lệ! Vui lòng chọn từ 1 đến 4.")
        except KeyboardInterrupt:
            print("\n")
            print_info("Hẹn gặp lại anh Tân!")
            break
        except Exception as e:
            print_error(f"Đã xảy ra lỗi ngoài ý muốn: {e}")
        print("\n")

# --- MAIN ENTRY POINT ---
def main():
    if len(sys.argv) < 2:
        # Chạy chế độ Menu tương tác
        interactive_menu()
    else:
        command = sys.argv[1].lower()
        if command == "install" and len(sys.argv) >= 3:
            route_install(sys.argv[2])
        elif command == "uninstall" and len(sys.argv) >= 3:
            uninstall_app(sys.argv[2])
        elif command in ["list", "show"]:
            list_apps()
        elif command in ["--help", "-h", "help"]:
            print(f"{BOLD}Sử dụng:{RESET}")
            print("  Giao diện menu:  python3 installer.py")
            print("  Cài đặt file:    python3 installer.py install <đường_dẫn_file>")
            print("  Gỡ cài đặt:      python3 installer.py uninstall <id_ứng_dụng>")
            print("  Liệt kê:         python3 installer.py list")
        else:
            print_error("Lệnh không hợp lệ! Dùng -h hoặc --help để xem hướng dẫn.")

if __name__ == "__main__":
    main()
