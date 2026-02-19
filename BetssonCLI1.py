import os
import time
import requests
import re
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

load_dotenv()

# --- CONFIGURATION ---
CASINO_NAME = "Betsson GE"
API_ENDPOINT = os.getenv('API_ENDPOINT', 'http://checkthisone.online/api/slots/sync')
IS_HEADLESS = os.getenv('HEADLESS', 'True').lower() == 'true'
TARGET_URL = "https://ge.betsson.com/ka/slots"


def sync_to_laravel(slots_data):
    if not slots_data: return False
    print(f"   [API] Syncing {len(slots_data)} slots...")
    try:
        response = requests.post(API_ENDPOINT, json=slots_data, timeout=120)
        if response.status_code == 200:
            res = response.json()
            details = res.get('details', {})
            # FIXED: Matching your Laravel refactor keys
            new = details.get('new_links_added', 0)
            skipped = details.get('existing_links_skipped', 0)
            print(f"   [SUCCESS] New Links: {new}, Skipped: {skipped}")
            return True
    except Exception as e:
        print(f"   [API ERROR] {e}")
    return False


def run():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=IS_HEADLESS, args=["--disable-blink-features=AutomationControlled"])
        context = browser.new_context(viewport={'width': 1920, 'height': 1080})
        page = context.new_page()
        Stealth().apply_stealth_sync(page)

        print(f">>> Opening {TARGET_URL}")
        try:
            # FIX 1: Change to domcontentloaded to bypass network timeouts
            page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=60000)
            # Explicitly wait for the Angular slot cards to appear
            page.wait_for_selector('.eb-slot-card-container', timeout=45000)
        except Exception as e:
            print(f"!!! Initial load failed or timed out: {e}")
            page.screenshot(path="betsson_error.png")
            browser.close()
            return

        synced_titles = set()
        consecutive_no_new = 0

        while consecutive_no_new < 15:  # Stop if 15 scrolls yield no new data
            # 1. Scroll slightly to trigger lazy loading of images/data
            page.mouse.wheel(0, 1200)
            time.sleep(2)  # Wait for Angular to render new items

            # 2. Extract slots using the specific classes from your snippet
            items = page.query_selector_all('.eb-slot-card-container')
            new_batch = []

            for item in items:
                try:
                    # Title is inside .eb-slot-card-name-container span
                    title_el = item.query_selector('.eb-slot-card-name-container span')
                    title = title_el.inner_text().strip() if title_el else ""

                    if title and title not in synced_titles:
                        # Image is in .eb-slot-card-image-container background-image
                        img_div = item.query_selector('.eb-slot-card-image-container')
                        style = img_div.get_attribute('style') if img_div else ""

                        avatar = ""
                        if style:
                            match = re.search(r'url\(["\']?(.*?)["\']?\)', style)
                            if match:
                                avatar = match.group(1)

                        new_batch.append({
                            "title": title,
                            "provider": "Unknown",  # Betsson hides provider in tooltips
                            "url": TARGET_URL,
                            "avatar": avatar,
                            "casino_name": CASINO_NAME
                        })
                        synced_titles.add(title)
                except:
                    continue

            # 3. Sync to Laravel
            if new_batch:
                sync_to_laravel(new_batch)
                consecutive_no_new = 0  # Reset counter
            else:
                consecutive_no_new += 1
                print(f"   [INFO] No new items found (Attempt {consecutive_no_new}/15)")

            # Safety cap
            if len(synced_titles) > 8000: break

        browser.close()
        print(f"\n>>> Scrape Complete for Betsson. Total unique: {len(synced_titles)}")


if __name__ == "__main__":
    run()