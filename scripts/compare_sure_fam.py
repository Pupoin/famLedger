import os
import sys
import time
from pathlib import Path

# Add backend to sys.path
sys.path.insert(0, "/home/wln/famwealth/famledger/backend")

from auth import _make_token, SESSION_COOKIE
from playwright.sync_api import sync_playwright

COMPARE_DIR = Path("/tmp/sure_vs_famledger")
COMPARE_DIR.mkdir(parents=True, exist_ok=True)

def run_comparison():
    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path="/usr/bin/google-chrome",
            headless=True,
            args=["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"]
        )

        # ── 1. Log in to Sure on 3000 ─────────────────────────────
        print("Logging into Sure (port 3000)...")
        sure_desktop = browser.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=1.5)
        page_sure = sure_desktop.new_page()
        page_sure.goto("http://127.0.0.1:3000/sessions/new", wait_until="networkidle")
        
        # Fill login form
        page_sure.fill('input[name="email"]', "q@q.com")
        page_sure.fill('input[name="password"]', "password123")
        page_sure.click('button:has-text("Log in")')
        page_sure.wait_for_timeout(2500)
        print(f"Logged into Sure. Current URL: {page_sure.url}")

        # Capture Sure Desktop Dashboard
        page_sure.goto("http://127.0.0.1:3000/", wait_until="networkidle")
        page_sure.wait_for_timeout(1500)
        page_sure.screenshot(path=str(COMPARE_DIR / "sure_desktop_dashboard.png"))

        # Capture Sure Desktop Transactions
        page_sure.goto("http://127.0.0.1:3000/transactions", wait_until="networkidle")
        page_sure.wait_for_timeout(1500)
        page_sure.screenshot(path=str(COMPARE_DIR / "sure_desktop_transactions.png"))

        # Sure cookies for mobile
        cookies = sure_desktop.cookies()

        # Sure Mobile
        sure_mobile = browser.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2, is_mobile=True, has_touch=True)
        sure_mobile.add_cookies(cookies)
        page_sure_m = sure_mobile.new_page()

        # Capture Sure Mobile Dashboard
        page_sure_m.goto("http://127.0.0.1:3000/", wait_until="networkidle")
        page_sure_m.wait_for_timeout(1500)
        page_sure_m.screenshot(path=str(COMPARE_DIR / "sure_mobile_dashboard.png"))

        # Open Sure Mobile Sidebar (Left icon)
        panel_btn = page_sure_m.query_selector('button[data-action*="openMobileSidebar"], [data-action*="openMobileSidebar"]')
        if panel_btn:
            panel_btn.click()
            page_sure_m.wait_for_timeout(1000)
            page_sure_m.screenshot(path=str(COMPARE_DIR / "sure_mobile_sidebar.png"))

        # Capture Sure Mobile Transactions
        page_sure_m.goto("http://127.0.0.1:3000/transactions", wait_until="networkidle")
        page_sure_m.wait_for_timeout(1500)
        page_sure_m.screenshot(path=str(COMPARE_DIR / "sure_mobile_transactions.png"))

        # ── 2. FamLedger on 8888 ──────────────────────────────────
        token = _make_token("qq", persist=True)
        
        fam_desktop = browser.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=1.5)
        fam_desktop.add_cookies([{
            "name": SESSION_COOKIE,
            "value": token,
            "domain": "127.0.0.1",
            "path": "/",
            "httpOnly": True,
            "secure": False,
            "sameSite": "Lax",
        }])
        page_fam = fam_desktop.new_page()

        page_fam.goto("http://127.0.0.1:8888/", wait_until="networkidle")
        page_fam.wait_for_timeout(1000)
        page_fam.screenshot(path=str(COMPARE_DIR / "fam_desktop_dashboard.png"))

        page_fam.goto("http://127.0.0.1:8888/transactions", wait_until="networkidle")
        page_fam.wait_for_timeout(1000)
        page_fam.screenshot(path=str(COMPARE_DIR / "fam_desktop_transactions.png"))

        # FamLedger Mobile
        fam_mobile = browser.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2, is_mobile=True, has_touch=True)
        fam_mobile.add_cookies([{
            "name": SESSION_COOKIE,
            "value": token,
            "domain": "127.0.0.1",
            "path": "/",
            "httpOnly": True,
            "secure": False,
            "sameSite": "Lax",
        }])
        page_fam_m = fam_mobile.new_page()

        page_fam_m.goto("http://127.0.0.1:8888/", wait_until="networkidle")
        page_fam_m.wait_for_timeout(1000)
        page_fam_m.screenshot(path=str(COMPARE_DIR / "fam_mobile_dashboard.png"))

        # Open Fam Mobile Accounts Drawer
        card_btn = page_fam_m.query_selector('nav button:has-text("Accounts"), header button')
        if card_btn:
            card_btn.click()
            page_fam_m.wait_for_timeout(1000)
            page_fam_m.screenshot(path=str(COMPARE_DIR / "fam_mobile_sidebar.png"))

        page_fam_m.goto("http://127.0.0.1:8888/transactions", wait_until="networkidle")
        page_fam_m.wait_for_timeout(1000)
        page_fam_m.screenshot(path=str(COMPARE_DIR / "fam_mobile_transactions.png"))

        browser.close()
        print("All comparison screenshots saved to /tmp/sure_vs_famledger/")

if __name__ == "__main__":
    run_comparison()
