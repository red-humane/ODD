"""
ODD In-App Update Engine
- Queries GitHub Releases (https://api.github.com/repos/red-humane/ODD/releases)
- Non-blocking asynchronous checks & background interval scheduler
- Minimal, non-intrusive notification via Dynamic Island and Spotlight Overlay
- Seamless in-app download with Dynamic Island live activity progress ring
- One-click restart and upgrade execution
"""

import os
import sys
import json
import time
import re
import urllib.request
import urllib.error
import subprocess
from pathlib import Path
from dataclasses import dataclass
from typing import Optional, List, Tuple, Dict, Any

from PySide6.QtCore import QObject, Signal, QThread, QTimer, Qt
from PySide6.QtWidgets import QApplication, QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton

CURRENT_VERSION = "5.0.2"
GITHUB_REPO = "red-humane/ODD"
RELEASES_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases"
WEBSITE_URL = "https://humn.space/"
UPDATE_TEMP_DIR = Path(os.path.expandvars(r"%LOCALAPPDATA%\ODD\updates"))


@dataclass
class ReleaseInfo:
    tag_name: str
    version_display: str
    title: str
    body: str
    published_at: str
    html_url: str
    setup_download_url: str
    setup_file_size: int
    is_newer: bool


def parse_version_digits(ver_str: str) -> List[int]:
    """Extracts numeric version tokens e.g. 'v1.0.1' -> [1, 0, 1]"""
    clean = ver_str.lstrip("vV").strip()
    digits = re.findall(r"\d+", clean)
    return [int(d) for d in digits] if digits else []


def compare_versions(remote_tag: str, current_ver: str) -> bool:
    """
    Compares the GitHub remote release tag with the locally installed app version.
    - If remote and current version match (e.g. both are 1.0.0 or v1.0.0), returns False (no update).
    - If they do not match (e.g. remote is newer or distinct), returns True (update available).
    """
    remote_clean = remote_tag.lstrip("vV").strip().lower()
    current_clean = current_ver.lstrip("vV").strip().lower()

    if not remote_clean or not current_clean or remote_clean == current_clean:
        return False

    r_parts = parse_version_digits(remote_clean)
    c_parts = parse_version_digits(current_clean)

    if r_parts and c_parts:
        max_len = max(len(r_parts), len(c_parts))
        r_parts_padded = r_parts + [0] * (max_len - len(r_parts))
        c_parts_padded = c_parts + [0] * (max_len - len(c_parts))
        if tuple(r_parts_padded) == tuple(c_parts_padded):
            return False
        return tuple(r_parts_padded) > tuple(c_parts_padded)

    # Non-numeric tags (e.g. 'test' vs '1.0.0'): if distinct, show update
    return remote_clean != current_clean


