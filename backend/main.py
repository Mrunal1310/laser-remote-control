from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from typing import Dict

app = FastAPI()

# Enable CORS for React Frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, change to your React app's domain
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global state to track the connected ESP32 and HMI status
active_esp32_connection: WebSocket = None
hmi_connection_status = "Disconnected"

@app.websocket("/ws/esp32")
async def websocket_esp32(websocket: WebSocket):
    """ESP32 connects here over 4G"""
    global active_esp32_connection
    await websocket.accept()
    active_esp32_connection = websocket
    print("ESP32 Connected to Server!")
    
    try:
        while True:
            data = await websocket.receive_text()
            # If ESP32 sends status updates
            if data.startswith("STATUS:"):
                global hmi_connection_status
                hmi_connection_status = data.split(":")[1]
            else:
                # Handle actual HMI data coming from ESP32 here
                print(f"Data from HMI: {data}")
    except WebSocketDisconnect:
        print("ESP32 Disconnected!")
        active_esp32_connection = None
        hmi_connection_status = "Disconnected"

@app.post("/api/connect")
async def connect_hmi(payload: dict):
    """React calls this to command the ESP32 to connect to the HMI"""
    global active_esp32_connection
    
    if not active_esp32_connection:
        raise HTTPException(status_code=404, detail="ESP32 is offline. Cannot reach onsite network.")
    
    ip = payload.get("ip", "192.168.5.158")
    port = payload.get("port", "8050")
    
    # Send command to ESP32
    command = f"CONNECT:{ip}:{port}"
    await active_esp32_connection.send_text(command)
    
    return {"message": "Command sent to ESP32"}

@app.post("/api/disconnect")
async def disconnect_hmi():
    """React calls this to command ESP32 to drop HMI connection"""
    global active_esp32_connection
    if active_esp32_connection:
        await active_esp32_connection.send_text("DISCONNECT")
    return {"message": "Disconnect command sent"}

@app.get("/api/status")
async def get_status():
    """React calls this to check system health"""
    global hmi_connection_status
    return {
        "esp32_online": active_esp32_connection is not None,
        "hmi_status": hmi_connection_status
    }