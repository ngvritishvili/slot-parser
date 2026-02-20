import os
import time
import requests
import re
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

load_dotenv()

# --- CONFIGURATION ---
# User requested specific CASINO_NAME format
CASINO_NAME = "https://duelbits.com"
API_ENDPOINT = os.getenv('API_ENDPOINT', 'http://checkthisone.online/api/slots/sync')
IS_HEADLESS = os.getenv('HEADLESS', 'True').lower() == 'true'
TARGET_URL = "https://duelbits.com/en/slots"
BASE_URL = "https://duelbits.com"


def sync_to_laravel(slots_data):
    if not slots_data: return False
    print(f"   [API] Syncing {len(slots_data)} slots...")
    try:
        response = requests.post(API_ENDPOINT, json=slots_data, timeout=120)
        if response.status_code == 200:
            res = response.json()
            details = res.get('details', {})
            # Using updated keys
            new = details.get('new_links_added', 0)
            skipped = details.get('existing_links_skipped', 0)
            print(f"   [SUCCESS] New: {new}, Skipped: {skipped}")
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
        # Use a real user agent to bypass simple filters
        context = browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        page = context.new_page()
        Stealth().apply_stealth_sync(page)

        print(f">>> Opening {TARGET_URL}")
        try:
            # FIX 1: Use 'domcontentloaded' instead of 'networkidle'
            page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=60000)

            # Artificial wait for hydration
            print("   Waiting for game grid...")
            page.wait_for_selector('div[class*="cardContainer"]', timeout=30000)
        except Exception as e:
            print(f"!!! Load failed or timed out: {e}")
            page.screenshot(path="duelbits_error.png")

        synced_slugs = set()

        while True:
            # 2. Extract visible slots using the specific classes from your element
            # Select the container and then find the link inside
            containers = page.query_selector_all('div[class*="styles_cardContainer"]')
            new_batch = []

            for container in containers:
                try:
                    link_el = container.query_selector('a[href^="/slots/"]')
                    if not link_el: continue

                    url_path = link_el.get_attribute('href')
                    slug = url_path.split('/')[-1] if url_path else ""

                    if slug and slug not in synced_slugs:
                        img_el = container.query_selector('img')
                        title = img_el.get_attribute('alt') if img_el else "Unknown"
                        avatar = img_el.get_attribute('src') if img_el else ""

                        # 3. Provider logic: "pragmaticexternal-Sweet-Bonanza1000" -> "Pragmatic"
                        provider = "Unknown"
                        if '-' in slug:
                            # Take first part, remove 'external'
                            raw_provider = slug.split('-')[0].replace('external', '')
                            # Capitalize nicely
                            provider = raw_provider.capitalize()

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

            # 4. Handle "Load More" Button
            # Duelbits uses a button that often contains "Load More" text or specific styles classes
            # We look for a button that is visible and contains 'loadMore' in class or text
            load_more = page.locator('button:has-text("Load More"), button[class*="loadMore"]').first

            if load_more.is_visible():
                print(f"--- Clicking 'Load More' (Total seen: {len(synced_slugs)}) ---")
                load_more.scroll_into_view_if_needed()
                load_more.click()
                time.sleep(3)  # Wait for new items to load
            else:
                # Try a page scroll to trigger lazy loading if button isn't immediately visible
                page.mouse.wheel(0, 1000)
                time.sleep(2)

                # Check again after scroll
                if not load_more.is_visible():
                    print(">>> No more 'Load More' button found.")
                    break

            if len(synced_slugs) > 10000: break

        browser.close()
        print(f"\n>>> Scrape Complete for Duelbits. Total: {len(synced_slugs)}")


if __name__ == "__main__":
    run()