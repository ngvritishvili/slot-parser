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
    print(f"[Login] Initializing browser for {USER_LOGIN}...")
    browser = p.chromium.launch(headless=IS_HEADLESS)
    context = browser.new_context(
        viewport={'width': 1920, 'height': 1080},
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
    page = context.new_page()
    Stealth().apply_stealth_sync(page)

    try:
        print(f"    [Navigation] Opening login page...")
        page.goto("https://sportsbet.io/auth/login", wait_until="networkidle", timeout=60000)

        # Artificial delay before typing
        page.wait_for_timeout(random.randint(1000, 3000))

        page.locator('input[name="username"]').fill(str(USER_LOGIN))
        page.wait_for_timeout(random.randint(500, 1500))
        page.locator('input[name="password"]').fill(str(USER_PASS))

        print("    [Action] Clicking Sign In...")
        page.locator('button[type="submit"]').click()

        page.wait_for_url(lambda url: "/auth/login" not in url, timeout=30000)

        # --- THE FIX: WAIT AFTER LOGIN ---
        wait_after_login = random.randint(10000, 15000)
        print(f"    [Login] Success! Landing page reached. Resting for {wait_after_login / 1000}s...")
        page.wait_for_timeout(wait_after_login)

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
        # Avoid high-speed 'networkidle'; use 'domcontentloaded' or 'commit'
        page.goto(url, wait_until="domcontentloaded", timeout=60000)

        # Heavy delay to let Cloudflare validation finish in the background
        wait_time = random.randint(12000, 18000)
        print(f"    Waiting {wait_time / 1000}s for stats and security...")
        page.wait_for_timeout(wait_time)

        # Check for Cloudflare challenge strings in the HTML
        content = page.content()
        if "Verify you are human" in content or "cf-challenge" in content:
            print(f"    [!] Blocked by Cloudflare on {slot.get('title')}")
            page.screenshot(path=f"cf_block_{slot.get('id')}.png")
            return None

        # Scroll down to simulate reading the page
        page.mouse.wheel(0, 600)
        page.wait_for_timeout(2000)

        extracted = {"theoretical_rtp": None, "volatility_level": None, "max_win_multiplier": None}

        # Data extraction via data-translation keys
        rtp_el = page.locator('div:has(> p > span[data-translation="casino.rtp"]) >> p.text-bulma').first
        if rtp_el.is_visible():
            extracted["theoretical_rtp"] = rtp_el.inner_text().replace('%', '').strip()

        vol_el = page.locator('span[data-translation*="casino.volatility_"]').first
        if vol_el.is_visible():
            key = vol_el.get_attribute('data-translation')
            extracted["volatility_level"] = VOLATILITY_MAP.get(key)

        print(f"    [Data Found] {extracted}")
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
        # Handle fresh login if session state is missing
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
                    print(f"    [DB] {slot['title']} updated.")
                except:
                    print("    [DB Error] Failed to update API.")

            # Big cooldown between slots to keep the session "warm" but not "robotic"
            sleep_gap = random.randint(20, 45)
            print(f"[Cooldown] Resting for {sleep_gap}s before next slot...")
            time.sleep(sleep_gap)

        browser.close()


if __name__ == "__main__":
    run()