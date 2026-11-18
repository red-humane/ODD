import os
import sys
import tempfile
from typing import Optional, Dict, Tuple
from pathlib import Path
from PySide6.QtCore import QByteArray, QSize, Qt
from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor
from PySide6.QtSvg import QSvgRenderer

SVG_TEMPLATES = {
    "general": """<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
<line x1="4" y1="21" x2="4" y2="14"></line>
<line x1="4" y1="10" x2="4" y2="3"></line>
<line x1="12" y1="21" x2="12" y2="12"></line>
<line x1="12" y1="8" x2="12" y2="3"></line>
<line x1="20" y1="21" x2="20" y2="16"></line>
<line x1="20" y1="12" x2="20" y2="3"></line>
<line x1="1" y1="14" x2="7" y2="14"></line>
<line x1="9" y1="8" x2="15" y2="8"></line>
<line x1="17" y1="16" x2="23" y2="16"></line>
</svg>""",

    "appearance": """<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
<rect x="2" y="3" width="20" height="14" rx="2" ry="2"></rect>
<line x1="8" y1="21" x2="16" y2="21"></line>
<line x1="12" y1="17" x2="12" y2="21"></line>
</svg>""",

    "prefixes": """<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
<polyline points="4 17 10 11 4 5"></polyline>
<line x1="12" y1="19" x2="20" y2="19"></line>
</svg>""",

    "rook": """<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
<path d="M12 2L2 7l10 5 10-5-10-5z"></path>
<path d="M2 17l10 5 10-5"></path>
<path d="M2 12l10 5 10-5"></path>
</svg>""",

    "feedback": """<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path>
</svg>""",

    "wellness": """<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
<path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"></path>
</svg>""",

    "chat": """<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
<path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"></path>
</svg>""",

    "user": """<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
<path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path>
<circle cx="12" cy="7" r="4"></circle>
</svg>""",

    "modules": """<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
<rect x="3" y="3" width="7" height="7"></rect>
<rect x="14" y="3" width="7" height="7"></rect>
<rect x="14" y="14" width="7" height="7"></rect>
<rect x="3" y="14" width="7" height="7"></rect>
</svg>""",

    "refresh": """<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
<path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"></path>
<path d="M3 3v5h5"></path>
</svg>""",

    "phone": """<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
<rect x="5" y="2" width="14" height="20" rx="2" ry="2"></rect>
<line x1="12" y1="18" x2="12.01" y2="18"></line>
</svg>""",

    "mirror": """<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
<rect x="2" y="3" width="20" height="14" rx="2" ry="2"></rect>
<line x1="8" y1="21" x2="16" y2="21"></line>
<line x1="12" y1="17" x2="12" y2="21"></line>
<rect x="14" y="6" width="6" height="9" rx="1" fill="{color}" opacity="0.3"></rect>
</svg>""",

    "update": """<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
<path d="M21 12a9 9 0 0 0-9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"></path>
<path d="M3 3v5h5"></path>
<path d="M3 12a9 9 0 0 0 9 9 9.75 9.75 0 0 0 6.74-2.74L21 16"></path>
<path d="M21 21v-5h-5"></path>
</svg>""",

    "volume": """<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
<polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"></polygon>
<path d="M15.54 8.46a5 5 0 0 1 0 7.07"></path>
<path d="M19.07 4.93a10 10 0 0 1 0 14.14"></path>
</svg>""",

    "plus": """<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
<line x1="12" y1="5" x2="12" y2="19"></line>
<line x1="5" y1="12" x2="19" y2="12"></line>
</svg>""",

    "trash": """<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
<polyline points="3 6 5 6 21 6"></polyline>
<path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
</svg>""",

    "lightbulb": """<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
<path d="M9 18h6"></path>
<path d="M10 22h4"></path>
<path d="M15.09 14c.18-.98.65-1.74 1.41-2.5A4.65 4.65 0 0 0 18 8 6 6 0 0 0 6 8c0 1 .23 2.23 1.5 3.5.76.76 1.23 1.52 1.41 2.5"></path>
</svg>""",

    "mail": """<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
<rect x="2" y="4" width="20" height="16" rx="2"></rect>
<path d="m22 7-8.97 5.7a1.94 1.94 0 0 1-2.06 0L2 7"></path>
</svg>""",

    "copy": """<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
<rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
<path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
</svg>""",

    "check": """<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="3.5" stroke-linecap="round" stroke-linejoin="round">
<polyline points="20 6 9 17 4 12"></polyline>
</svg>""",

    "check_circle": """<svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
<circle cx="12" cy="12" r="10" fill="rgba(34, 197, 94, 0.15)"></circle>
<polyline points="16 9 10 15 7 12"></polyline>
</svg>""",

    "close": """<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
<line x1="18" y1="6" x2="6" y2="18"></line>
<line x1="6" y1="6" x2="18" y2="18"></line>
</svg>""",

    "download": """<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
<polyline points="7 10 12 15 17 10"></polyline>
<line x1="12" y1="15" x2="12" y2="3"></line>
</svg>""",

    "package": """<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
<line x1="16.5" y1="9.4" x2="7.55" y2="4.24"></line>
<path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"></path>
<polyline points="3.27 6.96 12 12.01 20.73 6.96"></polyline>
<line x1="12" y1="22.08" x2="12" y2="12"></line>
</svg>""",

    "calendar": """<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
<rect x="3" y="4" width="18" height="18" rx="2" ry="2"></rect>
<line x1="16" y1="2" x2="16" y2="6"></line>
<line x1="8" y1="2" x2="8" y2="6"></line>
<line x1="3" y1="10" x2="21" y2="10"></line>
</svg>""",

    "activity": """<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
<polyline points="22 12 18 12 15 21 9 3 6 12 2 12"></polyline>
</svg>""",

    "folder_open": """<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
<path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path>
</svg>""",

    "bell": """<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
<path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"></path>
<path d="M13.73 21a2 2 0 0 1-3.46 0"></path>
</svg>""",

    "snooze": """<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
<circle cx="12" cy="12" r="10"></circle>
<polyline points="12 6 12 12 16 14"></polyline>
</svg>""",

    "calendar_reschedule": """<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
<rect x="3" y="4" width="18" height="18" rx="2" ry="2"></rect>
<line x1="16" y1="2" x2="16" y2="6"></line>
<line x1="8" y1="2" x2="8" y2="6"></line>
<line x1="3" y1="10" x2="21" y2="10"></line>
<polyline points="10 14 12 16 16 12"></polyline>
</svg>""",

    "paperclip": """<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
<path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"></path>
</svg>""",

    "chevron_down": """<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
<polyline points="6 9 12 15 18 9"></polyline>
</svg>""",

    "call": """<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
<path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7A2 2 0 0 1 22 16.92z"></path>
</svg>""",

    "power": """<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
<path d="M18.36 6.64a9 9 0 1 1-12.73 0"></path>
<line x1="12" y1="2" x2="12" y2="12"></line>
</svg>""",

    "wifi": """<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
<path d="M5 12.55a11 11 0 0 1 14.08 0"></path>
<path d="M1.42 9a16 16 0 0 1 21.16 0"></path>
<path d="M8.53 16.11a6 6 0 0 1 6.95 0"></path>
<line x1="12" y1="20" x2="12.01" y2="20"></line>
</svg>""",

    "cast": """<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
<path d="M2 16.1A5 5 0 0 1 5.9 20M2 12.05A9 9 0 0 1 9.95 20M2 8V6a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-6"></path>
<line x1="2" y1="20" x2="2.01" y2="20"></line>
</svg>""",

    "home": """<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
<path d="m3 9 9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"></path>
<polyline points="9 22 9 12 15 12 15 22"></polyline>
</svg>""",

    "arrow_left": """<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
<line x1="19" y1="12" x2="5" y2="12"></line>
<polyline points="12 19 5 12 12 5"></polyline>
</svg>""",

    "info": """<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
<circle cx="12" cy="12" r="10"></circle>
<line x1="12" y1="16" x2="12" y2="12"></line>
<line x1="12" y1="8" x2="12.01" y2="8"></line>
</svg>""",

    "bluetooth": """<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
<polyline points="6.5 6.5 17.5 17.5 12 23 12 1 17.5 6.5 6.5 17.5"></polyline>
</svg>""",

    "desktop": """<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
<rect x="2" y="3" width="20" height="14" rx="2" ry="2"></rect>
<line x1="8" y1="21" x2="16" y2="21"></line>
<line x1="12" y1="17" x2="12" y2="21"></line>
</svg>""",

    "folder": """<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
<path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path>
</svg>""",

    "file": """<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
<polyline points="14 2 14 8 20 8"></polyline>
<line x1="16" y1="13" x2="8" y2="13"></line>
<line x1="16" y1="17" x2="8" y2="17"></line>
</svg>""",

    "link": """<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
<path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"></path>
<path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"></path>
</svg>""",

    "moon": """<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
<path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"></path>
</svg>""",

    "puzzle": """<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
<path d="M19.439 7.85c0-1.571-1.274-2.85-2.846-2.85s-2.846 1.279-2.846 2.85H10.15c0-1.571-1.275-2.85-2.846-2.85s-2.846 1.279-2.846 2.85H2.5v4.593c1.571 0 2.85 1.274 2.85 2.846s-1.279 2.846-2.85 2.846V21.5h4.593c0-1.571 1.274-2.85 2.846-2.85s2.846 1.279 2.846 2.85h3.597c0-1.571 1.275-2.85 2.846-2.85s2.846 1.279 2.846 2.85H21.5v-4.593c-1.571 0-2.85-1.274-2.85-2.846s1.279-2.846 2.85-2.846V7.85z"></path>
</svg>""",

    "plugins": """<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
<path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83"></path>
</svg>""",

    "sparkles": """<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
<path d="m12 3-1.912 5.813a2 2 0 0 1-1.275 1.275L3 12l5.813 1.912a2 2 0 0 1 1.275 1.275L12 21l1.912-5.813a2 2 0 0 1 1.275-1.275L21 12l-5.813-1.912a2 2 0 0 1-1.275-1.275L12 3Z"></path>
</svg>""",

    "music": """<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
<path d="M9 18V5l12-2v13"></path>
<circle cx="6" cy="18" r="3"></circle>
<circle cx="18" cy="16" r="3"></circle>
</svg>""",

    "globe": """<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
<circle cx="12" cy="12" r="10"></circle>
<line x1="2" y1="12" x2="22" y2="12"></line>
<path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"></path>
</svg>""",

    "application": """<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
<rect x="2" y="3" width="20" height="18" rx="3" ry="3"></rect>
<line x1="2" y1="9" x2="22" y2="9"></line>
<circle cx="6" cy="6" r="1" fill="{color}"></circle>
<circle cx="10" cy="6" r="1" fill="{color}"></circle>
</svg>""",

        "mobile": """<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
<rect x="5" y="2" width="14" height="20" rx="3" ry="3"></rect>
<line x1="12" y1="18" x2="12.01" y2="18"></line>
</svg>""",

    "do_not_disturb_on_total_silence": """<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
<circle cx="12" cy="12" r="10"></circle>
<circle cx="12" cy="12" r="5" stroke-dasharray="0"></circle>
<line x1="8" y1="12" x2="16" y2="12" stroke-width="2.5"></line>
</svg>""",

    "image_search": """<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
<rect x="3" y="3" width="14" height="14" rx="2" ry="2"></rect>
<circle cx="8" cy="8" r="1.5" fill="{color}"></circle>
<path d="M14 12l-3-3-5 5"></path>
<circle cx="17.5" cy="17.5" r="3.5"></circle>
<line x1="20" y1="20" x2="22" y2="22" stroke-width="2.5"></line>
</svg>""",

    "cloud": """<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
<path d="M17.5 19H9a7 7 0 1 1 6.71-9h1.79a4.5 4.5 0 1 1 0 9Z"></path>
</svg>""",
    "rotate": """<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
<path d="M21 12a9 9 0 1 1-9-9c2.52 0 4.93 1 6.74 2.74L21 8"></path>
<polyline points="21 3 21 8 16 8"></polyline>
</svg>"""
}

