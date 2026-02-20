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


def perform_login(p):
    print(f"[Login] Process started for {USER_LOGIN}...")
    browser = p.chromium.launch(headless=IS_HEADLESS)
    context = browser.new_context(viewport={'width': 1920, 'height': 1080})
    page = context.new_page()
    Stealth().apply_stealth_sync(page)

    try:
        print("    Navigating to Sportsbet.io...")
        page.goto("https://sportsbet.io/", wait_until="domcontentloaded", timeout=60000)

        # Target the specific 'Sign In' link from your HTML snippet
        print("    Clicking Sign In link...")
        # selector based on your provided snippet: a[href="/auth/login"]
        page.wait_for_selector('a[href="/auth/login"]', timeout=15000)
        page.click('a[href="/auth/login"]')

        # Wait for the login page to load
        print("    Waiting for login page form...")
        # Since it goes to a new page, we wait for the username input to appear
        page.wait_for_selector('input[name="username"], input[placeholder*="Username"]', timeout=20000)

        print("    Filling credentials...")
        page.fill('input[name="username"]', USER_LOGIN)
        page.fill('input[name="password"]', USER_PASS)

        # Click the Sign In button on the new page
        # Using the selector from your previous snippet: button[type="submit"]
        print("    Submitting form...")
        page.click('button[type="submit"]')

        # Wait for redirect back to home or dashboard
        print("    Verifying session...")
        page.wait_for_timeout(10000)

        # If the Sign In link is gone, we are logged in
        if page.query_selector('a[href="/auth/login"]'):
            print("    [!] Login failed. Sign In link still visible.")
            page.screenshot(path="login_failed_final.png")
            return False

        context.storage_state(path=STATE_FILE)
        print("[Login] Success! State saved.")
        browser.close()
        return True
    except Exception as e:
        print(f"[Login Error] {e}")
        page.screenshot(path="login_error_trace.png")
        browser.close()
        return False


def parse_slot_details(page, slot):
    url = slot.get('url')
    if "sportsbet.io" not in url:
        return None

    print(f"\n[Scraping] {slot.get('title')}")
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(5000)

        extracted = {"theoretical_rtp": None, "volatility_level": None, "max_win_multiplier": None}

        # Specific Sportsbet detail selectors
        blocks = page.query_selector_all('div.flex-col.justify-between.md\\:items-center')
        for block in blocks:
            label_el = block.query_selector('span.text-secondary')
            value_el = block.query_selector('span.truncate')

            if label_el and value_el:
                label = label_el.inner_text().lower()
                val = value_el.inner_text().strip()
                if "rtp" in label:
                    extracted["theoretical_rtp"] = val.replace('%', '')
                elif "volatility" in label:
                    extracted["volatility_level"] = VOLATILITY_MAP.get(val.lower())
                elif "max win" in label:
                    extracted["max_win_multiplier"] = val.upper().replace('X', '')

        print(f"    Data: {extracted}")
        return extracted
    except Exception as e:
        print(f"    Error on page: {str(e)[:50]}")
        return None


def run():
    print("[DB] Fetching slots from API...")
    try:
        response = requests.post(API_GET_SLOTS, timeout=30)
        slots = response.json() if response.status_code == 200 else []
    except Exception as e:
        print(f"API Error: {e}")
        return

    if not slots:
        print("No slots to process.")
        return

    with sync_playwright() as p:
        # Check if we need to log in
        if not os.path.exists(STATE_FILE):
            if not perform_login(p):
                print("Aborting: Login failed.")
                return

        browser = p.chromium.launch(headless=IS_HEADLESS)
        context = browser.new_context(storage_state=STATE_FILE)
        page = context.new_page()
        Stealth().apply_stealth_sync(page)

        for slot in slots:
            data = parse_slot_details(page, slot)
            if data and any(data.values()):
                requests.post(API_UPDATE_SLOT, json={"slot_id": slot['id'], **data})
            time.sleep(2)

        browser.close()


if __name__ == "__main__":
    run()