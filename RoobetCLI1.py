import os
import time
import requests
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

load_dotenv()

# --- CONFIGURATION ---
CASINO_NAME = "https://roobet.com"
API_ENDPOINT = os.getenv('API_ENDPOINT', 'http://checkthisone.online/api/slots/sync')
IS_HEADLESS = os.getenv('HEADLESS', 'True').lower() == 'true'
TARGET_URL = "https://roobet.com/casino/category/slots?sort=pop_desc"
BASE_URL = "https://roobet.com"


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

        print(f">>> Opening {TARGET_URL} for {CASINO_NAME}")
        # Roobet has heavy Cloudflare; waiting for networkidle is safer here
        page.goto(TARGET_URL, wait_until="networkidle", timeout=90000)

        synced_slugs = set()

        while True:
            # 1. Wait for game items (MUI Link roots)
            page.wait_for_selector('a[href^="/casino/game/"]', timeout=30000)

            # 2. Extract slots
            items = page.query_selector_all('a[href^="/casino/game/"]')
            new_batch = []

            for item in items:
                try:
                    url_path = item.get_attribute('href')
                    # Roobet slugs often look like /casino/game/provider-title
                    slug = url_path.split('/')[-1] if url_path else ""

                    if slug and slug not in synced_slugs:
                        title = item.get_attribute('aria-label') or "Unknown"

                        # Extract Provider from the slug if possible
                        # Roobet URLs usually start with provider name: pragmatic-play-gates...
                        provider = "Unknown"
                        if slug:
                            parts = slug.split('-')
                            provider = parts[0].title() if len(parts) > 0 else "Unknown"

                        # Extract Image
                        img_el = item.query_selector('img')
                        avatar = ""
                        if img_el:
                            raw_src = img_el.get_attribute('src') or ""
                            # Handle Roobet's cdn-cgi relative paths
                            if raw_src.startswith('cdn-cgi'):
                                avatar = f"{BASE_URL}/{raw_src}"
                            else:
                                avatar = raw_src

                        new_batch.append({
                            "title": title,
                            "provider": provider,
                            "url": f"{BASE_URL}{url_path}",
                            "avatar": avatar,
                            "casino_name": CASINO_NAME
                        })
                        synced_slugs.add(slug)
                except:
                    continue

            # 3. Sync
            if new_batch:
                sync_to_laravel(new_batch)

            # 4. Handle "Load More Games" button
            # We use the text content specifically inside the MUI button span
            load_more = page.locator('button:has-text("Load More Games")')

            if load_more.count() > 0 and load_more.is_visible():
                print(f"--- Clicking 'Load More' (Total seen: {len(synced_slugs)}) ---")
                load_more.scroll_into_view_if_needed()
                load_more.click()

                # Give Roobet time to fetch next batch
                time.sleep(4)
            else:
                # Check if we are actually at the bottom or if it's just loading
                print(">>> No more 'Load More' button found.")
                break

            if len(synced_slugs) > 5000: break

        browser.close()
        print(f"\n>>> Scrape Complete for Roobet. Total synced: {len(synced_slugs)}")


if __name__ == "__main__":
    run()