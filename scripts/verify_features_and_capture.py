import os
import sys
import time
from pathlib import Path

# Add backend to sys.path
sys.path.insert(0, "/home/wln/famwealth/famledger/backend")

from auth import _make_token, SESSION_COOKIE
from playwright.sync_api import sync_playwright

OUT_DIR = Path("/tmp/sure_vs_famledger/features")
OUT_DIR.mkdir(parents=True, exist_ok=True)

def verify_and_capture():
    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path="/usr/bin/google-chrome",
            headless=True,
            args=["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"]
        )

        token = _make_token("qq", persist=True)

        ctx = browser.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=1.5)
        ctx.add_cookies([{
            "name": SESSION_COOKIE,
            "value": token,
            "domain": "127.0.0.1",
            "path": "/",
            "httpOnly": True,
            "secure": False,
            "sameSite": "Lax",
        }])
        page = ctx.new_page()

        print("1. Capturing Dashboard with Sankey chart...")
        page.goto("http://127.0.0.1:8888/", wait_until="networkidle")
        page.wait_for_timeout(1000)
        
        # Click Sankey switch in Cashflow section
        sankey_btn = page.query_selector('button:has-text("Sankey"), button:has-text("桑基图")')
        if sankey_btn:
            sankey_btn.click()
            page.wait_for_timeout(1000)
        page.screenshot(path=str(OUT_DIR / "fam_dashboard_sankey.png"))
        print("  - Saved fam_dashboard_sankey.png")

        print("2. Capturing Calendar heatmap...")
        page.goto("http://127.0.0.1:8888/calendar", wait_until="networkidle")
        page.wait_for_timeout(1200)
        page.screenshot(path=str(OUT_DIR / "fam_calendar_heatmap.png"))
        print("  - Saved fam_calendar_heatmap.png")

        print("3. Capturing Rules Center (/rules)...")
        page.goto("http://127.0.0.1:8888/rules", wait_until="networkidle")
        page.wait_for_timeout(1000)
        page.screenshot(path=str(OUT_DIR / "fam_rules_list.png"))
        print("  - Saved fam_rules_list.png")

        # Open Rule Drawer (Add Rule)
        add_rule_btn = page.query_selector('button:has-text("New Rule"), button:has-text("新建规则")')
        if add_rule_btn:
            add_rule_btn.click()
            page.wait_for_timeout(800)
            page.screenshot(path=str(OUT_DIR / "fam_rule_drawer.png"))
            print("  - Saved fam_rule_drawer.png")
            # Close drawer
            cancel_btn = page.query_selector('button:has-text("Cancel"), button:has-text("取消")')
            if cancel_btn:
                cancel_btn.click()
                page.wait_for_timeout(500)

        # Open Dry Run Modal
        dry_run_btn = page.query_selector('button:has-text("Dry Run"), button:has-text("模拟预演")')
        if dry_run_btn:
            dry_run_btn.click()
            page.wait_for_timeout(800)
            page.screenshot(path=str(OUT_DIR / "fam_rules_dry_run.png"))
            print("  - Saved fam_rules_dry_run.png")
            close_btn = page.query_selector('button:has-text("Close"), button:has-text("关闭")')
            if close_btn:
                close_btn.click()
                page.wait_for_timeout(500)

        print("4. Capturing Settings tabs...")
        page.goto("http://127.0.0.1:8888/settings?tab=preferences", wait_until="networkidle")
        page.wait_for_timeout(800)
        page.screenshot(path=str(OUT_DIR / "fam_settings_preferences.png"))
        print("  - Saved fam_settings_preferences.png")

        page.goto("http://127.0.0.1:8888/settings?tab=oidc", wait_until="networkidle")
        page.wait_for_timeout(800)
        page.screenshot(path=str(OUT_DIR / "fam_settings_oidc_list.png"))
        print("  - Saved fam_settings_oidc_list.png")

        # Open Add Provider modal
        add_idp_btn = page.query_selector('button:has-text("OIDC")')
        if add_idp_btn:
            add_idp_btn.click()
            page.wait_for_timeout(600)
            page.screenshot(path=str(OUT_DIR / "fam_settings_oidc_modal.png"))
            print("  - Saved fam_settings_oidc_modal.png")
            # Close modal
            cancel_btn = page.query_selector('button:has-text("Cancel"), button:has-text("取消")')
            if cancel_btn:
                cancel_btn.click()
                page.wait_for_timeout(400)

        page.goto("http://127.0.0.1:8888/settings?tab=hosting", wait_until="networkidle")
        page.wait_for_timeout(800)
        page.screenshot(path=str(OUT_DIR / "fam_settings_hosting.png"))
        print("  - Saved fam_settings_hosting.png")

        page.goto("http://127.0.0.1:8888/settings?tab=rules", wait_until="networkidle")
        page.wait_for_timeout(800)
        page.screenshot(path=str(OUT_DIR / "fam_settings_rules.png"))
        print("  - Saved fam_settings_rules.png")

        page.goto("http://127.0.0.1:8888/settings?tab=security", wait_until="networkidle")
        page.wait_for_timeout(800)
        page.screenshot(path=str(OUT_DIR / "fam_settings_security.png"))
        print("  - Saved fam_settings_security.png")

        print("5. Testing Language Toggle...")
        # Toggle language using the navbar button
        lang_btn = page.query_selector('nav button:has-text("EN"), nav button:has-text("中")')
        if lang_btn:
            lang_btn.click()
            page.wait_for_timeout(800)
            page.goto("http://127.0.0.1:8888/settings?tab=preferences", wait_until="networkidle")
            page.wait_for_timeout(800)
            page.screenshot(path=str(OUT_DIR / "fam_settings_preferences_toggled_lang.png"))
            print("  - Saved fam_settings_preferences_toggled_lang.png")

        browser.close()
        print("\nAll feature screenshots captured successfully!")

if __name__ == "__main__":
    verify_and_capture()
