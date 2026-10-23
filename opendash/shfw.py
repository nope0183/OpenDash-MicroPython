"""SHFW register table and pure helpers (ported from upstream shfw.h).

The table is generated from tools/shfw_registers.csv.  Keep tuples compact:
this module is imported on an ESP32 without PSRAM.  Addresses are ESC words,
lengths are bytes.  Masked fields preserve the other bits of a 16-bit word.
"""

KIND_NUM, KIND_FLAG, KIND_ENUM = range(3)

# Operation results shared by the BLE client and the UI.  Keeping them here
# avoids the UI importing the hardware-facing ninebot module.
(SHFW_OK, SHFW_LOCKED, SHFW_NO_LINK, SHFW_MOVING, SHFW_NOT_DETECTED,
 SHFW_READ_FAIL, SHFW_VERIFY_FAIL, SHFW_NO_VERSION, SHFW_EMPTY,
 SHFW_BAD_SLOT, SHFW_VER_MISMATCH, SHFW_SAVE_FAIL, SHFW_WRITE_FAIL,
 SHFW_RESERVED, SHFW_NOCHANGE) = range(15)

GROUPS_EN = (
    'Power & limits',
    'Modes & profiles',
    'Lights',
    'Dashboard',
    'System',
    'Expert',
)
GROUPS_RU = (
    'Мощность и лимиты',
    'Режимы и профили',
    'Свет',
    'Приборная панель',
    'Система',
    'Эксперт',
)

# (value, English label); the scooter protocol uses the numeric value.
OPTS = (
    (0, 'Off'),
    (1, 'Time'),
    (2, 'Single tap'),
    (3, 'Double tap'),
    (0, 'Drive'),
    (1, 'Eco'),
    (2, 'Sport'),
    (3, 'Last'),
    (0, 'None'),
    (1, 'Single'),
    (2, 'Long'),
    (3, 'Double'),
    (4, 'Extra Long'),
    (0, 'Off'),
    (1, 'On'),
    (2, 'Flashing'),
    (3, 'Full brightness'),
    (0, 'Off'),
    (1, 'On'),
    (2, 'Flashing'),
    (3, 'Full brightness'),
    (0, 'Off'),
    (1, 'On'),
    (2, 'Flashing'),
    (3, 'Full brightness'),
    (0, 'Off'),
    (1, 'On'),
    (2, 'Flashing'),
    (3, 'Full brightness'),
    (0, 'Off'),
    (2, 'Average speed (km/h)'),
    (3, 'Uptime'),
    (4, 'Trip mileage (km)'),
    (5, 'Battery level'),
    (6, 'Voltage'),
    (10, 'Average speed (mp/h)'),
    (11, 'Average speed (m/s)'),
    (14, 'Battery temperature'),
    (15, 'Throttle value'),
    (16, 'Brake value'),
    (19, 'Remaining mileage (km)'),
    (2, 'Average speed (km/h)'),
    (3, 'Uptime'),
    (4, 'Trip mileage (km)'),
    (5, 'Battery level'),
    (6, 'Voltage'),
    (7, 'Speed (mp/h)'),
    (8, 'Speed (km/h)'),
    (9, 'Speed (m/s)'),
    (10, 'Average speed (mp/h)'),
    (11, 'Average speed (m/s)'),
    (14, 'Battery temperature'),
    (17, 'Current'),
    (18, 'Power (10W)'),
    (19, 'Remaining mileage (km)'),
    (22, 'Phase current'),
    (0, 'Off'),
    (2, 'Average Speed (km/h)'),
    (3, 'Uptime'),
    (4, 'Trip mileage (km)'),
    (5, 'Battery level'),
    (6, 'Voltage'),
    (7, 'Speed (mp/h)'),
    (8, 'Speed (km/h)'),
    (9, 'Speed (m/s)'),
    (10, 'Average Speed (mp/h)'),
    (11, 'Average Speed (m/s)'),
    (12, 'CC Speed (mp/h)'),
    (13, 'CC Speed (km/h)'),
    (14, 'Battery temperature'),
    (17, 'Current'),
    (18, 'Power (10W)'),
    (19, 'Remaining mileage (km)'),
    (22, 'Phase current'),
    (0, 'Off'),
    (1, 'Throttle value'),
    (2, 'Brake value'),
    (3, 'Current of max A'),
    (4, '% of speed limit'),
    (5, 'Active profile'),
)

