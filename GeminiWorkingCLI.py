import os
import mysql.connector
import time
import re
import sys
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

# --- DEBUG: Initial Start ---
print(">>> Script starting...")

# 1. Load the .env file
if not os.path.exists('.env'):
    print(">>> ERROR: .env file not found in current directory!")
else:
    print(">>> .env file detected.")

load_dotenv()

# 2. Access variables with validation
try:
    DB_CONFIG = {
        'host': os.getenv('DB_HOST', '127.0.0.1'),
        'database': os.getenv('DB_NAME'),
        'user': os.getenv('DB_USER'),
        'password': os.getenv('DB_PASS')
    }

    # Check if critical DB variables are missing
    for key, val in DB_CONFIG.items():
        if not val:
            print(f">>> WARNING: DB parameter '{key}' is empty in .env")

    MAX_PAGES = int(os.getenv('MAX_PAGES', 160))
    IS_HEADLESS = os.getenv('HEADLESS', 'True').lower() == 'true'
    print(f">>> Config Loaded: DB={DB_CONFIG['database']}, Pages={MAX_PAGES}, Headless={IS_HEADLESS}")

except Exception as e:
    print(f">>> CRITICAL ERROR during config load: {e}")
    sys.exit(1)

BASE_URL = "https://sportsbet.io"
CATEGORY_URL = "https://sportsbet.io/casino/categories/video-slots"


def slugify(text):
    text = text.lower()
    return re.sub(r'[^a-z0-9]+', '-', text).strip('-')


def save_to_db(slots_data):
    try:
        print(f"   [DB] Connecting to {DB_CONFIG['host']}...")
        conn = mysql.connector.connect(**DB_CONFIG)
        cursor = conn.cursor()

        for item in slots_data:
            # Sync Provider
            provider_name = item['provider']
            cursor.execute("SELECT id FROM providers WHERE name = %s", (provider_name,))
            provider_row = cursor.fetchone()

            if not provider_row:
                cursor.execute(
                    "INSERT INTO providers (name, slug, created_at, updated_at) VALUES (%s, %s, NOW(), NOW())",
                    (provider_name, slugify(provider_name))
                )
                provider_id = cursor.lastrowid
            else:
                provider_id = provider_row[0]

            # Sync Slot
            query = """
                INSERT IGNORE INTO slots (provider_id, title, url, avatar, slug, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, NOW(), NOW())
            """
            slot_slug = slugify(item['title'])
            values = (provider_id, item['title'], item['url'], item['avatar'], slot_slug)
            cursor.execute(query, values)

        conn.commit()
        print(f"   [DB] Batch of {len(slots_data)} slots saved.")
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"   [DB ERROR] {e}")


def scrape_page(p, page_number):
    print(f">>> Launching browser for Page {page_number}...")
    browser = p.chromium.launch(headless=IS_HEADLESS)
    context = browser.new_context(viewport={'width': 1920, 'height': 1080})
    page = context.new_page()

    stealth = Stealth()
    stealth.apply_stealth_sync(page)

    target_url = f"{CATEGORY_URL}?page={page_number}"
    print(f"--- Processing Page {page_number} ---")

    try:
        print(f"   [Web] Navigating to {target_url}...")
        page.goto(target_url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(5000)

        # Scrape logic (simplified for debug)
        slot_divs = page.query_selector_all('div.relative.flex.cursor-pointer.flex-col')
        print(f"   [Web] Found {len(slot_divs)} potential slot containers.")

        # ... (rest of your extract_slots logic here) ...

        return True
    except Exception as e:
        print(f"   [Web ERROR] {e}")
        return False
    finally:
        browser.close()


def run():
    print(">>> Entering Playwright loop...")
    try:
        with sync_playwright() as p:
            current_page = 1
            while current_page <= MAX_PAGES:
                success = scrape_page(p, current_page)
                if not success:
                    print(f">>> Stopping: Page {current_page} failed or returned no results.")
                    break
                current_page += 1
                time.sleep(2)
    except Exception as e:
        print(f">>> CRITICAL loop error: {e}")


if __name__ == "__main__":
    run()
    print(">>> Script finished.")