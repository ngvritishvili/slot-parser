import os
import time
import json
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
IS_HEADLESS = os.getenv('HEADLESS', 'False').lower() == 'true'
STATE_FILE = "state.json"

# Credentials (Add these to your .env)
USER_EMAIL = os.getenv('wirusn@gmail.com')
USER_PASS = os.getenv('Cracket1!')

VOLATILITY_MAP = {
    "low": 1,
    "medium": 2,
    "high": 3,
    "very high": 4
}


def get_slots_to_process():
    print(f"[DB] Fetching slots for casino_id: {CASINO_ID}...")
    try:
        # Note: Using POST as per your Laravel route definition
        response = requests.post(API_GET_SLOTS, timeout=30)
        if response.status_code == 200:
            return response.json()
        print(f"[ERROR] API returned {response.status_code}")
        return []
    except Exception as e:
        print(f"[ERROR] Connection failed: {e}")
        return []


def update_slot_in_db(slot_id, data):
    print(f"   [API] Syncing details for ID {slot_id}...")
    try:
        payload = {"slot_id": slot_id, **data}
        response = requests.post(API_UPDATE_SLOT, json=payload, timeout=30)
        return response.status_code == 200
    except Exception as e:
        print(f"   [API ERROR] {e}")
        return False


def ensure_logged_in(p):
    """Logs in and saves session if no state file exists."""
    if os.path.exists(STATE_FILE):
        return True

    print("[Login] No session found. Logging in...")
    browser = p.chromium.launch(headless=IS_HEADLESS)
    context = browser.new_context()
    page = context.new_page()
    Stealth().apply_stealth_sync(page)

    try:
        page.goto("https://sportsbet.io/login", wait_until="networkidle")
        # Adjust selectors based on Sportsbet's login form
        page.fill('input[name="username"]', USER_EMAIL)
        page.fill('input[name="password"]', USER_PASS)
        page.click('button[type="submit"]')

        # Wait for dashboard to confirm login
        page.wait_for_load_state("networkidle")
        context.storage_state(path=STATE_FILE)
        print("[Login] Success! Session saved.")
        browser.close()
        return True
    except Exception as e:
        print(f"[Login Failed] {e}")
        browser.close()
        return False


def parse_slot_details(page, slot):
    url = slot.get('url')
    print(f"\n[Scraping] {slot.get('title')} -> {url}")

    try:
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        # Wait specifically for the stats container to appear
        page.wait_for_selector('span:has-text("RTP")', timeout=15000)

        extracted = {
            "theoretical_rtp": None,
            "volatility_level": None,
            "max_win_multiplier": None
        }

        # Select blocks - using escaped colons for Playwright/CSS
        blocks = page.query_selector_all('div.flex-col.justify-between.md\\:items-center')

        for block in blocks:
            label_el = block.query_selector('span.text-secondary')
            value_el = block.query_selector('span.truncate')

            if not label_el or not value_el:
                continue

            label = label_el.inner_text().strip().lower()
            value = value_el.inner_text().strip()

            if "rtp" in label:
                extracted["theoretical_rtp"] = value.replace('%', '')
            elif "volatility" in label:
                extracted["volatility_level"] = VOLATILITY_MAP.get(value.lower())
            elif "max win" in label:
                extracted["max_win_multiplier"] = value.upper().replace('X', '')

        return extracted
    except Exception as e:
        print(f"   [Error] Page did not load stats: {e}")
        return None


def run():
    slots = get_slots_to_process()
    if not slots:
        return

    with sync_playwright() as p:
        # Optional: ensure_logged_in(p)

        browser = p.chromium.launch(headless=IS_HEADLESS)
        # Load the context with the saved session if it exists
        if os.path.exists(STATE_FILE):
            context = browser.new_context(storage_state=STATE_FILE)
        else:
            context = browser.new_context()

        page = context.new_page()
        Stealth().apply_stealth_sync(page)

        for slot in slots:
            data = parse_slot_details(page, slot)
            if data and any(data.values()):
                update_slot_in_db(slot['id'], data)

            # Important: Polite delay to avoid IP bans
            time.sleep(3)

        browser.close()


if __name__ == "__main__":
    run()