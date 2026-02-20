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
            # FIX 1: Bypass networkidle timeout
            page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=60000)
            # Wait for the specific data-testid pattern you provided
            page.wait_for_selector('[data-testid*="game"]', timeout=45000)
        except Exception as e:
            print(f"!!! Initial Load Failed: {e}")
            page.screenshot(path="casumo_error.png")
            browser.close()
            return

        synced_titles = set()

        # 2. Iterate through categories/rows
        # Casumo uses rows for different game types
        for _ in range(15):  # Vertical scroll loop

            # Find all horizontal scroll containers
            containers = page.query_selector_all('div.flex.overflow-x-auto')

            for container in containers:
                # Scroll the main window to the container first
                container.scroll_into_view_if_needed()

                # Inside each container, scroll right to reveal more games
                for scroll_step in range(5):
                    items = container.query_selector_all('[data-testid*="game"]')
                    new_batch = []

                    for item in items:
                        try:
                            img_el = item.query_selector('img')
                            if not img_el: continue

                            title = img_el.get_attribute('alt') or ""

                            if title and title not in synced_titles:
                                avatar = img_el.get_attribute('src') or ""

                                # Provider is in bg-purple-60 as per your snippet
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

                    # Horizontal Scroll inside the div
                    page.evaluate("(el) => el.scrollBy(1000, 0)", container)
                    time.sleep(1)

            # Scroll the whole page down to find more categories
            page.mouse.wheel(0, 1500)
            time.sleep(2)

            if len(synced_titles) > 10000: break

        browser.close()
        print(f"\n>>> Scrape Complete for Casumo. Total: {len(synced_titles)}")


if __name__ == "__main__":
    run()