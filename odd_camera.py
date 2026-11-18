"""
ODD See Me — Landscape Camera Mirror Overlay
Provides a real-time, non-recording live camera preview so the user can see their face.
Clean, landscape liquid glass overlay with natural horizontal mirroring (mirror view).
"""
import sys
import os
import time
from typing import Optional

from PySide6.QtCore import (
    Qt, QTimer, QRect, QRectF, QPoint, QPointF, Signal, Property,
    QEasingCurve, QPropertyAnimation, QThread, QObject
)
from PySide6.QtGui import (
    QPainter, QColor, QBrush, QPen, QFont, QFontMetrics, QImage, QPixmap,
    QPainterPath, QCursor, QKeyEvent, QMouseEvent, QLinearGradient
)
from PySide6.QtWidgets import QWidget, QApplication

try:
    import cv2
    HAS_CV2 = True
except Exception:
    HAS_CV2 = False


class CameraThread(QThread):
    """
    Dedicated background capture thread that continuously reads camera frames,
    mirrors them horizontally, and emits thread-safe QImage frames to the UI.
    """
    frame_ready = Signal(QImage)
    error_occurred = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._running = False

    def run(self):
        if not HAS_CV2:
            self.error_occurred.emit("OpenCV (cv2) is not installed.")
            return

        self._running = True
        cap = None
        try:
            # 1. Try OpenCV native auto backend (CAP_ANY) first, then DirectShow (CAP_DSHOW) across indices 0 and 1
            for api in [cv2.CAP_ANY, cv2.CAP_DSHOW]:
                for idx in [0, 1]:
                    try:
                        c = cv2.VideoCapture(idx, api)
                        if c.isOpened():
                            c.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
                            c.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
                            ret, test_frame = c.read()
                            if ret and test_frame is not None:
                                cap = c
                                break
                            c.release()
                        else:
                            c.release()
                    except Exception:
                        pass
                if cap is not None:
                    break

            if not cap or not cap.isOpened():
                self.error_occurred.emit("Camera is in use or unavailable.")
                return

            while self._running:
                ret, frame = cap.read()
                if not ret or frame is None:
                    time.sleep(0.015)
                    continue

                # Mirror horizontally for natural mirror preview
                frame = cv2.flip(frame, 1)

                h, w, ch = frame.shape
                bytes_per_line = ch * w
                rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                # Create QImage and copy data so the buffer remains valid across threads
                q_img = QImage(rgb_frame.data, w, h, bytes_per_line, QImage.Format.Format_RGB888).copy()

                self.frame_ready.emit(q_img)

                # ~30-40 FPS loop
                time.sleep(0.025)

        except Exception as e:
            self.error_occurred.emit(str(e))
        finally:
            if cap is not None:
                try:
                    cap.release()
                except Exception:
                    pass

    def stop(self):
        self._running = False
        self.wait(800)


