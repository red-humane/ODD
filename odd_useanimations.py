import os
import sys
import json
from pathlib import Path
from typing import Optional, Dict, Tuple
from PySide6.QtCore import QObject, QTimer, Signal, Qt, QByteArray, QPointF, QRectF
from PySide6.QtGui import QPainter, QPixmap, QColor
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QWidget

_ANIM_DATA: Optional[Dict] = None
_PIXMAP_CACHE: Dict[Tuple[str, int, str, int], QPixmap] = {}
_RENDERER_CACHE: Dict[Tuple[str, int, str], QSvgRenderer] = {}

ALIAS_MAP = {
    "smartphone": "smartphone",
    "android": "smartphone",
    "phone": "smartphone",
    "phone_mirror": "smartphone",
    "android_phone": "smartphone",
    "mirror": "smartphone",
    
    "wifi": "wifi",
    "wifi_on": "wifi",
    "wifion": "wifi",
    
    "wifioff": "wifiOff",
    "wifi_off": "wifiOff",
    
    "bluetooth": "bluetooth",
    "bt": "bluetooth",
    
    "download": "download",
    "downloading": "download",
    
    "file": "fileText",
    "filetext": "fileText",
    "file_text": "fileText",
    "doc": "fileText",
    "document": "fileText",
    
    "folder": "folderPlus",
    "folderplus": "folderPlus",
    "folder_plus": "folderPlus",
    
    "copy": "copy",
    "copied": "copy",
    "clipboard": "copy",
    
    "volume": "volume",
    "sound": "volume",
    "audio": "volume",
    "mute": "volume",
    "unmute": "volume",
    "sound_effects": "volume",
    "sound_fx": "volume",
    
    "camera": "camera",
    "lens": "camera",
    "google_lens": "camera",
    
    "battery": "battery",
    
    "batterycharging": "batteryCharging",
    "battery_charging": "batteryCharging",
    "charging": "batteryCharging",
    
    "scissors": "scissors",
    "snip": "scissors",
    "screenshot": "scissors",
    "screen_snip": "scissors",
    
    "clock": "clock",
    "time": "clock",
    "all_time": "clock",
    "infomatic": "clock",
    "history": "clock",
}

def get_animations_file_path() -> Path:
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        base = Path(sys._MEIPASS)
    else:
        base = Path(__file__).resolve().parent
    return base / "assets" / "animations" / "useanimations.json"

def load_animations() -> Dict:
    global _ANIM_DATA
    if _ANIM_DATA is not None:
        return _ANIM_DATA
    p = get_animations_file_path()
    if p.exists():
        try:
            with open(p, "r", encoding="utf-8") as f:
                _ANIM_DATA = json.load(f)
                return _ANIM_DATA
        except Exception:
            pass
    _ANIM_DATA = {}
    return _ANIM_DATA

def canonical_anim_name(name: str) -> str:
    clean = str(name).lower().strip().replace("-", "_")
    return ALIAS_MAP.get(clean, clean)

def get_animation_info(name: str) -> Optional[Dict]:
    data = load_animations()
    canonical = canonical_anim_name(name)
    return data.get(canonical)

def get_total_frames(name: str) -> int:
    info = get_animation_info(name)
    return len(info["frames"]) if info and "frames" in info else 1

def get_animation_fps(name: str) -> int:
    info = get_animation_info(name)
    return int(info.get("fps", 30)) if info else 30

def get_animation_interaction(name: str) -> str:
    info = get_animation_info(name)
    return str(info.get("interaction", "hover-replay")) if info else "hover-replay"

def get_useanimation_pixmap(name: str, frame_idx: int = 0, color: str = "#FFFFFF", size: int = 32) -> Optional[QPixmap]:
    """
    Renders a specific frame of a react-useanimations icon with the requested color and size.
    Cached for zero CPU overhead on repeated draws.
    """
    info = get_animation_info(name)
    if not info or not info.get("frames"):
        return None
    canonical = info["name"]
    frames = info["frames"]
    total = len(frames)
    idx = max(0, min(total - 1, int(frame_idx)))
    
    clean_color = str(color).upper().strip()
    key = (canonical, idx, clean_color, int(size))
    if key in _PIXMAP_CACHE:
        return _PIXMAP_CACHE[key]
        
    svg_raw = frames[idx]
    svg_colored = svg_raw.replace("{color}", clean_color)
    
    renderer = QSvgRenderer(QByteArray(svg_colored.encode("utf-8")))
    if not renderer.isValid():
        return None
        
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    renderer.render(p)
    p.end()
    
    _PIXMAP_CACHE[key] = pix
    return pix


