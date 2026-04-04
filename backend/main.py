# ============================================================
#  Remote HMI Connectivity System — FastAPI Backend
#  File: main.py
#  Deploy this on Render.com
# ============================================================

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import asyncio
import socket
import json
import logging
from typing import Optional
from datetime import datetime

# ── Logging ─────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── App setup ───────────────────────────────────────────────
app = FastAPI(title="Remote HMI Gateway", version="1.0.1")

# ── Allowed Origins ─────────────────────────────────────────
# Your frontend URLs
ALLOWED_ORIGINS = [
    "http://localhost:5173",
    "https://laser-remote-control-1.onrender.com",
]

# CORS Middleware for REST API endpoints
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Global state ────────────────────────────────────────────
esp32_connection: Optional[socket.socket] = None
esp32_writer: Optional[asyncio.StreamWriter] = None
esp32_reader: Optional[asyncio.StreamReader] = None

connection_status = {
    "connected": False,
    "hmi_ip": None,
    "hmi_port": None,
    "esp32_ip": None,
    "connected_at": None,
    "message": "Not connected"
}

# ── Request models ───────────────────────────────────────────
class ConnectRequest(BaseModel):
    hmi_ip: str
    hmi_port: int
    esp32_ip: str
    esp32_port: int = 9000

class SendDataRequest(BaseModel):
    data: str


# ── Helper: connect to ESP32 over TCP ───────────────────────
async def connect_to_esp32(esp32_ip: str, esp32_port: int, hmi_ip: str, hmi_port: int):
    global esp32_reader, esp32_writer, connection_status

    try:
        logger.info(f"Connecting to ESP32 at {esp32_ip}:{esp32_port}")

        esp32_reader, esp32_writer = await asyncio.wait_for(
            asyncio.open_connection(esp32_ip, esp32_port),
            timeout=10.0
        )

        handshake = json.dumps({
            "cmd": "CONNECT",
            "hmi_ip": hmi_ip,
            "hmi_port": hmi_port
        }) + "\n"

        esp32_writer.write(handshake.encode())
        await esp32_writer.drain()

        response_line = await asyncio.wait_for(esp32_reader.readline(), timeout=10.0)
        response = json.loads(response_line.decode().strip())

        if response.get("status") == "OK":
            connection_status.update({
                "connected": True,
                "hmi_ip": hmi_ip,
                "hmi_port": hmi_port,
                "esp32_ip": esp32_ip,
                "connected_at": datetime.now().isoformat(),
                "message": f"Connected to HMI at {hmi_ip}:{hmi_port} via ESP32"
            })
            logger.info("ESP32 acknowledged connection to HMI")
            return True, "Connected successfully"

        error_msg = response.get("error", "ESP32 rejected connection")
        return False, error_msg

    except asyncio.TimeoutError:
        return False, "Timeout: ESP32 did not respond. Check if ESP32 is online."
    except ConnectionRefusedError:
        return False, f"Connection refused at {esp32_ip}:{esp32_port}. Is ESP32 listening?"
    except Exception as e:
        return False, f"Connection error: {str(e)}"


async def disconnect_from_esp32():
    global esp32_reader, esp32_writer, connection_status

    if esp32_writer:
        try:
            disconnect_msg = json.dumps({"cmd": "DISCONNECT"}) + "\n"
            esp32_writer.write(disconnect_msg.encode())
            await esp32_writer.drain()

            esp32_writer.close()
            await esp32_writer.wait_closed()

        except Exception as e:
            logger.warning(f"Error during disconnect: {e}")

        finally:
            esp32_writer = None
            esp32_reader = None

    connection_status.update({
        "connected": False,
        "hmi_ip": None,
        "hmi_port": None,
        "esp32_ip": None,
        "connected_at": None,
        "message": "Disconnected"
    })


# ── API Endpoints ────────────────────────────────────────────

@app.get("/")
async def root():
    return {"status": "HMI Gateway is running", "version": "1.0.1"}


@app.get("/status")
async def get_status():
    return connection_status


@app.post("/connect")
async def connect(req: ConnectRequest):
    global connection_status

    if connection_status["connected"]:
        await disconnect_from_esp32()

    success, message = await connect_to_esp32(
        req.esp32_ip, req.esp32_port,
        req.hmi_ip, req.hmi_port
    )

    return {
        "success": success,
        "message": message,
        "status": connection_status
    }


@app.post("/disconnect")
async def disconnect():
    if not connection_status["connected"]:
        return {"success": True, "message": "Already disconnected"}

    await disconnect_from_esp32()
    return {
        "success": True,
        "message": "Disconnected from HMI",
        "status": connection_status
    }


@app.post("/send")
async def send_data(req: SendDataRequest):
    if not connection_status["connected"] or not esp32_writer:
        return {"success": False, "message": "Not connected. Please connect first."}

    try:
        message = json.dumps({"cmd": "SEND", "data": req.data}) + "\n"
        esp32_writer.write(message.encode())
        await esp32_writer.drain()

        response_line = await asyncio.wait_for(esp32_reader.readline(), timeout=5.0)
        response = json.loads(response_line.decode().strip())

        return {"success": True, "response": response}

    except asyncio.TimeoutError:
        return {"success": False, "message": "Timeout waiting for HMI response"}
    except Exception as e:
        return {"success": False, "message": f"Send error: {str(e)}"}


# ── WebSocket for real-time status updates ──────────────────
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    Allows WebSocket connections only from trusted origins.
    Prevents 403 errors due to origin rejection.
    """

    origin = websocket.headers.get("origin")
    logger.info(f"WebSocket connection attempt from Origin: {origin}")

    # Allow React dev + your Render frontend/backend
    if origin not in ALLOWED_ORIGINS:
        logger.warning(f"WebSocket blocked from origin: {origin}")
        await websocket.close(code=1008)
        return

    await websocket.accept()
    logger.info("WebSocket client connected")

    try:
        while True:
            await websocket.send_json(connection_status)
            await asyncio.sleep(2)

    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected")


# ── Startup / Shutdown ───────────────────────────────────────
@app.on_event("startup")
async def startup_event():
    logger.info("HMI Gateway started. Waiting for connections...")


@app.on_event("shutdown")
async def shutdown_event():
    await disconnect_from_esp32()
    logger.info("HMI Gateway shut down cleanly.")