import sys
import types
import unittest
from unittest.mock import patch


class _FakeBLE:
    def active(self, enabled):
        pass

    def irq(self, handler):
        pass


_bluetooth = types.ModuleType("bluetooth")
_bluetooth.BLE = _FakeBLE
_ucryptolib = types.ModuleType("ucryptolib")
with patch.dict(sys.modules, {"bluetooth": _bluetooth, "ucryptolib": _ucryptolib}):
    from opendash import config, ninebot


class NinebotPairingTests(unittest.TestCase):
    def setUp(self):
        self.client = ninebot.Ninebot()
        self.client.dev_name = "G30"
        self.client.crypto.serial = b"12345678901234"
        self.client.auth_state = ninebot.AUTH_WAIT_INIT
        self.client.state = ninebot.AUTH
        self.client.send_packet = unittest.mock.Mock(return_value=True)

    def test_reuses_key_for_matching_scooter_without_prompt(self):
        app_key = bytes(range(16))
        with patch.object(ninebot.storage, "load_pairing", return_value=app_key), \
                patch.object(ninebot.time, "ticks_ms", return_value=1, create=True):
            self.client._handle_plain(
                bytes((0x5A, 0xA5, 0, 0x21, config.ADDR_APP, 0x5B, 1)))

        self.assertEqual(self.client.crypto.random_app, app_key)
        self.assertEqual(self.client.auth_state, ninebot.AUTH_WAIT_PING)
        self.assertTrue(self.client.auth_app_key_reused)
        self.assertFalse(self.client.press_power)
        self.assertEqual(self.client.status_text, "AUTH KEY")
        self.client.send_packet.assert_called_once_with(0x21, 0x5C, 0, app_key)

    def test_new_scooter_still_requires_power_button(self):
        app_key = b"k" * 16
        with patch.object(ninebot.storage, "load_pairing", return_value=None), \
                patch.object(ninebot.os, "urandom", return_value=app_key), \
                patch.object(ninebot.time, "ticks_ms", return_value=1, create=True):
            self.client._handle_plain(
                bytes((0x5A, 0xA5, 0, 0x21, config.ADDR_APP, 0x5B, 1)))

        self.assertEqual(self.client.crypto.random_app, app_key)
        self.assertTrue(self.client.press_power)
        self.assertEqual(self.client.status_text, "PRESS POWER")
        self.assertFalse(self.client.auth_app_key_reused)

    def test_prompts_if_saved_key_gets_no_response(self):
        self.client.auth_state = ninebot.AUTH_WAIT_PING
        self.client.auth_app_key_reused = True
        self.client.auth_attempts = 2
        self.client.auth_last = 0
        with patch.object(ninebot.time, "ticks_diff",
                          side_effect=lambda now, then: now - then, create=True):
            self.client._auth_tick(1201)

        self.assertTrue(self.client.press_power)
        self.assertEqual(self.client.status_text, "PRESS POWER")

    def test_key_is_saved_only_after_pair_ack(self):
        app_key = b"k" * 16
        self.client.crypto.random_app = app_key
        self.client.auth_state = ninebot.AUTH_WAIT_PAIR
        self.client.send_packet = unittest.mock.Mock(return_value=True)
        with patch.object(ninebot.storage, "save_pairing", return_value=True) as save, \
                patch.object(ninebot.time, "ticks_ms", return_value=1, create=True):
            self.client._handle_plain(
                bytes((0x5A, 0xA5, 0, 0x21, config.ADDR_APP, 0x5D, 0)))
            save.assert_not_called()
            self.client.auth_state = ninebot.AUTH_WAIT_PAIR
            self.client._handle_plain(
                bytes((0x5A, 0xA5, 0, 0x21, config.ADDR_APP, 0x5D, 1)))

        save.assert_called_once_with("G30", b"12345678901234", app_key)
        self.assertEqual(self.client.state, ninebot.READY)


if __name__ == "__main__":
    unittest.main()
