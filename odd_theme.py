"""

ODD Design System & Token Engine

Monochrome "Dynamic Island for Windows" Design Tokens, Squircle Geometry,

and Vector Line-Icon Set.

Strict Monochrome Palette: Neutral Grays + White + Black (Zero Hue/Color).

"""

import math

from typing import Tuple, Dict, Optional

from PySide6.QtCore import Qt, QRectF, QPointF

from PySide6.QtGui import (

    QColor, QFont, QPen, QBrush, QPainterPath, QLinearGradient, QPixmap, QPainter

)

# ---------------------------------------------------------------------------

# 1. DESIGN TOKENS: PALETTE (Refined Contrast & Surfaces)

# ---------------------------------------------------------------------------

class Tokens:

    """

    ODD Visual Tokens: Refined Contrast & Surfaces

    - Background:     #070708 (Deep black)

    - Island:         #101012 (Main surface)

    - Elevated:       #171719 (Secondary surfaces)

    - Hover:          #202023 (Interactive feedback)

    - Border subtle:  White 7%  (Surface separation)

    - Border active:  White 16% (Focus)

    - Primary text:   White 94% (Main content)

    - Secondary text: White 58% (Supporting content)

    - Tertiary text:  White 36% (Metadata)

    """

    # Core Surfaces (ODD 2.0 Pure Black Minimal & Premium System)
    BACKGROUND      = QColor(5, 5, 5, 255)       # #050505 Pure black
    ISLAND          = QColor(8, 8, 8, 255)       # #080808 Pure AMOLED black (100% opaque)
    ISLAND_SOLID    = QColor(8, 8, 8, 255)       # #080808 Solid opaque
    ELEVATED        = QColor(14, 14, 15, 255)    # #0E0E0F Solid secondary surfaces
    HOVER           = QColor(24, 24, 26, 255)    # #18181A Interactive feedback
    ACTIVE          = QColor(32, 32, 35, 255)    # #202023 Pressed state
    BORDER_INNER_HIGHLIGHT = QColor(0, 0, 0, 0)  # No gradients or fake highlights

    # Backward Compatibility Surface Aliases

    SURFACE_0       = ISLAND

    SURFACE_0_SOLID = ISLAND_SOLID

    SURFACE_1       = ELEVATED

    SURFACE_2       = HOVER

    SURFACE_3       = ACTIVE

    # Hairline Borders & Dividers (Subtle Grey #292929 & Accessible Focus)
    BORDER_SUBTLE   = QColor(41, 41, 41, 255)    # #292929 Subtle grey border
    BORDER_ACTIVE   = QColor(70, 70, 75, 255)    # #46464B Focus ring / highlight
    BORDER_STRONG   = BORDER_ACTIVE              # #46464B
    BORDER_GLOW     = QColor(90, 90, 95, 255)    # Subtle focus ring
    DIVIDER         = QColor(28, 28, 30, 255)    # Subtle internal divider

    # Typography (White Alphas for Razor-Sharp Hierarchy)

    PRIMARY_TEXT     = QColor(255, 255, 255, 240) # White 94% (Main content)

    SECONDARY_TEXT   = QColor(255, 255, 255, 148) # White 58% (Supporting content)

    TERTIARY_TEXT    = QColor(255, 255, 255, 92)  # White 36% (Metadata)

    TEXT_PRIMARY     = PRIMARY_TEXT               # White 94%

    TEXT_PRIMARY_HEX = "#FFFFFF"

    TEXT_SECONDARY   = SECONDARY_TEXT             # White 58%

    TEXT_TERTIARY    = TERTIARY_TEXT              # White 36%

    TEXT_DISABLED    = QColor(255, 255, 255, 60)  # White ~24%

    # Inverted Contrasts (For Primary White Buttons & Pills)

    INVERT_BG       = QColor(255, 255, 255, 255) # Pure White Fill

    INVERT_TEXT     = QColor(16, 16, 18, 255)    # Solid Dark Text (#101012)

    INVERT_HOVER    = QColor(235, 235, 238, 255) # Hover state on White Fill

    # 4px Spacing Grid

    SPACE_XXS = 4

    SPACE_XS  = 8

    SPACE_SM  = 12

    SPACE_MD  = 16

    SPACE_LG  = 20

    SPACE_XL  = 24

    SPACE_XXL = 32

    # Continuous Corner Radii

    RADIUS_PILL  = 999.0  # Automatic Capsule (r = h / 2)

    RADIUS_PANEL = 30.0   # Large Island Dropdown Panel

    RADIUS_TILE  = 16.0   # Sub-cards & Tiles

    RADIUS_ROW   = 10.0   # Search result rows & list items

    RADIUS_CHIP  = 8.0    # Badges & status chips

    # Motion Timing (Physics Spring Constants)

    SPRING_SNAPPY_RESPONSE  = 0.08

    SPRING_SNAPPY_DAMPING   = 0.92

    SPRING_LIQUID_RESPONSE  = 0.12

    SPRING_LIQUID_DAMPING   = 0.82

    SPRING_SOFT_RESPONSE    = 0.16

    SPRING_SOFT_DAMPING     = 0.88

    # High Contrast Mode Overrides

    @classmethod

    def apply_high_contrast(cls, enabled: bool):

        if enabled:

            cls.SURFACE_0       = QColor(0, 0, 0, 250)

            cls.BORDER_SUBTLE   = QColor(255, 255, 255, 55)

            cls.BORDER_ACTIVE   = QColor(255, 255, 255, 95)

            cls.BORDER_STRONG   = QColor(255, 255, 255, 95)

            cls.TEXT_PRIMARY    = QColor(255, 255, 255, 255)

            cls.TEXT_SECONDARY  = QColor(255, 255, 255, 205)

            cls.TEXT_TERTIARY   = QColor(255, 255, 255, 160)

        else:

            cls.SURFACE_0       = cls.ISLAND

            cls.BORDER_SUBTLE   = QColor(255, 255, 255, 18)

            cls.BORDER_ACTIVE   = QColor(255, 255, 255, 41)

            cls.BORDER_STRONG   = QColor(255, 255, 255, 41)

            cls.TEXT_PRIMARY    = QColor(255, 255, 255, 240)

            cls.TEXT_SECONDARY  = QColor(255, 255, 255, 148)

            cls.TEXT_TERTIARY   = QColor(255, 255, 255, 92)

