import os
import time
import requests
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

load_dotenv()

# Configuration
API_ENDPOINT = os.getenv('API_ENDPOINT', 'http://checkthisone.online/api/slots/sync')
MAX_PAGES = int(os.getenv('MAX_PAGES', 5))  # Set how many pages you want to click through
IS_HEADLESS = os.getenv('HEADLESS', 'True').lower() == 'true'
TARGET_URL = "https://bc.game/casino/slots"
BASE_URL = "https://bc.game"


def sync_to_laravel(slots_data):
    if not slots_data: return False
    print(f"   [API] Syncing {len(slots_data)} slots...")
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


def extract_slots(page):
    """Parses BC.Game slot items based on the provided HTML structure."""
    slots = []
    # Find all game item anchors
    items = page.query_selector_all('a.game-item')

    for item in items:
        try:
            url_path = item.get_attribute('href')
            url = f"{BASE_URL}{url_path}"

            img = item.query_selector('img')
            title = img.get_attribute('alt') if img else "Unknown"
            avatar = img.get_attribute('src') if img else ""

            # BC.Game often hides the provider name or puts it in the URL slug
            # For "the-luxe-h-v-by-hacksaw", we can extract 'hacksaw'
            provider = "Unknown"
            if "by-" in url_path:
                provider = url_path.split("by-")[-1].replace("-", " ").title()

            if title and title != "Unknown":
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
        browser = p.chromium.launch(headless=IS_HEADLESS)
        context = browser.new_context(viewport={'width': 1920, 'height': 1080})
        page = context.new_page()
        Stealth().apply_stealth_sync(page)

        print(f">>> Opening {TARGET_URL}")
        page.goto(TARGET_URL, wait_until="networkidle")

        for current_page in range(1, MAX_PAGES + 1):
            print(f"\n--- Processing Page {current_page} ---")

            # Wait for items to be visible
            page.wait_for_selector('a.game-item', timeout=30000)

            # Scroll to load all images on current view
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(2)

            slots = extract_slots(page)
            if slots:
                sync_to_laravel(slots)

            # --- PAGINATION LOGIC ---
            if current_page < MAX_PAGES:
                print("   Clicking Next Page...")
                try:
                    # Target the 'Next' arrow button (usually the last button in pagination)
                    # Or look for the button with the right arrow SVG
                    next_button = page.locator('button.next-btn, .pagination button').last

                    if next_button.is_visible():
                        next_button.click()
                        # Wait for the content to swap/refresh
                        time.sleep(3)
                        page.wait_for_load_state("networkidle")
                    else:
                        print("   No more pages found.")
                        break
                except Exception as e:
                    print(f"   Pagination failed: {e}")
                    break

        browser.close()
        print("\n>>> Scrape Complete.")


if __name__ == "__main__":
    run()