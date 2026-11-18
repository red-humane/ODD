import ctypes
import json
import os
import re
import subprocess
import threading
import time
import urllib.parse
import webbrowser
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from PySide6.QtCore import QObject, Signal

CONTACTS_CACHE_FILE = Path(os.path.expandvars(r"%APPDATA%\ODD\messaging_contacts.json"))


class MessagingState(str, Enum):
    OPEN_APP = "OPEN_APP"
    WAIT_FOR_APP_READY = "WAIT_FOR_APP_READY"
    WAIT_FOR_LOGIN = "WAIT_FOR_LOGIN"
    WAIT_FOR_SEARCH = "WAIT_FOR_SEARCH"
    SEARCH_RECIPIENT = "SEARCH_RECIPIENT"
    WAIT_FOR_RESULTS = "WAIT_FOR_RESULTS"
    RESOLVE_RECIPIENT = "RESOLVE_RECIPIENT"
    OPEN_CHAT = "OPEN_CHAT"
    WAIT_FOR_CHAT = "WAIT_FOR_CHAT"
    TYPE_MESSAGE = "TYPE_MESSAGE"
    SEND = "SEND"
    PAUSED_DISAMBIGUATION = "PAUSED_DISAMBIGUATION"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


@dataclass
class ParsedMessageCommand:
    action: str  # "send_message"
    recipient: str
    message: str
    raw_query: str
    provider_override: Optional[str] = None


@dataclass
class ContactMatch:
    name: str
    subtitle: str = ""
    control_rect: Optional[Tuple[int, int, int, int]] = None  # (left, top, right, bottom)
    row_index: int = 0

    @property
    def display_name(self) -> str:
        return self.name


# Words that commonly begin the message body rather than a contact's surname or qualifier
_MESSAGE_STARTER_WORDS = {
    "i", "i'll", "i'm", "i've", "i'd", "im", "ill", "ive", "id", "me", "my",
    "we", "we're", "we'll", "we've", "we'd", "us", "our",
    "you", "you're", "you'll", "you've", "your", "u", "ur",
    "he", "he's", "he'll", "she", "she's", "she'll", "they", "they're", "they'll",
    "it", "it's", "its", "that", "that's", "this", "there", "here",
    "hey", "hi", "hello", "yo", "sup", "hii", "hiii", "hola", "namaste", "dear",
    "good", "gm", "gn", "morning", "afternoon", "evening", "night",
    "happy", "congrats", "congratulations", "merry",
    "please", "pls", "plz", "kindly",
    "can", "could", "will", "would", "should", "shall", "may", "might", "must",
    "do", "does", "did", "done", "doing",
    "are", "is", "am", "was", "were", "be", "been", "being",
    "have", "has", "had", "having",
    "don't", "dont", "doesn't", "doesnt", "didn't", "didnt",
    "can't", "cant", "cannot", "won't", "wont", "wouldn't", "shouldn't", "couldn't",
    "isn't", "isnt", "aren't", "arent", "wasn't", "weren't", "haven't", "hasn't",
    "call", "calling", "called", "text", "message", "msg", "ping", "ring",
    "meet", "meeting", "come", "coming", "came", "go", "going", "went", "gone",
    "run", "running", "leaving", "left", "arrived", "arriving", "reached", "reaching",
    "on", "in", "at", "to", "for", "from", "with", "about", "after", "before", "by", "of",
    "where", "when", "what", "what's", "whats", "why", "who", "how", "how's", "hows", "which",
    "ok", "okay", "k", "kk", "yes", "no", "yeah", "yep", "yup", "nope", "nah", "sure",
    "fine", "great", "nice", "cool", "awesome", "alright", "right",
    "thanks", "thank", "thx", "ty", "tysm", "appreciate",
    "sorry", "sry", "apologies", "excuse",
    "let", "let's", "lets", "check", "send", "sending", "sent",
    "bring", "buy", "get", "getting", "got", "pick", "take", "took", "give", "gave",
    "see", "saw", "look", "watch", "talk", "tell", "ask", "need", "want", "wish", "hope",
    "wait", "waiting", "hold", "stop", "start", "open", "close", "finish", "finished", "ready",
    "almost", "nearly", "just", "still", "already", "also", "too", "very", "so", "really",
    "omw", "brb", "btw", "fyi", "asap", "lol", "lmao", "haha", "hehe", "omg", "wtf",
    "urgent", "important", "quick", "fast", "remember", "remind",
    "late", "early", "soon", "now", "today", "tonight", "tomorrow", "yesterday",
    "the", "a", "an", "some", "any", "all", "every", "not", "never", "always",
    "if", "while", "because", "since", "until", "unless", "though", "although",
}

# Contact qualifier keywords that frequently appear inside a contact's saved name (e.g. "sis num 2", "dad no 1")
_CONTACT_QUALIFIER_WORDS = {
    "num", "no", "no.", "number", "#", "sim", "alt", "new", "old", "personal", "official", "work", "home", "office", "jio", "airtel", "vi",
}

# Excluded first tokens after "send " so "send file" or "send email" don't false-trigger messaging
_NON_RECIPIENT_KEYWORDS = {
    "file", "files", "folder", "folders", "email", "mail", "photo", "photos",
    "image", "images", "video", "document", "doc", "pdf", "link", "url",
    "clipboard", "nearby", "feedback", "report", "logs", "it", "this", "that",
}

_SECTION_HEADERS = {
    "chats", "contacts", "messages", "other contacts", "frequently contacted",
    "recent", "recent chats", "unread", "groups", "channels", "communities",
    "archived", "starred", "all", "favorites", "favourites", "search results",
    "no results", "no chats, contacts or messages found", "whatsapp",
}


