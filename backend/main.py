# ============================================================
#  Remote HMI Connectivity System — FastAPI Backend (FIXED)
#  Supports ESP32 outbound WebSocket connection
# ============================================================

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import asyncio
import json
import logging
from typing import Optional
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Remote HMI Gateway", version="2.0.0")

# CORS – allow your frontend origins
ALLOWED_ORIGINS = [
    "http://localhost:5173",
    "https://laser-remote-control-1.onrender.com",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global state
esp32_websocket: Optional[WebSocket] = None
pending_requests = {}  # request_id -> asyncio.Future
request_counter = 0

connection_status = {
    "connected": False,
    "hmi_ip": None,
    "hmi_port": None,
    "esp32_ip": None,
    "connected_at": None,
    "message": "Not connected"
}

# Request models
class ConnectRequest(BaseModel):
    hmi_ip: str
    hmi_port: int
    esp32_ip: str   # kept for reference, not used for connection anymore
    esp32_port: int = 9000

class SendDataRequest(BaseModel):
    data: str


# ──────────────────────────────────────────────────────────
#  WebSocket for ESP32 (outbound connection from ESP32)
# ──────────────────────────────────────────────────────────
@app.websocket("/ws/esp32")
async def esp32_websocket_endpoint(websocket: WebSocket):
    global esp32_websocket, connection_status
    await websocket.accept()
    logger.info("ESP32 connected via WebSocket")
    esp32_websocket = websocket

    try:
        while True:
            # Wait for messages from ESP32
            raw = await websocket.receive_text()
            data = json.loads(raw)

            # Check if this is a response to a pending request
            req_id = data.get("request_id")
            if req_id and req_id in pending_requests:
                future = pending_requests.pop(req_id)
                future.set_result(data)
                continue

            # Otherwise, it's an unsolicited message (e.g., HMI event)
            logger.info(f"Unsolicited from ESP32: {data}")

    except WebSocketDisconnect:
        logger.warning("ESP32 WebSocket disconnected")
        esp32_websocket = None
        connection_status["connected"] = False
        connection_status["message"] = "ESP32 disconnected"


# ──────────────────────────────────────────────────────────
#  Helper: send command to ESP32 and wait for response
# ──────────────────────────────────────────────────────────
async def send_to_esp32(command: dict, timeout: float = 10.0):
    global request_counter
    if esp32_websocket is None:
        return {"success": False, "message": "ESP32 not connected"}

    request_counter += 1
    req_id = str(request_counter)
    command["request_id"] = req_id

    future = asyncio.Future()
    pending_requests[req_id] = future

    try:
        await esp32_websocket.send_text(json.dumps(command))
        response = await asyncio.wait_for(future, timeout=timeout)
        return {"success": True, "response": response}
    except asyncio.TimeoutError:
        pending_requests.pop(req_id, None)
        return {"success": False, "message": "ESP32 did not respond"}
    except Exception as e:
        pending_requests.pop(req_id, None)
        return {"success": False, "message": f"Error: {str(e)}"}


# ──────────────────────────────────────────────────────────
#  REST Endpoints
# ──────────────────────────────────────────────────────────
@app.get("/")
async def root():
    return {"status": "HMI Gateway is running", "version": "2.0.0"}

@app.get("/status")
async def get_status():
    return connection_status

@app.post("/connect")
async def connect(req: ConnectRequest):
    global connection_status

    if esp32_websocket is None:
        return {"success": False, "message": "ESP32 is not online"}

    # Send CONNECT command to ESP32
    cmd = {
        "cmd": "CONNECT",
        "hmi_ip": req.hmi_ip,
        "hmi_port": req.hmi_port
    }
    result = await send_to_esp32(cmd, timeout=15.0)

    if result["success"] and result["response"].get("status") == "OK":
        connection_status.update({
            "connected": True,
            "hmi_ip": req.hmi_ip,
            "hmi_port": req.hmi_port,
            "esp32_ip": req.esp32_ip,
            "connected_at": datetime.now().isoformat(),
            "message": f"Connected to HMI at {req.hmi_ip}:{req.hmi_port}"
        })
        return {"success": True, "message": "Connected", "status": connection_status}
    else:
        error_msg = result.get("response", {}).get("error", result.get("message", "Unknown error"))
        return {"success": False, "message": error_msg}

@app.post("/disconnect")
async def disconnect():
    global connection_status
    if esp32_websocket is None:
        return {"success": False, "message": "ESP32 not connected"}

    cmd = {"cmd": "DISCONNECT"}
    result = await send_to_esp32(cmd)

    if result["success"]:
        connection_status["connected"] = False
        connection_status["message"] = "Disconnected"
        return {"success": True, "message": "Disconnected"}
    else:
        return {"success": False, "message": result.get("message")}

@app.post("/send")
async def send_data(req: SendDataRequest):
    if not connection_status["connected"]:
        return {"success": False, "message": "Not connected to HMI"}
    if esp32_websocket is None:
        return {"success": False, "message": "ESP32 not connected"}

    cmd = {
        "cmd": "SEND",
        "data": req.data
    }
    result = await send_to_esp32(cmd, timeout=10.0)

    if result["success"]:
        return {"success": True, "response": result["response"]}
    else:
        return {"success": False, "message": result.get("message")}


# ──────────────────────────────────────────────────────────
#  WebSocket for frontend (status only)
# ──────────────────────────────────────────────────────────
@app.websocket("/ws")
async def frontend_websocket(websocket: WebSocket):
    origin = websocket.headers.get("origin")
    if origin not in ALLOWED_ORIGINS:
        await websocket.close(code=1008)
        return

    await websocket.accept()
    try:
        while True:
            await websocket.send_json(connection_status)
            await asyncio.sleep(2)
    except WebSocketDisconnect:
        pass


# ──────────────────────────────────────────────────────────
#  Startup / Shutdown
# ──────────────────────────────────────────────────────────
@app.on_event("startup")
async def startup_event():
    logger.info("HMI Gateway started. Waiting for ESP32 to connect via WebSocket...")

@app.on_event("shutdown")
async def shutdown_event():
    if esp32_websocket:
        await esp32_websocket.close()
    logger.info("Shutdown complete.")