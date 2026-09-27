import os
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

INSPECT_DIR = Path("/tmp/sure_inspect")
INSPECT_DIR.mkdir(parents=True, exist_ok=True)

def inspect():
    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path="/usr/bin/google-chrome",
            headless=True,
            args=["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"]
        )
        ctx = browser.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=1.5)
        page = ctx.new_page()

        # Login to Sure
        page.goto("http://127.0.0.1:3000/sessions/new")
        page.fill('input[type="email"], input[name*="email"]', "q@q.com")
        page.fill('input[type="password"]', "password123")
        page.click('button:has-text("Log in"), input[type="submit"]')
        page.wait_for_timeout(1000)

        pages_to_visit = [
            ("settings_profile", "http://127.0.0.1:3000/settings/profile"),
            ("settings_preferences", "http://127.0.0.1:3000/settings/preferences"),
            ("settings_hosting", "http://127.0.0.1:3000/settings/hosting"),
            ("settings_security", "http://127.0.0.1:3000/settings/security"),
            ("rules", "http://127.0.0.1:3000/rules"),
            ("reports", "http://127.0.0.1:3000/reports"),
        ]

        for name, url in pages_to_visit:
            try:
                page.goto(url, wait_until="networkidle")
                page.wait_for_timeout(1000)
                page.screenshot(path=str(INSPECT_DIR / f"{name}.png"))
                print(f"Captured {name}")
            except Exception as e:
                print(f"Failed {name}: {e}")

        browser.close()

if __name__ == "__main__":
    inspect()