def fetch_latest_release(timeout: int = 8) -> Optional[ReleaseInfo]:
    """
    Queries GitHub API to find the latest release or active release tag for red-humane/ODD.
    """
    try:
        req = urllib.request.Request(
            RELEASES_API_URL,
            headers={
                "User-Agent": "ODD-Desktop-App-Updater",
                "Accept": "application/vnd.github.v3+json"
            }
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                return None
            data = json.loads(resp.read().decode("utf-8"))

        if not data or not isinstance(data, list):
            return None

        candidate_releases = []
        for rel in data:
            tag = rel.get("tag_name", "").strip()
            if not tag:
                continue

            title = rel.get("name", "") or tag
            body = rel.get("body", "").strip() or "General improvements and performance enhancements."
            pub_at = rel.get("published_at", "")
            html_url = rel.get("html_url", f"https://github.com/{GITHUB_REPO}/releases/tag/{tag}")

            setup_url = ""
            setup_size = 0

            # Search for setup or exe in assets
            for asset in rel.get("assets", []):
                name = asset.get("name", "").lower()
                if "setup" in name and name.endswith(".exe"):
                    setup_url = asset.get("browser_download_url", "")
                    setup_size = asset.get("size", 0)
                    break
                elif name.endswith(".exe") and not setup_url:
                    setup_url = asset.get("browser_download_url", "")
                    setup_size = asset.get("size", 0)

            # Fallback to direct asset download URL
            if not setup_url:
                setup_url = f"https://github.com/{GITHUB_REPO}/releases/download/{tag}/ODD_Setup.exe"

            is_new = compare_versions(tag, CURRENT_VERSION)
            candidate_releases.append(ReleaseInfo(
                tag_name=tag,
                version_display=tag if tag.startswith("v") else f"v{tag}",
                title=title,
                body=body,
                published_at=pub_at,
                html_url=html_url,
                setup_download_url=setup_url,
                setup_file_size=setup_size,
                is_newer=is_new
            ))

        if not candidate_releases:
            return None

        # Find the highest version among candidates
        best_release = candidate_releases[0]
        for candidate in candidate_releases[1:]:
            if compare_versions(candidate.tag_name, best_release.tag_name):
                best_release = candidate

        return best_release
    except Exception as e:
        print(f"[ODD Updater] Check failed: {e}")
        return None


class CheckUpdateWorker(QThread):
    finished_check = Signal(object, bool, str)  # (Optional[ReleaseInfo], manual, error_msg)

    def __init__(self, manual: bool = False, timeout: int = 8):
        super().__init__()
        self.manual = manual
        self.timeout = timeout

    def run(self):
        try:
            rel = fetch_latest_release(timeout=self.timeout)
            if rel:
                self.finished_check.emit(rel, self.manual, "")
            else:
                self.finished_check.emit(None, self.manual, "Unable to reach update server.")
        except Exception as e:
            self.finished_check.emit(None, self.manual, str(e))


class DownloadUpdateWorker(QThread):
    progress_changed = Signal(int, int, float, str)  # (downloaded_bytes, total_bytes, percent, speed_str)
    download_completed = Signal(str)                 # setup_exe_path
    download_failed = Signal(str)                    # error_msg

    def __init__(self, download_url: str, expected_size: int = 0):
        super().__init__()
        self.download_url = download_url
        self.expected_size = expected_size
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        try:
            UPDATE_TEMP_DIR.mkdir(parents=True, exist_ok=True)
            target_path = UPDATE_TEMP_DIR / "ODD_Setup.exe"

            # Clean previous partial downloads
            if target_path.exists():
                try:
                    target_path.unlink()
                except Exception:
                    pass

            req = urllib.request.Request(
                self.download_url,
                headers={"User-Agent": "ODD-Desktop-App-Updater"}
            )

            with urllib.request.urlopen(req, timeout=30) as resp:
                total_len = resp.headers.get("Content-Length")
                total_bytes = int(total_len) if total_len and total_len.isdigit() else self.expected_size

                downloaded = 0
                block_size = 64 * 1024
                start_time = time.time()
                last_update_time = 0.0

                with open(target_path, "wb") as f:
                    while True:
                        if self._cancelled:
                            return
                        chunk = resp.read(block_size)
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)

                        cur_time = time.time()
                        if cur_time - last_update_time >= 0.1 or (total_bytes > 0 and downloaded >= total_bytes):
                            last_update_time = cur_time
                            elapsed = max(0.001, cur_time - start_time)
                            speed_bps = downloaded / elapsed
                            speed_str = f"{speed_bps / (1024 * 1024):.1f} MB/s" if speed_bps >= 1024 * 1024 else f"{speed_bps / 1024:.0f} KB/s"
                            pct = (downloaded / total_bytes * 100.0) if total_bytes > 0 else -1.0
                            self.progress_changed.emit(downloaded, total_bytes, pct, speed_str)

            if target_path.exists() and target_path.stat().st_size > 1000:
                self.download_completed.emit(str(target_path))
            else:
                self.download_failed.emit("Downloaded installer file is invalid or empty.")
        except Exception as e:
            self.download_failed.emit(str(e))