_svg_cache_dir = None
_ICONS8_CACHE = {}

def get_icons_dir() -> Path:
    """Returns the assets/icons directory, compatible with dev tree and PyInstaller frozen bundle."""
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        base = Path(sys._MEIPASS)
    else:
        base = Path(__file__).resolve().parent
    return base / "assets" / "icons"

def get_icons8_pixmap(name: str, color: str = "#FFFFFF", size: int = 20) -> Optional[QPixmap]:
    """
    Loads a free white monochrome icon from Icons8 and returns a crisp tinted QPixmap.
    If color is #FFFFFF, returns pristine white monochrome without any tinting overhead.
    Otherwise applies smooth alpha composition to match the requested UI color.
    """
    clean_name = str(name).lower().strip()
    clean_color = str(color).upper().strip()
    key = (clean_name, clean_color, size)
    if key in _ICONS8_CACHE:
        return _ICONS8_CACHE[key]

    try:
        from odd_useanimations import get_useanimation_pixmap
        ua_pix = get_useanimation_pixmap(clean_name, frame_idx=0, color=clean_color, size=size)
        if ua_pix is not None and not ua_pix.isNull():
            _ICONS8_CACHE[key] = ua_pix
            return ua_pix
    except Exception:
        pass

    icons_dir = get_icons_dir()
    name_map = {
        "mobile": "mobile",
        "do_not_disturb_on_total_silence": "do_not_disturb_on_total_silence",
        "image_search": "image_search",
        "cloud": "cloud",

        "android": "android_phone",
        "phone": "android_phone",
        "android-phone": "android_phone",
        "phonelink": "phonelink",
        "mirror": "phonelink",
        "phone_mirror": "phonelink",
        "screen_mirror": "phonelink",
        "cast": "phonelink",
        "volume": "volume",
        "sound": "quick_sound",
        "audio": "volume",
        "wifi": "wifi",
        "wi-fi": "wifi",
        "bluetooth": "bluetooth",
        "sun": "sun",
        "brightness": "brightness",
        "bright": "brightness",
        "battery": "battery",
        "settings": "settings",
        "lens": "google_lens",
        "google_lens": "google_lens",
        "wellness": "quick_wellness",
        "island": "quick_island",
        "bell": "quick_island",
        "dnd": "quick_dnd",
        "moon": "quick_dnd",
        "infomatic": "quick_infomatic",
        "clock": "quick_infomatic",
        "edgebar": "quick_infomatic",
        "camera": "quick_camera",
        "mirror_cam": "quick_camera",
        "seeme": "quick_camera",
        "see_me": "quick_camera",
        "mirror": "quick_camera",
        "weather": "quick_weather",
        "forecast": "quick_weather",
        "snip": "quick_snip",
        "screenshot": "quick_snip",
    }
    canonical = name_map.get(clean_name, clean_name)
    path = icons_dir / f"{canonical}.png"
    if not path.exists():
        return None

    raw_pix = QPixmap(str(path))
    if raw_pix.isNull():
        return None

    scaled = raw_pix.scaled(
        size, size,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation
    )

    qcol = QColor(clean_color)
    if qcol.red() >= 248 and qcol.green() >= 248 and qcol.blue() >= 248 and qcol.alpha() >= 248:
        result = scaled
    else:
        result = QPixmap(scaled.size())
        result.fill(Qt.GlobalColor.transparent)
        p = QPainter(result)
        p.drawPixmap(0, 0, scaled)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
        p.fillRect(result.rect(), qcol)
        p.end()

    _ICONS8_CACHE[key] = result
    return result

