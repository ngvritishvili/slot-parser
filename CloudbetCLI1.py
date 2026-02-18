import os
import time
import requests
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

load_dotenv()

# --- CONFIGURATION ---
CASINO_NAME = "https://cloudbet.com"
API_ENDPOINT = os.getenv('API_ENDPOINT', 'http://checkthisone.online/api/slots/sync')
IS_HEADLESS = os.getenv('HEADLESS', 'True').lower() == 'true'
TARGET_URL = "https://www.cloudbet.com/en/casino/slots"  # Ensure standard entry URL
BASE_URL = "https://www.cloudbet.com"


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
        page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=90000)

        synced_slugs = set()

        while True:
            # 1. Wait for game tiles to render
            # We use the unique class 'TileContent-wrapper' which contains the info
            try:
                page.wait_for_selector('.TileContent-wrapper', timeout=30000)
            except:
                print(">>> Timeout waiting for slots. Ending.")
                break

            # 2. Extract slots
            # Each game is inside an <a> tag within the game_tile div
            items = page.query_selector_all('a[href*="/casino/play/"]')
            new_batch = []

            for item in items:
                try:
                    url_path = item.get_attribute('href')
                    # Use the URL path as a unique slug
                    slug = url_path.split('/')[-1] if url_path else ""

                    if slug and slug not in synced_slugs:
                        # Find Title and Provider inside the TileContent-wrapper
                        title_el = item.query_selector('.TileContent-wrapper span:nth-child(1)')
                        provider_el = item.query_selector('.TileContent-wrapper span:nth-child(2)')

                        title = title_el.inner_text().strip() if title_el else "Unknown"
                        provider = provider_el.inner_text().strip() if provider_el else "Unknown"

                        # Extract Image from the TileImage-wrapper
                        img_el = item.query_selector('.TileImage-wrapper img')
                        avatar = img_el.get_attribute('src') if img_el else ""

                        new_batch.append({
                            "title": title,
                            "provider": provider,
                            "url": f"{BASE_URL}{url_path}",
                            "avatar": avatar,
                            "casino_name": CASINO_NAME
                        })
                        synced_slugs.add(slug)
                except:
                    continue

            # 3. Sync to Laravel
            if new_batch:
                sync_to_laravel(new_batch)

            # 4. Handle "Load more" button
            # We look for the button containing the text 'Load more'
            load_more = page.locator('button:has-text("Load more")')

            if load_more.is_visible():
                print(f"--- Clicking 'Load more' (Total processed: {len(synced_slugs)}) ---")
                load_more.scroll_into_view_if_needed()
                load_more.click()

                # Cloudbet needs a moment to fetch and append the next grid
                time.sleep(4)
            else:
                print(">>> Reached the end or 'Load more' button disappeared.")
                break

            # Safety break
            if len(synced_slugs) > 5000: break

        browser.close()
        print(f"\n>>> Scrape Complete for Cloudbet. Total: {len(synced_slugs)}")


if __name__ == "__main__":
    run()