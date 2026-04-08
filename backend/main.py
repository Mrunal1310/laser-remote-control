from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import asyncio
import json
import logging
import uvicorn
from typing import Optional
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("HMI-GATEWAY")

app = FastAPI(title="Remote HMI Gateway", version="4.4.0")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global state
esp32_websocket: Optional[WebSocket] = None
pending_requests: dict = {}
request_counter: int = 0

connection_status = {
    "esp32_connected": False,
    "hmi_connected":   False,
    "hmi_ip":          None,
    "hmi_port":        None,
    "connected_at":    None,
    "last_ping":       None,
    "message":         "ESP32 offline",
}

# Models
class ConnectRequest(BaseModel):
    hmi_ip:   str
    hmi_port: int

class SetTargetRequest(BaseModel):
    hmi_ip:   str
    hmi_port: int

class SendDataRequest(BaseModel):
    data: str

# ------------------------------------------------------------
# ESP32 WebSocket
# ------------------------------------------------------------
@app.websocket("/ws/esp32")
async def esp32_ws(websocket: WebSocket):
    global esp32_websocket, connection_status

    await websocket.accept()
    esp32_websocket = websocket
    connection_status["esp32_connected"] = True
    connection_status["message"] = "ESP32 online"
    logger.info("✓ ESP32 WebSocket connected from %s", websocket.client)

    try:
        while True:
            raw = await websocket.receive_text()
            logger.info("[ESP32→SERVER] %s", raw)

            try:
                data = json.loads(raw)
            except Exception:
                logger.warning("Invalid JSON from ESP32 — ignored: %s", raw)
                continue

            if data.get("type") == "PING":
                connection_status["last_ping"] = datetime.now().isoformat()
                await websocket.send_text(json.dumps({
                    "type": "PONG",
                    "ts":   connection_status["last_ping"]
                }))
                logger.info("[PING] → PONG sent")
                continue

            if data.get("status") == "HELLO":
                logger.info("[HELLO] device=%s fw=%s version=%s",
                            data.get("device"), data.get("fw"), data.get("version"))
                continue

            req_id = data.get("request_id")
            if req_id and req_id in pending_requests:
                future = pending_requests.pop(req_id)
                if not future.done():
                    future.set_result(data)
            else:
                logger.info("[ESP32] Unsolicited msg: %s", data)

    except WebSocketDisconnect:
        logger.warning("ESP32 disconnected!")
        esp32_websocket = None
        connection_status.update({
            "esp32_connected": False,
            "hmi_connected":   False,
            "hmi_ip":          None,
            "hmi_port":        None,
            "connected_at":    None,
            "last_ping":       None,
            "message":         "ESP32 offline",
        })
    except Exception as e:
        logger.error("ESP32 WS error: %s", e)
        esp32_websocket = None
        connection_status.update({
            "esp32_connected": False,
            "message":         f"Error: {e}",
        })

# ------------------------------------------------------------
# Helper: send command to ESP32 and await response
# ------------------------------------------------------------
async def send_to_esp32(cmd: dict, timeout: float = 15.0):
    global request_counter

    if esp32_websocket is None:
        return {"success": False, "message": "ESP32 not connected"}

    request_counter += 1
    req_id = str(request_counter)
    cmd["request_id"] = req_id

    loop = asyncio.get_running_loop()
    future = loop.create_future()
    pending_requests[req_id] = future

    try:
        await esp32_websocket.send_text(json.dumps(cmd))
        response = await asyncio.wait_for(future, timeout=timeout)
        return {"success": True, "response": response}
    except asyncio.TimeoutError:
        pending_requests.pop(req_id, None)
        return {"success": False, "message": "Timeout waiting for ESP32 response"}
    except Exception as e:
        pending_requests.pop(req_id, None)
        return {"success": False, "message": str(e)}

# ------------------------------------------------------------
# REST API
# ------------------------------------------------------------
@app.get("/")
async def root():
    return {
        "status":  "HMI Gateway is running",
        "version": "4.4.0",
        "esp32":   connection_status["esp32_connected"],
    }

@app.get("/status")
async def get_status():
    return connection_status

@app.post("/set_hmi_target")
async def set_hmi_target(req: SetTargetRequest):
    """Change the HMI target IP/port on the ESP32 (no connection attempt)."""
    if not connection_status["esp32_connected"]:
        return {"success": False, "message": "ESP32 not connected"}
    result = await send_to_esp32({
        "cmd": "SET_HMI_TARGET",
        "hmi_ip": req.hmi_ip,
        "hmi_port": req.hmi_port
    }, timeout=10.0)
    if result["success"]:
        # Optionally update status display
        connection_status["hmi_target_ip"] = req.hmi_ip
        connection_status["hmi_target_port"] = req.hmi_port
    return result

@app.post("/connect")
async def connect(req: ConnectRequest):
    global connection_status

    if not connection_status["esp32_connected"]:
        return {"success": False, "message": "ESP32 not connected"}

    result = await send_to_esp32(
        {"cmd": "CONNECT", "hmi_ip": req.hmi_ip, "hmi_port": req.hmi_port},
        timeout=20.0
    )

    if result["success"] and result["response"].get("status") == "OK":
        connection_status.update({
            "hmi_connected": True,
            "hmi_ip":        req.hmi_ip,
            "hmi_port":      req.hmi_port,
            "connected_at":  datetime.now().isoformat(),
            "message":       f"HMI connected {req.hmi_ip}:{req.hmi_port}",
        })
        return {"success": True, "status": connection_status}

    if result["success"]:
        return {"success": False, "message": result["response"].get("error", "ESP32 error")}
    return result

@app.post("/disconnect")
async def disconnect():
    global connection_status

    result = await send_to_esp32({"cmd": "DISCONNECT"}, timeout=10.0)

    if result["success"] and result["response"].get("status") == "OK":
        connection_status.update({
            "hmi_connected": False,
            "hmi_ip":        None,
            "hmi_port":      None,
            "connected_at":  None,
            "message":       "ESP32 online",
        })
        return {"success": True, "message": "HMI disconnected"}
    return {"success": False, "message": result.get("message", "Disconnect failed")}

@app.post("/start")
async def start():
    if not connection_status["hmi_connected"]:
        return {"success": False, "message": "HMI not connected"}
    result = await send_to_esp32({"cmd": "START"}, timeout=15.0)
    return result

@app.post("/stop")
async def stop():
    if not connection_status["hmi_connected"]:
        return {"success": False, "message": "HMI not connected"}
    result = await send_to_esp32({"cmd": "STOP"}, timeout=15.0)
    return result

@app.post("/send")
async def send(req: SendDataRequest):
    if not connection_status["hmi_connected"]:
        return {"success": False, "message": "HMI not connected"}
    return await send_to_esp32({"cmd": "SEND", "data": req.data}, timeout=15.0)

# ------------------------------------------------------------
# Frontend live‑status WebSocket
# ------------------------------------------------------------
@app.websocket("/ws")
async def frontend_ws(websocket: WebSocket):
    await websocket.accept()
    logger.info("Frontend WS client connected from %s", websocket.client)
    try:
        while True:
            await websocket.send_json(connection_status)
            await asyncio.sleep(2)
    except WebSocketDisconnect:
        logger.info("Frontend WS client disconnected")

# ------------------------------------------------------------
# Lifecycle
# ------------------------------------------------------------
@app.on_event("startup")
async def startup_event():
    logger.info("=== HMI Gateway v4.4.0 — waiting for ESP32 ===")

@app.on_event("shutdown")
async def shutdown_event():
    if esp32_websocket:
        await esp32_websocket.close()

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=10000,
        log_level="info",
    )