"""WS2812B strip with the twelve OpenDash effects."""
import machine
import math
import time

try:
    from . import config
    from .colors import hsv_rgb
except ImportError:
    from opendash import config
    from opendash.colors import hsv_rgb

LED_OFF, LED_SOLID, LED_PULSE, LED_RAINBOW, LED_BLINK, LED_BREATH = range(6)
LED_CHASE, LED_COMET, LED_TWINKLE, LED_GRADIENT, LED_BOUNCE, LED_FILL = range(6, 12)


def _scale(rgb, level, bright):
    if level <= 0:
        return (0, 0, 0)
    if level > 1:
        level = 1
    k = level * bright / 255.0
    return (int(rgb[0] * k), int(rgb[1] * k), int(rgb[2] * k))


def _hash(x):
    x &= 0xFFFFFFFF
    x ^= x >> 16
    x = (x * 0x7FEB352D) & 0xFFFFFFFF
    x ^= x >> 15
    x = (x * 0x846CA68B) & 0xFFFFFFFF
    x ^= x >> 16
    return x


class LedStrip:
    def __init__(self):
        self.np = None
        self.pin = None
        self.count = 0
        self.last = 0
        self.was_lit = False
        self._neopixel = None
        module = None
        try:
            import neopixel
            module = neopixel
        except ImportError:
            pass
        self._module = module

    def configure(self, pin_index, count):
        pin = config.LED_PINS[pin_index]
        if self.np is not None and self.pin == pin and self.count == count:
            return
        if self.np is not None:
            # The old object cannot control the new pin/count; make sure its
            # physical LEDs are cleared before dropping the reference.
            self.off()
        if self._module is None:
            self.np = None
            return
        try:
            self.np = self._module.NeoPixel(machine.Pin(pin), count, bpp=3)
            self.pin = pin
            self.count = count
        except Exception as exc:
            print("led init:", exc)
            self.np = None

    def off(self):
        if self.np is not None:
            try:
                for i in range(self.count):
                    self.np[i] = (0, 0, 0)
                self.np.write()
            except Exception:
                pass
        self.was_lit = False

    def update(self, now, led, braking):
        if self.np is None:
            return
        if not led["enabled"]:
            if self.was_lit:
                self.off()
            return
        if time.ticks_diff(now, self.last) < 40:
            return
        self.last = now
        self.was_lit = True

        count = self.count
        bright = led["bright"]
        brake_mode = led["brake"]
        brake_all = braking and brake_mode == 1
        brake_seg = -1
        if braking and brake_mode == 2:
            for i in (2, 1, 0):
                if led["segmentCount"][i]:
                    brake_seg = i
                    break

        start = 0
        # Clear the whole strip: segment sizes can shrink, and LEDs beyond the
        # configured segments must not keep the previous frame.
        for p in range(count):
            self.np[p] = (0, 0, 0)
        for seg in range(3):
            length = led["segmentCount"][seg]
            if length <= 0:
                continue
            end = start + length
            if end > count:
                end = count
            if start >= count:
                break
            self._segment(seg, start, end, now, led,
                          brake_all or seg == brake_seg)
            start += length
        try:
            self.np.write()
        except Exception:
            pass

    # ---------------------------------------------------------------- effects
    def _segment(self, seg, start, end, now, led, brake):
        length = end - start
        if length <= 0:
            return
        effect = led["effect"][seg]
        hue = led["hue"][seg]
        sat = led["sat"][seg]
        val = led["val"][seg]
        bright = led["bright"]
        base = hsv_rgb(hue, sat, val)
        t = now + seg * 137
        if brake:
            for p in range(start, end):
                self.np[p] = (bright, 0, 0)
            return

        np = self.np
        if effect == LED_SOLID:
            c = _scale(base, 1.0, bright)
            for p in range(start, end):
                np[p] = c
        elif effect == LED_PULSE:
            phase = (math.sin(now * 0.004) + 1.0) * 0.5
            c = _scale(base, 0.12 + phase * 0.88, bright)
            for p in range(start, end):
                np[p] = c
        elif effect == LED_RAINBOW:
            head = now * 66 // 1000       # matches hue = now*12 in 16-bit
            for i, p in enumerate(range(start, end)):
                np[p] = _scale(hsv_rgb((head + i * 360 // max(1, led["count"])) % 360,
                                       255, 255), 1.0, bright)
        elif effect == LED_BLINK:
            c = (0, 0, 0) if (t // 250) & 1 else _scale(base, 1.0, bright)
            for p in range(start, end):
                np[p] = c
        elif effect == LED_BREATH:
            u = (t % 4000) / 4000.0
            tri = u * 2.0 if u < 0.5 else (1.0 - u) * 2.0
            s = tri * tri * (3.0 - 2.0 * tri)
            c = _scale(base, 0.05 + s * 0.95, bright)
            for p in range(start, end):
                np[p] = c
        elif effect == LED_CHASE:
            pos = (t // 70) % length
            for i in range(length):
                d = (i + length - pos) % length
                level = 1.0 - d / 8.0 if d < 8 else 0.0
                np[start + i] = _scale(base, level, bright)
        elif effect == LED_COMET:
            pos = (t // 55) % length
            for i in range(length):
                d = (i + length - pos) % length
                x = 1.0 - d / 24.0 if d < 24 else 0.0
                np[start + i] = _scale(base, x * x, bright)
        elif effect == LED_TWINKLE:
            tick = t // 90
            for i in range(length):
                seed = _hash((i + 1) * 2654435761)
                period = 6 + seed % 18
                phase = (tick + ((seed >> 8) % period)) % period
                level = 1.0 if phase == 0 else 0.45 if phase == 1 else 0.12 if phase == 2 else 0.0
                np[start + i] = _scale(base, level, bright)
        elif effect == LED_GRADIENT:
            for i in range(length):
                h2 = (hue + i * 120 // length) % 360
                np[start + i] = _scale(hsv_rgb(h2, sat, val), 1.0, bright)
        elif effect == LED_BOUNCE:
            if length <= 1:
                pos = 0
            else:
                period = (length - 1) * 2
                step = (t // 70) % (period + 1)
                pos = step if step <= length - 1 else period - step
            for i in range(length):
                np[start + i] = _scale(base, 1.0 if i == pos else 0.0, bright)
        elif effect == LED_FILL:
            step = (t // 60) % (length * 2)
            filled = step if step < length else length * 2 - step
            for i in range(length):
                level = 1.0 if i < filled else 0.45 if i == filled else 0.0
                np[start + i] = _scale(base, level, bright)
        else:
            for p in range(start, end):
                np[p] = (0, 0, 0)
