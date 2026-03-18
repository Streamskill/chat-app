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
import winreg
import ctypes
from pathlib import Path


GITHUB_RELEASES = "https://api.github.com/repos/Streamskill/chat-app/releases/latest"
PYTHON_INSTALLER = "https://www.python.org/ftp/python/3.12.9/python-3.12.9-amd64.exe"
INSTALL_DIR = Path(os.environ.get("LOCALAPPDATA", "C:/Users/User/AppData/Local")) / "chat-app"
DESKTOP = Path.home() / "Desktop"


def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False


def log(msg: str):
    print(msg)


def python_installed() -> str | None:
    """Returns python path if found, else None."""
    try:
        result = subprocess.run(["python", "--version"], capture_output=True, text=True)
        if result.returncode == 0:
            return "python"
    except:
        pass
    # check common install paths
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
    # silent install with PATH
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
    packages = [
        "customtkinter",
        "websockets",
        "cryptography",
        "requests",
        "aiortc"
    ]
    subprocess.run([
        python, "-m", "pip", "install", "--quiet", "--upgrade"
    ] + packages, check=True)
    log("Dependencies installiert!")


def download_chat():
    log("Chat App wird heruntergeladen...")
    INSTALL_DIR.mkdir(parents=True, exist_ok=True)

    r = requests.get(GITHUB_RELEASES, timeout=10)
    data = r.json()

    # find windows zip
    download_url = None
    for asset in data.get("assets", []):
        if asset["name"].lower().endswith(".zip") and "windows" in asset["name"].lower():
            download_url = asset["browser_download_url"]
            break

    if not download_url:
        # fallback — download client.py directly from repo
        log("Keine .zip gefunden — lade client.py direkt...")
        r = requests.get("https://raw.githubusercontent.com/Streamskill/chat-app/main/client.py")
        client_path = INSTALL_DIR / "client.py"
        client_path.write_text(r.text)
        return None

    # download zip
    r = requests.get(download_url, stream=True, timeout=120)
    zip_path = INSTALL_DIR / "chat-windows.zip"
    with open(zip_path, "wb") as f:
        for chunk in r.iter_content(8192):
            f.write(chunk)

    # extract
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(INSTALL_DIR)
    zip_path.unlink()

    log("Chat App heruntergeladen!")

    # find chat.exe
    for path in INSTALL_DIR.rglob("chat.exe"):
        return path
    return None


def create_shortcut(target: Path, python: str):
    log("Desktop Shortcut wird erstellt...")
    try:
        import winshell
        from win32com.client import Dispatch
    except ImportError:
        subprocess.run([python, "-m", "pip", "install", "--quiet", "winshell", "pywin32"], check=True)
        import winshell
        from win32com.client import Dispatch

    shortcut_path = DESKTOP / "chat.lnk"
    shell = Dispatch("WScript.Shell")
    shortcut = shell.CreateShortCut(str(shortcut_path))
    shortcut.Targetpath = str(target)
    shortcut.WorkingDirectory = str(target.parent)
    shortcut.IconLocation = str(target)
    shortcut.save()
    log("Desktop Shortcut erstellt!")


def create_shortcut_py(python: str, client_py: Path):
    """Fallback shortcut that runs python client.py"""
    log("Desktop Shortcut wird erstellt...")
    bat_path = INSTALL_DIR / "start.bat"
    bat_path.write_text(f'@echo off\n"{python}" "{client_py}"\n')
    shortcut_path = DESKTOP / "chat.lnk"
    # use powershell to create shortcut
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

    # check python
    python = python_installed()
    if not python:
        install_python()
        python = python_installed()
        if not python:
            python = str(Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/Python/Python312/python.exe")

    log(f"Python gefunden: {python}")

    # install dependencies
    install_dependencies(python)

    # download chat
    chat_exe = download_chat()

    # create shortcut
    if chat_exe and chat_exe.exists():
        try:
            create_shortcut(chat_exe, python)
        except Exception:
            pass
        log("")
        log("Installation abgeschlossen!")
        log("Chat wird gestartet...")
        subprocess.Popen([str(chat_exe)])
    else:
        # fallback — run with python
        client_py = INSTALL_DIR / "client.py"
        if client_py.exists():
            create_shortcut_py(python, client_py)
            log("")
            log("Installation abgeschlossen!")
            log("Chat wird gestartet...")
            subprocess.Popen([python, str(client_py)])
        else:
            log("FEHLER: Chat konnte nicht installiert werden!")
            input("Enter drücken zum Beenden...")
            sys.exit(1)

    input("Enter drücken zum Beenden...")


if __name__ == "__main__":
    main()