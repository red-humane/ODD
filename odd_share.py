"""
ODD Nearby Share & Universal Cross-Device Clipboard Sync Engine (ODD Drop)
- Zero-config LAN P2P discovery via UDP Broadcast (Port 45892)
- High-speed direct TCP data streaming (Port 45893)
- Universal Cross-Device Clipboard copy-paste syncing
- Quick Text, Link & Note Drop to nearby computers
- Zero internet server dependencies, 100% offline & local LAN speed
"""

import os
import sys
import json
import time
import uuid
import socket
import hashlib
import platform
import threading
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple

from PySide6.QtCore import QObject, Signal, QTimer
from PySide6.QtWidgets import QApplication

DEVICE_PROFILE_FILE = Path(os.path.expandvars(r"%APPDATA%\ODD\device_profile.json"))
NEARBY_DISCOVERY_PORT = 45892
NEARBY_TCP_PORT = 45893
ONLINE_TIMEOUT_SEC = 5.5


def get_local_ip() -> str:
    """Gets the best non-loopback local network IP of this machine"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.2)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        try:
            return socket.gethostbyname(socket.gethostname())
        except Exception:
            return "127.0.0.1"


def get_default_device_name() -> str:
    """Generates a friendly default name based on system hostname and username"""
    try:
        hostname = socket.gethostname().strip()
        if hostname and hostname.lower() != "localhost":
            return hostname
    except Exception:
        pass
    try:
        user = os.environ.get("USERNAME", "User").strip()
        return f"{user}'s PC"
    except Exception:
        return "ODD Device"


class NearbyDevice:
    """Represents a discovered peer device running ODD on the local network"""
    def __init__(self, device_id: str, device_name: str, device_type: str = "desktop",
                 ip: str = "127.0.0.1", tcp_port: int = NEARBY_TCP_PORT, last_seen: float = 0.0):
        self.device_id = device_id
        self.device_name = device_name.strip() or "Nearby Device"
        self.device_type = device_type  # 'desktop', 'laptop', 'tablet', 'phone'
        self.ip = ip
        self.tcp_port = tcp_port
        self.last_seen = last_seen or time.time()

    @property
    def is_online(self) -> bool:
        return (time.time() - self.last_seen) <= ONLINE_TIMEOUT_SEC

    @property
    def icon_symbol(self) -> str:
        return ""

    def to_dict(self) -> dict:
        return {
            "device_id": self.device_id,
            "device_name": self.device_name,
            "device_type": self.device_type,
            "ip": self.ip,
            "tcp_port": self.tcp_port,
            "last_seen": self.last_seen
        }

    @classmethod
    def from_dict(cls, d: dict) -> "NearbyDevice":
        return cls(
            device_id=d.get("device_id", ""),
            device_name=d.get("device_name", "Nearby Device"),
            device_type=d.get("device_type", "desktop"),
            ip=d.get("ip", "127.0.0.1"),
            tcp_port=d.get("tcp_port", NEARBY_TCP_PORT),
            last_seen=d.get("last_seen", time.time())
        )


class NearbyShareManager(QObject):
    """
    Core Manager for Nearby Share & Universal Cross-Device Clipboard Sync.
    - Broadcasts UDP beacons on LAN for instant zero-config discovery.
    - Runs a lightweight TCP socket server for receiving clipboard & dropped text.
    - Provides instant 1-click clipboard transmission to nearby devices.
    """
    device_discovered = Signal(object)              # NearbyDevice
    devices_changed = Signal()                      # Discovered device list updated
    clipboard_received = Signal(str, str, str)      # sender_name, content, content_type ('text', 'url', 'clip')
    transfer_status = Signal(str, bool, str)        # device_name, success, message

    _instance = None

    @classmethod
    def get_instance(cls, settings=None) -> "NearbyShareManager":
        if cls._instance is None:
            cls._instance = NearbyShareManager(settings or {})
        elif settings:
            cls._instance.settings = settings
        return cls._instance

    def __init__(self, settings: dict):
        super().__init__()
        self.settings = settings
        self.devices: Dict[str, NearbyDevice] = {}  # device_id -> NearbyDevice
        self._running = True
        self.local_ip = get_local_ip()
        self.device_id = self._load_or_create_device_id()
        self.device_name = self._load_or_create_device_name()
        self.device_type = "laptop" if "laptop" in platform.uname().node.lower() else "desktop"

        self._last_sent_hash = ""
        self._last_received_hash = ""
        self._last_clipboard_text = ""

        # Background Network Threads
        self._udp_broadcast_socket: Optional[socket.socket] = None
        self._udp_listen_socket: Optional[socket.socket] = None
        self._tcp_server_socket: Optional[socket.socket] = None

        self._start_network_services()

        # Periodic Beacon Timer (sends presence beacon every 2.0s)
        self.beacon_timer = QTimer(self)
        self.beacon_timer.setInterval(2000)
        self.beacon_timer.timeout.connect(self._send_beacon)
        self.beacon_timer.start()

        # Periodic Stale Sweep Timer (cleans up offline peers)
        self.sweep_timer = QTimer(self)
        self.sweep_timer.setInterval(2500)
        self.sweep_timer.timeout.connect(self._sweep_stale_devices)
        self.sweep_timer.start()

        # Clipboard Auto-Sync Poller
        self.clip_poll_timer = QTimer(self)
        self.clip_poll_timer.setInterval(800)
        self.clip_poll_timer.timeout.connect(self._poll_clipboard_auto_sync)
        self.clip_poll_timer.start()

    def _load_or_create_device_id(self) -> str:
        try:
            if DEVICE_PROFILE_FILE.exists():
                with open(DEVICE_PROFILE_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if data.get("device_id"):
                        return data["device_id"]
        except Exception:
            pass
        new_id = uuid.uuid4().hex[:12]
        self._save_profile(new_id, get_default_device_name())
        return new_id

    def _load_or_create_device_name(self) -> str:
        try:
            if DEVICE_PROFILE_FILE.exists():
                with open(DEVICE_PROFILE_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if data.get("device_name"):
                        return data["device_name"]
        except Exception:
            pass
        return get_default_device_name()

    def _save_profile(self, dev_id: str, dev_name: str):
        try:
            DEVICE_PROFILE_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(DEVICE_PROFILE_FILE, "w", encoding="utf-8") as f:
                json.dump({
                    "device_id": dev_id,
                    "device_name": dev_name,
                    "device_type": self.device_type
                }, f, indent=4)
        except Exception:
            pass

    def update_device_name(self, new_name: str):
        cleaned = new_name.strip()
        if cleaned:
            self.device_name = cleaned
            self._save_profile(self.device_id, self.device_name)
            self._send_beacon()

    # ------------------------------------------------------------------
    # Network Initialization & Listeners
    # ------------------------------------------------------------------
    def _start_network_services(self):
        # 1. UDP Listener for Beacons
        def udp_listener():
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                try:
                    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                except Exception:
                    pass
                sock.bind(("", NEARBY_DISCOVERY_PORT))
                self._udp_listen_socket = sock
                while self._running:
                    try:
                        data, addr = sock.recvfrom(4096)
                        if not data:
                            continue
                        self._handle_incoming_beacon(data, addr[0])
                    except Exception:
                        pass
            except Exception:
                pass

        t_udp = threading.Thread(target=udp_listener, daemon=True, name="ODD_UDP_Listener")
        t_udp.start()

        # 2. TCP Server for Direct Drops & Clipboard Sync
        def tcp_server():
            try:
                server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                server.bind(("", NEARBY_TCP_PORT))
                server.listen(10)
                self._tcp_server_socket = server
                while self._running:
                    try:
                        client, client_addr = server.accept()
                        client.settimeout(4.0)
                        threading.Thread(target=self._handle_tcp_client, args=(client, client_addr[0]), daemon=True).start()
                    except Exception:
                        pass
            except Exception:
                pass

        t_tcp = threading.Thread(target=tcp_server, daemon=True, name="ODD_TCP_Server")
        t_tcp.start()

        # Initial Beacon Send
        threading.Thread(target=self._send_beacon, daemon=True).start()

    def _send_beacon(self):
        """Broadcasts presence beacon across local network"""
        if not self._running:
            return
        try:
            if not self._udp_broadcast_socket:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                s.settimeout(0.5)
                self._udp_broadcast_socket = s

            beacon = {
                "type": "odd_nearby_beacon",
                "device_id": self.device_id,
                "device_name": self.device_name,
                "device_type": self.device_type,
                "tcp_port": NEARBY_TCP_PORT,
                "version": "1.0",
                "timestamp": time.time()
            }
            raw = json.dumps(beacon).encode("utf-8")
            self._udp_broadcast_socket.sendto(raw, ("<broadcast>", NEARBY_DISCOVERY_PORT))
            # Also send directly to subnet fallback
            self._udp_broadcast_socket.sendto(raw, ("255.255.255.255", NEARBY_DISCOVERY_PORT))
        except Exception:
            pass

    def _handle_incoming_beacon(self, raw_data: bytes, sender_ip: str):
        try:
            payload = json.loads(raw_data.decode("utf-8"))
            if payload.get("type") != "odd_nearby_beacon":
                return
            peer_id = payload.get("device_id")
            # Ignore self
            if not peer_id or peer_id == self.device_id:
                return

            name = payload.get("device_name", "Nearby Device")
            dtype = payload.get("device_type", "desktop")
            port = int(payload.get("tcp_port", NEARBY_TCP_PORT))

            now = time.time()
            if peer_id in self.devices:
                dev = self.devices[peer_id]
                dev.device_name = name
                dev.device_type = dtype
                dev.ip = sender_ip
                dev.tcp_port = port
                dev.last_seen = now
            else:
                new_dev = NearbyDevice(
                    device_id=peer_id,
                    device_name=name,
                    device_type=dtype,
                    ip=sender_ip,
                    tcp_port=port,
                    last_seen=now
                )
                self.devices[peer_id] = new_dev
                self.device_discovered.emit(new_dev)
                self.devices_changed.emit()
        except Exception:
            pass

    def _sweep_stale_devices(self):
        """Sweeps devices that have stopped broadcasting"""
        now = time.time()
        to_remove = []
        for dev_id, dev in self.devices.items():
            if now - dev.last_seen > (ONLINE_TIMEOUT_SEC * 2.5):
                to_remove.append(dev_id)
        if to_remove:
            for dev_id in to_remove:
                del self.devices[dev_id]
            self.devices_changed.emit()

    def get_nearby_devices(self) -> List[NearbyDevice]:
        """Returns list of online nearby devices sorted by name"""
        now = time.time()
        active = [d for d in self.devices.values() if (now - d.last_seen) <= ONLINE_TIMEOUT_SEC]
        active.sort(key=lambda d: d.device_name.lower())
        return active

    # ------------------------------------------------------------------
    # TCP Incoming Data Handler
    # ------------------------------------------------------------------
    def _handle_tcp_client(self, sock: socket.socket, client_ip: str):
        try:
            chunks = []
            while True:
                part = sock.recv(8192)
                if not part:
                    break
                chunks.append(part)
                if len(part) < 8192:
                    break
            raw_bytes = b"".join(chunks)
            if not raw_bytes:
                return

            payload = json.loads(raw_bytes.decode("utf-8"))
            msg_type = payload.get("type", "clipboard_sync")
            from_name = payload.get("from_device", "Nearby Device")
            content = payload.get("content", "")
            auto_copy = bool(payload.get("auto_copy", True))

            if not content:
                return

            content_hash = hashlib.md5(content.encode("utf-8")).hexdigest()
            # Prevent loop bounce
            if content_hash == self._last_sent_hash or content_hash == self._last_received_hash:
                return
            self._last_received_hash = content_hash
            self._last_clipboard_text = content

            # Auto place into local OS clipboard if enabled
            if auto_copy and self.settings.get("nearby_auto_copy_on_receive", True):
                try:
                    app = QApplication.instance()
                    if app:
                        cb = app.clipboard()
                        cb.setText(content)
                except Exception:
                    pass

            # Detect content type (URL vs multiline text vs code)
            content_type = "url" if content.startswith("http://") or content.startswith("https://") else "text"

            # Emit signal for overlay / Island HUD notification
            self.clipboard_received.emit(from_name, content, content_type)

            # Send back quick ACK
            sock.sendall(b'{"status": "ok"}')
        except Exception:
            pass
        finally:
            try:
                sock.close()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Data Transmission (Push Clipboard / Drop Text)
    # ------------------------------------------------------------------
    def send_clipboard_to_device(self, target_ip: str, target_port: int = NEARBY_TCP_PORT, content: Optional[str] = None) -> Tuple[bool, str]:
        """Sends clipboard content directly to a specific device on LAN"""
        if content is None:
            try:
                content = QApplication.clipboard().text().strip()
            except Exception:
                content = ""

        if not content:
            return False, "Clipboard is empty"

        payload = {
            "type": "clipboard_sync",
            "from_device": self.device_name,
            "from_ip": self.local_ip,
            "content": content,
            "auto_copy": True,
            "timestamp": time.time()
        }

        self._last_sent_hash = hashlib.md5(content.encode("utf-8")).hexdigest()

        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(2.5)
            s.connect((target_ip, target_port))
            raw = json.dumps(payload).encode("utf-8")
            s.sendall(raw)
            s.close()
            self.transfer_status.emit(target_ip, True, "Sent successfully")
            return True, "Transferred successfully! \u2713"
        except Exception as e:
            self.transfer_status.emit(target_ip, False, str(e))
            return False, f"Could not reach {target_ip}"

    def broadcast_clipboard_to_all(self, content: Optional[str] = None) -> Tuple[int, str]:
        """Pushes current clipboard or specified text to all discovered online devices"""
        devices = self.get_nearby_devices()
        if not devices:
            return 0, "No nearby ODD devices found on this network"

        if content is None:
            try:
                content = QApplication.clipboard().text().strip()
            except Exception:
                content = ""

        if not content:
            return 0, "Clipboard is empty"

        sent_count = 0
        for d in devices:
            ok, _ = self.send_clipboard_to_device(d.ip, d.tcp_port, content)
            if ok:
                sent_count += 1

        if sent_count > 0:
            return sent_count, f"Pushed to {sent_count} device{'s' if sent_count != 1 else ''}! \u2713"
        return 0, "Failed to connect to nearby devices"

    def send_text_or_url(self, target_ip: str, target_port: int, text: str) -> Tuple[bool, str]:
        """Drops text, link, or notes directly to target device"""
        return self.send_clipboard_to_device(target_ip, target_port, text)

    # ------------------------------------------------------------------
    # Automatic System Clipboard Poller
    # ------------------------------------------------------------------
    def _poll_clipboard_auto_sync(self):
        """If auto-sync is enabled in settings, pushes local clipboard changes to LAN peers"""
        if not self.settings.get("nearby_auto_sync_clipboard", False):
            return

        try:
            app = QApplication.instance()
            if not app:
                return
            curr_text = app.clipboard().text().strip()
            if not curr_text or curr_text == self._last_clipboard_text:
                return

            # Check if this was just received
            curr_hash = hashlib.md5(curr_text.encode("utf-8")).hexdigest()
            if curr_hash == self._last_received_hash:
                return

            self._last_clipboard_text = curr_text
            self._last_sent_hash = curr_hash

            # Broadcast to active peers
            devices = self.get_nearby_devices()
            if devices:
                for d in devices:
                    threading.Thread(target=self.send_clipboard_to_device, args=(d.ip, d.tcp_port, curr_text), daemon=True).start()
        except Exception:
            pass


# Singleton instance accessor
def get_share_manager(settings=None) -> NearbyShareManager:
    return NearbyShareManager.get_instance(settings)