class ContactStore:
    """Persists discovered WhatsApp contacts so disambiguation and multi-word name matching are instant."""

    def __init__(self):
        self._lock = threading.Lock()
        self._contacts: List[str] = []
        self._load()

    def _load(self):
        try:
            if CONTACTS_CACHE_FILE.exists():
                with open(CONTACTS_CACHE_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        self._contacts = [str(x).strip() for x in data if str(x).strip()]
        except Exception:
            self._contacts = []

    def _save(self):
        try:
            CONTACTS_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(CONTACTS_CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(self._contacts[:500], f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    def record_contacts(self, names: List[str]):
        if not names:
            return
        with self._lock:
            existing_low = {c.lower(): idx for idx, c in enumerate(self._contacts)}
            changed = False
            for raw_name in names:
                clean = raw_name.strip()
                if not clean or len(clean) > 60 or clean.lower() in _SECTION_HEADERS:
                    continue
                low = clean.lower()
                if low not in existing_low:
                    self._contacts.insert(0, clean)
                    existing_low[low] = 0
                    changed = True
            if changed:
                self._save()

    def get_all(self) -> List[str]:
        with self._lock:
            return list(self._contacts)

    def find_matches(self, query_name: str) -> List[str]:
        q = query_name.strip().lower()
        if not q:
            return []
        with self._lock:
            exact = [c for c in self._contacts if c.lower() == q]
            prefix_word = [
                c for c in self._contacts
                if c.lower() != q and (
                    c.lower().startswith(q + " ")
                    or c.lower().startswith(q)
                    or any(part == q or part.startswith(q) for part in c.lower().split())
                )
            ]
            return exact + prefix_word


contact_store = ContactStore()


class MessageCommandParser:
    """
    Natural-language parser for quick messaging commands:
      - Text John I'll be there in 10 minutes
      - Message Mom I'm coming home
      - Send Alex I'll call you later
      - text sis num 2 hi
    Extracts:
      action = "send_message"
      recipient = "John" / "sis num 2"
      message = "I'll be there in 10 minutes" / "hi"
    Preserves the user's message text exactly.
    """

    _PREFIX_PATTERNS = [
        (re.compile(r"^(?:whatsapp\s+web|wa\s+web)\s*[:\-]?\s+(.+)$", re.IGNORECASE), "whatsapp_web"),
        (re.compile(r"^(?:whatsapp\s+desktop|wa\s+desktop)\s*[:\-]?\s+(.+)$", re.IGNORECASE), "whatsapp_desktop"),
        (re.compile(r"^(?:send\s+a?\s*(?:quick\s+)?(?:text|message|msg|whatsapp)\s+to)\s+(.+)$", re.IGNORECASE), None),
        (re.compile(r"^(?:text|message|msg)\s+to\s+(.+)$", re.IGNORECASE), None),
        (re.compile(r"^(?:send\s+to)\s+(.+)$", re.IGNORECASE), None),
        (re.compile(r"^(?:text|message|msg|whatsapp|wa|dm)\s*[:\-]?\s+(.+)$", re.IGNORECASE), None),
        (re.compile(r"^(?:send)\s+(.+)$", re.IGNORECASE), None),
    ]

    @staticmethod
    def _is_message_starter_token(tok: str) -> bool:
        w_clean = tok.lower().strip(",.!?;:")
        if not w_clean:
            return False
        if w_clean in _MESSAGE_STARTER_WORDS:
            return True
        if "'" in tok and w_clean.endswith(("'ll", "'m", "'re", "'ve", "'d", "'s", "n't")):
            return True
        if any(ch in tok for ch in ("?", "!", ";", "@", "/", "\\")):
            return True
        return False

    @staticmethod
    def _is_incomplete_contact_only(rem: str) -> bool:
        """
        Returns True when `rem` only contains a contact name (1 word, or a name with qualifiers
        like 'sis num', 'sis num 2', 'sis 2') and no message has been typed yet.
        """
        words = [w.lower().strip(",.!?;:") for w in rem.split() if w.strip()]
        if not words:
            return True
        if len(words) == 1:
            return True
        if len(words) == 2 and (words[1] in _CONTACT_QUALIFIER_WORDS or words[1].isdigit()):
            return True
        if len(words) == 3 and words[1] in ("num", "no", "no.", "number", "#", "sim") and words[2].isdigit():
            return True
        return False

    @classmethod
    def is_partial_trigger(cls, query: str) -> Tuple[bool, str]:
        """Returns (True, recipient_hint) when user has typed 'text' or 'text sis num 2' but not the message yet."""
        q = query.strip()
        low = q.lower()
        if low in ("text", "text:", "message", "message:", "msg", "msg:"):
            return True, ""
        for pat, _ in cls._PREFIX_PATTERNS[:6]:
            m = pat.match(q)
            if m:
                rem = m.group(1).strip()
                if rem and ":" not in rem and cls._is_incomplete_contact_only(rem):
                    return True, rem
        return False, ""

    @classmethod
    def parse_partial(cls, query: str) -> Optional[Dict[str, str]]:
        is_part, rec_hint = cls.is_partial_trigger(query)
        if is_part:
            return {"recipient": rec_hint}
        return None

    @classmethod
    def parse(cls, query: str) -> Optional[ParsedMessageCommand]:
        if not query or not query.strip():
            return None

        raw = query.strip()

        # Avoid colliding with split commands ("edge and word") unless clearly a message after recipient
        remainder = None
        provider_override = None
        is_generic_send = False

        for idx, (pat, prov) in enumerate(cls._PREFIX_PATTERNS):
            m = pat.match(raw)
            if m:
                remainder = m.group(1).strip()
                provider_override = prov
                is_generic_send = (idx == len(cls._PREFIX_PATTERNS) - 1)
                break

        if not remainder:
            return None

        recipient, message = cls._split_recipient_and_message(remainder)
        if not recipient or not message:
            return None

        rec_low = recipient.lower().strip()
        if rec_low in _NON_RECIPIENT_KEYWORDS:
            return None

        # If triggered by bare "send <recipient> <message>", verify recipient looks like a contact name
        if is_generic_send:
            first_word = rec_low.split()[0]
            if first_word in _NON_RECIPIENT_KEYWORDS or first_word in ("a", "an", "the", "my", "some", "all"):
                return None

        return ParsedMessageCommand(
            action="send_message",
            recipient=recipient,
            message=message,
            raw_query=raw,
            provider_override=provider_override,
        )

    @classmethod
    def _split_recipient_and_message(cls, remainder: str) -> Tuple[str, str]:
        rem = remainder.strip()
        if not rem:
            return "", ""

        # 1. Quoted recipient: Text "John Smith" I'll be there
        m_quote = re.match(r'^["\']([^"\']+)["\']\s+(.+)$', rem, re.DOTALL)
        if m_quote:
            return m_quote.group(1).strip(), m_quote.group(2).strip()

        # 2. Explicit separator after 1–4 word name: Text sis num 2: hi
        m_colon = re.match(r"^([A-Za-z0-9_.\-+]+(?:\s+[A-Za-z0-9_.\-+]+){0,3})\s*[:\-]\s+(.+)$", rem, re.DOTALL)
        if m_colon:
            return m_colon.group(1).strip(), m_colon.group(2).strip()

        # If the user has only typed the contact name / qualifier so far (e.g. "sis num 2"), wait for message
        if cls._is_incomplete_contact_only(rem):
            return "", ""

        # 3. Match against known multi-word contacts in ContactStore (longest first)
        known = sorted(contact_store.get_all(), key=lambda s: len(s), reverse=True)
        rem_low = rem.lower()
        for cname in known:
            c_low = cname.lower()
            if " " in c_low and rem_low.startswith(c_low + " "):
                msg_part = rem[len(cname):].strip()
                if msg_part:
                    return cname, msg_part

        # 4. Token-based natural language boundary detection
        tokens = list(re.finditer(r"\S+", rem))
        if len(tokens) < 2:
            return "", ""

        w0 = tokens[0].group(0)
        w1 = tokens[1].group(0)
        w1_clean = w1.lower().strip(",.!?;:")

        # If only 2 words (e.g., "Text John hello"), word 0 is recipient and word 1 is message
        if len(tokens) == 2:
            return w0, rem[tokens[1].start():].strip()

        # 4a. Check explicit multi-word contact qualifier patterns first:
        # Pattern: "<name> num/no/number/# <N> <message...>" (e.g., "sis num 2 hi")
        if len(tokens) >= 4:
            w2_clean = tokens[2].group(0).lower().strip(",.!?;:")
            if w1_clean in ("num", "no", "no.", "number", "#", "sim") and (w2_clean.isdigit() or len(w2_clean) <= 2):
                return (
                    rem[tokens[0].start():tokens[2].end()].strip(),
                    rem[tokens[3].start():].strip(),
                )

        # Pattern: "<name> <number/qualifier> <message...>" (e.g., "sis 2 hi", "dad work call me")
        if len(tokens) >= 3 and (w1_clean.isdigit() or w1_clean in _CONTACT_QUALIFIER_WORDS):
            return (
                rem[tokens[0].start():tokens[1].end()].strip(),
                rem[tokens[2].start():].strip(),
            )

        # 4b. Scan tokens 1..min(3, len(tokens)-1) for the first clear message-starter word:
        # e.g., "text John I'll be there" -> starter at idx 1 ("I'll") -> recipient="John"
        # e.g., "text john smith hi there" -> starter at idx 2 ("hi") -> recipient="john smith"
        # e.g., "text mary jane watson hey" -> starter at idx 3 ("hey") -> recipient="mary jane watson"
        max_name_tokens = min(3, len(tokens) - 1)
        for idx in range(1, max_name_tokens + 1):
            tok_str = tokens[idx].group(0)
            if cls._is_message_starter_token(tok_str):
                return (
                    rem[tokens[0].start():tokens[idx - 1].end()].strip(),
                    rem[tokens[idx].start():].strip(),
                )

        # 4c. If token 1 starts with an uppercase letter (e.g., "John Smith") and is not a message starter,
        # treat "w0 w1" as a 2-word contact name
        if w1[0].isupper() and w1.isalpha():
            return rem[tokens[0].start():tokens[1].end()].strip(), rem[tokens[2].start():].strip()

        # 4d. If exactly 3 tokens and token 1 is a short alphabetic name token while token 2 is the message
        if len(tokens) == 3 and w1.isalpha() and len(w1) <= 14:
            return rem[tokens[0].start():tokens[1].end()].strip(), rem[tokens[2].start():].strip()

        # Default: 1-word recipient followed by the full message
        return w0, rem[tokens[1].start():].strip()


# ==============================================================================
# WIN32 & UI AUTOMATION HELPERS
# ==============================================================================

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32


def _activate_hwnd(hwnd: int) -> bool:
    if not hwnd:
        return False
    try:
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        else:
            user32.ShowWindow(hwnd, 5)  # SW_SHOW
        fg_hwnd = user32.GetForegroundWindow()
        if fg_hwnd == hwnd:
            return True
        fg_tid = user32.GetWindowThreadProcessId(fg_hwnd, None)
        cur_tid = kernel32.GetCurrentThreadId()
        target_tid = user32.GetWindowThreadProcessId(hwnd, None)
        if fg_tid and fg_tid != cur_tid:
            user32.AttachThreadInput(cur_tid, fg_tid, True)
        if target_tid and target_tid != cur_tid:
            user32.AttachThreadInput(cur_tid, target_tid, True)
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
        if target_tid and target_tid != cur_tid:
            user32.AttachThreadInput(cur_tid, target_tid, False)
        if fg_tid and fg_tid != cur_tid:
            user32.AttachThreadInput(cur_tid, fg_tid, False)
        return user32.GetForegroundWindow() == hwnd
    except Exception:
        return False


def _enable_chromium_accessibility(top_hwnd: int):
    """Sends WM_GETOBJECT to any Chromium/WebView2 render widget inside top_hwnd so UIA DOM is populated."""
    if not top_hwnd:
        return
    try:
        import win32gui

        def _enum_child(ch_hwnd, _):
            try:
                cls = win32gui.GetClassName(ch_hwnd) or ""
                if "Chrome_RenderWidgetHostHWND" in cls or "Intermediate D3D Window" in cls or "Chrome_WidgetWin" in cls:
                    res = ctypes.c_ulonglong(0)
                    # WM_GETOBJECT = 0x003D, OBJID_CLIENT = 0xFFFFFFFC (-4)
                    user32.SendMessageTimeoutW(
                        int(ch_hwnd), 0x003D, 0, -4, 0x0002, 150, ctypes.byref(res)
                    )
                    user32.SendMessageTimeoutW(
                        int(ch_hwnd), 0x003D, 0, 1, 0x0002, 150, ctypes.byref(res)
                    )
            except Exception:
                pass
            return True

        win32gui.EnumChildWindows(top_hwnd, _enum_child, None)
    except Exception:
        pass


def _save_clipboard_state() -> Tuple[Optional[str], str]:
    """Saves current Win32 clipboard text and ODD clipboard manager state."""
    import win32clipboard
    import win32con
    import odd_search

    prev_text = None
    clip_mgr = getattr(odd_search, "clipboard_mgr", None)
    old_last_text = getattr(clip_mgr, "last_text", "") if clip_mgr else ""

    for _ in range(4):
        try:
            win32clipboard.OpenClipboard()
            try:
                if win32clipboard.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT):
                    prev_text = win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
            except Exception:
                prev_text = None
            win32clipboard.CloseClipboard()
            break
        except Exception:
            try:
                win32clipboard.CloseClipboard()
            except Exception:
                pass
            time.sleep(0.015)

    return prev_text, old_last_text


def _restore_clipboard_state_async(saved_state: Tuple[Optional[str], str], delay: float = 0.65):
    """Restores Win32 clipboard text after messaging finishes without racing active Ctrl+V."""
    import win32clipboard
    import win32con
    import odd_search

    prev_text, old_last_text = saved_state
    clip_mgr = getattr(odd_search, "clipboard_mgr", None)

    def _restore():
        time.sleep(delay)
        if prev_text is not None:
            for _ in range(4):
                try:
                    if clip_mgr:
                        clip_mgr.last_text = prev_text
                    win32clipboard.OpenClipboard()
                    win32clipboard.EmptyClipboard()
                    win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, prev_text)
                    win32clipboard.CloseClipboard()
                    break
                except Exception:
                    try:
                        win32clipboard.CloseClipboard()
                    except Exception:
                        pass
                    time.sleep(0.02)
        elif clip_mgr:
            clip_mgr.last_text = old_last_text

    threading.Thread(target=_restore, daemon=True).start()


def _paste_exact_text_via_clipboard(text: str, wait_after: float = 0.12):
    """
    Copies `text` to the Win32 clipboard and dispatches Ctrl+V synchronously,
    waiting `wait_after` seconds so WhatsApp commits the pasted text before the next keystroke.
    """
    import win32clipboard
    import win32con
    import odd_search

    clip_mgr = getattr(odd_search, "clipboard_mgr", None)
    if clip_mgr:
        clip_mgr.last_text = text

    for _ in range(5):
        try:
            win32clipboard.OpenClipboard()
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, text)
            win32clipboard.CloseClipboard()
            break
        except Exception:
            try:
                win32clipboard.CloseClipboard()
            except Exception:
                pass
            time.sleep(0.015)

    try:
        import uiautomation as auto
        auto.SendKeys("{Ctrl}v", waitTime=0.05)
    except Exception:
        pass

    if wait_after > 0:
        time.sleep(wait_after)