class UseAnimationPlayer(QObject):
    """
    Stateful animation player that handles hover-replay, click-toggle, and loop interactions
    matching react-useanimations behavior at 30/60 FPS.
    """
    frame_changed = Signal(int)
    finished = Signal()

    def __init__(self, animation_name: str, parent=None):
        super().__init__(parent)
        self.animation_name = canonical_anim_name(animation_name)
        self.total_frames = get_total_frames(self.animation_name)
        self.fps = get_animation_fps(self.animation_name)
        self.interaction = get_animation_interaction(self.animation_name)
        
        self.current_frame = 0
        self.direction = 1
        self.is_playing = False
        self.is_active = False
        
        self.timer = QTimer(self)
        interval = max(10, int(1000.0 / self.fps))
        self.timer.setInterval(interval)
        self.timer.timeout.connect(self._on_tick)

    def set_animation(self, name: str):
        c = canonical_anim_name(name)
        if self.animation_name != c:
            self.stop()
            self.animation_name = c
            self.total_frames = get_total_frames(c)
            self.fps = get_animation_fps(c)
            self.interaction = get_animation_interaction(c)
            self.timer.setInterval(max(10, int(1000.0 / self.fps)))
            self.current_frame = 0
            self.frame_changed.emit(0)

    def play(self):
        if self.total_frames <= 1:
            return
        self.is_playing = True
        if not self.timer.isActive():
            self.timer.start()

    def replay(self):
        self.current_frame = 0
        self.direction = 1
        self.play()
        self.frame_changed.emit(0)

    def stop(self):
        self.is_playing = False
        if self.timer.isActive():
            self.timer.stop()

    def toggle(self):
        self.is_active = not self.is_active
        if self.is_active:
            self.direction = 1
        else:
            self.direction = -1
        self.play()

    def set_active(self, active: bool, animate: bool = True):
        self.is_active = bool(active)
        if animate:
            self.direction = 1 if self.is_active else -1
            self.play()
        else:
            self.stop()
            self.current_frame = (self.total_frames - 1) if self.is_active else 0
            self.frame_changed.emit(self.current_frame)

    def handle_hover_enter(self):
        if self.interaction in ("hover-replay", "hover"):
            self.replay()
        elif self.interaction == "click-toggle":
            # Subtle preview or play
            pass

    def handle_hover_leave(self):
        if self.interaction == "hover":
            self.direction = -1
            self.play()

    def handle_click(self):
        if self.interaction == "click-toggle":
            self.toggle()
        else:
            self.replay()

    def _on_tick(self):
        next_frame = self.current_frame + self.direction
        if next_frame >= self.total_frames:
            if self.interaction == "click-toggle":
                self.current_frame = self.total_frames - 1
                self.stop()
                self.finished.emit()
            else:
                self.current_frame = 0
                self.stop()
                self.finished.emit()
        elif next_frame < 0:
            self.current_frame = 0
            self.stop()
            self.finished.emit()
        else:
            self.current_frame = next_frame
            
        self.frame_changed.emit(self.current_frame)


class UseAnimationWidget(QWidget):
    """
    Lightweight, drop-in PySide6 widget representing <UseAnimations animation={...} size={32} />
    Automatically plays on hover or click according to user settings.
    """
    clicked = Signal()

    def __init__(self, animation_name: str, size: int = 32, color: str = "#FFFFFF", parent=None):
        super().__init__(parent)
        self.anim_size = int(size)
        self.color = str(color)
        self.setFixedSize(self.anim_size, self.anim_size)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        
        self.player = UseAnimationPlayer(animation_name, self)
        self.player.frame_changed.connect(lambda _: self.update())

    def set_animation(self, name: str):
        self.player.set_animation(name)
        self.update()

    def set_color(self, color: str):
        if self.color != color:
            self.color = color
            self.update()

    def set_active(self, active: bool, animate: bool = True):
        self.player.set_active(active, animate=animate)

    def replay(self):
        self.player.replay()

    def enterEvent(self, event):
        super().enterEvent(event)
        self.player.handle_hover_enter()

    def leaveEvent(self, event):
        super().leaveEvent(event)
        self.player.handle_hover_leave()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.player.handle_click()
            self.clicked.emit()
        super().mousePressEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        try:
            pix = get_useanimation_pixmap(
                self.player.animation_name,
                frame_idx=self.player.current_frame,
                color=self.color,
                size=self.anim_size
            )
            if pix and not pix.isNull():
                painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
                painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
                dx = int((self.width() - pix.width()) / 2.0)
                dy = int((self.height() - pix.height()) / 2.0)
                painter.drawPixmap(dx, dy, pix)
        finally:
            painter.end()
