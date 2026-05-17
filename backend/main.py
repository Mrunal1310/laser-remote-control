from fastapi import FastAPI, Request
import json

app = FastAPI()

latest_cmd  = {"cmd": "NONE"}
latest_resp = {"resp": "NONE"}


async def extract_msg(request: Request) -> str:
    """
    Accept JSON body regardless of Content-Type header.
    EC200U may send application/json, text/plain, or nothing.
    """
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