def _is_noise_or_icon_text(s: str) -> bool:
    """Returns True if `s` is a Private Use Area icon glyph, timestamp, or badge counter."""
    if not s:
        return True
    t = s.strip()
    if not t:
        return True
    # Filter out Segoe Fluent / Material Private Use Area icon glyphs
    if any(0xE000 <= ord(ch) <= 0xF8FF for ch in t):
        return True
    if re.match(r"^\d+$", t):
        return True
    if re.match(r"^\d{1,2}:\d{2}\s*(?:AM|PM|am|pm)?$", t):
        return True
    if re.match(r"^\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}$", t):
        return True
    if t.lower() in (
        "yesterday", "today", "monday", "tuesday", "wednesday",
        "thursday", "friday", "saturday", "sunday",
        "unread", "pinned", "muted", "all", "favorites", "groups", "contacts", "chats",
    ):
        return True
    return False


def _extract_descendant_label(ctrl, max_depth: int = 4) -> str:
    """Extracts the primary contact title from a ListItemControl or its nested TextControl descendants."""
    try:
        direct = (ctrl.Name or "").strip()
        if direct and not _is_noise_or_icon_text(direct):
            return direct
    except Exception:
        pass

    queue = [(ctrl, 0)]
    visited_nodes = 0
    while queue and visited_nodes < 32:
        node, depth = queue.pop(0)
        visited_nodes += 1
        if depth > 0:
            try:
                nt = node.ControlTypeName
                nm = (node.Name or "").strip()
                if nt in ("TextControl", "EditControl", "ButtonControl") and nm and not _is_noise_or_icon_text(nm):
                    return nm
            except Exception:
                pass
        if depth < max_depth:
            try:
                for ch in node.GetChildren():
                    queue.append((ch, depth + 1))
            except Exception:
                pass
    return ""


