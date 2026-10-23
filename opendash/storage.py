"""Persistent settings (JSON file on the internal filesystem)."""
import json
import os

try:
    from . import config
except ImportError:          # running from the repository root
    from opendash import config


def _copy(value):
    if isinstance(value, dict):
        return {k: _copy(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_copy(v) for v in value]
    return value


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _merge(defaults, data):
    """Merge loaded JSON into the defaults, keeping the default types."""
    out = _copy(defaults)
    if not isinstance(data, dict):
        return out
    for key, default in defaults.items():
        value = data.get(key)
        if isinstance(default, dict):
            if isinstance(value, dict):
                out[key] = _merge(default, value)
        elif isinstance(default, list):
            if (isinstance(value, list) and len(value) == len(default)
                    and all(_num(v) for v in value)):
                out[key] = [_copy(v) for v in value]
        elif isinstance(default, int):
            if isinstance(value, int) and not isinstance(value, bool):
                out[key] = value
        elif isinstance(default, float):
            if _num(value):
                out[key] = float(value)
        elif isinstance(default, str):
            if isinstance(value, str):
                out[key] = value
    return out


def _clamp(value, low, high):
    return low if value < low else high if value > high else value


def _validate(cfg):
    cfg["theme"] = int(_clamp(cfg["theme"], 0, 3))
    cfg["accent"] = int(_clamp(cfg["accent"], 0, 8))
    cfg["style"] = int(_clamp(cfg["style"], 0, 2))
    cfg["units"] = int(_clamp(cfg["units"], 0, 1))
    cfg["bright"] = int(_clamp(cfg["bright"], 10, 100))
    cfg["dim"] = int(_clamp(cfg["dim"], 0, 3))
    cfg["flip"] = int(_clamp(cfg["flip"], 0, 1))
    cfg["lock"] = int(_clamp(cfg["lock"], 0, 1))
    cfg["showInfo"] = int(_clamp(cfg["showInfo"], 0, 1))
    cfg["showDebug"] = int(_clamp(cfg["showDebug"], 0, 1))
    cfg["lang"] = int(_clamp(cfg["lang"], 0, 1))
    cfg["ota"] = int(_clamp(cfg["ota"], 0, 1))
    cfg["hue"] = int(_clamp(cfg["hue"], 0, 359))
    cfg["gmaxKmh"] = int(_clamp(cfg["gmaxKmh"], 10, 60))
    cfg["gmaxMph"] = int(_clamp(cfg["gmaxMph"], 5, 40))
    cfg["card"] = [int(_clamp(v, 0, config.M_COUNT - 1)) for v in cfg["card"]]

    cal = cfg["cal"]
    cal["valid"] = int(_clamp(cal["valid"], 0, 1))
    cal["swap"] = int(_clamp(cal["swap"], 0, 1))
    cal["flip"] = int(_clamp(cal["flip"], 0, 1))
    for key in ("x0", "xk", "y0", "yk"):
        if cal[key] == 0 and key.endswith("k"):
            cal[key] = 1.0
        cal[key] = float(cal[key])

    led = cfg["led"]
    led["enabled"] = int(_clamp(led["enabled"], 0, 1))
    led["pinIndex"] = int(_clamp(led["pinIndex"], 0, len(config.LED_PINS) - 1))
    led["count"] = int(_clamp(led["count"], 1, config.LED_MAX_COUNT))
    led["bright"] = int(_clamp(led["bright"], 1, 255))
    led["brake"] = int(_clamp(led["brake"], 0, 2))
    led["segmentCount"] = [int(_clamp(v, 0, config.LED_MAX_COUNT)) for v in led["segmentCount"]]
    led["effect"] = [int(_clamp(v, 0, 11)) for v in led["effect"]]
    led["hue"] = [int(_clamp(v, 0, 359)) for v in led["hue"]]
    led["sat"] = [int(_clamp(v, 0, 255)) for v in led["sat"]]
    led["val"] = [int(_clamp(v, 0, 255)) for v in led["val"]]
    while sum(led["segmentCount"]) > led["count"]:
        for i in (2, 1, 0):
            if led["segmentCount"][i]:
                led["segmentCount"][i] -= 1
                break
        else:
            break
    return cfg


def load():
    try:
        with open(config.SETTINGS_FILE, "r") as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = {}
    return _validate(_merge(config.DEFAULT_SETTINGS, data))


def defaults():
    return _validate(_copy(config.DEFAULT_SETTINGS))


def save(cfg):
    tmp = config.SETTINGS_FILE + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(cfg, f)
        # LittleFS rename atomically replaces the destination; never remove
        # the old file first, otherwise a power loss can lose the settings.
        try:
            os.sync()
        except AttributeError:
            pass
        os.rename(tmp, config.SETTINGS_FILE)
        try:
            os.sync()
        except AttributeError:
            pass
        return True
    except OSError as exc:
        try:
            os.remove(tmp)
        except OSError:
            pass
        print("settings save failed:", exc)
        return False
