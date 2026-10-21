import unittest
from unittest.mock import Mock, patch

from server.coreApi import FileUploadApi


class FileUploadApiTest(unittest.TestCase):
    def setUp(self):
        self.jpeg_bytes = b"\xff\xd8\xff\xe0test-jpeg-payload\xff\xd9"
        self.key = "upload/org-123/2026-10-21/report/user-456_123.jpg"

    def _mock_session(self, response):
        session = Mock()
        session.__enter__ = Mock(return_value=session)
        session.__exit__ = Mock(return_value=False)
        session.post.return_value = response
        return session

    def test_upload_sends_existing_fields_and_jpeg_multipart_tuple(self):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"key": self.key, "hash": "digest"}
        session = self._mock_session(response)

        with (
            patch.object(FileUploadApi.requests, "Session", return_value=session) as session_factory,
            patch.object(FileUploadApi, "build_upload_key", return_value=self.key),
            patch.object(FileUploadApi.time, "sleep"),
        ):
            attachment = FileUploadApi.upload("upload-token", "org-123", "user-456", [self.jpeg_bytes])

        self.assertEqual(attachment, "org-123/2026-10-21/report/user-456_123.jpg")
        session_factory.assert_called_once_with()
        session.post.assert_called_once()
        args, kwargs = session.post.call_args
        self.assertEqual(args[0], "https://up.qiniup.com/")
        self.assertEqual(kwargs["data"]["token"], "upload-token")
        self.assertEqual(kwargs["data"]["key"], self.key)
        self.assertIn("x-qn-meta-fname", kwargs["data"])
        self.assertEqual(set(kwargs["files"]), {"file"})
        self.assertEqual(
            kwargs["files"]["file"],
            (self.key, self.jpeg_bytes, "image/jpeg"),
        )
        self.assertEqual(kwargs["timeout"], 30)

    def test_only_a_leading_upload_prefix_is_removed(self):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"key": "upload/org/report/upload/name.jpg"}
        session = self._mock_session(response)

        result = FileUploadApi.upload_image(
            session, "https://up.qiniup.com/", {}, self.jpeg_bytes,
            "token", self.key, max_retries=1,
        )

        self.assertEqual(result, "org/report/upload/name.jpg")

    def test_invalid_json_and_invalid_or_business_error_keys_never_succeed(self):
        bad_responses = [
            (ValueError("invalid JSON"),),
            (["not", "an", "object"],),
            ({},),
            ({"key": ""},),
            ({"key": None},),
            ({"key": 123},),
            ({"key": "/absolute/name.jpg"},),
            ({"key": "org/../name.jpg"},),
            ({"key": "https://cdn.example/name.jpg"},),
            ({"key": "org/name.png"},),
            ({"key": self.key, "error": "invalid upload token"},),
            ({"key": self.key, "code": 500},),
            ({"key": self.key, "success": False},),
        ]
        for (payload,) in bad_responses:
            with self.subTest(payload=payload):
                response = Mock()
                response.raise_for_status.return_value = None
                if isinstance(payload, Exception):
                    response.json.side_effect = payload
                else:
                    response.json.return_value = payload
                session = self._mock_session(response)
                result = FileUploadApi.upload_image(
                    session, "https://up.qiniup.com/", {}, self.jpeg_bytes,
                    "token", self.key, max_retries=1,
                )
                self.assertIsNone(result)

    def test_http_upload_failure_never_returns_an_attachment_key(self):
        response = Mock()
        response.raise_for_status.side_effect = FileUploadApi.requests.exceptions.HTTPError("upload failed")
        session = self._mock_session(response)

        with patch.object(FileUploadApi.time, "sleep"):
            result = FileUploadApi.upload_image(
                session, "https://up.qiniup.com/", {}, self.jpeg_bytes,
                "token", self.key, max_retries=1,
            )

        self.assertIsNone(result)
        session.post.assert_called_once()

    def test_missing_token_org_or_user_fails_before_session_or_request(self):
        invalid_inputs = [
            ("", "org-123", "user-456"),
            ("token", "  ", "user-456"),
            ("token", "org-123", None),
        ]
        for token, org_id, user_id in invalid_inputs:
            with self.subTest(token=token, org_id=org_id, user_id=user_id):
                with patch.object(FileUploadApi.requests, "Session") as session_factory:
                    with self.assertRaisesRegex(ValueError, "不能为空"):
                        FileUploadApi.upload(token, org_id, user_id, [self.jpeg_bytes])
                session_factory.assert_not_called()

    def test_numeric_platform_ids_remain_compatible_with_existing_uploads(self):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"key": self.key}
        session = self._mock_session(response)
        with patch.object(FileUploadApi.requests, "Session", return_value=session), patch.object(FileUploadApi.time, "sleep"):
            result = FileUploadApi.upload("upload-token", 123, 456, [self.jpeg_bytes])
        self.assertTrue(result.endswith(".jpg"))
        self.assertTrue(session.post.call_args.kwargs["data"]["key"].startswith("upload/123/"))


if __name__ == "__main__":
    unittest.main()
