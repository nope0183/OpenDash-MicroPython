"""BLE client for Ninebot G30 / ES4 (Nordic UART + encrypted handshake).

The implementation follows the original OpenDash state machine:
scan -> connect -> discover NUS -> subscribe -> INIT/PING/PAIR -> telemetry.
"""
import bluetooth
import os
import struct
import time

try:
    from . import config
    from .crypto import NinebotCrypto
except ImportError:
    from opendash import config
    from opendash.crypto import NinebotCrypto

# The SHFW table is large for an ESP32 without PSRAM.  Keep it off the boot
# path: Ninebot.__init__ must succeed even when the heap is tight, and the
# table is only imported when the rider opens the SHFW menu.
shfw = None
shfwstore = None

_MAX_XFER = 0x50
_VER_MAX = 32
_DUMP_BYTES = 134
_PROFILE_BYTES = 118
_PROFILE_WORDS = 59


def _load_shfw():
    global shfw
    if shfw is None:
        try:
            from opendash import shfw as mod
        except ImportError:
            from . import shfw as mod
        shfw = mod
    return shfw


def _load_store():
    global shfwstore
    if shfwstore is None:
        try:
            from opendash import shfwstore as mod
        except ImportError:
            from . import shfwstore as mod
        shfwstore = mod
    return shfwstore

# ------------------------------------------------------------------ telemetry
(SPEED, TRIP, TOTAL_LO, TOTAL_HI, ETEMP, SOC, AMP, VOLT, BTEMP,
 SERIAL_NO, FW, RIDE_MODE) = range(12)

POLL_LIST = (
    (config.ADDR_BMS, 0x32, 2, SOC),
    (config.ADDR_BMS, 0x34, 2, VOLT),
    (config.ADDR_BMS, 0x35, 2, BTEMP),
    (config.ADDR_ESC, 0xB9, 2, TRIP),
    (config.ADDR_ESC, 0x3E, 2, ETEMP),
    (config.ADDR_ESC, 0x29, 2, TOTAL_LO),
    (config.ADDR_ESC, 0x2A, 2, TOTAL_HI),
    (config.ADDR_ESC, 0x10, 14, SERIAL_NO),
    (config.ADDR_ESC, 0x1A, 2, FW),
    (config.ADDR_ESC, 0x75, 2, RIDE_MODE),
)

AUTH_IDLE, AUTH_WAIT_INIT, AUTH_WAIT_PING, AUTH_WAIT_PAIR, AUTH_READY = range(5)

IDLE, SCAN, CONNECT, DISCOVER, AUTH, READY = range(6)

# MicroPython exposes BLE events as plain integers.  Their names live in the
# C implementation and are not attributes of the ``bluetooth`` module, so we
# have to declare them locally (values from extmod/modbluetooth.h).
_IRQ_SCAN_RESULT = 5
_IRQ_SCAN_DONE = 6
_IRQ_PERIPHERAL_CONNECT = 7
_IRQ_PERIPHERAL_DISCONNECT = 8
_IRQ_GATTC_SERVICE_RESULT = 9
_IRQ_GATTC_SERVICE_DONE = 10
_IRQ_GATTC_CHARACTERISTIC_RESULT = 11
_IRQ_GATTC_CHARACTERISTIC_DONE = 12
_IRQ_GATTC_DESCRIPTOR_RESULT = 13
_IRQ_GATTC_DESCRIPTOR_DONE = 14
_IRQ_GATTC_READ_RESULT = 15
_IRQ_GATTC_READ_DONE = 16
_IRQ_GATTC_WRITE_DONE = 17
_IRQ_GATTC_NOTIFY = 18
_IRQ_GATTC_INDICATE = 19

STATE_NAMES = ("idle", "scan", "connect", "discover", "auth", "ready")

# SHFW operation results shared with the UI.  The same numeric values live in
# shfw.py; keeping local copies avoids importing the large table at boot.
(SHFW_OK, SHFW_LOCKED, SHFW_NO_LINK, SHFW_MOVING, SHFW_NOT_DETECTED,
 SHFW_READ_FAIL, SHFW_VERIFY_FAIL, SHFW_NO_VERSION, SHFW_EMPTY,
 SHFW_BAD_SLOT, SHFW_VER_MISMATCH, SHFW_SAVE_FAIL, SHFW_WRITE_FAIL,
 SHFW_RESERVED, SHFW_NOCHANGE) = range(15)


def _uuid_le(text):
    raw = bytes.fromhex(text.replace("-", ""))
    return raw[::-1]


def _u16(data, pos=0):
    return data[pos] | (data[pos + 1] << 8)


def _s16(data, pos=0):
    v = _u16(data, pos)
    return v - 0x10000 if v & 0x8000 else v


def _hex(data, n=16):
    return "".join("%02X" % b for b in data[:n])


class Telemetry:
    def __init__(self):
        self.reset()

    def reset(self):
        self.speed = 0.0
        self.trip_km = 0.0
        self.total_km = 0.0
        self.esc_temp = 0.0
        self.batt_temp = 0.0
        self.volt = 0.0
        self.amp = 0.0
        self.soc = -1
        self.serial = ""
        self.fw = 0
        self.ride_mode = 0
        self.valid = 0
        self.total_low = 0
        self.total_high = 0
        self.session_max = 0.0
        self.brake_until = 0

    def has(self, bit):
        return bool(self.valid & (1 << bit))

    def has_total(self):
        mask = (1 << TOTAL_LO) | (1 << TOTAL_HI)
        return (self.valid & mask) == mask


