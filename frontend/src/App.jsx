import { useState, useEffect, useRef } from "react";

const BACKEND_URL = "https://laser-remote-control-1.onrender.com";

export default function App() {
  const [hmiIp, setHmiIp] = useState("192.168.5.158");
  const [hmiPort, setHmiPort] = useState("8050");
  const [esp32Ip, setEsp32Ip] = useState("");
  const [esp32Port, setEsp32Port] = useState("9000");

  const [isConnected, setIsConnected] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [statusMessage, setStatusMessage] = useState("Not connected");
  const [error, setError] = useState("");
  const [logs, setLogs] = useState([]);
  const [sendData, setSendData] = useState("");
  const [lastResponse, setLastResponse] = useState("");
  const [esp32Online, setEsp32Online] = useState(false);

  const wsRef = useRef(null);
  const reconnectTimerRef = useRef(null);
  const logsEndRef = useRef(null);

  useEffect(() => {
    logsEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [logs]);

  function addLog(message, type = "info") {
    const time = new Date().toLocaleTimeString();
    setLogs((prev) => [...prev.slice(-49), { time, message, type }]);
  }

  function getWsUrl() {
    if (BACKEND_URL.startsWith("https://")) {
      return BACKEND_URL.replace("https://", "wss://") + "/ws";
    }
    return BACKEND_URL.replace("http://", "ws://") + "/ws";
  }

  function connectWebSocket() {
    if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current);
    if (wsRef.current) wsRef.current.close();

    const ws = new WebSocket(getWsUrl());
    wsRef.current = ws;

    ws.onopen = () => addLog("WebSocket connected to backend", "success");

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        setIsConnected(data.connected);
        setStatusMessage(data.message || (data.connected ? "Connected" : "Not connected"));
        // Optional: detect if ESP32 is online based on message content
        if (data.message && data.message.includes("ESP32")) {
          setEsp32Online(data.connected);
        }
      } catch (err) {
        addLog("WebSocket received invalid JSON", "warn");
      }
    };

    ws.onerror = () => addLog("WebSocket error", "error");
    ws.onclose = () => {
      addLog("WebSocket disconnected. Reconnecting in 5s...", "warn");
      reconnectTimerRef.current = setTimeout(connectWebSocket, 5000);
    };
  }

  useEffect(() => {
    connectWebSocket();
    return () => {
      if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current);
      if (wsRef.current) wsRef.current.close();
    };
  }, []);

  async function handleConnect() {
    if (!hmiIp || !hmiPort || !esp32Ip || !esp32Port) {
      setError("Please fill in all fields before connecting.");
      return;
    }
    setError("");
    setIsLoading(true);
    addLog(`Connecting to HMI ${hmiIp}:${hmiPort} via ESP32 ${esp32Ip}:${esp32Port}...`, "info");

    try {
      const res = await fetch(`${BACKEND_URL}/connect`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          hmi_ip: hmiIp,
          hmi_port: parseInt(hmiPort),
          esp32_ip: esp32Ip,
          esp32_port: parseInt(esp32Port),
        }),
      });
      const data = await res.json();
      if (data.success) {
        setIsConnected(true);
        setStatusMessage(data.message);
        addLog(data.message, "success");
      } else {
        setError(data.message);
        addLog(`Connection failed: ${data.message}`, "error");
      }
    } catch (err) {
      setError(`Cannot reach backend: ${err.message}`);
      addLog(`Cannot reach backend: ${err.message}`, "error");
    } finally {
      setIsLoading(false);
    }
  }

  async function handleDisconnect() {
    setIsLoading(true);
    addLog("Disconnecting...", "warn");
    try {
      const res = await fetch(`${BACKEND_URL}/disconnect`, { method: "POST" });
      const data = await res.json();
      setIsConnected(false);
      setStatusMessage("Disconnected");
      addLog(data.message || "Disconnected", "warn");
    } catch (err) {
      setError(`Disconnect error: ${err.message}`);
      addLog(`Disconnect error: ${err.message}`, "error");
    } finally {
      setIsLoading(false);
    }
  }

  async function handleSend() {
    if (!sendData.trim()) return;
    if (!isConnected) {
      setError("Connect to HMI first before sending data.");
      return;
    }
    setError("");
    addLog(`Sending: ${sendData}`, "info");
    try {
      const res = await fetch(`${BACKEND_URL}/send`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ data: sendData }),
      });
      const data = await res.json();
      if (data.success) {
        setLastResponse(JSON.stringify(data.response, null, 2));
        addLog("Data sent successfully", "success");
        setSendData("");
      } else {
        setError(data.message);
        addLog(`Send failed: ${data.message}`, "error");
      }
    } catch (err) {
      setError(`Send error: ${err.message}`);
      addLog(`Send error: ${err.message}`, "error");
    }
  }

  const logColor = { info: "#aaa", success: "#4ade80", error: "#f87171", warn: "#fbbf24" };

  return (
    <div style={styles.page}>
      <div style={styles.card}>
        <div style={styles.header}>
          <h1 style={styles.title}>Remote HMI Control</h1>
          <p style={styles.subtitle}>Connect to onsite HMI via ESP32 gateway (WebSocket tunnel)</p>
        </div>

        <div style={{ ...styles.statusBar, background: isConnected ? "#14532d" : "#1c1917" }}>
          <span style={{ ...styles.statusDot, background: isConnected ? "#4ade80" : "#ef4444" }} />
          <span style={{ color: isConnected ? "#4ade80" : "#ef4444", fontWeight: 600 }}>
            {isConnected ? "CONNECTED" : "DISCONNECTED"}
          </span>
          <span style={{ color: "#9ca3af", marginLeft: 12, fontSize: 13 }}>{statusMessage}</span>
          {esp32Online && <span style={{ color: "#60a5fa", marginLeft: "auto", fontSize: 12 }}>ESP32 Online</span>}
        </div>

        {error && (
          <div style={styles.errorBox}>
            ⚠️ {error}
            <button style={styles.clearBtn} onClick={() => setError("")}>✕</button>
          </div>
        )}

        <div style={styles.section}>
          <h2 style={styles.sectionTitle}>Connection Settings</h2>
          <div style={styles.grid2}>
            <label style={styles.label}>
              HMI IP Address
              <input style={styles.input} value={hmiIp} onChange={(e) => setHmiIp(e.target.value)} placeholder="192.168.5.158" disabled={isConnected} />
            </label>
            <label style={styles.label}>
              HMI Port
              <input style={styles.input} value={hmiPort} onChange={(e) => setHmiPort(e.target.value)} placeholder="8050" type="number" disabled={isConnected} />
            </label>
            <label style={styles.label}>
              ESP32 Public IP (for reference)
              <input style={styles.input} value={esp32Ip} onChange={(e) => setEsp32Ip(e.target.value)} placeholder="103.45.67.89" disabled={isConnected} />
              <span style={styles.hint}>Used only for display – ESP32 now connects outbound.</span>
            </label>
            <label style={styles.label}>
              ESP32 Listen Port (legacy)
              <input style={styles.input} value={esp32Port} onChange={(e) => setEsp32Port(e.target.value)} placeholder="9000" type="number" disabled />
              <span style={styles.hint}>No longer needed for inbound connections.</span>
            </label>
          </div>
          <div style={styles.buttonRow}>
            <button style={{ ...styles.btn, background: isConnected ? "#374151" : "#2563eb", opacity: isLoading ? 0.6 : 1 }} onClick={handleConnect} disabled={isConnected || isLoading}>
              {isLoading && !isConnected ? "Connecting..." : "🔌 Connect"}
            </button>
            <button style={{ ...styles.btn, background: !isConnected ? "#374151" : "#dc2626", opacity: isLoading ? 0.6 : 1 }} onClick={handleDisconnect} disabled={!isConnected || isLoading}>
              {isLoading && isConnected ? "Disconnecting..." : "🔴 Disconnect"}
            </button>
          </div>
        </div>

        {isConnected && (
          <div style={styles.section}>
            <h2 style={styles.sectionTitle}>Send Data to HMI</h2>
            <div style={styles.sendRow}>
              <input style={{ ...styles.input, flex: 1 }} value={sendData} onChange={(e) => setSendData(e.target.value)} placeholder='Enter command (e.g., {"action":"read","register":1})' onKeyDown={(e) => e.key === "Enter" && handleSend()} />
              <button style={{ ...styles.btn, background: "#16a34a", minWidth: 80 }} onClick={handleSend}>Send</button>
            </div>
            {lastResponse && <pre style={styles.responseBox}>{lastResponse}</pre>}
          </div>
        )}

        <div style={styles.section}>
          <h2 style={styles.sectionTitle}>Activity Log</h2>
          <div style={styles.logBox}>
            {logs.length === 0 && <p style={{ color: "#6b7280", margin: 0, fontSize: 13 }}>No activity yet...</p>}
            {logs.map((log, i) => (
              <div key={i} style={{ marginBottom: 4 }}>
                <span style={{ color: "#6b7280", fontSize: 12 }}>[{log.time}] </span>
                <span style={{ color: logColor[log.type] || "#aaa", fontSize: 13 }}>{log.message}</span>
              </div>
            ))}
            <div ref={logsEndRef} />
          </div>
        </div>

        <p style={{ color: "#4b5563", fontSize: 12, textAlign: "center", marginTop: 8 }}>
          Backend: <code style={{ color: "#60a5fa" }}>{BACKEND_URL}</code>
        </p>
      </div>
    </div>
  );
}