class UpdateManager(QObject):
    """
    Central Singleton Coordinator for ODD Updates.
    Manages background checks, minimal notifications, and in-app download execution.
    """
    update_available = Signal(object)             # ReleaseInfo
    update_not_available = Signal(bool)           # manual
    update_check_failed = Signal(str, bool)       # (error_msg, manual)
    download_progress = Signal(int, int, float, str)
    download_finished = Signal(str, object)       # (setup_path, ReleaseInfo)
    download_failed = Signal(str)

    _instance = None

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = UpdateManager()
        return cls._instance

    def __init__(self):
        super().__init__()
        self.current_version = CURRENT_VERSION
        self.latest_release: Optional[ReleaseInfo] = None
        self.is_checking = False
        self.is_downloading = False
        self.downloaded_setup_path: Optional[str] = None

        self._check_worker: Optional[CheckUpdateWorker] = None
        self._download_worker: Optional[DownloadUpdateWorker] = None

        # Auto-check schedule: starts 4 seconds after launch, then every 6 hours
        self._periodic_timer = QTimer(self)
        self._periodic_timer.setInterval(6 * 60 * 60 * 1000)  # 6 hours
        self._periodic_timer.timeout.connect(lambda: self.check_for_updates(manual=False))

        # Initial delayed check
        QTimer.singleShot(4500, lambda: self.check_for_updates(manual=False))
        self._periodic_timer.start()

    def check_for_updates(self, manual: bool = False):
        if self.is_checking:
            return
        if not manual:
            try:
                from odd_settings import load_settings
                cfg = load_settings()
                if not cfg.get("enable_auto_update", True):
                    return
            except Exception:
                pass
        self.is_checking = True
        self._check_worker = CheckUpdateWorker(manual=manual)
        self._check_worker.finished_check.connect(self._on_check_finished)
        self._check_worker.start()

    def _on_check_finished(self, rel: Optional[ReleaseInfo], manual: bool, error_msg: str):
        self.is_checking = False
        if rel:
            self.latest_release = rel
            if rel.is_newer:
                self.update_available.emit(rel)
                try:
                    from odd_settings import load_settings
                    cfg = load_settings()
                    if cfg.get("enable_auto_update", True) and not self.is_downloading and not self.ready_to_install:
                        # Auto-update is enabled: Ask whether to update or not instead of updating automatically
                        QTimer.singleShot(600, lambda: self.ask_update_confirmation(rel))
                except Exception as ex:
                    print(f"[ODD Auto-Update] Prompt error: {ex}")
            else:
                self.update_not_available.emit(manual)
        else:
            self.update_check_failed.emit(error_msg, manual)

_ACTIVE_UPDATE_DIALOG = None

