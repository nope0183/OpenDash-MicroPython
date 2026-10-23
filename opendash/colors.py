"""RGB565 colour helpers and the four OpenDash themes."""


def rgb565(r, g, b):
    return ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)


def swap(c):
    """Byte-swap a RGB565 value.

    ``framebuf`` stores RGB565 in little-endian order while the panel expects
    the high byte first.  Pre-swapping the colour constants lets us keep a
    normal RGB565 framebuffer and send its bytes to the display unchanged.
    """
    return ((c & 0xFF) << 8) | (c >> 8)


# theme name, Russian name, bg, panel, track, txt, dim, good, warn, bad
THEMES = (
    ("NAVY", "Синяя",
     rgb565(8, 10, 18), rgb565(20, 26, 42), rgb565(36, 44, 64),
     rgb565(240, 244, 252), rgb565(125, 138, 165), rgb565(60, 225, 120),
     rgb565(255, 190, 40), rgb565(255, 70, 70)),
    ("BLACK", "Чёрная",
     rgb565(0, 0, 0), rgb565(18, 18, 22), rgb565(44, 44, 52),
     rgb565(245, 245, 250), rgb565(130, 135, 150), rgb565(60, 225, 120),
     rgb565(255, 190, 40), rgb565(255, 70, 70)),
    ("SLATE", "Серая",
     rgb565(30, 34, 40), rgb565(46, 52, 60), rgb565(74, 82, 94),
     rgb565(236, 240, 246), rgb565(150, 160, 176), rgb565(60, 225, 120),
     rgb565(255, 190, 40), rgb565(255, 80, 80)),
    ("LIGHT", "Светлая",
     rgb565(232, 236, 244), rgb565(255, 255, 255), rgb565(205, 212, 226),
     rgb565(16, 20, 32), rgb565(92, 104, 126), rgb565(0, 150, 70),
     rgb565(225, 140, 0), rgb565(215, 40, 40)),
)

ACCENTS = (
    rgb565(0, 200, 255), rgb565(70, 120, 255), rgb565(170, 90, 255),
    rgb565(255, 80, 170), rgb565(255, 70, 70), rgb565(255, 140, 30),
    rgb565(255, 210, 40), rgb565(60, 225, 120),
)
ACCENT_NAME = ("cyan", "blue", "purple", "pink", "red", "orange", "yellow", "green")
ACCENT_NAME_RU = ("голубой", "синий", "сиреневый", "розовый", "красный",
                  "оранжевый", "жёлтый", "зелёный")
STYLE_NAME = ("fade", "solid", "zones")
STYLE_NAME_RU = ("плавная", "один цвет", "зоны")

LED_COLORS = (0x00C8FF, 0x4678FF, 0xAA5AFF, 0xFF50AA,
              0xFF4646, 0xFF8C1E, 0xFFD228, 0x3CE178)
LED_EFFECT_NAMES = ("OFF", "SOLID", "PULSE", "RAINBOW", "BLINK", "BREATH",
                    "CHASE", "COMET", "TWINKLE", "GRADIENT", "BOUNCE", "FILL")
LED_EFFECT_NAMES_RU = ("выкл.", "постоянный", "пульсация", "радуга", "мигание",
                       "дыхание", "бегущая", "комета", "искры", "градиент",
                       "отскок", "заливка")
LED_BRAKE_NAMES = ("OFF", "ALL", "REAR SEG")
LED_BRAKE_NAMES_RU = ("выкл.", "вся лента", "задний сегмент")

# status colours used on the connection screen
COL_BG = THEMES[0][2]
COL_PANEL = THEMES[0][3]
COL_TRACK = THEMES[0][4]
COL_TXT = THEMES[0][5]
COL_DIM = THEMES[0][6]
COL_GOOD = THEMES[0][7]
COL_WARN = THEMES[0][8]
COL_BAD = THEMES[0][9]
COL_ACCENT = ACCENTS[0]


def apply_theme(theme, accent, hue):
    global COL_BG, COL_PANEL, COL_TRACK, COL_TXT, COL_DIM
    global COL_GOOD, COL_WARN, COL_BAD, COL_ACCENT
    t = THEMES[theme if 0 <= theme < len(THEMES) else 0]
    COL_BG, COL_PANEL, COL_TRACK, COL_TXT = t[2], t[3], t[4], t[5]
    COL_DIM, COL_GOOD, COL_WARN, COL_BAD = t[6], t[7], t[8], t[9]
    COL_ACCENT = ACCENTS[accent] if 0 <= accent < len(ACCENTS) else hue565(hue)


def hue565(h):
    h = ((h % 360) + 360) % 360
    f = (h % 60) * 255 // 60
    s = h // 60
    if s == 0:
        r, g, b = 255, f, 0
    elif s == 1:
        r, g, b = 255 - f, 255, 0
    elif s == 2:
        r, g, b = 0, 255, f
    elif s == 3:
        r, g, b = 0, 255 - f, 255
    elif s == 4:
        r, g, b = f, 0, 255
    else:
        r, g, b = 255, 0, 255 - f
    return rgb565(r, g, b)


def lerp565(a, b, t):
    if t <= 0:
        return a
    if t >= 255:
        return b
    ar, ag, ab = (a >> 11) & 31, (a >> 5) & 63, a & 31
    br, bg, bb = (b >> 11) & 31, (b >> 5) & 63, b & 31
    r = ar + (br - ar) * t // 255
    g = ag + (bg - ag) * t // 255
    bl = ab + (bb - ab) * t // 255
    return (r << 11) | (g << 5) | bl


def hsv_rgb(h, s, v):
    """HSV (0..359, 0..255, 0..255) -> (r, g, b)."""
    h = ((h % 360) + 360) % 360
    f = (h % 60) * 255 // 60
    q = h // 60
    if q == 0:
        r, g, b = 255, f, 0
    elif q == 1:
        r, g, b = 255 - f, 255, 0
    elif q == 2:
        r, g, b = 0, 255, f
    elif q == 3:
        r, g, b = 0, 255 - f, 255
    elif q == 4:
        r, g, b = f, 0, 255
    else:
        r, g, b = 255, 0, 255 - f
    return (r * s // 255 * v // 255,
            g * s // 255 * v // 255,
            b * s // 255 * v // 255)


def rgb_to_hsv(r, g, b):
    mx = max(r, g, b)
    mn = min(r, g, b)
    d = mx - mn
    v = mx
    s = 0 if mx == 0 else d * 255 // mx
    if d == 0:
        return 0, s, v
    if mx == r:
        hh = (g - b) * 60 // d
    elif mx == g:
        hh = 120 + (b - r) * 60 // d
    else:
        hh = 240 + (r - g) * 60 // d
    return (hh % 360), s, v
