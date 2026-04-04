import React, { useState, useEffect } from 'react';

// Replace with your FastAPI server's public IP/Domain
const API_BASE_URL = 'http://localhost:8000/api'; 

function App() {
  const [ip, setIp] = useState('192.168.5.158');
  const [port, setPort] = useState('8050');
  const [status, setStatus] = useState({ esp32_online: false, hmi_status: 'Disconnected' });
  const [error, setError] = useState(null);

  // Poll status every 3 seconds
  useEffect(() => {
    const fetchStatus = async () => {
      try {
        const res = await fetch(`${API_BASE_URL}/status`);
        const data = await res.json();
        setStatus(data);
        setError(null);
      } catch (err) {
        setError("Failed to reach Remote Server.");
      }
    };
    
    fetchStatus();
    const interval = setInterval(fetchStatus, 3000);
    return () => clearInterval(interval);
  }, []);

  const handleConnect = async () => {
    try {
      const res = await fetch(`${API_BASE_URL}/connect`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ip, port })
      });
      if (!res.ok) throw new Error(await res.text());
      setError(null);
    } catch (err) {
      setError("Connect failed: " + err.message);
    }
  };

  const handleDisconnect = async () => {
    try {
      await fetch(`${API_BASE_URL}/disconnect`, { method: 'POST' });
    } catch (err) {
      setError("Disconnect failed.");
    }
  };

  return (
    <div style={{ padding: '20px', fontFamily: 'Arial, sans-serif', maxWidth: '400px', margin: 'auto' }}>
      <h2>HMI Remote Connector</h2>
      
      <div style={{ marginBottom: '20px', padding: '10px', border: '1px solid #ccc', borderRadius: '5px' }}>
        <strong>System Status</strong>
        <p>Gateway (ESP32): {status.esp32_online ? '🟢 Online' : '🔴 Offline'}</p>
        <p>HMI Connection: {status.hmi_status}</p>
      </div>

      {error && <p style={{ color: 'red' }}>{error}</p>}

      <div style={{ marginBottom: '10px' }}>
        <label>HMI IP: </label>
        <input value={ip} onChange={(e) => setIp(e.target.value)} style={{ width: '100%', padding: '5px' }} />
      </div>

      <div style={{ marginBottom: '20px' }}>
        <label>HMI Port: </label>
        <input value={port} onChange={(e) => setPort(e.target.value)} type="number" style={{ width: '100%', padding: '5px' }} />
      </div>

      <div style={{ display: 'flex', gap: '10px' }}>
        <button onClick={handleConnect} style={{ flex: 1, padding: '10px', background: 'green', color: 'white' }}>
          Connect
        </button>
        <button onClick={handleDisconnect} style={{ flex: 1, padding: '10px', background: 'red', color: 'white' }}>
          Disconnect
        </button>
      </div>
    </div>
  );
}

export default App;