def _extract_clean_contact_name(raw_name: str) -> str:
    """Extracts the primary contact display name from a UIA list item Name string."""
    if not raw_name:
        return ""
    text = raw_name.strip()
    # Split on newlines first
    lines = [ln.strip() for ln in text.splitlines() if ln.strip() and not _is_noise_or_icon_text(ln)]
    if lines:
        text = lines[0]

    # Many WhatsApp accessibility labels format chat rows as:
    # "John Smith, 10:42 AM, Hey there..." or "Unread, John Smith, ..."
    parts = [p.strip() for p in text.split(",") if p.strip()]
    if len(parts) > 1:
        if parts[0].lower() in ("unread", "pinned", "muted") or re.match(r"^\d+\s+unread", parts[0].lower()):
            candidate = parts[1]
        else:
            candidate = parts[0]
    else:
        candidate = text

    # Strip trailing timestamps like " 10:45 AM" or " Yesterday"
    candidate = re.sub(r"\s+\d{1,2}:\d{2}\s*(?:AM|PM|am|pm)?.*$", "", candidate).strip()
    candidate = re.sub(r"\s+(?:Yesterday|Today|Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday).*$", "", candidate, flags=re.IGNORECASE).strip()
    if _is_noise_or_icon_text(candidate):
        return ""
    return candidate


def _matches_recipient_query(contact_name: str, query_name: str) -> bool:
    if not contact_name or not query_name:
        return False
    c_low = contact_name.strip().lower()
    q_low = query_name.strip().lower()
    if not c_low or c_low in _SECTION_HEADERS:
        return False
    if len(c_low) > 55:
        return False
    if c_low == q_low:
        return True
    if c_low.startswith(q_low + " ") or c_low.startswith(q_low):
        return True
    words = re.split(r"[\s\-_().]+", c_low)
    if any(w == q_low or w.startswith(q_low) for w in words if w):
        return True
    return False


# ==============================================================================
# BASE MESSAGING PROVIDER & IMPLEMENTATIONS
# ==============================================================================

class MessagingProvider:
    provider_id: str = "base"
    display_name: str = "Messaging Provider"

    def is_available(self) -> bool:
        return True

    def send_message_flow(
        self,
        recipient: str,
        message: str,
        exact_selected: bool,
        preferred_rect: Optional[Tuple[int, int, int, int]],
        on_disambiguate: Callable[[str, str, List[ContactMatch]], None],
        on_error: Callable[[str, str], None],
        cancel_event: threading.Event,
    ):
        raise NotImplementedError


