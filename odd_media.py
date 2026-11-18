"""
Universal Windows Media Transport Controls (GSMTC) & Audio Controller for ODD
Detects all active media sessions across Windows apps (Spotify, Chrome, Edge, VLC, Apple Music, etc.),
allows switching between multiple media sources, and controls playback and volume/mute.
"""
import sys
import asyncio
import threading
from typing import Optional, Dict, Any, List
from PySide6.QtCore import QObject, Signal

try:
    import winrt.windows.media.control as wmc
    import winrt.windows.storage.streams as streams
    HAS_WINRT = True
except Exception:
    HAS_WINRT = False

HAS_PYCAW = False


import time

class MediaState:
    def __init__(self):
        self.has_media: bool = False
        self.title: str = ""
        self.artist: str = ""
        self.album: str = ""
        self.app_id: str = ""
        self.app_display_name: str = ""
        self.status: str = "stopped"  # "playing", "paused", "stopped"
        self.is_playing: bool = False
        self.thumbnail_bytes: Optional[bytes] = None
        self.available_sessions: List[Dict[str, Any]] = []
        self.selected_session_index: int = 0
        self.is_muted: bool = False
        self.master_volume: float = 1.0
        self.position_sec: float = 0.0
        self.duration_sec: float = 0.0
        self.can_seek: bool = False
        self.last_updated_time: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "has_media": self.has_media,
            "title": self.title,
            "artist": self.artist,
            "album": self.album,
            "app_id": self.app_id,
            "app_display_name": self.app_display_name,
            "status": self.status,
            "is_playing": self.is_playing,
            "thumbnail_bytes": self.thumbnail_bytes,
            "available_sessions": self.available_sessions,
            "selected_session_index": self.selected_session_index,
            "is_muted": self.is_muted,
            "master_volume": self.master_volume,
            "position_sec": self.position_sec,
            "duration_sec": self.duration_sec,
            "can_seek": self.can_seek,
            "last_updated_time": self.last_updated_time,
        }


def clean_app_name(app_id: str) -> str:
    """Turn raw UWP / Win32 app ID into a clean display name"""
    if not app_id:
        return "Media Player"
    name = app_id.lower()
    if "applemusic" in name or "itunes" in name or "amplibraryagent" in name or "appleinc" in name:
        return "Apple Music"
    elif "spotify" in name:
        return "Spotify"
    elif "youtubemusic" in name or "ytmdesktop" in name or "youtube music" in name:
        return "YouTube Music"
    elif "tidal" in name:
        return "Tidal"
    elif "soundcloud" in name:
        return "SoundCloud"
    elif "deezer" in name:
        return "Deezer"
    elif "amazonmusic" in name or "amazon music" in name:
        return "Amazon Music"
    elif "foobar" in name:
        return "Foobar2000"
    elif "musicbee" in name:
        return "MusicBee"
    elif "aimp" in name:
        return "AIMP"
    elif "winamp" in name:
        return "Winamp"
    elif "chrome" in name:
        return "Google Chrome"
    elif "edge" in name or "msedge" in name:
        return "Microsoft Edge"
    elif "brave" in name:
        return "Brave"
    elif "firefox" in name or "mozilla" in name:
        return "Firefox"
    elif "opera" in name:
        return "Opera"
    elif "vivaldi" in name:
        return "Vivaldi"
    elif "zen" in name and ("browser" in name or name.startswith("zen")):
        return "Zen"
    elif "vlc" in name:
        return "VLC Player"
    elif "potplayer" in name:
        return "PotPlayer"
    elif "mpc-hc" in name or "mpc-be" in name or "mplayerc" in name:
        return "MPC Player"
    elif "mpv" in name:
        return "MPV"
    elif "discord" in name:
        return "Discord"
    elif "telegram" in name:
        return "Telegram"
    elif "whatsapp" in name:
        return "WhatsApp"
    elif "zune" in name or "mediaplayer" in name or "wmplayer" in name or "music" in name:
        return "Media Player"

    import re
    if re.match(r'^[0-9a-fA-F]{16}$', app_id.strip()):
        return "Google Chrome"

    # Strip paths, UWP package suffixes, or extensions
    base = app_id.split("\\")[-1].split("/")[-1]
    if "!" in base:
        pkg_part = base.split("!")[0]
        app_part = base.split("!")[-1]
        if app_part.lower() not in ("app", "main", "default"):
            base = app_part
        else:
            base = pkg_part.split("_")[0]
    base = base.replace(".exe", "").split("_")[0]
    if "." in base:
        parts = [p for p in base.split(".") if p.lower() not in ("microsoft", "windows", "app", "client", "desktop", "win", "inc", "com")]
        if parts:
            base = parts[-1]
    return base.strip().capitalize() if base.strip() else "Media Player"


