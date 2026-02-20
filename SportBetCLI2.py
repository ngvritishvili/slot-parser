import os
import time
import random
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
    print(f"[Login] Initializing fresh login for {USER_LOGIN}...")
    browser = p.chromium.launch(headless=IS_HEADLESS)
    context = browser.new_context(
        viewport={'width': 1920, 'height': 1080},
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
    page = context.new_page()
    Stealth().apply_stealth_sync(page)

    try:
        page.goto("https://sportsbet.io/auth/login", wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(random.randint(2000, 4000))

        page.locator('input[name="username"]').fill(str(USER_LOGIN))
        page.wait_for_timeout(random.randint(500, 1500))
        page.locator('input[name="password"]').fill(str(USER_PASS))
        page.locator('button[type="submit"]').click()

        page.wait_for_url(lambda url: "/auth/login" not in url, timeout=30000)

        # Settle after login
        post_login_wait = random.randint(12000, 15000)
        print(f"    [Login] Success. Warming up session for {post_login_wait / 1000}s...")
        page.wait_for_timeout(post_login_wait)

        context.storage_state(path=STATE_FILE)
        browser.close()
        return True
    except Exception as e:
        print(f"[CRITICAL LOGIN ERROR] {e}")
        browser.close()
        return False


def parse_slot_details(page, slot):
    url = slot.get('url')
    if not url or "sportsbet.io" not in url: return None

    print(f"\n[Scraper] Navigating to: {slot.get('title')}")
    try:
        # Use 'commit' to get the page moving without waiting for all trackers
        page.goto(url, wait_until="commit", timeout=60000)

        # Heavy wait to look human and let CF challenges pass
        wait_time = random.randint(15000, 20000)
        print(f"    Waiting {wait_time / 1000}s for security/render...")
        page.wait_for_timeout(wait_time)

        if "Verify you are human" in page.content() or "cf-challenge" in page.content():
            print(f"    [!] Still blocked by Cloudflare on {slot.get('title')}")
            page.screenshot(path=f"cf_block_{slot.get('id')}.png")
            return None

        # Scroll to simulate user reading stats
        page.mouse.wheel(0, 700)
        page.wait_for_timeout(3000)

        extracted = {"theoretical_rtp": None, "volatility_level": None, "max_win_multiplier": None}

        # Data-translation based selectors
        rtp_el = page.locator('div:has(> p > span[data-translation="casino.rtp"]) >> p.text-bulma').first
        if rtp_el.is_visible():
            extracted["theoretical_rtp"] = rtp_el.inner_text().replace('%', '').strip()

        vol_el = page.locator('span[data-translation*="casino.volatility_"]').first
        if vol_el.is_visible():
            key = vol_el.get_attribute('data-translation')
            extracted["volatility_level"] = VOLATILITY_MAP.get(key)

        print(f"    [Data] {extracted}")
        return extracted
    except Exception as e:
        print(f"    [Error] {str(e)[:50]}")
        return None


def run():
    print(f"[Start] Casino ID: {CASINO_ID}")
    try:
        res = requests.post(API_GET_SLOTS, timeout=20)
        slots = res.json() if res.status_code == 200 else []
    except:
        print("[Error] DB API Offline")
        return

    with sync_playwright() as p:
        # 1. Ensure state file exists
        if not os.path.exists(STATE_FILE):
            if not perform_login(p): return

        # 2. Main Scraping Session
        browser = p.chromium.launch(headless=IS_HEADLESS)
        context = browser.new_context(storage_state=STATE_FILE)
        page = context.new_page()
        Stealth().apply_stealth_sync(page)

        # --- THE FIX: WARM UP SESSION ON RESUME ---
        print("[Session] Resuming. Loading dashboard to warm up cookies...")
        page.goto("https://sportsbet.io/", wait_until="domcontentloaded")
        warmup = random.randint(10000, 15000)
        print(f"    Waiting {warmup / 1000}s on dashboard before starting slot loop...")
        page.wait_for_timeout(warmup)

        for slot in slots:
            data = parse_slot_details(page, slot)
            if data and any(data.values()):
                try:
                    requests.post(API_UPDATE_SLOT, json={"slot_id": slot['id'], **data}, timeout=10)
                    print(f"    [DB] {slot['title']} updated.")
                except:
                    print("    [DB Error] Update failed.")

            # Substantial cooldown between items
            sleep_gap = random.randint(25, 50)
            print(f"[Cooldown] Resting for {sleep_gap}s...")
            time.sleep(sleep_gap)

        browser.close()


if __name__ == "__main__":
    run()