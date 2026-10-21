import copy
import unittest
from unittest.mock import Mock, patch

from fastapi import HTTPException
from server.account_location import (
    latest_start_location, saved_account_location, account_location_payload,
)
from server.models import User
from server import api


class AccountLocationTest(unittest.TestCase):
    def test_only_start_and_latest_record(self):
        rows = [
            {"type": "END", "attendenceTime": "2026-10-21 18:00", "latitude": 99, "longitude": 180},
            {"type": "START", "attendenceTime": "2026-10-20 08:00", "latitude": "30", "longitude": "110", "address": "旧"},
            {"type": "START", "attendenceTime": "2026-10-21 08:00", "latitude": "31.2", "longitude": "121.5", "address": "上班地址"},
        ]
        candidate = latest_start_location(rows)
        self.assertEqual(candidate["address"], "上班地址")
        self.assertEqual(candidate["latitude"], 31.2)
        self.assertEqual(candidate["source"], "最近上班打卡记录")
        self.assertIsNone(latest_start_location([rows[0]]))

    def test_no_coordinate_fabrication(self):
        for bad in ("nan", "inf", True, "91", "wrong", None):
            with self.subTest(bad=bad):
                candidate = latest_start_location([{"type": "START", "address": "有地址", "latitude": bad, "longitude": 110}])
                self.assertIsNone(candidate["latitude"])
                self.assertIn("手动补全", account_location_payload(candidate)["locationMessage"])
        self.assertEqual(latest_start_location([{"type": "START", "latitude": 0, "longitude": 0}])["latitude"], 0)

    def test_never_use_school_or_old_config_as_account_location(self):
        self.assertIsNone(saved_account_location({"latitude": 31, "longitude": 121}, {}))
        self.assertIsNotNone(saved_account_location({}, {"workLocation": {"latitude": 31, "longitude": 121}}))

    def test_fetch_never_mutates_user_or_commits(self):
        user = User(id=7, phone="test", password="test", enable_clockin=False,
                    clockIn={"location": {"latitude": "1", "longitude": "2", "address": "原地址"}},
                    userInfo={}, planInfo={})
        before = copy.deepcopy(user.model_dump())
        client = Mock()
        client.get_checkin_records.return_value = [{"type": "START", "latitude": 31, "longitude": 121, "address": "候选"}]
        with patch.object(api, "ApiClient", return_value=client), patch.object(api, "_ensure_remote_runtime"):
            payload = api._read_account_location(user)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["accountLocation"]["address"], "候选")
        self.assertEqual(user.model_dump(), before)
        client.submit_report.assert_not_called()
        client.clock_in.assert_not_called()

    def test_missing_location_is_explicit_and_keeps_existing(self):
        user = User(id=7, phone="test", password="test", clockIn={"location": {"latitude": 1, "longitude": 2}})
        client = Mock()
        client.get_checkin_records.return_value = []
        with patch.object(api, "ApiClient", return_value=client), patch.object(api, "_ensure_remote_runtime"):
            payload = api._read_account_location(user)
        self.assertIsNone(payload["accountLocation"])
        self.assertIn("保持不变", payload["locationMessage"])
        self.assertEqual(user.clockIn["location"]["latitude"], 1)

    def test_refresh_tenant_lookup_and_no_session_write(self):
        session = Mock()
        request = Mock()
        user = User(id=7, phone="test", password="test")
        operator = {"tenant_id": "tenant-a"}
        with patch.object(api, "_get_active_user_for_payload", return_value=user) as lookup, \
             patch.object(api, "_rate_limit"), patch.object(api, "get_client_ip", return_value="127.0.0.1"), \
             patch.object(api, "_read_account_location", return_value={"ok": True}):
            api.refresh_user_account(request=request, user_id=7, session=session, operator=operator)
        lookup.assert_called_once_with(session, 7, operator)
        session.add.assert_not_called()
        session.commit.assert_not_called()


if __name__ == "__main__":
    unittest.main()
