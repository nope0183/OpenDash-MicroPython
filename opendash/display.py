"""Minimal ST7789 / ILI9341 driver plus a small RGB565 canvas.

The CYD has no PSRAM, so a full 240x320 framebuffer is not practical.
Static elements are drawn straight to the panel and small dynamic areas are
composited in a reusable ``Canvas`` and blitted with one SPI write.
"""
import framebuf
import machine
import time

try:
    from . import config
    from .colors import swap
    from .fonts import FONTS
except ImportError:
    from opendash import config
    from opendash.colors import swap
    from opendash.fonts import FONTS


class Display:
    def __init__(self, driver=None):
        self.driver = (driver or config.DISPLAY_DRIVER).lower()
        self.width = config.TFT_WIDTH
        self.height = config.TFT_HEIGHT
        self.spi = machine.SPI(
            config.TFT_SPI_ID,
            baudrate=config.TFT_BAUD,
            polarity=0,
            phase=0,
            sck=machine.Pin(config.TFT_SCLK),
            mosi=machine.Pin(config.TFT_MOSI),
            miso=machine.Pin(config.TFT_MISO),
        )
        self.cs = machine.Pin(config.TFT_CS, machine.Pin.OUT, value=1)
        self.dc = machine.Pin(config.TFT_DC, machine.Pin.OUT, value=1)
        if config.TFT_RST is not None:
            self.rst = machine.Pin(config.TFT_RST, machine.Pin.OUT, value=1)
        else:
            self.rst = None
        try:
            self.bl = machine.PWM(machine.Pin(config.TFT_BL), freq=5000)
            self._bl_pct = -1
        except Exception:
            self.bl = None
        self._rotation = 0
        self._init_panel()

    # ------------------------------------------------------------ low level
    def _cmd(self, cmd, data=None):
        self.cs.value(0)
        self.dc.value(0)
        self.spi.write(bytes((cmd,)))
        if data:
            self.dc.value(1)
            self.spi.write(data)
        self.cs.value(1)

    def _begin_data(self):
        self.cs.value(0)
        self.dc.value(1)

    def _end_data(self):
        self.cs.value(1)

    def _init_panel(self):
        if self.rst is not None:
            self.rst.value(1)
            time.sleep_ms(20)
            self.rst.value(0)
            time.sleep_ms(20)
            self.rst.value(1)
            time.sleep_ms(120)
        if self.driver == "ili9341":
            self._init_ili9341()
        else:
            self._init_st7789()
        self.set_rotation(0)

    def _init_st7789(self):
        c = self._cmd
        c(0x01)                       # software reset
        time.sleep_ms(150)
        c(0x11)                       # sleep out
        time.sleep_ms(120)
        c(0x3A, b"\x55")              # 16 bit colour
        c(0x36, b"\x08")              # BGR, portrait
        c(0xB2, b"\x0C\x0C\x00\x33\x33")
        c(0xB7, b"\x35")
        c(0xBB, b"\x19")
        c(0xC0, b"\x2C")
        c(0xC2, b"\x01")
        c(0xC3, b"\x12")
        c(0xC4, b"\x20")
        c(0xC6, b"\x0F")
        c(0xD0, b"\xA4\xA1")
        c(0xE0, b"\xD0\x04\x0D\x11\x13\x2B\x3F\x54\x4C\x18\x0D\x0B\x1F\x23")
        c(0xE1, b"\xD0\x04\x0C\x11\x13\x2C\x3F\x44\x51\x2F\x1F\x1F\x20\x23")
        c(0x21)                       # inversion on (CYD panel)
        c(0x13)                       # normal display
        c(0x29)                       # display on
        time.sleep_ms(50)

    def _init_ili9341(self):
        c = self._cmd
        c(0x01)
        time.sleep_ms(120)
        c(0xCB, b"\x39\x2C\x00\x34\x02")
        c(0xCF, b"\x00\xC1\x30")
        c(0xE8, b"\x85\x00\x78")
        c(0xEA, b"\x00\x00")
        c(0xED, b"\x64\x03\x12\x81")
        c(0xF7, b"\x20")
        c(0xC0, b"\x23")
        c(0xC1, b"\x10")
        c(0xC5, b"\x3E\x28")
        c(0xC7, b"\x86")
        c(0x36, b"\x48")
        c(0x37, b"\x00")
        c(0x3A, b"\x55")
        c(0xB1, b"\x00\x18")
        c(0xB6, b"\x08\x82\x27")
        c(0xF2, b"\x00")
        c(0x26, b"\x01")
        c(0xE0, b"\x0F\x31\x2B\x0C\x0E\x08\x4E\xF1\x37\x07\x10\x03\x0E\x09\x00")
        c(0xE1, b"\x00\x0E\x14\x03\x11\x07\x31\xC1\x48\x08\x0F\x0C\x31\x36\x0F")
        c(0x11)
        time.sleep_ms(120)
        c(0x29)
        time.sleep_ms(50)

    def set_rotation(self, rotation):
        self._rotation = 2 if rotation == 2 else 0
        if self.driver == "ili9341":
            madctl = 0xE8 if self._rotation else 0x48
        else:
            madctl = 0xC8 if self._rotation else 0x08
        self._cmd(0x36, bytes((madctl,)))

    def set_backlight(self, percent):
        percent = max(1, min(100, int(percent)))
        if self.bl is None or percent == self._bl_pct:
            self._bl_pct = percent
            return
        self._bl_pct = percent
        try:
            self.bl.duty_u16(percent * 65535 // 100)
        except AttributeError:
            self.bl.duty(percent * 1023 // 100)

    def set_window(self, x, y, w, h):
        x2 = x + w - 1
        y2 = y + h - 1
        self._cmd(0x2A, bytes((x >> 8, x & 0xFF, x2 >> 8, x2 & 0xFF)))
        self._cmd(0x2B, bytes((y >> 8, y & 0xFF, y2 >> 8, y2 & 0xFF)))
        self._cmd(0x2C)

    # ------------------------------------------------------------ primitives
    def fill_rect(self, x, y, w, h, color):
        if w <= 0 or h <= 0:
            return
        if x < 0:
            w += x
            x = 0
        if y < 0:
            h += y
            y = 0
        if x + w > self.width:
            w = self.width - x
        if y + h > self.height:
            h = self.height - y
        if w <= 0 or h <= 0:
            return
        self.set_window(x, y, w, h)
        row = bytes((color >> 8, color & 0xFF)) * w
        per = max(1, 4096 // (w * 2))
        self._begin_data()
        while h > 0:
            n = h if h < per else per
            self.spi.write(row * n)
            h -= n
        self._end_data()

    def fill(self, color):
        self.fill_rect(0, 0, self.width, self.height, color)

    def pixel(self, x, y, color):
        self.fill_rect(x, y, 1, 1, color)

    def hline(self, x, y, w, color):
        self.fill_rect(x, y, w, 1, color)

    def vline(self, x, y, h, color):
        self.fill_rect(x, y, 1, h, color)

    def line(self, x0, y0, x1, y1, color):
        dx = abs(x1 - x0)
        dy = -abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx + dy
        while True:
            self.pixel(x0, y0, color)
            if x0 == x1 and y0 == y1:
                break
            e2 = 2 * err
            if e2 >= dy:
                err += dy
                x0 += sx
            if e2 <= dx:
                err += dx
                y0 += sy

    def fill_circle(self, cx, cy, r, color):
        x = r
        y = 0
        err = 1 - r
        while x >= y:
            self.hline(cx - x, cy + y, 2 * x + 1, color)
            self.hline(cx - x, cy - y, 2 * x + 1, color)
            self.hline(cx - y, cy + x, 2 * y + 1, color)
            self.hline(cx - y, cy - x, 2 * y + 1, color)
            y += 1
            if err < 0:
                err += 2 * y + 1
            else:
                x -= 1
                err += 2 * (y - x) + 1

    def circle(self, cx, cy, r, color):
        for x in range(-r, r + 1):
            yy = int((r * r - x * x) ** 0.5)
            self.pixel(cx + x, cy + yy, color)
            self.pixel(cx + x, cy - yy, color)

    def fill_round_rect(self, x, y, w, h, r, color):
        if r <= 0:
            self.fill_rect(x, y, w, h, color)
            return
        if r > w // 2:
            r = w // 2
        if r > h // 2:
            r = h // 2
        self.fill_rect(x + r, y, w - 2 * r, h, color)
        self.fill_rect(x, y + r, r, h - 2 * r, color)
        self.fill_rect(x + w - r, y + r, r, h - 2 * r, color)
        self.fill_circle(x + r, y + r, r, color)
        self.fill_circle(x + w - r - 1, y + r, r, color)
        self.fill_circle(x + r, y + h - r - 1, r, color)
        self.fill_circle(x + w - r - 1, y + h - r - 1, r, color)

    def fill_triangle(self, x0, y0, x1, y1, x2, y2, color):
        if y0 > y1:
            x0, y0, x1, y1 = x1, y1, x0, y0
        if y1 > y2:
            x1, y1, x2, y2 = x2, y2, x1, y1
        if y0 > y1:
            x0, y0, x1, y1 = x1, y1, x0, y0

        def interp(xa, ya, xb, yb, y):
            if yb == ya:
                return xa
            return xa + (xb - xa) * (y - ya) // (yb - ya)

        for y in range(y0, y1 + 1):
            xa = interp(x0, y0, x2, y2, y)
            xb = interp(x0, y0, x1, y1, y)
            if xa > xb:
                xa, xb = xb, xa
            self.hline(xa, y, xb - xa + 1, color)
        for y in range(y1 + 1, y2 + 1):
            xa = interp(x0, y0, x2, y2, y)
            xb = interp(x1, y1, x2, y2, y)
            if xa > xb:
                xa, xb = xb, xa
            self.hline(xa, y, xb - xa + 1, color)

    def blit(self, x, y, w, h, buf):
        if x < 0 or y < 0 or w <= 0 or h <= 0:
            return
        if x + w > self.width:
            w = self.width - x
        if y + h > self.height:
            h = self.height - y
        self.set_window(x, y, w, h)
        self._begin_data()
        total = w * h * 2
        pos = 0
        step = 4096
        while pos < total:
            self.spi.write(buf[pos:pos + step])
            pos += step
        self._end_data()

    def blit_sub(self, src, sx, sy, w, h, dx, dy):
        """Copy a rectangle from a Canvas to the panel."""
        if w <= 0 or h <= 0:
            return
        if sx < 0:
            dx -= sx
            w += sx
            sx = 0
        if sy < 0:
            dy -= sy
            h += sy
            sy = 0
        if sx + w > src.w:
            w = src.w - sx
        if sy + h > src.h:
            h = src.h - sy
        if dx < 0:
            sx -= dx
            w += dx
            dx = 0
        if dy < 0:
            sy -= dy
            h += dy
            dy = 0
        if dx + w > self.width:
            w = self.width - dx
        if dy + h > self.height:
            h = self.height - dy
        if w <= 0 or h <= 0:
            return
        self.set_window(dx, dy, w, h)
        self._begin_data()
        stride = src.w * 2
        off = (sy * src.w + sx) * 2
        for _ in range(h):
            self.spi.write(src.buf[off:off + w * 2])
            off += stride
        self._end_data()


class Canvas:
    """Small RGB565 drawing surface.

    Colours passed to the methods are normal RGB565 values; the canvas
    byte-swaps them internally so its raw buffer can be sent to the panel.
    """

    def __init__(self, w, h):
        self.w = w
        self.h = h
        self.buf = bytearray(w * h * 2)
        self.fb = framebuf.FrameBuffer(self.buf, w, h, framebuf.RGB565)

    def fill(self, color):
        self.fb.fill(swap(color))

    def fill_rect(self, x, y, w, h, color):
        self.fb.fill_rect(x, y, w, h, swap(color))

    def rect(self, x, y, w, h, color):
        self.fb.rect(x, y, w, h, swap(color))

    def pixel(self, x, y, color):
        self.fb.pixel(x, y, swap(color))

    def line(self, x0, y0, x1, y1, color):
        self.fb.line(x0, y0, x1, y1, swap(color))

    # -------------------------------------------------------------- text
    @staticmethod
    def text_width(s, font_id=1, scale=1):
        if not s:
            return 0
        f = FONTS.get(font_id) or FONTS[1]
        glyphs = f[1]
        total = 0
        for ch in s:
            g = glyphs.get(ord(ch))
            total += (g[3] if g else (glyphs[63][3] if 63 in glyphs else 4))
        return total * scale

    @classmethod
    def text_height(cls, font_id=1, scale=1):
        f = FONTS.get(font_id) or FONTS[1]
        return (f[3] + f[4]) * scale

    def _draw_glyphs(self, s, x, baseline, font_id, color, scale):
        f = FONTS.get(font_id) or FONTS[1]
        bitmap, glyphs, _yadv, _asc, _desc = f
        col = swap(color)
        pen = x
        fallback = glyphs.get(63)
        for ch in s:
            g = glyphs.get(ord(ch), fallback)
            if not g:
                pen += 4 * scale
                continue
            off, w, h, xadv, xoff, yoff = g
            gx = pen + xoff * scale
            gy = baseline + yoff * scale
            stride = (w + 7) // 8
            for row in range(h):
                bit_base = (off + row * stride) * 8
                c = 0
                while c < w:
                    byte = bitmap[(bit_base + c) >> 3]
                    if not ((byte >> (7 - (c & 7))) & 1):
                        c += 1
                        continue
                    start = c
                    c += 1
                    while c < w:
                        byte2 = bitmap[(bit_base + c) >> 3]
                        if not ((byte2 >> (7 - (c & 7))) & 1):
                            break
                        c += 1
                    self.fb.fill_rect(gx + start * scale, gy + row * scale,
                                      (c - start) * scale, scale, col)
            pen += xadv * scale

    def text(self, s, x, y, font_id=1, color=0xFFFF, bg=None, scale=1,
             maxw=None, anchor="tl", padding=0):
        """Draw text.

        ``anchor`` uses the usual two-letter form: t/m/b + l/c/r.
        ``y`` is the top of the text box for t-anchors, the middle for m and
        the bottom for b.
        """
        s = str(s)
        if maxw is not None and maxw > 0:
            full = self.text_width(s, font_id, scale)
            if full > maxw:
                tail = ".."
                while s and self.text_width(s + tail, font_id, scale) > maxw:
                    s = s[:-1]
                s += tail
        f = FONTS.get(font_id) or FONTS[1]
        ascent, descent = f[3], f[4]
        th = (ascent + descent) * scale
        tw = self.text_width(s, font_id, scale)
        if anchor[1] == "c":
            x -= tw // 2
        elif anchor[1] == "r":
            x -= tw
        if anchor[0] == "m":
            y -= th // 2
        elif anchor[0] == "b":
            y -= th
        if bg is not None:
            self.fb.fill_rect(x - padding, y - padding,
                              tw + 2 * padding, th + 2 * padding, swap(bg))
        self._draw_glyphs(s, x, y + ascent * scale, font_id, color, scale)
        return tw

    def push(self, display, x, y):
        display.blit(x, y, self.w, self.h, self.buf)
