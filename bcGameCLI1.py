import os
import time
import requests
import re
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

# 1. Load configuration
load_dotenv()

# Settings from .env
API_ENDPOINT = os.getenv('API_ENDPOINT', 'http://checkthisone.online/api/slots/sync')
IS_HEADLESS = os.getenv('HEADLESS', 'True').lower() == 'true'
TARGET_URL = "https://bc.game/casino/slots"
BASE_URL = "https://bc.game"


def sync_to_laravel(slots_data):
    """Sends the scraped slots to your Laravel API for Spatie Media processing."""
    if not slots_data:
        return False

    print(f"   [API] Syncing {len(slots_data)} slots to Laravel...")
    try:
        # 120s timeout to allow Spatie time to download images
        response = requests.post(API_ENDPOINT, json=slots_data, timeout=120)

        if response.status_code == 200:
            res = response.json()
            details = res.get('details', {})
            print(
                f"   [SUCCESS] Added: {details.get('new_slots_added')}, Skipped: {details.get('existing_slots_skipped')}")
            return True
        else:
            print(f"   [API ERROR] Status {response.status_code}: {response.text}")
            return False
    except Exception as e:
        print(f"   [CONNECTION ERROR] {e}")
        return False


def extract_slots(page):
    """Parses the grid items from the current view."""
    slots = []
    # Targeted selector based on your HTML snippet
    items = page.query_selector_all('a.game-item')

    for item in items:
        try:
            url_path = item.get_attribute('href')
            url = f"{BASE_URL}{url_path}"

            img = item.query_selector('img')
            title = img.get_attribute('alt') if img else "Unknown"
            avatar = img.get_attribute('src') if img else ""

            # Logic to extract provider name from the URL slug
            provider = "Unknown"
            if "by-" in url_path:
                # Extracts 'hacksaw' from 'the-luxe-h-v-by-hacksaw'
                provider = url_path.split("by-")[-1].replace("-", " ").title()

            # Filter out UI elements or empty titles
            if title and "play" not in title.lower() and title != "Unknown":
                slots.append({
                    "title": title,
                    "provider": provider,
                    "url": url,
                    "avatar": avatar
                })
        except:
            continue
    return slots


def run():
    with sync_playwright() as p:
        # Launch Browser
        browser = p.chromium.launch(headless=IS_HEADLESS)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            viewport={'width': 1920, 'height': 1080}
        )
        page = context.new_page()
        Stealth().apply_stealth_sync(page)

        print(f">>> Navigating to {TARGET_URL}")
        page.goto(TARGET_URL, wait_until="networkidle", timeout=60000)

        current_page = 1
        max_pages = 1  # This will be updated dynamically from the UI

        while True:
            print(f"\n--- Processing Page {current_page} ---")

            # 1. Wait for game items to appear
            page.wait_for_selector('a.game-item', timeout=30000)

            # 2. Scroll to bottom to ensure pagination element is rendered
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(2)

            # 3. On the first page, detect the total number of pages (e.g., 129)
            if current_page == 1:
                try:
                    # Targets the span inside the pagination div: <span>129</span>
                    total_pages_element = page.locator('.pagination div span').last
                    max_pages = int(total_pages_element.inner_text())
                    print(f">>> Detected Total Pages: {max_pages}")
                except Exception as e:
                    print(f">>> Could not detect total pages, using fallback. Error: {e}")
                    max_pages = 160

                    # 4. Scrape data
            slots_found = extract_slots(page)
            if slots_found:
                sync_to_laravel(slots_found)
            else:
                print("   [!] No slots found on this page.")

                # 5. Handle Pagination
                if current_page < max_pages:
                    next_btn = page.locator('button.pagination-next')

                    if next_btn.count() > 0 and next_btn.is_visible() and not next_btn.is_disabled():
                        print(f"   Moving to next page ({current_page} -> {current_page + 1})...")

                        # Store current first game title to detect when the page actually changes
                        first_game = page.query_selector('a.game-item img')
                        old_title = first_game.get_attribute('alt') if first_game else ""

                        next_btn.click()

                        # Relaxed Wait Logic:
                        try:
                            # 1. Wait for the URL or DOM to stabilize slightly
                            page.wait_for_load_state("domcontentloaded", timeout=10000)

                            # 2. Wait until the first game's title is different from the old one
                            # This confirms the new set of games has loaded
                            def title_changed(p):
                                new_el = p.query_selector('a.game-item img')
                                if not new_el: return False
                                return new_el.get_attribute('alt') != old_title

                            # Wait up to 15 seconds for the content to swap
                            for _ in range(30):  # 30 * 0.5s = 15s
                                if title_changed(page):
                                    break
                                time.sleep(0.5)

                        except Exception as e:
                            print(f"   [Note] Transition wait finished with notice: {e}")

                        current_page += 1
                    else:
                        print("   Next button is missing or disabled. Ending run.")
                        break

        browser.close()
        print("\n>>> All pages processed.")


if __name__ == "__main__":
    run()