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
    print(f"   [API] Syncing {len(slots_data)} slots to {API_ENDPOINT}...")
    try:
        response = requests.post(API_ENDPOINT, json=slots_data, timeout=120)
        if response.status_code == 200:
            res = response.json()
            details = res.get('details', {})
            # Updated keys to match your Laravel refactor
            new = details.get('new_links_added', 0)
            skipped = details.get('existing_links_skipped', 0)
            print(f"   [SUCCESS] New Links: {new}, Skipped: {skipped}")
            return True
        else:
            print(f"   [API ERROR] {response.status_code}: {response.text}")
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
            print(f"!!! Initial Load Failed: {e}")
            page.screenshot(path="roobet_error.png")
            browser.close()
            return

        synced_slugs = set()

        while True:
            # 1. Scroll to the bottom to trigger image loading and button visibility
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(2)

            # 2. Extract items
            items = page.query_selector_all('a[href^="/casino/game/"]')
            new_batch = []

            for item in items:
                try:
                    url_path = item.get_attribute('href')
                    slug = url_path.split('/')[-1] if url_path else ""

                    if slug and slug not in synced_slugs:
                        title = item.get_attribute('aria-label') or "Unknown"

                        # Better provider extraction from aria-label if available
                        # Often aria-label is "Game Title by Provider"
                        provider = "Unknown"
                        if " by " in title.lower():
                            provider = title.lower().split(" by ")[-1].title()
                        elif slug:
                            provider = slug.split('-')[0].capitalize()

                        img_el = item.query_selector('img')
                        avatar = ""
                        if img_el:
                            avatar = img_el.get_attribute('src') or ""
                            if avatar.startswith('/'):
                                avatar = f"{BASE_URL}{avatar}"

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

            # 3. Send to Laravel
            if new_batch:
                sync_to_laravel(new_batch)

            # 4. Handle "Load More"
            # Roobet uses a button that might be hidden under a 'Load More Games' text
            load_more = page.get_by_role("button", name="Load More Games")

            if load_more.is_visible():
                print(f"--- Clicking 'Load More' (Seen so far: {len(synced_slugs)}) ---")
                load_more.click()
                time.sleep(5)  # Critical wait for content injection
            else:
                # Last ditch effort: scroll again
                page.evaluate("window.scrollBy(0, -500)")  # Scroll up slightly
                time.sleep(1)
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")  # Scroll down
                time.sleep(2)

                if not load_more.is_visible():
                    print(">>> No more 'Load More' button found.")
                    break

            if len(synced_slugs) > 10000: break

        browser.close()
        print(f"\n>>> Scrape Complete. Total: {len(synced_slugs)}")


if __name__ == "__main__":
    run()