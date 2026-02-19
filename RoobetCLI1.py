import os
import time
import requests
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

load_dotenv()

# --- CONFIGURATION ---
CASINO_NAME = "Roobet"  # Consistent name for DB
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
    except Exception as e:
        print(f"   [API ERROR] {e}")
    return False


def run():
    with sync_playwright() as p:
        # Launch with extra arguments to help avoid Cloudflare detection
        browser = p.chromium.launch(headless=IS_HEADLESS, args=["--disable-blink-features=AutomationControlled"])
        context = browser.new_context(viewport={'width': 1920, 'height': 1080})
        page = context.new_page()
        Stealth().apply_stealth_sync(page)

        print(f">>> Opening {TARGET_URL} for {CASINO_NAME}")

        try:
            # CHANGE: wait_until="domcontentloaded" is much faster and reliable for SPAs
            page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=60000)

            # Now explicitly wait for the game links to appear
            print("   Waiting for game grid to render...")
            page.wait_for_selector('a[href^="/casino/game/"]', timeout=45000)
        except Exception as e:
            print(f"!!! Initial Load Failed: {e}")
            # Save screenshot for debugging
            page.screenshot(path="roobet_error.png")
            print("!!! Saved roobet_error.png. Check if blocked by Cloudflare.")
            browser.close()
            return

        synced_slugs = set()

        while True:
            # 1. Extract slots using the link selector
            items = page.query_selector_all('a[href^="/casino/game/"]')
            new_batch = []

            for item in items:
                try:
                    url_path = item.get_attribute('href')
                    slug = url_path.split('/')[-1] if url_path else ""

                    if slug and slug not in synced_slugs:
                        title = item.get_attribute('aria-label') or "Unknown"

                        # Logic to guess provider from slug (Roobet standard)
                        provider = "Unknown"
                        if slug:
                            parts = slug.split('-')
                            provider = parts[0].capitalize() if len(parts) > 0 else "Unknown"

                        # Image extraction
                        img_el = item.query_selector('img')
                        avatar = ""
                        if img_el:
                            raw_src = img_el.get_attribute('src') or ""
                            # Fix Roobet's relative CDN paths
                            if raw_src.startswith('/'):
                                avatar = f"{BASE_URL}{raw_src}"
                            elif 'cdn-cgi' in raw_src:
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

            if new_batch:
                sync_to_laravel(new_batch)

            # 2. Handle "Load More Games"
            # Roobet buttons are often nested in spans/divs
            load_more = page.get_by_role("button", name="Load More Games")

            if load_more.is_visible() and load_more.is_enabled():
                print(f"--- Clicking 'Load More' (Total seen: {len(synced_slugs)}) ---")
                load_more.scroll_into_view_if_needed()
                load_more.click()
                # Important: Roobet needs time to inject new items into the DOM
                time.sleep(5)
            else:
                # One last scroll attempt in case it's lazy loading
                page.keyboard.press("End")
                time.sleep(2)
                if not page.get_by_role("button", name="Load More Games").is_visible():
                    print(">>> No more 'Load More' button found.")
                    break

            if len(synced_slugs) > 5000: break

        browser.close()
        print(f"\n>>> Scrape Complete for Roobet. Total synced: {len(synced_slugs)}")


if __name__ == "__main__":
    run()