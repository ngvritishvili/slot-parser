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
    """Converts 'Frozen Gems' to 'frozen-gems' and removes special chars like ™"""
    text = text.lower().strip()
    # Remove ™, ®, and other non-alphanumeric except spaces/hyphens
    text = re.sub(r'[^\w\s-]', '', text)
    # Replace spaces with hyphens
    text = re.sub(r'[\s_-]+', '-', text)
    return text.strip('-')


def sync_to_laravel(slots_data):
    if not slots_data: return False
    print(f"   [API] Syncing {len(slots_data)} new slots...")
    try:
        response = requests.post(API_ENDPOINT, json=slots_data, timeout=120)
        if response.status_code == 200:
            res = response.json()
            details = res.get('details', {})
            new = details.get('new_links_added', 0)
            skipped = details.get('existing_links_skipped', 0)
            print(f"   [SUCCESS] New: {new}, Skipped: {skipped}")
            return True
    except Exception as e:
        print(f"   [API ERROR] {e}")
    return False


def run():
    with sync_playwright() as p:
        # Added extra arguments to look more 'human'
        browser = p.chromium.launch(headless=IS_HEADLESS, args=[
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-setuid-sandbox"
        ])

        # Use a realistic User Agent
        context = browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )

        page = context.new_page()
        Stealth().apply_stealth_sync(page)

        print(f">>> Opening {TARGET_URL}")
        try:
            page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=60000)

            # 1. WAITING FOR COOKIES / MODALS
            print("   Waiting 5s for potential modals...")
            time.sleep(5)

            # Click "Accept" if any button contains that text
            try:
                accept_btn = page.get_by_role("button",
                                              name=re.compile("Accept|Agree|Allow|Confirm|Got it", re.I)).first
                if accept_btn.is_visible():
                    print("   Clicking Consent Button...")
                    accept_btn.click()
                    time.sleep(3)
            except:
                pass

            # 2. Wait for the actual game container to exist
            print("   Searching for game rows...")
            page.wait_for_selector('[data-testid$="-games-0"]', timeout=30000)

        except Exception as e:
            print(f"!!! Wait issue (proceeding anyway): {e}")
            page.screenshot(path="casumo_debug.png")

        synced_titles = set()

        # Vertical discovery loop
        for v_step in range(20):
            # Selector matches trendingNow-games-0, gameOfWeek-games-1, etc.
            items = page.query_selector_all('div[data-testid*="-games-"]')
            new_batch = []

            for item in items:
                try:
                    img_el = item.query_selector('img')
                    if not img_el: continue

                    raw_title = img_el.get_attribute('alt') or ""
                    if not raw_title or raw_title in synced_titles:
                        continue

                    # Provider: in the div with bg-purple-60
                    provider_el = item.query_selector('.bg-purple-60')
                    provider = provider_el.inner_text().strip() if provider_el else "Unknown"

                    # URL: row/play/slug
                    slug = slugify(raw_title)
                    game_url = f"https://www.casumo.com/row/play/{slug}/"

                    avatar = img_el.get_attribute('src') or ""

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

            # Scroll down to load more categories
            page.mouse.wheel(0, 1200)
            time.sleep(2.5)

            if len(synced_titles) > 10000: break

        browser.close()
        print(f"\n>>> Scrape Complete. Total: {len(synced_titles)}")


if __name__ == "__main__":
    run()