# how to run? xvfb-run python3 bcGameCLI1.py
import os
import time
import requests
import re
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

load_dotenv()

# --- CONFIGURATION ---
CASINO_NAME = "https://bc.game"  # <--- Specify your static casino name here
API_ENDPOINT = os.getenv('API_ENDPOINT', 'http://checkthisone.online/api/slots/sync')
IS_HEADLESS = os.getenv('HEADLESS', 'True').lower() == 'true'
TARGET_URL = "https://bc.game/casino/slots"
BASE_URL = "https://bc.game"


def sync_to_laravel(slots_data):
    if not slots_data:
        return False
    print(f"   [API] Syncing {len(slots_data)} slots...")
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


def extract_slots(page, casino_name):
    slots = []
    items = page.query_selector_all('a.game-item')
    for item in items:
        try:
            url_path = item.get_attribute('href')
            url = f"{BASE_URL}{url_path}"
            img = item.query_selector('img')
            title = img.get_attribute('alt') if img else "Unknown"
            avatar = img.get_attribute('src') if img else ""

            provider = "Unknown"
            if "by-" in url_path:
                provider = url_path.split("by-")[-1].replace("-", " ").title()

            if title and "play" not in title.lower():
                slots.append({
                    "title": title,
                    "provider": provider,
                    "url": url,
                    "avatar": avatar,
                    "casino_name": casino_name
                })
        except:
            continue
    return slots


def run():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=IS_HEADLESS)
        context = browser.new_context(viewport={'width': 1920, 'height': 1080})
        page = context.new_page()
        Stealth().apply_stealth_sync(page)

        print(f">>> Opening {TARGET_URL} for {CASINO_NAME}")
        page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=60000)

        current_page = 1
        max_pages = 1

        while True:
            print(f"\n--- Processing Page {current_page} ---")

            # 1. Wait for content and scroll
            page.wait_for_selector('a.game-item', timeout=30000)
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(2)

            # 2. Detect Max Pages (Only on first run)
            if current_page == 1:
                try:
                    total_pages_text = page.locator('.pagination div span').last.inner_text()
                    max_pages = int(total_pages_text)
                    print(f">>> Detected Total Pages: {max_pages}")
                except:
                    print(">>> Could not detect pagination, using default.")
                    max_pages = 129

            # 3. Scrape and Sync
            slots = extract_slots(page, CASINO_NAME)
            if slots:
                sync_to_laravel(slots)

            # 4. Pagination Logic
            if current_page < max_pages:
                next_btn = page.locator('button.pagination-next')

                if next_btn.is_visible() and not next_btn.is_disabled():
                    # Capture the title of the first game to detect when the page flips
                    first_game_el = page.query_selector('a.game-item img')
                    old_first_title = first_game_el.get_attribute('alt') if first_game_el else ""

                    print(f"   Clicking Next (moving to {current_page + 1})...")
                    next_btn.click()

                    # 5. WAIT FOR CONTENT TO CHANGE
                    page_changed = False
                    for _ in range(20):  # 10 seconds max
                        time.sleep(0.5)
                        new_game_el = page.query_selector('a.game-item img')
                        new_first_title = new_game_el.get_attribute('alt') if new_game_el else ""

                        if new_first_title != old_first_title:
                            page_changed = True
                            break

                    if not page_changed:
                        print("   [Warning] Content didn't seem to change, but moving on...")

                    current_page += 1
                else:
                    print("   Next button is disabled or hidden. Finishing.")
                    break
            else:
                print("   Reached the last page.")
                break

        browser.close()
        print(f"\n>>> Scrape Complete for {CASINO_NAME}.")


if __name__ == "__main__":
    run()