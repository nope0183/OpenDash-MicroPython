"""Touch UI for the MicroPython port.

Screens mirror the original OpenDash: dashboard with speedometer and four
metric cards, device info, BLE debug, connection screen, settings, ARGB
strip editor, OTA and touch calibration.
"""
import gc
import math
import time

try:
    from . import colors as C
    from . import config
    from .display import Canvas
    from .touch import CAL_POINTS
except ImportError:
    from opendash import colors as C
    from opendash import config
    from opendash.display import Canvas
    from opendash.touch import CAL_POINTS

# The SHFW table and its screens live in shfwui.py and are imported on
# demand, keeping roughly 26 KB of bytecode off the boot heap.
_shfw_ui_mod = None
_shfw_ui_error = ""

SCR_MAIN = 0
SCR_SET = 1
SCR_APPEAR = 2
SCR_DISPLAY = 3
SCR_GAUGE = 4
SCR_WIDGETS = 5
SCR_LED = 6
SCR_LED_COLOR = 7
SCR_LED_EFFECT = 8
SCR_OTA = 9
SCR_PICK = 10
SCR_CAL = 11
SCR_SHFW = 12
SCR_SHFW_LIST = 13
SCR_SHFW_EDIT = 14
SCR_SHFW_BAK = 15
SCR_SHFW_PROF = 16

GCX, GCY = 120, 118
GR_O, GR_I = 82, 69
GAUGE_SEGS = 40
CAL_M = 20

CX = (8, 124, 8, 124)
CY = (207, 207, 263, 263)


def hit(x, y, rx, ry, rw, rh):
    return rx <= x < rx + rw and ry <= y < ry + rh


def km_u(v, units):
    return v * 0.621371 if units else v