# ---------------------------------------------------------------------------

# 2. TYPOGRAPHY SCALE (Segoe UI Variable Native Hierarchy)

# ---------------------------------------------------------------------------

class Fonts:

    """

    Segoe UI Variable Type Scale:

    - Hero:            Display, Medium

    - Section heading: Text, Semibold

    - Body:            Text, Regular

    - Metadata:        Text, Medium

    - Numeric values:  Tabular figures

    """

    @staticmethod

    def hero(size: int = 44) -> QFont:

        """Hero role: Display, Medium"""

        font = QFont("Segoe UI Variable Display", size, QFont.Weight.Medium)

        font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)

        return font

    @staticmethod

    def hero_numeral(size: int = 44) -> QFont:

        return Fonts.hero(size)

    @staticmethod

    def section_heading(size: int = 14) -> QFont:

        """Section heading role: Text, Semibold"""

        font = QFont("Segoe UI Variable Text", size, QFont.Weight.DemiBold)

        font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)

        return font

    @staticmethod

    def title(size: int = 15) -> QFont:

        return Fonts.section_heading(size)

    @staticmethod

    def body(size: int = 12, bold: bool = False) -> QFont:

        """Body role: Text, Regular (or Semibold if explicitly bold)"""

        w = QFont.Weight.DemiBold if bold else QFont.Weight.Normal

        font = QFont("Segoe UI Variable Text", size, w)

        font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)

        return font

    @staticmethod

    def metadata(size: int = 11) -> QFont:

        """Metadata role: Text, Medium"""

        font = QFont("Segoe UI Variable Text", size, QFont.Weight.Medium)

        font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)

        return font

    @staticmethod

    def section_header() -> QFont:

        """10.5px All-Caps Section Header with Letter Tracking"""

        font = QFont("Segoe UI Variable Display", 9, QFont.Weight.Bold)

        font.setCapitalization(QFont.Capitalization.AllUppercase)

        font.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 108.0)

        font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)

        return font

    @staticmethod

    def caption(size: int = 10, bold: bool = False) -> QFont:

        w = QFont.Weight.Bold if bold else QFont.Weight.Normal

        font = QFont("Segoe UI Variable Text", size, w)

        font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)

        return font

    @staticmethod

    def tabular(size: int = 12, bold: bool = False) -> QFont:

        """Numeric values: Tabular figures to prevent digit jittering during live value updates"""

        w = QFont.Weight.DemiBold if bold else QFont.Weight.Normal

        font = QFont("Segoe UI Variable Text", size, w)

        font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)

        font.setStyleHint(QFont.StyleHint.SansSerif)

        return font

    tabular_numbers = tabular

# ---------------------------------------------------------------------------

# 3. SQUIRCLE GEOMETRY (Continuous-Curvature Superellipse Path)

# ---------------------------------------------------------------------------

def create_squircle_path(rect: QRectF, radius: float) -> QPainterPath:

    """

    Constructs an analytic continuous-curvature superellipse rounded rectangle

    using cubic Beziers (curvature continuity G2).

    Avoids plain circular-arc joints for the signature Apple/Dynamic Island look.

    """

    w = rect.width()

    h = rect.height()

    max_r = min(w, h) / 2.0

    r = min(max_r, float(radius))

    path = QPainterPath()

    if r <= 0.5:

        path.addRect(rect)

        return path

    x = rect.x()

    y = rect.y()

    # Kappa constant for cubic Bezier approximation of superellipse

    # Standard circle kappa is ~0.55228; superellipse squircle uses 0.5857

    k = 0.5857864376 * r

    path.moveTo(x + r, y)

    # Top edge

    path.lineTo(x + w - r, y)

    # Top-right corner

    path.cubicTo(x + w - r + k, y, x + w, y + r - k, x + w, y + r)

    # Right edge

    path.lineTo(x + w, y + h - r)

    # Bottom-right corner

    path.cubicTo(x + w, y + h - r + k, x + w - r + k, y + h, x + w - r, y + h)

    # Bottom edge

    path.lineTo(x + r, y + h)

    # Bottom-left corner

    path.cubicTo(x + r - k, y + h, x, y + h - r + k, x, y + h - r)

    # Left edge

    path.lineTo(x, y + r)

    # Top-left corner

    path.cubicTo(x, y + r - k, x + r - k, y, x + r, y)

    path.closeSubpath()

    return path

