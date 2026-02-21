import os
import time
import random
import requests
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

load_dotenv()

# --- CONFIG ---
CASINO_ID = 2
API_BASE = os.getenv('API_ENDPOINT_BASE', 'http://checkthisone.online')
API_GET_SLOTS = f"{API_BASE}/api/casinos/{CASINO_ID}/slots"
API_UPDATE_SLOT = f"{API_BASE}/api/slots/update-details"
IS_HEADLESS = os.getenv('HEADLESS', 'True').lower() == 'true'
STATE_FILE = "stake_state.json"

USER_LOGIN = os.getenv('CASINO_USER')
USER_PASS = os.getenv('CASINO_PASS')

VOLATILITY_MAP = {
    "low": 1, "medium": 2, "high": 3, "very high": 4, "extreme": 5
}


def perform_login(p):
    if not USER_LOGIN or not USER_PASS:
        print("[ERROR] CASINO_USER or CASINO_PASS missing in .env")
        return False

    print(f"[Login] Initializing browser for {USER_LOGIN}...")
    browser = p.chromium.launch(headless=IS_HEADLESS)
    context = browser.new_context(
        viewport={'width': 1280, 'height': 800},
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
    page = context.new_page()
    Stealth().apply_stealth_sync(page)

    try:
        # Step 1: Base Load
        print("    [Navigation] Loading Stake Base...")
        page.goto("https://stake.com/", wait_until="commit", timeout=60000)
        page.screenshot(path="stake_01_base_load.png")

        # Step 2: Trigger Modal
        print("    [Navigation] Triggering Login Modal...")
        page.goto("https://stake.com/?modal=auth&tab=login", wait_until="domcontentloaded", timeout=60000)
        time.sleep(5)  # Extra time for Svelte to mount the modal
        page.screenshot(path="stake_02_modal_triggered.png")

        # Step 3: Wait for Fields
        print("    [Action] Waiting for login fields...")
        try:
            page.wait_for_selector('input[data-testid="login-name"], input[name="emailOrName"]', timeout=30000)
        except Exception:
            print("    [!] Form not found. Saving debug data...")
            page.screenshot(path="stake_error_form_not_found.png")
            with open("stake_debug_source.html", "w", encoding="utf-8") as f:
                f.write(page.content())
            raise Exception("Login form timeout")

        print("    [Action] Filling credentials...")
        page.locator('input[data-testid="login-name"], input[name="emailOrName"]').first.fill(str(USER_LOGIN))
        page.wait_for_timeout(random.randint(500, 1000))
        page.locator('input[data-testid="login-password"], input[name="password"]').first.fill(str(USER_PASS))
        page.screenshot(path="stake_03_filled.png")

        print("    [Action] Clicking Sign In...")
        page.locator('button[data-testid="button-login"], button[type="submit"]').first.click()

        # Verification
        print("    [Verification] Waiting for session...")
        success = False
        for i in range(30):
            if "modal=auth" not in page.url:
                success = True
                break
            time.sleep(1)

        if success:
            print("    [Login] Success! Saving state.")
            time.sleep(5)
            context.storage_state(path=STATE_FILE)
            page.screenshot(path="stake_04_success.png")
            browser.close()
            return True
        else:
            page.screenshot(path="stake_error_login_failed.png")
            print("    [Error] Stuck on login modal.")
            browser.close()
            return False

    except Exception as e:
        print(f"[CRITICAL LOGIN ERROR] {e}")
        page.screenshot(path="stake_critical_crash.png")
        browser.close()
        return False


def parse_slot_details(page, slot):
    url = slot.get('url')
    if not url: return None

    print(f"\n[Scraper] Visiting: {slot.get('title')}")
    try:
        page.goto(url, wait_until="commit", timeout=60000)
        time.sleep(8)
        page.mouse.wheel(0, 500)
        time.sleep(2)

        # Attempt to find the info table
        for btn_text in ["Game info", "Description", "Game Information"]:
            info_btn = page.get_by_role("button", name=btn_text, exact=False)
            if info_btn.is_visible():
                info_btn.click()
                time.sleep(2)
                break

        extracted = {"theoretical_rtp": None, "volatility_level": None, "max_win_multiplier": None}
        rows = page.query_selector_all('tbody tr')

        if not rows:
            page.screenshot(path=f"stake_slot_fail_{slot.get('id')}.png")

        for row in rows:
            cells = row.query_selector_all('td')
            if len(cells) >= 2:
                label = cells[0].inner_text().strip().lower()
                val = cells[1].inner_text().strip()
                if "rtp" == label:
                    extracted["theoretical_rtp"] = val.replace('%', '').strip()
                elif "volatility" == label:
                    extracted["volatility_level"] = VOLATILITY_MAP.get(val.lower())
                elif "max win" == label:
                    extracted["max_win_multiplier"] = val.lower().replace('x', '').replace(',', '').strip()

        print(f"    [Data] {extracted}")
        return extracted
    except Exception as e:
        print(f"    [Skip] {slot.get('title')} error: {str(e)[:50]}")
        return None


def run():
    print(f"[Start] Stake Scanner (Casino ID: {CASINO_ID})")
    try:
        res = requests.post(API_GET_SLOTS, timeout=20)
        slots = res.json() if res.status_code == 200 else []
    except:
        return

    with sync_playwright() as p:
        if not os.path.exists(STATE_FILE):
            if not perform_login(p): return

        browser = p.chromium.launch(headless=IS_HEADLESS)
        context = browser.new_context(storage_state=STATE_FILE)
        page = context.new_page()
        Stealth().apply_stealth_sync(page)

        page.goto("https://stake.com/casino/slots", wait_until="commit")
        time.sleep(10)

        for slot in slots:
            data = parse_slot_details(page, slot)
            if data and any(data.values()):
                try:
                    requests.post(API_UPDATE_SLOT, json={"slot_id": slot['id'], **data}, timeout=10)
                    print(f"    [DB] {slot['title']} updated.")
                except:
                    pass
            time.sleep(random.randint(10, 20))
        browser.close()


if __name__ == "__main__": run()