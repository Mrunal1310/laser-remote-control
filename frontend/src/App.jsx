import { useState, useEffect, useRef, useCallback } from "react";

const BACKEND_URL = "https://laser-remote-control-1.onrender.com";

function getWsUrl() {
  return BACKEND_URL.replace("https://", "wss://") + "/ws";
}

function Dot({ active, color, size = 8 }) {
  return (
    <span style={{
      width: size, height: size, borderRadius: "50%",
      background: active ? color : "#1e3a5f",
      display: "inline-block", flexShrink: 0,
      boxShadow: active ? `0 0 10px ${color}99` : "none",
      transition: "all 0.4s",
    }} />
  );
}

function Chip({ active, borderColor, bg, dotColor, label, value }) {
  return (
    <div style={{
      display: "flex", alignItems: "center", gap: 8,
      padding: "7px 14px", borderRadius: 30,
      border: `1px solid ${active ? borderColor : "#1e3a5f"}`,
      background: active ? bg : "#050e1d",
      transition: "all 0.4s",
    }}>
      <Dot active={active} color={dotColor} />
      <span style={{ color: "#64748b", fontSize: 11, fontWeight: 600, letterSpacing: "0.1em" }}>
        {label}
      </span>
      <span style={{ fontSize: 11, fontWeight: 700, letterSpacing: "0.08em", color: active ? dotColor : "#334155" }}>
        {value}
      </span>
    </div>
  );
}