class SeeMeOverlay(QWidget):
    """
    Landscape floating camera mirror overlay for ODD.
    Opens on 'see me' command, mirrors horizontally so user sees themselves naturally,
    with no photo taking or recording features.
    """
    _instance: Optional["SeeMeOverlay"] = None

    @classmethod
    def instance(cls, parent=None) -> "SeeMeOverlay":
        if cls._instance is None:
            cls._instance = SeeMeOverlay(parent=parent)
        return cls._instance

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, False)

        # Landscape 16:10 dimensions
        self.overlay_width = 560
        self.overlay_height = 350
        self.setFixedSize(self.overlay_width, self.overlay_height)

        # Camera state
        self.camera_thread: Optional[CameraThread] = None
        self.current_frame_img: Optional[QImage] = None
        self.camera_error: Optional[str] = None

        # Dragging support
        self._is_dragging = False
        self._drag_start_pos = QPoint()

        # UI state
        self._close_hover = False
        self._opacity: float = 0.0
        self._hint_visible_until: float = 0.0

        # Fade animations
        self.anim = QPropertyAnimation(self, b"overlay_opacity")
        self.anim.setDuration(220)
        self.anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        self._close_btn_rect = QRectF(self.overlay_width - 36, 12, 24, 24)

    def get_overlay_opacity(self) -> float:
        return self._opacity

    def set_overlay_opacity(self, val: float):
        self._opacity = max(0.0, min(1.0, float(val)))
        self.update()

    overlay_opacity = Property(float, get_overlay_opacity, set_overlay_opacity)

    def open_overlay(self):
        """Opens and positions the See Me overlay and starts the live camera preview"""
        # Position at top center of current active monitor screen (matching ODD overlay)
        screen = QApplication.screenAt(QCursor.pos()) or QApplication.primaryScreen()
        if screen:
            scr_geo = screen.geometry()
            cx = scr_geo.x() + (scr_geo.width() - self.overlay_width) // 2
            cy = scr_geo.y() + 14
            self.move(cx, cy)

        self._hint_visible_until = time.time() + 4.0
        self.current_frame_img = None
        self.camera_error = None

        self._start_camera()

        self.anim.stop()
        self.anim.setStartValue(self._opacity)
        self.anim.setEndValue(1.0)
        self.show()
        self.raise_()
        self.activateWindow()
        self.anim.start()

    def close_overlay(self):
        """Stops the camera and smoothly closes the overlay"""
        self._stop_camera()
        self.anim.stop()
        self.anim.setStartValue(self._opacity)
        self.anim.setEndValue(0.0)
        self.anim.finished.connect(self._on_close_finished)
        self.anim.start()

    def _on_close_finished(self):
        try:
            self.anim.finished.disconnect(self._on_close_finished)
        except Exception:
            pass
        self.hide()
        self.current_frame_img = None

    def _start_camera(self):
        self._stop_camera()
        self.camera_thread = CameraThread(self)
        self.camera_thread.frame_ready.connect(self._on_frame_ready)
        self.camera_thread.error_occurred.connect(self._on_camera_error)
        self.camera_thread.start()

    def _stop_camera(self):
        if self.camera_thread is not None:
            self.camera_thread.stop()
            self.camera_thread = None

    def _on_frame_ready(self, q_img: QImage):
        self.current_frame_img = q_img
        self.camera_error = None
        self.update()

    def _on_camera_error(self, err_msg: str):
        self.camera_error = err_msg
        self.update()

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() == Qt.Key.Key_Escape:
            self.close_overlay()
            event.accept()
        else:
            super().keyPressEvent(event)

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position() if hasattr(event, 'position') else event.pos()
            if self._close_btn_rect.contains(pos):
                self.close_overlay()
                event.accept()
                return
            self._is_dragging = True
            self._drag_start_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft() if hasattr(event, 'globalPosition') else event.globalPos() - self.frameGeometry().topLeft()
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        pos = event.position() if hasattr(event, 'position') else event.pos()
        is_hover = self._close_btn_rect.contains(pos)
        if is_hover != self._close_hover:
            self._close_hover = is_hover
            self.setCursor(Qt.CursorShape.PointingHandCursor if is_hover else Qt.CursorShape.ArrowCursor)
            self.update()

        if self._is_dragging and event.buttons() & Qt.MouseButton.LeftButton:
            cur_global = event.globalPosition().toPoint() if hasattr(event, 'globalPosition') else event.globalPos()
            self.move(cur_global - self._drag_start_pos)
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        self._is_dragging = False
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent):
        self.close_overlay()
        event.accept()

    def paintEvent(self, event):
        if self._opacity <= 0.005:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        painter.setOpacity(self._opacity)

        w = self.width()
        h = self.height()
        r_outer = 22.0

        # 1. Background dark translucent liquid container
        bg_rect = QRectF(1, 1, w - 2, h - 2)
        painter.setBrush(QBrush(QColor(18, 18, 22, 240)))
        painter.setPen(QPen(QColor(255, 255, 255, 30), 1.2))
        painter.drawRoundedRect(bg_rect, r_outer, r_outer)

        # 2. Camera Video Surface (with 6px padding inside container)
        margin = 6.0
        vid_rect = QRectF(margin, margin, w - 2 * margin, h - 2 * margin)
        r_vid = 18.0

        clip_path = QPainterPath()
        clip_path.addRoundedRect(vid_rect, r_vid, r_vid)

        painter.save()
        painter.setClipPath(clip_path)

        if self.current_frame_img and not self.current_frame_img.isNull():
            # Natural center-crop to preserve facial proportions
            img_w = self.current_frame_img.width()
            img_h = self.current_frame_img.height()
            target_ratio = vid_rect.width() / vid_rect.height()
            img_ratio = img_w / img_h
            if img_ratio > target_ratio:
                crop_w = int(img_h * target_ratio)
                src_rect = QRect((img_w - crop_w) // 2, 0, crop_w, img_h)
            else:
                crop_h = int(img_w / target_ratio)
                src_rect = QRect(0, (img_h - crop_h) // 2, img_w, crop_h)

            painter.drawImage(vid_rect, self.current_frame_img, QRectF(src_rect))
        else:
            # Video loading / connecting state
            painter.setBrush(QBrush(QColor(12, 12, 16)))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRect(vid_rect)

            painter.setFont(QFont("Segoe UI Variable Text", 10.5, QFont.Weight.DemiBold))
            painter.setPen(QColor(240, 240, 245, 200))
            if self.camera_error:
                msg = f"Camera: {self.camera_error}"
            else:
                msg = "Connecting to camera mirror..."
            painter.drawText(vid_rect, Qt.AlignmentFlag.AlignCenter, msg)

        # Soft dark gradient at top for header readability
        top_grad_rect = QRectF(margin, margin, w - 2 * margin, 50)
        grad = QLinearGradient(0, margin, 0, margin + 50)
        grad.setColorAt(0.0, QColor(0, 0, 0, 140))
        grad.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.setBrush(QBrush(grad))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRect(top_grad_rect)

        painter.restore()

        # 3. Inner border specular highlight
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(255, 255, 255, 45), 1.0))
        painter.drawRoundedRect(vid_rect, r_vid, r_vid)

        # 4. Top Right: Close '✕' Button
        btn_r = self._close_btn_rect
        if self._close_hover:
            painter.setBrush(QBrush(QColor(255, 255, 255, 45)))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(btn_r, 12, 12)
        else:
            painter.setBrush(QBrush(QColor(0, 0, 0, 110)))
            painter.setPen(QPen(QColor(255, 255, 255, 25), 0.8))
            painter.drawRoundedRect(btn_r, 12, 12)

        painter.setPen(QPen(QColor(255, 255, 255, 220 if self._close_hover else 180), 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        cx = btn_r.center().x()
        cy = btn_r.center().y()
        d = 3.5
        painter.drawLine(QPointF(cx - d, cy - d), QPointF(cx + d, cy + d))
        painter.drawLine(QPointF(cx + d, cy - d), QPointF(cx - d, cy + d))

        # 5. Bottom Helper Pill: 'Press ESC or click ✕ to close' (fades out after 4s)
        now = time.time()
        if now < self._hint_visible_until:
            hint_alpha = min(1.0, (self._hint_visible_until - now) / 1.0)
            hint_text = "Press ESC or click ✕ to close"
            painter.setFont(QFont("Segoe UI Variable Text", 8.0))
            fm = QFontMetrics(painter.font())
            tw = fm.horizontalAdvance(hint_text)
            hint_w = tw + 24
            hint_h = 22
            hint_x = (w - hint_w) / 2.0
            hint_y = h - 32.0

            painter.save()
            painter.setOpacity(self._opacity * hint_alpha * 0.9)
            painter.setBrush(QBrush(QColor(0, 0, 0, 140)))
            painter.setPen(QPen(QColor(255, 255, 255, 20), 0.8))
            painter.drawRoundedRect(QRectF(hint_x, hint_y, hint_w, hint_h), 11, 11)

            painter.setPen(QColor(240, 240, 245, 210))
            painter.drawText(QRectF(hint_x, hint_y, hint_w, hint_h), Qt.AlignmentFlag.AlignCenter, hint_text)
            painter.restore()
