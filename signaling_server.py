import asyncio
import json
import logging
import sys
import socket
import websockets
import os
import random
import string
from functools import lru_cache

# --- Logging Setup ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# --- Persistent Users ---
USERS_FILE = "users.json"
clients = {}            # username -> websocket
registered_users = {}   # username -> { code }

def load_users():
    if os.path.exists(USERS_FILE):
        with open(USERS_FILE, "r") as f:
            return json.load(f)
    return {}

def save_users():
    with open(USERS_FILE, "w") as f:
        json.dump(registered_users, f, indent=2)

def generate_user_code(length=6):
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))

@lru_cache(maxsize=1)
def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

HOST = get_local_ip()
PORT = 8765

async def broadcast_user_list():
    user_list = [
        {"name": name, "code": info["code"], "is_online": name in clients}
        for name, info in registered_users.items()
    ]
    message = json.dumps({"type": "user_list", "users": user_list})
    for ws in clients.values():
        try:
            await ws.send(message)
        except Exception as e:
            logger.warning(f"Failed sending user list to a client: {e}")

async def handler(websocket):
    username = None
    logger.info(f"🔌 New connection from {websocket.remote_address}")
    try:
        async for message in websocket:
            logger.info(f"📩 Message from {websocket.remote_address}: {message}")
            data = json.loads(message)
            msg_type = data.get("type")

            if msg_type == "register":
                username = data.get("name")
                if not username:
                    logger.warning("🔺 Register message without a name")
                    continue

                if username not in registered_users:
                    code = generate_user_code()
                    registered_users[username] = {"code": code}
                    save_users()
                    logger.info(f"✅ Registered new user '{username}' with code {code}")
                else:
                    logger.info(f"🔁 User '{username}' reconnected")

                clients[username] = websocket
                await broadcast_user_list()

                await websocket.send(json.dumps({
                    "type": "registered",
                    "name": username,
                    "code": registered_users[username]["code"]
                }))
                logger.info(f"📤 Sent registered info to '{username}'")

            elif msg_type in ("offer", "answer", "candidate"):
                frm = data.get("from")
                target = data.get("to")
                if target in clients:
                    logger.info(f"↔️ Forwarding {msg_type} from '{frm}' to '{target}'")
                    await clients[target].send(json.dumps(data))
                else:
                    logger.warning(f"❌ Attempted {msg_type} from '{frm}' to unknown/offline '{target}'")

            else:
                logger.warning(f"⚠️ Unknown message type: {msg_type}")

    except websockets.exceptions.ConnectionClosed:
        logger.info(f"❌ Connection closed for {username or websocket.remote_address}")
    finally:
        if username and registered_users and username in clients:
            logger.info(f"🔻 Removing offline user '{username}'")
            del clients[username]
            await broadcast_user_list()

async def main():
    global registered_users
    registered_users = load_users()
    logger.info(f"🚀 Starting signaling server at ws://{HOST}:{PORT}")
    async with websockets.serve(handler, HOST, PORT):
        await asyncio.Future()  # Run forever

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("🛑 Server stopped manually")
