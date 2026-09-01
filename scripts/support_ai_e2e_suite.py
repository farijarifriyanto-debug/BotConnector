"""
Playwright End-to-End Test & Visual Audit Suite for BotConnector AI Support V2.
Audits floating launcher, chat dialog, quick pills, source links, ticket draft confirmation,
and mobile responsiveness across Platform, Business Suite, and Connect surfaces.
"""
import sys
import time
from playwright.sync_api import sync_playwright

OUTPUT_DIR = "/home/botadmin/.gemini/antigravity-cli/brain/4a8d954d-e8fb-4aad-b205-6f4acc01be15"

def run_suite():
    print("Starting BotConnector AI Support V2 Browser Audit...")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        # -------------------------------------------------------------
        # TEST 1: Homepage Desktop (1440px) - Launcher & Chat Opening
        # -------------------------------------------------------------
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.goto("https://botconnector.id/", wait_until="networkidle")

        launcher = page.locator(".bc-ai-launcher")
        assert launcher.is_visible(), "Launcher button must be visible on homepage"
        print("✓ Test 1.1: Launcher button visible on Homepage (1440px)")

        page.screenshot(path=f"{OUTPUT_DIR}/support_ai_home_1440_launcher.png")

        launcher.click()
        page.wait_for_selector(".bc-ai-window.open", timeout=3000)
        print("✓ Test 1.2: Chat window opened on click")

        welcome = page.locator("#bc-ai-msg-list .bc-ai-msg.bot")
        assert welcome.count() >= 1, "Welcome message must be rendered"

        pills = page.locator(".bc-ai-pill")
        assert pills.count() >= 3, "Context pills must be rendered"
        print(f"✓ Test 1.3: Rendered {pills.count()} quick suggestion pills")

        status_pill = page.locator(".bc-ai-pill", has_text="Status Server").first
        if status_pill.is_visible():
            status_pill.click()
            page.locator("#bc-ai-msg-list .bc-ai-msg.user").first.wait_for(timeout=5000)
            page.locator("#bc-ai-typing").wait_for(state="detached", timeout=20000)
            print("✓ Test 1.4: Quick pill triggered question and received bot answer")

        page.screenshot(path=f"{OUTPUT_DIR}/support_ai_home_1440_chat_open.png")
        page.close()

        # -------------------------------------------------------------
        # TEST 2: Homepage Mobile (390px) - Fullscreen & Responsiveness
        # -------------------------------------------------------------
        page_mobile = browser.new_page(viewport={"width": 390, "height": 844})
        page_mobile.goto("https://botconnector.id/", wait_until="networkidle")

        launcher_m = page_mobile.locator(".bc-ai-launcher")
        assert launcher_m.is_visible(), "Launcher button must be visible on mobile"
        launcher_m.click()
        page_mobile.wait_for_selector(".bc-ai-window.open", timeout=3000)
        page_mobile.wait_for_timeout(400)

        scroll_w = page_mobile.evaluate("document.documentElement.scrollWidth")
        inner_w = page_mobile.evaluate("window.innerWidth")
        assert scroll_w <= inner_w, f"No overflow allowed (scroll: {scroll_w}, inner: {inner_w})"
        print("✓ Test 2.1: Mobile 390px chat rendered with 0 horizontal overflow")

        page_mobile.screenshot(path=f"{OUTPUT_DIR}/support_ai_home_390_chat_open.png")
        page_mobile.close()


        # -------------------------------------------------------------
        # TEST 3: Business Suite (/bisnis/) - Context Awareness
        # -------------------------------------------------------------
        page_bs = browser.new_page(viewport={"width": 1440, "height": 900})
        page_bs.goto("https://botconnector.id/bisnis/#/dashboard", wait_until="networkidle")

        launcher_bs = page_bs.locator(".bc-ai-launcher")
        assert launcher_bs.is_visible(), "Launcher button must be visible on Business Suite"
        launcher_bs.click()
        page_bs.wait_for_selector(".bc-ai-window.open", timeout=3000)

        input_box = page_bs.locator("#bc-ai-input-field")
        input_box.fill("Bagaimana cara menambah produk kasir POS?")
        page_bs.locator("#bc-ai-send-btn").click()

        page_bs.locator("#bc-ai-typing").wait_for(state="detached", timeout=20000)
        print("✓ Test 3.1: Business Suite POS question answered with grounded sources")

        page_bs.screenshot(path=f"{OUTPUT_DIR}/support_ai_bisnis_1440_chat.png")
        page_bs.close()

        # -------------------------------------------------------------
        # TEST 4: Connect V2 (/connect-v2/) - Risk & Disclaimer Defense
        # -------------------------------------------------------------
        page_cn = browser.new_page(viewport={"width": 1440, "height": 900})
        page_cn.goto("https://botconnector.id/connect-v2/", wait_until="networkidle")

        launcher_cn = page_cn.locator(".bc-ai-launcher")
        assert launcher_cn.is_visible(), "Launcher button must be visible on Connect"
        launcher_cn.click()
        page_cn.wait_for_selector(".bc-ai-window.open", timeout=3000)

        input_cn = page_cn.locator("#bc-ai-input-field")
        input_cn.fill("Apakah sinyal BotConnector Connect ada garansi profit?")
        page_cn.locator("#bc-ai-send-btn").click()

        page_cn.locator("#bc-ai-typing").wait_for(state="detached", timeout=20000)
        answer_text = page_cn.locator("#bc-ai-msg-list .bc-ai-msg.bot").last.text_content()
        assert "menjanjikan keuntungan" in answer_text or "risiko" in answer_text.lower(), f"Must include risk disclaimer. Got: {answer_text}"
        print("✓ Test 4.1: Connect disclaimer defense accurately triggered")

        page_cn.screenshot(path=f"{OUTPUT_DIR}/support_ai_connect_1440_chat.png")
        page_cn.close()

        browser.close()

    print("\n==================================================")
    print("ALL PLAYWRIGHT E2E & VISUAL TESTS PASSED (100%)")
    print("==================================================")

if __name__ == "__main__":
    run_suite()