class _WhatsAppUIAEngine:
    """
    Shared state-machine engine driving UIA element detection for both
    WhatsApp Desktop (WinUI / UWP / WebView2) and WhatsApp Web (Browser DOM).
    Never uses fixed sleep(2) delays — every step polls for actual UI readiness.
    """

    def __init__(self, is_web: bool):
        self.is_web = is_web
        self._recent_sent_guard: Dict[Tuple[str, str], float] = {}
        self._guard_lock = threading.Lock()

    def _was_recently_sent(self, recipient: str, message: str) -> bool:
        key = (recipient.strip().lower(), message)
        now = time.time()
        with self._guard_lock:
            ts = self._recent_sent_guard.get(key)
            if ts and (now - ts) < 8.0:
                return True
            return False

    def _mark_sent(self, recipient: str, message: str):
        key = (recipient.strip().lower(), message)
        with self._guard_lock:
            self._recent_sent_guard[key] = time.time()

    def _find_target_window(self, auto) -> Tuple[Optional[Any], int]:
        """Finds the top-level WhatsApp Desktop or WhatsApp Web browser window."""
        import win32gui
        import win32process
        import psutil

        browser_exes = {"chrome.exe", "msedge.exe", "brave.exe", "firefox.exe", "vivaldi.exe", "opera.exe", "arc.exe"}
        matched_hwnd = 0

        def _enum_cb(hwnd, _):
            nonlocal matched_hwnd
            if matched_hwnd or not win32gui.IsWindowVisible(hwnd):
                return True
            title = (win32gui.GetWindowText(hwnd) or "").strip()
            if not title:
                return True
            t_low = title.lower()
            cls = (win32gui.GetClassName(hwnd) or "").strip()

            try:
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                proc_name = psutil.Process(pid).name().lower() if pid else ""
            except Exception:
                proc_name = ""

            if self.is_web:
                if ("whatsapp" in t_low or "web.whatsapp" in t_low) and (
                    proc_name in browser_exes or "Chrome_WidgetWin" in cls or "MozillaWindowClass" in cls
                ):
                    matched_hwnd = hwnd
                    return False
            else:
                if "whatsapp" in t_low and proc_name not in browser_exes:
                    matched_hwnd = hwnd
                    return False
                if proc_name in ("whatsapp.root.exe", "whatsapp.exe") and len(title) > 0:
                    matched_hwnd = hwnd
                    return False
            return True

        try:
            win32gui.EnumWindows(_enum_cb, None)
        except Exception:
            pass

        if matched_hwnd:
            try:
                ctrl = auto.ControlFromHandle(matched_hwnd)
                return ctrl, matched_hwnd
            except Exception:
                pass
        return None, 0

    def _inspect_ui_snapshot(self, win_ctrl, win_hwnd: int, auto, collect_results: bool = True) -> Dict[str, Any]:
        """
        Walks the live UIA tree of `win_ctrl` and returns detected elements:
          - is_loading: bool
          - is_login_qr: bool
          - is_ready: bool
          - search_ctrl: Optional[Control]
          - search_bottom_y: int
          - compose_ctrl: Optional[Control]
          - send_btn_ctrl: Optional[Control]
          - result_items: List[ContactMatch]
        """
        _enable_chromium_accessibility(win_hwnd)

        snapshot = {
            "is_loading": False,
            "is_login_qr": False,
            "is_ready": False,
            "search_ctrl": None,
            "search_bottom_y": 0,
            "compose_ctrl": None,
            "send_btn_ctrl": None,
            "result_items": [],
        }

        try:
            w_rect = win_ctrl.BoundingRectangle
            w_left, w_top, w_right, w_bottom = w_rect.left, w_rect.top, w_rect.right, w_rect.bottom
            w_width = max(400, w_right - w_left)
            w_height = max(300, w_bottom - w_top)
        except Exception:
            return snapshot

        qr_keywords = (
            "use whatsapp on your computer",
            "steps to log in",
            "scan this qr code",
            "scan the qr code",
            "log in with phone number",
            "link with phone number",
            "scan me!",
            "to use whatsapp on your computer",
        )
        loading_keywords = (
            "loading your chats",
            "downloading messages",
            "connecting to whatsapp",
        )

        candidate_results: List[ContactMatch] = []
        seen_names = set()
        seen_row_tops: List[int] = []
        in_messages_section = False
        search_bottom_y = w_top + 110
        snapshot["search_bottom_y"] = search_bottom_y

        max_nodes = 2200
        visited = 0

        try:
            for ctrl, depth in auto.WalkControl(win_ctrl, includeTop=False, maxDepth=18):
                visited += 1
                if visited > max_nodes:
                    break

                try:
                    ctype = ctrl.ControlTypeName
                    cname = (ctrl.Name or "").strip()
                    cid = (ctrl.AutomationId or "").strip()
                except Exception:
                    continue

                cname_low = cname.lower()
                cid_low = cid.lower()

                # 1. Check QR / Login indicators
                if cname_low and any(k in cname_low for k in qr_keywords):
                    snapshot["is_login_qr"] = True

                if cname_low and any(k in cname_low for k in loading_keywords):
                    snapshot["is_loading"] = True

                # 2. Check section headers in left pane ("Messages" section vs "Chats"/"Contacts")
                if ctype == "TextControl" and cname_low in ("messages", "message", "chats", "contacts", "other contacts"):
                    try:
                        tr = ctrl.BoundingRectangle
                        if 0 <= (tr.left - w_left) <= w_width * 0.45 and tr.top >= search_bottom_y:
                            if cname_low in ("messages", "message"):
                                in_messages_section = True
                            else:
                                in_messages_section = False
                    except Exception:
                        pass

                # 3. Check interactive controls
                if ctype in (
                    "EditControl",
                    "DocumentControl",
                    "ComboBoxControl",
                    "ButtonControl",
                    "ListItemControl",
                    "DataItemControl",
                ):
                    try:
                        r = ctrl.BoundingRectangle
                        rl, rt, rr, rb = r.left, r.top, r.right, r.bottom
                        rw = rr - rl
                        rh = rb - rt
                    except Exception:
                        rl = rt = rr = rb = rw = rh = 0

                    if rw <= 8 or rh <= 8:
                        continue

                    rel_x = rl - w_left
                    rel_y = rt - w_top

                    # Detect Search Input Box (top-left pane)
                    if ctype in ("EditControl", "DocumentControl", "ComboBoxControl"):
                        is_search_label = (
                            "search" in cname_low
                            or "search" in cid_low
                            or "new chat" in cname_low
                            or "chatlistsearch" in cid_low
                            or "find" in cname_low
                        )
                        is_top_left_edit = (
                            0 <= rel_x < w_width * 0.48
                            and 24 <= rel_y <= 240
                            and rw >= 80
                            and rh <= 85
                        )
                        if (is_search_label and rel_y <= 260) or (is_top_left_edit and snapshot["search_ctrl"] is None):
                            snapshot["search_ctrl"] = ctrl
                            search_bottom_y = max(search_bottom_y, rb)
                            snapshot["search_bottom_y"] = search_bottom_y
                            snapshot["is_ready"] = True
                            continue

                        # Detect Message Compose Input Box (bottom-right pane)
                        is_compose_label = (
                            "type a message" in cname_low
                            or "write a message" in cname_low
                            or ("message" in cname_low and "search" not in cname_low)
                            or "inputbartextbox" in cid_low
                            or "compose" in cid_low
                            or "lexical" in cid_low
                        )
                        is_bottom_right_edit = (
                            rel_x >= w_width * 0.25
                            and rel_y >= w_height - 230
                            and rw >= 120
                            and rh <= 180
                        )
                        if (is_compose_label and rel_y >= w_height * 0.45) or is_bottom_right_edit:
                            snapshot["compose_ctrl"] = ctrl
                            snapshot["is_ready"] = True
                            continue

                    # Detect collapsed Search Button if EditControl isn't open yet
                    if ctype == "ButtonControl" and snapshot["search_ctrl"] is None:
                        if ("search" in cname_low or "search" in cid_low) and rel_x < w_width * 0.48 and rel_y <= 220:
                            snapshot["search_ctrl"] = ctrl
                            snapshot["is_ready"] = True

                    # Detect Send Button in bottom-right compose area
                    if ctype == "ButtonControl" and (
                        "send" in cname_low
                        or "send" in cid_low
                        or cid_low in ("sendbutton", "rightbutton")
                    ):
                        if rel_x >= w_width * 0.45 and rel_y >= w_height - 190:
                            snapshot["send_btn_ctrl"] = ctrl

                    # Detect Chat / Contact result items in the left sidebar below the search box
                    if collect_results and ctype in ("ListItemControl", "DataItemControl", "ButtonControl"):
                        # For ButtonControl, only accept wide chat-row buttons, not small filter chips ("All", "Unread")
                        min_row_w = 140 if ctype in ("ListItemControl", "DataItemControl") else 185
                        min_row_h = 34 if ctype in ("ListItemControl", "DataItemControl") else 44
                        is_left_pane_row = (
                            0 <= rel_x <= w_width * 0.46
                            and rt >= (search_bottom_y + 2)
                            and rb <= (w_bottom - 8)
                            and rw >= min_row_w
                            and min_row_h <= rh <= 125
                        )
                        if is_left_pane_row:
                            if any(abs(rt - prev_y) < 18 for prev_y in seen_row_tops):
                                continue
                            raw_label = _extract_descendant_label(ctrl, max_depth=4)
                            if raw_label:
                                low_lbl = raw_label.strip().lower()
                                if low_lbl in ("messages", "message"):
                                    in_messages_section = True
                                    continue
                                if low_lbl in ("chats", "contacts", "other contacts", "frequently contacted"):
                                    in_messages_section = False
                                    continue
                                if not in_messages_section:
                                    clean_name = _extract_clean_contact_name(raw_label)
                                    clean_low = clean_name.lower()
                                    if (
                                        clean_name
                                        and clean_low not in _SECTION_HEADERS
                                        and "search" not in clean_low
                                        and "new chat" not in clean_low
                                        and "archived" not in clean_low
                                        and clean_low not in seen_names
                                    ):
                                        seen_names.add(clean_low)
                                        seen_row_tops.append(rt)
                                        candidate_results.append(
                                            ContactMatch(
                                                name=clean_name,
                                                subtitle="WhatsApp Contact",
                                                control_rect=(rl, rt, rr, rb),
                                                row_index=len(candidate_results),
                                            )
                                        )
                                        snapshot["is_ready"] = True
        except Exception:
            pass

        if snapshot["search_ctrl"] is not None or snapshot["compose_ctrl"] is not None:
            snapshot["is_login_qr"] = False
            snapshot["is_ready"] = True

        # Filter out any candidate result that accidentally sat above the discovered search_ctrl bottom
        final_search_bottom = snapshot["search_bottom_y"]
        snapshot["result_items"] = [
            item for item in candidate_results
            if item.control_rect is None or item.control_rect[1] >= (final_search_bottom - 2)
        ]
        return snapshot

    def _get_control_text(self, ctrl) -> str:
        if ctrl is None:
            return ""
        try:
            vp = ctrl.GetValuePattern()
            if vp:
                val = vp.Value
                if val is not None:
                    return str(val)
        except Exception:
            pass
        try:
            tp = ctrl.GetTextPattern()
            if tp:
                return str(tp.DocumentRange.GetText(500) or "").strip()
        except Exception:
            pass
        return ""

    def _select_and_open_chat_row(
        self,
        win_ctrl,
        win_hwnd: int,
        auto,
        resolved_contact: Optional[ContactMatch],
        snap: Dict[str, Any],
    ):
        """
        Opens the target contact's chat in WhatsApp Desktop or WhatsApp Web using both
        precise row clicking and step-timed keyboard selection.
        """
        _activate_hwnd(win_hwnd)

        # 1. If we have a specific bounding rectangle for the contact row, click its left-center
        target_rect = None
        if resolved_contact and resolved_contact.control_rect:
            target_rect = resolved_contact.control_rect
        elif snap.get("result_items"):
            target_rect = snap["result_items"][0].control_rect

        if target_rect:
            rl, rt, rr, rb = target_rect
            cx = rl + min(115, max(45, (rr - rl) // 3))
            cy = (rt + rb) // 2
            try:
                auto.Click(cx, cy, waitTime=0.06)
            except Exception:
                pass
            time.sleep(0.16)
            # Check if compose box is now active or focused
            snap_check = self._inspect_ui_snapshot(win_ctrl, win_hwnd, auto, collect_results=False)
            if snap_check.get("compose_ctrl") is not None:
                return

        # 2. Keyboard navigation from the search box: press Down, skip filter chips if focused, press Enter
        try:
            auto.SendKeys("{Down}", waitTime=0.06)
            time.sleep(0.12)
            foc = auto.GetFocusedControl()
            if foc is not None:
                f_type = foc.ControlTypeName
                f_rect = foc.BoundingRectangle
                f_w = f_rect.right - f_rect.left
                # If focus moved onto a small filter chip button ("All", "Unread", "Contacts") or clear button,
                # press Down again to enter the actual results list
                if f_type == "ButtonControl" and f_w < 150:
                    auto.SendKeys("{Down}", waitTime=0.06)
                    time.sleep(0.10)
                    foc = auto.GetFocusedControl()

                if foc is not None and foc.ControlTypeName in ("ListItemControl", "DataItemControl"):
                    fr = foc.BoundingRectangle
                    if (fr.right - fr.left) >= 120 and (fr.bottom - fr.top) >= 28:
                        cx = fr.left + min(115, max(45, (fr.right - fr.left) // 3))
                        cy = (fr.top + fr.bottom) // 2
                        auto.Click(cx, cy, waitTime=0.05)
            auto.SendKeys("{Enter}", waitTime=0.06)
        except Exception:
            pass

        time.sleep(0.16)
        snap_check = self._inspect_ui_snapshot(win_ctrl, win_hwnd, auto, collect_results=False)
        if snap_check.get("compose_ctrl") is not None:
            return

        # 3. Coordinate fallback: click the first search result slot below the search box in the left pane
        try:
            wr = win_ctrl.BoundingRectangle
            s_bottom = snap.get("search_bottom_y") or (wr.top + 115)
            first_row_x = wr.left + min(155, max(85, int((wr.right - wr.left) * 0.16)))
            first_row_y = s_bottom + 74
            if first_row_y < wr.bottom - 60:
                auto.Click(first_row_x, first_row_y, waitTime=0.06)
                time.sleep(0.14)
        except Exception:
            pass

    def execute_state_machine(
        self,
        launch_fn: Callable[[], bool],
        recipient: str,
        message: str,
        exact_selected: bool,
        preferred_rect: Optional[Tuple[int, int, int, int]],
        on_disambiguate: Callable[[str, str, List[ContactMatch]], None],
        on_error: Callable[[str, str], None],
        cancel_event: threading.Event,
    ):
        if self._was_recently_sent(recipient, message):
            return

        saved_clip = _save_clipboard_state()
        try:
            import uiautomation as auto

            with auto.UIAutomationInitializerInThread():
                state = MessagingState.OPEN_APP
                win_ctrl = None
                win_hwnd = 0
                snap: Dict[str, Any] = {}
                resolved_contact: Optional[ContactMatch] = None
                message_typed = False
                send_dispatched = False

                # 1. OPEN_APP
                win_ctrl, win_hwnd = self._find_target_window(auto)
                if win_hwnd:
                    _activate_hwnd(win_hwnd)
                else:
                    if not launch_fn():
                        on_error(
                            "WhatsApp is not available",
                            "Install WhatsApp Desktop or switch provider to WhatsApp Web in ODD Settings.",
                        )
                        return

                # 2. WAIT_FOR_APP_READY (and WAIT_FOR_LOGIN if QR code screen appears)
                state = MessagingState.WAIT_FOR_APP_READY
                ready_deadline = time.time() + (35.0 if self.is_web else 25.0)
                login_deadline = time.time() + 180.0  # Up to 3 minutes if waiting for user QR scan

                while not cancel_event.is_set():
                    win_ctrl, win_hwnd = self._find_target_window(auto)
                    if win_ctrl and win_hwnd:
                        _activate_hwnd(win_hwnd)
                        snap = self._inspect_ui_snapshot(win_ctrl, win_hwnd, auto)
                        if snap["is_ready"]:
                            break
                        if snap["is_login_qr"]:
                            state = MessagingState.WAIT_FOR_LOGIN
                            # Keep preserving the command while waiting for QR login!
                            if time.time() > login_deadline:
                                on_error(
                                    "WhatsApp Login Timed Out",
                                    f'Scan the QR code in WhatsApp to send "{message}" to {recipient}.',
                                )
                                return
                            time.sleep(0.25)
                            continue

                    if state != MessagingState.WAIT_FOR_LOGIN and time.time() > ready_deadline:
                        if win_hwnd:
                            break
                        on_error(
                            "WhatsApp did not finish loading in time",
                            "Please verify WhatsApp is open and try your command again.",
                        )
                        return
                    time.sleep(0.08)

                if cancel_event.is_set():
                    return

                # Record any visible contacts from the initial sidebar
                if snap.get("result_items"):
                    contact_store.record_contacts([c.name for c in snap["result_items"]])

                # Fast path if user just clicked a disambiguated contact whose bounding rect is already visible on screen
                if exact_selected and preferred_rect is not None:
                    resolved_contact = ContactMatch(name=recipient, control_rect=preferred_rect)
                    state = MessagingState.OPEN_CHAT
                else:
                    state = MessagingState.WAIT_FOR_SEARCH

                # 3. WAIT_FOR_SEARCH & 4. SEARCH_RECIPIENT
                if state == MessagingState.WAIT_FOR_SEARCH:
                    search_ready = False
                    search_deadline = time.time() + 6.0
                    while time.time() < search_deadline and not cancel_event.is_set():
                        _activate_hwnd(win_hwnd)
                        snap = self._inspect_ui_snapshot(win_ctrl, win_hwnd, auto, collect_results=False)
                        s_ctrl = snap.get("search_ctrl")
                        if s_ctrl is not None:
                            try:
                                sr = s_ctrl.BoundingRectangle
                                cx = (sr.left + sr.right) // 2
                                cy = (sr.top + sr.bottom) // 2
                                auto.Click(cx, cy, waitTime=0.04)
                                search_ready = True
                                break
                            except Exception:
                                pass
                        # Trigger WhatsApp's native focus-search shortcut
                        if self.is_web:
                            auto.SendKeys("{Ctrl}{Alt}/", waitTime=0.05)
                        else:
                            auto.SendKeys("{Ctrl}f", waitTime=0.05)
                        time.sleep(0.08)
                        snap = self._inspect_ui_snapshot(win_ctrl, win_hwnd, auto, collect_results=False)
                        if snap.get("search_ctrl") is not None:
                            search_ready = True
                            break
                        try:
                            foc = auto.GetFocusedControl()
                            if foc and foc.ControlTypeName in ("EditControl", "DocumentControl"):
                                search_ready = True
                                break
                        except Exception:
                            pass

                    if cancel_event.is_set():
                        return

                    # 4. SEARCH_RECIPIENT
                    state = MessagingState.SEARCH_RECIPIENT
                    _activate_hwnd(win_hwnd)
                    if not search_ready:
                        if self.is_web:
                            auto.SendKeys("{Ctrl}{Alt}/", waitTime=0.05)
                        else:
                            auto.SendKeys("{Ctrl}f", waitTime=0.05)
                        time.sleep(0.06)

                    # Clear existing search text and input recipient name
                    auto.SendKeys("{Ctrl}a{Back}", waitTime=0.03)
                    _paste_exact_text_via_clipboard(recipient, wait_after=0.14)

                    # 5. WAIT_FOR_RESULTS
                    state = MessagingState.WAIT_FOR_RESULTS
                    results_deadline = time.time() + 1.6
                    last_names: List[str] = []
                    stable_polls = 0
                    matched_items: List[ContactMatch] = []

                    while time.time() < results_deadline and not cancel_event.is_set():
                        time.sleep(0.08)
                        snap = self._inspect_ui_snapshot(win_ctrl, win_hwnd, auto, collect_results=True)
                        raw_items: List[ContactMatch] = snap.get("result_items", [])
                        filtered = [it for it in raw_items if _matches_recipient_query(it.name, recipient)]
                        cur_names = [it.name for it in filtered]
                        if filtered:
                            if cur_names == last_names:
                                stable_polls += 1
                                if stable_polls >= 1:
                                    matched_items = filtered
                                    break
                            else:
                                last_names = cur_names
                                matched_items = filtered
                                stable_polls = 0

                    if matched_items:
                        contact_store.record_contacts([m.name for m in matched_items])

                    # 6. RESOLVE_RECIPIENT
                    state = MessagingState.RESOLVE_RECIPIENT
                    if not exact_selected:
                        if len(matched_items) > 1:
                            state = MessagingState.PAUSED_DISAMBIGUATION
                            on_disambiguate(recipient, message, matched_items)
                            return
                        elif len(matched_items) == 0:
                            cached_matches = contact_store.find_matches(recipient)
                            if len(cached_matches) > 1:
                                state = MessagingState.PAUSED_DISAMBIGUATION
                                on_disambiguate(
                                    recipient,
                                    message,
                                    [ContactMatch(name=n, subtitle="WhatsApp Contact") for n in cached_matches],
                                )
                                return

                    if matched_items:
                        exact_hit = next(
                            (m for m in matched_items if m.name.strip().lower() == recipient.strip().lower()),
                            None,
                        )
                        resolved_contact = exact_hit or matched_items[0]

                    state = MessagingState.OPEN_CHAT

                # 7. OPEN_CHAT
                if cancel_event.is_set():
                    return

                self._select_and_open_chat_row(win_ctrl, win_hwnd, auto, resolved_contact, snap)

                # 8. WAIT_FOR_CHAT & FOCUS MESSAGE FIELD
                state = MessagingState.WAIT_FOR_CHAT
                chat_deadline = time.time() + 2.2
                compose_ctrl = None
                compose_clicked = False

                while time.time() < chat_deadline and not cancel_event.is_set():
                    snap = self._inspect_ui_snapshot(win_ctrl, win_hwnd, auto, collect_results=False)
                    compose_ctrl = snap.get("compose_ctrl")
                    if compose_ctrl is not None:
                        try:
                            compose_ctrl.SetFocus()
                        except Exception:
                            pass
                        try:
                            cr = compose_ctrl.BoundingRectangle
                            if (cr.right - cr.left) > 60 and (cr.bottom - cr.top) > 10:
                                cx = cr.left + min(130, max(35, (cr.right - cr.left) // 3))
                                cy = (cr.top + cr.bottom) // 2
                                auto.Click(cx, cy, waitTime=0.05)
                                compose_clicked = True
                                break
                        except Exception:
                            break

                    # Check if focus is already inside a bottom-right EditControl / DocumentControl
                    try:
                        foc = auto.GetFocusedControl()
                        if foc and foc.ControlTypeName in ("EditControl", "DocumentControl"):
                            fr = foc.BoundingRectangle
                            wr = win_ctrl.BoundingRectangle
                            if (
                                fr.top > wr.top + (wr.bottom - wr.top) * 0.50
                                and fr.left > wr.left + (wr.right - wr.left) * 0.22
                            ):
                                compose_ctrl = foc
                                compose_clicked = True
                                break
                    except Exception:
                        pass
                    time.sleep(0.07)

                if cancel_event.is_set():
                    return

                # Always ensure the bottom-right message compose bar is clicked & focused if UIA didn't click it yet
                if not compose_clicked and win_ctrl is not None:
                    try:
                        wr = win_ctrl.BoundingRectangle
                        cx = wr.left + int((wr.right - wr.left) * 0.62)
                        cy = wr.bottom - 38
                        auto.Click(cx, cy, waitTime=0.06)
                        time.sleep(0.06)
                    except Exception:
                        pass

                # 9. TYPE_MESSAGE (preserving exact message text, preventing duplicate typing)
                state = MessagingState.TYPE_MESSAGE
                if not message_typed:
                    _activate_hwnd(win_hwnd)
                    _paste_exact_text_via_clipboard(message, wait_after=0.16)
                    message_typed = True

                if cancel_event.is_set():
                    return

                # 10. SEND (with duplicate-send prevention)
                state = MessagingState.SEND
                if not send_dispatched and not self._was_recently_sent(recipient, message):
                    _activate_hwnd(win_hwnd)
                    send_dispatched = True
                    self._mark_sent(recipient, message)
                    auto.SendKeys("{Enter}", waitTime=0.05)

                    # Verify submission: if a Send button is still visible after 280ms, click it once
                    time.sleep(0.28)
                    snap_post = self._inspect_ui_snapshot(win_ctrl, win_hwnd, auto, collect_results=False)
                    s_btn = snap_post.get("send_btn_ctrl")
                    if s_btn is not None:
                        try:
                            br = s_btn.BoundingRectangle
                            if (br.right - br.left) > 8 and (br.bottom - br.top) > 8:
                                auto.Click((br.left + br.right) // 2, (br.top + br.bottom) // 2, waitTime=0.04)
                        except Exception:
                            pass

                contact_store.record_contacts([resolved_contact.name if resolved_contact else recipient])
                state = MessagingState.COMPLETED
        finally:
            _restore_clipboard_state_async(saved_clip, delay=0.65)



class WhatsAppDesktopProvider(MessagingProvider):
    provider_id = "whatsapp_desktop"
    display_name = "WhatsApp Desktop"

    def __init__(self):
        self._engine = _WhatsAppUIAEngine(is_web=False)

    def is_available(self) -> bool:
        # 1. Check Store package folder in %LOCALAPPDATA%\Packages or WindowsApps
        local_app_data = os.environ.get("LOCALAPPDATA", "")
        if local_app_data:
            pkg_dir = Path(local_app_data) / "Packages" / "5319275A.WhatsAppDesktop_cv1g1gvanyjgm"
            if pkg_dir.exists():
                return True
            exe_legacy = Path(local_app_data) / "WhatsApp" / "WhatsApp.exe"
            if exe_legacy.exists():
                return True
        # 2. Check whatsapp: protocol in registry
        try:
            import winreg
            for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_CLASSES_ROOT):
                try:
                    with winreg.OpenKey(root, r"Software\Classes\whatsapp" if root == winreg.HKEY_CURRENT_USER else "whatsapp"):
                        return True
                except FileNotFoundError:
                    pass
        except Exception:
            pass
        return False

    def _launch_app(self) -> bool:
        if not self.is_available():
            return False
        try:
            subprocess.Popen(
                ["explorer.exe", r"shell:AppsFolder\5319275A.WhatsAppDesktop_cv1g1gvanyjgm!App"],
                 close_fds=True,
            )
            return True
        except Exception:
            pass
        try:
            os.startfile("whatsapp://")
            return True
        except Exception:
            return False

    def send_message_flow(
        self,
        recipient: str,
        message: str,
        exact_selected: bool,
        preferred_rect: Optional[Tuple[int, int, int, int]],
        on_disambiguate: Callable[[str, str, List[ContactMatch]], None],
        on_error: Callable[[str, str], None],
        cancel_event: threading.Event,
    ):
        self._engine.execute_state_machine(
            launch_fn=self._launch_app,
            recipient=recipient,
            message=message,
            exact_selected=exact_selected,
            preferred_rect=preferred_rect,
            on_disambiguate=on_disambiguate,
            on_error=on_error,
            cancel_event=cancel_event,
        )


class WhatsAppWebProvider(MessagingProvider):
    provider_id = "whatsapp_web"
    display_name = "WhatsApp Web"

    def __init__(self):
        self._engine = _WhatsAppUIAEngine(is_web=True)

    def is_available(self) -> bool:
        return True

    def _launch_web(self) -> bool:
        try:
            webbrowser.open("https://web.whatsapp.com")
            return True
        except Exception:
            return False

    def send_message_flow(
        self,
        recipient: str,
        message: str,
        exact_selected: bool,
        preferred_rect: Optional[Tuple[int, int, int, int]],
        on_disambiguate: Callable[[str, str, List[ContactMatch]], None],
        on_error: Callable[[str, str], None],
        cancel_event: threading.Event,
    ):
        self._engine.execute_state_machine(
            launch_fn=self._launch_web,
            recipient=recipient,
            message=message,
            exact_selected=exact_selected,
            preferred_rect=preferred_rect,
            on_disambiguate=on_disambiguate,
            on_error=on_error,
            cancel_event=cancel_event,
        )


class MessagingManager(QObject):
    """
    Coordinates messaging providers, background state-machine execution,
    recipient disambiguation, and login-resume preservation.
    """
    disambiguation_requested = Signal(str, object)  # (prompt_title, List[ContactMatch])
    error_surfaced = Signal(str, str)  # (title, subtitle)

    _instance: Optional["MessagingManager"] = None

    @classmethod
    def get_instance(cls, settings: Optional[dict] = None) -> "MessagingManager":
        if cls._instance is None:
            cls._instance = MessagingManager(settings or {})
        elif settings is not None:
            cls._instance.settings = settings
        return cls._instance

    def __init__(self, settings: dict):
        super().__init__()
        self.settings = settings
        self.contact_store = contact_store
        self.providers: Dict[str, MessagingProvider] = {
            "whatsapp_desktop": WhatsAppDesktopProvider(),
            "whatsapp_web": WhatsAppWebProvider(),
        }
        self._providers = self.providers
        self._active_cancel_event: Optional[threading.Event] = None
        self._pending_command: Optional[ParsedMessageCommand] = None
        self._disambig_candidates: List[ContactMatch] = []
        self._disambig_message: str = ""
        self._disambig_provider_id: Optional[str] = None

    def get_selected_provider_id(self, override: Optional[str] = None) -> str:
        if override and override in self.providers:
            return override
        pref = str(self.settings.get("messaging_provider", "whatsapp_desktop")).strip().lower()
        if pref not in self.providers:
            pref = "whatsapp_desktop"
        return pref

    def get_selected_provider(self, override: Optional[str] = None) -> MessagingProvider:
        pid = self.get_selected_provider_id(override)
        return self.providers[pid]

    def get_active_provider(self) -> MessagingProvider:
        return self.get_selected_provider()

    def list_providers(self) -> List[Tuple[str, str]]:
        return [(pid, prov.display_name) for pid, prov in self.providers.items()]

    def set_preferred_provider(self, provider_id: str):
        if provider_id in self.providers:
            self.settings["messaging_provider"] = provider_id
            try:
                from odd_settings import save_settings
                save_settings(self.settings)
            except Exception:
                pass

    def set_preferred_provider_id(self, provider_id: str):
        self.set_preferred_provider(provider_id)

    def _trigger_disambiguation(self, recipient: str, message: str, matches: List[ContactMatch], provider_id: str):
        self._disambig_candidates = list(matches)
        self._disambig_message = message
        self._disambig_provider_id = provider_id
        prompt_title = f"Which {recipient} should I send this to?"
        self.disambiguation_requested.emit(prompt_title, list(matches))

    def execute_command(
        self,
        cmd: ParsedMessageCommand,
        exact_selected: bool = False,
        preferred_rect: Optional[Tuple[int, int, int, int]] = None,
    ):
        """
        Starts or resumes a quick message command.
        If pre-cached contacts already show multiple matches for `cmd.recipient` and `exact_selected` is False,
        asks the user immediately before sending; otherwise runs the provider state machine which also
        detects live multiple matches inside WhatsApp.
        """
        self._pending_command = cmd
        provider_id = self.get_selected_provider_id(cmd.provider_override)
        provider = self.providers[provider_id]

        # Check pre-known contacts if user typed an ambiguous first name
        if not exact_selected:
            cached_matches = contact_store.find_matches(cmd.recipient)
            if len(cached_matches) > 1:
                candidates = [ContactMatch(name=n, subtitle=f"{provider.display_name} Contact") for n in cached_matches]
                self._trigger_disambiguation(cmd.recipient, cmd.message, candidates, provider_id)
                return

        if self._active_cancel_event is not None:
            self._active_cancel_event.set()
        cancel_ev = threading.Event()
        self._active_cancel_event = cancel_ev

        def _on_disambiguate(rec: str, msg: str, matches: List[ContactMatch]):
            self._trigger_disambiguation(rec, msg, matches, provider_id)

        def _on_error(title: str, subtitle: str):
            self.error_surfaced.emit(title, subtitle)

        worker = threading.Thread(
            target=provider.send_message_flow,
            args=(
                cmd.recipient,
                cmd.message,
                exact_selected,
                preferred_rect,
                _on_disambiguate,
                _on_error,
                cancel_ev,
            ),
            daemon=True,
        )
        worker.start()

    def select_disambiguated_contact(self, index: int):
        """Called immediately when the user selects one of the matching contacts by index."""
        if 0 <= index < len(self._disambig_candidates):
            selected = self._disambig_candidates[index]
            self.complete_disambiguation(selected, self._disambig_message, self._disambig_provider_id)

    def complete_disambiguation(
        self,
        selected_contact: ContactMatch,
        message: str,
        provider_id: Optional[str] = None,
    ):
        """Called immediately when the user selects one of the matching contacts."""
        cmd = ParsedMessageCommand(
            action="send_message",
            recipient=selected_contact.name,
            message=message,
            raw_query=f"Text {selected_contact.name} {message}",
            provider_override=provider_id,
        )
        self.execute_command(
            cmd,
            exact_selected=True,
            preferred_rect=selected_contact.control_rect,
        )
