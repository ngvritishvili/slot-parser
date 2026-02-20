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

USER_LOGIN = os.getenv('CASINO_USER')
USER_PASS = os.getenv('CASINO_PASS')

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
    print(f"[Login] Attempting login for {USER_LOGIN}...")
    browser = p.chromium.launch(headless=IS_HEADLESS)

    # Adding more realistic headers
    context = browser.new_context(
        viewport={'width': 1920, 'height': 1080},
        extra_http_headers={"Accept-Language": "en-US,en;q=0.9"}
    )

    page = context.new_page()
    Stealth().apply_stealth_sync(page)

    try:
        # 1. Try to go to the login page directly if possible, or use home with a longer timeout
        print("    Navigating to Sportsbet.io...")
        # We use 'domcontentloaded' because 'networkidle' is too strict for crypto sites
        page.goto("https://sportsbet.io/", wait_until="domcontentloaded", timeout=90000)

        # 2. Look for the Sign In button
        print("    Opening Login Modal...")
        page.wait_for_selector('button:has-text("Sign in")', timeout=20000)
        page.click('button:has-text("Sign in")')

        # 3. Fill credentials (Wait for form to appear)
        page.wait_for_selector('input[name="username"]', timeout=10000)
        page.fill('input[name="username"]', USER_LOGIN)
        page.fill('input[name="password"]', USER_PASS)

        # 4. Submit
        print("    Submitting credentials...")
        page.click('button[type="submit"]')

        # 5. Wait to see if login successful (e.g., look for user profile or a specific element)
        page.wait_for_timeout(10000)

        # Check if we are still on login (failed login/captcha)
        if page.query_selector('button[type="submit"]'):
            print("    [!] Login form still visible. Possibly failed or Captcha appeared.")
            page.screenshot(path="login_failed.png")
            return False

        # Save session
        context.storage_state(path=STATE_FILE)
        print("[Login] Success! Session saved.")
        browser.close()
        return True
    except Exception as e:
        print(f"[Login Error] {e}")
        page.screenshot(path="login_timeout_debug.png")
        browser.close()
        return False


def parse_slot_details(page, slot):
    url = slot.get('url')
    # Filter out BC.Game URLs if they accidentally got into the Sportsbet list
    if "sportsbet.io" not in url:
        print(f"    [SKIP] Invalid URL for this scraper: {url}")
        return None

    print(f"\n--- [Scraping] {slot.get('title')} ---")

    try:
        # Use domcontentloaded here too for speed
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(5000)

        extracted = {
            "theoretical_rtp": None,
            "volatility_level": None,
            "max_win_multiplier": None
        }

        # Handle the technical info blocks
        blocks = page.query_selector_all('div.flex-col.justify-between.md\\:items-center')

        for block in blocks:
            label_el = block.query_selector('span.text-secondary')
            value_el = block.query_selector('span.truncate')

            if label_el and value_el:
                label = label_el.inner_text().strip().lower()
                value = value_el.inner_text().strip()

                if "rtp" in label:
                    extracted["theoretical_rtp"] = value.replace('%', '')
                elif "volatility" in label:
                    extracted["volatility_level"] = VOLATILITY_MAP.get(value.lower())
                elif "max win" in label:
                    extracted["max_win_multiplier"] = value.upper().replace('X', '')

        if any(extracted.values()):
            print(f"    [FOUND] {extracted}")
        else:
            print("    [!] No data found on this page.")

        return extracted
    except Exception as e:
        print(f"    [Page Error] {str(e)[:100]}")
        return None


def run():
    slots = get_slots_to_process()
    if not slots:
        return

    with sync_playwright() as p:
        if not os.path.exists(STATE_FILE):
            if not perform_login(p):
                print("Aborting: Could not establish session.")
                return

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