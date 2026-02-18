import os
import time
import requests
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

load_dotenv()

# --- CONFIGURATION ---
CASINO_NAME = "CasinoGrounds"  # Static source name
API_ENDPOINT = os.getenv('API_ENDPOINT', 'http://checkthisone.online/api/slots/sync')
IS_HEADLESS = os.getenv('HEADLESS', 'True').lower() == 'true'
TARGET_URL = "https://casinogrounds.com/slots/"


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
        page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=60000)

        synced_titles = set()

        while True:
            # 1. Wait for game cards using data-testid
            page.wait_for_selector('[data-testid^="game-card-"]', timeout=30000)

            # 2. Extract visible slots
            # We target the main card containers
            cards = page.query_selector_all('[data-testid^="game-card-"]')
            # Filter out elements that aren't the main containers (like actions/images)
            card_containers = [c for c in cards if "-" not in c.get_attribute('data-testid').replace('game-card-', '')]

            new_batch = []

            for card in card_containers:
                try:
                    # Use the specific data-testid child elements from your HTML snippet
                    title_el = card.query_selector('[data-testid$="-title"]')
                    title = title_el.inner_text().strip() if title_el else ""

                    if title and title not in synced_titles:
                        provider_el = card.query_selector('[data-testid$="-provider"]')
                        provider = provider_el.inner_text().strip() if provider_el else "Unknown"

                        img_el = card.query_selector('img[data-testid$="-image"]')
                        avatar = img_el.get_attribute('src') if img_el else ""

                        new_batch.append({
                            "title": title,
                            "provider": provider,
                            "url": TARGET_URL,  # Cards don't always have direct links in the snippet
                            "avatar": avatar,
                            "casino_name": CASINO_NAME
                        })
                        synced_titles.add(title)
                except:
                    continue

            # 3. Sync to Laravel
            if new_batch:
                sync_to_laravel(new_batch)

            # 4. Handle "Load More"
            # Using the specific text and uppercase requirement from your snippet
            load_more = page.locator('button:has-text("Load More")')

            if load_more.is_visible():
                print(f"--- Clicking 'Load More' (Total seen: {len(synced_titles)}) ---")
                load_more.scroll_into_view_if_needed()
                load_more.click()

                # Wait for Next.js to append new items to the DOM
                time.sleep(3)
            else:
                print(">>> Reached the end of the list.")
                break

            # Safety break
            if len(synced_titles) > 5000: break

        browser.close()
        print(f"\n>>> Scrape Complete. Total: {len(synced_titles)}")


if __name__ == "__main__":
    run()