"""
chat server - max 2 users, E2E encrypted
dependencies: pip install websockets cryptography
run: python server.py
"""

import asyncio
import json
import websockets

# max 2 clients: {websocket: {"username": str, "public_key": str}}
clients: dict = {}


async def broadcast(message: dict, sender=None):
    """Send message to all connected clients except sender."""
    data = json.dumps(message)
    targets = [ws for ws in clients if ws != sender]
    if targets:
        await asyncio.gather(*[ws.send(data) for ws in targets], return_exceptions=True)


async def handler(websocket):
    """Handle a single client connection."""
    username = None
    try:
        # reject if already 2 users connected
        if len(clients) >= 2:
            await websocket.send(json.dumps({
                "type": "error",
                "text": "server is full (max 2 users)"
            }))
            return

        # first message must be handshake with username + public key
        raw = await websocket.recv()
        msg = json.loads(raw)
        username = msg.get("username", "unknown").strip() or "unknown"
        public_key = msg.get("public_key", "")

        clients[websocket] = {"username": username, "public_key": public_key}
        print(f"[+] {username} connected  ({len(clients)}/2 online)")

        # send existing user's public key to new user (if someone already connected)
        for ws, data in clients.items():
            if ws != websocket and data["public_key"]:
                await websocket.send(json.dumps({
                    "type": "key_exchange",
                    "username": data["username"],
                    "public_key": data["public_key"]
                }))

        # send new user's public key to existing user
        await broadcast({
            "type": "key_exchange",
            "username": username,
            "public_key": public_key
        }, sender=websocket)

        # notify everyone
        await broadcast({"type": "system", "text": f"{username} joined"}, sender=websocket)
        await websocket.send(json.dumps({"type": "system", "text": f"welcome, {username}!"}))

        # if 2 users now connected - notify both chat is ready
        if len(clients) == 2:
            await broadcast({"type": "system", "text": "chat is now end-to-end encrypted. server is locked."})

        # main message loop - server only forwards encrypted blobs, never reads content
        async for raw in websocket:
            msg = json.loads(raw)
            msg_type = msg.get("type", "")  # ← das fehlt noch

            if msg_type == "message":
                packet = {
                    "type": "message",
                    "username": username,
                    "ciphertext": msg.get("ciphertext", ""),
                    "nonce": msg.get("nonce", "")
                }
                await broadcast(packet, sender=websocket)

            elif msg_type in ("webrtc_offer", "webrtc_answer", "webrtc_ice"):
                msg["username"] = username
                await broadcast(msg, sender=websocket)

    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        if websocket in clients:
            del clients[websocket]
        if username:
            print(f"[-] {username} disconnected  ({len(clients)}/2 online)")
            await broadcast({"type": "system", "text": f"{username} left — chat unlocked"})
            await broadcast({"type": "call_ended"})  # ← hier, nach username check


async def main():
    print("chat server starting on ws://localhost:8765")
    print("max 2 users — server never reads message content\n")
    async with websockets.serve(handler, "0.0.0.0", 8765, ping_interval=20, ping_timeout=10):
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())