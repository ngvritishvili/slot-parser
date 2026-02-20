import os
import time
import requests
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

# Load configuration
load_dotenv()

# --- CONFIGURATION ---
CASINO_ID = 1  # Set this to the ID of sportsbet.io in your DB
API_GET_SLOTS = f"{os.getenv('API_ENDPOINT_BASE')}/api/casinos/{CASINO_ID}/slots"
API_UPDATE_SLOT = f"{os.getenv('API_ENDPOINT_BASE')}/api/slots/update-details"
IS_HEADLESS = os.getenv('HEADLESS', 'True').lower() == 'true'

# Mapping for Volatility
VOLATILITY_MAP = {
    "low": 1,
    "medium": 2,
    "high": 3,
    "very high": 4
}


def get_slots_to_process():
    """
    Fetches the list of slots for this casino from your Laravel DB.
    Expects a list of objects containing at least 'id' and 'url'.
    """
    print(f"[DB] Fetching slots for casino_id: {CASINO_ID}...")
    try:
        # Replace with your actual Laravel route that returns slots by casino
        response = requests.post(API_GET_SLOTS, timeout=30)
        if response.status_code == 200:
            return response.json()  # Assuming it returns [{id: 1, url: '...'}, ...]
        return []
    except Exception as e:
        print(f"[ERROR] Could not fetch slots from API: {e}")
        return []


def update_slot_in_db(slot_id, data):
    """
    Sends the parsed RTP, Volatility, and Max Win back to Laravel.
    """
    print(f"   [API] Updating slot {slot_id}: {data}")
    try:
        # We send slot_id so Laravel knows which row to update
        payload = {"slot_id": slot_id, **data}
        response = requests.post(API_UPDATE_SLOT, json=payload, timeout=30)
        return response.status_code == 200
    except Exception as e:
        print(f"   [API ERROR] Update failed: {e}")
        return False


def parse_slot_details(page, slot):
    """
    Navigates to the slot URL and extracts technical data.
    """
    url = slot.get('url')
    print(f"\n[Scraping] {slot.get('title', 'Unknown Slot')} -> {url}")

    try:
        page.goto(url, wait_until="networkidle", timeout=60000)
        # Small wait for the dynamic JS elements to render the stats bar
        page.wait_for_timeout(3000)

        extracted_data = {
            "theoretical_rtp": None,
            "volatility_level": None,
            "max_win_multiplier": None
        }

        # Select all detail blocks (the flex-col divs you described)
        blocks = page.query_selector_all('div.flex-col.justify-between.md\\:items-center')

        for block in blocks:
            label_el = block.query_selector('span.text-secondary')
            value_el = block.query_selector('span.truncate')

            if not label_el or not value_el:
                continue

            label = label_el.inner_text().strip().lower()
            value = value_el.inner_text().strip()

            if "rtp" in label:
                # Extracts "96.01" from "96.01%"
                extracted_data["theoretical_rtp"] = value.replace('%', '')

            elif "volatility" in label:
                # Maps "High" to 3
                val_lower = value.lower()
                extracted_data["volatility_level"] = VOLATILITY_MAP.get(val_lower, None)

            elif "max win" in label:
                # Extracts "50000" from "50000X"
                extracted_data["max_win_multiplier"] = value.upper().replace('X', '')

        return extracted_data

    except Exception as e:
        print(f"   [SKIP] Error parsing {url}: {e}")
        return None


def run():
    slots = get_slots_to_process()
    if not slots:
        print("No slots found to process. Check your API or Casino ID.")
        return

    print(f"Starting processing for {len(slots)} slots...")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=IS_HEADLESS)
        # Use a single context for the whole session to be faster,
        # but consider rotating if memory climbs.
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0 Safari/537.36"
        )
        page = context.new_page()
        Stealth().apply_stealth_sync(page)

        for slot in slots:
            # 1. Scrape
            data = parse_slot_details(page, slot)

            # 2. Sync if we found anything
            if data and any(data.values()):
                update_slot_in_db(slot['id'], data)

            # 3. Polite delay
            time.sleep(2)

        browser.close()


if __name__ == "__main__":
    run()