def normalize_media_metadata(title: str, artist: str, album: str = "") -> tuple[str, str, str]:
    """
    Normalizes track title, artist, and album across media players.
    Specifically handles Apple Music on Windows which packs 'Artist — Album' into the GSMTC artist field.
    """
    clean_title = (title or "").strip()
    clean_artist = (artist or "").strip()
    clean_album = (album or "").strip()

    # Apple Music on Windows separates Artist and Album with an em-dash ' — ' or en-dash ' – '
    for sep in (" \u2014 ", " \u2013 "):
        if sep in clean_artist:
            parts = clean_artist.split(sep, 1)
            left_artist = parts[0].strip()
            right_album = parts[1].strip()
            if left_artist:
                clean_artist = left_artist
                if not clean_album and right_album:
                    clean_album = right_album
            break

    return clean_title, clean_artist, clean_album


class WindowsMediaManager(QObject):
    media_changed = Signal(dict)

    def __init__(self):
        super().__init__()
        self._current_state = MediaState()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._session_manager = None
        self._last_state_signature = ""
        self._selected_session_index = 0
        self._user_selected_app_id: Optional[str] = None
        self._seek_hold_until = 0.0

    def start(self):
        if not HAS_WINRT:
            return
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._worker_thread_main, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)

    def _worker_thread_main(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._poll_loop())
        except Exception:
            pass

    async def _get_manager(self):
        if not self._session_manager:
            try:
                self._session_manager = await wmc.GlobalSystemMediaTransportControlsSessionManager.request_async()
            except Exception:
                self._session_manager = None
        return self._session_manager

    async def _extract_thumbnail(self, thumb_ref) -> Optional[bytes]:
        if not thumb_ref:
            return None
        try:
            stream = await thumb_ref.open_read_async()
            size = stream.size
            if size == 0 or size > 10 * 1024 * 1024:
                return None
            reader = streams.DataReader(stream.get_input_stream_at(0))
            await reader.load_async(size)
            buffer = bytearray(size)
            reader.read_bytes(buffer)
            return bytes(buffer)
        except Exception:
            return None

    def _get_audio_volume_info(self) -> (bool, float):
        """Returns live master volume and mute state from DynamicIslandMonitor without COM overhead"""
        try:
            import odd_island
            inst = odd_island.DynamicIslandMonitor.get_instance()
            if inst:
                vol = getattr(inst, "_last_vol", -1)
                muted = getattr(inst, "_last_mute", None)
                if vol >= 0 and muted is not None:
                    return bool(muted) or (vol <= 0), max(0.0, min(1.0, vol / 100.0))
        except Exception:
            pass
        return self._current_state.is_muted, 1.0

    async def _fetch_current_media(self) -> MediaState:
        state = MediaState()
        is_muted, vol_level = self._get_audio_volume_info()
        state.is_muted = is_muted
        state.master_volume = vol_level

        mgr = await self._get_manager()
        if not mgr:
            return state

        try:
            raw_sessions = mgr.get_sessions()
            all_sessions = []

            for idx, sess in enumerate(raw_sessions):
                try:
                    s_app_id = sess.source_app_user_model_id or ""
                    s_info = await sess.try_get_media_properties_async()
                    s_pb = sess.get_playback_info()
                    if s_info and s_pb:
                        raw_title = getattr(s_info, "title", "") or ""
                        raw_artist = getattr(s_info, "artist", "") or ""
                        raw_album = getattr(s_info, "album_title", "") or ""
                        s_title, s_artist, s_album = normalize_media_metadata(raw_title, raw_artist, raw_album)

                        pb_status = getattr(s_pb, "playback_status", 0)
                        s_is_playing = (pb_status == 4)
                        s_status_str = "playing" if s_is_playing else ("paused" if pb_status == 5 else "stopped")

                        all_sessions.append({
                            "index": idx,
                            "app_id": s_app_id,
                            "app_name": clean_app_name(s_app_id),
                            "title": s_title or "Media Track",
                            "artist": s_artist,
                            "album": s_album,
                            "status": s_status_str,
                            "is_playing": s_is_playing,
                            "raw_session": sess,
                            "thumb_ref": getattr(s_info, "thumbnail", None)
                        })
                except Exception:
                    continue

            state.available_sessions = [
                {
                    "index": s["index"],
                    "app_id": s["app_id"],
                    "app_name": s["app_name"],
                    "title": s["title"],
                    "artist": s["artist"],
                    "album": s["album"],
                    "status": s["status"],
                    "is_playing": s["is_playing"]
                }
                for s in all_sessions
            ]

            if not all_sessions:
                return state

            # Select target session:
            # 1. Check if current selected index is still valid
            target = None
            for s in all_sessions:
                if s["index"] == self._selected_session_index:
                    target = s
                    break

            # 2. If the selected session is not playing, check if another session actively started playing
            playing_sessions = [s for s in all_sessions if s["is_playing"]]
            if playing_sessions:
                if target is None or not target["is_playing"]:
                    # If user pinned a specific app that is still playing, keep it; otherwise follow active playback
                    if self._user_selected_app_id:
                        pinned = next((s for s in playing_sessions if s["app_id"] == self._user_selected_app_id), None)
                        target = pinned or playing_sessions[0]
                    else:
                        target = playing_sessions[0]
                    self._selected_session_index = target["index"]

            if target is None:
                target = all_sessions[0]
                self._selected_session_index = target["index"]

            if target:
                state.has_media = True
                state.title = target["title"]
                state.artist = target["artist"]
                state.album = target.get("album", "")
                state.app_id = target["app_id"]
                state.app_display_name = target["app_name"]
                state.status = target["status"]
                state.is_playing = target["is_playing"]
                state.selected_session_index = target["index"]

                try:
                    raw_sess = target.get("raw_session")
                    if raw_sess:
                        tl = raw_sess.get_timeline_properties()
                        if tl:
                            start_sec = tl.start_time.total_seconds() if getattr(tl, "start_time", None) else 0.0
                            pos_raw = tl.position.total_seconds() if getattr(tl, "position", None) else 0.0
                            dur_raw = tl.end_time.total_seconds() if getattr(tl, "end_time", None) else 0.0
                            if dur_raw <= 0 and getattr(tl, "max_seek_time", None):
                                dur_raw = tl.max_seek_time.total_seconds()
                            pos = max(0.0, float(pos_raw - start_sec)) if start_sec > 0 and pos_raw >= start_sec else max(0.0, float(pos_raw))
                            dur = max(0.0, float(dur_raw - start_sec)) if start_sec > 0 and dur_raw > start_sec else max(0.0, float(dur_raw))

                            # Adjust for elapsed time since last_updated_time if track is currently playing
                            lut = getattr(tl, "last_updated_time", None)
                            if lut and target.get("is_playing", False):
                                try:
                                    import datetime
                                    now_utc = datetime.datetime.now(datetime.timezone.utc)
                                    if getattr(lut, "tzinfo", None) is None:
                                        lut = lut.replace(tzinfo=datetime.timezone.utc)
                                    elapsed = max(0.0, (now_utc - lut).total_seconds())
                                    pos = pos + elapsed
                                    if dur > 0 and pos > dur:
                                        pos = dur
                                except Exception:
                                    pass

                            if dur > 0 and pos > dur:
                                pos = dur
                            is_target_apple = any(
                                k in target["app_id"].lower() or k in target["app_name"].lower()
                                for k in ("apple", "itunes", "amplibrary")
                            )
                            if dur <= 0 and is_target_apple:
                                dur = max(dur, 210.0)
                            state.position_sec = pos
                            state.duration_sec = dur
                            state.can_seek = (state.duration_sec > 0 or is_target_apple)
                            state.last_updated_time = time.time()
                except Exception:
                    pass

                thumb_sig = f"{target['title']}|{target['artist']}|{target['app_id']}"
                prev_thumb_sig = getattr(self, "_last_thumb_signature", "")
                if thumb_sig != prev_thumb_sig or self._current_state.thumbnail_bytes is None:
                    state.thumbnail_bytes = await self._extract_thumbnail(target.get("thumb_ref"))
                    self._last_thumb_signature = thumb_sig
                else:
                    state.thumbnail_bytes = self._current_state.thumbnail_bytes

        except Exception:
            pass

        return state

    async def _poll_loop(self):
        last_pos_sync = 0.0
        while self._running:
            try:
                new_state = await self._fetch_current_media()
                now = time.time()
                # If user recently seeked from ODD, smoothly advance from seek position to prevent rubber-banding
                if now < getattr(self, '_seek_hold_until', 0.0):
                    seek_pos = getattr(self, '_user_seek_pos', self._current_state.position_sec)
                    seek_t = getattr(self, '_user_seek_time', self._current_state.last_updated_time)
                    elapsed = max(0.0, now - seek_t) if new_state.is_playing else 0.0
                    pos = seek_pos + elapsed
                    if new_state.duration_sec > 0 and pos > new_state.duration_sec:
                        pos = new_state.duration_sec
                    new_state.position_sec = pos
                    new_state.last_updated_time = now

                # Signature includes all session states so sources dropdown stays in sync
                sess_sig = ";".join(
                    f"{s.get('app_id')}:{s.get('title')}:{s.get('status')}"
                    for s in new_state.available_sessions
                )
                sig = (
                    f"{new_state.has_media}|{new_state.title}|{new_state.artist}|"
                    f"{new_state.status}|{new_state.selected_session_index}|"
                    f"{new_state.is_muted}|{int(new_state.duration_sec)}|"
                    f"{new_state.thumbnail_bytes is not None}|{sess_sig}"
                )

                # Check if state changed or external seek occurred in player
                should_emit = (sig != self._last_state_signature)

                # Detect external scrubber seek in browser or media player
                est_prev_pos = self._current_state.position_sec
                if self._current_state.is_playing:
                    elapsed_since_last = max(0.0, now - self._current_state.last_updated_time)
                    est_prev_pos += elapsed_since_last

                pos_drift = abs(new_state.position_sec - est_prev_pos)
                if pos_drift >= 1.2:
                    should_emit = True

                # If paused and position changed by >= 0.4s (user scrubbed while paused)
                if not new_state.is_playing and abs(new_state.position_sec - self._current_state.position_sec) >= 0.4:
                    should_emit = True

                # Periodic continuous synchronization while playing (every 1s)
                if not should_emit and new_state.is_playing and (now - last_pos_sync >= 1.0):
                    should_emit = True
                    last_pos_sync = now

                if should_emit:
                    self._last_state_signature = sig
                    self._current_state = new_state
                    self.media_changed.emit(new_state.to_dict())
            except Exception:
                pass
            await asyncio.sleep(0.35)

    def select_session(self, index: int):
        """User explicitly chooses a media source from available sessions"""
        self._selected_session_index = index
        for s in self._current_state.available_sessions:
            if s.get("index") == index:
                self._user_selected_app_id = s.get("app_id")
                break
        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(self._refresh_immediate(), self._loop)

    def toggle_play_pause(self):
        """Thread-safe command to toggle play/pause on the selected media session"""
        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(self._async_toggle_play_pause(), self._loop)

    def next_track(self):
        """Thread-safe command to skip to next track"""
        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(self._async_next(), self._loop)

    def previous_track(self):
        """Thread-safe command to skip to previous track"""
        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(self._async_previous(), self._loop)

    def seek_to(self, position_sec: float):
        """Thread-safe command to seek to target position in seconds"""
        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(self._async_seek(position_sec), self._loop)

    def _seek_apple_music_worker(self, target_sec: float, current_sec: float, duration_sec: float):
        """Dedicated worker to seek Apple Music via COM, UI Automation, and keyboard shortcuts."""
        # 1. Try classic iTunes COM interface
        try:
            import win32com.client
            itunes = win32com.client.Dispatch("iTunes.Application")
            if itunes and getattr(itunes, "PlayerState", 0) != 0:
                itunes.PlayerPosition = int(target_sec)
                return
        except Exception:
            pass

        # 2. Try Windows UI Automation on Apple Music window slider
        try:
            import uiautomation as auto
            am_win = auto.WindowControl(searchDepth=3, SubName="Apple Music")
            if not am_win.Exists(0, 0):
                am_win = auto.WindowControl(searchDepth=2, ClassName="ApplicationFrameWindow", SubName="Apple Music")
            if am_win.Exists(0.1, 0.1):
                slider = am_win.SliderControl(searchDepth=6)
                if slider.Exists(0.1, 0.1):
                    rvp = slider.GetRangeValuePattern()
                    if rvp:
                        rvp.SetValue(target_sec)
                        return
                    rect = slider.BoundingRectangle
                    if rect.width() > 0 and duration_sec > 0:
                        pct = max(0.0, min(1.0, target_sec / duration_sec))
                        click_x = rect.left + int(rect.width() * pct)
                        click_y = rect.top + int(rect.height() / 2)
                        auto.Click(click_x, click_y)
                        return
        except Exception:
            pass

        # 3. Native Keyboard Shortcuts (Ctrl + Alt + Right / Left) for Apple Music
        try:
            import ctypes
            VK_CONTROL = 0x11
            VK_MENU = 0x12  # Alt
            VK_RIGHT = 0x27
            VK_LEFT = 0x25
            KEYEVENTF_KEYUP = 0x0002

            delta = target_sec - current_sec
            if abs(delta) >= 1.5:
                steps = max(1, min(25, int(round(abs(delta) / 5.0))))
                target_key = VK_RIGHT if delta > 0 else VK_LEFT
                for _ in range(steps):
                    ctypes.windll.user32.keybd_event(VK_CONTROL, 0, 0, 0)
                    ctypes.windll.user32.keybd_event(VK_MENU, 0, 0, 0)
                    ctypes.windll.user32.keybd_event(target_key, 0, 0, 0)
                    time.sleep(0.015)
                    ctypes.windll.user32.keybd_event(target_key, 0, KEYEVENTF_KEYUP, 0)
                    ctypes.windll.user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)
                    ctypes.windll.user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)
                    time.sleep(0.02)
        except Exception:
            pass

    async def _async_seek(self, position_sec: float):
        session = await self._get_target_session()
        app_name = (self._current_state.app_display_name or "").lower()
        app_id = (self._current_state.app_id or "").lower()
        is_apple = any(k in app_name or k in app_id for k in ("apple", "itunes", "amplibrary"))

        gm_success = False
        if session:
            try:
                start_sec = 0.0
                try:
                    tl = session.get_timeline_properties()
                    if tl and getattr(tl, "start_time", None):
                        start_sec = tl.start_time.total_seconds()
                except Exception:
                    pass
                ticks = int(max(0.0, float(start_sec + position_sec)) * 10_000_000)
                res = await session.try_change_playback_position_async(ticks)
                gm_success = bool(res)
            except Exception:
                gm_success = False

        if is_apple and not gm_success:
            threading.Thread(
                target=self._seek_apple_music_worker,
                args=(position_sec, self._current_state.position_sec, self._current_state.duration_sec),
                daemon=True
            ).start()

        now = time.time()
        pos = max(0.0, float(position_sec))
        self._user_seek_pos = pos
        self._user_seek_time = now
        self._seek_hold_until = now + 0.7
        self._current_state.position_sec = pos
        self._current_state.last_updated_time = now
        self.media_changed.emit(self._current_state.to_dict())

    def toggle_master_mute(self) -> bool:
        """Toggle Windows Master audio mute immediately with zero-lag hardware event"""
        try:
            import ctypes
            VK_VOLUME_MUTE = 0xAD
            ctypes.windll.user32.keybd_event(VK_VOLUME_MUTE, 0, 0, 0)
            ctypes.windll.user32.keybd_event(VK_VOLUME_MUTE, 0, 2, 0)
            # Invert local state immediately for instant UI feedback
            self._current_state.is_muted = not self._current_state.is_muted
            self.media_changed.emit(self._current_state.to_dict())
            if self._loop and self._loop.is_running():
                asyncio.run_coroutine_threadsafe(self._refresh_immediate(), self._loop)
            return self._current_state.is_muted
        except Exception:
            return False

    async def _get_target_session(self):
        mgr = await self._get_manager()
        if not mgr:
            return None
        sessions = mgr.get_sessions()
        if not sessions:
            return None
        if 0 <= self._selected_session_index < len(sessions):
            return sessions[self._selected_session_index]
        return mgr.get_current_session() or sessions[0]

    async def _async_toggle_play_pause(self):
        session = await self._get_target_session()
        if session:
            try:
                await session.try_toggle_play_pause_async()
                await asyncio.sleep(0.1)
                await self._refresh_immediate()
            except Exception:
                pass

    async def _async_next(self):
        session = await self._get_target_session()
        if session:
            try:
                await session.try_skip_next_async()
                await asyncio.sleep(0.15)
                await self._refresh_immediate()
            except Exception:
                pass

    async def _async_previous(self):
        session = await self._get_target_session()
        if session:
            try:
                await session.try_skip_previous_async()
                await asyncio.sleep(0.15)
                await self._refresh_immediate()
            except Exception:
                pass

    async def _refresh_immediate(self):
        st = await self._fetch_current_media()
        self._current_state = st
        self.media_changed.emit(st.to_dict())


# Global singleton instance
_global_media_manager: Optional[WindowsMediaManager] = None

def get_media_manager() -> WindowsMediaManager:
    global _global_media_manager
    if _global_media_manager is None:
        _global_media_manager = WindowsMediaManager()
        _global_media_manager.start()
    return _global_media_manager
