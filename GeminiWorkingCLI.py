import os
import time
import requests
import sys
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

# Load configuration from .env
load_dotenv()

# Use the API URL from .env or fallback to localhost
API_ENDPOINT = os.getenv('API_ENDPOINT', 'http://127.0.0.1:8000/api/slots/sync')
MAX_PAGES = int(os.getenv('MAX_PAGES', 160))
IS_HEADLESS = os.getenv('HEADLESS', 'True').lower() == 'true'
BASE_URL = "https://sportsbet.io"
CATEGORY_URL = "https://sportsbet.io/casino/categories/video-slots"


def sync_to_laravel(slots_data):
    """
    Sends data to Laravel API.
    Required for Spatie Media Library to process images.
    """
    if not slots_data:
        print("   [API] No data to sync.")
        return False

    print(f"   [API] Syncing {len(slots_data)} slots to {API_ENDPOINT}...")
    try:
        # Timeout is 120s because Laravel needs time to download images via Spatie
        response = requests.post(API_ENDPOINT, json=slots_data, timeout=120)

        if response.status_code == 200:
            res = response.json()
            details = res.get('details', {})
            print(
                f"   [SUCCESS] Added: {details.get('new_slots_added')}, Skipped: {details.get('existing_slots_skipped')}")
            return True
        else:
            print(f"   [API ERROR] {response.status_code}: {response.text}")
            return False
    except Exception as e:
        print(f"   [CONNECTION ERROR] Is Laravel running? Error: {e}")
        return False


def scrape_page(p, page_number):
    browser = p.chromium.launch(headless=IS_HEADLESS)
    context = browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        viewport={'width': 1920, 'height': 1080}
    )
    page = context.new_page()
    Stealth().apply_stealth_sync(page)

    target_url = f"{CATEGORY_URL}?page={page_number}"
    print(f"\n--- Processing Page {page_number} ---")

    try:
        # Wait until network is quiet
        page.goto(target_url, wait_until="networkidle", timeout=60000)

        # Wait specifically for the grid to render
        print("   Waiting for slot grid...")
        page.wait_for_selector('a[href*="/play/video-slots/"]', timeout=30000)

        # Scroll to ensure images are in the DOM for Spatie to find later
        page.evaluate("window.scrollBy(0, 1000)")
        page.wait_for_timeout(2000)

        links = page.query_selector_all('a[href*="/play/video-slots/"]')
        slots = []

        for link in links:
            try:
                # Find the container to get the provider name
                container = link.evaluate_handle("el => el.closest('div.flex-col')")
                if not container: continue

                img = link.query_selector('img')
                title = img.get_attribute('alt') if img else "Unknown"

                # Filter out UI icons
                if not title or "play" in title.lower() or title == "Unknown":
                    continue

                avatar = img.get_attribute('src') if img else None
                url = f"{BASE_URL}{link.get_attribute('href')}"

                # Get provider text
                provider = page.evaluate('el => el.innerText', container).split('\n')[0]

                slots.append({
                    "title": title,
                    "provider": provider or "Unknown",
                    "url": url,
                    "avatar": avatar
                })
            except:
                continue

        if slots:
            return sync_to_laravel(slots)

        print(f"   [!] Page {page_number} appeared empty.")
        return False

    except Exception as e:
        print(f"   [Web ERROR] {e}")
        return False
    finally:
        browser.close()


def run():
    with sync_playwright() as p:
        # Starting from page 1, or adjust as needed
        for page_num in range(1, MAX_PAGES + 1):
            success = scrape_page(p, page_num)

            # If a page fails, wait 10 seconds and try one more time
            if not success:
                print(f"   Retrying Page {page_num} in 10s...")
                time.sleep(10)
                scrape_page(p, page_num)

            # Polite delay to avoid IP blocking
            time.sleep(5)


if __name__ == "__main__":
    run()