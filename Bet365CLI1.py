import os
import time
import requests
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

load_dotenv()

# Configuration
API_ENDPOINT = os.getenv('API_ENDPOINT', 'http://checkthisone.online/api/slots/sync')
IS_HEADLESS = os.getenv('HEADLESS', 'True').lower() == 'true'
TARGET_URL = "https://casino.bet365.com/all-games/VideoSlots"


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
        page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=60000)

        # Bet365 can be slow to start, wait for the first batch
        page.wait_for_selector('div[data-testid="launchGame"]', timeout=30000)

        synced_titles = set()  # Keep track of what we sent in this session
        scroll_attempts = 0
        max_scroll_attempts = 50  # Adjust based on how many games you want

        while scroll_attempts < max_scroll_attempts:
            # 1. Extract currently visible slots
            items = page.query_selector_all('div[data-testid="launchGame"]')
            new_batch = []

            for item in items:
                title = item.get_attribute('aria-label')

                # If we haven't synced this title yet, process it
                if title and title not in synced_titles:
                    img = item.query_selector('img.imageContainer')
                    avatar = img.get_attribute('src') if img else ""

                    # Bet365 images are often relative (//content...)
                    if avatar.startswith('//'):
                        avatar = 'https:' + avatar

                    new_batch.append({
                        "title": title,
                        "provider": "Bet365",  # Provider isn't explicitly in the HTML you gave
                        "url": TARGET_URL,  # Bet365 usually opens games in a modal
                        "avatar": avatar
                    })
                    synced_titles.add(title)

            # 2. Sync only the new ones found in this scroll
            if new_batch:
                sync_to_laravel(new_batch)

            # 3. Scroll down to trigger lazy load
            print(f"--- Scroll {scroll_attempts + 1}: Found {len(new_batch)} new items ---")
            page.evaluate("window.scrollBy(0, 1500)")
            time.sleep(3)  # Wait for lazy load

            # 4. Check if we reached the end (if no new items found after a few scrolls)
            if not new_batch:
                scroll_attempts += 1
            else:
                scroll_attempts = 0  # Reset attempts if we are still finding items

            # Safety break
            if len(synced_titles) > 2000: break

        browser.close()
        print(f"\n>>> Scrape Complete. Total synced: {len(synced_titles)}")


if __name__ == "__main__":
    run()