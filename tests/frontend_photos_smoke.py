"""Photo-library UI E2E smoke test; no backend, real account, or real mutations.

Run after rebuilding the frontend (the test deliberately serves web/dist only):
    cd /workspace/GXYdaka && python tests/frontend_photos_smoke.py

All API and external requests are intercepted. Only the named photo endpoints are
mocked; every other API request fails the test. The edit view's external map iframe
is aborted without contacting its host. Uses in-memory Pillow-generated images.
"""
from __future__ import annotations

import json
import os
import re
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from pathlib import Path
from threading import Thread
from urllib.parse import urlparse

from PIL import Image
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "web" / "dist"
ADMIN_PERMISSIONS = ["users:read", "users:write", "tasks:run", "audit:read", "settings:manage"]
PHOTO_BASES = {
    "/u/settings": "/api/app/clock-in/photos",
    "/edit/1": "/api/users/1/clock-in/photos",
}

USER = {
    "id": 1,
    "phone": "13800000000",
    "remark": "照片 UI 模拟账号",
    "enable_clockin": False,
    "clockIn": {
        "photoEnabled": False,
        "location": {"address": "模拟地址", "latitude": "30.572800", "longitude": "104.066800"},
        "schedule": {"startTime": "07:30", "endTime": "18:00", "skipHolidays": False},
    },
    "reportSettings": {},
    "pushNotifications": [],
    "last_execution": {},
}


class StaticHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        path = urlparse(self.path).path
        # Defense in depth: API requests must be intercepted in Playwright and
        # can never be routed to a real service by this static-only server.
        if path.startswith("/api/"):
            self.send_error(503, "Mock API interception required")
            return
        requested = self.translate_path(path)
        if not Path(requested).is_file():
            self.path = "/index.html"
        super().do_GET()

    def log_message(self, *_args):
        pass


def pillow_image_bytes(fmt: str, color: tuple[int, int, int]) -> bytes:
    image = Image.new("RGB", (48, 32), color)
    out = BytesIO()
    image.save(out, format=fmt)
    return out.getvalue()


def json_response(route, payload, status: int = 200):
    route.fulfill(status=status, content_type="application/json", body=json.dumps(payload, ensure_ascii=False))


