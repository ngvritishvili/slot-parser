import os
import time
import requests
import re
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

load_dotenv()

# --- CONFIGURATION ---
CASINO_NAME = "https://www.casumo.com"
API_ENDPOINT = os.getenv('API_ENDPOINT', 'http://checkthisone.online/api/slots/sync')
IS_HEADLESS = os.getenv('HEADLESS', 'True').lower() == 'true'
TARGET_URL = "https://www.casumo.com/row/slots/"


def slugify(text):
    """Converts 'Game Name' to 'game-name'"""
    text = text.lower().strip()
    text = re.sub(r'[^\w\s-]', '', text)
    return re.sub(r'[\s_-]+', '-', text)


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
        browser = p.chromium.launch(headless=IS_HEADLESS, args=[
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox"
        ])
        context = browser.new_context(viewport={'width': 1920, 'height': 1080})
        page = context.new_page()
        Stealth().apply_stealth_sync(page)

        print(f">>> Opening {TARGET_URL}")
        try:
            # Use a more lenient wait
            page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=60000)

            # Artificial wait to let React/Next.js hydrate the game grid
            print("   Waiting for elements to hydrate...")
            time.sleep(10)

            # Try to accept cookies if they appear
            cookie_btn = page.locator('button:has-text("Accept"), button:has-text("Allow")').first
            if cookie_btn.is_visible():
                cookie_btn.click()
                time.sleep(2)

        except Exception as e:
            print(f"!!! Page load issue: {e}")

        synced_titles = set()

        # Vertical loop to discover rows
        for v_step in range(15):
            # Target elements that match your snippet: data-testid containing 'game'
            items = page.query_selector_all('[data-testid*="game"]')
            new_batch = []

            if not items:
                print("   [DEBUG] No items found yet, scrolling...")

            for item in items:
                try:
                    img_el = item.query_selector('img')
                    if not img_el: continue

                    raw_title = img_el.get_attribute('alt') or ""
                    if not raw_title or raw_title in synced_titles:
                        continue

                    # 1. URL Generation: https://www.casumo.com/row/play/game-name/
                    game_slug = slugify(raw_title)
                    game_url = f"https://www.casumo.com/row/play/{game_slug}/"

                    # 2. Avatar extraction
                    avatar = img_el.get_attribute('src') or ""

                    # 3. Provider extraction from the purple div
                    provider_el = item.query_selector('.bg-purple-60')
                    provider = provider_el.inner_text().strip() if provider_el else "Unknown"

                    new_batch.append({
                        "title": raw_title,
                        "provider": provider,
                        "url": game_url,
                        "avatar": avatar,
                        "casino_name": CASINO_NAME
                    })
                    synced_titles.add(raw_title)
                except:
                    continue

            if new_batch:
                sync_to_laravel(new_batch)

            # Scroll to trigger more content
            # Horizontal rows usually load more when the page moves or row is interacted with
            page.mouse.wheel(0, 1000)
            time.sleep(3)

            if len(synced_titles) > 10000: break

        browser.close()
        print(f"\n>>> Scrape Complete. Total unique: {len(synced_titles)}")


if __name__ == "__main__":
    run()