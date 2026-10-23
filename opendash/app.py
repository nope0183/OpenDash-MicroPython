'''Application glue: hardware, settings, BLE, LED, OTA and UI loop.'''
import gc
import machine
import time

try:
    from . import colors
    from . import config
    from . import storage
    from .display import Display
    from .touch import Touch
    from .ninebot import Ninebot
    from .led import LedStrip
    from .ota import OtaServer
    from .ui import UI, SCR_MAIN, SCR_SET, SCR_OTA
except ImportError:
    from opendash import colors
    from opendash import config
    from opendash import storage
    from opendash.display import Display
    from opendash.touch import Touch
    from opendash.ninebot import Ninebot
    from opendash.led import LedStrip
    from opendash.ota import OtaServer
    from opendash.ui import UI, SCR_MAIN, SCR_SET, SCR_OTA


class App:
    def __init__(self):
        try:
            machine.freq(240_000_000)
        except Exception:
            pass

        self.cfg = storage.load()
        colors.apply_theme(self.cfg['theme'], self.cfg['accent'], self.cfg['hue'])
        self.d = Display()
        self.d.set_rotation(self.cfg['flip'] * 2)
        self.d.set_backlight(self.cfg['bright'])
        self.touch = Touch()
        # Import/compile garbage and display buffers can leave the heap
        # fragmented; reclaim it before the BLE client allocates its caches.
        gc.collect()
        self.nb = Ninebot()
        self.led = LedStrip()
        self.ota = OtaServer()
        self.ui = UI(self)

        self._last_ui = 0
        self._save_due = 0
        self._btn = machine.Pin(config.BTN_PIN, machine.Pin.IN, machine.Pin.PULL_UP)
        self._btn_down = False
        self._btn_at = 0
        self.last_act = time.ticks_ms()
        self.dimmed = False

        self.apply_led_hardware()
        if self.cfg['ota']:
            if not self.ota.start():
                self.cfg['ota'] = 0
                storage.save(self.cfg)
        if not self.cfg['cal']['valid']:
            self.ui.start_boot_calibration()
        self.ui.tick(time.ticks_ms())

    # ------------------------------------------------------------- settings
    def apply_display(self):
        colors.apply_theme(self.cfg['theme'], self.cfg['accent'], self.cfg['hue'])
        self.d.set_rotation(self.cfg['flip'] * 2)
        self.set_backlight(self.cfg['bright'])
        if hasattr(self, 'ui'):
            self.ui.cfg = self.cfg
            self.ui.cache.clear()
            self.ui.need_static = True
            if self.ui.scr != SCR_MAIN:
                self.ui.settings_dirty = True

    def apply_led_hardware(self):
        led = self.cfg['led']
        self.led.configure(led['pinIndex'], led['count'])
        if not led['enabled']:
            self.led.off()

    def set_backlight(self, percent):
        self.d.set_backlight(percent)

    def save_soon(self):
        self._save_due = time.ticks_add(time.ticks_ms(), 1200)

    def save_now(self):
        self._save_due = 0
        storage.save(self.cfg)

    def reset_defaults(self):
        cal = self.cfg['cal']
        if self.ota.enabled:
            self.ota.stop()
        self.nb.shfw_force = False
        self.nb.shfw_reset(lock=True)
        self.cfg = storage.defaults()
        self.cfg['cal'] = cal
        self.ui.cfg = self.cfg
        self.apply_display()
        self.apply_led_hardware()
        self.save_now()
        self.ui.enter(SCR_SET)

    # ------------------------------------------------------------------ OTA
    def set_ota(self, enabled):
        if enabled:
            if not self.ota.enabled:
                ok = self.ota.start()
                self.cfg['ota'] = 1 if ok else 0
        else:
            self.ota.stop()
            self.cfg['ota'] = 0
        self.save_now()

    # -------------------------------------------------------------- activity
    def mark_activity(self, now=None):
        now = time.ticks_ms() if now is None else now
        self.last_act = now
        if self.dimmed:
            self.dimmed = False
            self.set_backlight(self.cfg['bright'])

    def brake_active(self, now):
        return bool(self.nb.data.brake_until and
                    time.ticks_diff(self.nb.data.brake_until, now) > 0)

    def reconnect(self):
        self.nb.disconnect()
        self.ui.page = 0
        self.ui.clear_cache()
        self.ui.need_static = True

    # ---------------------------------------------------------------- button
    def handle_button(self, now):
        value = self._btn.value()
        if value == 0 and not self._btn_down:
            self._btn_down = True
            self._btn_at = now
            self.mark_activity(now)
        elif value == 1 and self._btn_down:
            self._btn_down = False
            dt = time.ticks_diff(now, self._btn_at)
            if dt >= 1500:
                self.ui.button_press(long=True)
            elif dt >= 40:
                self.ui.button_press(long=False)

    # ------------------------------------------------------------ housekeeping
    def housekeeping(self, now):
        if self._save_due and time.ticks_diff(now, self._save_due) >= 0:
            self._save_due = 0
            storage.save(self.cfg)

        data = self.nb.data
        if self.nb.is_live() and data.has(0):
            if data.speed > data.session_max:
                data.session_max = data.speed
            if data.speed > 1.0:
                self.mark_activity(now)

        if self.cfg['dim'] and not self.dimmed:
            limit = config.DIM_SEC[self.cfg['dim']] * 1000
            if limit and time.ticks_diff(now, self.last_act) > limit:
                self.dimmed = True
                self.set_backlight(max(5, self.cfg['bright'] // 6))

    # ------------------------------------------------------------------- loop
    def run(self):
        while True:
            now = time.ticks_ms()
            if self.touch.poll(self.cfg, self.dimmed, now) or self.touch.down:
                self.mark_activity(now)
            self.ui.handle_touch()
            self.handle_button(now)
            self.nb.poll(now)
            self.led.update(now, self.cfg['led'], self.brake_active(now))
            if self.ota.enabled:
                self.ota.poll()
            self.housekeeping(now)
            if time.ticks_diff(now, self._last_ui) >= 90:
                self._last_ui = now
                self.ui.tick(now)
            time.sleep_ms(3)
