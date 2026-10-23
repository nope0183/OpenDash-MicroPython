"""Small, atomic SHFW backup files on the internal LittleFS.

Each dump is 134 bytes and each profile 118 bytes, so a short JSON record is
cheap to parse and easy to inspect.  The SHFW version and a CRC are stored with
every record: restoring a backup made by another firmware version is refused.
"""
import binascii
import json
import os

try:
    from . import shfw
except ImportError:
    from opendash import shfw

DUMP_SLOTS = 3          # user-visible copies
UNDO_SLOT = 3           # automatic copy before a dump restore
PROFILE_SLOTS = 4       # profiles 1..3 plus the automatic undo copy


def _name(kind, slot):
    return "/shfw_%s_%d.json" % (kind, slot)


def _load(kind, slot):
    try:
        with open(_name(kind, slot), "r") as fh:
            rec = json.load(fh)
        return rec if isinstance(rec, dict) else None
    except (OSError, ValueError):
        return None


def _save(kind, slot, rec):
    path = _name(kind, slot)
    tmp = path + ".tmp"
    try:
        with open(tmp, "w") as fh:
            json.dump(rec, fh)
        try:
            os.sync()
        except AttributeError:
            pass
        os.rename(tmp, path)
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
        print("shfw save failed:", exc)
        return False


def _dump_crc(ver, data):
    return shfw.crc16(data, shfw.crc16(ver))


def save_dump(slot, ver, data):
    if not 0 <= slot < PROFILE_SLOTS or not ver or len(ver) > shfw.VER_MAX:
        return False
    if len(data) != shfw.DUMP_BYTES:
        return False
    ver = bytes(ver)
    data = bytes(data)
    rec = {
        "fmt": 1,
        "table": shfw.TABLE_ID,
        "ver": binascii.hexlify(ver).decode(),
        "data": binascii.hexlify(data).decode(),
        "crc": _dump_crc(ver, data),
    }
    return _save("bak", slot, rec)


def load_dump(slot):
    """Return (state, record): state 1=valid, 0=empty, -1=damaged."""
    rec = _load("bak", slot)
    if rec is None:
        return 0, None
    try:
        if rec.get("fmt") != 1 or rec.get("table") != shfw.TABLE_ID:
            return -1, None
        ver = binascii.unhexlify(rec["ver"].encode())
        data = binascii.unhexlify(rec["data"].encode())
        if not 1 <= len(ver) <= shfw.VER_MAX or len(data) != shfw.DUMP_BYTES:
            return -1, None
        if rec.get("crc") != _dump_crc(ver, data):
            return -1, None
        return 1, {"ver": ver, "data": data}
    except (KeyError, TypeError, ValueError):
        return -1, None


def dump_slots():
    out = []
    for i in range(DUMP_SLOTS):
        state, rec = load_dump(i)
        out.append((state, rec["ver"] if rec else b""))
    return out


def _profile_crc(ver, data, ok):
    crc = shfw.crc16(ver)
    crc = shfw.crc16(data, crc)
    return shfw.crc16(ok, crc)


def save_profile(slot, profile, ver, data, ok):
    if not 0 <= slot < PROFILE_SLOTS or not 1 <= profile <= 3:
        return False
    if not ver or len(ver) > shfw.VER_MAX:
        return False
    if len(data) != shfw.PROFILE_BYTES or len(ok) != shfw.PROFILE_WORDS:
        return False
    ver = bytes(ver)
    data = bytes(data)
    mask = bytearray(8)
    for i, value in enumerate(ok):
        if value:
            mask[i >> 3] |= 1 << (i & 7)
    rec = {
        "fmt": 1,
        "layout": shfw.PROFILE_LAYOUT,
        "profile": profile,
        "words": shfw.PROFILE_WORDS,
        "ver": binascii.hexlify(ver).decode(),
        "data": binascii.hexlify(data).decode(),
        "ok": binascii.hexlify(mask).decode(),
        "crc": _profile_crc(ver, data, mask),
    }
    return _save("prof", slot, rec)


def load_profile(slot):
    """Return (state, record); a manual slot must contain its own profile."""
    rec = _load("prof", slot)
    if rec is None:
        return 0, None
    try:
        profile = rec["profile"]
        if (rec.get("fmt") != 1 or rec.get("layout") != shfw.PROFILE_LAYOUT
                or rec.get("words") != shfw.PROFILE_WORDS
                or not 1 <= profile <= 3 or (slot < 3 and profile != slot + 1)):
            return -1, None
        ver = binascii.unhexlify(rec["ver"].encode())
        data = binascii.unhexlify(rec["data"].encode())
        mask = binascii.unhexlify(rec["ok"].encode())
        if not 1 <= len(ver) <= shfw.VER_MAX:
            return -1, None
        if len(data) != shfw.PROFILE_BYTES or len(mask) != 8:
            return -1, None
        if rec.get("crc") != _profile_crc(ver, data, mask):
            return -1, None
        ok = bytearray(shfw.PROFILE_WORDS)
        for i in range(shfw.PROFILE_WORDS):
            if (mask[i >> 3] >> (i & 7)) & 1:
                ok[i] = 1
        return 1, {"profile": profile, "ver": ver, "data": data, "ok": ok}
    except (KeyError, TypeError, ValueError):
        return -1, None


def profile_slots():
    out = []
    for i in range(PROFILE_SLOTS):
        state, rec = load_profile(i)
        out.append((state,
                    rec["profile"] if rec else 0,
                    rec["ver"] if rec else b""))
    return out
