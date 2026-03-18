"""
chat client - E2E encrypted, 2 user max, WebRTC voice chat
Linux + Windows + macOS
dependencies: pip install customtkinter websockets cryptography requests aiortc
run: python client.py
"""

import asyncio
import base64
import json
import os
import platform
import stat
import subprocess
import sys
import tempfile
import threading
import requests
import websockets

import customtkinter as ctk

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from aiortc import RTCPeerConnection, RTCSessionDescription, RTCIceCandidate
from aiortc.contrib.media import MediaPlayer, MediaBlackhole


# ── config ────────────────────────────────────────────────────────────────────

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

CURRENT_VERSION = "1.1.1"
GITHUB_RELEASES = "https://api.github.com/repos/Streamskill/chat-app/releases/latest"
DEFAULT_SERVER = "localhost:8765"


# ── crypto ────────────────────────────────────────────────────────────────────

def derive_key(shared_secret: bytes, extra_key: str) -> bytes:
    salt = extra_key.encode() if extra_key else b"chatapp-default-salt"
    hkdf = HKDF(algorithm=hashes.SHA256(), length=32, salt=salt, info=b"chatapp-v1")
    return hkdf.derive(shared_secret)


def encrypt(key: bytes, plaintext: str) -> tuple[str, str]:
    nonce = os.urandom(12)
    aesgcm = AESGCM(key)
    ciphertext = aesgcm.encrypt(nonce, plaintext.encode(), None)
    return base64.b64encode(ciphertext).decode(), base64.b64encode(nonce).decode()


def decrypt(key: bytes, ciphertext_b64: str, nonce_b64: str) -> str:
    try:
        aesgcm = AESGCM(key)
        ciphertext = base64.b64decode(ciphertext_b64)
        nonce = base64.b64decode(nonce_b64)
        return aesgcm.decrypt(nonce, ciphertext, None).decode()
    except Exception:
        return "⚠ could not decrypt message"


# ── mic helper ────────────────────────────────────────────────────────────────

def get_mic():
    system = platform.system()
    if system == "Linux":
        return MediaPlayer("default", format="pulse")
    elif system == "Windows":
        return MediaPlayer("audio=default", format="dshow")
    elif system == "Darwin":
        return MediaPlayer("default:none", format="avfoundation")
    return None


# ── app ───────────────────────────────────────────────────────────────────────

class ChatApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("chat")
        self.geometry("500x700")
        self.resizable(True, True)

        # state
        self.websocket = None
        self.username = None
        self.extra_key = ""
        self.server_uri = ""
        self.loop = None
        self.session_key = None
        self._download_url = None

        # webrtc
        self.pc = None
        self.in_call = False

        # crypto
        self.private_key = X25519PrivateKey.generate()
        self.public_key_bytes = self.private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)

        self._build_login()
        threading.Thread(target=self._check_update, daemon=True).start()

    # ── update ────────────────────────────────────────────────────────────────

    def _check_update(self):
        try:
            r = requests.get(GITHUB_RELEASES, timeout=5)
            data = r.json()
            latest = data.get("tag_name", "").lstrip("v")
            if not latest or latest == CURRENT_VERSION:
                return
            is_windows = platform.system() == "Windows"
            for asset in data.get("assets", []):
                name = asset["name"].lower()
                if is_windows and name.endswith(".exe"):
                    self._download_url = asset["browser_download_url"]
                    break
                elif not is_windows and "linux" in name:
                    self._download_url = asset["browser_download_url"]
                    break
            if self._download_url:
                self.after(0, self._enable_update_button, latest)
        except Exception:
            pass

    def _enable_update_button(self, latest: str):
        self.update_btn.configure(
            text=f"⬆  update v{latest}",
            state="normal",
            fg_color="#4a9e3f",
            hover_color="#3d8a34"
        )

    def _do_update(self):
        if not self._download_url:
            return
        try:
            self.after(0, lambda: self.update_btn.configure(text="downloading...", state="disabled"))
            r = requests.get(self._download_url, stream=True, timeout=60)
            r.raise_for_status()
            suffix = ".exe" if platform.system() == "Windows" else ""
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
            for chunk in r.iter_content(chunk_size=8192):
                tmp.write(chunk)
            tmp.close()
            if platform.system() != "Windows":
                os.chmod(tmp.name, os.stat(tmp.name).st_mode | stat.S_IEXEC)
            current_exe = sys.executable if getattr(sys, "frozen", False) else sys.argv[0]
            if platform.system() == "Windows":
                bat = tempfile.NamedTemporaryFile(delete=False, suffix=".bat", mode="w")
                bat.write(f'@echo off\ntimeout /t 2 /nobreak >nul\nmove /y "{tmp.name}" "{current_exe}"\nstart "" "{current_exe}"\ndel "%~f0"\n')
                bat.close()
                subprocess.Popen(["cmd", "/c", bat.name], creationflags=0x08000000)
            else:
                os.replace(tmp.name, current_exe)
                subprocess.Popen([current_exe] + sys.argv[1:])
            self.after(0, self.destroy)
        except Exception:
            self.after(0, lambda: self.update_btn.configure(text="update failed", state="disabled", fg_color="red"))

    # ── login screen ──────────────────────────────────────────────────────────

    def _build_login(self):
        self.login_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.login_frame.place(relx=0.5, rely=0.5, anchor="center")

        ctk.CTkLabel(self.login_frame, text="chat", font=ctk.CTkFont(size=28, weight="bold")).pack(pady=(0, 24))

        ctk.CTkLabel(self.login_frame, text="server IP", anchor="w", width=320).pack(fill="x")
        self.server_entry = ctk.CTkEntry(self.login_frame, width=320, placeholder_text="192.168.1.42:8765")
        self.server_entry.insert(0, DEFAULT_SERVER)
        self.server_entry.pack(pady=(2, 12))

        ctk.CTkLabel(self.login_frame, text="username", anchor="w", width=320).pack(fill="x")
        self.name_entry = ctk.CTkEntry(self.login_frame, width=320, placeholder_text="your name")
        self.name_entry.pack(pady=(2, 12))

        ctk.CTkLabel(self.login_frame, text="shared key  (both users must enter the same)", anchor="w", width=320, text_color="gray").pack(fill="x")
        self.key_entry = ctk.CTkEntry(self.login_frame, width=320, placeholder_text="optional extra key", show="•")
        self.key_entry.pack(pady=(2, 20))
        self.key_entry.bind("<Return>", lambda e: self._on_join())

        ctk.CTkButton(self.login_frame, text="connect", width=320, height=38, command=self._on_join).pack()

        self.update_btn = ctk.CTkButton(
            self.login_frame, text="up to date",
            width=320, height=32,
            fg_color="gray25", hover_color="gray25",
            text_color="gray50", state="disabled",
            command=lambda: threading.Thread(target=self._do_update, daemon=True).start()
        )
        self.update_btn.pack(pady=(8, 0))

        self.login_error = ctk.CTkLabel(self.login_frame, text="", text_color="#ff6b6b")
        self.login_error.pack(pady=(8, 0))

    # ── chat screen ───────────────────────────────────────────────────────────

    def _build_chat(self):
        self.login_frame.destroy()

        header = ctk.CTkFrame(self, height=44, corner_radius=0)
        header.pack(fill="x", side="top")
        header.pack_propagate(False)

        self.status_label = ctk.CTkLabel(header, text="chat  •  waiting for other user...", font=ctk.CTkFont(size=13))
        self.status_label.pack(side="left", padx=14)

        self.msg_frame = ctk.CTkScrollableFrame(self, corner_radius=0)
        self.msg_frame.pack(fill="both", expand=True)

        input_bar = ctk.CTkFrame(self, height=52, corner_radius=0)
        input_bar.pack(fill="x", side="bottom")
        input_bar.pack_propagate(False)

        self.call_btn = ctk.CTkButton(
            input_bar, text="📞",
            width=44, height=32,
            fg_color="#4a9e3f", hover_color="#3d8a34",
            command=self._on_call
        )
        self.call_btn.pack(side="left", padx=(10, 4), pady=10)

        self.msg_entry = ctk.CTkEntry(input_bar, placeholder_text="type a message...", state="disabled")
        self.msg_entry.pack(side="left", fill="x", expand=True, padx=(4, 6), pady=10)
        self.msg_entry.bind("<Return>", lambda e: self._on_send())

        ctk.CTkButton(input_bar, text="send", width=70, height=32, command=self._on_send).pack(side="right", padx=(0, 10), pady=10)

    # ── messages ──────────────────────────────────────────────────────────────

    def _add_message(self, username: str, text: str, is_system=False, is_self=False):
        row = ctk.CTkFrame(self.msg_frame, fg_color="transparent")
        row.pack(fill="x", pady=1)

        if is_system:
            ctk.CTkLabel(row, text=text, text_color="gray", font=ctk.CTkFont(size=11)).pack(anchor="center", pady=2)
        else:
            anchor = "e" if is_self else "w"
            ctk.CTkLabel(
                row, text=username,
                font=ctk.CTkFont(size=11, weight="bold"),
                text_color="#4da6ff" if is_self else "#aaaaaa"
            ).pack(anchor=anchor, padx=10)
            ctk.CTkLabel(
                row, text=text,
                wraplength=340,
                justify="right" if is_self else "left",
                font=ctk.CTkFont(size=13)
            ).pack(anchor=anchor, padx=10)

        self.after(50, lambda: self.msg_frame._parent_canvas.yview_moveto(1.0))

    # ── events ────────────────────────────────────────────────────────────────

    def _on_join(self):
        username = self.name_entry.get().strip()
        server = self.server_entry.get().strip() or DEFAULT_SERVER
        if not username:
            self.login_error.configure(text="please enter a name")
            return
        if not server.startswith("ws://"):
            server = f"ws://{server}"
        self.server_uri = server
        self.username = username
        self.extra_key = self.key_entry.get().strip()
        self._build_chat()
        self._start_ws_thread()

    def _on_send(self):
        text = self.msg_entry.get().strip()
        if not text or not self.websocket or not self.session_key:
            return
        self.msg_entry.delete(0, "end")
        asyncio.run_coroutine_threadsafe(self._send(text), self.loop)

    def _on_call(self):
        if self.in_call:
            asyncio.run_coroutine_threadsafe(self._end_call(), self.loop)
        else:
            asyncio.run_coroutine_threadsafe(self._start_call(), self.loop)

    # ── webrtc ────────────────────────────────────────────────────────────────

    async def _start_call(self):
        self.pc = RTCPeerConnection()
        mic = get_mic()
        if mic:
            self.pc.addTrack(mic.audio)

        @self.pc.on("icecandidate")
        async def on_ice(candidate):
            if candidate:
                await self.websocket.send(json.dumps({
                    "type": "webrtc_ice",
                    "candidate": candidate.to_sdp(),
                    "sdpMid": candidate.sdpMid,
                    "sdpMLineIndex": candidate.sdpMLineIndex
                }))

        offer = await self.pc.createOffer()
        await self.pc.setLocalDescription(offer)
        await self.websocket.send(json.dumps({
            "type": "webrtc_offer",
            "sdp": offer.sdp,
            "sdpType": offer.type
        }))

        self.in_call = True
        self.after(0, lambda: self.call_btn.configure(text="📵", fg_color="#e74c3c", hover_color="#c0392b"))
        self.after(0, self._add_message, "", "📞 calling...", True, False)

    async def _handle_offer(self, msg: dict):
        self.pc = RTCPeerConnection()
        mic = get_mic()
        if mic:
            self.pc.addTrack(mic.audio)

        @self.pc.on("icecandidate")
        async def on_ice(candidate):
            if candidate:
                await self.websocket.send(json.dumps({
                    "type": "webrtc_ice",
                    "candidate": candidate.to_sdp(),
                    "sdpMid": candidate.sdpMid,
                    "sdpMLineIndex": candidate.sdpMLineIndex
                }))

        @self.pc.on("track")
        async def on_track(track):
            recorder = MediaBlackhole()
            recorder.addTrack(track)
            await recorder.start()

        await self.pc.setRemoteDescription(RTCSessionDescription(sdp=msg["sdp"], type=msg["sdpType"]))
        answer = await self.pc.createAnswer()
        await self.pc.setLocalDescription(answer)
        await self.websocket.send(json.dumps({
            "type": "webrtc_answer",
            "sdp": answer.sdp,
            "sdpType": answer.type
        }))

        self.in_call = True
        self.after(0, lambda: self.call_btn.configure(text="📵", fg_color="#e74c3c", hover_color="#c0392b"))
        self.after(0, self._add_message, "", "📞 call connected", True, False)

    async def _handle_answer(self, msg: dict):
        await self.pc.setRemoteDescription(RTCSessionDescription(sdp=msg["sdp"], type=msg["sdpType"]))
        self.after(0, self._add_message, "", "📞 call connected", True, False)

    async def _handle_ice(self, msg: dict):
        if self.pc:
            candidate = RTCIceCandidate(
                sdpMid=msg["sdpMid"],
                sdpMLineIndex=msg["sdpMLineIndex"],
                candidate=msg["candidate"]
            )
            await self.pc.addIceCandidate(candidate)

    async def _end_call(self):
        if self.pc:
            await self.pc.close()
            self.pc = None
        self.in_call = False
        self.after(0, lambda: self.call_btn.configure(text="📞", fg_color="#4a9e3f", hover_color="#3d8a34"))
        self.after(0, self._add_message, "", "📵 call ended", True, False)

    # ── key exchange ──────────────────────────────────────────────────────────

    def _handle_key_exchange(self, msg: dict):
        try:
            their_public_key = X25519PublicKey.from_public_bytes(base64.b64decode(msg["public_key"]))
            shared_secret = self.private_key.exchange(their_public_key)
            self.session_key = derive_key(shared_secret, self.extra_key)
            name = msg["username"]
            self.after(0, lambda: self.msg_entry.configure(state="normal"))
            self.after(0, lambda: self.msg_entry.focus())
            self.after(0, lambda: self.status_label.configure(text=f"chat  •  🔒 encrypted with {name}"))
            self.after(0, self._add_message, "", "🔒 end-to-end encrypted — server sees nothing", True, False)
        except Exception as e:
            self.after(0, self._add_message, "", f"⚠ key exchange failed: {e}", True, False)

    # ── websocket ─────────────────────────────────────────────────────────────

    def _start_ws_thread(self):
        def run():
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            self.loop.run_until_complete(self._connect())
        threading.Thread(target=run, daemon=True).start()

    async def _connect(self):
        try:
            async with websockets.connect(self.server_uri) as ws:
                self.websocket = ws
                await ws.send(json.dumps({
                    "username": self.username,
                    "public_key": base64.b64encode(self.public_key_bytes).decode()
                }))
                async for raw in ws:
                    msg = json.loads(raw)
                    t = msg.get("type", "")
                    if t == "error":
                        self.after(0, self._add_message, "", f"✗ {msg['text']}", True, False)
                    elif t == "system":
                        self.after(0, self._add_message, "", msg["text"], True, False)
                    elif t == "key_exchange":
                        self._handle_key_exchange(msg)
                    elif t == "message":
                        plaintext = decrypt(self.session_key, msg["ciphertext"], msg["nonce"]) if self.session_key else "⚠ received message before key exchange"
                        is_self = msg["username"] == self.username
                        self.after(0, self._add_message, msg["username"], plaintext, False, is_self)
                    elif t == "webrtc_offer":
                        asyncio.run_coroutine_threadsafe(self._handle_offer(msg), self.loop)
                    elif t == "webrtc_answer":
                        asyncio.run_coroutine_threadsafe(self._handle_answer(msg), self.loop)
                    elif t == "webrtc_ice":
                        asyncio.run_coroutine_threadsafe(self._handle_ice(msg), self.loop)
                    elif t == "call_ended":
                        asyncio.run_coroutine_threadsafe(self._end_call(), self.loop)
        except Exception as e:
            self.after(0, self._add_message, "", f"connection error: {e}", True, False)

    async def _send(self, text: str):
        if self.websocket and self.session_key:
            ciphertext, nonce = encrypt(self.session_key, text)
            await self.websocket.send(json.dumps({"ciphertext": ciphertext, "nonce": nonce}))
            self.after(0, self._add_message, self.username, text, False, True)


if __name__ == "__main__":
    app = ChatApp()
    app.mainloop()