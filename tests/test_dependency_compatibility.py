import io
import tempfile
import unittest
from pathlib import Path


class DependencyCompatibilityTest(unittest.TestCase):
    def test_file_uploader_converts_rgba_png_to_jpeg(self):
        from PIL import Image

        from server.util.FileUploader import process_image

        with tempfile.TemporaryDirectory() as temp_dir:
            source_path = Path(temp_dir) / "source.png"
            Image.new("RGBA", (17, 11), color=(40, 120, 200, 90)).save(source_path)

            output = process_image(str(source_path))

        self.assertTrue(output.startswith(b"\xff\xd8"))
        with Image.open(io.BytesIO(output)) as converted:
            self.assertEqual(converted.format, "JPEG")
            self.assertEqual(converted.mode, "RGB")
            self.assertEqual(converted.size, (17, 11))

    def test_fernet_decrypts_existing_wire_format_ciphertext(self):
        from cryptography.fernet import Fernet

        key = b"J9mEnl6sPqhIzkdBZxQqb2tXnAfpmEQ9AJ4gQIfzd7c="
        # Fixed Fernet token fixture: verifies decryption of ciphertext in the
        # stable Fernet wire format, rather than only encrypt/decrypt symmetry.
        legacy_token = (
            b"gAAAAABlU_EAPhOvmBZGJrdKAvjKoNrT3ioFG1KZ7TkzcQcBR0PTOQ2uGRSrf0Vja_hF_tLKMNGeFHZB"
            b"fu7QykEo2TygghXIhSrOwBhDUsqbYIAM3EqT3p52BS66gN9NfuR3IWKRZs7E"
        )

        self.assertEqual(
            Fernet(key).decrypt(legacy_token),
            b"legacy ciphertext interoperability fixture",
        )

    def test_pbkdf2_encrypted_backup_payload_round_trips(self):
        from server.backup import _decrypt_payload, _encrypt_payload

        payload = {
            "format": "automoguding-backup-v1",
            "tables": {"user": [{"id": 23, "phone": "13800000000"}]},
            "manifest": {"checksum": "compatibility-fixture"},
        }
        encrypted = _encrypt_payload(payload, "test-backup-key-with-enough-entropy")

        self.assertEqual(encrypted["kdf"], "pbkdf2_sha256")
        self.assertEqual(encrypted["iterations"], 390_000)
        self.assertEqual(_decrypt_payload(encrypted, "test-backup-key-with-enough-entropy"), payload)


if __name__ == "__main__":
    unittest.main()
