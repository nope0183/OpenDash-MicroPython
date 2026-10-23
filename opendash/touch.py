"""XPT2046 touch controller and gesture recognition."""
import machine
import time

try:
    from . import config
except ImportError:
    from opendash import config

CAL_M = 20
LONG_MS = 650
# Top-left, top-right and bottom-left: the affine calibration assumes exactly
# this order (same as the original OpenDash).
CAL_POINTS = ((20, 20), (219, 20), (20, 299))
TOUCH_PRESSURE = 350


class Touch:
    def __init__(self):
        self.spi = machine.SPI(
            config.TOUCH_SPI_ID,
            baudrate=config.TOUCH_BAUD,
            polarity=0,
            phase=0,
            sck=machine.Pin(config.TOUCH_SCLK),
            mosi=machine.Pin(config.TOUCH_MOSI),
            miso=machine.Pin(config.TOUCH_MISO),
        )
        self.cs = machine.Pin(config.TOUCH_CS, machine.Pin.OUT, value=1)
        try:
            self.irq = machine.Pin(config.TOUCH_IRQ, machine.Pin.IN)
        except Exception:
            self.irq = None
        self._last = 0
        self.reset()

    def reset(self):
        self.down = False
        self.moved = False
        self.long_done = False
        self.swallow = False
        self.x = self.y = 0
        self.sx = self.sy = 0
        self.t0 = 0
        self.last_seen = 0
        self.swipe = 0
        self.ev_down = self.ev_tap = self.ev_long = self.ev_up = False
        self.rx_sum = self.ry_sum = 0
        self.rn = 0

    def _read(self, cmd):
        self.cs.value(0)
        self.spi.write(bytes((cmd,)))
        data = self.spi.read(2)
        self.cs.value(1)
        return ((data[0] << 8) | data[1]) >> 3

    def _sample(self):
        # one dummy conversion settles the ADC after power-up
        z = self._read(0xB0)
        if z < TOUCH_PRESSURE:
            return None
        x = self._read(0xD0)
        y = self._read(0x90)
        z = self._read(0xB0)
        if z < TOUCH_PRESSURE:
            return None
        return x, y, z

    @staticmethod
    def map_raw(rx, ry, cfg):
        cal = cfg["cal"]
        a = ry if cal["swap"] else rx
        b = rx if cal["swap"] else ry
        sx = CAL_M + int((a - cal["x0"]) * cal["xk"])
        sy = CAL_M + int((b - cal["y0"]) * cal["yk"])
        sx = 0 if sx < 0 else 239 if sx > 239 else sx
        sy = 0 if sy < 0 else 319 if sy > 319 else sy
        if cal["flip"] != cfg["flip"]:
            sx = 239 - sx
            sy = 319 - sy
        return sx, sy

    def poll(self, cfg, dimmed=False, now=None):
        """Update state. Returns True when a new touch just started."""
        now = time.ticks_ms() if now is None else now
        self.ev_down = self.ev_tap = self.ev_long = self.ev_up = False
        self.swipe = 0
        sample = self._sample()
        activity = False
        if sample is not None:
            rx, ry, _z = sample
            self.last_seen = now
            sx, sy = self.map_raw(rx, ry, cfg)
            if not self.down:
                self.down = True
                self.moved = False
                self.long_done = False
                self.swallow = dimmed
                self.x = self.sx = sx
                self.y = self.sy = sy
                self.t0 = now
                self.rx_sum = 0
                self.ry_sum = 0
                self.rn = 0
                self.ev_down = not self.swallow
                activity = True
            else:
                self.x = (self.x + sx) // 2
                self.y = (self.y + sy) // 2
            if self.rn < 200:
                self.rx_sum += rx
                self.ry_sum += ry
                self.rn += 1
            if not self.moved and (abs(self.x - self.sx) > 14 or abs(self.y - self.sy) > 14):
                self.moved = True
            if (not self.swallow and not self.moved and not self.long_done
                    and time.ticks_diff(now, self.t0) > LONG_MS):
                self.long_done = True
                self.ev_long = True
        elif self.down and time.ticks_diff(now, self.last_seen) > 45:
            self.down = False
            if not self.swallow:
                self.ev_up = True
                if not self.moved and not self.long_done:
                    self.ev_tap = True
                elif self.moved:
                    dx = self.x - self.sx
                    dy = self.y - self.sy
                    if abs(dx) >= 40 and abs(dx) * 2 > abs(dy) * 3:
                        self.swipe = 1 if dx < 0 else -1
        return activity

    def raw_avg(self):
        if not self.rn:
            return None
        return self.rx_sum / self.rn, self.ry_sum / self.rn

    @staticmethod
    def finish_calibration(cfg, raw):
        """`raw` = three (x, y) averages; returns True on success."""
        x0r, y0r = raw[0]
        x1r, y1r = raw[1]
        x2r, y2r = raw[2]
        swap = abs(y1r - y0r) > abs(x1r - x0r)
        ax0 = y0r if swap else x0r
        ax1 = y1r if swap else x1r
        ay0 = x0r if swap else y0r
        ay1 = x2r if swap else y2r
        if abs(ax1 - ax0) < 300 or abs(ay1 - ay0) < 300:
            return False
        cal = cfg["cal"]
        cal["swap"] = 1 if swap else 0
        cal["x0"] = ax0
        cal["xk"] = (239 - 2 * CAL_M) / (ax1 - ax0)
        cal["y0"] = ay0
        cal["yk"] = (319 - 2 * CAL_M) / (ay1 - ay0)
        cal["flip"] = cfg["flip"]
        cal["valid"] = 1
        return True
