import os
import sys
import time
from pathlib import Path

# Add backend to sys.path
sys.path.insert(0, "/home/wln/famwealth/famledger/backend")

from auth import _make_token, SESSION_COOKIE
from playwright.sync_api import sync_playwright

SCREENSHOT_DIR = Path("/tmp/famledger_screenshots")
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)

PAGES = [
    ("dashboard", "http://127.0.0.1:8888/"),
    ("transactions", "http://127.0.0.1:8888/transactions"),
    ("expenses", "http://127.0.0.1:8888/expenses"),
    ("analytics", "http://127.0.0.1:8888/analytics"),
    ("insights", "http://127.0.0.1:8888/insights"),
    ("calendar", "http://127.0.0.1:8888/calendar"),
    ("emails", "http://127.0.0.1:8888/emails"),
    ("rules", "http://127.0.0.1:8888/rules"),
    ("debts", "http://127.0.0.1:8888/debts"),
    ("settings", "http://127.0.0.1:8888/settings"),
]

def main():
    token = _make_token("qq", persist=True)
    print(f"Generated session token for qq: {token[:20]}...")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path="/usr/bin/google-chrome",
            headless=True,
            args=["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"]
        )
        context = browser.new_context(
            viewport={"width": 1440, "height": 900},
            device_scale_factor=1.5,
        )
        # Set session cookie
        context.add_cookies([{
            "name": SESSION_COOKIE,
            "value": token,
            "domain": "127.0.0.1",
            "path": "/",
            "httpOnly": True,
            "secure": False,
            "sameSite": "Lax",
        }])

        page = context.new_page()

        console_errors = []
        failed_requests = []
        page.on("requestfailed", lambda req: failed_requests.append(f"FAILED: {req.url} {req.failure}"))
        page.on("response", lambda resp: failed_requests.append(f"HTTP {resp.status}: {resp.url}") if resp.status >= 400 else None)
        page.on("console", lambda msg: console_errors.append(f"[{msg.type}] {msg.text}") if msg.type in ("error", "warning") else None)
        page.on("pageerror", lambda err: console_errors.append(f"[pageerror] {err}"))

        for name, url in PAGES:
            print(f"Navigating to {name} ({url})...")
            try:
                page.goto(url, wait_until="networkidle", timeout=10000)
            except Exception as e:
                print(f"  Timeout/warning on {name}: {e}")
            page.wait_for_timeout(1000)

            screenshot_path = SCREENSHOT_DIR / f"{name}.png"
            page.screenshot(path=str(screenshot_path), full_page=False)
            print(f"  Saved screenshot to {screenshot_path}")

        print("\nFailed HTTP requests:")
        for r in set(failed_requests):
            print(f"  {r}")

        print("\nConsole errors/warnings encountered:")
        for err in console_errors[:15]:
            print(f"  {err}")

        browser.close()

if __name__ == "__main__":
    main()
