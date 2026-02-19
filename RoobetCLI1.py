import os
import time
import requests
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

load_dotenv()

# --- CONFIGURATION ---
CASINO_NAME = "Roobet"
API_ENDPOINT = os.getenv('API_ENDPOINT', 'http://checkthisone.online/api/slots/sync')
IS_HEADLESS = os.getenv('HEADLESS', 'True').lower() == 'true'
TARGET_URL = "https://roobet.com/casino/category/slots?sort=pop_desc"
BASE_URL = "https://roobet.com"


def sync_to_laravel(slots_data):
    if not slots_data: return False
    print(f"   [API] Syncing {len(slots_data)} slots...")
    try:
        response = requests.post(API_ENDPOINT, json=slots_data, timeout=120)
        if response.status_code == 200:
            res = response.json()
            details = res.get('details', {})
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
            page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_selector('a[href^="/casino/game/"]', timeout=45000)
        except Exception as e:
            print(f"!!! Initial Load Failed. Check connection.")
            browser.close()
            return

        synced_slugs = set()

        while True:
            # 1. Aggressive Scroll to find the button
            print("   Scrolling to find 'Load More' button...")
            for _ in range(8):  # 8 small scrolls to trigger lazy load
                page.mouse.wheel(0, 1000)
                time.sleep(0.5)

            # 2. Extract items currently visible
            items = page.query_selector_all('a[href^="/casino/game/"]')
            new_batch = []
            for item in items:
                try:
                    url_path = item.get_attribute('href')
                    slug = url_path.split('/')[-1] if url_path else ""
                    if slug and slug not in synced_slugs:
                        title = item.get_attribute('aria-label') or "Unknown"
                        img_el = item.query_selector('img')
                        avatar = img_el.get_attribute('src') if img_el else ""
                        if avatar.startswith('/'): avatar = f"{BASE_URL}{avatar}"

                        # Provider from slug
                        provider = slug.split('-')[0].capitalize() if '-' in slug else "Unknown"

                        new_batch.append({
                            "title": title, "provider": provider, "url": f"{BASE_URL}{url_path}",
                            "avatar": avatar, "casino_name": CASINO_NAME
                        })
                        synced_slugs.add(slug)
                except:
                    continue

            if new_batch:
                sync_to_laravel(new_batch)

            # 3. Handle Button with Retry
            found_button = False
            # Search for the button using a very loose class + text combo
            load_more_selector = 'button:has-text("Load More Games")'

            for retry in range(3):  # Try 3 times to find the button
                btn = page.locator(load_more_selector)
                if btn.count() > 0 and btn.is_visible():
                    print(f"--- Clicking 'Load More' (Total seen: {len(synced_slugs)}) ---")
                    btn.scroll_into_view_if_needed()
                    time.sleep(1)
                    btn.click(force=True)
                    found_button = True
                    time.sleep(6)  # Give Roobet plenty of time to load
                    break
                else:
                    # Scroll a bit more if not found
                    page.evaluate("window.scrollBy(0, 1500)")
                    time.sleep(2)

            if not found_button:
                # Final check: is there a loader?
                if page.locator('div[class*="MuiCircularProgress"]').is_visible():
                    print("   Waiting for loading spinner...")
                    time.sleep(5)
                    continue  # Try loop again

                print(">>> No more 'Load More' button found. Finishing.")
                break

            if len(synced_slugs) > 10000: break

        browser.close()
        print(f"\n>>> Scrape Complete. Total unique: {len(synced_slugs)}")


if __name__ == "__main__":
    run()