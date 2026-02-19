import os
import time
import requests
import re
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

load_dotenv()

# --- CONFIGURATION ---
CASINO_NAME = "https://ge.betsson.com"
API_ENDPOINT = os.getenv('API_ENDPOINT', 'http://checkthisone.online/api/slots/sync')
IS_HEADLESS = os.getenv('HEADLESS', 'True').lower() == 'true'
TARGET_URL = "https://ge.betsson.com/ka/slots"  # Targeted specifically to slots


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

        synced_titles = set()
        scroll_attempts = 0
        max_scroll_attempts = 30  # Stop if no new items after 30 scrolls

        while scroll_attempts < max_scroll_attempts:
            # 1. Wait for Angular slot cards to render
            page.wait_for_selector('.eb-slot-card-container', timeout=30000)

            # 2. Extract slots
            items = page.query_selector_all('.eb-slot-card-container')
            new_batch = []

            for item in items:
                try:
                    # Extract Title from the specific name container
                    title_el = item.query_selector('.eb-slot-card-name-container span')
                    title = title_el.inner_text().strip() if title_el else ""

                    if title and title not in synced_titles:
                        # Extract Image from background-image style in the image-container
                        img_div = item.query_selector('.eb-slot-card-image-container')
                        style = img_div.get_attribute('style') if img_div else ""

                        avatar = ""
                        if style:
                            # Matches url("...") or url(...)
                            match = re.search(r'url\(["\']?(.*?)["\']?\)', style)
                            if match:
                                avatar = match.group(1)

                        new_batch.append({
                            "title": title,
                            "provider": "Betsson",  # Provider usually hidden in a details view/hover
                            "url": TARGET_URL,
                            "avatar": avatar,
                            "casino_name": CASINO_NAME
                        })
                        synced_titles.add(title)
                except Exception as e:
                    continue

            # 3. Sync found items
            if new_batch:
                sync_to_laravel(new_batch)
                scroll_attempts = 0  # Reset because we found data
            else:
                scroll_attempts += 1

            # 4. Scroll down to trigger Angular lazy loading
            print(f"--- Scroll Activity: Found {len(new_batch)} new items (Total seen: {len(synced_titles)}) ---")
            page.evaluate("window.scrollBy(0, 1000)")
            time.sleep(2.5)  # Wait for cards to pop in

            # Safety break
            if len(synced_titles) > 5000: break

        browser.close()
        print(f"\n>>> Scrape Complete for Betsson. Total synced: {len(synced_titles)}")


if __name__ == "__main__":
    run()