class Ninebot:
    def __init__(self):
        self.ble = bluetooth.BLE()

        self.nus_svc = _uuid_le(config.NUS_SVC)
        self.nus_tx = _uuid_le(config.NUS_TX)
        self.nus_rx = _uuid_le(config.NUS_RX)

        self.crypto = NinebotCrypto()
        self.data = Telemetry()

        self.state = IDLE
        self.auth_state = AUTH_IDLE
        self.conn = None
        self.connected = False
        self.dev_name = ""
        self.status_text = "NO LINK"
        self.status_color = 0xF800
        self.press_power = False

        self.tx_handle = None
        self.rx_handle = None
        self.tx_props = 0
        self.svc_start = 0
        self.svc_end = 0
        self.found_svc = False
        self.sub_handle = None
        self.sub_status = None

        self.txq = []
        self.tx_busy = False
        self.tx_busy_at = 0
        self.next_tx = 0
        self.write_status = None

        self.auth_last = 0
        self.auth_attempts = 0
        self.last_rx = 0
        self.last_fast = 0
        self.last_poll = 0
        self.poll_idx = 0
        self.poll_brake = False
        self.retry_at = 0
        self.deadline = 0
        self.ready_at = 0

        self.scan_results = {}
        self.scan_done = False
        self.pending_connect = None
        self._disconnected = False
        self._connected_evt = False
        self._svc_ready = False
        self._char_ready = False
        self._chars = {}
        self._rx = bytearray()
        self.rxbuf = bytearray()
        self.rx_seen = 0
        self.notify_count = 0
        self.frame_count = 0
        self.tx_count = 0
        self.tx_failures = 0
        self.checksum_errors = 0
        self.last_notify = b""
        self.dbg = [""] * 7

        # ---------------------------------------------------------- SHFW
        # Writes stay locked until the user explicitly enables them on the
        # SHFW screen.  The flag is deliberately not part of the saved
        # settings and is therefore false after every reboot.
        self.shfw_enabled = False
        self.shfw_force = False
        self.shfw_forced = False
        self.shfw_detected = -1          # -1 unknown, 0 absent, 1 present
        self.shfw_profile = 0
        self.shfw_diag = ""
        self.shfw_ver = b""
        self.shfw_ver_len = 0
        self.shfw_saved_ver = b""
        self.shfw_profile_got = 0
        # The caches are allocated on first use.  Ninebot() runs while the
        # boot heap is tight, so it must not reserve ~2 KB for a menu that may
        # never be opened.
        self.shfw_word = None            # cached 16-bit config words
        self.shfw_have = None            # cached bytes per word (0/1/2)
        self.shfw_rx_pending = False
        self.shfw_rx_ok = False
        self.shfw_rx_reg = 0
        self.shfw_rx_len = 0
        self.shfw_rx_data = None
        self.shfw_ver_pending = False
        self.shfw_ver_ok = False
        self.shfw_ver_data = None
        self.shfw_dump = None
        self.shfw_prof_buf = None
        self.shfw_prof_ok = None
        self.shfw_prof_cur = None
        self.shfw_prof_cur_ok = None
        self.shfw_last_fail_count = 0
        self.shfw_last_fail_reg = 0

        # Activate only after every attribute used by _irq exists.  Activating
        # (or registering the handler) earlier can deliver an event into a
        # half-initialised object and abort Ninebot() during boot.
        self.ble.active(True)
        self.ble.irq(self._irq)

    # ------------------------------------------------------------------ IRQ
    def _irq(self, event, data):
        try:
            if event == _IRQ_SCAN_RESULT:
                addr_type, addr, adv_type, rssi, adv = data
                name = self._adv_name(adv)
                if name and self._name_matches(name):
                    old = self.scan_results.get(name)
                    if old is None or rssi > old[0]:
                        self.scan_results[name] = (rssi, addr_type, bytes(addr))
            elif event == _IRQ_SCAN_DONE:
                self.scan_done = True
            elif event == _IRQ_PERIPHERAL_CONNECT:
                self.conn = data[0]
                self._connected_evt = True
            elif event == _IRQ_PERIPHERAL_DISCONNECT:
                self.conn = None
                self._disconnected = True
            elif event == _IRQ_GATTC_SERVICE_RESULT:
                _conn, start, end, uuid = data
                if bytes(uuid) == self.nus_svc:
                    self.svc_start = start
                    self.svc_end = end
                    self.found_svc = True
            elif event == _IRQ_GATTC_SERVICE_DONE:
                self._svc_ready = True
            elif event == _IRQ_GATTC_CHARACTERISTIC_RESULT:
                _conn, _definition, value, props, uuid = data
                uuid = bytes(uuid)
                if uuid == self.nus_tx:
                    self.tx_handle = value
                    self.tx_props = props
                elif uuid == self.nus_rx:
                    self.rx_handle = value
            elif event == _IRQ_GATTC_CHARACTERISTIC_DONE:
                self._char_ready = True
            elif event == _IRQ_GATTC_WRITE_DONE:
                handle = data[1] if len(data) > 1 else None
                status = data[2] if len(data) > 2 else 0
                if self.sub_handle is not None and handle == self.sub_handle:
                    self.sub_status = status
                elif self.tx_busy:
                    # A completion arriving after the 800 ms timeout must not
                    # be mistaken for the completion of a newer packet.
                    self.write_status = status
            elif event == _IRQ_GATTC_NOTIFY:
                _conn, value_handle, notify_data = data
                if value_handle == self.rx_handle:
                    self.notify_count += 1
                    self.last_rx = time.ticks_ms()
                    self.last_notify = bytes(notify_data[:20])
                    if len(self._rx) < 512:
                        self._rx.extend(notify_data)
        except Exception as exc:      # never raise from the BLE IRQ
            print("ble irq:", exc)

    @staticmethod
    def _adv_name(adv):
        i = 0
        n = len(adv)
        while i + 1 < n:
            ln = adv[i]
            if ln == 0:
                break
            typ = adv[i + 1]
            if typ in (0x08, 0x09) and i + 2 + ln - 1 <= n:
                try:
                    return bytes(adv[i + 2:i + 1 + ln]).decode()
                except Exception:
                    return ""
            i += ln + 1
        return ""

    @staticmethod
    def _name_matches(name):
        if config.TARGET_NAME:
            return name == config.TARGET_NAME
        low = name.lower()
        return (low.startswith("nb") or "ninebot" in low or "segway" in low
                or "es4" in low)

    # -------------------------------------------------------------- helpers
    def _status(self, text, color):
        self.status_text = text
        self.status_color = color

    def _dbg_push(self, data):
        for i in range(6, 0, -1):
            self.dbg[i] = self.dbg[i - 1]
        self.dbg[0] = _hex(data, 16)

    def _fail(self, text):
        self._status(text, 0xF800)
        self._close()

    def _close(self):
        self.connected = False
        self.auth_state = AUTH_IDLE
        self.press_power = False
        self.tx_handle = None
        self.rx_handle = None
        self.tx_props = 0
        self.sub_handle = None
        self.sub_status = None
        self.txq = []
        self.tx_busy = False
        self.write_status = None
        self.last_rx = 0
        self._rx = bytearray()
        self.rxbuf = bytearray()
        self.rx_seen = 0
        self.data.reset()
        # A dropped link invalidates both the SHFW cache and the write unlock:
        # the rider has to unlock editing again after reconnecting.
        self.shfw_reset()
        if self.conn is not None:
            try:
                self.ble.gap_disconnect(self.conn)
            except Exception:
                pass
        self.conn = None
        self.state = IDLE
        self.retry_at = time.ticks_add(time.ticks_ms(), 1200)

    # ------------------------------------------------------------------ scan
    def _start_scan(self):
        self.scan_results = {}
        self.scan_done = False
        self._status("scan...", 0xFFE0)
        try:
            self.ble.gap_scan(5000, 30000, 30000, True)
        except Exception as exc:
            print("scan failed:", exc)
            self.retry_at = time.ticks_add(time.ticks_ms(), 2000)
            self.state = IDLE
            return
        self.state = SCAN

    def _scan_finished(self):
        best = None
        for name, info in self.scan_results.items():
            if best is None or info[0] > best[1][0]:
                best = (name, info)
        self.scan_results = {}
        if best is None:
            self._status("not found", 0xF800)
            self.state = IDLE
            self.retry_at = time.ticks_add(time.ticks_ms(), 1500)
            return
        name, (rssi, addr_type, addr) = best
        self.dev_name = name
        self._status("connect " + name, 0xFFE0)
        try:
            self.ble.gap_connect(addr_type, addr)
        except Exception as exc:
            print("connect failed:", exc)
            self._status("conn fail", 0xF800)
            self.state = IDLE
            self.retry_at = time.ticks_add(time.ticks_ms(), 1500)
            return
        self.state = CONNECT
        self.deadline = time.ticks_add(time.ticks_ms(), 9000)

    # --------------------------------------------------------------- packets
    def _write_packet(self, packet):
        for i in range(0, len(packet), 20):
            self.txq.append(packet[i:i + 20])

    def send_packet(self, dst, cmd, arg, payload=b""):
        if self.conn is None or self.tx_handle is None:
            return False
        plain = bytes((0x5A, 0xA5, len(payload), config.ADDR_APP, dst, cmd, arg)) + payload
        enc = self.crypto.encrypt_packet(plain)
        self._write_packet(enc)
        return True

    def send_read(self, dev, reg, n):
        return self.send_packet(dev, 0x01, reg, bytes((n,)))

    def _pump(self, now):
        if self.tx_busy:
            if self.write_status is not None:
                status = self.write_status
                self.write_status = None
                self.tx_busy = False
                if status != 0:
                    self.tx_failures += 1
                    self.txq = []
            elif time.ticks_diff(now, self.tx_busy_at) > 800:
                self.tx_busy = False
                self.write_status = None
                self.txq = []
            return
        if not self.txq or time.ticks_diff(now, self.next_tx) < 0:
            return
        chunk = self.txq.pop(0)
        mode = 1 if (self.tx_props & 0x08) else 0
        self.write_status = None
        try:
            self.ble.gattc_write(self.conn, self.tx_handle, chunk, mode)
            self.tx_count += 1
            if mode == 0:
                # Write Without Response: no completion event is generated.
                self.next_tx = time.ticks_add(now, 20)
            else:
                # Write With Response: wait for _IRQ_GATTC_WRITE_DONE.
                self.tx_busy = True
                self.tx_busy_at = now
        except Exception as exc:
            print("write failed:", exc)
            self.tx_failures += 1
            self.txq = []
            self.next_tx = time.ticks_add(now, 50)

    # ------------------------------------------------------------------ auth
    def _send_init(self):
        self.auth_state = AUTH_WAIT_INIT
        self.auth_last = time.ticks_ms()
        self.auth_attempts = 0
        self.send_packet(0x21, 0x5B, 0)

    def _send_ping(self):
        self.auth_last = time.ticks_ms()
        self.auth_attempts = 0
        self.send_packet(0x21, 0x5C, 0, self.crypto.random_app)

    def _send_pair(self):
        self.auth_last = time.ticks_ms()
        self.auth_attempts = 0
        self.send_packet(0x21, 0x5D, 0, self.crypto.serial)

    def _start_auth(self):
        self.crypto.reset(self.dev_name)
        self.auth_state = AUTH_WAIT_INIT
        self.auth_attempts = 0
        self.press_power = False
        self.data.reset()
        self.state = AUTH
        self.last_rx = time.ticks_ms()
        self._status("AUTH INIT", 0x07FF)
        self._send_init()

    def _auth_tick(self, now):
        if time.ticks_diff(now, self.auth_last) < 0:
            return
        if self.auth_state == AUTH_WAIT_INIT:
            if time.ticks_diff(now, self.auth_last) > 900:
                self.auth_attempts += 1
                if self.auth_attempts > 5:
                    self._fail("conn fail")
                    return
                self.send_packet(0x21, 0x5B, 0)
                self.auth_last = now
        elif self.auth_state == AUTH_WAIT_PING:
            if time.ticks_diff(now, self.auth_last) > 1200:
                # Keep asking while the link is alive; the rider may need
                # time to press the scooter's power button.
                self.auth_attempts += 1
                self.send_packet(0x21, 0x5C, 0, self.crypto.random_app)
                self.auth_last = now
        elif self.auth_state == AUTH_WAIT_PAIR:
            if time.ticks_diff(now, self.auth_last) > 1200:
                self.auth_attempts += 1
                self.send_packet(0x21, 0x5D, 0, self.crypto.serial)
                self.auth_last = now

    # ---------------------------------------------------------------- frames
    def feed(self, data):
        # Notifications can split one frame or contain several frames.  Never
        # discard a partial frame just because the next chunk starts with the
        # same two bytes as the header: that can happen inside binary payload.
        self.rx_seen = time.ticks_ms()
        if len(self.rxbuf) + len(data) > 512:
            self.rxbuf = bytearray()
            self.checksum_errors += 1
            return
        self.rxbuf.extend(data)
        while len(self.rxbuf) >= 2:
            if self.rxbuf[0] != 0x5A or self.rxbuf[1] != 0xA5:
                # Resynchronise to the next possible header instead of
                # throwing away a good frame sitting behind some noise.
                pos = 1
                while pos + 1 < len(self.rxbuf):
                    if self.rxbuf[pos] == 0x5A and self.rxbuf[pos + 1] == 0xA5:
                        break
                    pos += 1
                if pos + 1 >= len(self.rxbuf):
                    self.rxbuf = bytearray()
                    self.checksum_errors += 1
                    return
                del self.rxbuf[:pos]
                self.checksum_errors += 1
                continue
            if len(self.rxbuf) < 3:
                return
            expected = self.rxbuf[2] + 13
            if expected > 512:
                del self.rxbuf[:1]
                self.checksum_errors += 1
                continue
            if len(self.rxbuf) < expected:
                return
            frame = bytes(self.rxbuf[:expected])
            del self.rxbuf[:expected]
            plain = self.crypto.decrypt_packet(frame)
            if plain is None:
                self.checksum_errors += 1
            else:
                self.frame_count += 1
                self._dbg_push(frame)
                self._handle_plain(plain)

    def _handle_plain(self, plain):
        if len(plain) < 7:
            return
        src, dst, cmd, arg = plain[3], plain[4], plain[5], plain[6]
        length = plain[2]

        if (src == 0x21 and dst == config.ADDR_APP and cmd == 0x5B
                and self.auth_state == AUTH_WAIT_INIT):
            self.crypto.random_app = os.urandom(16)
            self.auth_state = AUTH_WAIT_PING
            self.press_power = True
            self._status("PRESS POWER", 0xFFE0)
            self._send_ping()
            return
        if (src == 0x21 and dst == config.ADDR_APP and cmd == 0x5C
                and self.auth_state == AUTH_WAIT_PING):
            self.auth_last = time.ticks_ms()
            if arg == 0x01:
                self.press_power = False
                self.auth_state = AUTH_WAIT_PAIR
                self._status("PAIRING", 0x07FF)
                self._send_pair()
            else:
                self.press_power = True
                self._status("PRESS POWER", 0xFFE0)
            return
        if (src == 0x21 and dst == config.ADDR_APP and cmd == 0x5D
                and self.auth_state == AUTH_WAIT_PAIR):
            self.auth_last = time.ticks_ms()
            if arg == 0x01:
                self.auth_state = AUTH_READY
                self.state = READY
                self.press_power = False
                self.last_rx = time.ticks_ms()
                self.ready_at = self.last_rx
                self.last_fast = self.last_rx
                self.last_poll = self.last_rx
                self._status("LIVE " + self.dev_name, 0x07E0)
            else:
                self.send_packet(0x21, 0x5D, 0, self.crypto.serial)
            return

        # SHFW config read/version replies.  They use command 0x34/0x31 and
        # 0x39 instead of the telemetry command 0x04, so correlate them here
        # before the normal parser.
        if (self.shfw_rx_pending and src == config.ADDR_ESC
                and dst == config.ADDR_APP and self.auth_state == AUTH_READY
                and len(plain) >= 7 + length):
            if ((cmd == 0x34 or cmd == 0x31) and arg == self.shfw_rx_reg
                    and length >= self.shfw_rx_len):
                self.shfw_rx_data[:self.shfw_rx_len] = plain[7:7 + self.shfw_rx_len]
                self.shfw_rx_ok = True
                self.shfw_rx_pending = False
                return
        if (self.shfw_ver_pending and src == config.ADDR_ESC
                and dst == config.ADDR_APP and self.auth_state == AUTH_READY
                and len(plain) >= 7 + length and length):
            if cmd == 0x39 or arg == 0x39:
                n = length if length < _VER_MAX else _VER_MAX
                self.shfw_ver_data[:n] = plain[7:7 + n]
                self.shfw_ver_len = n
                self.shfw_ver_ok = True
                self.shfw_ver_pending = False
                return

        if (dst != config.ADDR_APP or cmd != 0x04
                or self.auth_state != AUTH_READY or len(plain) < 7 + length):
            return
        payload = plain[7:7 + length]
        d = self.data
        if src == config.ADDR_ESC and arg == 0x26 and length >= 2:
            d.speed = abs(_s16(payload) * config.SPEED_SCALE)
            d.valid |= 1 << SPEED
            return
        if src == config.ADDR_BMS and arg == 0x33 and length >= 2:
            d.amp = _s16(payload) * config.BMS_CUR_SCALE
            d.valid |= 1 << AMP
            if d.has(SPEED) and d.speed > 3.0 and d.amp <= -config.BRAKE_REGEN_CURRENT_A:
                d.brake_until = time.ticks_add(time.ticks_ms(), config.BRAKE_HOLD_MS)
            return

        for dev, reg, size, ident in POLL_LIST:
            if dev != src or reg != arg or length < size:
                continue
            if ident == TRIP:
                d.trip_km = _u16(payload) * config.TRIP_SCALE
            elif ident == TOTAL_LO:
                d.total_low = _u16(payload)
                d.total_km = (((d.total_high << 16) | d.total_low)
                              * config.TOTAL_SCALE)
            elif ident == TOTAL_HI:
                d.total_high = _u16(payload)
                d.total_km = (((d.total_high << 16) | d.total_low)
                              * config.TOTAL_SCALE)
            elif ident == ETEMP:
                d.esc_temp = _s16(payload) * config.ETEMP_SCALE
            elif ident == SOC:
                v = _u16(payload)
                d.soc = 0 if v < 0 else 100 if v > 100 else v
            elif ident == VOLT:
                d.volt = _u16(payload) * config.BMS_VOLT_SCALE
            elif ident == BTEMP:
                d.batt_temp = (payload[0] + payload[1]) // 2 - 20
            elif ident == SERIAL_NO:
                try:
                    d.serial = payload[:14].decode()
                except Exception:
                    d.serial = ""
            elif ident == FW:
                d.fw = _u16(payload)
            elif ident == RIDE_MODE:
                d.ride_mode = _u16(payload)
            d.valid |= 1 << ident

    # ------------------------------------------------------------------ poll
    def poll(self, now):
        if self._rx:
            chunk = bytes(self._rx)
            self._rx = bytearray()
            self.feed(chunk)

        # A bogus length byte can otherwise leave the parser waiting forever.
        if self.rxbuf and time.ticks_diff(now, self.rx_seen) > 500:
            pos = 1
            while pos + 1 < len(self.rxbuf):
                if self.rxbuf[pos] == 0x5A and self.rxbuf[pos + 1] == 0xA5:
                    break
                pos += 1
            if pos + 1 >= len(self.rxbuf):
                self.rxbuf = bytearray()
            else:
                del self.rxbuf[:pos]
            self.rx_seen = now
            self.checksum_errors += 1

        # disconnect event
        if self._disconnected:
            self._disconnected = False
            if self.state in (CONNECT, DISCOVER, AUTH, READY):
                self._close()
                return

        # scan result ready
        if self.state == SCAN:
            if self.scan_done:
                self.scan_done = False
                self._scan_finished()
            return

        if self.state == CONNECT:
            if self._connected_evt:
                self._connected_evt = False
                self.state = DISCOVER
                self.found_svc = False
                self._svc_ready = False
                self._char_ready = False
                self._chars = {}
                self.tx_handle = None
                self.rx_handle = None
                self.tx_props = 0
                try:
                    self.ble.gattc_discover_services(self.conn)
                except Exception as exc:
                    print("discover svc:", exc)
                    self._fail("no NUS")
            elif time.ticks_diff(now, self.deadline) > 0:
                self._fail("conn fail")
            return

        if self.state == DISCOVER:
            if self._svc_ready:
                self._svc_ready = False
                if not self.found_svc:
                    self._fail("no NUS")
                    return
                self._char_ready = False
                try:
                    self.ble.gattc_discover_characteristics(
                        self.conn, self.svc_start, self.svc_end)
                except Exception as exc:
                    print("discover chr:", exc)
                    self._fail("chr fail")
                return
            if self._char_ready:
                self._char_ready = False
                if self.tx_handle is None or self.rx_handle is None:
                    self._fail("chr fail")
                    return
                # MicroPython has no gattc_set_characteristic_notify().
                # Subscribe to the NUS RX characteristic by writing 0x0001 to
                # its Client Characteristic Configuration Descriptor.  The
                # CCCD always follows the characteristic value handle.
                self.sub_handle = self.rx_handle + 1
                self.sub_status = None
                try:
                    self.ble.gattc_write(self.conn, self.sub_handle,
                                         b"\x01\x00", 1)
                except Exception as exc:
                    print("subscribe:", exc)
                    self.sub_handle = None
                    self._fail("chr fail")
                    return
                self._status("SUBSCRIBE", 0x07FF)
                return
            if self.sub_handle is not None:
                if self.sub_status is None:
                    if time.ticks_diff(now, self.deadline) > 0:
                        self._fail("chr fail")
                    return
                status = self.sub_status
                self.sub_handle = None
                self.sub_status = None
                if status:
                    self._fail("chr fail")
                    return
                self.connected = True
                self._start_auth()
                return
            if time.ticks_diff(now, self.deadline) > 0:
                self._fail("conn fail")
            return

        if self.state == AUTH:
            self._auth_tick(now)
            self._pump(now)
            if self.auth_state == AUTH_READY:
                pass
            elif time.ticks_diff(now, self.last_rx) > 60000 and self.last_rx:
                self._fail("link lost")
            return

        if self.state == READY:
            self._pump(now)
            if time.ticks_diff(now, self.last_rx) > config.LINK_TIMEOUT:
                self._fail("link lost")
                return
            if not self.txq and not self.tx_busy:
                if time.ticks_diff(now, self.last_fast) >= config.FAST_TELEMETRY_POLL_MS:
                    self.last_fast = now
                    if self.poll_brake:
                        self.send_read(config.ADDR_BMS, 0x33, 2)
                    else:
                        self.send_read(config.ADDR_ESC, 0x26, 2)
                    self.poll_brake = not self.poll_brake
                if time.ticks_diff(now, self.last_poll) >= config.POLL_INTERVAL:
                    self.last_poll = now
                    dev, reg, size, ident = POLL_LIST[self.poll_idx]
                    self.poll_idx = (self.poll_idx + 1) % len(POLL_LIST)
                    slow_done = ((ident == SERIAL_NO and self.data.serial)
                                 or (ident == FW and self.data.fw))
                    if not slow_done:
                        self.send_read(dev, reg, size)
            return

        # IDLE
        if time.ticks_diff(now, self.retry_at) >= 0:
            self._start_scan()

    # ------------------------------------------------------------------ misc
    def disconnect(self):
        self._status("NO LINK", 0xF800)
        self._close()

    def send_shfw_read(self, reg, n):
        return self.send_packet(config.ADDR_ESC, 0x31, reg, bytes((n,)))

    def send_shfw_write(self, reg, data):
        return self.send_packet(config.ADDR_ESC, 0x32, reg, bytes(data))

    def send_shfw_version(self):
        return self.send_packet(config.ADDR_ESC, 0x39, 0)

    # ------------------------------------------------------------- SHFW
    def _shfw_alloc(self):
        """Allocate the SHFW caches only when the menu/transport needs them."""
        if self.shfw_word is not None:
            return
        # Build everything in locals first.  If one allocation raises
        # MemoryError, the object stays clean and a later retry can work.
        word = [0] * 256
        have = bytearray(256)
        rx_data = bytearray(_MAX_XFER)
        ver_data = bytearray(_VER_MAX)
        dump = bytearray(_DUMP_BYTES)
        prof_buf = bytearray(_PROFILE_BYTES)
        prof_ok = bytearray(_PROFILE_WORDS)
        prof_cur = bytearray(_PROFILE_BYTES)
        prof_cur_ok = bytearray(_PROFILE_WORDS)
        self.shfw_word = word
        self.shfw_have = have
        self.shfw_rx_data = rx_data
        self.shfw_ver_data = ver_data
        self.shfw_dump = dump
        self.shfw_prof_buf = prof_buf
        self.shfw_prof_ok = prof_ok
        self.shfw_prof_cur = prof_cur
        self.shfw_prof_cur_ok = prof_cur_ok

    def _shfw_clear_cache(self):
        if self.shfw_word is None:
            return
        for i in range(256):
            self.shfw_word[i] = 0
            self.shfw_have[i] = 0

    def shfw_reset(self, lock=True):
        """Forget cached ESC data and, by default, lock editing again."""
        if lock:
            self.shfw_enabled = False
            self.shfw_force = False
        else:
            self._shfw_alloc()
        self.shfw_detected = -1
        self.shfw_profile = 0
        self.shfw_forced = False
        self.shfw_diag = ""
        self.shfw_ver = b""
        self.shfw_ver_len = 0
        self.shfw_profile_got = 0
        self._shfw_clear_cache()
        self.shfw_rx_pending = False
        self.shfw_rx_ok = False
        self.shfw_ver_pending = False
        self.shfw_ver_ok = False
        self.shfw_saved_ver = b""
        self.shfw_last_fail_count = 0
        self.shfw_last_fail_reg = 0

    def shfw_live(self):
        return self.is_live()

    def shfw_read_version(self):
        self._shfw_alloc()
        return self._shfw_read_version()

    @staticmethod
    def shfw_hex(data, limit=8):
        n = len(data) if len(data) < limit else limit
        return "".join("%02X" % data[i] for i in range(n))

    def _shfw_service(self, now=None):
        """Run the BLE transport while an SHFW operation waits for a reply."""
        now = time.ticks_ms() if now is None else now
        if self._rx:
            chunk = bytes(self._rx)
            self._rx = bytearray()
            self.feed(chunk)
        self._pump(now)

    def _shfw_wait_idle(self, timeout=500):
        deadline = time.ticks_add(time.ticks_ms(), timeout)
        for _ in range(timeout // 2 + 4):
            if not self.txq and not self.tx_busy:
                return True
            if self.conn is None or self.auth_state != AUTH_READY:
                return False
            self._shfw_service()
            if not self.txq and not self.tx_busy:
                return True
            if time.ticks_diff(time.ticks_ms(), deadline) >= 0:
                return False
            time.sleep_ms(2)
        return False

    def _shfw_read_block(self, reg, n, timeout=450, attempts=2):
        self._shfw_alloc()
        if not self.is_live() or n < 1 or n > _MAX_XFER:
            return None
        for _ in range(attempts):
            if not self._shfw_wait_idle():
                return None
            self.shfw_rx_reg = reg
            self.shfw_rx_len = n
            self.shfw_rx_ok = False
            self.shfw_rx_pending = True
            if not self.send_shfw_read(reg, n):
                self.shfw_rx_pending = False
                return None
            deadline = time.ticks_add(time.ticks_ms(), timeout)
            for _ in range(timeout // 2 + 4):
                self._shfw_service()
                if not self.shfw_rx_pending:
                    break
                if time.ticks_diff(time.ticks_ms(), deadline) >= 0:
                    break
                time.sleep_ms(2)
            self.shfw_rx_pending = False
            if self.shfw_rx_ok:
                return bytes(self.shfw_rx_data[:n])
            if not self.is_live():
                return None
        return None

    def _shfw_read_version(self):
        self._shfw_alloc()
        if not self.is_live():
            return False
        for _ in range(2):
            if not self._shfw_wait_idle():
                break
            self.shfw_ver_ok = False
            self.shfw_ver_pending = True
            if not self.send_shfw_version():
                self.shfw_ver_pending = False
                break
            deadline = time.ticks_add(time.ticks_ms(), 600)
            for _ in range(304):
                self._shfw_service()
                if not self.shfw_ver_pending:
                    break
                if time.ticks_diff(time.ticks_ms(), deadline) >= 0:
                    break
                time.sleep_ms(2)
            self.shfw_ver_pending = False
            if self.shfw_ver_ok:
                self.shfw_ver = bytes(self.shfw_ver_data[:self.shfw_ver_len])
                return bool(self.shfw_ver)
            if not self.is_live():
                break
        self.shfw_ver = b""
        self.shfw_ver_len = 0
        return False

    def _shfw_write_block(self, reg, data):
        if not self.is_live() or not data or len(data) > _MAX_XFER:
            return False
        if not self._shfw_wait_idle():
            return False
        failures = self.tx_failures
        if not self.send_shfw_write(reg, data):
            return False
        if not self._shfw_wait_idle(700):
            return False
        if self.tx_failures != failures:
            return False
        # The ESC applies the write asynchronously; a short settle keeps the
        # verification read from racing it.
        time.sleep_ms(150)
        return True

    def _shfw_store_word(self, reg, data, length):
        self._shfw_alloc()
        word = shfw.word_from_bytes(data, length)
        if length >= 2:
            self.shfw_word[reg] = word
            self.shfw_have[reg] = 2
        else:
            high = (self.shfw_word[reg] & 0xFF00
                    if self.shfw_have[reg] >= 2 else 0)
            self.shfw_word[reg] = high | (word & 0xFF)
            if not self.shfw_have[reg]:
                self.shfw_have[reg] = 1
        return word

    def shfw_read_reg(self, reg, length):
        _load_shfw()
        self._shfw_alloc()
        data = self._shfw_read_block(reg, length, 450)
        if data is None:
            self.shfw_have[reg] = 0
            return None
        return self._shfw_store_word(reg, data, length)

    def shfw_ensure(self, item):
        _load_shfw()
        self._shfw_alloc()
        if self.shfw_have[item[1]] >= item[2]:
            return True
        return self.shfw_read_reg(item[1], item[2]) is not None

    def shfw_cached(self, item):
        _load_shfw()
        self._shfw_alloc()
        if self.shfw_have[item[1]] < item[2]:
            return None
        return shfw.field(item, self.shfw_word[item[1]])

    def shfw_prefetch(self, items):
        """Read the unique registers displayed on one page, coalesced."""
        _load_shfw()
        self._shfw_alloc()
        need = {}
        for index in items:
            item = shfw.ITEMS[index]
            reg, length = item[1], item[2]
            if self.shfw_have[reg] < length and need.get(reg, 0) < length:
                need[reg] = length
        for reg, length in need.items():
            if self.shfw_read_reg(reg, length) is None:
                return False
        return True

    def shfw_detect(self):
        self._shfw_alloc()
        self.shfw_detected = 0
        self.shfw_profile = 0
        self.shfw_forced = False
        if not self.is_live():
            self.shfw_diag = ""
            return False
        ver_ok = self._shfw_read_version()
        word = self.shfw_read_reg(0xB2, 2)
        b2_ok = word is not None
        profile = (word & 0xFF) if b2_ok else 0
        valid = b2_ok and 1 <= profile <= 3
        self.shfw_diag = "ver:%s B2:%s" % (
            self.shfw_hex(self.shfw_ver) if ver_ok else "-",
            ("%04X" % word) if b2_ok else "-")
        if valid:
            self.shfw_profile = profile
        if ver_ok or valid:
            self.shfw_detected = 1
        elif self.shfw_force:
            self.shfw_detected = 1
            self.shfw_forced = True
        return self.shfw_detected == 1

    def _shfw_moving(self):
        # Unknown speed is treated as unsafe, exactly like a moving scooter.
        return not self.data.has(SPEED) or self.data.speed > 1.0

    def shfw_write_item(self, item, value):
        _load_shfw()
        self._shfw_alloc()
        if not self.shfw_enabled:
            return SHFW_LOCKED
        if not self.is_live():
            return SHFW_NO_LINK
        if self._shfw_moving():
            return SHFW_MOVING
        if self.shfw_detected != 1 and not self.shfw_detect():
            return SHFW_NOT_DETECTED
        value = shfw.clamp(item, value)
        cur = self.shfw_read_reg(item[1], item[2])
        if cur is None:
            return SHFW_READ_FAIL
        nxt = shfw.set_field(item, cur, value)
        if nxt == cur:
            return SHFW_OK
        if not self._shfw_write_block(item[1], shfw.bytes_from_word(nxt, item[2])):
            self.shfw_have[item[1]] = 0
            return SHFW_VERIFY_FAIL
        back = self.shfw_read_reg(item[1], item[2])
        if back is None:
            self.shfw_have[item[1]] = 0
            return SHFW_VERIFY_FAIL
        return SHFW_OK if shfw.field(item, back) == value else SHFW_VERIFY_FAIL

    def shfw_dump_read(self):
        _load_shfw()
        self._shfw_alloc()
        if not self.is_live():
            return False
        for reg, n, off in shfw.CHUNKS:
            data = self._shfw_read_block(reg, n, 700)
            if data is None:
                return False
            self.shfw_dump[off:off + n] = data
        return True

    def shfw_backup(self, slot):
        _load_shfw()
        _load_store()
        if not 0 <= slot < shfwstore.DUMP_SLOTS:
            return SHFW_RESERVED
        if not self.is_live():
            return SHFW_NO_LINK
        if self.shfw_detected != 1 and not self.shfw_detect():
            return SHFW_NOT_DETECTED
        if not self._shfw_read_version():
            return SHFW_NO_VERSION
        if not self.shfw_dump_read():
            return SHFW_READ_FAIL
        if not shfwstore.save_dump(slot, self.shfw_ver, self.shfw_dump):
            return SHFW_SAVE_FAIL
        return SHFW_OK

    def shfw_restore(self, slot):
        _load_shfw()
        _load_store()
        if not 0 <= slot < shfwstore.DUMP_SLOTS:
            return SHFW_BAD_SLOT
        if not self.shfw_enabled:
            return SHFW_LOCKED
        if not self.is_live():
            return SHFW_NO_LINK
        if self._shfw_moving():
            return SHFW_MOVING
        if self.shfw_detected != 1 and not self.shfw_detect():
            return SHFW_NOT_DETECTED
        if not self._shfw_read_version():
            return SHFW_NO_VERSION
        state, rec = shfwstore.load_dump(slot)
        if state == 0:
            return SHFW_EMPTY
        if state < 0:
            return SHFW_BAD_SLOT
        self.shfw_saved_ver = rec["ver"]
        if rec["ver"] != self.shfw_ver:
            return SHFW_VER_MISMATCH
        if not self.shfw_dump_read():
            return SHFW_READ_FAIL
        if not shfwstore.save_dump(shfwstore.UNDO_SLOT,
                                   self.shfw_ver, self.shfw_dump):
            return SHFW_SAVE_FAIL
        self.shfw_last_fail_count = 0
        self.shfw_last_fail_reg = 0
        for reg, n, off in shfw.CHUNKS:
            data = rec["data"][off:off + n]
            good = (self._shfw_write_block(reg, data)
                    and self._shfw_read_block(reg, n, 700) == data)
            if not good:
                self.shfw_last_fail_count += 1
                if not self.shfw_last_fail_reg:
                    self.shfw_last_fail_reg = reg
        self._shfw_clear_cache()
        return SHFW_WRITE_FAIL if self.shfw_last_fail_count else SHFW_OK

    def shfw_dump_slots(self):
        _load_store()
        return shfwstore.dump_slots()

    # --------------------------------------------------------- SHFW profiles
    def _shfw_read_words(self, reg, words, out, ok, out_word=0):
        data = self._shfw_read_block(reg, words * 2, 700)
        if data is not None:
            start = out_word * 2
            out[start:start + words * 2] = data
            ok[out_word:out_word + words] = b"\x01" * words
            return words
        if words > 8:
            for off in range(0, words, 8):
                n = 8 if words - off > 8 else words - off
                self._shfw_read_words(reg + off, n, out, ok, out_word + off)
        elif words > 1:
            for off in range(words):
                self._shfw_read_words(reg + off, 1, out, ok, out_word + off)
        else:
            start = out_word * 2
            out[start] = 0
            out[start + 1] = 0
            ok[out_word] = 0
        return 0

    def shfw_read_profile(self, profile, out=None, ok=None):
        _load_shfw()
        self._shfw_alloc()
        if not 1 <= profile <= 3 or not self.is_live():
            return 0
        out = self.shfw_prof_buf if out is None else out
        ok = self.shfw_prof_ok if ok is None else ok
        out[:] = b"\x00" * shfw.PROFILE_BYTES
        ok[:] = b"\x00" * shfw.PROFILE_WORDS
        start = shfw.PROFILE_FROM[profile - 1]
        left = shfw.PROFILE_WORDS
        word = 0
        while left:
            n = 40 if left > 40 else left
            self._shfw_read_words(start + word, n, out, ok, word)
            word += n
            left -= n
        return sum(ok)

    def shfw_profile_backup(self, slot):
        _load_shfw()
        self._shfw_alloc()
        _load_store()
        if not 0 <= slot < 3:
            return SHFW_RESERVED
        if not self.is_live():
            return SHFW_NO_LINK
        if self.shfw_detected != 1 and not self.shfw_detect():
            return SHFW_NOT_DETECTED
        if not self._shfw_read_version():
            return SHFW_NO_VERSION
        got = self.shfw_read_profile(slot + 1)
        self.shfw_profile_got = got
        if not got:
            return SHFW_READ_FAIL
        if not shfwstore.save_profile(slot, slot + 1, self.shfw_ver,
                                      self.shfw_prof_buf, self.shfw_prof_ok):
            return SHFW_SAVE_FAIL
        return SHFW_OK

    def shfw_profile_restore(self, slot):
        _load_shfw()
        self._shfw_alloc()
        _load_store()
        if not 0 <= slot < shfwstore.PROFILE_SLOTS:
            return SHFW_BAD_SLOT
        if not self.shfw_enabled:
            return SHFW_LOCKED
        if not self.is_live():
            return SHFW_NO_LINK
        if self._shfw_moving():
            return SHFW_MOVING
        if self.shfw_detected != 1 and not self.shfw_detect():
            return SHFW_NOT_DETECTED
        if not self._shfw_read_version():
            return SHFW_NO_VERSION
        state, rec = shfwstore.load_profile(slot)
        if state == 0:
            return SHFW_EMPTY
        if state < 0:
            return SHFW_BAD_SLOT
        self.shfw_saved_ver = rec["ver"]
        if rec["ver"] != self.shfw_ver:
            return SHFW_VER_MISMATCH
        profile = rec["profile"]
        if not self.shfw_read_profile(profile, self.shfw_prof_cur,
                                      self.shfw_prof_cur_ok):
            return SHFW_READ_FAIL
        need = bytearray(shfw.PROFILE_WORDS)
        count = 0
        for i in range(shfw.PROFILE_WORDS):
            if (rec["ok"][i] and self.shfw_prof_cur_ok[i]
                    and rec["data"][i * 2:i * 2 + 2]
                    != self.shfw_prof_cur[i * 2:i * 2 + 2]):
                need[i] = 1
                count += 1
        if not count:
            return SHFW_NOCHANGE
        if slot != 3 and not shfwstore.save_profile(
                shfwstore.UNDO_SLOT, profile, self.shfw_ver,
                self.shfw_prof_cur, self.shfw_prof_cur_ok):
            return SHFW_SAVE_FAIL
        self.shfw_last_fail_count = 0
        self.shfw_last_fail_reg = 0
        word = 0
        while word < shfw.PROFILE_WORDS:
            if not need[word]:
                word += 1
                continue
            end = word
            while (end < shfw.PROFILE_WORDS and need[end]
                   and end - word < 40):
                end += 1
            reg = shfw.PROFILE_FROM[profile - 1] + word
            data = rec["data"][word * 2:end * 2]
            good = (self._shfw_write_block(reg, data)
                    and self._shfw_read_block(reg, len(data), 700) == data)
            if not good:
                self.shfw_last_fail_count += 1
                if not self.shfw_last_fail_reg:
                    self.shfw_last_fail_reg = reg
            word = end
        self._shfw_clear_cache()
        return SHFW_WRITE_FAIL if self.shfw_last_fail_count else SHFW_OK

    def shfw_profile_switch(self, profile):
        _load_shfw()
        self._shfw_alloc()
        if not 1 <= profile <= 3:
            return SHFW_READ_FAIL
        for item in shfw.ITEMS:
            if item[1] == 0xB2:
                result = self.shfw_write_item(item, profile)
                if result == SHFW_OK:
                    self.shfw_profile = profile
                    self._shfw_clear_cache()
                return result
        return SHFW_READ_FAIL

    def shfw_active_profile(self):
        if not self.is_live():
            self.shfw_profile = 0
            return 0
        word = self.shfw_read_reg(0xB2, 2)
        if word is None:
            return 0
        profile = word & 0xFF
        if 1 <= profile <= 3:
            self.shfw_profile = profile
            return profile
        return 0

    def shfw_profile_slots(self):
        _load_store()
        return shfwstore.profile_slots()

    def is_live(self):
        return self.auth_state == AUTH_READY and self.state == READY
