from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()

latest_cmd = {"cmd": "NONE"}
latest_resp = {"resp": "NONE"}

class Msg(BaseModel):
    msg: str

@app.post("/esp32/hello")
async def esp32_hello(data: Msg):
    return {"status": "OK", "received": data.msg}

@app.post("/esp32/sendcmd")
async def send_command(data: Msg):
    global latest_cmd
    latest_cmd = {"cmd": data.msg}
    return {"status": "OK"}

@app.get("/esp32/cmd")
async def get_cmd():
    global latest_cmd
    return latest_cmd

@app.post("/esp32/response")
async def esp32_response(data: Msg):
    global latest_resp
    latest_resp = {"resp": data.msg}
    return {"status": "OK"}

@app.get("/esp32/lastresp")
async def last_response():
    return latest_resp