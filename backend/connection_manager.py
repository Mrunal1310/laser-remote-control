import socket
import threading
import json
import logging
from typing import Optional, Dict, Any

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ESP32ConnectionManager:
    def __init__(self, host: str = "0.0.0.0", port: int = 5000):
        self.host = host
        self.port = port
        self.server_socket: Optional[socket.socket] = None
        self.client_socket: Optional[socket.socket] = None
        self.client_address: Optional[tuple] = None
        self.running = False
        self.connected = False
        self.receive_thread: Optional[threading.Thread] = None
        
    def start_server(self):
        try:
            self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server_socket.bind((self.host, self.port))
            self.server_socket.listen(1)
            self.running = True
            logger.info(f"TCP server listening on {self.host}:{self.port}")
            accept_thread = threading.Thread(target=self._accept_connections, daemon=True)
            accept_thread.start()
            return True
        except Exception as e:
            logger.error(f"Failed to start TCP server: {e}")
            return False
    
    def _accept_connections(self):
        while self.running:
            try:
                self.server_socket.settimeout(1.0)
                client, addr = self.server_socket.accept()
                self.client_socket = client
                self.client_address = addr
                self.connected = True
                logger.info(f"ESP32 connected from {addr}")
                self.receive_thread = threading.Thread(target=self._receive_loop, daemon=True)
                self.receive_thread.start()
            except socket.timeout:
                continue
            except Exception as e:
                if self.running:
                    logger.error(f"Accept error: {e}")
                    
    def _receive_loop(self):
        buffer = ""
        while self.running and self.connected and self.client_socket:
            try:
                data = self.client_socket.recv(4096)
                if not data:
                    logger.info("ESP32 disconnected")
                    self.connected = False
                    break
                buffer += data.decode('utf-8')
                while '\n' in buffer:
                    line, buffer = buffer.split('\n', 1)
                    if line.strip():
                        self._handle_message(line.strip())
            except Exception as e:
                logger.error(f"Receive error: {e}")
                self.connected = False
                break
                
    def _handle_message(self, message: str):
        try:
            msg = json.loads(message)
            msg_type = msg.get('type', '')
            if msg_type == 'status':
                logger.info(f"Status from ESP32: {msg}")
            elif msg_type == 'hmi_response':
                logger.info(f"Response from HMI: {msg.get('data', '')}")
        except json.JSONDecodeError:
            logger.info(f"Raw message from ESP32: {message}")
            
    def send_command(self, command: Dict[str, Any]) -> bool:
        if not self.connected or not self.client_socket:
            logger.warning("No ESP32 connection available")
            return False
        try:
            message = json.dumps(command) + "\n"
            self.client_socket.send(message.encode('utf-8'))
            logger.info(f"Sent command: {command}")
            return True
        except Exception as e:
            logger.error(f"Failed to send command: {e}")
            self.connected = False
            return False
            
    def get_status(self) -> Dict[str, Any]:
        return {
            "connected": self.connected,
            "client_address": str(self.client_address) if self.client_address else None,
            "server_port": self.port
        }
        
    def stop(self):
        self.running = False
        self.connected = False
        if self.client_socket:
            try:
                self.client_socket.close()
            except:
                pass
        if self.server_socket:
            try:
                self.server_socket.close()
            except:
                pass