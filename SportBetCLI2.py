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

VOLATILITY_MAP = {"low": 1, "medium": 2, "high": 3, "very high": 4}


def get_slots_to_process():
    print(f"[DB] Fetching slots for casino_id: {CASINO_ID}...")
    try:
        # Use POST as requested
        response = requests.post(API_GET_SLOTS, timeout=30)
        if response.status_code == 200:
            return response.json()
        return []
    except Exception as e:
        print(f"[ERROR] API Connection failed: {e}")
        return []


def update_slot_in_db(slot_id, data):
    try:
        payload = {"slot_id": slot_id, **data}
        response = requests.post(API_UPDATE_SLOT, json=payload, timeout=30)
        return response.status_code == 200
    except:
        return False


def perform_login(p):
    print(f"[Login] Attempting login for {USER_LOGIN}...")
    browser = p.chromium.launch(headless=IS_HEADLESS)
    context = browser.new_context(viewport={'width': 1280, 'height': 720})
    page = context.new_page()
    Stealth().apply_stealth_sync(page)

    try:
        # Go to the site
        page.goto("https://sportsbet.io/", wait_until="domcontentloaded", timeout=60000)

        # Check if the modal is already open or click sign in
        # If it's BC.Game logic, the modal might trigger via URL or button
        if not page.query_selector('input[placeholder*="Username"]'):
            print("    Clicking Sign In button...")
            page.click('button:has-text("Sign in")', timeout=15000)

        # Wait for the specific placeholders you provided in the HTML
        print("    Filling credentials...")
        page.wait_for_selector('input[placeholder*="Username"]', timeout=15000)
        page.fill('input[placeholder*="Username"]', USER_LOGIN)
        page.fill('input[placeholder="Password"]', USER_PASS)

        # Click the submit button
        page.click('button[type="submit"]')

        # Wait for navigation after login
        print("    Waiting for session to establish...")
        page.wait_for_timeout(10000)

        # Verify we aren't still on the login page
        if page.query_selector('button[type="submit"]'):
            print("    [!] Login failed. Form still visible (Check for Captcha).")
            page.screenshot(path="login_failed.png")
            return False

        context.storage_state(path=STATE_FILE)
        print("[Login] Success! State saved.")
        browser.close()
        return True
    except Exception as e:
        print(f"[Login Error] {e}")
        page.screenshot(path="debug_login_error.png")
        browser.close()
        return False


def parse_slot_details(page, slot):
    url = slot.get('url')
    # Safety check for casino domain
    if "sportsbet.io" not in url:
        print(f"    [SKIP] URL {url} is not for Sportsbet.")
        return None

    print(f"\n[Scraping] {slot.get('title')}")
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(5000)  # Wait for JS to render stats

        extracted = {
            "theoretical_rtp": None,
            "volatility_level": None,
            "max_win_multiplier": None
        }

        # Targeted selectors for Sportsbet technical data
        blocks = page.query_selector_all('div.flex-col.justify-between.md\\:items-center')
        for block in blocks:
            label_el = block.query_selector('span.text-secondary')
            value_el = block.query_selector('span.truncate')

            if label_el and value_el:
                label = label_el.inner_text().lower()
                val = value_el.inner_text()
                if "rtp" in label:
                    extracted["theoretical_rtp"] = val.replace('%', '').strip()
                elif "volatility" in label:
                    extracted["volatility_level"] = VOLATILITY_MAP.get(val.lower().strip())
                elif "max win" in label:
                    extracted["max_win_multiplier"] = val.upper().replace('X', '').strip()

        print(f"    [DATA] {extracted}")
        return extracted
    except Exception as e:
        print(f"    [Error] {str(e)[:50]}")
        return None


def run():
    slots = get_slots_to_process()
    if not slots:
        print("No slots found.")
        return

    with sync_playwright() as p:
        if not os.path.exists(STATE_FILE):
            if not perform_login(p): return

        browser = p.chromium.launch(headless=IS_HEADLESS)
        context = browser.new_context(storage_state=STATE_FILE)
        page = context.new_page()
        Stealth().apply_stealth_sync(page)

        for slot in slots:
            data = parse_slot_details(page, slot)
            if data and any(data.values()):
                update_slot_in_db(slot['id'], data)
            time.sleep(2)

        browser.close()


if __name__ == "__main__":
    run()