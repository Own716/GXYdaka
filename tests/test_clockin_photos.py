import io
import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch, Mock

from PIL import Image
from starlette.requests import Request

# App imports require a MySQL URL; tests use only a lazy, non-routable engine.
os.environ.setdefault("DATABASE_URL", "mysql+pymysql://test:test@127.0.0.1/test_db")

from server import api, main, task_runner, clockin_photos
from server.util.Config import ConfigManager
from server.user_runtime import user_to_config
from server.models import User


def image_bytes(fmt="PNG", size=(32, 24)):
    output = io.BytesIO()
    Image.new("RGB", size, (40, 120, 200)).save(output, format=fmt)
    return output.getvalue()


class ClockInPhotoStorageTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root_patch = patch.object(clockin_photos, "_ROOT", Path(self.temp.name) / "images" / "clockin_photos")
        self.root_patch.start()

    def tearDown(self):
        self.root_patch.stop()
        self.temp.cleanup()

    def test_upload_normalizes_image_and_delete_updates_manifest(self):
        rows = clockin_photos.add_photos("tenant-a", 51, [("front.png", image_bytes())])
        self.assertEqual(len(rows), 1)
        normalized = clockin_photos.read_photo("tenant-a", 51, rows[0]["id"])
        with Image.open(io.BytesIO(normalized)) as image:
            self.assertEqual(image.format, "JPEG")
            self.assertEqual(image.size, (32, 24))
            self.assertFalse(image.getexif())
        self.assertEqual(clockin_photos.delete_photo("tenant-a", 51, rows[0]["id"]), [])
        self.assertEqual(clockin_photos.list_photos("tenant-a", 51), [])

    def test_limits_invalid_images_and_batch_atomicity(self):
        with self.assertRaises(clockin_photos.PhotoError):
            clockin_photos.add_photos("t", 1, [("bad.jpg", b"not image")])
        with self.assertRaises(clockin_photos.PhotoError):
            clockin_photos.add_photos("t", 1, [("too-large", b"x" * (clockin_photos.MAX_UPLOAD_BYTES + 1))])
        with self.assertRaises(clockin_photos.PhotoError):
            clockin_photos.add_photos("t", 1, [("x", image_bytes())] * 21)
        with self.assertRaises(clockin_photos.PhotoError):
            clockin_photos.add_photos("t", 1, [("batch", b"x" * (clockin_photos.MAX_BATCH_BYTES + 1))])
        # Decode failure in a later part must not leave earlier files or manifest entries behind.
        with self.assertRaises(clockin_photos.PhotoError):
            clockin_photos.add_photos("t", 2, [("ok.png", image_bytes()), ("bad", b"bad")])
        self.assertEqual(clockin_photos.list_photos("t", 2), [])

    def test_twenty_photo_cap_and_tenant_user_isolation(self):
        rows = clockin_photos.add_photos("tenant-a", 3, [(f"{i}.png", image_bytes()) for i in range(20)])
        self.assertEqual(len(rows), 20)
        with self.assertRaises(clockin_photos.PhotoError):
            clockin_photos.add_photos("tenant-a", 3, [("extra.png", image_bytes())])
        self.assertEqual(clockin_photos.list_photos("tenant-b", 3), [])
        self.assertEqual(clockin_photos.list_photos("tenant-a", 4), [])
        with self.assertRaises(FileNotFoundError):
            clockin_photos.read_photo("tenant-b", 3, rows[0]["id"])

    def test_traversal_symlink_and_empty_gallery_fail_closed(self):
        with self.assertRaises(FileNotFoundError):
            clockin_photos.read_photo("tenant-a", 1, "../../manifest.json")
        with self.assertRaises(FileNotFoundError):
            clockin_photos.delete_photo("tenant-a", 1, "../../manifest.json")
        with self.assertRaises(clockin_photos.PhotoError):
            clockin_photos.choose_photo_bytes("tenant-a", 1)
        rows = clockin_photos.add_photos("tenant-a", 1, [("photo", image_bytes())])
        path = clockin_photos._directory("tenant-a", 1) / f"{rows[0]['id']}.jpg"
        path.unlink()
        path.symlink_to(Path(self.temp.name) / "outside.jpg")
        with self.assertRaises(clockin_photos.PhotoError):
            clockin_photos.choose_photo_bytes("tenant-a", 1)

    def test_random_selection_uses_one_manifest_entry_without_altering_gallery(self):
        rows = clockin_photos.add_photos("tenant-a", 1, [("one.png", image_bytes()), ("two.jpg", image_bytes("JPEG"))])
        expected = clockin_photos.read_photo("tenant-a", 1, rows[1]["id"])
        with patch("random.choice", side_effect=lambda entries: entries[1]) as choice:
            selected = clockin_photos.choose_photo_bytes("tenant-a", 1)
        self.assertEqual(selected, expected)
        choice.assert_called_once()
        self.assertEqual(clockin_photos.list_photos("tenant-a", 1), rows)

    def test_concurrent_uploads_cannot_overwrite_manifest_or_exceed_cap(self):
        from concurrent.futures import ThreadPoolExecutor
        clockin_photos.add_photos("tenant-a", 1, [(f"{n}.png", image_bytes()) for n in range(19)])

        def add_one(n):
            try:
                clockin_photos.add_photos("tenant-a", 1, [(f"extra-{n}.png", image_bytes())])
                return True
            except clockin_photos.PhotoError:
                return False

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(add_one, (1, 2)))
        self.assertEqual(sorted(outcomes), [False, True])
        self.assertEqual(len(clockin_photos.list_photos("tenant-a", 1)), 20)

    def test_normalization_rotates_strips_metadata_and_bounds_encoded_size(self):
        source = io.BytesIO()
        image = Image.new("RGB", (32, 16), "blue")
        exif = Image.Exif()
        exif[274] = 6
        exif[271] = "private camera metadata"
        image.save(source, "JPEG", exif=exif)
        with Image.open(io.BytesIO(clockin_photos.normalize_image(source.getvalue()))) as normalized:
            self.assertEqual(normalized.size, (16, 32))
            self.assertFalse(normalized.getexif())
        noisy = io.BytesIO()
        Image.effect_noise((1920, 1920), 100).convert("RGB").save(noisy, "JPEG", quality=95)
        self.assertLessEqual(len(clockin_photos.normalize_image(noisy.getvalue())), 1024 * 1024)
        with patch.object(clockin_photos, "MAX_PIXELS", 100):
            with self.assertRaises(clockin_photos.PhotoError):
                clockin_photos.normalize_image(image_bytes(size=(20, 20)))


