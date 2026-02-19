import os
import time
import requests
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

load_dotenv()

# --- CONFIGURATION ---
CASINO_NAME = "https://mrgreen.com"
API_ENDPOINT = os.getenv('API_ENDPOINT', 'http://checkthisone.online/api/slots/sync')
IS_HEADLESS = os.getenv('HEADLESS', 'True').lower() == 'true'
TARGET_URL = "https://www.mrgreen.com/slots/"


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
            # Use domcontentloaded to avoid the timeout
            page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=60000)
            # Wait for the game grid specifically
            page.wait_for_selector('.cy-single-game-regular-template', timeout=45000)
        except Exception as e:
            print(f"!!! Initial Load Failed: {e}")
            browser.close()
            return

        synced_titles = set()

        # 1. Identify containers that hold the swiper/sliders
        # We target the common parent of the game templates
        print("   Scanning page for sliders...")

        # 2. Extract slots by scrolling. Mr Green sliders usually expand
        # or load more as you scroll the main page down too.
        scroll_count = 0
        while scroll_count < 20:
            items = page.query_selector_all('.cy-single-game-regular-template')
            new_batch = []

            for item in items:
                try:
                    title_el = item.query_selector('.cy-game-title')
                    title = title_el.inner_text().strip() if title_el else ""

                    if title and title not in synced_titles:
                        img_el = item.query_selector('img.cy-game-image')
                        avatar = img_el.get_attribute('src') if img_el else ""

                        # Extract Provider from class list (it was in your element snippet)
                        classes = item.get_attribute('class') or ""
                        provider = "Unknown"
                        for cls in classes.split():
                            if cls.startswith('game-company-'):
                                provider = cls.replace('game-company-', '').capitalize()

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

            # 3. Horizontal Swiping Logic
            # Mr Green often uses a generic swiper-button-next
            next_buttons = page.locator('button.cy-swiper-button-next').all()
            for btn in next_buttons:
                if btn.is_visible() and btn.is_enabled():
                    btn.click()
                    time.sleep(0.5)

            # 4. Vertical Scrolling (to trigger more categories)
            page.mouse.wheel(0, 800)
            time.sleep(2)
            scroll_count += 1

            # If we've seen enough or the page stopped growing
            if len(synced_titles) > 5000: break

        browser.close()
        print(f"\n>>> Scrape Complete for Mr Green. Total synced: {len(synced_titles)}")


if __name__ == "__main__":
    run()