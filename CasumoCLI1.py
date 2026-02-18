import os
import time
import requests
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

load_dotenv()

# --- CONFIGURATION ---
CASINO_NAME = "https://www.casumo.com"
API_ENDPOINT = os.getenv('API_ENDPOINT', 'http://checkthisone.online/api/slots/sync')
IS_HEADLESS = os.getenv('HEADLESS', 'True').lower() == 'true'
TARGET_URL = "https://www.casumo.com/row/slots/"


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

        # 1. Identify all horizontal containers
        # Casumo typically wraps these in divs with overflow-x-auto or specific flex layouts
        # We target the parent of the game cards
        horizontal_containers = page.query_selector_all('div.flex.overflow-x-auto, [class*="horizontal-scroll"]')

        print(f">>> Found {len(horizontal_containers)} horizontal categories.")

        # 2. Iterate through categories
        for container in horizontal_containers:
            # Scroll to the container so images start lazy-loading
            container.scroll_into_view_if_needed()

            # We will scroll right in steps to trigger lazy loading and find all slots
            for _ in range(10):  # Scroll right 10 times per category
                items = container.query_selector_all('[data-testid^="gameOfWeek-games-"], [data-testid*="game"]')
                new_batch = []

                for item in items:
                    try:
                        title = item.query_selector('img').get_attribute('alt') or ""

                        if title and title not in synced_titles:
                            # Extract Image
                            img_el = item.query_selector('img')
                            avatar = img_el.get_attribute('src') if img_el else ""

                            # Extract Provider (usually in the purple-60 background div)
                            provider_el = item.query_selector('.bg-purple-60')
                            provider = provider_el.inner_text().strip() if provider_el else "Unknown"

                            new_batch.append({
                                "title": title,
                                "provider": provider,
                                "url": TARGET_URL,
                                "avatar": avatar,
                                "casino_name": CASINO_NAME
                            })
                            synced_titles.add(title)
                    except:
                        continue

                if new_batch:
                    sync_to_laravel(new_batch)

                # Scroll the container to the right
                page.evaluate("(el) => el.scrollBy(800, 0)", container)
                time.sleep(1.5)  # Wait for animation/lazy load

        # 3. Handle General Vertical Scroll (in case there are more categories below)
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        time.sleep(2)

        browser.close()
        print(f"\n>>> Scrape Complete for Casumo. Total: {len(synced_titles)}")


if __name__ == "__main__":
    run()