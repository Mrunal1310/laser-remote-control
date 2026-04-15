from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import datetime
import uuid

app = FastAPI(title="HMI Polling Gateway", version="5.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------
# Global Memory (Simple queue)
# ---------------------------------------------------------
pending_command = None
last_response = None
esp32_last_seen = None


# ---------------------------------------------------------
# Models
# ---------------------------------------------------------
class UICommand(BaseModel):
    cmd: str
    hmi_ip: str = None
    hmi_port: int = None
    data: str = None


class ESP32Response(BaseModel):
    request_id: str
    status: str
    response: str


# ---------------------------------------------------------
# UI API (React will call this)
# ---------------------------------------------------------
@app.post("/api/ui_command")
def ui_command(req: UICommand):
    global pending_command

    request_id = str(uuid.uuid4())[:8]

    pending_command = {
        "cmd": req.cmd,
        "request_id": request_id,
        "hmi_ip": req.hmi_ip,
        "hmi_port": req.hmi_port,
        "data": req.data,
        "created_at": datetime.now().isoformat()
    }

    return {"success": True, "message": "Command queued", "request_id": request_id}


# ---------------------------------------------------------
# ESP32 Poll API
# ESP32 will call this every 2 seconds
# ---------------------------------------------------------
@app.get("/api/poll")
def poll():
    global pending_command, esp32_last_seen

    esp32_last_seen = datetime.now().isoformat()

    if pending_command is None:
        return {"cmd": ""}

    cmd = pending_command
    pending_command = None
    return cmd


# ---------------------------------------------------------
# ESP32 Response API
# ESP32 sends execution result here
# ---------------------------------------------------------
@app.post("/api/response")
def response(req: ESP32Response):
    global last_response

    last_response = {
        "request_id": req.request_id,
        "status": req.status,
        "response": req.response,
        "received_at": datetime.now().isoformat()
    }

    return {"success": True}


# ---------------------------------------------------------
# UI checks response
# ---------------------------------------------------------
@app.get("/api/get_response")
def get_response(request_id: str):
    if last_response and last_response["request_id"] == request_id:
        return {"success": True, "data": last_response}

    return {"success": False, "message": "No response yet"}


# ---------------------------------------------------------
# Status API
# ---------------------------------------------------------
@app.get("/api/status")
def status():
    return {
        "esp32_last_seen": esp32_last_seen,
        "pending_command": pending_command,
        "last_response": last_response
    }


@app.get("/")
def root():
    return {"status": "HMI Polling Gateway Running", "version": "5.0"}