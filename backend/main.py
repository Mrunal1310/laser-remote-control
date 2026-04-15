from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import datetime, timezone
import uuid

app = FastAPI(title="HMI Polling Gateway", version="6.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------
# Global Memory
# ---------------------------------------------------------
pending_command = None      # Command waiting for ESP32 to pick up
last_response   = None      # Last response from ESP32
esp32_last_seen = None      # Timestamp of last ESP32 poll
hmi_connected   = False     # Updated by ESP32 response after CONNECT/DISCONNECT


# ---------------------------------------------------------
# Models
# ---------------------------------------------------------
class UICommand(BaseModel):
    cmd: str
    hmi_ip: str   = None
    hmi_port: int = None
    data: str     = None


class ESP32Response(BaseModel):
    request_id: str
    status: str
    response: str
    hmi_connected: bool = False   # ESP32 reports its HMI socket state


# ---------------------------------------------------------
# UI → Backend: queue a command
# POST /api/ui_command
# Body: { cmd, hmi_ip, hmi_port, data }
# Returns: { success, request_id }
# ---------------------------------------------------------
@app.post("/api/ui_command")
def ui_command(req: UICommand):
    global pending_command

    request_id = str(uuid.uuid4())[:8]

    pending_command = {
        "cmd":        req.cmd,
        "request_id": request_id,
        "hmi_ip":     req.hmi_ip,
        "hmi_port":   req.hmi_port,
        "data":       req.data,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    return {"success": True, "message": "Command queued", "request_id": request_id}


# ---------------------------------------------------------
# ESP32 → Backend: poll for next command
# GET /api/poll
# Returns: pending command dict, or { "cmd": "" } if nothing pending
# ---------------------------------------------------------
@app.get("/api/poll")
def poll():
    global pending_command, esp32_last_seen

    esp32_last_seen = datetime.now(timezone.utc).isoformat()

    if pending_command is None:
        return {"cmd": ""}

    cmd = pending_command
    pending_command = None      # clear — command handed off
    return cmd


# ---------------------------------------------------------
# ESP32 → Backend: submit execution result
# POST /api/response
# Body: { request_id, status, response, hmi_connected }
# ---------------------------------------------------------
@app.post("/api/response")
def esp32_response(req: ESP32Response):
    global last_response, hmi_connected

    last_response = {
        "request_id":   req.request_id,
        "status":       req.status,
        "response":     req.response,
        "received_at":  datetime.now(timezone.utc).isoformat(),
    }

    # Keep HMI state in sync (ESP32 reports truth)
    hmi_connected = req.hmi_connected

    return {"success": True}


# ---------------------------------------------------------
# UI → Backend: poll for result of a specific command
# GET /api/get_response?request_id=<id>
# Returns: { success, data } or { success: false }
# ---------------------------------------------------------
@app.get("/api/get_response")
def get_response(request_id: str):
    if last_response and last_response["request_id"] == request_id:
        return {"success": True, "data": last_response}
    return {"success": False, "message": "No response yet"}


# ---------------------------------------------------------
# UI → Backend: overall system status
# GET /api/status
# Returns esp32_online (derived from last_seen < 10 s), hmi_connected, etc.
# ---------------------------------------------------------
@app.get("/api/status")
def status():
    esp32_online = False
    if esp32_last_seen:
        last = datetime.fromisoformat(esp32_last_seen)
        # Make both timezone-aware for comparison
        now = datetime.now(timezone.utc)
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        diff = (now - last).total_seconds()
        esp32_online = diff < 10      # ESP32 polls every 2 s; 10 s = 5 missed polls

    return {
        "esp32_online":    esp32_online,
        "esp32_last_seen": esp32_last_seen,
        "hmi_connected":   hmi_connected,
        "pending_command": pending_command,
        "last_response":   last_response,
    }


@app.get("/")
def root():
    return {"status": "HMI Polling Gateway Running", "version": "6.0"}