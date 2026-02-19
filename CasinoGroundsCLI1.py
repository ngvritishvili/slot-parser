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
            # FIXED: Using your new Laravel response keys
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
        browser = p.chromium.launch(headless=IS_HEADLESS)
        context = browser.new_context(viewport={'width': 1920, 'height': 1080})
        page = context.new_page()
        Stealth().apply_stealth_sync(page)

        print(f">>> Opening {TARGET_URL}")
        try:
            page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=60000)
            # Wait for the grid to appear
            page.wait_for_selector('[data-testid^="game-card-"]', timeout=30000)
        except Exception as e:
            print(f"!!! Initial Load Failed: {e}")
            browser.close()
            return

        synced_titles = set()

        while True:
            # 1. SCROLL DOWN to ensure all currently loaded cards are rendered
            page.evaluate("window.scrollBy(0, 800)")
            time.sleep(1)

            # 2. Extract visible slots
            # We look for all cards, but focus on the ones with titles
            cards = page.query_selector_all('[data-testid^="game-card-"]')
            new_batch = []

            for card in cards:
                try:
                    # Target the title element specifically
                    title_el = card.query_selector('[data-testid$="-title"]')
                    if not title_el: continue

                    title = title_el.inner_text().strip()

                    if title and title not in synced_titles:
                        provider_el = card.query_selector('[data-testid$="-provider"]')
                        provider = provider_el.inner_text().strip() if provider_el else "Unknown"

                        img_el = card.query_selector('img')
                        avatar = img_el.get_attribute('src') if img_el else ""

                        # Some cards have links, some don't. We try to find an <a> tag.
                        link_el = card.query_selector('a')
                        url = link_el.get_attribute('href') if link_el else TARGET_URL
                        if url and url.startswith('/'):
                            url = f"https://casinogrounds.com{url}"

                        new_batch.append({
                            "title": title,
                            "provider": provider,
                            "url": url,
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
                print("   (No new items found in this view)")

            # 4. Handle "Load More"
            # CasinoGrounds button often has specific classes or just text
            load_more = page.locator('button:has-text("Load More"), button:has-text("LOAD MORE")')

            if load_more.is_visible():
                print(f"--- Clicking 'Load More' (Seen so far: {len(synced_titles)}) ---")
                load_more.scroll_into_view_if_needed()
                time.sleep(1)
                load_more.click()

                # IMPORTANT: Wait for the network to fetch more items
                time.sleep(4)
            else:
                # One last scroll to be sure
                page.keyboard.press("End")
                time.sleep(2)
                if not load_more.is_visible():
                    print(">>> No 'Load More' button visible. Reached end.")
                    break

            if len(synced_titles) > 10000: break

        browser.close()
        print(f"\n>>> Scrape Complete for CasinoGrounds. Total unique: {len(synced_titles)}")


if __name__ == "__main__":
    run()