class ODDUpdateConfirmationDialog(QDialog):
    """
    Standalone top-level Update Confirmation Dialog:
    - Never tied to or owned by odd_overlay HWND so it NEVER hides when ODD search hides.
    - Matches Windows 11 Fluent dark styling.
    - Stays on top and remains interactive until user clicks Update Now or Later.
    """
    def __init__(self, rel: ReleaseInfo, on_confirmed=None, on_cancelled=None):
        super().__init__(None)
        self.rel = rel
        self.on_confirmed = on_confirmed
        self.on_cancelled = on_cancelled

        self.setWindowTitle("ODD Update Available")
        self.setWindowFlags(
            Qt.WindowType.Window |
            Qt.WindowType.WindowTitleHint |
            Qt.WindowType.WindowSystemMenuHint |
            Qt.WindowType.WindowCloseButtonHint |
            Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setFixedSize(450, 270)
        self.setStyleSheet("""
            QDialog {
                background-color: #1a1a20;
                border: 1px solid rgba(255, 255, 255, 0.16);
                border-radius: 12px;
            }
            QLabel {
                color: #f1f5f9;
                font-family: 'Segoe UI Variable Display', 'Segoe UI', -apple-system, sans-serif;
            }
            QPushButton#btnUpdate {
                background-color: #00e5ff;
                color: #050b14;
                font-weight: 700;
                font-size: 13px;
                border: none;
                border-radius: 8px;
                padding: 8px 22px;
            }
            QPushButton#btnUpdate:hover {
                background-color: #38bdf8;
            }
            QPushButton#btnLater {
                background-color: rgba(255, 255, 255, 0.08);
                color: #cbd5e1;
                font-weight: 600;
                font-size: 13px;
                border: 1px solid rgba(255, 255, 255, 0.15);
                border-radius: 8px;
                padding: 8px 22px;
            }
            QPushButton#btnLater:hover {
                background-color: rgba(255, 255, 255, 0.14);
                color: #ffffff;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)

        lbl_title = QLabel(f"A new version of ODD ({rel.version_display}) is available.", self)
        lbl_title.setStyleSheet("font-size: 15px; font-weight: 700; color: #ffffff;")
        layout.addWidget(lbl_title)

        body_text = rel.body.strip() if rel.body else "General improvements and performance enhancements."
        if len(body_text) > 180:
            body_text = body_text[:180] + "..."
        lbl_body = QLabel(body_text, self)
        lbl_body.setStyleSheet("font-size: 13px; color: #94a3b8;")
        lbl_body.setWordWrap(True)
        layout.addWidget(lbl_body)

        lbl_ver = QLabel(f"Current version: v{CURRENT_VERSION}\nNew version: {rel.version_display}\n\nWould you like to update now?", self)
        lbl_ver.setStyleSheet("font-size: 12px; color: #cbd5e1; line-height: 1.4;")
        layout.addWidget(lbl_ver)

        layout.addStretch(1)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        btn_row.setSpacing(10)

        self.btn_update = QPushButton("Update Now", self)
        self.btn_update.setObjectName("btnUpdate")
        self.btn_update.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_update.clicked.connect(self._do_update)
        btn_row.addWidget(self.btn_update)

        self.btn_later = QPushButton("Later", self)
        self.btn_later.setObjectName("btnLater")
        self.btn_later.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_later.clicked.connect(self._do_later)
        btn_row.addWidget(self.btn_later)

        layout.addLayout(btn_row)

        # Detach Win32 window ownership so odd_overlay.hide() NEVER hides this dialog
        try:
            import ctypes
            hwnd = int(self.winId())
            ctypes.windll.user32.SetWindowLongPtrW(hwnd, -8, 0)  # GWLP_HWNDPARENT = -8
        except Exception:
            pass

    def _do_update(self):
        self.close()
        if self.on_confirmed:
            self.on_confirmed()

    def _do_later(self):
        self.close()
        if self.on_cancelled:
            self.on_cancelled()

    def ask_update_confirmation(self, rel: ReleaseInfo, parent=None):
        """
        Prompts the user whether to update or not when a new release is available.
        Runs as an independent top-level window so hiding ODD search NEVER hides this dialog.
        """
        global _ACTIVE_UPDATE_DIALOG
        if _ACTIVE_UPDATE_DIALOG is not None:
            try:
                if _ACTIVE_UPDATE_DIALOG.isVisible():
                    _ACTIVE_UPDATE_DIALOG.raise_()
                    _ACTIVE_UPDATE_DIALOG.activateWindow()
                    return
            except Exception:
                _ACTIVE_UPDATE_DIALOG = None

        def _handle_update():
            print(f"[ODD Update] User confirmed update to {rel.version_display}. Starting download...")
            self.start_download(rel)

        def _handle_later():
            print(f"[ODD Update] User chose to postpone update to {rel.version_display}.")

        dialog = ODDUpdateConfirmationDialog(rel, on_confirmed=_handle_update, on_cancelled=_handle_later)
        _ACTIVE_UPDATE_DIALOG = dialog
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    @property
    def ready_to_install(self) -> bool:
        return bool(self.downloaded_setup_path and Path(self.downloaded_setup_path).is_file())

    def start_download(self, release_info: Optional[ReleaseInfo] = None):
        target_rel = release_info or self.latest_release
        if not target_rel or not target_rel.setup_download_url:
            self.download_failed.emit("No valid download link found for this release.")
            return

        if self.is_downloading:
            return

        self.is_downloading = True
        self.downloaded_setup_path = None

        # Register in Dynamic Island Activity Manager for living HUD progress
        try:
            from odd_island import ActivityManager
            act_mgr = ActivityManager.get_instance()
            if act_mgr:
                act_mgr.start_activity(
                    activity_id="odd_app_update",
                    title=f"Updating ODD ({target_rel.version_display})",
                    progress=0.0,
                    subtitle="Starting download...",
                    activity_type="update",
                    icon_type="download",
                    total_bytes=target_rel.setup_file_size
                )
        except Exception:
            pass

        self._download_worker = DownloadUpdateWorker(
            download_url=target_rel.setup_download_url,
            expected_size=target_rel.setup_file_size
        )
        self._download_worker.progress_changed.connect(self._on_download_progress)
        self._download_worker.download_completed.connect(lambda p: self._on_download_completed(p, target_rel))
        self._download_worker.download_failed.connect(self._on_download_failed)
        self._download_worker.start()

    def _on_download_progress(self, downloaded: int, total: int, pct: float, speed_str: str):
        self.download_progress.emit(downloaded, total, pct, speed_str)
        try:
            from odd_island import ActivityManager
            act_mgr = ActivityManager.get_instance()
            if act_mgr:
                disp_pct = f"{int(pct)}%" if pct >= 0 else "Downloading..."
                sub = f"{disp_pct} • {speed_str}"
                act_mgr.update_activity(
                    activity_id="odd_app_update",
                    progress=pct if pct >= 0 else 50.0,
                    subtitle=sub,
                    speed_str=speed_str,
                    downloaded_bytes=downloaded,
                    total_bytes=total
                )
        except Exception:
            pass

    def _on_download_completed(self, setup_path: str, release_info: ReleaseInfo):
        self.is_downloading = False
        self.downloaded_setup_path = setup_path
        self.download_finished.emit(setup_path, release_info)

        # Notify via Dynamic Island Activity & Bezel HUD
        try:
            from odd_island import ActivityManager
            act_mgr = ActivityManager.get_instance()
            if act_mgr:
                act_mgr.finish_activity(
                    activity_id="odd_app_update",
                    status="completed",
                    message="Ready to Install",
                    target_path=setup_path
                )
        except Exception:
            pass

    def _on_download_failed(self, error_msg: str):
        self.is_downloading = False
        self.download_failed.emit(error_msg)
        try:
            from odd_island import ActivityManager
            act_mgr = ActivityManager.get_instance()
            if act_mgr:
                act_mgr.finish_activity(
                    activity_id="odd_app_update",
                    status="failed",
                    message="Download Failed"
                )
        except Exception:
            pass

    def apply_update_and_restart(self, setup_path: Optional[str] = None):
        """
        Executes the downloaded ODD_Setup installer and terminates current application instance cleanly.
        """
        target = setup_path or self.downloaded_setup_path
        if not target or not Path(target).exists():
            # Fallback to web browser download
            if self.latest_release and self.latest_release.html_url:
                import webbrowser
                webbrowser.open(self.latest_release.html_url)
            return

        try:
            # Spawn installer with --update flag so it applies update cleanly and restarts app
            subprocess.Popen([str(target), "--update"], cwd=str(Path(target).parent))
            # Immediate OS-level termination to guarantee all file locks on ODD.exe are instantly released
            import os
            try:
                QApplication.quit()
            except Exception:
                pass
            os._exit(0)
        except Exception as e:
            print(f"[ODD Updater] Error launching setup: {e}")
            import webbrowser
            webbrowser.open(WEBSITE_URL)


def check_for_updates_background(notify_ui: bool = True):
    """
    Convenience function to trigger background or manual update check.
    """
    mgr = UpdateManager.get_instance()
    mgr.check_for_updates(manual=notify_ui)

