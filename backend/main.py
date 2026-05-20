from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

command = {"cmd": "NONE"}
response = {"resp": "NONE"}

# ---------------- COMMAND FROM UI ----------------
@app.post("/command")
async def set_command(req: Request):
    global command
    data = await req.json()
    command = {"cmd": data["cmd"]}
    return {"ok": True, "cmd": command}

# ---------------- ESP32 POLLS COMMAND ----------------
@app.get("/command")
async def get_command():
    return command

# ---------------- ESP32 SEND RESPONSE ----------------
@app.post("/response")
async def set_response(req: Request):
    global response
    data = await req.json()
    response = {"resp": data["resp"]}
    return {"ok": True}

# ---------------- UI READ RESPONSE ----------------
@app.get("/response")
async def get_response():
    return response

@app.get("/ping")
async def ping():
    return {"status": "ok"}