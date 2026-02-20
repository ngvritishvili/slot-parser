import os
import time
import requests
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

# Load configuration
load_dotenv()

# --- CONFIGURATION ---
CASINO_ID = 1
API_BASE = os.getenv('API_ENDPOINT_BASE', 'http://checkthisone.online')
API_GET_SLOTS = f"{API_BASE}/api/casinos/{CASINO_ID}/slots"
API_UPDATE_SLOT = f"{API_BASE}/api/slots/update-details"
IS_HEADLESS = os.getenv('HEADLESS', 'True').lower() == 'true'
STATE_FILE = "state.json"

# Credentials for Sportsbet.io
USER_LOGIN = os.getenv('CASINO_USER')  # Your username/email
USER_PASS = os.getenv('CASINO_PASS')  # Your password

VOLATILITY_MAP = {"low": 1, "medium": 2, "high": 3, "very high": 4}


def get_slots_to_process():
    print(f"[DB] Fetching slots for casino_id: {CASINO_ID}...")
    try:
        response = requests.post(API_GET_SLOTS, timeout=30)
        if response.status_code == 200:
            return response.json()
        return []
    except Exception as e:
        print(f"[ERROR] API Connection failed: {e}")
        return []


def update_slot_in_db(slot_id, data):
    print(f"   [API] Syncing ID {slot_id}...")
    try:
        payload = {"slot_id": slot_id, **data}
        response = requests.post(API_UPDATE_SLOT, json=payload, timeout=30)
        return response.status_code == 200
    except Exception as e:
        print(f"   [API ERROR] {e}")
        return False


def perform_login(p):
    """Logs into Sportsbet.io and saves the state to state.json"""
    print(f"[Login] Attempting login for {USER_LOGIN}...")
    browser = p.chromium.launch(headless=IS_HEADLESS)
    context = browser.new_context(viewport={'width': 1920, 'height': 1080})
    page = context.new_page()
    Stealth().apply_stealth_sync(page)

    try:
        page.goto("https://sportsbet.io/", wait_until="networkidle")

        # Click the Sign In button (using text-based selector as it's more stable)
        page.click('button:has-text("Sign in")')

        # Fill credentials
        page.fill('input[name="username"]', USER_LOGIN)
        page.fill('input[name="password"]', USER_PASS)

        # Click Login button
        page.click('button[type="submit"]')

        # Wait for the URL to change or a logout button to appear to confirm success
        page.wait_for_timeout(10000)

        # Save cookies and local storage
        context.storage_state(path=STATE_FILE)
        print("[Login] Success! Session saved to state.json")
        browser.close()
        return True
    except Exception as e:
        print(f"[Login Error] Could not log in: {e}")
        page.screenshot(path="login_error.png")
        browser.close()
        return False


def parse_slot_details(page, slot):
    url = slot.get('url')
    print(f"\n--- [Scraping] {slot.get('title')} ---")

    try:
        # Increase timeout and wait for idle network
        page.goto(url, wait_until="networkidle", timeout=60000)

        # Extra wait for the stats bar to render after the page 'load'
        page.wait_for_timeout(5000)

        extracted = {
            "theoretical_rtp": None,
            "volatility_level": None,
            "max_win_multiplier": None
        }

        # The selectors for the detail blocks
        blocks = page.query_selector_all('div.flex-col.justify-between.md\\:items-center')

        if not blocks:
            # Fallback debug: check if we are still seeing a login button
            if page.query_selector('button:has-text("Sign in")'):
                print("    [!] Error: Session expired or not logged in.")
            else:
                print("    [!] Error: Could not find technical info blocks.")
            page.screenshot(path=f"debug_{slot['id']}.png")

        for block in blocks:
            label_el = block.query_selector('span.text-secondary')
            value_el = block.query_selector('span.truncate')

            if label_el and value_el:
                label = label_el.inner_text().strip().lower()
                value = value_el.inner_text().strip()
                print(f"    [FOUND] {label}: {value}")

                if "rtp" in label:
                    extracted["theoretical_rtp"] = value.replace('%', '')
                elif "volatility" in label:
                    extracted["volatility_level"] = VOLATILITY_MAP.get(value.lower())
                elif "max win" in label:
                    extracted["max_win_multiplier"] = value.upper().replace('X', '')

        return extracted
    except Exception as e:
        print(f"    [Page Error] {str(e)[:100]}")
        return None


def run():
    slots = get_slots_to_process()
    if not slots:
        print("No slots to process.")
        return

    with sync_playwright() as p:
        # 1. Login if we don't have a saved session
        if not os.path.exists(STATE_FILE):
            if not perform_login(p):
                return

        # 2. Start scraping with the saved session
        browser = p.chromium.launch(headless=IS_HEADLESS)
        context = browser.new_context(
            storage_state=STATE_FILE,
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        page = context.new_page()
        Stealth().apply_stealth_sync(page)

        for slot in slots:
            data = parse_slot_details(page, slot)
            if data and any(data.values()):
                update_slot_in_db(slot['id'], data)

            time.sleep(3)

        browser.close()


if __name__ == "__main__":
    run()