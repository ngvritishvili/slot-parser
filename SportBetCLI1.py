import os
import time
import requests
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

# Load configuration from .env
load_dotenv()

# --- CONFIGURATION ---
CASINO_NAME = "https://sportsbet.io" # Explicitly defined
API_ENDPOINT = os.getenv('API_ENDPOINT', 'http://checkthisone.online/api/slots/sync')
MAX_PAGES = int(os.getenv('MAX_PAGES', 3))
IS_HEADLESS = os.getenv('HEADLESS', 'True').lower() == 'true'
BASE_URL = "https://sportsbet.io"
CATEGORY_URL = "https://sportsbet.io/casino/categories/video-slots"

def sync_to_laravel(slots_data):
    """
    Sends data to Laravel API.
    """
    if not slots_data:
        print("   [API] No data to sync.")
        return False

    print(f"   [API] Syncing {len(slots_data)} slots to {API_ENDPOINT}...")
    try:
        response = requests.post(API_ENDPOINT, json=slots_data, timeout=120)

        if response.status_code == 200:
            res = response.json()
            details = res.get('details', {})
            print(f"   [SUCCESS] Added: {details.get('new_slots_added')}, Skipped: {details.get('existing_slots_skipped')}")
            return True
        else:
            print(f"   [API ERROR] {response.status_code}: {response.text}")
            return False
    except Exception as e:
        print(f"   [CONNECTION ERROR] Error: {e}")
        return False

def scrape_page(p, page_number):
    """
    Launches a fresh browser, context, and page for every page number.
    """
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
        page.goto(target_url, wait_until="networkidle", timeout=60000)

        # Wait for slot grid elements
        print("   Waiting for slot grid...")
        page.wait_for_selector('a[href*="/play/video-slots/"]', timeout=30000)

        # Scroll to trigger lazy loading of images
        page.evaluate("window.scrollBy(0, 1000)")
        page.wait_for_timeout(2000)

        links = page.query_selector_all('a[href*="/play/video-slots/"]')
        slots = []

        for link in links:
            try:
                # Find the container for provider name
                container = link.evaluate_handle("el => el.closest('div.flex-col')")
                if not container: continue

                img = link.query_selector('img')
                title = img.get_attribute('alt') if img else "Unknown"

                # Filter out generic play icons
                if not title or "play" in title.lower() or title == "Unknown":
                    continue

                avatar = img.get_attribute('src') if img else None
                url = f"{BASE_URL}{link.get_attribute('href')}"

                # Extract provider (usually the first line of text in the container)
                provider_text = page.evaluate('el => el.innerText', container).split('\n')[0]

                slots.append({
                    "title": title,
                    "provider": provider_text or "Unknown",
                    "url": url,
                    "avatar": avatar,
                    "casino_name": CASINO_NAME # <--- Correctly integrated
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
        # Crucial: Close browser every time to free up RAM
        browser.close()

def run():
    with sync_playwright() as p:
        for page_num in range(1, MAX_PAGES + 1):
            success = scrape_page(p, page_num)

            if not success:
                print(f"   Retrying Page {page_num} once in 10s...")
                time.sleep(10)
                scrape_page(p, page_num)

            # Polite delay between full browser launches
            time.sleep(5)

if __name__ == "__main__":
    run()