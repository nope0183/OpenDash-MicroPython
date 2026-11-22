import os
import tempfile
import unittest

from opendash import config, storage


class PairingStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.old_path = config.PAIRING_FILE
        config.PAIRING_FILE = os.path.join(self.temp_dir.name, "pairing.json")

    def tearDown(self):
        config.PAIRING_FILE = self.old_path
        self.temp_dir.cleanup()

    def test_saves_and_matches_exact_scooter_identity(self):
        serial = b"12345678901234"
        app_key = bytes(range(16))
        self.assertTrue(storage.save_pairing("G30", serial, app_key))
        self.assertEqual(storage.load_pairing("G30", serial), app_key)
        self.assertIsNone(storage.load_pairing("Other", serial))
        self.assertIsNone(storage.load_pairing("G30", b"43210987654321"))

    def test_rejects_malformed_saved_key(self):
        with open(config.PAIRING_FILE, "w") as f:
            f.write('{"name":"G30","serial":"3132333435363738393031323334",'
                    '"app_key":"bad"}')
        self.assertIsNone(storage.load_pairing("G30", b"12345678901234"))

    def test_rejects_invalid_key_length(self):
        self.assertFalse(storage.save_pairing("G30", b"12345678901234", b"short"))


if __name__ == "__main__":
    unittest.main()