def run_case(browser, origin: str, path: str, width: int, theme: str) -> None:
    base = PHOTO_BASES[path]
    photos: list[dict[str, object]] = []
    api_calls: list[tuple[str, str]] = []
    failures: list[str] = []
    first_list_get = True
    next_id = 1
    context = browser.new_context(viewport={"width": width, "height": 940}, color_scheme=theme)
    page = context.new_page()
    page.set_default_timeout(8000)
    page.add_init_script(
        f"""(() => {{
          if (location.origin !== {json.dumps(origin)}) return;
          localStorage.setItem('theme', {json.dumps(theme)});
          sessionStorage.setItem('user_auth_meta', JSON.stringify({{authed:true,phone:'13800000000',userId:1}}));
          sessionStorage.setItem('auth_meta', JSON.stringify({{authed:true,username:'mock-admin',role:'admin',permissions:{json.dumps(ADMIN_PERMISSIONS)}}}));
        }})();"""
    )
    page.on("pageerror", lambda error: failures.append(f"pageerror: {error}"))

    def intercept(route):
        nonlocal first_list_get, next_id
        request = route.request
        parsed = urlparse(request.url)
        if parsed.netloc == "www.mapchaxun.cn" or parsed.netloc.endswith(".mapchaxun.cn"):
            # UserEdit embeds this external map; explicitly abort it, do not fetch it.
            route.abort()
            return
        if parsed.netloc != urlparse(origin).netloc or parsed.scheme != "http":
            failures.append(f"Unexpected external request blocked: {request.url}")
            route.abort()
            return
        if not parsed.path.startswith("/api/"):
            route.continue_()
            return

        method = request.method.upper()
        api_calls.append((method, parsed.path))
        if method == "GET" and parsed.path == "/api/auth/me":
            json_response(route, {"username": "mock-admin", "role": "admin", "permissions": ADMIN_PERMISSIONS})
            return
        if method == "GET" and parsed.path == "/api/app/me":
            json_response(route, {"app_phone": "13800000000", "bound": True, "task_user": USER})
            return
        if method == "GET" and parsed.path == "/api/users/1":
            json_response(route, USER)
            return
        if method == "GET" and parsed.path == base:
            if first_list_get:
                first_list_get = False
                json_response(route, {"detail": "mock initial list failure"}, status=503)
            else:
                json_response(route, {"photos": photos, "enabled": False})
            return
        if method == "GET" and parsed.path.startswith(base + "/"):
            # A tiny but valid in-memory JPEG; no network/image fixture is used.
            jpeg = pillow_image_bytes("JPEG", (55, 135, 210))
            route.fulfill(status=200, content_type="image/jpeg", body=jpeg)
            return
        if method == "POST" and parsed.path == base:
            content_type = request.headers.get("content-type", "")
            body = request.post_data_buffer or b""
            if "multipart/form-data" not in content_type.lower():
                failures.append(f"Photo upload was not multipart: {content_type}")
                json_response(route, {"detail": "Expected multipart"}, status=400)
                return
            filenames = re.findall(rb'filename="([^"]+)"', body)
            if not filenames:
                failures.append("Multipart photo upload contained no file fields")
            for filename in filenames:
                name = filename.decode("utf-8", errors="replace")
                photos.append({"id": str(next_id), "name": name})
                next_id += 1
            json_response(route, {"photos": photos, "enabled": False})
            return
        if method == "DELETE" and parsed.path.startswith(base + "/"):
            photo_id = parsed.path.rsplit("/", 1)[-1]
            photos[:] = [photo for photo in photos if str(photo["id"]) != photo_id]
            json_response(route, {"photos": photos, "enabled": False})
            return

        failures.append(f"Unexpected API request blocked: {method} {parsed.path}")
        json_response(route, {"detail": "Unmocked API route"}, status=404)

    context.route("**/*", intercept)
    try:
        page.goto(origin + path, wait_until="domcontentloaded")
        if path == "/edit/1":
            page.get_by_role("tab", name="打卡设置").click()
        library = page.locator(".photo-library")
        library.wait_for(state="visible")
        picker = page.get_by_label("选择多张打卡照片")
        refresh = page.get_by_role("button", name="刷新照片")

        # Exercise a failed photo-list request and the in-component retry affordance.
        page.locator(".photo-library .el-alert").first.wait_for(state="visible")
        assert picker.is_disabled(), "The picker should remain disabled until a failed list is retried"
        refresh.click()
        page.get_by_text("还没有照片，点击“添加照片”可一次选择多张。", exact=True).wait_for(state="visible")

        assert page.get_by_role("switch", name="随机提交打卡照片").get_attribute("aria-checked") == "false"
        initial_config_patches = sum(1 for method, endpoint in api_calls if endpoint in {"/api/app/me", "/api/users/1"} and method in {"PATCH", "PUT"})
        assert initial_config_patches == 0

        # Two genuine, in-memory Pillow JPEG images selected in one operation.
        photo_a = pillow_image_bytes("JPEG", (210, 60, 55))
        photo_b = pillow_image_bytes("JPEG", (45, 180, 100))
        picker.set_input_files([
            {"name": "morning.jpg", "mimeType": "image/jpeg", "buffer": photo_a},
            {"name": "evening.jpg", "mimeType": "image/jpeg", "buffer": photo_b},
        ])
        page.locator(".photo-tile").nth(1).wait_for(state="visible")
        assert page.locator(".photo-tile").count() == 2, "Expected two photo thumbnails"
        assert page.locator(".photo-tile .el-image img").count() == 2, "Expected two rendered thumbnail images"
        assert page.get_by_text("2 / 20 张", exact=False).count() >= 1
        assert page.get_by_role("switch", name="随机提交打卡照片").get_attribute("aria-checked") == "false", "Upload must not enable photo submission"
        assert not any(method == "PATCH" and endpoint in {"/api/app/me", "/api/users/1"} for method, endpoint in api_calls), "Uploading must not PATCH user configuration"

        # Invalid MIME, too many selected files, and a >10 MiB image are rejected client-side.
        post_count = sum(method == "POST" and endpoint == base for method, endpoint in api_calls)
        picker.set_input_files({"name": "not-an-image.txt", "mimeType": "text/plain", "buffer": b"not an image"})
        page.get_by_text("不是支持的 JPG、PNG 或 WebP 图片", exact=False).wait_for(state="visible")
        picker.set_input_files([
            {"name": f"extra-{i}.png", "mimeType": "image/png", "buffer": photo_b}
            for i in range(19)
        ])
        page.get_by_text("最多保存 20 张照片", exact=False).wait_for(state="visible")
        picker.set_input_files({"name": "oversized.jpg", "mimeType": "image/jpeg", "buffer": b"x" * (10 * 1024 * 1024 + 1)})
        page.get_by_text("“oversized.jpg”为空或超过 10 MB", exact=False).wait_for(state="visible")
        assert sum(method == "POST" and endpoint == base for method, endpoint in api_calls) == post_count, "Invalid file selections must not POST"

        # An unsaved manual toggle changes local state only; do not click the page Save button.
        toggle = page.locator(".photo-heading .el-switch")
        toggle_input = toggle.locator("input[role='switch']")
        toggle.click()
        assert toggle_input.get_attribute("aria-checked") == "true"
        assert not any(method == "PATCH" and endpoint in {"/api/app/me", "/api/users/1"} for method, endpoint in api_calls), "An unsaved switch change must not PATCH configuration"
        toggle.click()
        assert toggle_input.get_attribute("aria-checked") == "false"

        # Confirm exactly one deletion, then empty the library and verify the no-photo warning.
        page.get_by_role("button", name="删除照片 morning.jpg").click()
        page.locator(".el-message-box__title").get_by_text("删除打卡照片", exact=True).wait_for(state="visible")
        page.locator(".el-message-box__btns").get_by_role("button", name="删除").click()
        page.locator(".photo-tile").wait_for(state="visible")
        assert page.locator(".photo-tile").count() == 1
        assert page.get_by_text("1 / 20 张", exact=False).count() >= 1
        remaining = page.locator(".photo-tile").locator("button[aria-label^='删除照片']")
        remaining.click()
        page.locator(".el-message-box__btns").get_by_role("button", name="删除").click()
        page.locator(".photo-tile").wait_for(state="detached")
        assert page.get_by_text("0 / 20 张", exact=False).count() >= 1
        toggle.click()
        page.get_by_text("尚无可用照片：开启后将暂停提交", exact=False).wait_for(state="visible")

        # Lightweight responsive check scoped to the new feature so unrelated app chrome
        # does not mask a photo-library overflow regression.
        bounds = library.bounding_box()
        assert bounds is not None and bounds["x"] >= -1 and bounds["x"] + bounds["width"] <= width + 1, f"Photo library overflows viewport: {bounds}, width={width}"
        assert page.locator("html").evaluate("el => el.classList.contains('dark')") == (theme == "dark"), f"Theme mismatch for {theme}"
        assert not failures, failures
        assert not any(method == "PATCH" for method, _endpoint in api_calls), "No configuration PATCH is permitted in this test"
        expected_mutations = [method for method, endpoint in api_calls if (endpoint == base or endpoint.startswith(base + "/")) and method in {"POST", "DELETE"}]
        assert expected_mutations == ["POST", "DELETE", "DELETE"], expected_mutations
        print(f"PASS {path} {width}px {theme}: two uploads, client validation, local toggle, delete, empty warning, retry")
    finally:
        context.close()