export default function App() {
  const [hmiIp,   setHmiIp]   = useState("192.168.5.158");
  const [hmiPort, setHmiPort] = useState("8050");

  const [esp32Online,   setEsp32Online]   = useState(false);
  const [hmiConnected,  setHmiConnected]  = useState(false);
  const [isLoading,     setIsLoading]     = useState(false);
  const [statusMsg,     setStatusMsg]     = useState("ESP32 offline");
  const [lastPing,      setLastPing]      = useState(null);
  const [wsState,       setWsState]       = useState("connecting");
  const [error,         setError]         = useState("");
  const [logs,          setLogs]          = useState([]);
  const [sendData,      setSendData]      = useState("");
  const [lastResponse,  setLastResponse]  = useState("");
  const [incomingHmiData, setIncomingHmiData] = useState("");

  const wsRef       = useRef(null);
  const retryRef    = useRef(null);
  const logsEndRef  = useRef(null);
  const esp32Ref    = useRef(false);

  useEffect(() => { logsEndRef.current?.scrollIntoView({ behavior: "smooth" }); }, [logs]);

  const addLog = useCallback((msg, type = "info") => {
    const time = new Date().toLocaleTimeString();
    setLogs(p => [...p.slice(-199), { time, msg, type }]);
  }, []);

  // Live status + HMI data WebSocket
  const connectWS = useCallback(() => {
    if (retryRef.current) clearTimeout(retryRef.current);
    if (wsRef.current?.readyState === WebSocket.OPEN) return;
    if (wsRef.current) wsRef.current.close();

    setWsState("connecting");
    const ws = new WebSocket(getWsUrl());
    wsRef.current = ws;

    ws.onopen = () => { setWsState("open"); addLog("Status feed connected", "success"); };

    ws.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data);
        // If it's a status update (has esp32_connected)
        if ("esp32_connected" in data) {
          const was = esp32Ref.current;
          const now = data.esp32_connected === true;
          esp32Ref.current = now;
          setEsp32Online(now);
          setHmiConnected(data.hmi_connected === true);
          setStatusMsg(data.message || "");
          if (data.last_ping) setLastPing(data.last_ping);
          if (!was && now) addLog("✓ ESP32 came online", "success");
          if (was && !now) addLog("ESP32 went offline", "warn");
        }
        // If it's HMI data from ESP32
        else if (data.type === "hmi_data") {
          const incoming = data.data || "";
          setIncomingHmiData(incoming);
          addLog(`📩 HMI → ${incoming}`, "info");
        }
      } catch (err) { addLog("Status feed: bad JSON", "warn"); }
    };

    ws.onerror = () => { setWsState("closed"); addLog("Status feed error", "error"); };

    ws.onclose = (e) => {
      setWsState("closed");
      if (e.code === 1000) return;
      addLog("Status feed dropped — retrying in 5 s", "warn");
      retryRef.current = setTimeout(connectWS, 5000);
    };
  }, [addLog]);

  useEffect(() => {
    connectWS();
    return () => { if (retryRef.current) clearTimeout(retryRef.current); wsRef.current?.close(); };
  }, []);

  // API calls
  async function handleConnect() {
    if (!hmiIp || !hmiPort) { setError("Enter HMI IP and Port."); return; }
    if (!esp32Online)        { setError("ESP32 is offline — cannot connect."); return; }
    setError(""); setIsLoading(true);
    addLog(`Connecting HMI ${hmiIp}:${hmiPort}…`, "info");
    try {
      const r = await fetch(`${BACKEND_URL}/connect`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ hmi_ip: hmiIp, hmi_port: parseInt(hmiPort) }),
      });
      const d = await r.json();
      if (d.success) addLog(`HMI connected at ${hmiIp}:${hmiPort}`, "success");
      else { setError(d.message); addLog(`Failed: ${d.message}`, "error"); }
    } catch (e) { setError(`Backend error: ${e.message}`); addLog(`Backend error: ${e.message}`, "error"); }
    finally { setIsLoading(false); }
  }

  async function handleDisconnect() {
    setIsLoading(true); addLog("Disconnecting HMI…", "warn");
    try {
      const r = await fetch(`${BACKEND_URL}/disconnect`, { method: "POST" });
      const d = await r.json();
      addLog(d.message || "Disconnected", "warn");
    } catch (e) { setError(`Disconnect error: ${e.message}`); }
    finally { setIsLoading(false); }
  }

  async function handleSend() {
    if (!sendData.trim()) return;
    if (!hmiConnected) { setError("Connect to HMI first."); return; }
    setError(""); addLog(`Sending: ${sendData}`, "info");
    try {
      const r = await fetch(`${BACKEND_URL}/send`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ data: sendData }),
      });
      const d = await r.json();
      if (d.success) {
        setLastResponse(JSON.stringify(d.response, null, 2));
        addLog("Sent ✓", "success"); setSendData("");
      } else { setError(d.message); addLog(`Send failed: ${d.message}`, "error"); }
    } catch (e) { setError(`Send error: ${e.message}`); addLog(`Send error: ${e.message}`, "error"); }
  }

  const LC = { info: "#94a3b8", success: "#4ade80", error: "#f87171", warn: "#fbbf24" };
  const wsDot = wsState === "open" ? "#4ade80" : wsState === "connecting" ? "#fbbf24" : "#ef4444";
  const wsLbl = wsState === "open" ? "live" : wsState === "connecting" ? "connecting…" : "reconnecting…";

  return (
    <div style={s.page}>
      <div style={s.card}>
        <div style={s.header}>
          <h1 style={s.title}>Remote HMI Control</h1>
          <p style={s.subtitle}>ESP32 · ENC28J60 · Render v5.0</p>
        </div>

        <div style={s.bar}>
          <Chip active={esp32Online} borderColor="#166534" bg="#052e16"
                dotColor="#4ade80" label="ESP32" value={esp32Online ? "ACTIVE" : "OFFLINE"} />
          <span style={{ color: "#1e3a5f", fontSize: 16 }}>→</span>
          <Chip active={hmiConnected} borderColor="#1d4ed8" bg="#0f1f3d"
                dotColor="#60a5fa" label="HMI" value={hmiConnected ? "CONNECTED" : "IDLE"} />
          <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 6, fontSize: 11, color: "#475569" }}>
            <Dot active size={6} color={wsDot} />
            <span>{wsLbl}</span>
          </div>
          <span style={{ color: "#334155", fontSize: 11, fontStyle: "italic", width: "100%", marginTop: 4 }}>
            {statusMsg}
          </span>
        </div>

        {lastPing && esp32Online && (
          <div style={s.info}>⚡ Last PING: {new Date(lastPing).toLocaleTimeString()}</div>
        )}

        {!esp32Online && (
          <div style={s.warn}>
            🔌 Waiting for ESP32 WebSocket on <code style={{ color: "#fbbf24" }}>/ws/esp32</code>…
          </div>
        )}

        {error && (
          <div style={s.err}>
            <span>⚠ {error}</span>
            <button style={s.x} onClick={() => setError("")}>✕</button>
          </div>
        )}

        {/* HMI Connection */}
        <div style={s.box}>
          <h2 style={s.boxTitle}>HMI Connection</h2>
          <div style={s.grid}>
            <label style={s.lbl}>
              HMI IP Address
              <input style={s.inp} value={hmiIp} onChange={e => setHmiIp(e.target.value)}
                     disabled={hmiConnected} placeholder="192.168.x.x" />
            </label>
            <label style={s.lbl}>
              HMI Port
              <input style={s.inp} value={hmiPort} onChange={e => setHmiPort(e.target.value)}
                     type="number" disabled={hmiConnected} placeholder="8050" />
            </label>
          </div>
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
            <button style={s.btn("#2563eb", hmiConnected || !esp32Online || isLoading)}
                    onClick={handleConnect} disabled={hmiConnected || !esp32Online || isLoading}>
              {isLoading && !hmiConnected ? "CONNECTING…" : "▶ CONNECT HMI"}
            </button>
            <button style={s.btn("#dc2626", !hmiConnected || isLoading)}
                    onClick={handleDisconnect} disabled={!hmiConnected || isLoading}>
              {isLoading && hmiConnected ? "DISCONNECTING…" : "■ DISCONNECT"}
            </button>
          </div>
        </div>

        {/* Incoming HMI Data Display */}
        {hmiConnected && (
          <div style={s.box}>
            <h2 style={s.boxTitle}>📥 Incoming from HMI</h2>
            <pre style={s.pre}>{incomingHmiData || "— no data yet —"}</pre>
          </div>
        )}

        {/* Send data */}
        {hmiConnected && (
          <div style={s.box}>
            <h2 style={s.boxTitle}>Send Data to HMI</h2>
            <div style={{ display: "flex", gap: 10 }}>
              <input style={{ ...s.inp, flex: 1 }} value={sendData}
                     onChange={e => setSendData(e.target.value)}
                     placeholder='{"action":"read","register":1}'
                     onKeyDown={e => e.key === "Enter" && handleSend()} />
              <button style={s.btn("#16a34a", false)} onClick={handleSend}>SEND</button>
            </div>
            {lastResponse && <pre style={s.pre}>{lastResponse}</pre>}
          </div>
        )}

        {/* Log */}
        <div style={s.box}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
            <h2 style={{ ...s.boxTitle, marginBottom: 0 }}>Activity Log</h2>
            {logs.length > 0 && (
              <button style={{ ...s.x, fontSize: 11, color: "#334155" }} onClick={() => setLogs([])}>CLEAR</button>
            )}
          </div>
          <div style={s.log}>
            {!logs.length && <p style={{ color: "#1e3a5f", margin: 0, fontSize: 12 }}>No activity yet…</p>}
            {logs.map((l, i) => (
              <div key={i} style={{ marginBottom: 4 }}>
                <span style={{ color: "#1e3a5f", fontSize: 10 }}>[{l.time}] </span>
                <span style={{ color: LC[l.type] || "#94a3b8", fontSize: 12 }}>{l.msg}</span>
              </div>
            ))}
            <div ref={logsEndRef} />
          </div>
        </div>

        <p style={{ color: "#1e3a5f", fontSize: 11, textAlign: "center", marginTop: 8, letterSpacing: "0.04em" }}>
          BACKEND <code style={{ color: "#2563eb" }}>{BACKEND_URL}</code>
          &nbsp;·&nbsp; ESP32 WS <code style={{ color: "#2563eb" }}>/ws/esp32</code>
        </p>
      </div>
    </div>
  );
}

