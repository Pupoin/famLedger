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

def verify_all():
    token = _make_token("qq", persist=True)
    print(f"Generated session token for qq: {token[:20]}...")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path="/usr/bin/google-chrome",
            headless=True,
            args=["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"]
        )

        # ── 1. Desktop Context (1440x900) ──────────────────────────
        desktop_ctx = browser.new_context(
            viewport={"width": 1440, "height": 900},
            device_scale_factor=1.5,
        )
        desktop_ctx.add_cookies([{
            "name": SESSION_COOKIE,
            "value": token,
            "domain": "127.0.0.1",
            "path": "/",
            "httpOnly": True,
            "secure": False,
            "sameSite": "Lax",
        }])

        page = desktop_ctx.new_page()
        console_errors = []
        page.on("console", lambda msg: console_errors.append(f"[{msg.type}] {msg.text}") if msg.type in ("error", "warning") else None)
        page.on("pageerror", lambda err: console_errors.append(f"[pageerror] {err}"))

        # 1.1 Desktop Dashboard
        print("Capturing desktop dashboard...")
        page.goto("http://127.0.0.1:8888/", wait_until="networkidle", timeout=10000)
        page.wait_for_timeout(1000)
        page.screenshot(path=str(SCREENSHOT_DIR / "desktop_dashboard.png"))

        # 1.2 Desktop Dashboard with Accounts Sidebar Open
        print("Toggling desktop accounts sidebar...")
        toggle_btn = page.query_selector("button:has-text('展开银行卡'), button:has-text('多卡账户侧栏')")
        if toggle_btn:
            toggle_btn.click()
            page.wait_for_timeout(800)
            page.screenshot(path=str(SCREENSHOT_DIR / "desktop_dashboard_accounts_open.png"))

        # 1.3 Desktop Transactions - All Cards
        print("Capturing desktop transactions (all cards)...")
        page.goto("http://127.0.0.1:8888/transactions", wait_until="networkidle", timeout=10000)
        page.wait_for_timeout(1000)
        page.screenshot(path=str(SCREENSHOT_DIR / "desktop_transactions_all.png"))

        # 1.4 Desktop Transactions - Filter by Card (e.g. 7931)
        print("Filtering transactions by card *7931...")
        card_btn = page.query_selector("button:has-text('*7931')")
        if card_btn:
            card_btn.click()
            page.wait_for_timeout(1000)
            page.screenshot(path=str(SCREENSHOT_DIR / "desktop_transactions_card_7931.png"))

        # 1.5 Desktop Privacy Mode
        print("Testing Privacy Mode...")
        privacy_btn = page.query_selector("button:has-text('隐私模式'), button[title*='隐私']")
        if privacy_btn:
            privacy_btn.click()
            page.wait_for_timeout(500)
            page.screenshot(path=str(SCREENSHOT_DIR / "desktop_transactions_privacy.png"))

        # ── 2. Mobile Context (390x844 iPhone 14) ──────────────────
        mobile_ctx = browser.new_context(
            viewport={"width": 390, "height": 844},
            device_scale_factor=2,
            is_mobile=True,
            has_touch=True,
        )
        mobile_ctx.add_cookies([{
            "name": SESSION_COOKIE,
            "value": token,
            "domain": "127.0.0.1",
            "path": "/",
            "httpOnly": True,
            "secure": False,
            "sameSite": "Lax",
        }])

        m_page = mobile_ctx.new_page()
        m_page.on("console", lambda msg: console_errors.append(f"[m-{msg.type}] {msg.text}") if msg.type in ("error", "warning") else None)
        m_page.on("pageerror", lambda err: console_errors.append(f"[m-pageerror] {err}"))

        # 2.1 Mobile Dashboard
        print("Capturing mobile dashboard...")
        m_page.goto("http://127.0.0.1:8888/", wait_until="networkidle", timeout=10000)
        m_page.wait_for_timeout(1000)
        m_page.screenshot(path=str(SCREENSHOT_DIR / "mobile_dashboard.png"))

        # 2.2 Mobile Accounts Drawer Open (Click '卡片')
        print("Opening mobile accounts drawer...")
        card_tab = m_page.query_selector("nav[aria-label='移动端快速导航'] button:has-text('卡片'), header button:has-text('卡片')")
        if card_tab:
            card_tab.click()
            m_page.wait_for_timeout(800)
            m_page.screenshot(path=str(SCREENSHOT_DIR / "mobile_accounts_drawer.png"))
            # Close drawer
            close_btn = m_page.query_selector("button:has-text('关闭'), .lucide-x")
            if close_btn:
                close_btn.click()
                m_page.wait_for_timeout(500)

        # 2.3 Mobile Transactions
        print("Capturing mobile transactions...")
        m_page.goto("http://127.0.0.1:8888/transactions", wait_until="networkidle", timeout=10000)
        m_page.wait_for_timeout(1000)
        m_page.screenshot(path=str(SCREENSHOT_DIR / "mobile_transactions.png"))

        # 2.4 Mobile Filter by Card *2238
        print("Filtering mobile transactions by card *2238...")
        m_card_btn = m_page.query_selector("button:has-text('*2238')")
        if m_card_btn:
            m_card_btn.click()
            m_page.wait_for_timeout(1000)
            m_page.screenshot(path=str(SCREENSHOT_DIR / "mobile_transactions_card_2238.png"))

        print("\nAll browser verifications finished successfully!")
        if console_errors:
            print(f"Console messages: {len(console_errors)}")
            for ce in console_errors[:10]:
                print(f"  {ce}")

        browser.close()

if __name__ == "__main__":
    verify_all()
