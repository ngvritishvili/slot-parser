import os
import time
import requests
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

load_dotenv()

# --- CONFIGURATION ---
CASINO_NAME = "PlayOJO"
API_ENDPOINT = os.getenv('API_ENDPOINT', 'http://checkthisone.online/api/slots/sync')
IS_HEADLESS = os.getenv('HEADLESS', 'True').lower() == 'true'

# List of URLs provided
TARGET_URLS = [
    "https://www.playojo.com/slots/new-slots-games/",
    "https://www.playojo.com/slots/trending-slots-games/",
    "https://www.playojo.com/slots/popular-near-you-slots-games/",
    "https://www.playojo.com/slots/exclusive-slots-games/",
    "https://www.playojo.com/slots/megaways-games/"
]


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

        synced_titles = set()

        for url in TARGET_URLS:
            print(f"\n>>> Starting Category: {url}")
            try:
                page.goto(url, wait_until="networkidle", timeout=90000)
            except:
                print(f"!!! Failed to load {url}, skipping.")
                continue

            while True:
                # 1. Wait for thumbnails
                page.wait_for_selector('.thumb', timeout=30000)

                # 2. Extract slots
                items = page.query_selector_all('.thumb')
                new_batch = []

                for item in items:
                    try:
                        # Title is inside h3
                        title_el = item.query_selector('h3')
                        title = title_el.inner_text().strip() if title_el else ""

                        if title and title not in synced_titles:
                            # Avatar from the main thumb_img
                            img_el = item.query_selector('.thumb_img')
                            avatar = img_el.get_attribute('src') if img_el else ""

                            # Provider is hidden in an img alt tag inside the hover container
                            provider_img = item.query_selector('.thumb_hover img')
                            provider = provider_img.get_attribute('alt') if provider_img else "Unknown"

                            new_batch.append({
                                "title": title,
                                "provider": provider,
                                "url": url,
                                "avatar": avatar,
                                "casino_name": CASINO_NAME
                            })
                            synced_titles.add(title)
                    except:
                        continue

                # 3. Sync to Laravel
                if new_batch:
                    sync_to_laravel(new_batch)

                # 4. Handle "LOAD MORE"
                # Using the specific text and button class btn-green
                load_more = page.locator('button.btn-green:has-text("LOAD MORE")')

                if load_more.is_visible():
                    print(f"--- Clicking 'LOAD MORE' (Total items in memory: {len(synced_titles)}) ---")
                    load_more.scroll_into_view_if_needed()
                    load_more.click()

                    # PlayOJO items take a second to slide in
                    time.sleep(3)
                else:
                    print(">>> Category complete.")
                    break

        browser.close()
        print(f"\n>>> Global Scrape Complete. Total unique items: {len(synced_titles)}")


if __name__ == "__main__":
    run()