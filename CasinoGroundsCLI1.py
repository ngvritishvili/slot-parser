import os
import time
import requests
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

load_dotenv()

# --- CONFIGURATION ---
CASINO_NAME = "CasinoGrounds"
API_ENDPOINT = os.getenv('API_ENDPOINT', 'http://checkthisone.online/api/slots/sync')
IS_HEADLESS = os.getenv('HEADLESS', 'True').lower() == 'true'
TARGET_URL = "https://casinogrounds.com/slots/"


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
        browser = p.chromium.launch(headless=IS_HEADLESS)
        context = browser.new_context(viewport={'width': 1920, 'height': 1080})
        page = context.new_page()
        Stealth().apply_stealth_sync(page)

        print(f">>> Opening {TARGET_URL}")
        try:
            page.goto(TARGET_URL, wait_until="networkidle", timeout=60000)
        except:
            page.goto(TARGET_URL, wait_until="domcontentloaded")

        synced_titles = set()

        while True:
            # 1. Wait for any game card title to ensure the grid is loaded
            page.wait_for_selector('[data-testid$="-title"]', timeout=30000)

            # 2. Extract visible slots
            # We target only the parent DIVs that have an ID like game-card-0, game-card-1
            # The regex ^game-card-\d+$ ensures we only get the root containers
            cards = page.query_selector_all('div[data-testid^="game-card-"]')

            new_batch = []
            for card in cards:
                try:
                    testid = card.get_attribute('data-testid')
                    # Skip sub-elements like "game-card-0-image"
                    if not testid or not testid.split('-')[-1].isdigit():
                        continue

                    title_el = card.query_selector('[data-testid$="-title"]')
                    title = title_el.inner_text().strip() if title_el else ""

                    if title and title not in synced_titles:
                        provider_el = card.query_selector('[data-testid$="-provider"]')
                        provider = provider_el.inner_text().strip() if provider_el else "Unknown"

                        # Image handling
                        img_el = card.query_selector('img[data-testid$="-image"]')
                        avatar = img_el.get_attribute('src') if img_el else ""

                        # URL handling - CasinoGrounds usually wraps the image or title in a link
                        # but your snippet shows a "GO TO CASINO" link inside.
                        # We'll use the title as a slug generator or find the specific link.
                        new_batch.append({
                            "title": title,
                            "provider": provider,
                            "url": TARGET_URL,  # Or find internal link if exists
                            "avatar": avatar,
                            "casino_name": CASINO_NAME
                        })
                        synced_titles.add(title)
                except:
                    continue

            # 3. Sync found items
            if new_batch:
                sync_to_laravel(new_batch)
            else:
                print("   (No new items found in current view)")

            # 4. Handle "Load More"
            # The button is often "LOAD MORE" or "Load More"
            load_more = page.locator('button:has-text("Load More")').first

            if load_more.is_visible():
                print(f"--- Clicking 'Load More' (Seen so far: {len(synced_titles)}) ---")
                load_more.scroll_into_view_if_needed()
                time.sleep(1)
                load_more.click()

                # Give it time to inject new DOM elements
                time.sleep(5)
                # Force a scroll to trigger lazy loading of the new elements
                page.evaluate("window.scrollBy(0, 1000)")
                time.sleep(2)
            else:
                print(">>> No 'Load More' button found or reached end.")
                break

            if len(synced_titles) > 10000: break

        browser.close()
        print(f"\n>>> Scrape Complete. Total: {len(synced_titles)}")


if __name__ == "__main__":
    run()