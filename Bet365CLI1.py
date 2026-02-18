import os
import time
import requests
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

load_dotenv()

# --- CONFIGURATION ---
CASINO_NAME = "https://casino.bet365.com"  # <--- Specify your static casino name here
API_ENDPOINT = os.getenv('API_ENDPOINT', 'http://checkthisone.online/api/slots/sync')
IS_HEADLESS = os.getenv('HEADLESS', 'True').lower() == 'true'
TARGET_URL = "https://casino.bet365.com/all-games/VideoSlots"

def sync_to_laravel(slots_data):
    if not slots_data: return False
    print(f"   [API] Syncing {len(slots_data)} new slots...")
    try:
        response = requests.post(API_ENDPOINT, json=slots_data, timeout=120)
        if response.status_code == 200:
            details = response.json().get('details', {})
            print(f"   [SUCCESS] New: {details.get('new_slots_added')}, Skipped: {details.get('existing_slots_skipped')}")
            return True
        else:
            print(f"   [API ERROR] Status {response.status_code}: {response.text}")
    except Exception as e:
        print(f"   [API ERROR] {e}")
    return False

def run():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=IS_HEADLESS)
        context = browser.new_context(viewport={'width': 1920, 'height': 1080})
        page = context.new_page()
        Stealth().apply_stealth_sync(page)

        print(f">>> Opening {TARGET_URL} for {CASINO_NAME}")
        page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=60000)

        # Bet365 can be slow to start, wait for the first batch
        page.wait_for_selector('div[data-testid="launchGame"]', timeout=30000)

        synced_titles = set()  # Session-based tracking to avoid duplicates in the scroll loop
        scroll_attempts = 0
        max_scroll_attempts = 50

        while scroll_attempts < max_scroll_attempts:
            # 1. Extract currently visible slots
            items = page.query_selector_all('div[data-testid="launchGame"]')
            new_batch = []

            for item in items:
                title = item.get_attribute('aria-label')

                # Only process if we haven't seen this title in the current run
                if title and title not in synced_titles:
                    img = item.query_selector('img.imageContainer')
                    avatar = img.get_attribute('src') if img else ""

                    # Protocol-relative URL fix (e.g., //content... -> https://content...)
                    if avatar.startswith('//'):
                        avatar = 'https:' + avatar

                    new_batch.append({
                        "title": title,
                        "provider": "Bet365", # Note: Provider is not easily found in the grid view
                        "url": TARGET_URL,
                        "avatar": avatar,
                        "casino_name": CASINO_NAME  # <--- Added static casino name
                    })
                    synced_titles.add(title)

            # 2. Sync new items found in this specific scroll
            if new_batch:
                sync_to_laravel(new_batch)
                scroll_attempts = 0 # Reset attempts because we found data
            else:
                scroll_attempts += 1 # Increment because no new items appeared

            # 3. Scroll down to trigger the infinite scroll lazy-load
            print(f"--- Scroll Activity: Found {len(new_batch)} new items (Total seen: {len(synced_titles)}) ---")
            page.evaluate("window.scrollBy(0, 1500)")
            time.sleep(3)

            # Safety break to avoid infinite loops if the site behaves unexpectedly
            if len(synced_titles) > 3000:
                print(">>> Reached safety limit of 3000 slots.")
                break

        browser.close()
        print(f"\n>>> Scrape Complete for {CASINO_NAME}. Total synced: {len(synced_titles)}")

if __name__ == "__main__":
    run()