# name, reg, len, group, kind, mask, min, max, scale, decimals, unit, optFirst, optCount
ITEMS = (
    ('Speed limit [S]', 0x11, 1, 0, 0, 0x00FF, 1, 100, 1.0, 0, 'km/h', 0, 0),
    ('Speed limit [D]', 0x12, 1, 0, 0, 0x00FF, 1, 100, 1.0, 0, 'km/h', 0, 0),
    ('Speed limit [E]', 0x13, 1, 0, 0, 0x00FF, 1, 100, 1.0, 0, 'km/h', 0, 0),
    ('Motor Start speed', 0x14, 1, 0, 0, 0x00FF, 0, 10, 1.0, 0, 'km/h', 0, 0),
    ('Brake boost', 0x14, 2, 0, 0, 0xFF00, 0, 100, 1.0, 0, '%', 0, 0),
    ('Speed limit enabled [E]', 0x16, 2, 0, 1, 0x0020, 0, 1, 1.0, 0, '', 0, 0),
    ('Speed limit enabled [D]', 0x16, 2, 0, 1, 0x0040, 0, 1, 1.0, 0, '', 0, 0),
    ('Speed limit enabled [S]', 0x16, 2, 0, 1, 0x0080, 0, 1, 1.0, 0, '', 0, 0),
    ('Brake min speed', 0x1C, 1, 0, 0, 0x00FF, 0, 10, 1.0, 0, 'km/h', 0, 0),
    ('Brake phase current limit', 0x1C, 2, 0, 0, 0xFF00, 0, 100, 1.0, 0, 'A', 0, 0),
    ('Autobraking', 0x1D, 2, 0, 0, 0xFF00, 0, 65, 1.0, 0, 'A', 0, 0),
    ('Torque phase current limit', 0x20, 2, 0, 0, 0xFF00, 0, 100, 1.0, 0, 'A', 0, 0),
    ('Acceleration boost', 0x21, 2, 0, 0, 0xFF00, 0, 100, 1.0, 0, '%', 0, 0),
    ('Current Limit', 0x7A, 2, 0, 0, 0xFFFF, 0, 10000, 0.01, 2, 'A', 0, 0),
    ('Current smoothness', 0x89, 2, 0, 0, 0xFF00, 1, 25, 0.1, 1, 'A', 0, 0),
    ('Negative current limit', 0xF2, 2, 0, 0, 0xFF00, 0, 65, 1.0, 0, 'A', 0, 0),
    ('Swap button Functions', 0x16, 2, 1, 1, 0x0001, 0, 1, 1.0, 0, '', 0, 0),
    ('S mode only', 0x16, 2, 1, 1, 0x0010, 0, 1, 1.0, 0, '', 0, 0),
    ('Cruise control', 0x19, 1, 1, 2, 0x00FF, 0, 0, 1.0, 0, '', 0, 4),
    ('Default Mode', 0x1B, 1, 1, 2, 0x00FF, 0, 0, 1.0, 0, '', 4, 4),
    ('Profile Activation Beep type', 0x1B, 2, 1, 2, 0xFF00, 0, 0, 1.0, 0, '', 8, 5),
    ('Disable mode: Eco', 0x22, 2, 1, 1, 0x0040, 0, 1, 1.0, 0, '', 13, 0),
    ('Disable mode: Drive', 0x22, 2, 1, 1, 0x0080, 0, 1, 1.0, 0, '', 13, 0),
    ('Disable mode: Sport', 0x22, 2, 1, 1, 0x0100, 0, 1, 1.0, 0, '', 13, 0),
    ('Active profile', 0xB2, 2, 1, 0, 0x00FF, 1, 3, 1.0, 0, '', 13, 0),
    ('Boot profile', 0xB3, 2, 1, 0, 0x00FF, 0, 3, 1.0, 0, '', 13, 0),
    ('Boot profile with brake handle pressed', 0xB4, 2, 1, 0, 0x00FF, 0, 3, 1.0, 0, '', 13, 0),
    ('Boot profile with accelerator pressed', 0xB5, 2, 1, 0, 0x00FF, 0, 3, 1.0, 0, '', 13, 0),
    ('Boot profile with accelerator and brake handle pressed', 0xB6, 2, 1, 0, 0x00FF, 0, 3, 1.0, 0, '', 13, 0),
    ('Button press with brake handle pressed', 0xB7, 2, 1, 0, 0x00FF, 0, 3, 1.0, 0, '', 13, 0),
    ('Button double press with brake handle pressed', 0xB8, 2, 1, 0, 0x00FF, 0, 3, 1.0, 0, '', 13, 0),
    ('Accelerator and brake handle pressed profile', 0xB9, 2, 1, 0, 0x00FF, 0, 3, 1.0, 0, '', 13, 0),
    ('Always on headlight', 0x16, 2, 2, 1, 0x0004, 0, 1, 1.0, 0, '', 13, 0),
    ('Taillight smoothing', 0x1F, 2, 2, 0, 0xFF00, 0, 25, 1.0, 0, '', 13, 0),
    ('Taillight mode while not braking', 0x23, 1, 2, 2, 0x00FF, 0, 0, 1.0, 0, '', 13, 4),
    ('Taillight mode while braking', 0x23, 2, 2, 2, 0xFF00, 0, 0, 1.0, 0, '', 17, 4),
    ('Taillight mode while not braking with headlight on', 0x24, 1, 2, 2, 0x00FF, 0, 0, 1.0, 0, '', 21, 4),
    ('Taillight mode while braking with headlight on', 0x24, 2, 2, 2, 0xFF00, 0, 0, 1.0, 0, '', 25, 4),
    ('Taillight brightness', 0xF6, 2, 2, 0, 0x00FF, 1, 100, 1.0, 0, '%', 29, 0),
    ('No brake light with autobraking', 0xFE, 2, 2, 1, 0x0040, 0, 1, 1.0, 0, '', 29, 0),
    ('Dashboard Idle data type', 0x17, 1, 3, 2, 0x00FF, 0, 0, 1.0, 0, '', 29, 12),
    ('Dashboard Drive data type', 0x17, 2, 3, 2, 0xFF00, 0, 0, 1.0, 0, '', 41, 15),
    ('Dashboard Alternating data type', 0x18, 1, 3, 2, 0x00FF, 0, 0, 1.0, 0, '', 56, 18),
    ('Battery bar data type', 0x18, 2, 3, 2, 0xFF00, 0, 0, 1.0, 0, '', 74, 6),
    ('Disable Boot beep', 0x16, 2, 4, 1, 0x0002, 0, 1, 1.0, 0, '', 80, 0),
    ('Auto-shutdown delay', 0xF7, 2, 4, 0, 0x00FF, 0, 30, 1.0, 0, 'min', 80, 0),
    ('Auto shutdown delay when locked', 0xF8, 2, 4, 0, 0x00FF, 0, 255, 1.0, 0, '', 80, 0),
    ('Wheel size', 0xF9, 2, 4, 0, 0x00FF, 60, 120, 0.1, 1, 'in', 80, 0),
    ('Disable Charging mode', 0xFE, 2, 4, 1, 0x0002, 0, 1, 1.0, 0, '', 80, 0),
    ('Switch off motor without throttle', 0xFE, 2, 4, 1, 0x0010, 0, 1, 1.0, 0, '', 80, 0),
    ('Require a key', 0xFE, 2, 4, 1, 0x0080, 0, 1, 1.0, 0, '', 80, 0),
    ('Field weakening [S]', 0x16, 2, 5, 1, 0x0800, 0, 1, 1.0, 0, '', 80, 0),
    ('Field weakening [D]', 0x16, 2, 5, 1, 0x1000, 0, 1, 1.0, 0, '', 80, 0),
    ('Field weakening [E]', 0x16, 2, 5, 1, 0x2000, 0, 1, 1.0, 0, '', 80, 0),
    ('Field weakening Start Speed', 0x1E, 1, 5, 0, 0x00FF, 0, 65, 1.0, 0, 'km/h', 80, 0),
    ('Initial field current', 0x1E, 2, 5, 0, 0xFF00, 0, 15, 1.0, 0, 'A', 80, 0),
    ('Variable field current', 0x1F, 1, 5, 0, 0x00FF, 0, 250, 10.0, 0, 'mA*km/h', 80, 0),
    ('Field phase current limit', 0x20, 1, 5, 0, 0x00FF, 0, 100, 1.0, 0, 'A', 80, 0),
    ('Negative start speed', 0x22, 2, 5, 1, 0x0001, 0, 1, 1.0, 0, '', 80, 0),
    ('Motor PWM overmodulation [S]', 0x22, 2, 5, 1, 0x0002, 0, 1, 1.0, 0, '', 80, 0),
    ('Motor PWM overmodulation [D]', 0x22, 2, 5, 1, 0x0004, 0, 1, 1.0, 0, '', 80, 0),
    ('Motor PWM overmodulation [E]', 0x22, 2, 5, 1, 0x0008, 0, 1, 1.0, 0, '', 80, 0),
    ('Disable DPC smoothing', 0x22, 2, 5, 1, 0x0020, 0, 1, 1.0, 0, '', 80, 0),
    ('Positive battery current limit', 0x25, 1, 5, 0, 0x00FF, 0, 255, 1.0, 0, '', 80, 0),
    ('Suppress all errors', 0xED, 2, 5, 1, 0x0001, 0, 1, 1.0, 0, '', 80, 0),
    ('Suppress BMS temperature errors', 0xED, 2, 5, 1, 0x0002, 0, 1, 1.0, 0, '', 80, 0),
    ('Suppress general BMS errors', 0xED, 2, 5, 1, 0x0004, 0, 1, 1.0, 0, '', 80, 0),
    ('Suppress motor temperature errors', 0xED, 2, 5, 1, 0x0008, 0, 1, 1.0, 0, '', 80, 0),
    ('Suppress general motor errors', 0xED, 2, 5, 1, 0x0010, 0, 1, 1.0, 0, '', 80, 0),
    ('Suppress ESC temperature errors', 0xED, 2, 5, 1, 0x0020, 0, 1, 1.0, 0, '', 80, 0),
    ('Suppress general ESC errors', 0xED, 2, 5, 1, 0x0040, 0, 1, 1.0, 0, '', 80, 0),
    ('Suppress accelerator and brake handle errors', 0xED, 2, 5, 1, 0x0080, 0, 1, 1.0, 0, '', 80, 0),
    ('Motor PWM Frequency', 0xF1, 2, 5, 0, 0x00FF, 4, 24, 1.0, 0, '', 80, 0),
    ('Constant Kd', 0xF2, 1, 5, 0, 0x00FF, 1, 50, 1.0, 0, '', 80, 0),
    ('Constant Kp', 0xF3, 1, 5, 0, 0x00FF, 1, 50, 1.0, 0, '', 80, 0),
    ('Constant Ki', 0xF3, 2, 5, 0, 0xFF00, 10, 120, 1.0, 0, '', 80, 0),
    ('Min brake value', 0xF4, 1, 5, 0, 0x00FF, 30, 210, 1.0, 0, '', 80, 0),
    ('Max brake value', 0xF4, 2, 5, 0, 0xFF00, 30, 210, 1.0, 0, '', 80, 0),
    ('Min throttle value', 0xF5, 1, 5, 0, 0x00FF, 30, 210, 1.0, 0, '', 80, 0),
    ('Max throttle value', 0xF5, 2, 5, 0, 0xFF00, 30, 210, 1.0, 0, '', 80, 0),
    ('BMS emulation', 0xFA, 2, 5, 0, 0xFFFF, 0, 11, 1.0, 0, '', 80, 0),
    ('Battery Capacity', 0xFC, 2, 5, 0, 0xFFFF, 0, 65535, 1.0, 0, 'mAh', 80, 0),
    ('Enable new Max Motors (PxxH)', 0xFE, 2, 5, 1, 0x0100, 0, 1, 1.0, 0, '', 80, 0),
)