const styles = {
  page: { minHeight: "100vh", background: "#030712", display: "flex", alignItems: "flex-start", justifyContent: "center", padding: "24px 16px", fontFamily: "'Inter', system-ui, sans-serif" },
  card: { background: "#111827", border: "1px solid #1f2937", borderRadius: 16, padding: 32, width: "100%", maxWidth: 760, boxSizing: "border-box" },
  header: { marginBottom: 24, textAlign: "center" },
  title: { color: "#f9fafb", fontSize: 26, fontWeight: 700, margin: "0 0 6px" },
  subtitle: { color: "#9ca3af", fontSize: 14, margin: 0 },
  statusBar: { display: "flex", alignItems: "center", gap: 8, padding: "12px 16px", borderRadius: 10, marginBottom: 20, border: "1px solid #1f2937" },
  statusDot: { width: 10, height: 10, borderRadius: "50%", display: "inline-block", flexShrink: 0 },
  errorBox: { background: "#450a0a", border: "1px solid #991b1b", color: "#fca5a5", padding: "10px 14px", borderRadius: 8, marginBottom: 16, fontSize: 14, display: "flex", justifyContent: "space-between", alignItems: "center" },
  clearBtn: { background: "transparent", border: "none", color: "#fca5a5", cursor: "pointer", fontSize: 16, padding: 0 },
  section: { background: "#1f2937", borderRadius: 10, padding: 20, marginBottom: 16, border: "1px solid #374151" },
  sectionTitle: { color: "#e5e7eb", fontSize: 16, fontWeight: 600, margin: "0 0 16px" },
  grid2: { display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: 16, marginBottom: 16 },
  label: { color: "#d1d5db", fontSize: 14, display: "flex", flexDirection: "column", gap: 6 },
  input: { background: "#111827", border: "1px solid #374151", borderRadius: 8, color: "#f9fafb", padding: "10px 12px", fontSize: 14, outline: "none", width: "100%", boxSizing: "border-box" },
  hint: { color: "#6b7280", fontSize: 12, marginTop: 2 },
  buttonRow: { display: "flex", gap: 12, flexWrap: "wrap" },
  btn: { color: "#fff", border: "none", borderRadius: 8, padding: "12px 24px", fontSize: 15, fontWeight: 600, cursor: "pointer", transition: "opacity 0.2s" },
  sendRow: { display: "flex", gap: 10, alignItems: "center" },
  responseBox: { background: "#0f172a", color: "#34d399", borderRadius: 8, padding: 12, fontSize: 13, marginTop: 12, overflowX: "auto", border: "1px solid #1e3a5f" },
  logBox: { background: "#0f172a", borderRadius: 8, padding: 14, height: 180, overflowY: "auto", border: "1px solid #1f2937", fontFamily: "monospace" },
};