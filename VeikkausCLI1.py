import os
import time
import requests
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

load_dotenv()

# --- CONFIGURATION ---
CASINO_NAME = "Veikkaus"
API_ENDPOINT = os.getenv('API_ENDPOINT', 'http://checkthisone.online/api/slots/sync')
IS_HEADLESS = os.getenv('HEADLESS', 'True').lower() == 'true'
TARGET_URL = "https://www.veikkaus.fi/fi/nettikasino/automaattipelit"


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

        print(f">>> Opening {TARGET_URL}")
        page.goto(TARGET_URL, wait_until="networkidle", timeout=90000)

        synced_titles = set()

        while True:
            # 1. Wait for game cards using data-testid
            page.wait_for_selector('[data-testid="nettikasino-game-card"]', timeout=30000)

            # 2. Extract slots
            items = page.query_selector_all('[data-testid="nettikasino-game-card"]')
            new_batch = []

            for item in items:
                try:
                    # Title is in a specific text-title div
                    title_el = item.query_selector('[data-testid="game-card-text-title"]')
                    title = title_el.inner_text().strip() if title_el else ""

                    if title and title not in synced_titles:
                        # Image URL handling
                        img_el = item.query_selector('img')
                        raw_src = img_el.get_attribute('src') if img_el else ""

                        # Fix protocol-relative URLs (starts with //)
                        avatar = f"https:{raw_src}" if raw_src.startswith('//') else raw_src

                        new_batch.append({
                            "title": title,
                            "provider": "Veikkaus",  # Provider isn't explicitly listed in the card
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

            # 4. Handle "Show more" button
            # We target the data-testid for the load more button
            load_more = page.locator('[data-testid="casino-games-grid-load-more-button"]')

            if load_more.is_visible():
                print(f"--- Clicking 'Show more' (Total processed: {len(synced_titles)}) ---")
                load_more.scroll_into_view_if_needed()
                load_more.click()

                # Veikkaus uses React, give it time to render the next batch
                time.sleep(3)
            else:
                print(">>> Reached the end of the list.")
                break

            # Safety break for very large lists
            if len(synced_titles) > 5000: break

        browser.close()
        print(f"\n>>> Scrape Complete for Veikkaus. Total synced: {len(synced_titles)}")


if __name__ == "__main__":
    run()