from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import asyncio
import json
import logging
from typing import Optional, Dict
from datetime import datetime
import uuid

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Remote HMI Gateway", version="2.0.0")

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

# Store connected clients
class ConnectionManager:
    def __init__(self):
        self.frontend_ws: Optional[WebSocket] = None
        self.device_ws: Optional[WebSocket] = None
        self.device_ready = False
        self.pending_commands: Dict[str, asyncio.Future] = {}

    async def connect_frontend(self, websocket: WebSocket):
        await websocket.accept()
        self.frontend_ws = websocket
        logger.info("Frontend WebSocket connected")

    async def connect_device(self, websocket: WebSocket):
        await websocket.accept()
        self.device_ws = websocket
        self.device_ready = True
        logger.info("Device WebSocket connected")
        # Send initial status request to device
        await self.send_to_device({"type": "ping"})

    def disconnect_frontend(self):
        self.frontend_ws = None
        logger.info("Frontend WebSocket disconnected")

    def disconnect_device(self):
        self.device_ws = None
        self.device_ready = False
        logger.info("Device WebSocket disconnected")

    async def send_to_frontend(self, message: dict):
        if self.frontend_ws:
            try:
                await self.frontend_ws.send_json(message)
            except:
                self.disconnect_frontend()

    async def send_to_device(self, message: dict):
        if self.device_ws and self.device_ready:
            try:
                await self.device_ws.send_json(message)
                return True
            except:
                self.disconnect_device()
                return False
        return False

    async def send_command_and_wait(self, command: dict, timeout: float = 10.0) -> dict:
        """Send a command to device and wait for response."""
        cmd_id = str(uuid.uuid4())
        command["id"] = cmd_id
        future = asyncio.get_event_loop().create_future()
        self.pending_commands[cmd_id] = future
        try:
            sent = await self.send_to_device(command)
            if not sent:
                raise Exception("Device not connected")
            result = await asyncio.wait_for(future, timeout)
            return result
        finally:
            self.pending_commands.pop(cmd_id, None)

    def resolve_command(self, cmd_id: str, response: dict):
        if cmd_id in self.pending_commands:
            self.pending_commands[cmd_id].set_result(response)

manager = ConnectionManager()

# --- HTTP endpoints for frontend ---
class ConnectRequest(BaseModel):
    hmi_ip: str
    hmi_port: int

class SendDataRequest(BaseModel):
    data: str

@app.post("/connect")
async def connect_hmi(req: ConnectRequest):
    if not manager.device_ready:
        return {"success": False, "message": "ESP32 device not connected via WebSocket"}
    try:
        result = await manager.send_command_and_wait({
            "type": "connect",
            "hmi_ip": req.hmi_ip,
            "hmi_port": req.hmi_port
        })
        return {"success": result.get("success", False), "message": result.get("message", ""), "response": result}
    except Exception as e:
        return {"success": False, "message": str(e)}

@app.post("/disconnect")
async def disconnect_hmi():
    if not manager.device_ready:
        return {"success": False, "message": "Device not connected"}
    try:
        result = await manager.send_command_and_wait({"type": "disconnect"})
        return {"success": result.get("success", False), "message": result.get("message", "")}
    except Exception as e:
        return {"success": False, "message": str(e)}

@app.post("/start")
async def start():
    if not manager.device_ready:
        return {"success": False, "message": "Device not connected"}
    try:
        result = await manager.send_command_and_wait({"type": "start"})
        return {"success": result.get("success", False), "response": result.get("response")}
    except Exception as e:
        return {"success": False, "message": str(e)}

@app.post("/stop")
async def stop():
    if not manager.device_ready:
        return {"success": False, "message": "Device not connected"}
    try:
        result = await manager.send_command_and_wait({"type": "stop"})
        return {"success": result.get("success", False), "response": result.get("response")}
    except Exception as e:
        return {"success": False, "message": str(e)}

@app.post("/send")
async def send_data(req: SendDataRequest):
    if not manager.device_ready:
        return {"success": False, "message": "Device not connected"}
    try:
        result = await manager.send_command_and_wait({"type": "send", "data": req.data})
        return {"success": result.get("success", False), "response": result.get("response")}
    except Exception as e:
        return {"success": False, "message": str(e)}

@app.get("/status")
async def get_status():
    # Return current known status (can be extended)
    return {"device_online": manager.device_ready}

# --- WebSocket endpoints ---
@app.websocket("/ws/frontend")
async def websocket_frontend(websocket: WebSocket):
    await manager.connect_frontend(websocket)
    try:
        while True:
            # Keep connection alive, optionally receive pings from frontend
            data = await websocket.receive_text()
            # Frontend may send heartbeat
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        manager.disconnect_frontend()

@app.websocket("/ws/device")
async def websocket_device(websocket: WebSocket):
    await manager.connect_device(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)
            # Handle responses from device
            if "id" in message and "response" in message:
                manager.resolve_command(message["id"], message["response"])
                # Also forward to frontend for live updates
                await manager.send_to_frontend({
                    "type": "device_response",
                    "data": message["response"]
                })
            elif message.get("type") == "status":
                # Device reports its status (ESP32 online, HMI connected, etc.)
                await manager.send_to_frontend({
                    "type": "status",
                    "esp32_online": True,
                    "hmi_connected": message.get("hmi_connected", False),
                    "message": message.get("message", "")
                })
    except WebSocketDisconnect:
        manager.disconnect_device()

@app.on_event("startup")
async def startup():
    logger.info("HMI Gateway v2 started")

@app.on_event("shutdown")
async def shutdown():
    if manager.device_ws:
        await manager.device_ws.close()