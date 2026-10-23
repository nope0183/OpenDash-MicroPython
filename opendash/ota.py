"""Wi-Fi access point + HTTP firmware update (MicroPython .bin).

Uses ``esp32.Partition`` to write the next OTA slot and mark it bootable.
This is the MicroPython equivalent of the original OpenDash OTA page.
The uploaded image must be a MicroPython build for this exact board.
"""
import gc
import hashlib
import machine
import network
import os
import socket
import time

try:
    from . import config
except ImportError:
    from opendash import config

PAGE = """<!doctype html><html lang="ru"><meta name="viewport" content="width=device-width">
<title>OpenDash MicroPython OTA</title>
<style>body{font:16px system-ui;max-width:38em;margin:3em auto;padding:0 1em}
button,input{font:inherit;margin:.5em 0}progress{width:100%}</style>
<h1>OpenDash MicroPython — обновление</h1>
<p>Выберите <b>app-образ MicroPython (.app-bin)</b> для этой платы.
Это не полный установочный .bin: полный образ содержит загрузчик и таблицу
разделов и не подходит для OTA-слота.</p>
<p>Не отключайте питание во время загрузки.</p>
<form id="f"><input id="b" type="file" accept=".app-bin,.bin" required>
<button>Загрузить и установить</button></form>
<progress id="p" max="100" value="0" hidden></progress><p id="s"></p>
<script>f.onsubmit=async e=>{e.preventDefault();if(!b.files.length)return;
p.hidden=false;s.textContent='Загрузка…';let x=new XMLHttpRequest();
x.open('POST','/update');x.upload.onprogress=e=>{if(e.lengthComputable)p.value=e.loaded/e.total*100};
x.onload=()=>s.textContent=x.status===200?x.responseText:'Ошибка: '+x.responseText;
x.onerror=()=>s.textContent='Ошибка соединения';let d=new FormData();d.append('firmware',b.files[0]);x.send(d)};</script>
</html>"""


def _valid_image_header(header):
    """Cheap sanity check for an ESP32 application image header."""
    if len(header) < 24 or header[0] != 0xE9:
        return False
    segments = header[1]
    if segments < 1 or segments > 16:
        return False
    # Little-endian chip id at offset 12; 0 means ESP32.
    if header[12] != 0 or header[13] != 0:
        return False
    # Bit 0 of byte 23 says whether a SHA-256 digest is appended.
    if header[23] > 1:
        return False
    return True


class _ImageCheck:
    """Validate the app header and the optional trailing SHA-256.

    Only the first 24 bytes and the last 32 bytes need to be retained.  All
    bytes before the trailing digest are hashed while the upload streams in.
    """

    def __init__(self):
        self.header = bytearray()
        self.hasher = hashlib.sha256()
        self.tail = b""
        self.total = 0

    def feed(self, data):
        data = bytes(data)
        self.total += len(data)
        if len(self.header) < 24:
            n = min(24 - len(self.header), len(data))
            self.header.extend(data[:n])
        self.tail += data
        if len(self.tail) > 32:
            cut = len(self.tail) - 32
            self.hasher.update(self.tail[:cut])
            self.tail = self.tail[cut:]

    def finish(self):
        if not _valid_image_header(self.header):
            return False, "неверный заголовок app-образа ESP32"
        if self.header[23] & 1:
            if len(self.tail) != 32:
                return False, "в образе нет завершающего SHA-256"
            if self.hasher.digest() != self.tail:
                return False, "SHA-256 образа не совпадает"
        return True, ""


class _UploadSink:
    """Hold the first 0x7002 bytes before writing anything to flash.

    This lets us reject a complete installer image (partition table at file
    offset 0x7000) and garbage headers without touching the inactive slot.
    """

    FULL_OFFSET = 0x7000
    FULL_SIZE = FULL_OFFSET + 2

    def __init__(self, writer):
        self.writer = writer
        self.check = _ImageCheck()
        self.prefix = bytearray()
        self.ready = False
        self.error = ""

    def push(self, data):
        if not data:
            return True
        data = bytes(data)
        self.check.feed(data)
        if not self.ready:
            self.prefix.extend(data)
            if len(self.prefix) < self.FULL_SIZE:
                return True
            return self._flush_prefix()
        self.writer.write(data)
        if self.writer.overflow:
            self.error = "too big"
            return False
        return True

    def _flush_prefix(self):
        prefix = bytes(self.prefix)
        if (len(prefix) >= self.FULL_SIZE and
                prefix[self.FULL_OFFSET:self.FULL_SIZE] == b"\xAA\x50"):
            self.error = "full image"
            return False
        if not _valid_image_header(prefix[:24]):
            self.error = "bad header"
            return False
        self.writer.write(prefix)
        self.prefix = bytearray()
        if self.writer.overflow:
            self.error = "too big"
            return False
        self.ready = True
        return True

    def finish(self):
        if not self.ready:
            if not self.prefix:
                self.error = "empty"
                return False
            if not self._flush_prefix():
                return False
        if self.writer.overflow:
            self.error = "too big"
            return False
        ok, message = self.check.finish()
        if not ok:
            self.error = message
            return False
        return True