def get_asset_cache_dir() -> Path:
    global _svg_cache_dir
    if _svg_cache_dir is None:
        p = Path(tempfile.gettempdir()) / "odd_assets"
        p.mkdir(parents=True, exist_ok=True)
        _svg_cache_dir = p
    return _svg_cache_dir

def render_svg_pixmap(svg_content: str, size: int = 24) -> QPixmap:
    renderer = QSvgRenderer(QByteArray(svg_content.encode("utf-8")))
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    renderer.render(painter)
    painter.end()
    return pix

def get_vector_pixmap(name: str, color: str = "#A0AEC0", size: int = 20) -> QPixmap:
    # 1. Prefer free Icons8 white monochrome icon
    i8_pix = get_icons8_pixmap(name, color=color, size=size)
    if i8_pix is not None and not i8_pix.isNull():
        return i8_pix

    # 2. Fallback to vector SVG template
    template = SVG_TEMPLATES.get(name)
    if not template:
        pix = QPixmap(size, size)
        pix.fill(Qt.GlobalColor.transparent)
        return pix
    svg_str = template.format(color=color)
    return render_svg_pixmap(svg_str, size)

def get_vector_icon(name: str, color: str = "#A0AEC0", size: int = 20, active_color: str = "#FFFFFF") -> QIcon:
    normal_pix = get_vector_pixmap(name, color=color, size=size)
    icon = QIcon()
    icon.addPixmap(normal_pix, QIcon.Mode.Normal, QIcon.State.Off)
    if active_color:
        active_pix = get_vector_pixmap(name, color=active_color, size=size)
        icon.addPixmap(active_pix, QIcon.Mode.Active, QIcon.State.Off)
        icon.addPixmap(active_pix, QIcon.Mode.Selected, QIcon.State.Off)
        icon.addPixmap(active_pix, QIcon.Mode.Normal, QIcon.State.On)
    return icon

def get_checkbox_check_svg_path() -> str:
    """Returns the forward-slash path to the crisp white checkmark SVG for QSS"""
    cache_dir = get_asset_cache_dir()
    svg_path = cache_dir / "odd_check_white.svg"
    if not svg_path.exists():
        svg_content = SVG_TEMPLATES["check"].format(color="#FFFFFF")
        svg_path.write_text(svg_content, encoding="utf-8")
    return str(svg_path).replace("\\", "/")

def get_combo_arrow_svg_path(color: str = "#171717") -> str:
    """Returns the forward-slash path to a clean downward chevron SVG for QComboBox::down-arrow"""
    cache_dir = get_asset_cache_dir()
    clean_hex = color.lstrip("#")
    svg_path = cache_dir / f"odd_arrow_down_{clean_hex}.svg"
    svg_content = SVG_TEMPLATES["chevron_down"].format(color=color)
    svg_path.write_text(svg_content, encoding="utf-8")
    return str(svg_path).replace("\\", "/")
