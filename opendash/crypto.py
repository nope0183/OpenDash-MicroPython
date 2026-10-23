"""Ninebot encrypted transport (AES-128-ECB + SHA-1)."""
import hashlib
import ucryptolib

FW_DATA = bytes((
    0x97, 0xCF, 0xB8, 0x02, 0x84, 0x41, 0x43, 0xDE,
    0x56, 0x00, 0x2B, 0x3B, 0x34, 0x78, 0x0A, 0x5D,
))


class NinebotCrypto:
    def __init__(self):
        self.key = None
        self.aes = None
        self.name16 = b"\x00" * 16
        self.random_ble = b"\x00" * 16
        self.random_app = b"\x00" * 16
        self.serial = b"\x00" * 14
        self.message_counter = 0
        self.tx_counter = 0
        self.rx_counter = 0

    # -------------------------------------------------------------- helpers
    def _set_key(self, key):
        if self.key != key or self.aes is None:
            self.key = bytes(key)
            self.aes = ucryptolib.aes(self.key, 1)

    def set_sha_key(self, first, second):
        digest = hashlib.sha1(bytes(first) + bytes(second)).digest()
        self._set_key(digest[:16])

    def reset(self, name):
        raw = name.encode() if isinstance(name, str) else bytes(name)
        self.name16 = (raw + b"\x00" * 16)[:16]
        self.random_ble = b"\x00" * 16
        self.random_app = b"\x00" * 16
        self.serial = b"\x00" * 14
        self.set_sha_key(self.name16, FW_DATA)
        self.message_counter = 0
        self.tx_counter = 0
        self.rx_counter = 0

    def _encrypt_block(self, block):
        return self.aes.encrypt(bytes(block))

    # -------------------------------------------------------------- streams
    def crypto_first(self, data):
        stream = self._encrypt_block(FW_DATA)
        return bytes(b ^ stream[i & 15] for i, b in enumerate(data))

    def crypto_next(self, data, counter):
        seed = bytearray(16)
        seed[0] = 1
        seed[1] = (counter >> 24) & 0xFF
        seed[2] = (counter >> 16) & 0xFF
        seed[3] = (counter >> 8) & 0xFF
        seed[4] = counter & 0xFF
        seed[5:13] = self.random_ble[:8]
        out = bytearray(len(data))
        offset = 0
        block_no = 0
        while offset < len(data):
            block_no += 1
            seed[15] = block_no & 0xFF
            stream = self._encrypt_block(seed)
            n = min(16, len(data) - offset)
            for i in range(n):
                out[offset + i] = data[offset + i] ^ stream[i]
            offset += n
        return bytes(out)

    @staticmethod
    def crc_first(payload):
        total = sum(payload) & 0xFFFF
        checksum = (~total) & 0xFFFF
        return bytes((checksum & 0xFF, checksum >> 8))

    def crc_next(self, plain, counter):
        if len(plain) < 3:
            return None
        payload_len = len(plain) - 3
        seed = bytearray(16)
        seed[0] = 89
        seed[1] = (counter >> 24) & 0xFF
        seed[2] = (counter >> 16) & 0xFF
        seed[3] = (counter >> 8) & 0xFF
        seed[4] = counter & 0xFF
        seed[5:13] = self.random_ble[:8]
        seed[15] = payload_len & 0xFF
        chain = self._encrypt_block(seed)

        block = bytearray(16)
        block[0] = plain[0] ^ chain[0]
        block[1] = plain[1] ^ chain[1]
        block[2] = plain[2] ^ chain[2]
        block[3:16] = chain[3:16]
        chain = self._encrypt_block(block)
        offset = 3
        remaining = payload_len
        while remaining:
            n = min(16, remaining)
            block = bytearray(16)
            block[:n] = plain[offset:offset + n]
            for i in range(16):
                block[i] ^= chain[i]
            chain = self._encrypt_block(block)
            offset += n
            remaining -= n

        seed = bytearray(16)
        seed[0] = 1
        seed[1] = (counter >> 24) & 0xFF
        seed[2] = (counter >> 16) & 0xFF
        seed[3] = (counter >> 8) & 0xFF
        seed[4] = counter & 0xFF
        seed[5:13] = self.random_ble[:8]
        mask = self._encrypt_block(seed)
        return bytes(mask[i] ^ chain[i] for i in range(4))

    # -------------------------------------------------------------- packets
    def encrypt_packet(self, plain):
        plain = bytes(plain)
        payload_len = len(plain) - 3
        out = bytearray(plain[:3])
        if self.message_counter == 0:
            out += self.crypto_first(plain[3:])
            out += b"\x00\x00"
            out += self.crc_first(plain[3:])
            out += b"\x00\x00"
            self.message_counter = 1
        else:
            self.message_counter += 1
            checksum = self.crc_next(plain, self.message_counter)
            out += self.crypto_next(plain[3:], self.message_counter)
            out += checksum
            out.append((self.message_counter >> 8) & 0xFF)
            out.append(self.message_counter & 0xFF)
        self.tx_counter = self.message_counter
        return bytes(out)

    def decrypt_packet(self, frame):
        """Return the decrypted frame or None.  Updates the RX counter."""
        if len(frame) < 13 or frame[0] != 0x5A or frame[1] != 0xA5:
            return None
        payload_len = len(frame) - 9
        plain_len = len(frame) - 6
        plain = bytearray(plain_len)
        plain[:3] = frame[:3]
        next_counter = self.message_counter
        if (next_counter & 0x8000) and not (frame[-2] & 0x80):
            next_counter += 0x10000
        next_counter = (next_counter & 0xFFFF0000) | (frame[-2] << 8) | frame[-1]

        if next_counter == 0:
            body = self.crypto_first(frame[3:3 + payload_len])
            plain[3:] = body
            if (plain_len >= 37 and plain[2] == 0x1E and plain[3] == 0x21
                    and plain[4] == 0x3E and plain[5] == 0x5B):
                self.random_ble = bytes(plain[7:23])
                self.serial = bytes(plain[23:37])
                self.set_sha_key(self.name16, self.random_ble)
        elif next_counter > self.message_counter:
            body = self.crypto_next(frame[3:3 + payload_len], next_counter)
            plain[3:] = body
            if (plain_len >= 7 and plain[3] == 0x21 and plain[4] == 0x3E
                    and plain[5] == 0x5C and plain[6] == 0x01):
                self.set_sha_key(self.random_app, self.random_ble)
            self.message_counter = next_counter
            self.rx_counter = next_counter
        else:
            return None
        return bytes(plain)
