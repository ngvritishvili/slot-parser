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

VOLATILITY_MAP = {"low": 1, "medium": 2, "high": 3, "very high": 4}


def get_slots_to_process():
    print(f"[DB] Fetching slots for casino_id: {CASINO_ID}...")
    try:
        response = requests.post(API_GET_SLOTS, timeout=30)
        if response.status_code == 200:
            return response.json()
        print(f"[ERROR] API returned {response.status_code}")
        return []
    except Exception as e:
        print(f"[ERROR] Connection failed: {e}")
        return []


def update_slot_in_db(slot_id, data):
    try:
        payload = {"slot_id": slot_id, **data}
        response = requests.post(API_UPDATE_SLOT, json=payload, timeout=30)
        return response.status_code == 200
    except Exception as e:
        print(f"   [API ERROR] {e}")
        return False


def parse_slot_details(page, slot):
    url = slot.get('url')
    print(f"\n--- [Scraping] {slot.get('title')} ---")
    print(f"    URL: {url}")

    try:
        # Navigate
        page.goto(url, wait_until="domcontentloaded", timeout=60000)

        # --- DEBUG LOGS ---
        page.wait_for_timeout(5000)  # Give it extra time to settle
        print(f"    [LOG] Page Title: {page.title()}")

        # Save a screenshot to see why it fails (Look for this file in your folder)
        screenshot_path = f"debug_{slot['id']}.png"
        page.screenshot(path=screenshot_path)
        print(f"    [LOG] Screenshot saved to {screenshot_path}")

        # Check for technical info block existence
        found_blocks = page.query_selector_all('div.flex-col.justify-between')
        print(f"    [LOG] Found {len(found_blocks)} potential info blocks.")

        extracted = {
            "theoretical_rtp": None,
            "volatility_level": None,
            "max_win_multiplier": None
        }

        # Select all detail blocks
        blocks = page.query_selector_all('div.flex-col.justify-between.md\\:items-center')

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

        if not any(extracted.values()):
            print("    [!] No data extracted from this page.")

        return extracted

    except Exception as e:
        print(f"    [ERROR] {str(e)[:100]}")
        return None


def run():
    slots = get_slots_to_process()
    if not slots:
        print("No slots received from API.")
        return

    with sync_playwright() as p:
        # Using a persistent context can help bypass some bot checks
        browser = p.chromium.launch(headless=IS_HEADLESS)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        page = context.new_page()
        Stealth().apply_stealth_sync(page)

        for slot in slots:
            data = parse_slot_details(page, slot)
            if data and any(data.values()):
                update_slot_in_db(slot['id'], data)

            time.sleep(5)  # Increased delay to be safer

        browser.close()


if __name__ == "__main__":
    run()