def run() -> None:
    if not (DIST / "index.html").is_file():
        raise SystemExit("Missing web/dist/index.html; rebuild the frontend first with `cd web && npm run build`.")
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(StaticHandler, directory=str(DIST)))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f"http://127.0.0.1:{server.server_port}"
    try:
        # Fail clearly before the first case if the static bundle is not serveable.
        import urllib.request
        with urllib.request.urlopen(origin + "/index.html", timeout=5) as response:
            if response.status != 200:
                raise SystemExit(f"Static dist server returned HTTP {response.status}")
        with sync_playwright() as p:
            executable = os.environ.get("CHROMIUM_EXECUTABLE", "/usr/bin/chromium")
            browser = p.chromium.launch(executable_path=executable, headless=True, args=["--no-sandbox"])
            try:
                # Exercise both entry points, both target widths, and both themes
                # without multiplying the suite into a large visual matrix.
                run_case(browser, origin, "/u/settings", 375, "light")
                run_case(browser, origin, "/edit/1", 1440, "dark")
                run_case(browser, origin, "/u/settings", 1440, "dark")
                run_case(browser, origin, "/edit/1", 375, "light")
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    print("照片 UI Playwright 冒烟测试通过：4 个模拟浏览器场景；无真实后端、远程请求或账号修改。")


if __name__ == "__main__":
    run()
