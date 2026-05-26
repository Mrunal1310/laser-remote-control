from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
import json

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

latest_cmd  = {"cmd": "NONE"}
latest_resp = {"resp": "NONE"}
command     = {"cmd": "NONE"}
response    = {"resp": "NONE"}

# ── ping — accepts GET and HEAD ──────────────────────────────
@app.get("/ping")
async def ping_get():
    return "OK"

@app.head("/ping")
async def ping_head():
    return Response(status_code=200)

# ── COMMAND FROM UI ──────────────────────────────────────────
@app.post("/command")
async def set_command(req: Request):
    global command
    data = await req.json()
    command = {"cmd": data["cmd"]}
    return {"ok": True, "cmd": command}

# ── ESP32 POLLS COMMAND ──────────────────────────────────────
@app.get("/command")
async def get_command():
    return command

# ── ESP32 SENDS RESPONSE ─────────────────────────────────────
@app.post("/response")
async def set_response(req: Request):
    global response
    data = await req.json()
    response = {"resp": data["resp"]}
    return {"ok": True}

# ── UI READS RESPONSE ────────────────────────────────────────
@app.get("/response")
async def get_response():
    return response

async def extract_msg(request: Request) -> str:
    body = await request.body()
    try:
        data = json.loads(body)
        return data.get("msg", "")
    except Exception:
        return body.decode(errors="replace").strip()

@app.post("/esp32/hello")
async def esp32_hello(request: Request):
    msg = await extract_msg(request)
    print(f"[hello] {msg}")
    return {"status": "OK", "received": msg}

@app.post("/esp32/sendcmd")
async def send_command(request: Request):
    global latest_cmd
    msg = await extract_msg(request)
    latest_cmd = {"cmd": msg}
    print(f"[sendcmd] cmd set to: {msg}")
    return {"status": "OK"}

@app.get("/esp32/cmd")
async def get_cmd():
    return latest_cmd

@app.post("/esp32/response")
async def esp32_response(request: Request):
    global latest_resp
    msg = await extract_msg(request)
    latest_resp = {"resp": msg}
    print(f"[response] {msg}")
    return {"status": "OK"}

@app.get("/esp32/lastresp")
async def last_response():
    return latest_resp