"""界面冒烟测试（不启动后端、不使用真实账号、不允许真实 API 请求）。

先在 web/ 运行 npm run build，然后执行：
    python tests/frontend_visual_smoke.py

需要 playwright 和 Chromium；可通过 CHROMIUM_EXECUTABLE 指定浏览器路径。
所有接口均在独立浏览器上下文中拦截并返回假数据，非 GET 请求会使测试失败。
"""
from __future__ import annotations

import json
import os
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "web" / "dist"
PERMISSIONS = ["users:read", "users:write", "tasks:run", "audit:read", "settings:manage"]
USER = {
    "id": 1,
    "phone": "13800000000",
    "remark": "界面测试账号（模拟数据）",
    "enable_clockin": False,
    "clockIn": {"location": {"address": "示例地址"}, "schedule": {}},
    "reportSettings": {},
    "last_execution": {},
}


class StaticHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        # 即使浏览器拦截失效，也绝不将 API 转发到任何真实后端。
        if urlparse(self.path).path.startswith("/api/"):
            self.send_error(503, "Mock API interception required")
            return
        requested = self.translate_path(urlparse(self.path).path)
        if not Path(requested).is_file():
            self.path = "/index.html"
        super().do_GET()

    def log_message(self, *_args):
        pass


def run():
    if not (DIST / "index.html").is_file():
        raise SystemExit("请先在 web/ 运行 npm run build")
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(StaticHandler, directory=str(DIST)))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f"http://127.0.0.1:{server.server_port}"
    scenarios = 0
    try:
        with sync_playwright() as p:
            executable = os.environ.get("CHROMIUM_EXECUTABLE", "/usr/bin/chromium")
            browser = p.chromium.launch(executable_path=executable, headless=True, args=["--no-sandbox"])
            try:
                for width in (375, 768, 1440):
                    for theme in ("light", "dark"):
                        for path, selector in (("/login", ".login-title"), ("/u/login", ".login-title"), ("/", ".page-title"), ("/u", ".panel-title")):
                            context = browser.new_context(viewport={"width": width, "height": 900}, color_scheme=theme)
                            failures = []
                            page = context.new_page()
                            page.on("pageerror", lambda error: failures.append(str(error)))
                            page.add_init_script(f"localStorage.setItem('theme', '{theme}')")

                            def intercept(route):
                                req = route.request
                                parsed = urlparse(req.url)
                                if not req.url.startswith(origin + "/"):
                                    failures.append(f"Unexpected external request: {parsed.netloc}")
                                    route.abort()
                                    return
                                if not parsed.path.startswith("/api/"):
                                    route.continue_()
                                    return
                                if req.method != "GET":
                                    failures.append(f"Unexpected mutation: {req.method} {parsed.path}")
                                    route.abort()
                                    return
                                if parsed.path == "/api/auth/me":
                                    payload = {"username": "界面测试", "role": "admin", "permissions": PERMISSIONS}
                                elif parsed.path == "/api/app/auth/me":
                                    payload = {"phone": "13800000000", "user_id": 1}
                                elif parsed.path == "/api/users/page":
                                    payload = {"total": 1, "items": [USER]}
                                elif parsed.path == "/api/app/me":
                                    payload = {"app_phone": "13800000000", "bound": True, "task_user": USER}
                                elif parsed.path == "/api/app/execution":
                                    payload = {"results": []}
                                else:
                                    failures.append(f"Unexpected API: {parsed.path}")
                                    route.fulfill(status=404, json={"detail": "Unmocked API"})
                                    return
                                route.fulfill(status=200, content_type="application/json", body=json.dumps(payload))

                            context.route("**/*", intercept)
                            try:
                                page.goto(origin + path, wait_until="networkidle")
                                page.locator(selector).first.wait_for(state="visible")
                                assert page.url == origin + path, f"Unexpected redirect: {page.url}"
                                assert page.locator("html").evaluate("el => el.classList.contains('dark')") == (theme == "dark")
                                # 页面整体不可横向溢出；表格自己的滚动容器不受此约束。
                                metrics = page.evaluate("""() => ({
                                  width: document.documentElement.clientWidth,
                                  scroll: document.documentElement.scrollWidth,
                                  body: document.body.scrollWidth,
                                  interactive: [...document.querySelectorAll('button, input')]
                                    .filter(el => el.getBoundingClientRect().width > 0).length
                                })""")
                                assert max(metrics["scroll"], metrics["body"]) <= metrics["width"] + 1, metrics
                                assert metrics["interactive"] > 0, "No visible controls"
                                assert not failures, failures
                                scenarios += 1
                                print(f"PASS {width}px {theme} {path}")
                            finally:
                                context.close()
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    print(f"界面冒烟测试通过：{scenarios} 个场景；全部接口均为模拟数据。")


if __name__ == "__main__":
    run()
