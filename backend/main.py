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

app = FastAPI(title="Remote HMI Gateway", version="4.3.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

esp32_websocket: Optional[WebSocket] = None
pending_requests: dict = {}
request_counter: int = 0

connection_status = {
    "esp32_connected": False,
    "hmi_connected": False,
    "hmi_ip": None,
    "hmi_port": None,
    "connected_at": None,
    "last_ping": None,
    "message": "ESP32 offline",
}

class ConnectRequest(BaseModel):
    hmi_ip: str
    hmi_port: int

class SendDataRequest(BaseModel):
    data: str

def reset_state(message="ESP32 offline"):
    global pending_requests
    connection_status.update({
        "esp32_connected": False,
        "hmi_connected": False,
        "hmi_ip": None,
        "hmi_port": None,
        "connected_at": None,
        "last_ping": None,
        "message": message,
    })

    for req_id, future in list(pending_requests.items()):
        if not future.done():
            future.set_result({"status": "ERROR", "error": "ESP32 disconnected"})
    pending_requests.clear()

@app.websocket("/ws_esp32")
async def esp32_ws(websocket: WebSocket):
    global esp32_websocket, connection_status

    await websocket.accept()

    if esp32_websocket is not None:
        try:
            await esp32_websocket.close()
        except Exception:
            pass

    esp32_websocket = websocket
    connection_status["esp32_connected"] = True
    connection_status["message"] = "ESP32 online"
    logger.info("✓ ESP32 connected from %s", websocket.client)

    try:
        while True:
            raw = await websocket.receive_text()
            logger.info("[ESP32→SERVER] %s", raw)

            try:
                data = json.loads(raw)
            except Exception:
                logger.warning("Invalid JSON from ESP32: %s", raw)
                continue

            if data.get("type") == "PING":
                connection_status["last_ping"] = datetime.now().isoformat()
                await websocket.send_text(json.dumps({
                    "type": "PONG",
                    "ts": connection_status["last_ping"]
                }))
                continue

            if data.get("status") == "HELLO":
                connection_status["message"] = "ESP32 online"
                logger.info("[HELLO] device=%s fw=%s version=%s apn=%s",
                            data.get("device"), data.get("fw"),
                            data.get("version"), data.get("apn"))
                continue

            if data.get("event") == "HMI_CONNECTED":
                connection_status.update({
                    "hmi_connected": True,
                    "hmi_ip": data.get("hmi_ip"),
                    "hmi_port": data.get("hmi_port"),
                    "connected_at": datetime.now().isoformat(),
                    "message": f"HMI connected {data.get('hmi_ip')}:{data.get('hmi_port')}",
                })
                continue

            if data.get("event") == "HMI_DISCONNECTED":
                connection_status.update({
                    "hmi_connected": False,
                    "hmi_ip": None,
                    "hmi_port": None,
                    "connected_at": None,
                    "message": "ESP32 online",
                })
                continue

            if data.get("event") == "HMI_RX":
                logger.info("[HMI RX] %s", data.get("data"))
                continue

            req_id = data.get("request_id")
            if req_id and req_id in pending_requests:
                future = pending_requests.pop(req_id)
                if not future.done():
                    future.set_result(data)
            else:
                logger.info("[ESP32] Unsolicited: %s", data)

    except WebSocketDisconnect:
        logger.warning("ESP32 disconnected")
        esp32_websocket = None
        reset_state("ESP32 offline")
    except Exception as e:
        logger.error("ESP32 WS error: %s", e)
        esp32_websocket = None
        reset_state(f"ESP32 error: {e}")

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
        if response.get("status") == "OK":
            return {"success": True, "response": response}
        return {"success": False, "message": response.get("error", "ESP32 returned error"), "response": response}
    except asyncio.TimeoutError:
        pending_requests.pop(req_id, None)
        return {"success": False, "message": "Timeout waiting for ESP32 response"}
    except Exception as e:
        pending_requests.pop(req_id, None)
        return {"success": False, "message": str(e)}

@app.get("/")
async def root():
    return {
        "status": "HMI Gateway is running",
        "version": "4.3.0",
        "esp32": connection_status["esp32_connected"],
    }

@app.get("/status")
async def get_status():
    return connection_status

@app.post("/connect")
async def connect(req: ConnectRequest):
    if not connection_status["esp32_connected"]:
        return {"success": False, "message": "ESP32 not connected to server"}

    result = await send_to_esp32(
        {"cmd": "CONNECT", "hmi_ip": req.hmi_ip, "hmi_port": req.hmi_port},
        timeout=20.0
    )

    if result["success"]:
        return {"success": True, "status": connection_status}
    return result

@app.post("/disconnect")
async def disconnect():
    result = await send_to_esp32({"cmd": "DISCONNECT"}, timeout=10.0)
    return result

@app.post("/send")
async def send(req: SendDataRequest):
    if not connection_status["hmi_connected"]:
        return {"success": False, "message": "HMI not connected"}
    return await send_to_esp32({"cmd": "SEND", "data": req.data}, timeout=15.0)

@app.websocket("/ws")
async def frontend_ws(websocket: WebSocket):
    await websocket.accept()
    logger.info("Frontend WS connected from %s", websocket.client)
    try:
        while True:
            await websocket.send_json(connection_status)
            await asyncio.sleep(2)
    except WebSocketDisconnect:
        logger.info("Frontend WS disconnected")

@app.on_event("startup")
async def startup_event():
    logger.info("=== HMI Gateway v4.3.0 — waiting for ESP32 ===")

@app.on_event("shutdown")
async def shutdown_event():
    global esp32_websocket
    if esp32_websocket:
        try:
            await esp32_websocket.close()
        except Exception:
            pass

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=10000,
        log_level="info",
    )