# (reg, words) ranges covering every writable setting.
RUNS = (
    (0x01, 20),
    (0x16, 4),
    (0x1B, 11),
    (0x7A, 1),
    (0x89, 1),
    (0xB2, 12),
    (0xE9, 3),
    (0xED, 1),
    (0xF1, 14),
)

DUMP_BYTES = 134
TABLE_ID = 0x9F88
MAX_XFER = 0x50
VER_MAX = 32

# Profiles are three 59-word blocks; the active profile lives in B2 low byte.
PROFILE_WORDS = 59
PROFILE_BYTES = 118
PROFILE_FROM = (0x01, 0x3C, 0x77)
PROFILE_LAYOUT = 0x5001


def chunk_runs():
    """Return (reg, bytes, offset) blocks no larger than MAX_XFER."""
    out = []
    off = 0
    for reg, words in RUNS:
        left = words * 2
        done = 0
        while left:
            n = left if left < MAX_XFER else MAX_XFER
            out.append((reg + done // 2, n, off))
            done += n
            off += n
            left -= n
    return tuple(out)


CHUNKS = chunk_runs()


def shift(mask):
    return (mask & -mask).bit_length() - 1


def word_from_bytes(data, length):
    return data[0] | (data[1] << 8) if length >= 2 else data[0]


def bytes_from_word(word, length):
    return bytes((word & 0xFF, (word >> 8) & 0xFF)) if length >= 2 else bytes((word & 0xFF,))


def field(item, word):
    sh = shift(item[5])
    return (word & item[5]) >> sh


def set_field(item, word, value):
    sh = shift(item[5])
    return (word & ~item[5]) | ((value << sh) & item[5])


def clamp(item, value):
    kind = item[4]
    if kind == KIND_FLAG:
        return 1 if value else 0
    if kind == KIND_ENUM:
        first = item[11]
        for i in range(first, first + item[12]):
            if OPTS[i][0] == value:
                return value
        return OPTS[first][0]
    if value < item[6]:
        return item[6]
    if value > item[7]:
        return item[7]
    return value


def enum_step(item, value, direction):
    first = item[11]
    n = item[12]
    idx = 0
    for i in range(n):
        if OPTS[first + i][0] == value:
            idx = i
            break
    idx = (idx + direction + n) % n
    return OPTS[first + idx][0]


def opt_label(item, value):
    first = item[11]
    for i in range(first, first + item[12]):
        if OPTS[i][0] == value:
            return OPTS[i][1]
    return None


def format_value(item, raw, ru):
    kind = item[4]
    if kind == KIND_FLAG:
        return ("ВКЛ" if ru else "ON") if raw else ("ВЫКЛ" if ru else "OFF")
    if kind == KIND_ENUM:
        label = opt_label(item, raw)
        return label if label is not None else "?%d" % raw
    dec = item[9]
    if dec:
        text = ("%%.%df" % dec) % (raw * item[8])
    else:
        text = "%d" % (raw * item[8])
    return text + (" " + item[10] if item[10] else "")


def steps(item):
    span = item[7] - item[6]
    if span <= 30:
        return 1, 5
    if span <= 300:
        return 1, 10
    if span <= 3000:
        return 10, 100
    return 100, 1000


def crc16(data, crc=0xFFFF):
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if crc & 0x8000 else (crc << 1)
            crc &= 0xFFFF
    return crc


def group_items(group):
    return tuple(i for i, item in enumerate(ITEMS) if item[3] == group)


# Precomputed once at import; the menus reuse these tuples while scrolling.
GROUP_ITEMS = tuple(group_items(g) for g in range(6))
GROUP_COUNTS = tuple(len(items) for items in GROUP_ITEMS)

