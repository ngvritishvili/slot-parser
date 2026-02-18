import os
import time
import requests
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

load_dotenv()

# --- CONFIGURATION ---
CASINO_NAME = "https://www.mrgreen.com"
API_ENDPOINT = os.getenv('API_ENDPOINT', 'http://checkthisone.online/api/slots/sync')
IS_HEADLESS = os.getenv('HEADLESS', 'True').lower() == 'true'
TARGET_URL = "https://www.mrgreen.com/slots/"


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
        browser = p.chromium.launch(headless=IS_HEADLESS)
        context = browser.new_context(viewport={'width': 1920, 'height': 1080})
        page = context.new_page()
        Stealth().apply_stealth_sync(page)

        print(f">>> Opening {TARGET_URL}")
        page.goto(TARGET_URL, wait_until="networkidle", timeout=90000)

        synced_titles = set()

        # 1. Identify all Swiper/Carousel sections on the page
        # Each section usually has its own 'Next' button
        swipers = page.query_selector_all('.sc-cLVkoy')  # The container for the next button

        print(f">>> Found {len(swipers)} game categories to scroll.")

        # 2. Iterate through each horizontal slider
        for index, swiper_container in enumerate(swipers):
            print(f"--- Processing Slider {index + 1} ---")

            # Find the 'Next' button specifically within this slider
            next_btn = swiper_container.query_selector('button.cy-swiper-button-next')

            # Click next until the button is disabled or disappears (end of list)
            # We use a loop for horizontal sliding
            for _ in range(15):  # Arbitrary limit per category to avoid infinite loops

                # Extract visible slots in this specific moment
                items = page.query_selector_all('.cy-single-game-regular-template')
                new_batch = []

                for item in items:
                    title_el = item.query_selector('.cy-game-title')
                    title = title_el.inner_text().strip() if title_el else ""

                    if title and title not in synced_titles:
                        # Extract image
                        img_el = item.query_selector('img.cy-game-image')
                        avatar = img_el.get_attribute('src') if img_el else ""

                        # Extract Provider from class names (e.g., game-company-pragmatic)
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

                if new_batch:
                    sync_to_laravel(new_batch)

                # Check if we can click 'Next'
                if next_btn and next_btn.is_visible() and next_btn.is_enabled():
                    next_btn.click()
                    time.sleep(1)  # Short wait for the slide animation
                else:
                    break  # Reached the end of this slider

        browser.close()
        print(f"\n>>> Scrape Complete for Mr Green. Total: {len(synced_titles)}")


if __name__ == "__main__":
    run()