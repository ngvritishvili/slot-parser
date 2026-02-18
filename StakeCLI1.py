import os
import time
import requests
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

load_dotenv()

# --- CONFIGURATION ---
CASINO_NAME = "Stake"
API_ENDPOINT = os.getenv('API_ENDPOINT', 'http://checkthisone.online/api/slots/sync')
IS_HEADLESS = os.getenv('HEADLESS', 'True').lower() == 'true'
TARGET_URL = "https://stake.com/casino/group/slots"
BASE_URL = "https://stake.com"


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
        # Stake often detects headless Chromium. We add args to be more human-like.
        browser = p.chromium.launch(headless=IS_HEADLESS, args=["--disable-blink-features=AutomationControlled"])
        context = browser.new_context(viewport={'width': 1920, 'height': 1080})
        page = context.new_page()
        Stealth().apply_stealth_sync(page)

        print(f">>> Opening {TARGET_URL} for {CASINO_NAME}")

        try:
            # FIX: Use 'commit' instead of 'networkidle'
            page.goto(TARGET_URL, wait_until="commit", timeout=60000)

            # Manual wait for the content to actually render
            print("   Waiting for initial grid load...")
            page.wait_for_selector('a[href*="/casino/games/"]', timeout=45000)

        except Exception as e:
            print(f"!!! Initial Load Error: {e}")
            # If it times out, we try to proceed anyway if some cards are visible
            if page.query_selector_all('a[href*="/casino/games/"]').__len__() == 0:
                browser.close()
                return

        synced_ids = set()

        while True:
            # 1. Extract currently visible slots
            # Note: Stake's classes (svelte-zglogk) change often, targeting href is safer
            items = page.query_selector_all('a[href*="/casino/games/"]')
            new_batch = []

            for item in items:
                try:
                    url_path = item.get_attribute('href')
                    game_id = url_path.split('/')[-1] if url_path else ""

                    if game_id and game_id not in synced_ids:
                        # Stake's DOM is nested. We look for the alt on img or the span text
                        img_el = item.query_selector('img')
                        title = img_el.get_attribute('alt') if img_el else "Unknown"

                        # Provider is usually in the second text block
                        # We use a broad selector to find the provider text
                        provider = "Unknown"
                        provider_el = item.query_selector('p, span.provider-name, strong')
                        if provider_el:
                            provider = provider_el.inner_text().strip()

                        avatar = img_el.get_attribute('src') if img_el else ""

                        new_batch.append({
                            "title": title,
                            "provider": provider,
                            "url": f"{BASE_URL}{url_path}",
                            "avatar": avatar,
                            "casino_name": CASINO_NAME
                        })
                        synced_ids.add(game_id)
                except:
                    continue

            if new_batch:
                sync_to_laravel(new_batch)

            # 2. Handle "Load More"
            # Stake uses a button that often contains a 'loader' div
            load_more = page.get_by_role("button", name="Load More")

            if load_more.is_visible() and load_more.is_enabled():
                print(f"--- Clicking 'Load More' (Total seen: {len(synced_ids)}) ---")
                load_more.scroll_into_view_if_needed()
                load_more.click()
                time.sleep(4)  # Stake needs a long breath to load next 30+ items
            else:
                # Scroll down one last time to check if more appear (Lazy load check)
                page.evaluate("window.scrollBy(0, 500)")
                time.sleep(2)
                if not page.get_by_role("button", name="Load More").is_visible():
                    print(">>> No 'Load More' button found. Reached the end.")
                    break

            if len(synced_ids) > 10000: break

        browser.close()
        print(f"\n>>> Scrape Complete for Stake. Total synced: {len(synced_ids)}")


if __name__ == "__main__":
    run()