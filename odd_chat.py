"""
ODD Compatibility Shim for Legacy Chat references -> Redirects to ODD Nearby Share & Universal Sync Engine
"""

from typing import Dict, List, Optional, Any, Tuple
from PySide6.QtCore import QObject, Signal

from odd_share import NearbyShareManager, NearbyDevice, get_share_manager


class ChatProfile:
    def __init__(self, username: str = "", tag: str = "", peer_id: str = ""):
        mgr = get_share_manager()
        self.peer_id = mgr.device_id
        self.username = mgr.device_name
        self.tag = "LAN"
        self.status_message = "Nearby Share Active"

    @property
    def full_handle(self) -> str:
        return self.username

    def to_dict(self) -> dict:
        return {
            "peer_id": self.peer_id,
            "username": self.username,
            "tag": self.tag,
            "status_message": self.status_message
        }


class FriendItem:
    def __init__(self, handle: str, peer_id: str = "", status: str = "friend",
                 online_status: str = "online", last_ip: str = ""):
        self.handle = handle.strip()
        self.peer_id = peer_id
        self.status = status
        self.online_status = online_status
        self.last_ip = last_ip

    @property
    def username(self) -> str:
        return self.handle

    @property
    def tag(self) -> str:
        return "LAN"


class ChatManager(QObject):
    """Compatibility wrapper delegating to NearbyShareManager"""
    message_received = Signal(str, str, float)
    friend_request_received = Signal(str)
    friend_accepted = Signal(str)
    friends_changed = Signal()
    connection_status_changed = Signal(bool)

    _instance = None

    @classmethod
    def get_instance(cls, settings=None) -> "ChatManager":
        if cls._instance is None:
            cls._instance = ChatManager(settings or {})
        return cls._instance

    def __init__(self, settings: dict):
        super().__init__()
        self.settings = settings
        self.share_mgr = get_share_manager(settings)
        self.profile = ChatProfile()
        self.share_mgr.devices_changed.connect(self.friends_changed.emit)
        self.share_mgr.clipboard_received.connect(lambda from_d, text, ctype: self.message_received.emit(from_d, text, 6.0))

    def get_friends(self) -> List[FriendItem]:
        devices = self.share_mgr.get_nearby_devices()
        return [FriendItem(handle=d.device_name, peer_id=d.device_id, online_status="online" if d.is_online else "offline", last_ip=d.ip) for d in devices]

    def get_pending_received(self) -> List[FriendItem]:
        return []

    def send_ephemeral_message(self, target_handle: str, text: str, ttl_sec: float = 6.0) -> Tuple[bool, str]:
        devices = self.share_mgr.get_nearby_devices()
        matched = [d for d in devices if d.device_name.lower() == target_handle.lower()]
        if matched:
            return self.share_mgr.send_text_or_url(matched[0].ip, matched[0].tcp_port, text)
        elif devices:
            return self.share_mgr.send_text_or_url(devices[0].ip, devices[0].tcp_port, text)
        return False, "No nearby devices found"

    def send_friend_request(self, target_handle: str) -> Tuple[bool, str]:
        return True, "Device ready"

    def accept_friend_request(self, target_handle: str):
        pass

    def decline_friend_request(self, target_handle: str):
        pass

    def remove_friend(self, target_handle: str):
        pass

    def update_username(self, new_name: str, new_tag: Optional[str] = None):
        self.share_mgr.update_device_name(new_name)
        self.profile.username = self.share_mgr.device_name
