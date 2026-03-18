"""
chat installer
- checks if Python is installed
- installs Python if needed
- installs all dependencies
- downloads latest chat release
- creates desktop shortcut
- launches chat
dependencies: pip install requests pyinstaller
build: pyinstaller --onefile --windowed --name installer installer.py
"""

import os
import sys
import subprocess
import tempfile
import zipfile
import requests
from pathlib import Path


GITHUB_RELEASES = "https://api.github.com/repos/Streamskill/chat-app/releases/latest"
PYTHON_INSTALLER = "https://www.python.org/ftp/python/3.12.9/python-3.12.9-amd64.exe"
INSTALL_DIR = Path(os.environ.get("LOCALAPPDATA", "C:/Users/User/AppData/Local")) / "chat-app"
DESKTOP = Path.home() / "Desktop"


def show_message(msg: str):
    """Message box — works without terminal."""
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        messagebox.showinfo("chat installer", msg)
        root.destroy()
    except Exception:
        pass


def log(msg: str):
    print(msg)


def python_installed() -> str | None:
    try:
        result = subprocess.run(["python", "--version"], capture_output=True, text=True)
        if result.returncode == 0:
            return "python"
    except:
        pass
    for path in [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/Python/Python312/python.exe",
        Path("C:/Python312/python.exe"),
    ]:
        if path.exists():
            return str(path)
    return None


def install_python():
    log("Python nicht gefunden — wird installiert...")
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".exe")
    r = requests.get(PYTHON_INSTALLER, stream=True, timeout=120)
    for chunk in r.iter_content(8192):
        tmp.write(chunk)
    tmp.close()
    subprocess.run([
        tmp.name,
        "/quiet",
        "InstallAllUsers=0",
        "PrependPath=1",
        "Include_test=0"
    ], check=True)
    os.unlink(tmp.name)
    log("Python installiert!")


def install_dependencies(python: str):
    log("Dependencies werden installiert...")
    packages = ["customtkinter", "websockets", "cryptography", "requests", "aiortc"]
    subprocess.run([python, "-m", "pip", "install", "--quiet", "--upgrade"] + packages, check=True)
    log("Dependencies installiert!")


def download_chat():
    log("Chat App wird heruntergeladen...")
    INSTALL_DIR.mkdir(parents=True, exist_ok=True)

    r = requests.get(GITHUB_RELEASES, timeout=10)
    data = r.json()

    download_url = None
    for asset in data.get("assets", []):
        if asset["name"].lower().endswith(".zip") and "windows" in asset["name"].lower():
            download_url = asset["browser_download_url"]
            break

    if not download_url:
        log("Keine .zip gefunden — lade client.py direkt...")
        r = requests.get("https://raw.githubusercontent.com/Streamskill/chat-app/main/client.py")
        client_path = INSTALL_DIR / "client.py"
        client_path.write_text(r.text)
        return None

    r = requests.get(download_url, stream=True, timeout=120)
    zip_path = INSTALL_DIR / "chat-windows.zip"
    with open(zip_path, "wb") as f:
        for chunk in r.iter_content(8192):
            f.write(chunk)

    with zipfile.ZipFile(zip_path) as z:
        z.extractall(INSTALL_DIR)
    zip_path.unlink()

    log("Chat App heruntergeladen!")

    for path in INSTALL_DIR.rglob("chat.exe"):
        return path
    return None


def create_shortcut_ps(target: Path):
    """Create desktop shortcut via PowerShell — no extra dependencies."""
    shortcut_path = DESKTOP / "chat.lnk"
    ps = f"""
$ws = New-Object -ComObject WScript.Shell
$s = $ws.CreateShortcut('{shortcut_path}')
$s.TargetPath = '{target}'
$s.WorkingDirectory = '{target.parent}'
$s.Save()
"""
    subprocess.run(["powershell", "-Command", ps], capture_output=True)
    log("Desktop Shortcut erstellt!")


def create_shortcut_py(python: str, client_py: Path):
    bat_path = INSTALL_DIR / "start.bat"
    bat_path.write_text(f'@echo off\n"{python}" "{client_py}"\n')
    shortcut_path = DESKTOP / "chat.lnk"
    ps = f"""
$ws = New-Object -ComObject WScript.Shell
$s = $ws.CreateShortcut('{shortcut_path}')
$s.TargetPath = '{bat_path}'
$s.Save()
"""
    subprocess.run(["powershell", "-Command", ps], capture_output=True)
    log("Desktop Shortcut erstellt!")


def main():
    log("=== chat installer ===")
    log("")

    python = python_installed()
    if not python:
        install_python()
        python = python_installed()
        if not python:
            python = str(Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/Python/Python312/python.exe")

    log(f"Python gefunden: {python}")

    install_dependencies(python)

    chat_exe = download_chat()

    if chat_exe and chat_exe.exists():
        try:
            create_shortcut_ps(chat_exe)
        except Exception:
            pass
        log("Chat wird gestartet...")
        # onedir — must run from its own directory
        subprocess.Popen([str(chat_exe)], cwd=str(chat_exe.parent))
        show_message("Installation abgeschlossen!\nChat wurde gestartet.\nDu findest es auch auf dem Desktop.")
    else:
        client_py = INSTALL_DIR / "client.py"
        if client_py.exists():
            create_shortcut_py(python, client_py)
            log("Chat wird gestartet...")
            subprocess.Popen([python, str(client_py)])
            show_message("Installation abgeschlossen!\nChat wurde gestartet.\nDu findest es auch auf dem Desktop.")
        else:
            show_message("FEHLER: Chat konnte nicht installiert werden!")
            sys.exit(1)


if __name__ == "__main__":
    main()