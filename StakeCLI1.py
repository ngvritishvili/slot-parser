import os
import time
import requests
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

load_dotenv()

# --- CONFIGURATION ---
CASINO_NAME = "Stake"
API_ENDPOINT = os.getenv('API_ENDPOINT', 'http://checkthisone.online/api/slots/sync')
IS_HEADLESS = os.getenv('HEADLESS', 'True').lower() == 'true'
TARGET_URL = "https://stake.com/casino/group/slots"
BASE_URL = "https://stake.com"


def sync_to_laravel(slots_data):
    if not slots_data: return False
    print(f"   [API] Syncing {len(slots_data)} new slots...")
    try:
        response = requests.post(API_ENDPOINT, json=slots_data, timeout=120)
        return response.status_code == 200
    except Exception as e:
        print(f"   [API ERROR] {e}")
        return False


def run():
    with sync_playwright() as p:
        # Stake is VERY sensitive. We use extra arguments to hide the automation.
        browser = p.chromium.launch(
            headless=IS_HEADLESS,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-setuid-sandbox"
            ]
        )
        # Randomize User Agent to look less like a server
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            viewport={'width': 1920, 'height': 1080}
        )
        page = context.new_page()
        Stealth().apply_stealth_sync(page)

        print(f">>> Opening {TARGET_URL}")

        try:
            # Use 'domcontentloaded' - Stake is too heavy for 'networkidle'
            page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=60000)

            # Look for the grid. If it fails, take a screenshot of the blocker.
            print("   Waiting for initial grid load...")
            page.wait_for_selector('a[href*="/casino/games/"]', timeout=30000)

        except Exception as e:
            print(f"!!! Selector Timeout. Saving debug screenshot to 'stake_error.png'")
            page.screenshot(path="stake_error.png")
            print("!!! Check stake_error.png to see if Cloudflare is blocking you.")
            browser.close()
            return

        synced_ids = set()

        while True:
            # Scroll a bit to trigger rendering
            page.evaluate("window.scrollBy(0, 500)")
            time.sleep(1)

            items = page.query_selector_all('a[href*="/casino/games/"]')
            new_batch = []

            for item in items:
                try:
                    url_path = item.get_attribute('href')
                    game_id = url_path.split('/')[-1] if url_path else ""

                    if game_id and game_id not in synced_ids:
                        img_el = item.query_selector('img')
                        title = img_el.get_attribute('alt') if img_el else "Unknown"

                        # Provider extraction
                        provider = "Unknown"
                        provider_el = item.query_selector('p, span.provider-name, strong')
                        if provider_el:
                            provider = provider_el.inner_text().strip()

                        avatar = img_el.get_attribute('src') if img_el else ""

                        new_batch.append({
                            "title": title,
                            "provider": provider,
                            "url": f"{BASE_URL}{url_path}",
                            "avatar": avatar,
                            "casino_name": CASINO_NAME
                        })
                        synced_ids.add(game_id)
                except:
                    continue

            if new_batch:
                sync_to_laravel(new_batch)

            # Stake "Load More" button is usually in a div with .contents
            load_more = page.locator('button:has-text("Load More")')

            if load_more.is_visible():
                print(f"--- Clicking 'Load More' (Total: {len(synced_ids)}) ---")
                load_more.click()
                time.sleep(3)
            else:
                # Try one deep scroll to see if it appears
                page.keyboard.press("End")
                time.sleep(2)
                if not load_more.is_visible():
                    break

        browser.close()
        print(f">>> Done. Total: {len(synced_ids)}")


if __name__ == "__main__":
    run()