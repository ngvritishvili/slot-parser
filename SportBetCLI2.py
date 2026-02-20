import os
import time
import requests
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

load_dotenv()

# --- CONFIG ---
CASINO_ID = 1
API_BASE = os.getenv('API_ENDPOINT_BASE', 'http://checkthisone.online')
API_GET_SLOTS = f"{API_BASE}/api/casinos/{CASINO_ID}/slots"
API_UPDATE_SLOT = f"{API_BASE}/api/slots/update-details"
IS_HEADLESS = os.getenv('HEADLESS', 'True').lower() == 'true'
STATE_FILE = "state.json"

USER_LOGIN = os.getenv('CASINO_USER')
USER_PASS = os.getenv('CASINO_PASS')

VOLATILITY_MAP = {
    "casino.volatility_1": 1,
    "casino.volatility_2": 2,
    "casino.volatility_3": 3,
    "casino.volatility_4": 4,
    "casino.volatility_5": 5
}


def perform_login(p):
    print(f"[Login] Initializing browser for {USER_LOGIN}...")
    browser = p.chromium.launch(headless=IS_HEADLESS)
    context = browser.new_context(
        viewport={'width': 1920, 'height': 1080},
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    )
    page = context.new_page()
    Stealth().apply_stealth_sync(page)

    try:
        print(f"    [Navigation] Opening login page...")
        page.goto("https://sportsbet.io/auth/login", wait_until="domcontentloaded", timeout=60000)
        page.wait_for_selector('input[name="username"]', timeout=30000)

        print("    [Action] Entering credentials...")
        page.locator('input[name="username"]').fill(str(USER_LOGIN))
        page.locator('input[name="password"]').fill(str(USER_PASS))
        page.locator('button[type="submit"]').click()

        print("    [Verification] Waiting for redirect...")
        page.wait_for_url(lambda url: "/auth/login" not in url, timeout=25000)
        page.wait_for_timeout(5000)

        context.storage_state(path=STATE_FILE)
        print(f"[Login] SUCCESS! Session saved.")
        browser.close()
        return True
    except Exception as e:
        print(f"[CRITICAL LOGIN ERROR] {e}")
        page.screenshot(path="login_fail.png")
        browser.close()
        return False


def parse_slot_details(page, slot):
    url = slot.get('url')
    if not url or "sportsbet.io" not in url: return None

    print(f"\n[Scraper] Visiting Slot: {slot.get('title')}")
    try:
        # Navigate and wait for basic load
        page.goto(url, wait_until="domcontentloaded", timeout=60000)

        # Scroll down slightly to trigger lazy-loading of stats
        page.mouse.wheel(0, 500)

        print("    Waiting for Game Stats grid...")
        try:
            # We wait for the 'Game stats' header specifically
            page.wait_for_selector('span[data-translation="casino.game_stats"]', timeout=15000)
        except Exception as e:
            # If it fails, take a screenshot of the failure
            ss_name = f"fail_{slot.get('id')}.png"
            page.screenshot(path=ss_name)
            print(f"    [!] Timeout. Screenshot saved as {ss_name}")
            return None

        page.wait_for_timeout(2000)

        extracted = {"theoretical_rtp": None, "volatility_level": None, "max_win_multiplier": None}

        # RTP Extraction
        rtp_label = page.query_selector('span[data-translation="casino.rtp"]')
        if rtp_label:
            # Look for the value in the neighboring paragraph
            val_el = page.locator('div:has(> p > span[data-translation="casino.rtp"]) >> p.text-bulma').first
            if val_el.count() > 0:
                extracted["theoretical_rtp"] = val_el.inner_text().replace('%', '').strip()

        # Volatility Extraction
        vol_label = page.query_selector('span[data-translation="casino.volatility"]')
        if vol_label:
            val_span = page.locator(
                'div:has(> p > span[data-translation="casino.volatility"]) >> span[data-translation*="casino.volatility_"]').first
            if val_span.count() > 0:
                key = val_span.get_attribute('data-translation')
                extracted["volatility_level"] = VOLATILITY_MAP.get(key)

        print(f"    [Result] {extracted}")
        return extracted
    except Exception as e:
        print(f"    [Skip] {slot.get('title')} error: {str(e)[:100]}")
        return None


def run():
    print(f"[Start] Casino ID: {CASINO_ID}")
    try:
        res = requests.post(API_GET_SLOTS, timeout=20)
        slots = res.json() if res.status_code == 200 else []
    except Exception as e:
        print(f"[Error] API Connection failed: {e}")
        return

    if not slots:
        print("[Finish] No slots found.")
        return

    with sync_playwright() as p:
        if not os.path.exists(STATE_FILE):
            if not perform_login(p): return

        print("[Session] Resuming with saved authentication state...")
        browser = p.chromium.launch(headless=IS_HEADLESS)
        context = browser.new_context(storage_state=STATE_FILE)
        page = context.new_page()
        Stealth().apply_stealth_sync(page)

        for slot in slots:
            data = parse_slot_details(page, slot)
            if data and any(data.values()):
                try:
                    requests.post(API_UPDATE_SLOT, json={"slot_id": slot['id'], **data}, timeout=10)
                    print(f"    [DB] Updated {slot['title']}")
                except:
                    print("    [DB Error] Update failed.")

            time.sleep(4)

        browser.close()


if __name__ == "__main__":
    run()