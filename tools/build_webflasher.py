"""Build the preloaded LittleFS images used by the GitHub Pages installer.

The images are written to docs/firmware/.  They use the same dynamic VFS
partition layout as the MicroPython ESP32 OTA build:

    nvs       0x009000  0x004000
    otadata   0x00d000  0x002000
    phy_init  0x00f000  0x001000
    ota_0     0x010000  0x180000
    ota_1     0x190000  0x180000
    vfs       0x310000  0x0f0000  (created automatically by MicroPython)

Requires: python -m pip install littlefs-python
"""
from pathlib import Path
import hashlib
import sys

try:
    from littlefs import LittleFS, UserContextFile
except ImportError:
    raise SystemExit("Install littlefs-python: python -m pip install littlefs-python")

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs" / "firmware"
BLOCK_SIZE = 4096
IMAGE_SIZE = 0xF0000
BLOCK_COUNT = IMAGE_SIZE // BLOCK_SIZE


def _write(fs, remote, data):
    with fs.open(remote, "wb") as fh:
        fh.write(data)


def build(driver, output):
    DOCS.mkdir(parents=True, exist_ok=True)
    output.write_bytes(b"\xFF" * IMAGE_SIZE)
    ctx = UserContextFile(str(output))
    fs = LittleFS(
        context=ctx,
        block_size=BLOCK_SIZE,
        block_count=BLOCK_COUNT,
        read_size=32,
        prog_size=32,
        cache_size=BLOCK_SIZE,
        lookahead_size=32,
        mount=False,
    )
    fs.format()
    fs.mount()
    fs.mkdir("/opendash")

    config = (ROOT / "opendash" / "config.py").read_text(encoding="utf-8")
    if driver != "st7789":
        old = 'DISPLAY_DRIVER = "st7789"'
        new = 'DISPLAY_DRIVER = "%s"' % driver
        if old not in config:
            raise SystemExit("DISPLAY_DRIVER line not found in config.py")
        config = config.replace(old, new, 1)

    _write(fs, "/boot.py", (ROOT / "boot.py").read_bytes())
    _write(fs, "/main.py", (ROOT / "main.py").read_bytes())
    for path in sorted((ROOT / "opendash").glob("*.py")):
        data = config.encode("utf-8") if path.name == "config.py" else path.read_bytes()
        _write(fs, "/opendash/" + path.name, data)

    fs.unmount()
    ctx.close()

    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    print("%s  %s" % (digest, output.name))


def main():
    build("st7789", DOCS / "opendash-vfs-st7789.bin")
    build("ili9341", DOCS / "opendash-vfs-ili9341.bin")
    return 0


if __name__ == "__main__":
    sys.exit(main())
