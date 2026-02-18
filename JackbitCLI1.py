import os
import time
import requests
import re
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

load_dotenv()

# --- CONFIGURATION ---
CASINO_NAME = "https://jackbit.com"
API_ENDPOINT = os.getenv('API_ENDPOINT', 'http://checkthisone.online/api/slots/sync')
IS_HEADLESS = os.getenv('HEADLESS', 'True').lower() == 'true'
TARGET_URL = "https://jackbit.com/en/casino/casino?category=3"
BASE_URL = "https://jackbit.com"


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

        print(f">>> Opening {TARGET_URL}")
        page.goto(TARGET_URL, wait_until="networkidle", timeout=90000)

        synced_game_ids = set()

        while True:
            # 1. Wait for the list items
            page.wait_for_selector('li[gameid]', timeout=30000)

            # 2. Extract slots
            items = page.query_selector_all('li[gameid]')
            new_batch = []

            for item in items:
                try:
                    game_id = item.get_attribute('gameid')

                    if game_id and game_id not in synced_game_ids:
                        # Extract Image from background-image style
                        bg_div = item.query_selector('.bg')
                        style = bg_div.get_attribute('style') if bg_div else ""

                        # Regex to pull URL from background-image: url(...)
                        avatar = ""
                        if style:
                            match = re.search(r'url\("?(.*?)"?\)', style)
                            if match:
                                avatar = match.group(1)

                        # Jackbit usually stores the title in a tooltip or data attribute
                        # If not visible in the snippet, we'll try to get it from the alt of the play icon
                        # or use a placeholder until clicked.
                        # NOTE: Often these sites have the title in a 'title' attribute on the <li>
                        title = item.get_attribute('title') or f"Slot {game_id}"

                        new_batch.append({
                            "title": title,
                            "provider": "Unknown",  # Jackbit categories don't explicitly show provider in this view
                            "url": f"{TARGET_URL}&game={game_id}",
                            "avatar": avatar,
                            "casino_name": CASINO_NAME
                        })
                        synced_game_ids.add(game_id)
                except:
                    continue

            # 3. Sync to Laravel
            if new_batch:
                sync_to_laravel(new_batch)

            # 4. Handle "Show more" button
            # We use the text_key or the class
            load_more = page.locator('.show-more.visible')

            if load_more.is_visible():
                print(f"--- Clicking 'Show more' (Total: {len(synced_game_ids)}) ---")
                load_more.scroll_into_view_if_needed()
                load_more.click()

                # Jackbit can be slow to append new <li> elements
                time.sleep(4)
            else:
                print(">>> No more 'Show more' button found.")
                break

            if len(synced_game_ids) > 6000: break

        browser.close()
        print(f"\n>>> Scrape Complete. Total: {len(synced_game_ids)}")


if __name__ == "__main__":
    run()