class UI:
    def __init__(self, app):
        self.app = app
        self.cfg = app.cfg
        self.d = app.d
        self.nb = app.nb
        self.scratch = Canvas(240, 64)
        self.sv_canvas = None
        self.cache = {}
        self.scr = SCR_MAIN
        self.page = 0
        self.need_static = True
        self.settings_dirty = True
        self.was_live = None
        self.gauge_lit = 0
        self.bar_cache = [None, None, None, None]
        self.pick_slot = 0
        self.pick_return = SCR_WIDGETS
        self.cal_step = 0
        self.cal_from_boot = False
        self.cal_fail = False
        self.cal_raw = []
        self.led_color_seg = 0
        self._led_color_orig = None
        self._sv_last_hue = -1
        self._sv_marker = None
        self._last_sv_draw = 0
        self._last_conn = 0
        self._cal_key = None
        self._drag = -1
        self.ota_toggle_rect = (8, 54, 224, 44)

        self.shfw_grp = 0
        self.shfw_page = 0
        self.shfw_list = ()
        self.shfw_sel = -1
        self.shfw_edit = 0
        self.shfw_orig = 0
        self.shfw_edit_ready = False
        self.shfw_msg = ""
        self.shfw_msg_col = C.COL_DIM
        self.shfw_bak_sel = 0
        self.shfw_bak_slots = ()
        self.shfw_prof_sel = 0
        self.shfw_prof_slots = ()
        self.shfw_prof_active = 0

    # ------------------------------------------------------------- helpers
    def t(self, en, ru):
        return ru if self.cfg["lang"] else en

    def metric_name(self, i):
        i %= config.M_COUNT
        return (config.METRIC_NAME_RU if self.cfg["lang"] else config.METRIC_NAME)[i]

    def status_text(self, s):
        if not self.cfg["lang"]:
            return s
        table = {
            "AUTH INIT": "Авторизация", "PRESS POWER": "Нажмите кнопку",
            "PAIRING": "Сопряжение", "NO LINK": "Нет связи",
            "scan...": "Поиск...", "not found": "Не найден",
            "conn fail": "Сбой подключения", "no NUS": "Нет NUS",
            "chr fail": "Ошибка BLE", "link lost": "Связь потеряна",
            "READY": "Готово", "SUBSCRIBE": "Подписка BLE",
        }
        if s in table:
            return table[s]
        if s.startswith("LIVE "):
            return "На связи " + s[5:]
        if s.startswith("connect "):
            return "Подключение " + s[8:]
        return s

    def status_color(self):
        s = self.nb.status_text
        if s.startswith("LIVE"):
            return C.COL_GOOD
        if s.startswith("connect ") or s == "PRESS POWER" or s == "scan...":
            return C.COL_WARN
        if s in ("AUTH INIT", "PAIRING", "SUBSCRIBE"):
            return C.COL_ACCENT
        if s in ("NO LINK", "link lost", "not found", "conn fail", "no NUS", "chr fail"):
            return C.COL_BAD
        return C.COL_WARN

    def page_on(self, p):
        return (p == 0 or (p == 1 and self.cfg["showInfo"])
                or (p == 2 and self.cfg["showDebug"]))

    def next_page(self, direction):
        for _ in range(3):
            self.page = (self.page + direction + 3) % 3
            if self.page_on(self.page):
                break
        self.need_static = True
        self.cache.clear()

    def clear_cache(self):
        self.cache.clear()
        self.bar_cache = [None, None, None, None]

    def text_at(self, x, y, w, h, text, font=1, color=None, bg=None,
                anchor="tl", scale=1, maxw=None):
        bg = C.COL_BG if bg is None else bg
        color = C.COL_TXT if color is None else color
        c = self.scratch
        c.fill(bg)
        tx = 0 if anchor[1] == "l" else w // 2 if anchor[1] == "c" else w
        ty = 0 if anchor[0] == "t" else h // 2 if anchor[0] == "m" else h
        c.text(text, tx, ty, font, color, None, scale, maxw or w, anchor)
        self.d.blit_sub(c, 0, 0, w, h, x, y)

    def field(self, key, x, y, w, h, text, font=1, color=None, bg=None,
              anchor="tl", scale=1, maxw=None):
        color = C.COL_TXT if color is None else color
        bg = C.COL_BG if bg is None else bg
        sig = (str(text), color, font, scale, w, h, anchor, maxw)
        if self.cache.get(key) == sig:
            return
        self.cache[key] = sig
        self.text_at(x, y, w, h, text, font, color, bg, anchor, scale, maxw)

    # ------------------------------------------------------------- screens
    def enter(self, scr, dirty=True):
        if self.scr == SCR_LED_COLOR and scr != SCR_LED_COLOR:
            # The 160x90 colour square is only needed while this screen is
            # open; reclaim its ~29 KiB on a board without PSRAM.
            self.sv_canvas = None
            self._sv_last_hue = -1
            gc.collect()
        self.scr = scr
        self.need_static = True
        self.settings_dirty = dirty
        self.cache.clear()

    def start_boot_calibration(self):
        self.cal_from_boot = True
        self.start_calibration()

    def start_calibration(self):
        self.cal_step = 0
        self.cal_raw = []
        self.cal_fail = False
        self._cal_key = None
        self.enter(SCR_CAL)

    def tick(self, now):
        if self.scr == SCR_MAIN:
            # While disconnected the screen is mostly static.  Redrawing the
            # whole connection screen at 5 Hz instead of 11 Hz keeps the BLE
            # scan/auth loop responsive; live telemetry still updates at 90 ms.
            if (self.nb.is_live() or
                    time.ticks_diff(now, self._last_conn) >= 200):
                self._last_conn = now
                self.draw_main(now)
        elif self.scr == SCR_CAL:
            key = (self.cal_step, self.cal_fail, self.cfg["cal"]["valid"])
            if key != self._cal_key:
                self._cal_key = key
                self.draw_calibration()
        else:
            if self.settings_dirty:
                self.settings_dirty = False
                self.draw_settings()
            if self.scr == SCR_OTA:
                self.draw_ota_dynamic()

    # ---------------------------------------------------------------- main
    def draw_main(self, now):
        live = self.nb.is_live()
        if live != self.was_live:
            self.was_live = live
            self.need_static = True
            self.clear_cache()
            self.d.fill(C.COL_BG)
            if live:
                self.page = 0
        if live:
            if self.need_static:
                if self.page == 0:
                    self.draw_dash_static()
                elif self.page == 1:
                    self.draw_header_full()
                    self.draw_info_static()
                else:
                    self.draw_header_full()
                    self.draw_debug_static()
                self.need_static = False
            if self.page == 0:
                self.draw_dash_dynamic()
            elif self.page == 1:
                self.draw_info_dynamic()
            else:
                self.draw_debug_dynamic()
        else:
            self.draw_connection(now)

    def draw_header(self):
        d = self.d
        d.fill_rect(0, 0, 240, 24, C.COL_PANEL)
        d.hline(0, 23, 240, C.COL_TRACK)
        n = sum(1 for p in range(3) if self.page_on(p))
        if n:
            x = 196 - (n - 1) * 12
            for p in range(3):
                if not self.page_on(p):
                    continue
                d.fill_circle(x, 11, 3 if p == self.page else 2,
                              C.COL_ACCENT if p == self.page else C.COL_TRACK)
                x += 12
        self._gear(224, 11, C.COL_DIM, C.COL_PANEL)
        self.cache.pop("status", None)

    def _gear(self, cx, cy, col, bg):
        d = self.d
        d.fill_rect(cx - 2, cy - 9, 4, 4, col)
        d.fill_rect(cx - 2, cy + 5, 4, 4, col)
        d.fill_rect(cx - 9, cy - 2, 4, 4, col)
        d.fill_rect(cx + 5, cy - 2, 4, 4, col)
        d.fill_circle(cx, cy, 6, col)
        d.fill_circle(cx, cy, 2, bg)

    def draw_header_full(self):
        d = self.d
        d.fill_rect(0, 0, 240, 24, C.COL_PANEL)
        d.hline(0, 23, 240, C.COL_TRACK)
        n = sum(1 for p in range(3) if self.page_on(p))
        x = 196 - (n - 1) * 12
        for p in range(3):
            if not self.page_on(p):
                continue
            d.fill_circle(x, 11, 3 if p == self.page else 2,
                          C.COL_ACCENT if p == self.page else C.COL_TRACK)
            x += 12
        self._gear(224, 11, C.COL_DIM, C.COL_PANEL)
        self.cache.pop("status", None)

    # ------------------------------------------------------------ gauge
    def gauge_color(self, i):
        t = i / (GAUGE_SEGS - 1)
        if self.cfg["style"] == 1:
            return C.COL_ACCENT
        if self.cfg["style"] == 2:
            return C.COL_GOOD if t < 0.5 else C.COL_WARN if t < 0.75 else C.COL_BAD
        stops = (C.COL_ACCENT, C.COL_GOOD, C.COL_WARN, C.COL_BAD)
        pos = (0.0, 0.5, 0.75, 1.0)
        for k in range(3):
            if t <= pos[k + 1]:
                frac = (t - pos[k]) / (pos[k + 1] - pos[k])
                return C.lerp565(stops[k], stops[k + 1], int(frac * 255))
        return stops[3]

    def gauge_seg(self, i, color):
        d = self.d
        a0 = math.radians(-120 + 6 * i + 0.8)
        a1 = math.radians(-120 + 6 * (i + 1) - 0.8)
        ox0 = int(round(GCX + GR_O * math.sin(a0)))
        oy0 = int(round(GCY - GR_O * math.cos(a0)))
        ox1 = int(round(GCX + GR_O * math.sin(a1)))
        oy1 = int(round(GCY - GR_O * math.cos(a1)))
        ix0 = int(round(GCX + GR_I * math.sin(a0)))
        iy0 = int(round(GCY - GR_I * math.cos(a0)))
        ix1 = int(round(GCX + GR_I * math.sin(a1)))
        iy1 = int(round(GCY - GR_I * math.cos(a1)))
        d.fill_triangle(ox0, oy0, ox1, oy1, ix0, iy0, color)
        d.fill_triangle(ox1, oy1, ix1, iy1, ix0, iy0, color)

    def update_gauge(self, speed):
        gmax = self.gmax()
        lit = int(speed / gmax * GAUGE_SEGS + 0.5) if gmax else 0
        lit = 0 if lit < 0 else GAUGE_SEGS if lit > GAUGE_SEGS else lit
        if lit == self.gauge_lit:
            return
        if lit > self.gauge_lit:
            for i in range(self.gauge_lit, lit):
                self.gauge_seg(i, self.gauge_color(i))
        else:
            for i in range(lit, self.gauge_lit):
                self.gauge_seg(i, C.COL_TRACK)
        self.gauge_lit = lit

    def gmax(self):
        return self.cfg["gmaxMph"] if self.cfg["units"] else self.cfg["gmaxKmh"]

    def u_spd(self):
        return self.t("mph", "миль/ч") if self.cfg["units"] else self.t("km/h", "км/ч")

    def u_dst(self):
        return self.t("mi", "миль") if self.cfg["units"] else self.t("km", "км")

    # ------------------------------------------------------- dashboard draw
    def draw_dash_static(self):
        d = self.d
        d.fill(C.COL_BG)
        self.draw_header_full()
        for i in range(GAUGE_SEGS):
            self.gauge_seg(i, C.COL_TRACK)
        self.gauge_lit = 0
        for k in range(4):
            a = math.radians(-120 + 80 * k)
            tx = int(round(GCX + 57 * math.sin(a)))
            ty = int(round(GCY - 57 * math.cos(a)))
            self.text_at(tx - 20, ty - 7, 40, 14, str(self.gmax() * k // 3),
                         1, C.COL_DIM, C.COL_BG, "tc", 1, 40)
        self.text_at(60, GCY + 14, 120, 20, self.u_spd(), 2, C.COL_ACCENT,
                     C.COL_BG, "tc", 1, 120)
        for i in range(4):
            self._card(CX[i], CY[i], 108, 50)
            self.text_at(CX[i] + 8, CY[i] + 4, 92, 12,
                         self.metric_name(self.cfg["card"][i]), 1,
                         C.COL_DIM, C.COL_PANEL, "tl", 1, 92)

    def _card(self, x, y, w, h):
        self.d.fill_round_rect(x, y, w, h, 6, C.COL_PANEL)

    def draw_dash_dynamic(self):
        d = self.d
        nb = self.nb
        data = nb.data
        self.field("status", 18, 1, 150, 22, self.status_text(nb.status_text),
                   2, self.status_color(), C.COL_PANEL, "tl", 1, 140)

        speed = km_u(data.speed, self.cfg["units"]) if data.has(0) else None
        self.update_gauge(speed or 0)
        self.field("speed", 20, 72, 200, 54,
                   "%.1f" % speed if speed is not None else "--",
                   4, C.COL_TXT, C.COL_BG, "tc", 2, 200)
        self.field("ride", 50, GCY + 38, 140, 20, self.ride_mode_label(),
                   2, self.ride_mode_color(), C.COL_BG, "tc", 1, 140)
        total = data.has_total()
        odo = ("ODO %.1f %s" % (km_u(data.total_km, self.cfg["units"]), self.u_dst())
               if total else "ODO -- " + self.u_dst())
        self.field("odo", 20, 184, 200, 18, odo, 2, C.COL_DIM, C.COL_BG, "tc", 1, 200)

        for i in range(4):
            value, sub, col, bar = self.metric_out(self.cfg["card"][i])
            self.field("v%d" % i, CX[i] + 4, CY[i] + 16, 100, 26,
                       value, 4, col, C.COL_PANEL, "tl", 1, 96)
            if bar >= 0:
                self._draw_bar(i, bar, col)
            else:
                self.field("s%d" % i, CX[i] + 8, CY[i] + 39, 92, 11,
                           sub, 1, C.COL_DIM, C.COL_PANEL, "tl", 1, 92)

    def _draw_bar(self, i, lit, color):
        key = (lit, color)
        if self.bar_cache[i] == key:
            return
        self.bar_cache[i] = key
        d = self.d
        x = CX[i] + 8
        y = CY[i] + 36
        d.fill_rect(x, y, 92, 8, C.COL_PANEL)
        for k in range(10):
            d.fill_round_rect(x + (k * 92) // 10, y, 7, 6, 2,
                              color if k < lit else C.COL_TRACK)

    def ride_mode_label(self):
        data = self.nb.data
        if not (data.valid & (1 << 11)):
            return "--"
        mode = data.ride_mode
        if mode == 0:
            return self.t("DRIVE", "ДРАЙВ")
        if mode == 1:
            return self.t("ECO", "ЭКО")
        if mode == 2:
            return self.t("SPORT", "СПОРТ")
        return self.t("MODE ", "РЕЖИМ ") + str(mode)

    def ride_mode_color(self):
        data = self.nb.data
        if not (data.valid & (1 << 11)):
            return C.COL_DIM
        if data.ride_mode == 0:
            return C.COL_ACCENT
        if data.ride_mode == 1:
            return C.COL_GOOD
        if data.ride_mode == 2:
            return C.COL_WARN
        return C.COL_DIM

    def metric_out(self, m):
        data = self.nb.data
        units = self.cfg["units"]
        value = "--"
        sub = " "
        col = C.COL_DIM
        bar = -1
        if m == config.M_BATT:
            bar = 0
            if data.has(5):
                value = "%d%%" % data.soc
                col = C.COL_GOOD if data.soc > 50 else C.COL_WARN if data.soc > 20 else C.COL_BAD
                bar = (data.soc + 5) // 10
        elif m == config.M_POWER:
            if data.has(7) and data.has(6):
                watts = data.volt * data.amp
                value = "%d W" % int(watts)
                col = C.COL_GOOD if watts < -5 else C.COL_WARN if watts > 600 else C.COL_TXT
                sub = "%.1fV %.1fA" % (data.volt, data.amp)
            else:
                value = "-- W"
        elif m == config.M_TRIP:
            if data.has(1):
                value = "%.2f" % km_u(data.trip_km, units)
                col = C.COL_TXT
            sub = self.u_dst()
        elif m == config.M_TEMP:
            he = data.has(4)
            hb = data.has(8)
            value = ("%d" % round(data.esc_temp) if he else "--") + "/" + (
                "%d" % round(data.batt_temp) if hb else "--")
            col = self.temp_color(data.esc_temp) if he else (
                self.temp_color(data.batt_temp) if hb else C.COL_DIM)
            sub = self.t("ESC/BAT C", "ESC/АКБ C")
        elif m == config.M_ODO:
            if data.has_total():
                t = km_u(data.total_km, units)
                value = "%d" % round(t) if t >= 1000 else "%.1f" % t
                col = C.COL_TXT
            sub = self.u_dst()
        elif m == config.M_VOLT:
            if data.has(7):
                value = "%.1f V" % data.volt
                col = C.COL_TXT
        elif m == config.M_CURR:
            if data.has(6):
                value = "%.1f A" % data.amp
                col = C.COL_GOOD if data.amp < -0.5 else C.COL_TXT
        elif m == config.M_MAXSPD:
            if data.has(0):
                value = "%.1f" % km_u(data.session_max, units)
                col = C.COL_TXT
            sub = self.u_spd() + " " + self.t("this ride", "за поездку")
        return value, sub, col, bar

    @staticmethod
    def temp_color(t):
        return C.COL_GOOD if t < 45 else C.COL_WARN if t < 60 else C.COL_BAD

    # -------------------------------------------------------- connection UI
    def draw_connection(self, now):
        d = self.d
        d.fill(C.COL_BG)
        self._gear(224, 11, C.COL_DIM, C.COL_BG)
        w1 = Canvas.text_width("OPEN", 2)
        w2 = Canvas.text_width("DASH", 2)
        x = 120 - (w1 + 4 + w2) // 2
        self.text_at(x, 31, w1 + 2, 20, "OPEN", 2, C.COL_ACCENT, C.COL_BG, "tl", 1, w1 + 2)
        self.text_at(x + w1 + 4, 31, w2 + 2, 20, "DASH", 2, C.COL_TXT, C.COL_BG, "tl", 1, w2 + 2)
        self.text_at(20, 290, 200, 14,
                     self.t("Tap the gear for settings", "Настройки: значок шестерёнки"),
                     1, C.COL_DIM, C.COL_BG, "tc", 1, 200)

        nb_state = self.nb.state
        nb_auth = self.nb.auth_state
        if nb_state != 5:
            if nb_state in (0, 1):          # IDLE / SCAN
                phase = 0
            elif nb_state == 4:             # AUTH
                if nb_auth == 2:            # AUTH_WAIT_PING
                    phase = 2
                elif nb_auth == 3:          # AUTH_WAIT_PAIR
                    phase = 3
                else:
                    phase = 1
            elif nb_state in (2, 3):        # CONNECT / DISCOVER
                phase = 1
            else:
                phase = 0
        else:
            phase = 3
        power = self.nb.press_power and phase == 2
        blink = power and ((now // 400) & 1)
        base = C.COL_WARN if power else C.COL_ACCENT

        head = (now // 90) % 12
        for i in range(12):
            dd = (head - i + 12) % 12
            alpha = 255 - dd * 36 if dd < 7 else 20
            a = math.radians(i * 30)
            px = int(round(120 + 34 * math.sin(a)))
            py = int(round(100 - 34 * math.cos(a)))
            d.fill_circle(px, py, 5, C.lerp565(C.COL_BG, base, alpha))

        titles = (self.t("SEARCHING", "Поиск"), self.t("CONNECTING", "Подключение"),
                  self.t("PRESS POWER", "Нажмите кнопку"), self.t("PAIRING", "Сопряжение"))
        subs = (self.t("Turn on the scooter and stay close", "Включите самокат и будьте рядом"),
                self.t("Starting secure handshake", "Устанавливаем защищённую связь"),
                self.t("Press the scooter power button once", "Нажмите кнопку питания самоката"),
                self.t("Almost there...", "Почти готово..."))
        self.text_at(8, 146, 224, 28, titles[phase], 4,
                     C.COL_WARN if power else C.COL_TXT, C.COL_BG, "tc", 1, 224)
        self.text_at(8, 178, 224, 18, subs[phase], 2, C.COL_DIM,
                     C.COL_BG, "tc", 1, 224)

        names = (self.t("SCAN", "Поиск"), self.t("LINK", "Связь"),
                 self.t("POWER", "Кнопка"), self.t("PAIR", "Пара"))
        for i in range(4):
            x = 8 + i * 57
            if i < phase:
                fill = C.lerp565(C.COL_PANEL, C.COL_ACCENT, 90)
                fg = C.COL_TXT
            elif i == phase:
                fill = C.COL_TXT if blink else base
                fg = C.COL_BG
            else:
                fill = C.COL_PANEL
                fg = C.COL_DIM
            d.fill_round_rect(x, 224, 52, 26, 6, fill)
            self.text_at(x, 224, 52, 26, names[i], 1, fg, fill, "mc", 1, 48)

        if self.nb.status_text in ("not found", "conn fail", "no NUS", "chr fail", "link lost"):
            self.text_at(20, 262, 200, 16, self.status_text(self.nb.status_text),
                         1, C.COL_BAD, C.COL_BG, "tc", 1, 200)

    # ------------------------------------------------------------ info page
    def draw_info_static(self):
        labels = (
            self.t("DEVICE", "Устройство"), self.t("SERIAL", "Серийный номер"),
            self.t("FIRMWARE", "Прошивка"),
            self.t("ODOMETER (%s)" % self.u_dst(), "Одометр (%s)" % self.u_dst()),
            self.t("TRIP (%s)" % self.u_dst(), "Поездка (%s)" % self.u_dst()),
            self.t("VOLTAGE (V)", "Напряжение (В)"), self.t("CURRENT (A)", "Ток (А)"),
            self.t("ESC / BAT TEMP", "Темп. ESC / АКБ"),
        )
        for i, text in enumerate(labels):
            y = 28 + i * 36
            self._card(6, y, 228, 32)
            self.text_at(13, y + 11, 100, 12, text, 1, C.COL_DIM, C.COL_PANEL, "tl", 1, 100)

    def draw_info_dynamic(self):
        data = self.nb.data
        fw = "%X.%02X" % (data.fw >> 8, data.fw & 0xFF) if data.fw else "--"
        vals = (
            self.nb.dev_name,
            data.serial if data.serial else "--",
            fw,
            "%.1f" % km_u(data.total_km, self.cfg["units"]) if data.has_total() else "--",
            "%.2f" % km_u(data.trip_km, self.cfg["units"]) if data.has(1) else "--",
            "%.2f" % data.volt if data.has(7) else "--",
            "%.2f" % data.amp if data.has(6) else "--",
            ("%d" % round(data.esc_temp) if data.has(4) else "--") + " / " +
            ("%d" % round(data.batt_temp) if data.has(8) else "--"),
        )
        for i, value in enumerate(vals):
            y = 28 + i * 36
            self.field("inf%d" % i, 116, y + 8, 110, 20, value, 2,
                       C.COL_TXT, C.COL_PANEL, "tr", 1, 108)

    # ----------------------------------------------------------- debug page
    def draw_debug_static(self):
        for i, text in enumerate(("RX", "TX", "FRAMES", "BAD")):
            x = 8 + (i % 2) * 116
            y = 30 + (i // 2) * 42
            self._card(x, y, 108, 36)
            self.text_at(x + 8, y + 5, 60, 12, text, 1, C.COL_DIM, C.COL_PANEL, "tl", 1, 60)
        self._card(8, 116, 224, 48)
        self.text_at(16, 120, 160, 12, "LAST RX BYTES", 1, C.COL_DIM, C.COL_PANEL, "tl", 1, 160)
        self._card(8, 172, 224, 140)
        self.text_at(16, 176, 160, 12, "VALID FRAMES", 1, C.COL_DIM, C.COL_PANEL, "tl", 1, 160)

    def draw_debug_dynamic(self):
        nb = self.nb
        vals = (nb.notify_count, nb.tx_count, nb.frame_count, nb.checksum_errors)
        for i, value in enumerate(vals):
            x = 16 + (i % 2) * 116
            y = 43 + (i // 2) * 42
            self.field("dbgc%d" % i, x, y, 92, 20, str(value), 2,
                       C.COL_BAD if i == 3 and value else C.COL_TXT,
                       C.COL_PANEL, "tl", 1, 92)
        raw = nb.last_notify
        self.field("dbgr1", 16, 136, 208, 12, self.hex_line(raw[:14]), 1,
                   C.COL_ACCENT, C.COL_PANEL, "tl", 1, 208)
        self.field("dbgr2", 16, 150, 208, 12, self.hex_line(raw[14:]), 1,
                   C.COL_ACCENT, C.COL_PANEL, "tl", 1, 208)
        for i in range(7):
            self.field("dbgl%d" % i, 16, 194 + i * 16, 208, 14, nb.dbg[i], 1,
                       C.COL_GOOD, C.COL_PANEL, "tl", 1, 208)

    @staticmethod
    def hex_line(data):
        return " ".join("%02X" % b for b in data)

    # ------------------------------------------------------------ dashboard
    def open_settings(self):
        self.enter(SCR_SET)

    def leave_settings(self):
        self.enter(SCR_MAIN)

    def restore_led_color(self):
        if self._led_color_orig is None:
            return
        led = self.cfg["led"]
        seg = self.led_color_seg
        led["hue"][seg], led["sat"][seg], led["val"][seg] = self._led_color_orig
        self._led_color_orig = None

    def go_back(self):
        if self.scr == SCR_SET:
            self.leave_settings()
        elif self.scr == SCR_PICK:
            if self.pick_return == SCR_MAIN:
                self.leave_settings()
            else:
                self.enter(SCR_WIDGETS)
        elif self.scr == SCR_CAL:
            if self.cfg["cal"]["valid"]:
                self.enter(SCR_MAIN if self.cal_from_boot else SCR_SET)
        elif self.scr == SCR_LED_COLOR:
            self.restore_led_color()
            self.app.save_now()
            self.enter(SCR_LED)
        elif self.scr == SCR_LED_EFFECT:
            self.enter(SCR_LED)
        elif self.scr == SCR_SHFW_EDIT:
            self.enter(SCR_SHFW_LIST)
        elif self.scr in (SCR_SHFW_LIST, SCR_SHFW_BAK, SCR_SHFW_PROF):
            self.enter(SCR_SHFW)
        else:
            self.enter(SCR_SET)

    def page_draw(self):
        # page switching without a full redraw
        self.d.fill(C.COL_BG)
        if self.page == 0:
            self.draw_dash_static()
            self.draw_dash_dynamic()
        elif self.page == 1:
            self.draw_header_full()
            self.draw_info_static()
            self.draw_info_dynamic()
        else:
            self.draw_header_full()
            self.draw_debug_static()
            self.draw_debug_dynamic()
        self.need_static = False

    # ------------------------------------------------------------- settings
    def settings_header(self, title):
        d = self.d
        d.fill_rect(0, 0, 240, 28, C.COL_PANEL)
        d.hline(0, 28, 240, C.COL_TRACK)
        d.fill_triangle(16, 14, 25, 7, 25, 21, C.COL_ACCENT)
        self.text_at(30, 0, 200, 28, title, 2, C.COL_TXT, C.COL_PANEL, "mc", 1, 196)

    def btn(self, x, y, w, h, text, selected, font=2, maxw=None):
        fill = C.COL_ACCENT if selected else C.COL_PANEL
        fg = C.COL_BG if selected else C.COL_TXT
        self.d.fill_round_rect(x, y, w, h, 6, fill)
        self.text_at(x + 4, y, w - 8, h, text, font, fg, fill, "mc", 1, maxw or (w - 8))

    def section(self, x, y, text):
        self.text_at(x, y, 220, 12, text, 1, C.COL_DIM, C.COL_BG, "tl", 1, 220)

    def draw_settings(self):
        d = self.d
        d.fill(C.COL_BG)
        scr = self.scr
        if scr == SCR_SET:
            self.draw_set_root()
        elif scr == SCR_APPEAR:
            self.draw_set_appearance()
        elif scr == SCR_DISPLAY:
            self.draw_set_display()
        elif scr == SCR_GAUGE:
            self.draw_set_gauge()
        elif scr == SCR_WIDGETS:
            self.draw_set_widgets()
        elif scr == SCR_PICK:
            self.draw_set_pick()
        elif scr == SCR_LED:
            self.draw_set_led()
        elif scr == SCR_LED_EFFECT:
            self.draw_set_led_effect()
        elif scr == SCR_LED_COLOR:
            self.draw_set_led_color()
        elif scr == SCR_OTA:
            self.draw_set_ota()
        elif scr == SCR_SHFW:
            self.draw_set_shfw()
        elif scr == SCR_SHFW_LIST:
            self.draw_shfw_list()
        elif scr == SCR_SHFW_EDIT:
            self.draw_shfw_edit()
        elif scr == SCR_SHFW_BAK:
            self.draw_shfw_backup()
        elif scr == SCR_SHFW_PROF:
            self.draw_shfw_profiles()

    def draw_set_root(self):
        self.settings_header(self.t("SETTINGS", "НАСТРОЙКИ"))
        rows = (
            self.t("Appearance", "Внешний вид"),
            self.t("Display", "Экран"),
            self.t("Gauge & units", "Спидометр и единицы"),
            self.t("Widgets", "Виджеты"),
            self.t("Language", "Язык") + ": " + ("English" if not self.cfg["lang"] else "Русский"),
            self.t("Touch calibration", "Калибровка тача"),
            self.t("ARGB strip", "ARGB-лента"),
            self.t("OTA update", "Обновление OTA"),
            self.t("SHFW settings", "Настройки SHFW"),
            self.t("Reset to defaults", "Сброс настроек"),
        )
        for i, text in enumerate(rows):
            y = 32 + i * 28
            self.d.fill_rect(8, y, 224, 27, C.COL_PANEL)
            self.text_at(16, y, 196, 27, text, 2,
                         C.COL_BAD if i == 9 else C.COL_TXT, C.COL_PANEL, "ml", 1, 196)
            if i != 4 and i != 9:
                self.d.fill_triangle(220, y + 9, 226, y + 13, 220, y + 17, C.COL_DIM)

    def draw_set_appearance(self):
        self.settings_header(self.t("APPEARANCE", "ВНЕШНИЙ ВИД"))
        self.section(8, 34, self.t("THEME", "ТЕМА"))
        for i, theme in enumerate(C.THEMES):
            self.btn(8 + i * 58, 48, 54, 40,
                     (theme[1] if self.cfg["lang"] else theme[0]),
                     self.cfg["theme"] == i, 1)
        self.section(8, 96, self.t("ACCENT", "АКЦЕНТ"))
        for i in range(8):
            x = 8 + (i % 4) * 58
            y = 110 + (i // 4) * 38
            self.d.fill_round_rect(x, y, 54, 34, 5, C.ACCENTS[i])
            if self.cfg["accent"] == i:
                self.d.rect(x - 2, y - 2, 58, 38, C.COL_TXT)
        self.section(8, 190, self.t("CUSTOM HUE", "СВОЙ ОТТЕНОК"))
        self.draw_hue_slider()

    def draw_hue_slider(self):
        d = self.d
        d.fill_rect(8, 200, 224, 42, C.COL_BG)
        for i in range(0, 220, 4):
            d.fill_rect(10 + i, 206, 4, 30, C.hue565(i * 359 // 219))
        kx = 10 + self.cfg["hue"] * 219 // 359
        d.fill_round_rect(kx - 4, 201, 9, 40, 3, C.COL_TXT)
        d.fill_rect(kx - 2, 206, 5, 30, C.hue565(self.cfg["hue"]))
        self.settings_dirty = False

    def draw_set_display(self):
        self.settings_header(self.t("DISPLAY", "ЭКРАН"))
        self.section(8, 34, self.t("BRIGHTNESS", "ЯРКОСТЬ"))
        self.text_at(160, 31, 72, 18, "%d%%" % self.cfg["bright"], 2,
                     C.COL_ACCENT, C.COL_BG, "tr", 1, 70)
        self.draw_brightness()
        self.section(8, 96, self.t("AUTO DIM", "АВТОЗАТЕМНЕНИЕ"))
        for i, label in enumerate((self.t("OFF", "выкл"), "15 s", "30 s", "60 s")):
            self.btn(8 + i * 58, 110, 54, 40, label, self.cfg["dim"] == i, 2)
        self.section(8, 160, self.t("ROTATION", "ПОВОРОТ"))
        self.btn(8, 172, 108, 40, self.t("NORMAL", "ОБЫЧНЫЙ"), self.cfg["flip"] == 0)
        self.btn(124, 172, 108, 40, self.t("FLIPPED 180", "ПЕРЕВЁРНУТ"), self.cfg["flip"] == 1)
        self.section(8, 222, self.t("LOCK WHILE RIDING", "БЛОКИРОВКА В ДВИЖЕНИИ"))
        self.btn(8, 234, 108, 40, self.t("ON", "ВКЛ"), self.cfg["lock"] == 1)
        self.btn(124, 234, 108, 40, self.t("OFF", "ВЫКЛ"), self.cfg["lock"] == 0)

    def draw_brightness(self):
        d = self.d
        d.fill_round_rect(10, 52, 220, 28, 8, C.COL_PANEL)
        frac = (self.cfg["bright"] - 10) / 90.0
        d.fill_round_rect(10, 52, 12 + int(frac * 208), 28, 8, C.COL_ACCENT)

    def draw_set_gauge(self):
        self.settings_header(self.t("GAUGE & UNITS", "СПИДОМЕТР"))
        self.section(8, 34, self.t("UNITS", "ЕДИНИЦЫ"))
        self.btn(8, 48, 108, 44, "km/h", self.cfg["units"] == 0)
        self.btn(124, 48, 108, 44, "mph", self.cfg["units"] == 1)
        self.section(8, 100, self.t("MAX SCALE", "МАКСИМУМ ШКАЛЫ"))
        self.btn(8, 116, 64, 44, "-", False)
        self.text_at(76, 116, 88, 44, str(self.gmax()), 4, C.COL_TXT,
                     C.COL_BG, "mc", 1, 84)
        self.btn(168, 116, 64, 44, "+", False)
        self.section(8, 172, self.t("COLOUR STYLE", "СТИЛЬ ЦВЕТА"))
        names = C.STYLE_NAME_RU if self.cfg["lang"] else C.STYLE_NAME
        for i in range(3):
            self.btn(8 + i * 76, 186, 72, 44, names[i],
                     self.cfg["style"] == i, 1)

    def draw_set_widgets(self):
        self.settings_header(self.t("WIDGETS", "ВИДЖЕТЫ"))
        for i in range(4):
            x = 8 + (i % 2) * 116
            y = 48 + (i // 2) * 70
            self.d.fill_round_rect(x, y, 108, 64, 6, C.COL_PANEL)
            self.text_at(x + 8, y + 8, 92, 14, self.t("CARD", "КАРТОЧКА") + " %d" % (i + 1),
                         1, C.COL_DIM, C.COL_PANEL, "tl", 1, 92)
            self.text_at(x + 8, y + 28, 92, 26, self.metric_name(self.cfg["card"][i]),
                         2, C.COL_TXT, C.COL_PANEL, "tl", 1, 92)
        self.btn(8, 206, 108, 44,
                 self.t("INFO PAGE", "СТР. ИНФО") + " " + (self.t("ON", "ВКЛ") if self.cfg["showInfo"] else self.t("OFF", "ВЫКЛ")),
                 self.cfg["showInfo"] == 1, 1)
        self.btn(124, 206, 108, 44,
                 self.t("DEBUG PAGE", "СТР. ОТЛАДКИ") + " " + (self.t("ON", "ВКЛ") if self.cfg["showDebug"] else self.t("OFF", "ВЫКЛ")),
                 self.cfg["showDebug"] == 1, 1)

    def draw_set_pick(self):
        self.settings_header(self.t("WIDGET", "ВИДЖЕТ"))
        for i in range(config.M_COUNT):
            x = 8 + (i % 2) * 116
            y = 36 + (i // 2) * 50
            self.btn(x, y, 108, 44, self.metric_name(i),
                     self.cfg["card"][self.pick_slot] == i, 2)

    def draw_set_led(self):
        led = self.cfg["led"]
        self.settings_header(self.t("ARGB STRIP", "ARGB-ЛЕНТА"))
        self.section(8, 32, self.t("LED COUNT", "КОЛИЧЕСТВО LED"))
        self.btn(8, 40, 58, 26, "-", False, 2)
        self.text_at(70, 40, 100, 26, str(led["count"]), 2, C.COL_TXT,
                     C.COL_BG, "mc", 1, 96)
        self.btn(174, 40, 58, 26, "+", False, 2)
        self.section(8, 72, self.t("BRIGHTNESS", "ЯРКОСТЬ"))
        self.text_at(170, 70, 62, 16, "%d%%" % (led["bright"] * 100 // 255), 1,
                     C.COL_ACCENT, C.COL_BG, "tr", 1, 60)
        self.draw_led_brightness()
        self.btn(8, 120, 108, 26, "GPIO %d" % config.LED_PINS[led["pinIndex"]], False, 2)
        self.btn(124, 120, 108, 26,
                 self.t("LED ", "ЛЕНТА ") + (self.t("ON", "ВКЛ") if led["enabled"] else self.t("OFF", "ВЫКЛ")),
                 led["enabled"] == 1, 2)
        brake = C.LED_BRAKE_NAMES_RU if self.cfg["lang"] else C.LED_BRAKE_NAMES
        self.btn(8, 152, 224, 26, self.t("BRAKE: ", "ТОРМОЖЕНИЕ: ") + brake[led["brake"]], False, 2)
        effects = C.LED_EFFECT_NAMES_RU if self.cfg["lang"] else C.LED_EFFECT_NAMES
        start = 0
        for i in range(3):
            y = 184 + i * 44
            length = led["segmentCount"][i]
            self.section(8, y, "SEG %d  %d-%d" % (i + 1, start, start + max(0, length - 1)))
            self.btn(14, y + 18, 28, 21, "-", False, 2)
            self.text_at(46, y + 18, 32, 21, str(length), 2, C.COL_TXT,
                         C.COL_BG, "mc", 1, 30)
            self.btn(82, y + 18, 28, 21, "+", False, 2)
            self.btn(114, y + 18, 68, 21, effects[led["effect"][i]], False, 1)
            rgb = C.hsv_rgb(led["hue"][i], led["sat"][i], led["val"][i])
            self.d.fill_rect(196, y + 18, 32, 21,
                             C.rgb565(rgb[0], rgb[1], rgb[2]))
            start += length

    def draw_led_brightness(self):
        d = self.d
        led = self.cfg["led"]
        d.fill_round_rect(10, 88, 220, 24, 7, C.COL_PANEL)
        frac = (led["bright"] - 1) / 254.0
        d.fill_round_rect(10, 88, 12 + int(frac * 208), 24, 7, C.COL_ACCENT)

    def draw_set_led_effect(self):
        self.settings_header(self.t("EFFECT", "ЭФФЕКТ"))
        names = C.LED_EFFECT_NAMES_RU if self.cfg["lang"] else C.LED_EFFECT_NAMES
        seg = self.led_color_seg
        for i in range(12):
            x = 8 + (i % 2) * 116
            y = 34 + (i // 2) * 44
            self.btn(x, y, 108, 38, names[i],
                     self.cfg["led"]["effect"][seg] == i, 2)

    def draw_set_led_color(self):
        led = self.cfg["led"]
        seg = self.led_color_seg
        self.settings_header(self.t("COLOUR", "ЦВЕТ"))
        self.draw_sv_square(force=True)
        self.draw_hue_strip()
        for i in range(8):
            rgb = C.LED_COLORS[i]
            self.d.fill_rect(10 + i * 28, 184, 26, 26,
                             C.rgb565((rgb >> 16) & 0xFF, (rgb >> 8) & 0xFF, rgb & 0xFF))
        hue, sat, val = led["hue"][seg], led["sat"][seg], led["val"][seg]
        rgb = C.hsv_rgb(hue, sat, val)
        self.text_at(10, 216, 220, 18, "HEX #%02X%02X%02X" % rgb, 2,
                     C.COL_ACCENT, C.COL_BG, "tl", 1, 160)
        self.btn(8, 254, 108, 38, self.t("DONE", "ГОТОВО"), True)
        self.btn(124, 254, 108, 38, self.t("CANCEL", "ОТМЕНА"), False)
        self.draw_sv_marker()

    def _sv_geo(self):
        return 40, 44, 160, 90

    def draw_sv_square(self, force=False):
        led = self.cfg["led"]
        seg = self.led_color_seg
        hue = led["hue"][seg]
        now = time.ticks_ms()
        if not force and hue == self._sv_last_hue:
            return
        if not force and time.ticks_diff(now, self._last_sv_draw) < 120:
            return
        self._last_sv_draw = now
        self._sv_last_hue = hue
        x0, y0, w, h = self._sv_geo()
        if self.sv_canvas is None:
            self.sv_canvas = Canvas(w, h)
        c = self.sv_canvas
        fb = c.fb
        for y in range(h):
            v = 255 - y * 255 // (h - 1)
            for x in range(w):
                s = x * 255 // (w - 1)
                rgb = C.hsv_rgb(hue, s, v)
                fb.pixel(x, y, C.swap(C.rgb565(rgb[0], rgb[1], rgb[2])))
        self.d.blit(x0, y0, w, h, c.buf)
        self._sv_marker = None

    def draw_sv_marker(self):
        led = self.cfg["led"]
        seg = self.led_color_seg
        x0, y0, w, h = self._sv_geo()
        x = x0 + led["sat"][seg] * (w - 1) // 255
        y = y0 + (255 - led["val"][seg]) * (h - 1) // 255
        # Keep the 6 px marker ring inside the square so its old pixels can
        # always be restored from the cached SV canvas.
        x = max(x0 + 6, min(x0 + w - 7, x))
        y = max(y0 + 6, min(y0 + h - 7, y))
        if self._sv_marker is not None:
            ox, oy = self._sv_marker
            self.d.blit_sub(self.sv_canvas, ox - x0 - 6, oy - y0 - 6, 13, 13,
                            ox - 6, oy - 6)
        self._sv_marker = (x, y)
        self.d.circle(x, y, 5, C.COL_TXT)
        self.d.circle(x, y, 6, C.COL_BG)

    def draw_hue_strip(self):
        led = self.cfg["led"]
        seg = self.led_color_seg
        d = self.d
        d.fill_rect(40, 146, 160, 28, C.COL_BG)
        for i in range(0, 156, 4):
            d.fill_rect(42 + i, 150, 4, 20, C.hue565(i * 359 // 155))
        kx = 42 + led["hue"][seg] * 155 // 359
        d.fill_round_rect(kx - 3, 146, 8, 28, 2, C.COL_TXT)
        d.fill_rect(kx - 1, 150, 4, 20, C.hue565(led["hue"][seg]))

    def draw_set_ota(self):
        self.settings_header(self.t("OTA UPDATE", "ОБНОВЛЕНИЕ OTA"))
        enabled = self.app.ota.enabled
        self.btn(8, 54, 224, 44,
                 self.t("DISABLE ACCESS", "ВЫКЛЮЧИТЬ ДОСТУП") if enabled
                 else self.t("ENABLE ACCESS", "ВКЛЮЧИТЬ ДОСТУП"), enabled, 2)
        if enabled:
            self.text_at(10, 112, 220, 18,
                         self.t("Wi-Fi: ", "Wi-Fi: ") + self.app.ota.ssid, 2,
                         C.COL_TXT, C.COL_BG, "tl", 1, 220)
            self.text_at(10, 136, 220, 18,
                         self.t("Password: ", "Пароль: ") + self.app.ota.password, 2,
                         C.COL_TXT, C.COL_BG, "tl", 1, 220)
            self.text_at(10, 160, 220, 18, "http://" + self.app.ota.ip + "/", 2,
                         C.COL_ACCENT, C.COL_BG, "tl", 1, 220)
            self.text_at(10, 194, 220, 44,
                         self.t("Open the address, choose the MicroPython .app-bin "
                                "and upload. Do not power off.",
                                "Откройте адрес, выберите .app-bin MicroPython "
                                "и загрузите. Не отключайте питание."),
                         1, C.COL_DIM, C.COL_BG, "tl", 1, 220)
            self.field("otastat", 10, 246, 220, 14, self.app.ota.status, 1,
                       C.COL_GOOD, C.COL_BG, "tl", 1, 220)
        else:
            self.text_at(10, 116, 220, 60,
                         self.t("Enable the access point, connect from a phone "
                                "or PC and upload the MicroPython .app-bin.",
                                "Включите точку доступа, подключитесь с телефона "
                                "или ПК и загрузите .app-bin MicroPython."),
                         1, C.COL_DIM, C.COL_BG, "tl", 1, 220)
            if self.app.ota.status:
                self.text_at(10, 246, 220, 14,
                             self.status_text(self.app.ota.status), 1,
                             C.COL_BAD, C.COL_BG, "tl", 1, 220)

    def draw_ota_dynamic(self):
        if self.app.ota.enabled:
            status = self.app.ota.status
            col = C.COL_GOOD if status.startswith("http") else C.COL_WARN
            self.field("otastat", 10, 246, 220, 14, status, 1,
                       col, C.COL_BG, "tl", 1, 220)

    # ------------------------------------------------------------- SHFW UI
    # The screens and the 83-register table are imported only when the rider
    # opens the SHFW menu.  This keeps Ninebot() and UI() within the small
    # boot heap of an ESP32 CYD without PSRAM.
    def _shfw_ui_failed(self):
        self.settings_header(self.t("SHFW SETTINGS", "Настройки SHFW"))
        self.text_at(
            8, 40, 224, 24,
            self.t("SHFW module is not available",
                   "Модуль SHFW недоступен"),
            2, C.COL_BAD, C.COL_BG, "tl", 1, 224)
        self.text_at(
            8, 76, 224, 40,
            self.shfw_msg or self.t(
                "Reinstall the firmware files.",
                "Переустановите файлы прошивки."),
            1, C.COL_DIM, C.COL_BG, "tl", 1, 224)

    def _shfw_ui(self):
        global _shfw_ui_mod, _shfw_ui_error
        if _shfw_ui_mod is not None:
            return _shfw_ui_mod
        gc.collect()
        try:
            try:
                from opendash import shfwui as mod
            except ImportError:
                from . import shfwui as mod
            _shfw_ui_mod = mod
            _shfw_ui_error = ""
        except Exception as exc:
            _shfw_ui_error = "%s: %s" % (exc.__class__.__name__, exc)
            print("SHFW UI load failed:", _shfw_ui_error)
        return _shfw_ui_mod

    def open_shfw(self):
        self._shfw_open_failed = False
        mod = self._shfw_ui()
        if mod is None:
            self.shfw_msg = self.t(
                "SHFW module could not be loaded: " + _shfw_ui_error,
                "Не удалось загрузить модуль SHFW: " + _shfw_ui_error)
            self.shfw_msg_col = C.COL_BAD
            self.enter(SCR_SHFW)
            self.settings_dirty = True
            return
        try:
            return mod.open_shfw(self)
        except MemoryError as exc:
            self._shfw_open_failed = True
            self.shfw_msg = self.t(
                "Not enough memory for SHFW: %s" % exc,
                "Не хватает памяти для SHFW: %s" % exc)
            self.shfw_msg_col = C.COL_BAD
            self.enter(SCR_SHFW)
            self.settings_dirty = True

    def draw_set_shfw(self):
        mod = self._shfw_ui()
        if mod is None or getattr(self, "_shfw_open_failed", False):
            return self._shfw_ui_failed()
        return mod.draw_set_shfw(self)

    def draw_shfw_list(self):
        mod = self._shfw_ui()
        if mod is None:
            return self._shfw_ui_failed()
        return mod.draw_shfw_list(self)

    def draw_shfw_edit(self):
        mod = self._shfw_ui()
        if mod is None:
            return self._shfw_ui_failed()
        return mod.draw_shfw_edit(self)

    def draw_shfw_backup(self):
        mod = self._shfw_ui()
        if mod is None:
            return self._shfw_ui_failed()
        return mod.draw_shfw_backup(self)

    def draw_shfw_profiles(self):
        mod = self._shfw_ui()
        if mod is None:
            return self._shfw_ui_failed()
        return mod.draw_shfw_profiles(self)

    def touch_shfw(self, t, x, y):
        mod = self._shfw_ui()
        if mod is not None:
            return mod.touch_shfw(self, t, x, y)

    def draw_calibration(self):
        d = self.d
        d.fill(C.COL_BG)
        self.text_at(10, 108, 220, 24, self.t("TOUCH CALIBRATION", "КАЛИБРОВКА ТАЧА"),
                     2, C.COL_TXT, C.COL_BG, "tc", 1, 220)
        self.text_at(10, 142, 220, 20,
                     self.t("Tap the target (%d / 3)", "Коснитесь метки (%d / 3)")
                     % (min(self.cal_step, 2) + 1),
                     2, C.COL_DIM, C.COL_BG, "tc", 1, 220)
        if self.cal_fail:
            self.text_at(10, 168, 220, 20,
                         self.t("Points too close - try again", "Слишком близко, повторите"),
                         2, C.COL_BAD, C.COL_BG, "tc", 1, 220)
        hint = (self.t("BOOT button = cancel", "Кнопка BOOT: отмена")
                if self.cfg["cal"]["valid"]
                else self.t("A stylus gives best accuracy", "Лучше использовать стилус"))
        self.text_at(10, 198, 220, 16, hint, 1, C.COL_DIM, C.COL_BG, "tc", 1, 220)
        x, y = CAL_POINTS[min(self.cal_step, 2)]
        d.circle(x, y, 10, C.COL_ACCENT)
        d.circle(x, y, 5, C.COL_ACCENT)
        d.hline(x - 16, y, 33, C.COL_ACCENT)
        d.vline(x, y - 16, 33, C.COL_ACCENT)

    def touch_calibration(self):
        t = self.app.touch
        if not getattr(t, "ev_up", False) or t.rn < 3:
            return
        raw = t.raw_avg()
        if raw is None:
            return
        self.cal_raw.append(raw)
        self.cal_step += 1
        if self.cal_step >= 3:
            if self.app.touch.finish_calibration(self.cfg, self.cal_raw):
                from_boot = self.cal_from_boot
                self.app.save_now()
                self.cal_from_boot = False
                self.cal_step = 0
                self.cal_raw = []
                self.cal_fail = False
                self.enter(SCR_MAIN if from_boot else SCR_SET)
                self.app.apply_display()
                self.need_static = True
                self.settings_dirty = True
            else:
                self.cal_step = 0
                self.cal_raw = []
                self.cal_fail = True
        else:
            self.cal_fail = False
        self.settings_dirty = True

    # ------------------------------------------------------------- touch
    def handle_touch(self):
        t = self.app.touch
        if self.scr == SCR_MAIN:
            self.touch_main(t)
        elif self.scr == SCR_CAL:
            self.touch_calibration()
        else:
            self.touch_settings(t)

    def action(self):
        return self.app

    def touch_main(self, t):
        live = self.nb.is_live()
        locked = self.cfg["lock"] and live and self.nb.data.speed > 3.0
        if t.swipe and live:
            self.page_draw_after_swipe(t.swipe)
            return
        if locked:
            return
        x, y = t.sx, t.sy
        if t.ev_tap:
            if hit(x, y, 196, 0, 44, 44):
                self.open_settings()
                return
            if live and hit(x, y, 150, 0, 46, 44):
                self.next_page(1)
                self.page_draw()
                return
            if live and self.page == 0:
                for i in range(4):
                    if hit(x, y, CX[i], CY[i], 108, 50):
                        self.cfg["card"][i] = (self.cfg["card"][i] + 1) % config.M_COUNT
                        self.app.save_soon()
                        self.need_static = True
                        self.clear_cache()
                        return
                if hit(x, y, 0, 44, 240, 158):
                    self.cfg["units"] ^= 1
                    self.app.save_soon()
                    self.need_static = True
                    self.clear_cache()
                    return
        if t.ev_long and live and self.page == 0:
            for i in range(4):
                if hit(x, y, CX[i], CY[i], 108, 50):
                    self.pick_slot = i
                    self.pick_return = SCR_MAIN
                    self.enter(SCR_PICK)
                    return

    def page_draw_after_swipe(self, direction):
        for _ in range(3):
            self.page = (self.page + (1 if direction > 0 else -1) + 3) % 3
            if self.page_on(self.page):
                break
        self.clear_cache()
        self.page_draw()

    def touch_settings(self, t):
        x, y = t.sx, t.sy
        # sliders
        if t.ev_down:
            self._drag = -1
            if self.scr == SCR_APPEAR and hit(x, y, 0, 196, 240, 50):
                self._drag = 1
            elif self.scr == SCR_DISPLAY and hit(x, y, 0, 44, 240, 50):
                self._drag = 2
            elif self.scr == SCR_LED and hit(x, y, 8, 84, 224, 32):
                self._drag = 3
            elif self.scr == SCR_LED_COLOR:
                sx, sy, sw, sh = self._sv_geo()
                if hit(x, y, sx, sy, sw, sh):
                    self._drag = 4
                elif hit(x, y, 40, 144, 160, 32):
                    self._drag = 5
        if self._drag >= 0:
            self._drag_update(t)
            return
        if t.ev_tap and hit(x, y, 0, 0, 80, 32):
            self.go_back()
            return
        if t.swipe:
            return
        scr = self.scr
        if scr in (SCR_SHFW, SCR_SHFW_LIST, SCR_SHFW_EDIT,
                   SCR_SHFW_BAK, SCR_SHFW_PROF):
            self.touch_shfw(t, x, y)
            return
        if scr == SCR_SET and (t.ev_tap or t.ev_long):
            for i in range(10):
                if not hit(x, y, 8, 32 + i * 28, 224, 27):
                    continue
                if i == 9:
                    if t.ev_long:
                        self.app.reset_defaults()
                    return
                if not t.ev_tap:
                    return
                if i <= 3:
                    self.enter((SCR_APPEAR, SCR_DISPLAY, SCR_GAUGE, SCR_WIDGETS)[i])
                elif i == 4:
                    self.cfg["lang"] ^= 1
                    self.app.save_soon()
                    self.settings_dirty = True
                elif i == 5:
                    self.cal_from_boot = False
                    self.start_calibration()
                elif i == 6:
                    self.enter(SCR_LED)
                elif i == 7:
                    self.enter(SCR_OTA)
                elif i == 8:
                    self.open_shfw()
                return
            return
        if scr == SCR_APPEAR and t.ev_tap:
            for i in range(4):
                if hit(x, y, 8 + i * 58, 48, 54, 40):
                    self.cfg["theme"] = i
                    self.app.apply_display()
                    self.app.save_soon()
                    self.settings_dirty = True
                    return
            for i in range(8):
                if hit(x, y, 8 + (i % 4) * 58, 110 + (i // 4) * 38, 54, 34):
                    self.cfg["accent"] = i
                    self.app.apply_display()
                    self.app.save_soon()
                    self.settings_dirty = True
                    return
            return
        if scr == SCR_DISPLAY and t.ev_tap:
            for i in range(4):
                if hit(x, y, 8 + i * 58, 110, 54, 40):
                    self.cfg["dim"] = i
                    self.app.save_soon()
                    self.settings_dirty = True
                    return
            if hit(x, y, 8, 172, 108, 40):
                self.cfg["flip"] = 0
                self.app.apply_display()
                self.app.save_soon()
                self.settings_dirty = True
            elif hit(x, y, 124, 172, 108, 40):
                self.cfg["flip"] = 1
                self.app.apply_display()
                self.app.save_soon()
                self.settings_dirty = True
            elif hit(x, y, 8, 234, 108, 40):
                self.cfg["lock"] = 1
                self.app.save_soon()
                self.settings_dirty = True
            elif hit(x, y, 124, 234, 108, 40):
                self.cfg["lock"] = 0
                self.app.save_soon()
                self.settings_dirty = True
            return
        if scr == SCR_GAUGE and t.ev_tap:
            if hit(x, y, 8, 48, 108, 44):
                self.cfg["units"] = 0
            elif hit(x, y, 124, 48, 108, 44):
                self.cfg["units"] = 1
            elif hit(x, y, 8, 116, 64, 44):
                key = "gmaxMph" if self.cfg["units"] else "gmaxKmh"
                lo = 5 if self.cfg["units"] else 10
                self.cfg[key] = max(lo, self.cfg[key] - 3)
            elif hit(x, y, 168, 116, 64, 44):
                key = "gmaxMph" if self.cfg["units"] else "gmaxKmh"
                hi = 40 if self.cfg["units"] else 60
                self.cfg[key] = min(hi, self.cfg[key] + 3)
            elif hit(x, y, 8, 186, 72, 44):
                self.cfg["style"] = 0
            elif hit(x, y, 84, 186, 72, 44):
                self.cfg["style"] = 1
            elif hit(x, y, 160, 186, 72, 44):
                self.cfg["style"] = 2
            else:
                return
            self.app.save_soon()
            self.settings_dirty = True
            return
        if scr == SCR_WIDGETS and t.ev_tap:
            for i in range(4):
                if hit(x, y, 8 + (i % 2) * 116, 48 + (i // 2) * 70, 108, 64):
                    self.pick_slot = i
                    self.pick_return = SCR_WIDGETS
                    self.enter(SCR_PICK)
                    return
            if hit(x, y, 8, 206, 108, 44):
                self.cfg["showInfo"] ^= 1
                self.cfg["showInfo"] &= 1
                self.page = 0
                self.app.save_soon()
                self.settings_dirty = True
            elif hit(x, y, 124, 206, 108, 44):
                self.cfg["showDebug"] ^= 1
                self.cfg["showDebug"] &= 1
                self.page = 0
                self.app.save_soon()
                self.settings_dirty = True
            return
        if scr == SCR_PICK and t.ev_tap:
            for i in range(config.M_COUNT):
                if hit(x, y, 8 + (i % 2) * 116, 36 + (i // 2) * 50, 108, 44):
                    self.cfg["card"][self.pick_slot] = i
                    self.app.save_soon()
                    if self.pick_return == SCR_MAIN:
                        self.enter(SCR_MAIN)
                    else:
                        self.enter(SCR_WIDGETS)
                    return
            return
        if scr == SCR_LED:
            self.touch_led(t, x, y)
            return
        if scr == SCR_LED_EFFECT and t.ev_tap:
            for i in range(12):
                if hit(x, y, 8 + (i % 2) * 116, 34 + (i // 2) * 44, 108, 38):
                    self.cfg["led"]["effect"][self.led_color_seg] = i
                    self.app.save_now()
                    self.enter(SCR_LED)
                    return
            return
        if scr == SCR_LED_COLOR and t.ev_tap:
            if hit(x, y, 8, 254, 108, 38):
                self._led_color_orig = None
                self.app.save_now()
                self.enter(SCR_LED)
            elif hit(x, y, 124, 254, 108, 38):
                self.restore_led_color()
                self.app.save_now()
                self.enter(SCR_LED)
            else:
                for i in range(8):
                    if hit(x, y, 10 + i * 28, 184, 26, 26):
                        rgb = C.LED_COLORS[i]
                        h, s, v = C.rgb_to_hsv((rgb >> 16) & 0xFF,
                                               (rgb >> 8) & 0xFF, rgb & 0xFF)
                        led = self.cfg["led"]
                        seg = self.led_color_seg
                        led["hue"][seg], led["sat"][seg], led["val"][seg] = h, s, v
                        self.draw_sv_square(force=True)
                        self.draw_hue_strip()
                        self.draw_sv_marker()
                        self.settings_dirty = False
                        return
            return
        if scr == SCR_OTA and t.ev_tap:
            if hit(x, y, 8, 54, 224, 44):
                self.app.set_ota(not self.app.ota.enabled)
                self.settings_dirty = True
            return

    def _drag_update(self, t):
        x = t.x if t.down else t.x
        drag = self._drag
        if drag == 1:
            f = max(0.0, min(1.0, (x - 10) / 220.0))
            h = int(f * 359)
            if h != self.cfg["hue"] or self.cfg["accent"] != 8:
                self.cfg["hue"] = h
                self.cfg["accent"] = 8
                # Recolour the slider live, but do not repaint the whole
                # settings screen on every touch sample.
                C.apply_theme(self.cfg["theme"], 8, h)
                self.draw_hue_slider()
            if not t.down:
                self._drag = -1
                self.app.apply_display()
                self.app.save_soon()
        elif drag == 2:
            f = max(0.0, min(1.0, (x - 10) / 220.0))
            bv = 10 + int(f * 90)
            if bv != self.cfg["bright"]:
                self.cfg["bright"] = bv
                self.app.set_backlight(bv)
                self.text_at(160, 31, 72, 18, "%d%%" % bv, 2,
                             C.COL_ACCENT, C.COL_BG, "tr", 1, 70)
                self.draw_brightness()
            if not t.down:
                self._drag = -1
                self.app.save_soon()
        elif drag == 3:
            f = max(0.0, min(1.0, (x - 10) / 220.0))
            bv = 1 + int(f * 254)
            led = self.cfg["led"]
            if bv != led["bright"]:
                led["bright"] = bv
                self.draw_led_brightness()
                self.text_at(170, 70, 62, 16, "%d%%" % (bv * 100 // 255), 1,
                             C.COL_ACCENT, C.COL_BG, "tr", 1, 60)
            if not t.down:
                self._drag = -1
                self.app.save_now()
        elif drag == 4:
            sx, sy, sw, sh = self._sv_geo()
            sat = max(0, min(255, (x - sx) * 255 // (sw - 1)))
            val = max(0, min(255, 255 - (t.y - sy) * 255 // (sh - 1)))
            led = self.cfg["led"]
            seg = self.led_color_seg
            if sat != led["sat"][seg] or val != led["val"][seg]:
                led["sat"][seg], led["val"][seg] = sat, val
                self.draw_sv_marker()
                self.draw_led_color_preview()
            if not t.down:
                self._drag = -1
                self.app.save_now()
        elif drag == 5:
            h = max(0, min(359, int((x - 42) * 359 / 155)))
            led = self.cfg["led"]
            seg = self.led_color_seg
            if h != led["hue"][seg]:
                led["hue"][seg] = h
                # Redrawing the 14,400-pixel square on every sample would
                # stall BLE/touch; update it once when the finger is released.
                self.draw_hue_strip()
                self.draw_sv_marker()
                self.draw_led_color_preview()
            if not t.down:
                self._drag = -1
                self.draw_sv_square(force=True)
                self.draw_sv_marker()
                self.app.save_now()

    def draw_led_color_preview(self):
        led = self.cfg["led"]
        seg = self.led_color_seg
        rgb = C.hsv_rgb(led["hue"][seg], led["sat"][seg], led["val"][seg])
        self.text_at(10, 216, 220, 18, "HEX #%02X%02X%02X" % rgb, 2,
                     C.COL_ACCENT, C.COL_BG, "tl", 1, 160)

    def touch_led(self, t, x, y):
        led = self.cfg["led"]
        if not t.ev_tap:
            return
        if hit(x, y, 8, 40, 58, 26) or hit(x, y, 174, 40, 58, 26):
            led["count"] += -1 if x < 100 else 1
            led["count"] = max(1, min(config.LED_MAX_COUNT, led["count"]))
            while sum(led["segmentCount"]) > led["count"]:
                for i in (2, 1, 0):
                    if led["segmentCount"][i]:
                        led["segmentCount"][i] -= 1
                        break
                else:
                    break
            self.app.apply_led_hardware()
            self.app.save_now()
            self.settings_dirty = True
            return
        if hit(x, y, 8, 120, 108, 26):
            led["pinIndex"] = (led["pinIndex"] + 1) % len(config.LED_PINS)
            self.app.apply_led_hardware()
            self.app.save_now()
            self.settings_dirty = True
        elif hit(x, y, 124, 120, 108, 26):
            led["enabled"] ^= 1
            self.app.apply_led_hardware()
            self.app.save_now()
            self.settings_dirty = True
        elif hit(x, y, 8, 152, 224, 26):
            led["brake"] = (led["brake"] + 1) % 3
            self.app.save_now()
            self.settings_dirty = True
        else:
            start = 0
            for i in range(3):
                row = 184 + i * 44
                if hit(x, y, 14, row + 18, 28, 21) and led["segmentCount"][i] > 0:
                    led["segmentCount"][i] -= 1
                elif hit(x, y, 82, row + 18, 28, 21):
                    if sum(led["segmentCount"]) < led["count"]:
                        led["segmentCount"][i] += 1
                elif hit(x, y, 114, row + 18, 68, 21):
                    self.led_color_seg = i
                    self.enter(SCR_LED_EFFECT)
                    return
                elif hit(x, y, 196, row + 18, 32, 21):
                    self.led_color_seg = i
                    seg = self.cfg["led"]
                    self._led_color_orig = (seg["hue"][i], seg["sat"][i], seg["val"][i])
                    self._sv_last_hue = -1
                    self._sv_marker = None
                    self.enter(SCR_LED_COLOR)
                    return
                else:
                    start += led["segmentCount"][i]
                    continue
                self.app.save_now()
                self.settings_dirty = True
                return
        return

    # --------------------------------------------------------------- button
    def button_press(self, long=False):
        if long:
            self.app.reconnect()
            return
        if self.scr == SCR_MAIN:
            if not self.nb.is_live():
                return
            self.next_page(1)
            self.page_draw()
        else:
            self.go_back()