class ClockInPhotoTaskTest(unittest.TestCase):
    def _config(self, enabled=True):
        return ConfigManager(config={
            "tenant_id": "tenant-from-row", "user_id": 71,
            "config": {"clockIn": {"photoEnabled": enabled, "imageCount": 1}, "user": {}},
            "userInfo": {"nikeName": "Test", "userId": "remote-7", "orgJson": {"snowFlakeId": "org-3"}},
        })

    def _client(self):
        client = Mock()
        client.get_checkin_records.return_value = []
        client.get_upload_token.return_value = "token"
        client.submit_clock_in.return_value = {"status": "success"}
        return client

    def test_enabled_uses_exactly_one_randomly_chosen_photo(self):
        client = self._client()
        with patch.object(task_runner, "choose_photo_bytes", return_value=b"one-selected") as choose, patch.object(task_runner, "upload_image_bytes", return_value="remote.jpg") as upload:
            result = task_runner.perform_clock_in(client, self._config(), target_time=datetime(2026, 5, 1, 8, 0))
        self.assertEqual(result["status"], "success")
        choose.assert_called_once_with("tenant-from-row", 71)
        self.assertEqual(upload.call_args.args[3], [b"one-selected"])
        self.assertEqual(client.submit_clock_in.call_args.args[0]["attachments"], "remote.jpg")

    def test_empty_collection_or_remote_upload_failure_never_submits(self):
        client = self._client()
        with patch.object(task_runner, "choose_photo_bytes", side_effect=clockin_photos.PhotoError("empty")):
            result = task_runner.perform_clock_in(client, self._config(), target_time=datetime(2026, 5, 1, 8, 0))
        self.assertEqual(result["status"], "fail")
        client.submit_clock_in.assert_not_called()
        client = self._client()
        with patch.object(task_runner, "choose_photo_bytes", return_value=b"one"), patch.object(task_runner, "upload_image_bytes", return_value=""):
            result = task_runner.perform_clock_in(client, self._config(), target_time=datetime(2026, 5, 1, 8, 0))
        self.assertEqual(result["status"], "fail")
        client.submit_clock_in.assert_not_called()

    def test_opt_out_preserves_legacy_imagecount_gallery_path(self):
        client = self._client()
        with patch.object(task_runner, "upload_img", return_value="legacy.jpg") as legacy, patch.object(task_runner, "upload_image_bytes") as user_photo_upload:
            result = task_runner.perform_clock_in(client, self._config(False), target_time=datetime(2026, 5, 1, 8, 0))
        self.assertEqual(result["status"], "success")
        legacy.assert_called_once_with("token", "org-3", "remote-7", 1)
        user_photo_upload.assert_not_called()


class ClockInPhotoApiContractTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root_patch = patch.object(clockin_photos, "_ROOT", Path(self.temp.name) / "clockin_photos")
        self.root_patch.start()

    def tearDown(self):
        self.root_patch.stop()
        self.temp.cleanup()

    def test_routes_include_authorized_admin_and_bound_app_surfaces(self):
        routes = {(route.path, tuple(sorted(route.methods or []))): route for route in api.router.routes}
        expected = {
            "/users/{user_id}/clock-in/photos", "/users/{user_id}/clock-in/photos/{photo_id}",
            "/app/clock-in/photos", "/app/clock-in/photos/{photo_id}",
        }
        self.assertTrue(expected.issubset({path for path, _ in routes}))
        admin_get = routes[("/users/{user_id}/clock-in/photos", ("GET",))]
        admin_post = routes[("/users/{user_id}/clock-in/photos", ("POST",))]
        self.assertIn(api.require_users_read, {item.call for item in admin_get.dependant.dependencies})
        self.assertIn(api.require_users_write, {item.call for item in admin_post.dependant.dependencies})
        upload_ops = [r for r in routes.values() if r.path in {"/users/{user_id}/clock-in/photos", "/app/clock-in/photos"} and "POST" in r.methods]
        self.assertEqual(len(upload_ops), 2)
        self.assertTrue(all("requestBody" in r.openapi_extra for r in upload_ops))

    def test_toggle_is_strict_bool_and_upload_does_not_enable_it(self):
        with self.assertRaises(api.HTTPException):
            api._validate_user_rules({"photoEnabled": 1})
        api._validate_user_rules({"photoEnabled": False})
        user = User(id=7, tenant_id="tenant-a", phone="1", password="x", clockIn={"photoEnabled": False})
        self.assertFalse(api._clockin_photo_payload(user)["enabled"])
        self.assertEqual(api._clockin_photo_payload(user)["photos"], [])

    def test_identity_bridge_uses_persistent_ids_not_editable_clockin(self):
        user = User(id=82, tenant_id="trusted-tenant", phone="1", password="x", clockIn={"photoEnabled": True, "tenant_id": "attacker", "user_id": 8})
        config = user_to_config(user, decrypt_password=lambda _: "")
        self.assertEqual(config["tenant_id"], "trusted-tenant")
        self.assertEqual(config["user_id"], 82)

    def test_photo_body_limit_is_independent_bounded_and_does_not_change_other_routes(self):
        def request(path, method="POST"):
            return Request({"type": "http", "method": method, "path": path, "headers": []})
        with patch.dict("os.environ", {"APP_ENV": "production", "MAX_REQUEST_BODY_BYTES": "8388608", "MAX_CLOCKIN_PHOTO_REQUEST_BYTES": ""}):
            self.assertEqual(main._request_body_limit_for_request(request("/api/app/clock-in/photos")), 32 * 1024 * 1024)
            self.assertEqual(main._request_body_limit_for_request(request("/api/users/15/clock-in/photos")), 32 * 1024 * 1024)
            self.assertEqual(main._request_body_limit_for_request(request("/api/app/run")), 8 * 1024 * 1024)
            self.assertEqual(main._request_body_limit_for_request(request("/api/app/clock-in/photos", "GET")), 8 * 1024 * 1024)
            with patch.dict("os.environ", {"MAX_CLOCKIN_PHOTO_REQUEST_BYTES": "1048576"}):
                self.assertEqual(main._request_body_limit_for_request(request("/api/users/15/clock-in/photos")), 1024 * 1024)
                self.assertEqual(main._request_body_limit_for_request(request("/api/app/run")), 8 * 1024 * 1024)
            for configured in ("0", "-1", "invalid", str(64 * 1024 * 1024)):
                with patch.dict("os.environ", {"MAX_CLOCKIN_PHOTO_REQUEST_BYTES": configured}):
                    self.assertEqual(main._request_body_limit_for_request(request("/api/app/clock-in/photos")), 32 * 1024 * 1024)


if __name__ == "__main__":
    unittest.main()
