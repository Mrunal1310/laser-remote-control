from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import asyncio
import json
import logging
from typing import Optional, Dict
from datetime import datetime
import uuid
from collections import deque

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Remote HMI Gateway", version="3.0.0")

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

command_queue = deque()
command_responses = {}
device_status = {"last_seen": None, "hmi_connected": False, "message": "Waiting for device"}
frontend_ws = None

class ConnectRequest(BaseModel):
    hmi_ip: str
    hmi_port: int

class SendDataRequest(BaseModel):
    data: str

class DeviceResponse(BaseModel):
    command_id: str
    success: bool
    response: Optional[dict] = None
    error: Optional[str] = None
    hmi_connected: Optional[bool] = None
    message: Optional[str] = None

async def notify_frontend(msg: dict):
    if frontend_ws:
        try:
            await frontend_ws.send_json(msg)
        except:
            pass

@app.post("/connect")
async def connect_hmi(req: ConnectRequest):
    cmd_id = str(uuid.uuid4())
    command_queue.append({"id": cmd_id, "type": "connect", "hmi_ip": req.hmi_ip, "hmi_port": req.hmi_port})
    return {"success": True, "command_id": cmd_id}

@app.post("/disconnect")
async def disconnect_hmi():
    cmd_id = str(uuid.uuid4())
    command_queue.append({"id": cmd_id, "type": "disconnect"})
    return {"success": True, "command_id": cmd_id}

@app.post("/start")
async def start():
    cmd_id = str(uuid.uuid4())
    command_queue.append({"id": cmd_id, "type": "start"})
    return {"success": True, "command_id": cmd_id}

@app.post("/stop")
async def stop():
    cmd_id = str(uuid.uuid4())
    command_queue.append({"id": cmd_id, "type": "stop"})
    return {"success": True, "command_id": cmd_id}

@app.post("/send")
async def send_data(req: SendDataRequest):
    cmd_id = str(uuid.uuid4())
    command_queue.append({"id": cmd_id, "type": "send", "data": req.data})
    return {"success": True, "command_id": cmd_id}

@app.get("/status")
async def get_status():
    return {
        "device_online": device_status["last_seen"] is not None,
        "hmi_connected": device_status["hmi_connected"],
        "message": device_status["message"]
    }

@app.get("/poll")
async def device_poll():
    if command_queue:
        cmd = command_queue.popleft()
        logger.info(f"Device picked {cmd['id']}")
        return {"command": cmd}
    return {"command": None}

@app.post("/device/response")
async def device_response(resp: DeviceResponse):
    command_responses[resp.command_id] = resp.dict()
    device_status["last_seen"] = datetime.now().isoformat()
    if resp.hmi_connected is not None:
        device_status["hmi_connected"] = resp.hmi_connected
    if resp.message:
        device_status["message"] = resp.message
    await notify_frontend({
        "type": "device_response",
        "command_id": resp.command_id,
        "success": resp.success,
        "response": resp.response
    })
    await notify_frontend({
        "type": "status",
        "esp32_online": True,
        "hmi_connected": device_status["hmi_connected"],
        "message": device_status["message"]
    })
    return {"status": "ok"}

@app.websocket("/ws/frontend")
async def websocket_frontend(websocket: WebSocket):
    global frontend_ws
    await websocket.accept()
    frontend_ws = websocket
    logger.info("Frontend WebSocket connected")
    await websocket.send_json({
        "type": "status",
        "esp32_online": device_status["last_seen"] is not None,
        "hmi_connected": device_status["hmi_connected"],
        "message": device_status["message"]
    })
    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        frontend_ws = None
        logger.info("Frontend WebSocket disconnected")