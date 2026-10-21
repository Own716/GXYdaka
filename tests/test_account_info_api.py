import copy
import unittest
from unittest.mock import Mock, patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from server import api


class AccountInfoApiTest(unittest.TestCase):
    def setUp(self):
        self.app = FastAPI()
        self.app.include_router(api.router, prefix="/api")
        self.app.dependency_overrides[api.require_users_write] = lambda: {
            "sub": "test-admin", "role": "admin", "tenant_id": "test-tenant"
        }
        self.client = TestClient(self.app)
        self.credentials = {"phone": "13900000000", "password": " secret-with-spaces "}
        self.user_info = {"nikeName": "测试同学", "token": "do-not-return-token", "userId": "student", "userType": "student",
                          "orgJson": {"orgName": "测试学校"}}
        self.plan_info = {"planId": "plan", "planName": "实习计划"}
        self.job_info = {"jobAddress": "上海市测试岗位地址", "latitude": 31.2, "longitude": 121.4,
                         "practiceCompanyEntity": {"companyName": "测试企业", "companyAddress": "上海市企业地址"}}
        self.records = []
        self.remote = Mock()
        self.remote.get_job_info.side_effect = lambda: copy.deepcopy(self.job_info)
        self.remote.get_checkin_records.side_effect = lambda: copy.deepcopy(self.records)
        self.config = None

    def make_remote(self, config):
        self.config = config
        self.remote.login.side_effect = lambda: config.update_config(copy.deepcopy(self.user_info), "userInfo")
        self.remote.fetch_internship_plan.side_effect = lambda: config.update_config(copy.deepcopy(self.plan_info), "planInfo")
        return self.remote

    def request_preview(self):
        with (
            patch.object(api, "ApiClient", side_effect=self.make_remote),
            patch.object(api, "_rate_limit"),
            patch.object(api, "get_session") as session,
            patch.object(api, "engine") as engine,
            patch.object(api, "User") as user_model,
            patch.object(api, "add_user_job") as add_job,
            patch.object(api, "run_task_by_config") as run_task,
        ):
            response = self.client.post("/api/users/account-info", json=self.credentials)
        session.assert_not_called()
        engine.connect.assert_not_called()
        user_model.assert_not_called()
        add_job.assert_not_called()
        run_task.assert_not_called()
        self.remote.submit_report.assert_not_called()
        self.remote.clock_in.assert_not_called()
        return response

    def test_new_account_is_prefilled_without_creation_or_secret_response(self):
        response = self.request_preview()
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["ready"])
        self.assertEqual(data["profile"]["name"], "测试同学")
        self.assertEqual(data["profile"]["companyName"], "测试企业")
        self.assertEqual(data["accountLocation"]["latitude"], 31.2)
        self.assertEqual(self.config.get_value("config.user.password"), self.credentials["password"])
        for secret in [self.credentials["password"], "do-not-return-token", "userInfo", "password"]:
            self.assertNotIn(secret, response.text)

    def test_explicit_work_location_has_priority_and_skips_record_lookup(self):
        self.user_info["workLocation"] = {"address": "明确上班位置", "latitude": 30.1, "longitude": 120.2}
        response = self.request_preview()
        self.assertTrue(response.json()["ready"])
        self.assertEqual(response.json()["accountLocation"]["address"], "明确上班位置")
        self.remote.get_checkin_records.assert_not_called()

    def test_latest_start_record_is_preferred_to_job_coordinates(self):
        self.records = [
            {"type": "END", "createTime": "2026-10-21 19:00:00", "address": "下班", "latitude": 1, "longitude": 2},
            {"type": "START", "createTime": "2026-10-21 08:00:00", "address": "真实上班", "latitude": 30.2, "longitude": 120.1},
        ]
        response = self.request_preview()
        self.assertEqual(response.json()["accountLocation"]["address"], "真实上班")
        self.assertEqual(response.json()["accountLocation"]["source"], "最近上班打卡记录")

    def test_record_failure_can_fall_back_to_actual_job_location(self):
        self.remote.get_checkin_records.side_effect = RuntimeError("private remote response")
        response = self.request_preview()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ready"])
        self.assertTrue(response.json()["warnings"])
        self.assertNotIn("private remote response", response.text)

    def test_missing_coordinates_are_not_fabricated(self):
        self.job_info.pop("latitude")
        self.job_info.pop("longitude")
        response = self.request_preview()
        self.assertFalse(response.json()["ready"])
        self.assertIsNone(response.json()["accountLocation"]["latitude"])
        self.assertTrue(response.json()["warnings"])

    def test_invalid_credentials_and_login_errors_do_not_echo_password(self):
        secret = self.credentials["password"]
        with patch.object(api, "ApiClient") as remote:
            for body in [{"password": secret}, {"phone": "x", "password": secret},
                         {"phone": self.credentials["phone"], "password": "x" * 257},
                         {"phone": self.credentials["phone"]}]:
                response = self.client.post("/api/users/account-info", json=body)
                self.assertEqual(response.status_code, 400)
                self.assertNotIn(secret, response.text)
                self.assertNotIn("x" * 257, response.text)
            remote.assert_not_called()
        with patch.object(api, "ApiClient", side_effect=RuntimeError(secret)), patch.object(api, "_rate_limit"):
            response = self.client.post("/api/users/account-info", json=self.credentials)
        self.assertEqual(response.status_code, 400)
        self.assertNotIn(secret, response.text)
        self.assertNotIn(secret, repr(api.AccountInfoRequest(**self.credentials)))

    def test_rate_limit_rejects_before_remote_login(self):
        with patch.object(api, "_rate_limit", side_effect=HTTPException(status_code=429, detail="too many")), patch.object(api, "ApiClient") as remote:
            response = self.client.post("/api/users/account-info", json=self.credentials)
        self.assertEqual(response.status_code, 429)
        remote.assert_not_called()

    def test_permission_denial_prevents_remote_access(self):
        def denied():
            raise HTTPException(status_code=403, detail="权限不足")
        self.app.dependency_overrides[api.require_users_write] = denied
        with patch.object(api, "ApiClient") as remote:
            response = self.client.post("/api/users/account-info", json=self.credentials)
        self.assertEqual(response.status_code, 403)
        remote.assert_not_called()


if __name__ == "__main__":
    unittest.main()