class _FlashWriter:
    """Stream bytes into 4 KiB partition blocks with a hard size limit."""

    def __init__(self, part, max_size):
        self.part = part
        self.max_size = max_size
        self.block = bytearray(4096)
        self.block_len = 0
        self.block_no = 0
        self.written = 0
        self.overflow = False

    def write(self, data):
        if self.overflow or not data:
            return
        pos = 0
        while pos < len(data):
            n = min(4096 - self.block_len, len(data) - pos)
            if self.max_size and self.written + n > self.max_size:
                self.overflow = True
                return
            self.block[self.block_len:self.block_len + n] = data[pos:pos + n]
            self.block_len += n
            pos += n
            self.written += n
            if self.block_len == 4096:
                self.part.writeblocks(self.block_no, self.block)
                self.block_no += 1
                self.block_len = 0

    def finish(self):
        if self.overflow:
            return False
        if self.block_len:
            self.block[self.block_len:] = b"\xFF" * (4096 - self.block_len)
            self.part.writeblocks(self.block_no, self.block)
            self.block_no += 1
            self.block_len = 0
        return True


class OtaServer:
    def __init__(self):
        self.enabled = False
        self.ssid = ""
        self.password = ""
        self.ip = "192.168.4.1"
        self._ap = None
        self._sock = None
        self.status = ""
        self._esp32 = None
        try:
            import esp32
            self._esp32 = esp32
        except ImportError:
            pass

    def start(self):
        if self.enabled:
            return True
        uid = machine.unique_id()
        suffix = "".join("%02X" % b for b in uid[-3:])
        self.ssid = "OpenDash-" + suffix
        self.password = "".join("%02X" % b for b in os.urandom(6))
        try:
            ap = network.WLAN(network.AP_IF)
            ap.active(False)
            ap.config(essid=self.ssid, password=self.password,
                      authmode=network.AUTH_WPA2_PSK)
            ap.active(True)
            try:
                ap.ifconfig(("192.168.4.1", "255.255.255.0", "192.168.4.1", "192.168.4.1"))
            except Exception:
                pass
            deadline = time.ticks_add(time.ticks_ms(), 3000)
            while not ap.active() and time.ticks_diff(time.ticks_ms(), deadline) < 0:
                time.sleep_ms(50)
            if not ap.active():
                raise OSError("AP не включился")
            self.ip = ap.ifconfig()[0]
            if not self.ip or self.ip == "0.0.0.0":
                raise OSError("AP не получил адрес")
            self._ap = ap
            self._sock = socket.socket()
            self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._sock.bind(("0.0.0.0", 80))
            self._sock.listen(1)
            self._sock.settimeout(0.02)
            self.enabled = True
            self.status = "http://" + self.ip + "/"
            print("OTA AP:", self.ssid, self.password, self.status)
            return True
        except Exception as exc:
            print("OTA start failed:", exc)
            message = "AP error: " + str(exc)
            self.stop()
            self.status = message
            return False

    def stop(self):
        self.enabled = False
        if self._sock is not None:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None
        if self._ap is not None:
            try:
                self._ap.active(False)
            except Exception:
                pass
            self._ap = None
        self.ssid = ""
        self.password = ""
        self.status = ""

    def _send(self, conn, code, body, ctype="text/html; charset=utf-8"):
        if isinstance(body, str):
            body = body.encode()
        head = ("HTTP/1.1 %s\r\nContent-Type: %s\r\nContent-Length: %d\r\n"
                "Connection: close\r\nCache-Control: no-store\r\n\r\n" %
                (code, ctype, len(body)))
        data = head.encode() + body
        pos = 0
        try:
            while pos < len(data):
                sent = conn.send(data[pos:])
                if not sent:
                    break
                pos += sent
        except Exception:
            pass

    def poll(self):
        if not self.enabled or self._sock is None:
            return
        try:
            conn, _addr = self._sock.accept()
        except OSError:
            return
        try:
            conn.settimeout(1.0)
            self._handle(conn)
        except Exception as exc:
            print("OTA request:", exc)
            self.status = "ошибка: " + str(exc)
        finally:
            try:
                conn.close()
            except Exception:
                pass
            gc.collect()

    def _handle(self, conn):
        data = b""
        while b"\r\n\r\n" not in data:
            chunk = conn.recv(1024)
            if not chunk:
                return
            data += chunk
            if len(data) > 8192:
                return
        head, _, rest = data.partition(b"\r\n\r\n")
        lines = head.split(b"\r\n")
        request = lines[0].decode().split()
        if len(request) < 2:
            return
        method, path = request[0], request[1]
        if method == "GET":
            self._send(conn, "200 OK", PAGE)
            return
        if method != "POST" or path != "/update":
            self._send(conn, "404 Not Found", "Not found", "text/plain")
            return
        headers = {}
        for line in lines[1:]:
            if b":" in line:
                k, v = line.split(b":", 1)
                headers[k.strip().lower()] = v.strip()
        ctype = headers.get(b"content-type", b"").decode()
        if "boundary=" not in ctype:
            self._send(conn, "400 Bad Request", "bad multipart", "text/plain")
            return
        boundary = ctype.split("boundary=", 1)[1].strip().strip('"')
        try:
            length = int(headers.get(b"content-length", b"0"))
        except ValueError:
            length = 0
        if length <= 0:
            self._send(conn, "411 Length Required", "no length", "text/plain")
            return
        result, message = self._receive_image(conn, rest, length, boundary.encode())
        if result:
            self._send(conn, "200 OK", message, "text/plain; charset=utf-8")
            time.sleep_ms(1200)
            machine.reset()
        else:
            self._send(conn, "400 Bad Request", message, "text/plain; charset=utf-8")

    def _receive_image(self, conn, initial, length, boundary):
        if self._esp32 is None:
            return False, "esp32.Partition не поддерживается этой сборкой"
        try:
            part = self._esp32.Partition(self._esp32.Partition.RUNNING).get_next_update()
            max_size = part.info()[3]
        except Exception as exc:
            return False, "нет OTA-раздела: " + str(exc)
        marker = b"\r\n--" + boundary
        closing = marker + b"--"
        writer = _FlashWriter(part, max_size)
        sink = _UploadSink(writer)
        buf = bytearray(initial)
        total = len(initial)
        if total > length:
            return False, "лишние данные после тела запроса"
        headers = False
        pad = len(closing) + 8

        while True:
            if not headers:
                idx = buf.find(b"\r\n\r\n")
                if idx >= 0:
                    del buf[:idx + 4]
                    headers = True
                elif total >= length:
                    return False, "неверный multipart-запрос"
                else:
                    chunk = conn.recv(2048)
                    if not chunk:
                        return False, "соединение прервано до конца запроса"
                    total += len(chunk)
                    if total > length:
                        return False, "лишние данные после тела запроса"
                    buf.extend(chunk)
                    continue
            if not buf:
                if total >= length:
                    return False, "пустой файл"
                chunk = conn.recv(2048)
                if not chunk:
                    return False, "соединение прервано до конца запроса"
                total += len(chunk)
                if total > length:
                    return False, "лишние данные после тела запроса"
                buf.extend(chunk)
                continue

            end = buf.find(marker)
            if end >= 0:
                # Need the complete closing delimiter, not just a partial one.
                if len(buf) < end + len(closing):
                    if total >= length:
                        return False, "незавершённая multipart-граница"
                    chunk = conn.recv(2048)
                    if not chunk:
                        return False, "соединение прервано до конца запроса"
                    total += len(chunk)
                    if total > length:
                        return False, "лишние данные после тела запроса"
                    buf.extend(chunk)
                    continue
                if bytes(buf[end:end + len(closing)]) != closing:
                    return False, "неверная multipart-граница"
                if not sink.push(buf[:end]):
                    return False, self._sink_message(sink, max_size)
                break

            # No boundary yet.  Only accept Content-Length bytes; an early
            # EOF, a missing delimiter, or a short body must never reach
            # set_boot().
            if total >= length:
                return False, "нет закрывающей multipart-границы"
            if len(buf) > pad:
                keep = len(buf) - pad
                if not sink.push(buf[:keep]):
                    return False, self._sink_message(sink, max_size)
                del buf[:keep]

            chunk = conn.recv(2048)
            if not chunk:
                return False, "соединение прервано до конца запроса"
            total += len(chunk)
            if total > length:
                return False, "лишние данные после тела запроса"
            buf.extend(chunk)

        # Drain any epilogue bytes so the declared Content-Length is met.
        while total < length:
            chunk = conn.recv(min(2048, length - total))
            if not chunk:
                return False, "соединение прервано до конца запроса"
            total += len(chunk)
        if total != length:
            return False, "неверная длина тела запроса"

        if not sink.finish():
            return False, self._sink_message(sink, max_size)
        if writer.written == 0:
            return False, "пустой файл"
        try:
            if not writer.finish():
                return False, "прошивка больше OTA-раздела (%d байт)" % max_size
            part.set_boot()
        except Exception as exc:
            return False, "не удалось переключить раздел: " + str(exc)
        self.status = "прошивка записана: %d байт" % writer.written
        return True, ("Прошивка записана (%d байт). Устройство перезагрузится." % writer.written)

    @staticmethod
    def _sink_message(sink, max_size):
        if sink.error == "full image":
            return "это полный .bin; для OTA нужен app-образ .app-bin"
        if sink.error == "bad header":
            return "неверный заголовок app-образа ESP32 (.app-bin)"
        if sink.error == "too big":
            return "прошивка больше OTA-раздела (%d байт)" % max_size
        if sink.error == "empty":
            return "пустой файл"
        return sink.error or "неверный образ"