def create_top_anchored_squircle_path(rect: QRectF, bottom_radius: float, top_radius: float = 0.0) -> QPainterPath:
    """
    Constructs a top-anchored continuous-curvature superellipse rounded rectangle.
    Top edge is flush with or subtly inset from the display edge, with generously curved
    continuous-curvature bottom-left and bottom-right superellipse corners.
    """
    w = rect.width()
    h = rect.height()
    max_b_r = min(w / 2.0, h)
    r_b = max(0.0, min(max_b_r, float(bottom_radius)))
    max_t_r = min(w / 2.0, h / 2.0)
    r_t = max(0.0, min(max_t_r, float(top_radius)))

    path = QPainterPath()
    if r_b <= 0.5 and r_t <= 0.5:
        path.addRect(rect)
        return path

    x = rect.x()
    y = rect.y()
    k_b = 0.5857864376 * r_b
    k_t = 0.5857864376 * r_t

    path.moveTo(x + r_t, y)
    path.lineTo(x + w - r_t, y)
    if r_t > 0.5:
        path.cubicTo(x + w - r_t + k_t, y, x + w, y + r_t - k_t, x + w, y + r_t)
    else:
        path.lineTo(x + w, y)
    path.lineTo(x + w, y + h - r_b)
    if r_b > 0.5:
        path.cubicTo(x + w, y + h - r_b + k_b, x + w - r_b + k_b, y + h, x + w - r_b, y + h)
    else:
        path.lineTo(x + w, y + h)
    path.lineTo(x + r_b, y + h)
    if r_b > 0.5:
        path.cubicTo(x + r_b - k_b, y + h, x, y + h - r_b + k_b, x, y + h - r_b)
    else:
        path.lineTo(x, y + h)
    path.lineTo(x, y + r_t)
    if r_t > 0.5:
        path.cubicTo(x, y + r_t - k_t, x + r_t - k_t, y, x + r_t, y)
    else:
        path.lineTo(x, y)
    path.closeSubpath()
    return path


def calculate_dynamic_squircle_radius(width: float, height: float) -> float:

    """

    Keep compact search capsules pill-shaped, then quickly settle to a consistent

    panel radius as the surface expands. A long interpolation made short result

    panels look like oversized capsules with pinched-looking corners.

    """

    if height <= 54.0:

        return height / 2.0

    t = min(1.0, max(0.0, (height - 54.0) / 28.0))

    # Smoothstep gives a continuous change in both radius and slope at each end.

    t = t * t * (3.0 - 2.0 * t)

    pill_r = height / 2.0

    squircle_r = max(20.0, min(24.0, width * 0.035 + 8.0))

    return pill_r * (1.0 - t) + squircle_r * t

# ---------------------------------------------------------------------------

# 4. MONOCHROME LINE-ICON VECTOR SET

# Consistent 1.75px stroke, rounded end-caps, designed for 20x20 and 24x24 grids.

# ---------------------------------------------------------------------------

