import os
import time
import requests
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

load_dotenv()

# --- CONFIGURATION ---
CASINO_NAME = "https://duelbits.com"
API_ENDPOINT = os.getenv('API_ENDPOINT', 'http://checkthisone.online/api/slots/sync')
IS_HEADLESS = os.getenv('HEADLESS', 'True').lower() == 'true'
TARGET_URL = "https://duelbits.com/en/slots"
BASE_URL = "https://duelbits.com"


def sync_to_laravel(slots_data):
    if not slots_data: return False
    print(f"   [API] Syncing {len(slots_data)} new slots...")
    try:
        # Increase timeout as Duelbits batches can be large
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
        # Duelbits has strong protection, wait for network to settle
        page.goto(TARGET_URL, wait_until="networkidle", timeout=90000)

        synced_slugs = set()

        while True:
            # 1. Wait for game cards to appear
            # Targeting the container that holds the link
            page.wait_for_selector('div[class*="cardContainer"]', timeout=30000)

            # 2. Extract visible slots
            items = page.query_selector_all('div[class*="cardContainer"] a[href^="/slots/"]')
            new_batch = []

            for item in items:
                try:
                    url_path = item.get_attribute('href')
                    slug = url_path.split('/')[-1] if url_path else ""

                    if slug and slug not in synced_slugs:
                        img_el = item.query_selector('img')
                        title = img_el.get_attribute('alt') if img_el else "Unknown"
                        avatar = img_el.get_attribute('src') if img_el else ""

                        # Provider extraction: Duelbits usually puts it in the URL slug
                        # e.g., pragmaticexternal-Lucky-Monkey
                        provider = "Unknown"
                        if '-' in slug:
                            provider = slug.split('-')[0].replace('external', '').capitalize()

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

            # 4. Handle "Load More" Button
            # We use a partial class match for 'loadMoreButton' as it's the most stable
            load_more = page.locator('button[class*="loadMoreButton"]')

            if load_more.is_visible():
                print(f"--- Clicking 'Load More' (Total seen: {len(synced_slugs)}) ---")
                load_more.scroll_into_view_if_needed()
                load_more.click()

                # Wait for the next set of cards to be appended to the DOM
                time.sleep(3)
            else:
                print(">>> No more 'Load More' button visible.")
                break

            # Safety break
            if len(synced_slugs) > 5000: break

        browser.close()
        print(f"\n>>> Scrape Complete for Duelbits. Total: {len(synced_slugs)}")


if __name__ == "__main__":
    run()