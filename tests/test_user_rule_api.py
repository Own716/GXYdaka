import copy
import unittest
from unittest.mock import Mock, patch
from fastapi import HTTPException
from server import api
from server.models import User, UserUpdate
from server.util.Config import ConfigManager


class UserRuleApiTest(unittest.TestCase):
    def test_preview_is_read_only(self):
        req = api.SchedulePreviewRequest(clockIn={"schedule": {"startDate": "2030-01-01", "endDate": "2030-01-04", "weekdays": [1, 2, 3, 4, 5]}})
        with patch.object(api, "engine") as engine:
            result = api.preview_schedule(req, operator={})
        self.assertEqual(result["dates"], ["2030-01-01", "2030-01-02", "2030-01-03", "2030-01-04"])
        engine.connect.assert_not_called()

    def test_bad_rules_fail_before_persistence_or_job_rebuild(self):
        user = User(id=1, phone="test", password="test", enable_clockin=False)
        before = copy.deepcopy(user.model_dump())
        session = Mock()
        for update in (
            UserUpdate(clockIn={"schedule": {"startDate": "2030-02-01", "endDate": "2030-01-01"}}),
            UserUpdate(reportSettings={"weekly": {"minWords": 500, "maxWords": 100}}),
            UserUpdate(reportSettings={"weekly": {"submitTime": 8}}),
            UserUpdate(reportSettings={"monthly": {"submitTime": "fake"}}),
        ):
            with patch.object(api, "_get_active_user_for_payload", return_value=user), patch.object(api, "add_user_job") as jobs:
                with self.assertRaises(HTTPException) as raised:
                    api.update_user(session=session, user_id=1, user_update=update, operator={})
                self.assertEqual(raised.exception.status_code, 400)
                jobs.assert_not_called()
        session.commit.assert_not_called()
        self.assertEqual(user.model_dump(), before)

    def test_report_content_rejected_before_remote_metadata_or_submit(self):
        config = ConfigManager(config={"config": {"reportSettings": {"weekly": {"minWords": 5, "maxWords": 10}}}})
        client = Mock()
        for text in ("短", "这是一段超过十个字符长度的测试内容"):
            with self.assertRaises(ValueError):
                api._build_report_info(api_client=client, config=config,
                                       meta={"report_type": "week"}, content=text,
                                       target_period="2030-01-01")
        client.get_submitted_reports_info.assert_not_called()
        client.submit_report.assert_not_called()

    def test_month_last_valid_and_wrong_time_rejected(self):
        api._validate_user_rules(report_settings={"monthly": {"submitTime": "last", "submitAt": "18:30"}})
        with self.assertRaises(HTTPException):
            api._validate_user_rules(report_settings={"monthly": {"submitAt": "99:99"}})

    def test_http_preview_and_location_contract_without_writes(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        app = FastAPI()
        app.include_router(api.router, prefix="/api")
        session = Mock()
        app.dependency_overrides[api.get_session] = lambda: session
        app.dependency_overrides[api.require_users_read] = lambda: {"tenant_id": "test"}
        app.dependency_overrides[api.require_users_write] = lambda: {"tenant_id": "test"}
        client = TestClient(app)
        response = client.post("/api/schedule/preview", json={"clockIn": {"schedule": {
            "startDate": "2030-01-01", "endDate": "2030-01-03", "weekdays": [2, 4]
        }}})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["dates"], ["2030-01-01", "2030-01-03"])
        self.assertEqual(client.post("/api/schedule/preview", json={"clockIn": {
            "schedule": {"weekdays": [8]}
        }}).status_code, 400)
        user = User(id=9, phone="test", password="test", enable_clockin=False)
        payload = {"ok": True, "accountLocation": {"latitude": 31, "longitude": 121, "source": "最近上班打卡记录"}, "locationMessage": "请核对"}
        with patch.object(api, "_get_active_user_for_payload", return_value=user), \
             patch.object(api, "_read_account_location", return_value=payload), \
             patch.object(api, "_rate_limit"):
            response = client.post("/api/users/9/refresh")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), payload)
        session.add.assert_not_called()
        session.commit.assert_not_called()


if __name__ == "__main__":
    unittest.main()
