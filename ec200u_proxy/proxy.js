const express = require('express');
const WebSocket = require('ws');

const app = express();
app.use(express.json());

// Your backend WebSocket address (DO NOT CHANGE)
const BACKEND_WS_URL = "wss://laser-remote-control-1.onrender.com/ws/esp32";

// Store commands for each ESP32
const commandQueue = new Map();

// Connect to your backend
let backendWs = null;
function connectToBackend() {
  backendWs = new WebSocket(BACKEND_WS_URL);
  backendWs.on('open', () => {
    console.log('Connected to backend');
    backendWs.send(JSON.stringify({ status: "HELLO", device: "proxy", fw: "1.0", version: "4.3.0", apn: "proxy" }));
  });
  backendWs.on('message', (data) => {
    try {
      const msg = JSON.parse(data.toString());
      if (msg.cmd) {
        const deviceId = "esp32_001";
        if (!commandQueue.has(deviceId)) commandQueue.set(deviceId, []);
        commandQueue.get(deviceId).push(msg);
        console.log('Command received:', msg.cmd);
      }
    } catch(e) {}
  });
  backendWs.on('close', () => setTimeout(connectToBackend, 5000));
  backendWs.on('error', () => setTimeout(connectToBackend, 5000));
}
connectToBackend();

// Endpoint for ESP32 to ask for a command
app.get('/poll/:deviceId', (req, res) => {
  const deviceId = req.params.deviceId;
  const queue = commandQueue.get(deviceId);
  if (queue && queue.length > 0) {
    const cmd = queue.shift();
    return res.json({ command: cmd });
  }
  res.json({ command: null });
});

// Endpoint for ESP32 to send back status
app.post('/update/:deviceId', (req, res) => {
  if (backendWs && backendWs.readyState === WebSocket.OPEN) {
    backendWs.send(JSON.stringify(req.body));
    res.json({ status: "ok" });
  } else {
    res.status(503).json({ error: "Backend not connected" });
  }
});

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => console.log(`Proxy running on port ${PORT}`));