class MonochromeIcons:

    """

    High-performance vector line-icon painter.

    Renders pure monochrome line icons directly into any painter with zero pixel distortion.

    """

    @staticmethod

    def draw(name: str, painter: QPainter, center: QPointF, size: float = 20.0,

             color: Optional[QColor] = None, stroke_width: float = 1.75):

        cx = center.x()

        cy = center.y()

        s = size / 20.0  # Normalized scale factor

        c = color or Tokens.TEXT_PRIMARY

        pen = QPen(c, stroke_width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)

        painter.setPen(pen)

        painter.setBrush(Qt.BrushStyle.NoBrush)

        n = name.lower().replace("-", "_")

        # Check if custom asset icon exists for dnd, weather, seeme

        if n in ("seeme", "mirror", "island", "bell"):

            try:

                import odd_icons

                col_hex = f"#{c.red():02X}{c.green():02X}{c.blue():02X}"

                pix = odd_icons.get_icons8_pixmap(n, color=col_hex, size=int(size))

                if pix and not pix.isNull():

                    painter.drawPixmap(int(cx - pix.width() / 2.0), int(cy - pix.height() / 2.0), pix)

                    return

            except Exception:

                pass

        # --- Search & General UI Glyphs ---

        if n in ("search", "find"):

            r = 5.2 * s

            painter.drawEllipse(QPointF(cx - 1.5 * s, cy - 1.5 * s), r, r)

            painter.drawLine(QPointF(cx + 2.4 * s, cy + 2.4 * s), QPointF(cx + 6.8 * s, cy + 6.8 * s))

        elif n in ("sliders", "settings", "controls", "quick_settings"):

            # 3-row modern horizontal sliders with adjust pips

            y1, y2, y3 = cy - 4.5 * s, cy, cy + 4.5 * s

            painter.drawLine(QPointF(cx - 7.0 * s, y1), QPointF(cx + 7.0 * s, y1))

            painter.drawLine(QPointF(cx - 7.0 * s, y2), QPointF(cx + 7.0 * s, y2))

            painter.drawLine(QPointF(cx - 7.0 * s, y3), QPointF(cx + 7.0 * s, y3))

            # Pips

            painter.setBrush(QBrush(c))

            painter.drawEllipse(QPointF(cx - 2.5 * s, y1), 1.8 * s, 1.8 * s)

            painter.drawEllipse(QPointF(cx + 2.8 * s, y2), 1.8 * s, 1.8 * s)

            painter.drawEllipse(QPointF(cx - 3.8 * s, y3), 1.8 * s, 1.8 * s)

        elif n in ("phone", "phone_mirror", "android", "mobile"):

            # Clean rounded smartphone outline

            phone_rect = QRectF(cx - 4.8 * s, cy - 7.5 * s, 9.6 * s, 15.0 * s)

            path = QPainterPath()

            path.addRoundedRect(phone_rect, 2.2 * s, 2.2 * s)

            painter.drawPath(path)

            # Camera notch

            painter.drawLine(QPointF(cx - 1.2 * s, cy - 5.4 * s), QPointF(cx + 1.2 * s, cy - 5.4 * s))

            # Home indicator line

            painter.drawLine(QPointF(cx - 1.8 * s, cy + 5.2 * s), QPointF(cx + 1.8 * s, cy + 5.2 * s))

        elif n in ("lens", "google_lens", "image_search"):

            # Material Symbols Outlined 'image_search'

            # 1. Photo frame (top-left)

            frame_rect = QRectF(cx - 7.6 * s, cy - 7.0 * s, 11.2 * s, 9.6 * s)

            painter.drawRoundedRect(frame_rect, 1.8 * s, 1.8 * s)

            # 2. Sun dot inside

            painter.setPen(Qt.PenStyle.NoPen)

            painter.setBrush(QBrush(c))

            painter.drawEllipse(QPointF(cx - 4.4 * s, cy - 4.2 * s), 1.2 * s, 1.2 * s)

            # 3. Mountain line inside

            painter.setBrush(Qt.BrushStyle.NoBrush)

            painter.setPen(QPen(c, 1.25 * s, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))

            mtn = QPainterPath()

            mtn.moveTo(cx - 7.2 * s, cy + 1.0 * s)

            mtn.lineTo(cx - 4.4 * s, cy - 1.2 * s)

            mtn.lineTo(cx - 2.2 * s, cy + 0.8 * s)

            mtn.lineTo(cx - 0.4 * s, cy - 2.0 * s)

            mtn.lineTo(cx + 3.0 * s, cy + 1.0 * s)

            painter.drawPath(mtn)

            # 4. Magnifying glass (bottom-right)

            glass_cx, glass_cy, glass_r = cx + 3.8 * s, cy + 3.2 * s, 3.2 * s

            painter.setPen(QPen(c, 1.45 * s, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))

            painter.drawEllipse(QPointF(glass_cx, glass_cy), glass_r, glass_r)

            painter.setPen(QPen(c, 1.8 * s, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))

            painter.drawLine(QPointF(glass_cx + 2.2 * s, glass_cy + 2.2 * s), QPointF(glass_cx + 4.6 * s, glass_cy + 4.6 * s))

        elif n in ("weather", "cloud", "forecast"):

            # Material Symbols Outlined 'cloud'

            path = QPainterPath()

            path.moveTo(cx + 4.2 * s, cy + 2.8 * s)

            path.lineTo(cx - 3.4 * s, cy + 2.8 * s)

            path.arcTo(QRectF(cx - 6.0 * s, cy - 0.4 * s, 4.4 * s, 3.8 * s), -90, 160)

            path.arcTo(QRectF(cx - 2.8 * s, cy - 4.2 * s, 5.8 * s, 5.4 * s), 170, 160)

            path.arcTo(QRectF(cx + 1.8 * s, cy - 1.0 * s, 4.0 * s, 4.0 * s), 70, 150)

            path.closeSubpath()

            painter.drawPath(path)

        elif n in ("dnd", "do_not_disturb_on_total_silence"):

            # Material Symbols Outlined 'do_not_disturb_on_total_silence'

            painter.drawEllipse(QPointF(cx, cy), 6.5 * s, 6.5 * s)

            painter.drawEllipse(QPointF(cx, cy), 4.2 * s, 4.2 * s)

            painter.drawLine(QPointF(cx - 3.8 * s, cy), QPointF(cx + 3.8 * s, cy))

        elif n in ("camera", "mirror", "seeme", "see_me"):

            # Person-in-mirror glyph, distinct from Lens and screen capture.

            painter.drawEllipse(QPointF(cx, cy - 3.1 * s), 2.6 * s, 2.6 * s)

            shoulders = QPainterPath()

            shoulders.moveTo(cx - 6.3 * s, cy + 5.8 * s)

            shoulders.cubicTo(cx - 6.0 * s, cy + 1.6 * s, cx - 3.4 * s, cy + 0.5 * s, cx, cy + 0.5 * s)

            shoulders.cubicTo(cx + 3.4 * s, cy + 0.5 * s, cx + 6.0 * s, cy + 1.6 * s, cx + 6.3 * s, cy + 5.8 * s)

            painter.drawPath(shoulders)

        elif n in ("snip", "screenshot", "screen_snip", "crop"):

            # Area selection brackets with a small center reticle.

            arm = 3.2 * s

            extent = 6.5 * s

            for sx, sy in ((-1, -1), (1, -1), (-1, 1), (1, 1)):

                x1, y1 = cx + sx * extent, cy + sy * extent

                painter.drawLine(QPointF(x1, y1), QPointF(x1 - sx * arm, y1))

                painter.drawLine(QPointF(x1, y1), QPointF(x1, y1 - sy * arm))

            painter.drawEllipse(QPointF(cx, cy), 1.25 * s, 1.25 * s)

        elif n in ("refresh", "sync", "reload"):

            arc_rect = QRectF(cx - 5.5 * s, cy - 5.5 * s, 11.0 * s, 11.0 * s)

            painter.drawArc(arc_rect, 45 * 16, 270 * 16)

            # Arrow head

            arrow = QPainterPath()

            arrow.moveTo(cx + 2.0 * s, cy - 6.8 * s)

            arrow.lineTo(cx + 5.5 * s, cy - 5.5 * s)

            arrow.lineTo(cx + 4.2 * s, cy - 2.2 * s)

            painter.strokePath(arrow, pen)

        elif n in ("close", "x", "esc"):

            d = 4.2 * s

            painter.drawLine(QPointF(cx - d, cy - d), QPointF(cx + d, cy + d))

            painter.drawLine(QPointF(cx + d, cy - d), QPointF(cx - d, cy + d))

        elif n in ("chevron_right", "next", "arrow_right"):

            path = QPainterPath()

            path.moveTo(cx - 2.2 * s, cy - 4.5 * s)

            path.lineTo(cx + 2.5 * s, cy)

            path.lineTo(cx - 2.2 * s, cy + 4.5 * s)

            painter.strokePath(path, pen)

        elif n in ("chevron_left", "prev", "arrow_left"):

            path = QPainterPath()

            path.moveTo(cx + 2.2 * s, cy - 4.5 * s)

            path.lineTo(cx - 2.5 * s, cy)

            path.lineTo(cx + 2.2 * s, cy + 4.5 * s)

            painter.strokePath(path, pen)

        elif n in ("chevron_down", "expand"):

            path = QPainterPath()

            path.moveTo(cx - 4.5 * s, cy - 2.2 * s)

            path.lineTo(cx, cy + 2.5 * s)

            path.lineTo(cx + 4.5 * s, cy - 2.2 * s)

            painter.strokePath(path, pen)

        elif n in ("check", "tick"):

            path = QPainterPath()

            path.moveTo(cx - 5.0 * s, cy + 0.2 * s)

            path.lineTo(cx - 1.2 * s, cy + 4.0 * s)

            path.lineTo(cx + 5.5 * s, cy - 4.0 * s)

            painter.strokePath(path, pen)

        elif n in ("wifi", "wireless"):

            # 3 concentric arcs with center dot

            for rad, st_ang, spn in ((6.2 * s, 45, 90), (4.0 * s, 45, 90)):

                r_box = QRectF(cx - rad, cy - rad + 3.0 * s, rad * 2, rad * 2)

                painter.drawArc(r_box, st_ang * 16, spn * 16)

            painter.setBrush(QBrush(c))

            painter.drawEllipse(QPointF(cx, cy + 3.6 * s), 1.2 * s, 1.2 * s)

        elif n in ("usb", "wired"):

            painter.drawLine(QPointF(cx, cy - 6.5 * s), QPointF(cx, cy + 6.5 * s))

            painter.drawRect(QRectF(cx - 3.2 * s, cy - 6.5 * s, 6.4 * s, 5.0 * s))

            painter.drawLine(QPointF(cx - 1.2 * s, cy - 4.0 * s), QPointF(cx - 1.2 * s, cy - 2.0 * s))

            painter.drawLine(QPointF(cx + 1.2 * s, cy - 4.0 * s), QPointF(cx + 1.2 * s, cy - 2.0 * s))

        # --- Weather Line Glyphs ---

        elif n in ("weather", "forecast", "sun", "sunny", "clear_day"):

            # Sun center circle + 8 radiating tick rays

            painter.drawEllipse(QPointF(cx, cy), 3.8 * s, 3.8 * s)

            for i in range(8):

                ang = i * (math.pi / 4.0)

                r1 = 5.6 * s

                r2 = 7.6 * s

                painter.drawLine(

                    QPointF(cx + r1 * math.cos(ang), cy + r1 * math.sin(ang)),

                    QPointF(cx + r2 * math.cos(ang), cy + r2 * math.sin(ang))

                )

        elif n in ("moon", "clear_night"):
            # Smooth crescent moon
            path = QPainterPath()
            path.moveTo(cx + 2.5 * s, cy - 6.5 * s)
            path.cubicTo(cx - 5.5 * s, cy - 4.5 * s, cx - 5.5 * s, cy + 4.5 * s, cx + 2.5 * s, cy + 6.5 * s)
            path.cubicTo(cx - 1.2 * s, cy + 3.2 * s, cx - 1.2 * s, cy - 3.2 * s, cx + 2.5 * s, cy - 6.5 * s)
            painter.strokePath(path, pen)

        elif n in ("cloud", "cloudy", "overcast"):
            # Smooth cubic Bezier cloud contour (zero criss-cross lines)
            path = QPainterPath()
            path.moveTo(cx + 4.8 * s, cy + 3.0 * s)
            path.lineTo(cx - 4.8 * s, cy + 3.0 * s)
            path.cubicTo(cx - 7.6 * s, cy + 3.0 * s, cx - 7.6 * s, cy - 0.4 * s, cx - 4.8 * s, cy - 0.7 * s)
            path.cubicTo(cx - 5.2 * s, cy - 5.2 * s, cx + 1.2 * s, cy - 5.5 * s, cx + 3.0 * s, cy - 2.5 * s)
            path.cubicTo(cx + 7.0 * s, cy - 2.5 * s, cx + 7.6 * s, cy + 3.0 * s, cx + 4.8 * s, cy + 3.0 * s)
            painter.strokePath(path, pen)

        elif n in ("partly_cloudy", "partly_cloudy_day", "cloud_sun", "sun_cloud"):
            # Sun rays peeking from behind cloud
            for ang in (-0.8, -0.4, 0.0, 0.4):
                painter.drawLine(
                    QPointF(cx + 1.2 * s + 5.0 * s * math.cos(ang), cy - 2.5 * s + 5.0 * s * math.sin(ang)),
                    QPointF(cx + 1.2 * s + 7.2 * s * math.cos(ang), cy - 2.5 * s + 7.2 * s * math.sin(ang))
                )
            # Cloud in foreground
            path = QPainterPath()
            path.moveTo(cx + 4.2 * s, cy + 3.5 * s)
            path.lineTo(cx - 5.0 * s, cy + 3.5 * s)
            path.cubicTo(cx - 7.5 * s, cy + 3.5 * s, cx - 7.5 * s, cy + 0.5 * s, cx - 5.0 * s, cy + 0.2 * s)
            path.cubicTo(cx - 5.2 * s, cy - 3.8 * s, cx + 0.8 * s, cy - 4.2 * s, cx + 2.5 * s, cy - 1.8 * s)
            path.cubicTo(cx + 6.2 * s, cy - 1.8 * s, cx + 6.8 * s, cy + 3.5 * s, cx + 4.2 * s, cy + 3.5 * s)
            painter.strokePath(path, pen)

        elif n in ("partly_cloudy_night", "cloud_moon", "moon_cloud"):
            # Crescent moon peeking from behind cloud
            m_path = QPainterPath()
            m_cx = cx + 2.5 * s
            m_cy = cy - 3.5 * s
            m_path.moveTo(m_cx + 2.0 * s, m_cy - 4.5 * s)
            m_path.cubicTo(m_cx - 3.5 * s, m_cy - 3.0 * s, m_cx - 3.5 * s, m_cy + 3.0 * s, m_cx + 2.0 * s, m_cy + 4.5 * s)
            m_path.cubicTo(m_cx - 0.5 * s, m_cy + 2.0 * s, m_cx - 0.5 * s, m_cy - 2.0 * s, m_cx + 2.0 * s, m_cy - 4.5 * s)
            painter.strokePath(m_path, pen)
            # Cloud in foreground
            path = QPainterPath()
            path.moveTo(cx + 4.2 * s, cy + 3.5 * s)
            path.lineTo(cx - 5.0 * s, cy + 3.5 * s)
            path.cubicTo(cx - 7.5 * s, cy + 3.5 * s, cx - 7.5 * s, cy + 0.5 * s, cx - 5.0 * s, cy + 0.2 * s)
            path.cubicTo(cx - 5.2 * s, cy - 3.8 * s, cx + 0.8 * s, cy - 4.2 * s, cx + 2.5 * s, cy - 1.8 * s)
            path.cubicTo(cx + 6.2 * s, cy - 1.8 * s, cx + 6.8 * s, cy + 3.5 * s, cx + 4.2 * s, cy + 3.5 * s)
            painter.strokePath(path, pen)

        elif n in ("rain", "rainy", "shower", "rain_light", "rain_heavy", "drizzle"):
            # Cloud
            path = QPainterPath()
            path.moveTo(cx + 4.5 * s, cy + 0.5 * s)
            path.lineTo(cx - 4.5 * s, cy + 0.5 * s)
            path.cubicTo(cx - 7.2 * s, cy + 0.5 * s, cx - 7.2 * s, cy - 2.5 * s, cx - 4.5 * s, cy - 2.8 * s)
            path.cubicTo(cx - 4.8 * s, cy - 6.8 * s, cx + 1.2 * s, cy - 7.2 * s, cx + 2.8 * s, cy - 4.5 * s)
            path.cubicTo(cx + 6.5 * s, cy - 4.5 * s, cx + 7.2 * s, cy + 0.5 * s, cx + 4.5 * s, cy + 0.5 * s)
            painter.strokePath(path, pen)
            # Slanted raindrops
            if n in ("rain_light", "drizzle"):
                painter.drawLine(QPointF(cx - 2.0 * s, cy + 3.5 * s), QPointF(cx - 3.5 * s, cy + 7.0 * s))
                painter.drawLine(QPointF(cx + 2.0 * s, cy + 3.5 * s), QPointF(cx + 0.5 * s, cy + 7.0 * s))
            else:
                painter.drawLine(QPointF(cx - 3.8 * s, cy + 3.5 * s), QPointF(cx - 5.2 * s, cy + 7.0 * s))
                painter.drawLine(QPointF(cx, cy + 3.5 * s), QPointF(cx - 1.4 * s, cy + 7.0 * s))
                painter.drawLine(QPointF(cx + 3.8 * s, cy + 3.5 * s), QPointF(cx + 2.4 * s, cy + 7.0 * s))

        elif n in ("snow", "snowy", "snow_heavy"):
            # Cloud
            path = QPainterPath()
            path.moveTo(cx + 4.5 * s, cy + 0.5 * s)
            path.lineTo(cx - 4.5 * s, cy + 0.5 * s)
            path.cubicTo(cx - 7.2 * s, cy + 0.5 * s, cx - 7.2 * s, cy - 2.5 * s, cx - 4.5 * s, cy - 2.8 * s)
            path.cubicTo(cx - 4.8 * s, cy - 6.8 * s, cx + 1.2 * s, cy - 7.2 * s, cx + 2.8 * s, cy - 4.5 * s)
            path.cubicTo(cx + 6.5 * s, cy - 4.5 * s, cx + 7.2 * s, cy + 0.5 * s, cx + 4.5 * s, cy + 0.5 * s)
            painter.strokePath(path, pen)
            # Snow dots
            painter.setBrush(QBrush(c))
            painter.drawEllipse(QPointF(cx - 3.5 * s, cy + 5.5 * s), 1.0 * s, 1.0 * s)
            painter.drawEllipse(QPointF(cx, cy + 5.5 * s), 1.0 * s, 1.0 * s)
            painter.drawEllipse(QPointF(cx + 3.5 * s, cy + 5.5 * s), 1.0 * s, 1.0 * s)
            painter.setBrush(Qt.BrushStyle.NoBrush)

        elif n in ("thunder", "thunderstorm"):
            # Cloud + lightning bolt
            path = QPainterPath()
            path.moveTo(cx + 4.5 * s, cy + 0.5 * s)
            path.lineTo(cx - 4.5 * s, cy + 0.5 * s)
            path.cubicTo(cx - 7.2 * s, cy + 0.5 * s, cx - 7.2 * s, cy - 2.5 * s, cx - 4.5 * s, cy - 2.8 * s)
            path.cubicTo(cx - 4.8 * s, cy - 6.8 * s, cx + 1.2 * s, cy - 7.2 * s, cx + 2.8 * s, cy - 4.5 * s)
            path.cubicTo(cx + 6.5 * s, cy - 4.5 * s, cx + 7.2 * s, cy + 0.5 * s, cx + 4.5 * s, cy + 0.5 * s)
            painter.strokePath(path, pen)
            # Lightning bolt
            l_path = QPainterPath()
            l_path.moveTo(cx + 0.5 * s, cy + 2.5 * s)
            l_path.lineTo(cx - 1.5 * s, cy + 5.5 * s)
            l_path.lineTo(cx + 1.0 * s, cy + 5.5 * s)
            l_path.lineTo(cx - 0.5 * s, cy + 8.5 * s)
            painter.strokePath(l_path, pen)

        elif n in ("fog", "foggy", "mist"):
            # 3 horizontal mist lines
            painter.drawLine(QPointF(cx - 6.0 * s, cy - 3.0 * s), QPointF(cx + 6.0 * s, cy - 3.0 * s))
            painter.drawLine(QPointF(cx - 7.5 * s, cy), QPointF(cx + 7.5 * s, cy))
            painter.drawLine(QPointF(cx - 5.0 * s, cy + 3.0 * s), QPointF(cx + 5.0 * s, cy + 3.0 * s))

        # --- Media Controls ---
        elif n == "play":

            path = QPainterPath()

            path.moveTo(cx - 3.2 * s, cy - 5.5 * s)

            path.lineTo(cx + 5.5 * s, cy)

            path.lineTo(cx - 3.2 * s, cy + 5.5 * s)

            path.closeSubpath()

            painter.setBrush(QBrush(c))

            painter.drawPath(path)

        elif n == "pause":

            painter.setBrush(QBrush(c))

            painter.drawRoundedRect(QRectF(cx - 4.5 * s, cy - 5.5 * s, 2.8 * s, 11.0 * s), 1.2 * s, 1.2 * s)

            painter.drawRoundedRect(QRectF(cx + 1.7 * s, cy - 5.5 * s, 2.8 * s, 11.0 * s), 1.2 * s, 1.2 * s)

        elif n == "media_prev":

            painter.setBrush(QBrush(c))

            painter.drawRoundedRect(QRectF(cx - 6.0 * s, cy - 5.0 * s, 2.0 * s, 10.0 * s), 1.0 * s, 1.0 * s)

            p_arr = QPainterPath()

            p_arr.moveTo(cx + 4.5 * s, cy - 5.0 * s)

            p_arr.lineTo(cx - 3.0 * s, cy)

            p_arr.lineTo(cx + 4.5 * s, cy + 5.0 * s)

            p_arr.closeSubpath()

            painter.drawPath(p_arr)

        elif n == "media_next":

            painter.setBrush(QBrush(c))

            painter.drawRoundedRect(QRectF(cx + 4.0 * s, cy - 5.0 * s, 2.0 * s, 10.0 * s), 1.0 * s, 1.0 * s)

            p_arr = QPainterPath()

            p_arr.moveTo(cx - 4.5 * s, cy - 5.0 * s)

            p_arr.lineTo(cx + 3.0 * s, cy)

            p_arr.lineTo(cx - 4.5 * s, cy + 5.0 * s)

            p_arr.closeSubpath()

            painter.drawPath(p_arr)

        elif n in ("waveform", "equalizer", "audio_wave"):

            # 5-bar vector sound equalizer

            painter.setBrush(QBrush(c))

            painter.setPen(Qt.PenStyle.NoPen)

            bars = [-5.5 * s, -2.75 * s, 0.0, 2.75 * s, 5.5 * s]

            heights = [5.0 * s, 10.0 * s, 14.0 * s, 8.0 * s, 4.0 * s]

            for x_off, h_val in zip(bars, heights):

                painter.drawRoundedRect(QRectF(cx + x_off - 0.75 * s, cy - h_val / 2.0, 1.5 * s, h_val), 0.75 * s, 0.75 * s)

        elif n in ("sparkle", "ai"):

            # Elegant 4-point sparkle star

            p_sp = QPainterPath()

            p_sp.moveTo(cx, cy - 6.5 * s)

            p_sp.quadTo(cx, cy, cx + 6.5 * s, cy)

            p_sp.quadTo(cx, cy, cx, cy + 6.5 * s)

            p_sp.quadTo(cx, cy, cx - 6.5 * s, cy)

            p_sp.quadTo(cx, cy, cx, cy - 6.5 * s)

            p_sp.closeSubpath()

            painter.setBrush(QBrush(c))

            painter.drawPath(p_sp)

            # Accent mini diamond

            painter.drawEllipse(QPointF(cx + 4.2 * s, cy - 4.2 * s), 1.2 * s, 1.2 * s)

        elif n in ("wellness", "water", "hydration", "drop"):

            # Smooth water droplet

            p_drop = QPainterPath()

            p_drop.moveTo(cx, cy - 6.5 * s)

            p_drop.cubicTo(cx + 4.5 * s, cy - 1.0 * s, cx + 4.5 * s, cy + 4.5 * s, cx, cy + 5.5 * s)

            p_drop.cubicTo(cx - 4.5 * s, cy + 4.5 * s, cx - 4.5 * s, cy - 1.0 * s, cx, cy - 6.5 * s)

            p_drop.closeSubpath()

            painter.setBrush(QBrush(c))

            painter.drawPath(p_drop)

        elif n in ("island", "dynamic_island", "notch"):

            # Dynamic Island horizontal pill outline with circular center camera

            isl_rect = QRectF(cx - 7.5 * s, cy - 3.5 * s, 15.0 * s, 7.0 * s)

            p_isl = QPainterPath()

            p_isl.addRoundedRect(isl_rect, 3.5 * s, 3.5 * s)

            painter.drawPath(p_isl)

            painter.setBrush(QBrush(c))

            painter.drawEllipse(QPointF(cx + 2.5 * s, cy), 1.5 * s, 1.5 * s)

        elif n in ("sound", "volume", "audio", "speaker"):

            # Speaker cone + sound arc

            p_spk = QPainterPath()

            p_spk.moveTo(cx - 5.5 * s, cy - 2.5 * s)

            p_spk.lineTo(cx - 3.0 * s, cy - 2.5 * s)

            p_spk.lineTo(cx - 0.5 * s, cy - 5.5 * s)

            p_spk.lineTo(cx - 0.5 * s, cy + 5.5 * s)

            p_spk.lineTo(cx - 3.0 * s, cy + 2.5 * s)

            p_spk.lineTo(cx - 5.5 * s, cy + 2.5 * s)

            p_spk.closeSubpath()

            painter.setBrush(QBrush(c))

            painter.drawPath(p_spk)

            # Sound waves

            painter.setBrush(Qt.BrushStyle.NoBrush)

            painter.drawArc(QRectF(cx + 0.5 * s, cy - 3.5 * s, 7.0 * s, 7.0 * s), -45 * 16, 90 * 16)

        elif n in ("infomatic", "clock", "time"):

            # Clock circle with hands at 10:10

            painter.drawEllipse(QPointF(cx, cy), 6.0 * s, 6.0 * s)

            painter.drawLine(QPointF(cx, cy), QPointF(cx, cy - 3.2 * s))

            painter.drawLine(QPointF(cx, cy), QPointF(cx + 2.5 * s, cy - 1.5 * s))

        elif n in ("dnd", "moon_dnd"):

            # Crescent moon for Do Not Disturb

            p_moon = QPainterPath()

            p_moon.moveTo(cx + 2.0 * s, cy - 6.0 * s)

            p_moon.cubicTo(cx - 4.5 * s, cy - 4.0 * s, cx - 4.5 * s, cy + 4.0 * s, cx + 2.0 * s, cy + 6.0 * s)

            p_moon.cubicTo(cx - 1.5 * s, cy + 3.0 * s, cx - 1.5 * s, cy - 3.0 * s, cx + 2.0 * s, cy - 6.0 * s)

            p_moon.closeSubpath()

            painter.setBrush(QBrush(c))

            painter.drawPath(p_moon)

        else:

            # Fallback neutral glyph (hollow round dot)

            painter.drawEllipse(QPointF(cx, cy), 3.5 * s, 3.5 * s)

