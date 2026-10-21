import unittest
from types import SimpleNamespace
from unittest.mock import patch

from sqlmodel import Session, SQLModel, create_engine

from server import api
from server.auth import hash_password
from server.models import AdminUser, AuditLog, DEFAULT_TENANT_ID
from server.rate_limit import check_rate_limit, clear_memory_rate_limits


class AdminLoginRateLimitTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        SQLModel.metadata.create_all(self.engine)
        self.addCleanup(self.engine.dispose)
        clear_memory_rate_limits()
        self.addCleanup(clear_memory_rate_limits)
        with Session(self.engine) as session:
            session.add(AdminUser(username="admin", password_hash=hash_password("correct-password-123"), role="admin"))
            session.commit()
        self.request = SimpleNamespace(headers={}, client=SimpleNamespace(host="203.0.113.10"))
        self.response = SimpleNamespace(headers={}, set_cookie=lambda *args, **kwargs: None)

    def test_admin_login_ignores_old_saturated_buckets_and_allows_repeated_success(self):
        with (
            patch.dict("os.environ", {
                "RATE_LIMIT_BACKEND": "memory",
                "APP_SECRET": "test-secret-value-with-more-than-thirty-two-chars",
            }, clear=False),
            patch.object(api, "engine", self.engine),
            patch.object(api, "_rate_limit", wraps=api._rate_limit) as rate_limit,
        ):
            # 旧限流桶已满也不应再阻止管理员登录；无需清理运行中数据库。
            for _ in range(10):
                check_rate_limit("admin_login:ip:203.0.113.10", 10, 60)
            principal = api._rate_limit_principal_digest(DEFAULT_TENANT_ID, "admin")
            for _ in range(5):
                check_rate_limit(f"admin_login:principal:{DEFAULT_TENANT_ID}:{principal}", 5, 60)
            for _ in range(11):
                result = api.admin_login(
                    request=self.request,
                    response=self.response,
                    req=api.LoginRequest(username="admin", password="correct-password-123"),
                )
                self.assertEqual(result["role"], "admin")
            rate_limit.assert_not_called()

        with Session(self.engine) as session:
            logs = session.exec(api.select(AuditLog).where(AuditLog.action == "auth.login")).all()
        self.assertEqual(len(logs), 11)


if __name__ == "__main__":
    unittest.main()
