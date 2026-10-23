"""OpenDash MicroPython port - board configuration and defaults.

Ported from nope0183/OpenDash v2.1.1 (Arduino/C++).
"""

# ---------------------------------------------------------------- hardware
# CYD ESP32-2432S028 (2 USB revision).  The ILI9341 revision only differs
# by the panel controller.
DISPLAY_DRIVER = "st7789"        # "st7789" or "ili9341"

TFT_WIDTH = 240
TFT_HEIGHT = 320
TFT_SCLK = 14
TFT_MOSI = 13
TFT_MISO = 12
TFT_CS = 15
TFT_DC = 2
TFT_RST = None
TFT_BL = 21
TFT_SPI_ID = 1
TFT_BAUD = 40_000_000

TOUCH_CS = 33
TOUCH_IRQ = 36
TOUCH_SCLK = 25
TOUCH_MOSI = 32
TOUCH_MISO = 39
TOUCH_SPI_ID = 2
TOUCH_BAUD = 2_000_000

BTN_PIN = 0

LED_PINS = (4, 16, 17, 22, 26, 27)
LED_MAX_COUNT = 120

# ---------------------------------------------------------------- ninebot
TARGET_NAME = ""                 # "" = auto-detect NB / Ninebot / Segway / ES4
POLL_INTERVAL = 400
FAST_TELEMETRY_POLL_MS = 200
LINK_TIMEOUT = 6000
GAUGE_MAX = 30

SPEED_SCALE = 0.1
TRIP_SCALE = 0.01
TOTAL_SCALE = 0.001
ETEMP_SCALE = 0.1
BMS_CUR_SCALE = 0.01
BMS_VOLT_SCALE = 0.01
BRAKE_REGEN_CURRENT_A = 1.0
BRAKE_HOLD_MS = 700

ADDR_APP = 0x3E
ADDR_ESC = 0x20
ADDR_BMS = 0x22

NUS_SVC = "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
NUS_TX = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"
NUS_RX = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"

# ---------------------------------------------------------------- settings
SETTINGS_FILE = "/opendash.json"
SET_VER = 1

# metric ids (same order as the original)
M_BATT, M_POWER, M_TRIP, M_TEMP, M_ODO, M_VOLT, M_CURR, M_MAXSPD = range(8)
M_COUNT = 8

METRIC_NAME = (
    "BATTERY", "POWER", "TRIP", "ESC / BAT", "ODOMETER", "VOLTAGE",
    "CURRENT", "TOP SPEED",
)
METRIC_NAME_RU = (
    "Батарея", "Мощность", "Поездка", "Темп. ESC/АКБ", "Одометр",
    "Напряжение", "Ток", "Макс. скорость",
)

DIM_SEC = (0, 15, 30, 60)

DEFAULT_SETTINGS = {
    "ver": SET_VER,
    "theme": 0,
    "accent": 0,
    "style": 0,
    "units": 0,
    "bright": 100,
    "dim": 0,
    "flip": 0,
    "lock": 1,
    "showInfo": 1,
    "showDebug": 1,
    "gmaxKmh": GAUGE_MAX,
    "gmaxMph": 18,
    "card": [0, 1, 2, 3],
    "lang": 0,
    "hue": 200,
    "ota": 0,
    "cal": {
        "valid": 0, "swap": 0, "x0": 0.0, "xk": 1.0,
        "y0": 0.0, "yk": 1.0, "flip": 0,
    },
    "led": {
        "enabled": 0,
        "pinIndex": 3,
        "count": 30,
        "segmentCount": [10, 10, 10],
        "effect": [1, 2, 3],
        "bright": 64,
        "brake": 1,
        "hue": [193, 98, 224],
        "sat": [255, 187, 185],
        "val": [255, 225, 255],
    },
}