const s = {
  page: { minHeight: "100vh", background: "#020817", display: "flex", justifyContent: "center", padding: "24px 16px", fontFamily: "'JetBrains Mono','Fira Code',monospace" },
  card: { background: "#0a1628", border: "1px solid #1e3a5f", borderRadius: 20, padding: "32px 28px", width: "100%", maxWidth: 820, boxShadow: "0 0 60px rgba(37,99,235,0.08)", boxSizing: "border-box" },
  header: { marginBottom: 28, textAlign: "center" },
  title: { color: "#f0f9ff", fontSize: 24, fontWeight: 700, margin: 0, letterSpacing: "-0.02em" },
  subtitle: { color: "#38bdf8", fontSize: 12, marginTop: 6, letterSpacing: "0.12em", textTransform: "uppercase" },
  bar: { display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap", padding: "14px 18px", borderRadius: 12, marginBottom: 16, background: "#050e1d", border: "1px solid #0f2744" },
  info: { background: "#0d1f38", border: "1px solid #1e3a5f", color: "#38bdf8", padding: "10px 14px", borderRadius: 10, marginBottom: 14, fontSize: 12 },
  warn: { background: "#1c1400", border: "1px solid #713f12", color: "#fbbf24", padding: "10px 14px", borderRadius: 10, marginBottom: 14, fontSize: 12, lineHeight: 1.7 },
  err:  { background: "#300808", border: "1px solid #7f1d1d", color: "#fca5a5", padding: "10px 14px", borderRadius: 10, marginBottom: 14, display: "flex", justifyContent: "space-between", alignItems: "center", fontSize: 12 },
  x:    { background: "transparent", border: "none", color: "#fca5a5", cursor: "pointer", fontSize: 14 },
  box:  { background: "#0d1f38", borderRadius: 14, padding: "20px 22px", marginBottom: 16, border: "1px solid #1e3a5f" },
  boxTitle: { color: "#7dd3fc", fontSize: 12, fontWeight: 700, marginBottom: 16, letterSpacing: "0.12em", textTransform: "uppercase" },
  grid: { display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(240px,1fr))", gap: 14, marginBottom: 16 },
  lbl:  { color: "#475569", fontSize: 11, letterSpacing: "0.08em", textTransform: "uppercase", display: "flex", flexDirection: "column", gap: 6 },
  inp:  { background: "#050e1d", border: "1px solid #1e3a5f", borderRadius: 8, color: "#e0f2fe", padding: "10px 12px", fontSize: 13, outline: "none", fontFamily: "inherit", boxSizing: "border-box", width: "100%" },
  btn:  (color, dis) => ({ background: dis ? "#0d1f38" : color, color: dis ? "#334155" : "#fff", border: `1px solid ${dis ? "#1e3a5f" : color}`, borderRadius: 8, padding: "11px 22px", fontSize: 12, fontWeight: 700, letterSpacing: "0.06em", cursor: dis ? "not-allowed" : "pointer", transition: "all 0.2s", fontFamily: "inherit" }),
  pre:  { background: "#020c1b", color: "#34d399", borderRadius: 8, padding: 14, fontSize: 12, marginTop: 12, overflowX: "auto", border: "1px solid #0d4a2a", fontFamily: "inherit" },
  log:  { background: "#020c1b", borderRadius: 10, padding: "14px 16px", height: 220, overflowY: "auto", border: "1px solid #0f2744", fontFamily: "inherit" },
};