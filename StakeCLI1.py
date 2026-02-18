import os
import time
import requests
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

load_dotenv()

# --- CONFIGURATION ---
CASINO_NAME = "https://stake.com"  # Static name/URL for your DB
API_ENDPOINT = os.getenv('API_ENDPOINT', 'http://checkthisone.online/api/slots/sync')
IS_HEADLESS = os.getenv('HEADLESS', 'True').lower() == 'true'
TARGET_URL = "https://stake.com/casino/group/slots"
BASE_URL = "https://stake.com"


def sync_to_laravel(slots_data):
    if not slots_data: return False
    print(f"   [API] Syncing {len(slots_data)} new slots...")
    try:
        response = requests.post(API_ENDPOINT, json=slots_data, timeout=120)
        if response.status_code == 200:
            details = response.json().get('details', {})
            print(
                f"   [SUCCESS] New: {details.get('new_slots_added')}, Skipped: {details.get('existing_slots_skipped')}")
            return True
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
        page.goto(TARGET_URL, wait_until="networkidle", timeout=90000)

        synced_ids = set()  # Track unique game IDs (slugs) to avoid double-syncing

        while True:
            # 1. Wait for game cards to load
            page.wait_for_selector('a.link.svelte-zglogk', timeout=30000)

            # 2. Extract currently visible slots
            items = page.query_selector_all('a.link.svelte-zglogk')
            new_batch = []

            for item in items:
                try:
                    url_path = item.get_attribute('href')  # /casino/games/wild-woof
                    game_id = url_path.split('/')[-1] if url_path else ""

                    if game_id and game_id not in synced_ids:
                        # Extract Title from the specific span provided
                        title_el = item.query_selector('[data-ds-text="true"] span, .game-info-wrap span')
                        title = title_el.inner_text() if title_el else "Unknown"

                        # Extract Provider from the strong tag provided
                        provider_el = item.query_selector('.game-group strong')
                        provider = provider_el.inner_text().strip() if provider_el else "Unknown"

                        # Extract Image
                        img_el = item.query_selector('img')
                        avatar = img_el.get_attribute('src') if img_el else ""

                        new_batch.append({
                            "title": title,
                            "provider": provider,
                            "url": f"{BASE_URL}{url_path}",
                            "avatar": avatar,
                            "casino_name": CASINO_NAME
                        })
                        synced_ids.add(game_id)
                except Exception as e:
                    continue

            # 3. Sync found items
            if new_batch:
                sync_to_laravel(new_batch)

            # 4. Handle "Load More" button
            # We look for the div containing "Load More"
            load_more = page.locator('div.contents:has-text("Load More")')

            if load_more.is_visible():
                print(f"--- Clicking 'Load More' (Total seen: {len(synced_ids)}) ---")
                load_more.scroll_into_view_if_needed()
                load_more.click()

                # Wait for the loader to disappear and new items to arrive
                time.sleep(3)
            else:
                print(">>> No 'Load More' button found. Reached the end.")
                break

            # Safety break for your 4000+ games
            if len(synced_ids) > 5000: break

        browser.close()
        print(f"\n>>> Scrape Complete for Stake. Total synced: {len(synced_ids)}")


if __name__ == "__main__":
    run()