import os
import time
import requests
import re
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

load_dotenv()

# --- CONFIGURATION ---
CASINO_NAME = "Jackbit"
API_ENDPOINT = os.getenv('API_ENDPOINT', 'http://checkthisone.online/api/slots/sync')
IS_HEADLESS = os.getenv('HEADLESS', 'True').lower() == 'true'
TARGET_URL = "https://jackbit.com/en/casino/casino?category=3"
BASE_URL = "https://jackbit.com"


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
            # FIX 1: Use domcontentloaded to avoid the 90s timeout
            page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=60000)

            # FIX 2: Explicitly wait for the list items to appear
            print("   Waiting for slots to load...")
            page.wait_for_selector('li[gameid]', timeout=45000)
        except Exception as e:
            print(f"!!! Load failed: {e}")
            page.screenshot(path="jackbit_error.png")
            browser.close()
            return

        synced_game_ids = set()

        while True:
            # 1. Extract slots
            items = page.query_selector_all('li[gameid]')
            new_batch = []

            for item in items:
                try:
                    game_id = item.get_attribute('gameid')

                    if game_id and game_id not in synced_game_ids:
                        # Extract Image from background-image style
                        bg_div = item.query_selector('.bg')
                        style = bg_div.get_attribute('style') if bg_div else ""

                        avatar = ""
                        if style:
                            match = re.search(r'url\(["\']?(.*?)["\']?\)', style)
                            if match:
                                avatar = match.group(1)

                        # FIX 3: Jackbit Title Extraction
                        # Often titles are only in the 'alt' of the play button or a hidden tooltip
                        # We'll try alt first, then title, then fallback to ID
                        img_play = item.query_selector('img.play')
                        title = ""
                        if img_play:
                            title = img_play.get_attribute('alt').replace(' icon', '').strip()

                        if not title or title.lower() == "play":
                            title = item.get_attribute('title') or f"Slot {game_id}"

                        new_batch.append({
                            "title": title,
                            "provider": "Unknown",
                            "url": f"https://jackbit.com/en/casino/casino?game={game_id}",
                            "avatar": avatar,
                            "casino_name": CASINO_NAME
                        })
                        synced_game_ids.add(game_id)
                except:
                    continue

            # 2. Sync to Laravel
            if new_batch:
                sync_to_laravel(new_batch)

            # 3. Handle "Show more" button
            # Targeted the specific class and text_key from your snippet
            load_more = page.locator('div.show-more.visible[text_key="CASINO__LOAD_MORE"]')

            if load_more.is_visible():
                print(f"--- Clicking 'Show more' (Total: {len(synced_game_ids)}) ---")
                load_more.scroll_into_view_if_needed()
                time.sleep(1)
                load_more.click()

                # 4. Wait for new items to actually mount to the DOM
                time.sleep(5)
            else:
                # Final check: scroll to bottom to see if button appears
                page.keyboard.press("End")
                time.sleep(2)
                if not load_more.is_visible():
                    print(">>> No more 'Show more' button found.")
                    break

            if len(synced_game_ids) > 6000: break

        browser.close()
        print(f"\n>>> Scrape Complete. Total: {len(synced_game_ids)}")


if __name__ == "__main__":
    run()